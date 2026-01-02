"""
Analytics service for detailed call instrumentation and analysis.

Captures granular timing data at each pipeline stage to enable:
- Latency breakdown analysis (silence detection, STT, LLM, TTS)
- Quality issue detection (echo, low confidence, interruptions)
- Turn-by-turn and call-level metrics computation

Events are streamed to JSONL files for durability and computed into
summaries when calls end.
"""
import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path
from typing import Optional, Any

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

ANALYTICS_DIR = Path("/app/data/analytics")
CONFIDENCE_THRESHOLD = 0.80
SLOW_RESPONSE_THRESHOLD_MS = 4000
LONG_SILENCE_THRESHOLD_MS = 5000
ECHO_SIMILARITY_THRESHOLD = 0.60
REPEAT_SIMILARITY_THRESHOLD = 0.80


# =============================================================================
# EVENT TYPES
# =============================================================================

class EventType(str, Enum):
    """All possible event types in the call pipeline."""
    
    # Call lifecycle
    CALL_STARTED = "call_started"
    STREAM_CONNECTED = "stream_connected"
    GREETING_STARTED = "greeting_started"
    GREETING_COMPLETED = "greeting_completed"
    CALL_ENDED = "call_ended"
    
    # Audio input
    SPEECH_STARTED = "speech_started"
    SPEECH_CHUNK = "speech_chunk"
    SILENCE_DETECTED = "silence_detected"
    
    # Processing
    WHISPER_STARTED = "whisper_started"
    WHISPER_COMPLETED = "whisper_completed"
    WHISPER_FAILED = "whisper_failed"
    CLAUDE_STARTED = "claude_started"
    CLAUDE_COMPLETED = "claude_completed"
    CLAUDE_FAILED = "claude_failed"
    TTS_STARTED = "tts_started"
    TTS_COMPLETED = "tts_completed"
    TTS_FAILED = "tts_failed"
    
    # Output
    PLAYBACK_STARTED = "playback_started"
    PLAYBACK_CHUNK = "playback_chunk"
    PLAYBACK_COMPLETED = "playback_completed"
    MARK_RECEIVED = "mark_received"
    
    # Quality/Anomaly
    ECHO_DETECTED = "echo_detected"
    INTERRUPT_DETECTED = "interrupt_detected"
    REPEAT_DETECTED = "repeat_detected"
    LOW_CONFIDENCE = "low_confidence"
    LONG_SILENCE = "long_silence"


class QualityFlag(str, Enum):
    """Quality flags that can be attached to turns."""
    ECHO = "ECHO"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    SLOW_RESPONSE = "SLOW_RESPONSE"
    INTERRUPTED = "INTERRUPTED"
    REPEAT = "REPEAT"
    LONG_PAUSE = "LONG_PAUSE"
    TRANSCRIPTION_EMPTY = "TRANSCRIPTION_EMPTY"
    API_RETRY = "API_RETRY"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class Event:
    """A single instrumentation event."""
    id: str
    type: str
    timestamp: str
    turn_index: Optional[int]
    data: dict
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class LatencyBreakdown:
    """Latency metrics for a single turn."""
    total_ms: int = 0
    silence_detection_ms: int = 0
    whisper_ms: int = 0
    claude_ms: int = 0
    tts_ms: int = 0
    overhead_ms: int = 0
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TurnMetrics:
    """Computed metrics for a conversation turn."""
    turn_index: int
    speaker: str  # "caller" or "ai"
    started_at: str
    ended_at: str
    
    # Input
    transcript: str = ""
    anchor_words: list = field(default_factory=list)
    audio_duration_ms: int = 0
    speech_duration_ms: int = 0
    confidence: float = 0.0
    
    # Output
    response: str = ""
    response_anchor_words: list = field(default_factory=list)
    response_audio_duration_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    
    # Latency
    latency: LatencyBreakdown = field(default_factory=LatencyBreakdown)
    
    # Quality
    flags: list = field(default_factory=list)
    
    def to_dict(self) -> dict:
        d = asdict(self)
        d['latency'] = self.latency.to_dict()
        return d


