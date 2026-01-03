"""
Twilio webhook and WebSocket handlers for phone calls.
"""
import asyncio
import json
import logging
import os
import time
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream
from twilio.rest import Client as TwilioClient

from app.services.audio import (
    AudioBuffer, 
    base64_decode_audio, 
    prepare_audio_for_whisper,
    prepare_audio_for_twilio
)
from app.services.whisper import get_whisper_service
from app.services.tts import get_tts_service
from app.services.claude import get_claude_service
from app.services.knowledge import KnowledgeService
from app.services.analytics import get_analytics_service, EventType  # ðŸ“Š ANALYTICS

from app.routers.dashboard import broadcaster

router = APIRouter()
logger = logging.getLogger(__name__)

TRANSCRIPTS_DIR = "/app/data/transcripts"


def save_transcript(call_sid: str, call_data: dict):
    """Save call transcript to file for history."""
    import os
    
    os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
    filepath = os.path.join(TRANSCRIPTS_DIR, f"{call_sid}.json")
    
    try:
        with open(filepath, "w") as f:
            json.dump(call_data, f, indent=2, ensure_ascii=False)
        logger.info(f"ðŸ“ Saved transcript to {filepath}")
    except Exception as e:
        logger.error(f"Failed to save transcript: {e}")

# Track active calls
active_calls: dict[str, dict] = {}

# Phrases that indicate the AI is ending the conversation
GOODBYE_PHRASES = [
    "arrivederci",
    "buona giornata", 
    "buonasera",
    "a presto",
    "buon proseguimento",
    "alla prossima",
]


def is_goodbye(text: str) -> bool:
    """Check if text contains a goodbye phrase."""
    if not text:
        return False
    text_lower = text.lower()
    return any(phrase in text_lower for phrase in GOODBYE_PHRASES)


async def hangup_call(call_sid: str) -> bool:
    """
    Hang up a call using Twilio REST API.
    
    Called after the AI says goodbye to properly end the call.
    """
    try:
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        
        if not account_sid or not auth_token:
            logger.error("Twilio credentials not configured for hangup")
            return False
        
        client = TwilioClient(account_sid, auth_token)
        
        # Update call status to completed - this hangs up
        call = client.calls(call_sid).update(status="completed")
        logger.info(f"📞 Hung up call {call_sid}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to hang up call {call_sid}: {e}")
        return False


@router.post("/voice")
async def handle_incoming_call(request: Request):
    """Handle incoming voice call from Twilio."""
    form_data = await request.form()
    
    call_sid = form_data.get("CallSid", "unknown")
    caller = form_data.get("From", "Unknown")
    called = form_data.get("To", "Unknown")
    
    logger.info(f"ðŸ“ž Incoming call: {call_sid} from {caller} to {called}")
    
    # ðŸ“Š ANALYTICS: Start tracking this call
    analytics = get_analytics_service()
    analytics.start_call(call_sid, caller, called)
    await analytics.emit(call_sid, EventType.CALL_STARTED, {
        "caller": caller,
        "called": called
    }, turn_index=None)
    
    # Broadcast to dashboard
    await broadcaster.call_started(call_sid, caller, called)
    
    # Track the call (existing code)
    active_calls[call_sid] = {
        "caller": caller,
        "called": called,
        "started_at": datetime.now().isoformat(),
        "status": "ringing",
        "turns": []
    }
    
    # Build TwiML response
    response = VoiceResponse()
    
    # Brief pause before greeting (natural)
    response.pause(length=1)
    
    # Initial greeting using Twilio's TTS (fast, gets us started)
    # We'll switch to our own TTS once WebSocket is connected
    response.say(
        "Pronto. Un momento per favore.",
        voice="Google.it-IT-Wavenet-A",  # Good Italian voice
        language="it-IT"
    )
    
    # Connect to our WebSocket for bidirectional audio
    # Using the same hostname from the request
    host = request.headers.get("host", request.url.hostname)
    websocket_url = f"wss://{host}/api/twilio/stream"
    
    connect = Connect()
    stream = Stream(url=websocket_url)
    stream.parameter(name="call_sid", value=call_sid)
    stream.parameter(name="caller", value=caller)
    connect.append(stream)
    response.append(connect)
    
    logger.info(f"Connecting call {call_sid} to WebSocket: {websocket_url}")
    
    return PlainTextResponse(
        content=str(response),
        media_type="application/xml"
    )