@dataclass
class CallAnalytics:
    """Aggregate analytics for a complete call."""
    call_sid: str
    caller: str
    called: str
    started_at: str
    ended_at: str
    duration_seconds: int
    status: str
    
    # Summary
    total_turns: int = 0
    caller_turns: int = 0
    ai_turns: int = 0
    total_talk_time_ms: int = 0
    total_silence_time_ms: int = 0
    
    # Latency
    avg_total_ms: int = 0
    avg_whisper_ms: int = 0
    avg_claude_ms: int = 0
    avg_tts_ms: int = 0
    p95_total_ms: int = 0
    slowest_turn: int = 0
    slowest_component: str = ""
    
    # Quality
    avg_whisper_confidence: float = 0.0
    low_confidence_turns: list = field(default_factory=list)
    echo_events: int = 0
    interruptions: int = 0
    repeats: int = 0
    flags_summary: dict = field(default_factory=dict)
    
    # Tokens
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    avg_response_tokens: int = 0
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CallSession:
    """In-memory state for an active call being instrumented."""
    call_sid: str
    caller: str
    called: str
    started_at: datetime
    
    events: list = field(default_factory=list)
    event_counter: int = 0
    current_turn_index: int = 0
    
    # Recent AI outputs for echo detection
    recent_ai_outputs: list = field(default_factory=list)
    
    # Recent caller transcripts for repeat detection
    recent_caller_transcripts: list = field(default_factory=list)
    
    # Timing trackers for current turn
    turn_start_time: Optional[datetime] = None
    speech_start_time: Optional[datetime] = None
    silence_detected_time: Optional[datetime] = None
    whisper_start_time: Optional[datetime] = None
    claude_start_time: Optional[datetime] = None
    tts_start_time: Optional[datetime] = None
    playback_start_time: Optional[datetime] = None


# =============================================================================
# ANALYTICS SERVICE
# =============================================================================