@router.websocket("/stream")
async def media_stream(websocket: WebSocket):
    """Handle bidirectional audio stream from Twilio."""
    await websocket.accept()
    
    # Initialize services
    whisper = get_whisper_service()
    tts = get_tts_service()
    claude = get_claude_service()
    knowledge_service = KnowledgeService()
    knowledge_service.load()
    analytics = get_analytics_service()  # ðŸ“Š ANALYTICS
    
    # State for this call
    call_sid: Optional[str] = None
    caller: Optional[str] = None
    stream_sid: Optional[str] = None
    audio_buffer = AudioBuffer()
    
    processing_lock = asyncio.Lock()
    is_speaking = False
    speech_detected = False  # ðŸ“Š ANALYTICS: Track if we've emitted speech_started
    
    logger.info("WebSocket connection accepted")
    
    # ... (keep existing end_call function)
    
    async def send_audio_to_twilio(audio_data: bytes):
        """Send TTS audio back to the caller via Twilio."""
        nonlocal is_speaking
        
        if not stream_sid:
            return
        
        is_speaking = True
        
        # ðŸ“Š ANALYTICS: Track playback
        playback_start = time.time()
        audio_duration_ms = int(len(audio_data) / 24 / 2)  # Estimate from 24kHz 16-bit
        await analytics.playback_started(call_sid, expected_duration_ms=audio_duration_ms)
        
        try:
            b64_audio = prepare_audio_for_twilio(audio_data, source_rate=24000)
            chunk_size = 640
            
            for i in range(0, len(b64_audio), chunk_size):
                chunk = b64_audio[i:i + chunk_size]
                message = {
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": chunk}
                }
                await websocket.send_text(json.dumps(message))
                await asyncio.sleep(0.02)
            
            # ðŸ“Š ANALYTICS: Playback completed
            playback_duration = int((time.time() - playback_start) * 1000)
            await analytics.playback_completed(call_sid, actual_duration_ms=playback_duration)
            
        except Exception as e:
            logger.error(f"Error sending audio: {e}")
        finally:
            is_speaking = False
    
    async def process_speech(audio_data: bytes):
        """Process a complete speech segment."""
        nonlocal speech_detected
        
        async with processing_lock:
            if not call_sid:
                return
            
            # ðŸ“Š ANALYTICS: Start new turn and mark silence detected
            turn_index = analytics.start_turn(call_sid)
            speech_duration_ms = int(len(audio_data) / 8)  # Estimate from 8kHz
            await analytics.silence_detected(
                call_sid,
                speech_duration_ms=speech_duration_ms,
                audio_bytes=len(audio_data)
            )
            speech_detected = False  # Reset for next utterance
            
            await broadcaster.processing_status(call_sid, "processing")
            
            # 1. Prepare audio for Whisper
            wav_audio = prepare_audio_for_whisper(audio_data)
            
            # ðŸ“Š ANALYTICS: Whisper started
            whisper_start = time.time()
            await analytics.whisper_started(
                call_sid,
                audio_bytes=len(wav_audio),
                audio_duration_ms=speech_duration_ms
            )
            
            # 2. Transcribe with Whisper
            transcript = await whisper.transcribe(wav_audio)
            
            # ðŸ“Š ANALYTICS: Whisper completed
            whisper_duration = int((time.time() - whisper_start) * 1000)
            confidence = getattr(whisper, 'last_confidence', 0.0)  # If available
            await analytics.whisper_completed(
                call_sid,
                transcript=transcript or "",
                duration_ms=whisper_duration,
                confidence=confidence
            )
            
            if not transcript or not transcript.strip():
                await broadcaster.processing_status(call_sid, "listening")
                return
            
            logger.info(f"ðŸŽ¤ Caller said: {transcript}")
            
            # Broadcast caller transcript
            await broadcaster.transcript_update(call_sid, "caller", transcript, turn_index)
            
            # Track caller turn
            if call_sid in active_calls:
                active_calls[call_sid]["turns"].append({
                    "speaker": "caller",
                    "text": transcript,
                    "timestamp": datetime.now().isoformat()
                })
            
            # ðŸ“Š ANALYTICS: Claude started
            claude_start = time.time()
            context_turns = len(claude.get_conversation(call_sid).history) if claude.get_conversation(call_sid) else 0
            await analytics.claude_started(
                call_sid,
                input_tokens_estimate=context_turns * 50,  # Rough estimate
                context_turns=context_turns
            )
            
            # 3. Get Claude response
            response_text = await claude.respond(call_sid, transcript)
            
            # ðŸ“Š ANALYTICS: Claude completed with accurate token counts
            claude_duration = int((time.time() - claude_start) * 1000)
            usage = claude.last_usage
            await analytics.claude_completed(
                call_sid,
                response=response_text or "",
                duration_ms=claude_duration,
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"]
            )
            
            if not response_text:
                await broadcaster.processing_status(call_sid, "listening")
                return
            
            logger.info(f"ðŸ¤– AI response: {response_text}")
            
            # Calculate latency and broadcast
            latency_ms = whisper_duration + claude_duration
            await broadcaster.transcript_update(call_sid, "ai", response_text, turn_index, latency_ms)
            
            # Track AI turn
            if call_sid in active_calls:
                active_calls[call_sid]["turns"].append({
                    "speaker": "ai",
                    "text": response_text,
                    "timestamp": datetime.now().isoformat(),
                    "latency_ms": latency_ms
                })
            
            # ðŸ“Š ANALYTICS: TTS started
            tts_start = time.time()
            await analytics.tts_started(call_sid, text=response_text)
            
            # 4. Generate TTS audio
            await broadcaster.processing_status(call_sid, "speaking")
            audio_response = await tts.synthesize(response_text)
            
            # ðŸ“Š ANALYTICS: TTS completed
            tts_duration = int((time.time() - tts_start) * 1000)
            if audio_response:
                audio_duration_ms = int(len(audio_response) / 24 / 2)  # 24kHz 16-bit estimate
                await analytics.tts_completed(
                    call_sid,
                    duration_ms=tts_duration,
                    audio_bytes=len(audio_response),
                    audio_duration_ms=audio_duration_ms
                )
            else:
                await analytics.tts_failed(call_sid, error="TTS returned empty audio")
            
            if not audio_response:
                return
            
            # 5. Send audio to caller
            await send_audio_to_twilio(audio_response)
            
            await broadcaster.processing_status(call_sid, "listening")
            
            # 6. Check for goodbye - if AI said farewell, hang up after audio plays
            if is_goodbye(response_text):
                logger.info(f"👋 Goodbye detected in AI response, hanging up call {call_sid}")
                # Wait for audio to actually play to the caller
                # audio_duration_ms was calculated earlier from the TTS response
                wait_time = (audio_duration_ms / 1000) + 0.5  # Add 0.5s buffer
                logger.info(f"⏳ Waiting {wait_time:.1f}s for goodbye audio to play")
                await asyncio.sleep(wait_time)
                await hangup_call(call_sid)
                return  # Exit process_speech, call is ending
    
    try:
        async for message in websocket.iter_text():
            try:
                data = json.loads(message)
                event = data.get("event")
                
                if event == "connected":
                    logger.info("Twilio Media Stream connected")
                
                elif event == "start":
                    start_data = data.get("start", {})
                    stream_sid = start_data.get("streamSid")
                    call_sid = start_data.get("customParameters", {}).get("call_sid")
                    caller = start_data.get("customParameters", {}).get("caller")
                    
                    logger.info(f"Stream started: {stream_sid} for call {call_sid}")
                    
                    # ðŸ“Š ANALYTICS: Stream connected
                    if call_sid:
                        await analytics.emit(call_sid, EventType.STREAM_CONNECTED, {
                            "stream_sid": stream_sid
                        }, turn_index=None)
                    
                    if call_sid:
                        claude.start_conversation(
                            call_sid=call_sid,
                            caller_number=caller or "unknown",
                            knowledge=knowledge_service.data
                        )
                        
                        if call_sid in active_calls:
                            active_calls[call_sid]["status"] = "connected"
                            active_calls[call_sid]["stream_sid"] = stream_sid
                        
                        # ðŸ“Š ANALYTICS: Greeting started
                        await analytics.emit(call_sid, EventType.GREETING_STARTED, {}, turn_index=0)
                        
                        # Send greeting
                        await broadcaster.processing_status(call_sid, "speaking")
                        greeting = claude.get_opening_greeting(knowledge_service.data)
                        
                        # ðŸ“Š ANALYTICS: TTS for greeting
                        tts_start = time.time()
                        await analytics.tts_started(call_sid, text=greeting)
                        
                        greeting_audio = await tts.synthesize(greeting)
                        
                        tts_duration = int((time.time() - tts_start) * 1000)
                        if greeting_audio:
                            await analytics.tts_completed(
                                call_sid,
                                duration_ms=tts_duration,
                                audio_bytes=len(greeting_audio),
                                audio_duration_ms=int(len(greeting_audio) / 24 / 2)
                            )
                            
                            await broadcaster.transcript_update(call_sid, "ai", greeting, 0)
                            if call_sid in active_calls:
                                active_calls[call_sid]["turns"].append({
                                    "speaker": "ai",
                                    "text": greeting,
                                    "timestamp": datetime.now().isoformat()
                                })
                            
                            await send_audio_to_twilio(greeting_audio)
                            
                            # ðŸ“Š ANALYTICS: Greeting completed
                            await analytics.emit(call_sid, EventType.GREETING_COMPLETED, {
                                "audio_duration_ms": int(len(greeting_audio) / 24 / 2)
                            }, turn_index=0)
                        
                        await broadcaster.processing_status(call_sid, "listening")
                
                elif event == "media":
                    if is_speaking:
                        # ðŸ“Š ANALYTICS: Detect interrupt attempts
                        if call_sid and not speech_detected:
                            media_data = data.get("media", {})
                            # Could check RMS level here for significant interrupt
                        continue
                    
                    media_data = data.get("media", {})
                    payload = media_data.get("payload")
                    
                    if payload:
                        audio_chunk = base64_decode_audio(payload)
                        
                        # ðŸ“Š ANALYTICS: Emit speech_started on first audio above threshold
                        if not speech_detected and audio_buffer.is_speech(audio_chunk):
                            speech_detected = True
                            await analytics.speech_started(call_sid, rms_level=audio_buffer.get_rms(audio_chunk))
                        
                        complete_audio = audio_buffer.add_audio(audio_chunk)
                        
                        if complete_audio:
                            asyncio.create_task(process_speech(complete_audio))
                
                elif event == "mark":
                    mark_name = data.get("mark", {}).get("name")
                    # ðŸ“Š ANALYTICS: Mark received
                    if call_sid:
                        await analytics.emit(call_sid, EventType.MARK_RECEIVED, {
                            "mark_name": mark_name
                        })
                
                elif event == "stop":
                    logger.info(f"Stream stopping for call {call_sid}")
                    remaining = audio_buffer.flush()
                    if remaining:
                        await process_speech(remaining)
                    break
                    
            except json.JSONDecodeError:
                continue
                
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for call {call_sid}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
    finally:
        if call_sid:
            claude.end_conversation(call_sid)
            
            # Calculate duration
            duration_seconds = None
            if call_sid in active_calls:
                started = active_calls[call_sid].get("started_at")
                if started:
                    start_time = datetime.fromisoformat(started)
                    duration_seconds = int((datetime.now() - start_time).total_seconds())
                
                active_calls[call_sid]["status"] = "ended"
                active_calls[call_sid]["ended_at"] = datetime.now().isoformat()
                active_calls[call_sid]["duration_seconds"] = duration_seconds
            
            # ðŸ“Š ANALYTICS: End call tracking and compute metrics
            analytics.end_call(call_sid, reason="stream_ended")
            
            await broadcaster.call_ended(call_sid, duration_seconds)
            
            if call_sid in active_calls:
                save_transcript(call_sid, active_calls[call_sid])
        
        logger.info(f"WebSocket closed for call {call_sid}")


@router.post("/status")
async def call_status(request: Request):
    """
    Handle call status callbacks from Twilio.
    
    Twilio sends these when call state changes.
    """
    form_data = await request.form()
    
    call_sid = form_data.get("CallSid")
    call_status = form_data.get("CallStatus")
    caller = form_data.get("From")
    duration = form_data.get("CallDuration")
    
    logger.info(f"Call status: {call_sid} -> {call_status} (duration: {duration}s)")
    
    # Update our tracking
    if call_sid and call_sid in active_calls:
        active_calls[call_sid]["status"] = call_status
        if duration:
            active_calls[call_sid]["duration"] = int(duration)
    
    return {"status": "received"}


@router.get("/active")
async def get_active_calls():
    """
    Get list of active calls.
    
    For dashboard monitoring.
    """
    return {
        "calls": active_calls,
        "count": len([c for c in active_calls.values() if c.get("status") not in ["ended", "completed"]])
    }


@router.get("/call/{call_sid}")
async def get_call_info(call_sid: str):
    """Get info about a specific call."""
    if call_sid not in active_calls:
        return {"error": "Call not found"}
    return active_calls[call_sid]