class AnalyticsService:
    """
    Service for capturing and analysing call instrumentation data.
    
    Usage:
        analytics = get_analytics_service()
        
        # Start tracking a call
        analytics.start_call(call_sid, caller, called)
        
        # Emit events during pipeline
        await analytics.emit(call_sid, EventType.WHISPER_STARTED, {...})
        await analytics.emit(call_sid, EventType.WHISPER_COMPLETED, {...})
        
        # End call and compute analytics
        summary = analytics.end_call(call_sid)
    """
    
    def __init__(self):
        self._sessions: dict[str, CallSession] = {}
        self._broadcaster = None  # Set via set_broadcaster()
        
        # Ensure analytics directory exists
        ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
        
        logger.info("AnalyticsService initialized")
    
    def set_broadcaster(self, broadcaster):
        """Set the dashboard broadcaster for real-time updates."""
        self._broadcaster = broadcaster
    
    # -------------------------------------------------------------------------
    # Call Lifecycle
    # -------------------------------------------------------------------------
    
    def start_call(self, call_sid: str, caller: str, called: str) -> CallSession:
        """
        Start tracking a new call.
        
        Creates the analytics directory and initializes the event stream.
        """
        session = CallSession(
            call_sid=call_sid,
            caller=caller,
            called=called,
            started_at=datetime.now()
        )
        
        self._sessions[call_sid] = session
        
        # Create call analytics directory
        call_dir = ANALYTICS_DIR / call_sid
        call_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"📊 Started analytics for call {call_sid}")
        
        return session
    
    def get_session(self, call_sid: str) -> Optional[CallSession]:
        """Get the session for an active call."""
        return self._sessions.get(call_sid)
    
    def end_call(self, call_sid: str, reason: str = "normal") -> Optional[dict]:
        """
        End tracking for a call and compute final analytics.
        
        Returns the computed analytics summary.
        """
        session = self._sessions.pop(call_sid, None)
        if not session:
            logger.warning(f"No analytics session found for call {call_sid}")
            return None
        
        ended_at = datetime.now()
        duration_seconds = int((ended_at - session.started_at).total_seconds())
        
        # Emit final event
        self._emit_sync(session, EventType.CALL_ENDED, {
            "reason": reason,
            "total_turns": session.current_turn_index
        })
        
        # Compute turn metrics
        turns = self._compute_turns(session)
        
        # Compute call analytics
        analytics = self._compute_call_analytics(
            session, turns, ended_at, duration_seconds
        )
        
        # Save computed data
        self._save_turns(call_sid, turns)
        self._save_analytics(call_sid, analytics)
        
        logger.info(f"📊 Completed analytics for call {call_sid}: {len(turns)} turns, avg latency {analytics.avg_total_ms}ms")
        
        return analytics.to_dict()
    
    # -------------------------------------------------------------------------
    # Event Emission
    # -------------------------------------------------------------------------
    
    async def emit(
        self,
        call_sid: str,
        event_type: EventType,
        data: dict = None,
        turn_index: Optional[int] = None
    ) -> Optional[Event]:
        """
        Emit an instrumentation event.
        
        Events are:
        1. Added to in-memory list
        2. Appended to JSONL file
        3. Broadcast to dashboard (if connected)
        """
        session = self._sessions.get(call_sid)
        if not session:
            logger.warning(f"Cannot emit event: no session for {call_sid}")
            return None
        
        event = self._emit_sync(session, event_type, data or {}, turn_index)
        
        # Broadcast to dashboard
        if self._broadcaster:
            try:
                await self._broadcaster.analytics_event(call_sid, event.to_dict())
            except Exception as e:
                logger.debug(f"Failed to broadcast event: {e}")
        
        return event
    
    def _emit_sync(
        self,
        session: CallSession,
        event_type: EventType,
        data: dict,
        turn_index: Optional[int] = None
    ) -> Event:
        """Synchronous event emission (internal use)."""
        event = Event(
            id=f"evt_{session.event_counter:04d}",
            type=event_type.value if isinstance(event_type, EventType) else event_type,
            timestamp=datetime.now().isoformat(),
            turn_index=turn_index if turn_index is not None else session.current_turn_index,
            data=data
        )
        
        session.events.append(event)
        session.event_counter += 1
        
        # Append to JSONL file
        self._append_event(session.call_sid, event)
        
        return event
    
    def _append_event(self, call_sid: str, event: Event):
        """Append event to JSONL file."""
        filepath = ANALYTICS_DIR / call_sid / "events.jsonl"
        try:
            with open(filepath, "a") as f:
                f.write(event.to_json() + "\n")
        except Exception as e:
            logger.error(f"Failed to write event to {filepath}: {e}")
    
    # -------------------------------------------------------------------------
    # High-Level Instrumentation Helpers
    # -------------------------------------------------------------------------
    
    def start_turn(self, call_sid: str) -> int:
        """
        Mark the start of a new conversation turn.
        
        Returns the turn index.
        """
        session = self._sessions.get(call_sid)
        if not session:
            return 0
        
        session.current_turn_index += 1
        session.turn_start_time = datetime.now()
        
        # Reset timing trackers
        session.speech_start_time = None
        session.silence_detected_time = None
        session.whisper_start_time = None
        session.claude_start_time = None
        session.tts_start_time = None
        session.playback_start_time = None
        
        return session.current_turn_index
    
    async def speech_started(self, call_sid: str, rms_level: int = 0):
        """Mark when caller speech is detected."""
        session = self._sessions.get(call_sid)
        if session:
            session.speech_start_time = datetime.now()
        
        await self.emit(call_sid, EventType.SPEECH_STARTED, {
            "rms_level": rms_level
        })
    
    async def silence_detected(
        self,
        call_sid: str,
        speech_duration_ms: int,
        audio_bytes: int,
        peak_rms: int = 0
    ):
        """Mark when silence is detected (end of speech)."""
        session = self._sessions.get(call_sid)
        if session:
            session.silence_detected_time = datetime.now()
        
        await self.emit(call_sid, EventType.SILENCE_DETECTED, {
            "speech_duration_ms": speech_duration_ms,
            "audio_bytes": audio_bytes,
            "peak_rms": peak_rms
        })
    
    async def whisper_started(self, call_sid: str, audio_bytes: int, audio_duration_ms: int = 0):
        """Mark Whisper API call start."""
        session = self._sessions.get(call_sid)
        if session:
            session.whisper_start_time = datetime.now()
        
        await self.emit(call_sid, EventType.WHISPER_STARTED, {
            "audio_bytes": audio_bytes,
            "audio_duration_ms": audio_duration_ms
        })
    
    async def whisper_completed(
        self,
        call_sid: str,
        transcript: str,
        duration_ms: int,
        confidence: float = 0.0,
        language: str = "it"
    ):
        """
        Mark Whisper completion and check for quality issues.
        
        Automatically detects:
        - Low confidence transcriptions
        - Echo (transcript matches recent AI output)
        - Repeats (transcript matches recent caller input)
        """
        session = self._sessions.get(call_sid)
        
        await self.emit(call_sid, EventType.WHISPER_COMPLETED, {
            "transcript": transcript,
            "duration_ms": duration_ms,
            "confidence": confidence,
            "language": language
        })
        
        if not session:
            return
        
        # Check for low confidence
        if confidence > 0 and confidence < CONFIDENCE_THRESHOLD:
            await self.emit(call_sid, EventType.LOW_CONFIDENCE, {
                "confidence": confidence,
                "threshold": CONFIDENCE_THRESHOLD
            })
        
        # Check for echo
        if session.recent_ai_outputs:
            echo_score = self._check_echo(transcript, session.recent_ai_outputs)
            if echo_score >= ECHO_SIMILARITY_THRESHOLD:
                await self.emit(call_sid, EventType.ECHO_DETECTED, {
                    "similarity_score": echo_score,
                    "matched_text": transcript[:50]
                })
        
        # Check for repeat
        if session.recent_caller_transcripts:
            repeat_score, original_turn = self._check_repeat(
                transcript, session.recent_caller_transcripts
            )
            if repeat_score >= REPEAT_SIMILARITY_THRESHOLD:
                await self.emit(call_sid, EventType.REPEAT_DETECTED, {
                    "similarity_score": repeat_score,
                    "original_turn": original_turn
                })
        
        # Track for future repeat detection
        session.recent_caller_transcripts.append({
            "turn": session.current_turn_index,
            "text": transcript
        })
        # Keep last 5 turns
        session.recent_caller_transcripts = session.recent_caller_transcripts[-5:]
    
    async def whisper_failed(self, call_sid: str, error: str, retry_count: int = 0):
        """Mark Whisper API failure."""
        await self.emit(call_sid, EventType.WHISPER_FAILED, {
            "error": error,
            "retry_count": retry_count
        })
    
    async def claude_started(
        self,
        call_sid: str,
        input_tokens_estimate: int = 0,
        context_turns: int = 0
    ):
        """Mark Claude API call start."""
        session = self._sessions.get(call_sid)
        if session:
            session.claude_start_time = datetime.now()
        
        await self.emit(call_sid, EventType.CLAUDE_STARTED, {
            "input_tokens_estimate": input_tokens_estimate,
            "context_turns": context_turns
        })
    
    async def claude_completed(
        self,
        call_sid: str,
        response: str,
        duration_ms: int,
        input_tokens: int = 0,
        output_tokens: int = 0
    ):
        """Mark Claude completion and track output for echo detection."""
        session = self._sessions.get(call_sid)
        
        await self.emit(call_sid, EventType.CLAUDE_COMPLETED, {
            "response": response,
            "duration_ms": duration_ms,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens
        })
        
        # Track for echo detection
        if session:
            session.recent_ai_outputs.append(response)
            # Keep last 3 outputs
            session.recent_ai_outputs = session.recent_ai_outputs[-3:]
    
    async def claude_failed(self, call_sid: str, error: str, retry_count: int = 0):
        """Mark Claude API failure."""
        await self.emit(call_sid, EventType.CLAUDE_FAILED, {
            "error": error,
            "retry_count": retry_count
        })
    
    async def tts_started(self, call_sid: str, text: str, voice: str = "onyx"):
        """Mark TTS API call start."""
        session = self._sessions.get(call_sid)
        if session:
            session.tts_start_time = datetime.now()
        
        await self.emit(call_sid, EventType.TTS_STARTED, {
            "text": text[:100],  # Truncate for storage
            "text_length": len(text),
            "voice": voice
        })
    
    async def tts_completed(
        self,
        call_sid: str,
        duration_ms: int,
        audio_bytes: int,
        audio_duration_ms: int
    ):
        """Mark TTS completion."""
        await self.emit(call_sid, EventType.TTS_COMPLETED, {
            "duration_ms": duration_ms,
            "audio_bytes": audio_bytes,
            "audio_duration_ms": audio_duration_ms
        })
    
    async def tts_failed(self, call_sid: str, error: str):
        """Mark TTS failure."""
        await self.emit(call_sid, EventType.TTS_FAILED, {
            "error": error
        })
    
    async def playback_started(self, call_sid: str, expected_duration_ms: int = 0):
        """Mark start of audio playback to caller."""
        session = self._sessions.get(call_sid)
        if session:
            session.playback_start_time = datetime.now()
        
        await self.emit(call_sid, EventType.PLAYBACK_STARTED, {
            "expected_duration_ms": expected_duration_ms
        })
    
    async def playback_completed(self, call_sid: str, actual_duration_ms: int = 0):
        """Mark completion of audio playback."""
        await self.emit(call_sid, EventType.PLAYBACK_COMPLETED, {
            "actual_duration_ms": actual_duration_ms
        })
    
    async def interrupt_detected(
        self,
        call_sid: str,
        playback_progress_ms: int,
        interrupt_rms: int
    ):
        """Mark when caller audio is detected during AI playback."""
        await self.emit(call_sid, EventType.INTERRUPT_DETECTED, {
            "playback_progress_ms": playback_progress_ms,
            "interrupt_rms": interrupt_rms
        })
    
    # -------------------------------------------------------------------------
    # Quality Detection Helpers
    # -------------------------------------------------------------------------
    
    def _check_echo(self, transcript: str, recent_outputs: list) -> float:
        """
        Check if transcript is an echo of recent AI output.
        
        Returns similarity score (0-1).
        """
        transcript_clean = self._normalize_text(transcript)
        
        max_similarity = 0.0
        for output in recent_outputs:
            output_clean = self._normalize_text(output)
            similarity = SequenceMatcher(None, transcript_clean, output_clean).ratio()
            max_similarity = max(max_similarity, similarity)
        
        return max_similarity
    
    def _check_repeat(
        self,
        transcript: str,
        recent_transcripts: list
    ) -> tuple[float, Optional[int]]:
        """
        Check if transcript is a repeat of recent caller input.
        
        Returns (similarity_score, original_turn_index).
        """
        transcript_clean = self._normalize_text(transcript)
        
        max_similarity = 0.0
        original_turn = None
        
        for item in recent_transcripts:
            past_clean = self._normalize_text(item["text"])
            similarity = SequenceMatcher(None, transcript_clean, past_clean).ratio()
            if similarity > max_similarity:
                max_similarity = similarity
                original_turn = item["turn"]
        
        return max_similarity, original_turn
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text for comparison (lowercase, remove punctuation)."""
        text = text.lower()
        text = re.sub(r'[^\w\s]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    def _extract_anchor_words(self, text: str, max_words: int = 5) -> list:
        """
        Extract anchor words from text for quick scanning.
        
        Prioritizes: proper nouns, numbers, domain terms.
        """
        if not text:
            return []
        
        # Simple extraction: first N significant words
        words = text.split()
        
        # Filter out very common Italian words
        stop_words = {
            'il', 'la', 'lo', 'i', 'le', 'gli', 'un', 'una', 'uno',
            'di', 'a', 'da', 'in', 'con', 'su', 'per', 'tra', 'fra',
            'e', 'o', 'ma', 'se', 'che', 'non', 'mi', 'ti', 'ci', 'vi',
            'è', 'sono', 'ha', 'ho', 'si', 'sì', 'no', 'come', 'cosa',
            'del', 'della', 'dei', 'delle', 'al', 'alla', 'ai', 'alle'
        }
        
        anchors = []
        for word in words:
            word_clean = re.sub(r'[^\w]', '', word)
            if word_clean.lower() not in stop_words and len(word_clean) > 1:
                anchors.append(word_clean)
                if len(anchors) >= max_words:
                    break
        
        return anchors
    
    # -------------------------------------------------------------------------
    # Metrics Computation
    # -------------------------------------------------------------------------
    
    def _compute_turns(self, session: CallSession) -> list[TurnMetrics]:
        """
        Compute turn-level metrics from event stream.
        """
        turns = []
        events_by_turn: dict[int, list[Event]] = {}
        
        # Group events by turn
        for event in session.events:
            turn_idx = event.turn_index
            if turn_idx is not None:
                events_by_turn.setdefault(turn_idx, []).append(event)
        
        for turn_idx in sorted(events_by_turn.keys()):
            turn_events = events_by_turn[turn_idx]
            turn = self._compute_single_turn(turn_idx, turn_events)
            if turn:
                turns.append(turn)
        
        return turns
    
    def _compute_single_turn(
        self,
        turn_index: int,
        events: list[Event]
    ) -> Optional[TurnMetrics]:
        """Compute metrics for a single turn from its events."""
        if not events:
            return None
        
        # Initialize turn
        turn = TurnMetrics(
            turn_index=turn_index,
            speaker="ai" if turn_index == 0 else "caller",
            started_at=events[0].timestamp,
            ended_at=events[-1].timestamp
        )
        
        # Extract data from events
        whisper_start = None
        whisper_end = None
        claude_start = None
        claude_end = None
        tts_start = None
        tts_end = None
        silence_time = None
        
        for event in events:
            etype = event.type
            data = event.data
            
            if etype == EventType.SILENCE_DETECTED.value:
                silence_time = datetime.fromisoformat(event.timestamp)
                turn.speech_duration_ms = data.get("speech_duration_ms", 0)
            
            elif etype == EventType.WHISPER_STARTED.value:
                whisper_start = datetime.fromisoformat(event.timestamp)
            
            elif etype == EventType.WHISPER_COMPLETED.value:
                whisper_end = datetime.fromisoformat(event.timestamp)
                turn.transcript = data.get("transcript", "")
                turn.confidence = data.get("confidence", 0.0)
                turn.anchor_words = self._extract_anchor_words(turn.transcript)
            
            elif etype == EventType.CLAUDE_STARTED.value:
                claude_start = datetime.fromisoformat(event.timestamp)
            
            elif etype == EventType.CLAUDE_COMPLETED.value:
                claude_end = datetime.fromisoformat(event.timestamp)
                turn.response = data.get("response", "")
                turn.tokens_in = data.get("input_tokens", 0)
                turn.tokens_out = data.get("output_tokens", 0)
                turn.response_anchor_words = self._extract_anchor_words(turn.response)
            
            elif etype == EventType.TTS_STARTED.value:
                tts_start = datetime.fromisoformat(event.timestamp)
            
            elif etype == EventType.TTS_COMPLETED.value:
                tts_end = datetime.fromisoformat(event.timestamp)
                turn.response_audio_duration_ms = data.get("audio_duration_ms", 0)
            
            elif etype == EventType.LOW_CONFIDENCE.value:
                if QualityFlag.LOW_CONFIDENCE.value not in turn.flags:
                    turn.flags.append(QualityFlag.LOW_CONFIDENCE.value)
            
            elif etype == EventType.ECHO_DETECTED.value:
                if QualityFlag.ECHO.value not in turn.flags:
                    turn.flags.append(QualityFlag.ECHO.value)
            
            elif etype == EventType.REPEAT_DETECTED.value:
                if QualityFlag.REPEAT.value not in turn.flags:
                    turn.flags.append(QualityFlag.REPEAT.value)
            
            elif etype == EventType.INTERRUPT_DETECTED.value:
                if QualityFlag.INTERRUPTED.value not in turn.flags:
                    turn.flags.append(QualityFlag.INTERRUPTED.value)
        
        # Compute latency breakdown
        latency = LatencyBreakdown()
        
        if whisper_start and whisper_end:
            latency.whisper_ms = int((whisper_end - whisper_start).total_seconds() * 1000)
        
        if claude_start and claude_end:
            latency.claude_ms = int((claude_end - claude_start).total_seconds() * 1000)
        
        if tts_start and tts_end:
            latency.tts_ms = int((tts_end - tts_start).total_seconds() * 1000)
        
        # Silence detection latency (time from speech end to whisper start)
        if silence_time and whisper_start:
            latency.silence_detection_ms = int((whisper_start - silence_time).total_seconds() * 1000)
        
        # Total latency
        latency.total_ms = latency.whisper_ms + latency.claude_ms + latency.tts_ms
        latency.overhead_ms = max(0, latency.total_ms - latency.whisper_ms - latency.claude_ms - latency.tts_ms)
        
        turn.latency = latency
        
        # Check for slow response flag
        if latency.total_ms > SLOW_RESPONSE_THRESHOLD_MS:
            if QualityFlag.SLOW_RESPONSE.value not in turn.flags:
                turn.flags.append(QualityFlag.SLOW_RESPONSE.value)
        
        return turn
    
    def _compute_call_analytics(
        self,
        session: CallSession,
        turns: list[TurnMetrics],
        ended_at: datetime,
        duration_seconds: int
    ) -> CallAnalytics:
        """Compute call-level analytics from turns."""
        analytics = CallAnalytics(
            call_sid=session.call_sid,
            caller=session.caller,
            called=session.called,
            started_at=session.started_at.isoformat(),
            ended_at=ended_at.isoformat(),
            duration_seconds=duration_seconds,
            status="ended"
        )
        
        if not turns:
            return analytics
        
        # Summary counts
        analytics.total_turns = len(turns)
        analytics.caller_turns = sum(1 for t in turns if t.speaker == "caller")
        analytics.ai_turns = sum(1 for t in turns if t.speaker == "ai")
        
        # Latency stats (only for turns with actual latency)
        latencies = [t.latency.total_ms for t in turns if t.latency.total_ms > 0]
        whisper_latencies = [t.latency.whisper_ms for t in turns if t.latency.whisper_ms > 0]
        claude_latencies = [t.latency.claude_ms for t in turns if t.latency.claude_ms > 0]
        tts_latencies = [t.latency.tts_ms for t in turns if t.latency.tts_ms > 0]
        
        if latencies:
            analytics.avg_total_ms = int(sum(latencies) / len(latencies))
            sorted_latencies = sorted(latencies)
            p95_idx = int(len(sorted_latencies) * 0.95)
            analytics.p95_total_ms = sorted_latencies[min(p95_idx, len(sorted_latencies) - 1)]
            
            # Find slowest turn
            max_latency = max(latencies)
            for t in turns:
                if t.latency.total_ms == max_latency:
                    analytics.slowest_turn = t.turn_index
                    # Determine slowest component
                    components = {
                        "whisper": t.latency.whisper_ms,
                        "claude": t.latency.claude_ms,
                        "tts": t.latency.tts_ms
                    }
                    analytics.slowest_component = max(components, key=components.get)
                    break
        
        if whisper_latencies:
            analytics.avg_whisper_ms = int(sum(whisper_latencies) / len(whisper_latencies))
        
        if claude_latencies:
            analytics.avg_claude_ms = int(sum(claude_latencies) / len(claude_latencies))
        
        if tts_latencies:
            analytics.avg_tts_ms = int(sum(tts_latencies) / len(tts_latencies))
        
        # Quality stats
        confidences = [t.confidence for t in turns if t.confidence > 0]
        if confidences:
            analytics.avg_whisper_confidence = sum(confidences) / len(confidences)
        
        analytics.low_confidence_turns = [
            t.turn_index for t in turns
            if QualityFlag.LOW_CONFIDENCE.value in t.flags
        ]
        
        # Count flags
        flags_summary = {}
        for turn in turns:
            for flag in turn.flags:
                flags_summary[flag] = flags_summary.get(flag, 0) + 1
        
        analytics.flags_summary = flags_summary
        analytics.echo_events = flags_summary.get(QualityFlag.ECHO.value, 0)
        analytics.interruptions = flags_summary.get(QualityFlag.INTERRUPTED.value, 0)
        analytics.repeats = flags_summary.get(QualityFlag.REPEAT.value, 0)
        
        # Token stats
        analytics.total_input_tokens = sum(t.tokens_in for t in turns)
        analytics.total_output_tokens = sum(t.tokens_out for t in turns)
        output_turns = [t for t in turns if t.tokens_out > 0]
        if output_turns:
            analytics.avg_response_tokens = int(analytics.total_output_tokens / len(output_turns))
        
        return analytics
    
    # -------------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------------
    
    def _save_turns(self, call_sid: str, turns: list[TurnMetrics]):
        """Save computed turns to JSON file."""
        filepath = ANALYTICS_DIR / call_sid / "turns.json"
        try:
            with open(filepath, "w") as f:
                json.dump([t.to_dict() for t in turns], f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved turns to {filepath}")
        except Exception as e:
            logger.error(f"Failed to save turns: {e}")
    
    def _save_analytics(self, call_sid: str, analytics: CallAnalytics):
        """Save call analytics summary to JSON file."""
        filepath = ANALYTICS_DIR / call_sid / "summary.json"
        try:
            with open(filepath, "w") as f:
                json.dump(analytics.to_dict(), f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved analytics to {filepath}")
        except Exception as e:
            logger.error(f"Failed to save analytics: {e}")
    
    # -------------------------------------------------------------------------
    # Data Retrieval
    # -------------------------------------------------------------------------
    
    def list_calls(self, limit: int = 50) -> list[dict]:
        """
        List calls with analytics summaries.
        
        Returns most recent calls first.
        """
        calls = []
        
        if not ANALYTICS_DIR.exists():
            return calls
        
        # Get all call directories
        call_dirs = sorted(
            ANALYTICS_DIR.iterdir(),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )[:limit]
        
        for call_dir in call_dirs:
            if not call_dir.is_dir():
                continue
            
            summary_path = call_dir / "summary.json"
            if summary_path.exists():
                try:
                    with open(summary_path) as f:
                        summary = json.load(f)
                    
                    # Extract key fields for list view
                    calls.append({
                        "call_sid": summary.get("call_sid", call_dir.name),
                        "caller": summary.get("caller", ""),
                        "started_at": summary.get("started_at", ""),
                        "duration_seconds": summary.get("duration_seconds", 0),
                        "turns": summary.get("total_turns", 0),
                        "avg_latency_ms": summary.get("avg_total_ms", 0),
                        "quality_flags": list(summary.get("flags_summary", {}).keys())
                    })
                except Exception as e:
                    logger.error(f"Failed to read summary for {call_dir.name}: {e}")
        
        return calls
    
    def get_call(self, call_sid: str) -> Optional[dict]:
        """
        Get full analytics for a specific call.
        
        Returns events, turns, and summary.
        """
        call_dir = ANALYTICS_DIR / call_sid
        
        if not call_dir.exists():
            return None
        
        result = {"call_sid": call_sid}
        
        # Load events
        events_path = call_dir / "events.jsonl"
        if events_path.exists():
            events = []
            try:
                with open(events_path) as f:
                    for line in f:
                        if line.strip():
                            events.append(json.loads(line))
                result["events"] = events
            except Exception as e:
                logger.error(f"Failed to read events: {e}")
                result["events"] = []
        
        # Load turns
        turns_path = call_dir / "turns.json"
        if turns_path.exists():
            try:
                with open(turns_path) as f:
                    result["turns"] = json.load(f)
            except Exception as e:
                logger.error(f"Failed to read turns: {e}")
                result["turns"] = []
        
        # Load summary
        summary_path = call_dir / "summary.json"
        if summary_path.exists():
            try:
                with open(summary_path) as f:
                    result["analytics"] = json.load(f)
            except Exception as e:
                logger.error(f"Failed to read summary: {e}")
                result["analytics"] = {}
        
        return result
    
    def get_events(self, call_sid: str) -> list[dict]:
        """Get raw event stream for a call."""
        events_path = ANALYTICS_DIR / call_sid / "events.jsonl"
        
        if not events_path.exists():
            return []
        
        events = []
        try:
            with open(events_path) as f:
                for line in f:
                    if line.strip():
                        events.append(json.loads(line))
        except Exception as e:
            logger.error(f"Failed to read events: {e}")
        
        return events
    
    def get_aggregate_stats(self, days: int = 7) -> dict:
        """
        Get aggregate statistics across recent calls.
        
        Useful for identifying systemic issues.
        """
        calls = self.list_calls(limit=100)
        
        if not calls:
            return {
                "period_days": days,
                "total_calls": 0,
                "avg_latency_ms": 0,
                "common_flags": {}
            }
        
        # Aggregate metrics
        latencies = [c["avg_latency_ms"] for c in calls if c["avg_latency_ms"] > 0]
        
        all_flags = {}
        for call in calls:
            for flag in call.get("quality_flags", []):
                all_flags[flag] = all_flags.get(flag, 0) + 1
        
        return {
            "period_days": days,
            "total_calls": len(calls),
            "avg_latency_ms": int(sum(latencies) / len(latencies)) if latencies else 0,
            "common_flags": all_flags
        }


# =============================================================================
# SINGLETON
# =============================================================================

_analytics_service: Optional[AnalyticsService] = None


def get_analytics_service() -> AnalyticsService:
    """Get or create the analytics service singleton."""
    global _analytics_service
    if _analytics_service is None:
        _analytics_service = AnalyticsService()
    return _analytics_service