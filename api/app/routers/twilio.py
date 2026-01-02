"""
Twilio webhook and WebSocket handlers for phone calls.

Implements:
- /voice - Incoming call webhook (returns TwiML)
- /stream - WebSocket for bidirectional audio streaming
- /status - Call status callbacks

Includes dashboard broadcasting for real-time monitoring.
"""
import asyncio
import json
import logging
import os
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

from app.routers.dashboard import broadcaster

router = APIRouter()
logger = logging.getLogger(__name__)

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


@router.post("/voice")
async def handle_incoming_call(request: Request):
    """
    Handle incoming voice call from Twilio.
    
    Returns TwiML that:
    1. Plays initial greeting
    2. Connects to WebSocket for bidirectional streaming
    """
    form_data = await request.form()
    
    call_sid = form_data.get("CallSid", "unknown")
    caller = form_data.get("From", "Unknown")
    called = form_data.get("To", "Unknown")
    
    logger.info(f"📞 Incoming call: {call_sid} from {caller} to {called}")
    
    # Broadcast to dashboard
    await broadcaster.call_started(call_sid, caller, called)
    
    # Track the call
    active_calls[call_sid] = {
        "caller": caller,
        "called": called,
        "started_at": datetime.now().isoformat(),
        "status": "ringing",
        "turns": []  # Track conversation turns
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
    """
    Handle bidirectional audio stream from Twilio.
    
    Twilio Media Streams protocol:
    - Receives: JSON messages with base64-encoded mulaw audio
    - Sends: JSON messages with base64-encoded mulaw audio
    
    Pipeline:
    1. Receive audio chunks from Twilio
    2. Buffer until silence detected (end of speech)
    3. Send to Whisper API for transcription
    4. Feed transcript to Claude for response
    5. Generate response audio with TTS
    6. Stream back to Twilio
    """
    await websocket.accept()
    
    # Initialize services
    whisper = get_whisper_service()
    tts = get_tts_service()
    claude = get_claude_service()
    knowledge_service = KnowledgeService()
    knowledge_service.load()
    
    # State for this call
    call_sid: Optional[str] = None
    caller: Optional[str] = None
    stream_sid: Optional[str] = None
    audio_buffer = AudioBuffer()
    
    # Processing lock to prevent overlapping responses
    processing_lock = asyncio.Lock()
    is_speaking = False  # True when AI is outputting audio
    
    logger.info("WebSocket connection accepted")
    
    async def end_call(reason: str = "goodbye"):
        """Terminate the call via Twilio API."""
        nonlocal call_sid
        
        if not call_sid:
            return
            
        logger.info(f"🔚 Ending call {call_sid} (reason: {reason})")
        
        try:
            twilio_client = TwilioClient(
                os.getenv("TWILIO_ACCOUNT_SID"),
                os.getenv("TWILIO_AUTH_TOKEN")
            )
            twilio_client.calls(call_sid).update(status="completed")
            logger.info(f"📞 Call {call_sid} terminated successfully")
        except Exception as e:
            logger.error(f"Failed to end call {call_sid}: {e}")
    
    async def send_audio_to_twilio(audio_data: bytes):
        """Send TTS audio back to the caller via Twilio."""
        nonlocal is_speaking
        
        if not stream_sid:
            logger.warning("Cannot send audio: no stream_sid")
            return
        
        is_speaking = True
        
        try:
            # Convert TTS output to Twilio format
            # OpenAI TTS outputs 24kHz PCM, Twilio needs 8kHz mulaw
            b64_audio = prepare_audio_for_twilio(audio_data, source_rate=24000)
            
            # Send media message to Twilio
            # Twilio expects chunks of ~20ms (160 bytes at 8kHz mulaw)
            # We'll send in larger chunks for efficiency
            chunk_size = 640  # ~80ms of audio
            
            for i in range(0, len(b64_audio), chunk_size):
                chunk = b64_audio[i:i + chunk_size]
                
                message = {
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {
                        "payload": chunk
                    }
                }
                
                await websocket.send_text(json.dumps(message))
                
                # Small delay to pace the audio
                await asyncio.sleep(0.02)
            
            # Mark end of audio
            mark_message = {
                "event": "mark",
                "streamSid": stream_sid,
                "mark": {
                    "name": "response_end"
                }
            }
            await websocket.send_text(json.dumps(mark_message))
            
        finally:
            is_speaking = False
    
    async def process_speech(audio_bytes: bytes):
        """Process completed speech segment through the full pipeline."""
        nonlocal call_sid
        
        if not call_sid:
            return
        
        async with processing_lock:
            try:
                # 1. Convert audio for Whisper
                await broadcaster.processing_status(call_sid, "transcribing")
                wav_audio = prepare_audio_for_whisper(audio_bytes)
                
                # 2. Transcribe
                transcript = await whisper.transcribe(wav_audio)
                
                if not transcript:
                    logger.debug("Empty transcript, skipping")
                    await broadcaster.processing_status(call_sid, "listening")
                    return
                
                logger.info(f"🎤 Caller said: {transcript}")
                
                # Broadcast caller's speech to dashboard
                turn_index = len(active_calls.get(call_sid, {}).get("turns", []))
                await broadcaster.transcript_update(call_sid, "caller", transcript, turn_index)
                
                # Update call tracking
                if call_sid in active_calls:
                    active_calls[call_sid]["last_transcript"] = transcript
                    if "turns" not in active_calls[call_sid]:
                        active_calls[call_sid]["turns"] = []
                    active_calls[call_sid]["turns"].append({
                        "speaker": "caller", 
                        "text": transcript,
                        "timestamp": datetime.now().isoformat()
                    })
                
                # 3. Get Claude's response
                await broadcaster.processing_status(call_sid, "thinking")
                start_time = datetime.now()
                response_text = await claude.respond(call_sid, transcript)
                
                if not response_text:
                    logger.warning("No response from Claude")
                    await broadcaster.processing_status(call_sid, "listening")
                    return
                
                logger.info(f"🤖 AI response: {response_text}")
                
                # Calculate latency and broadcast AI response to dashboard
                latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                turn_index = len(active_calls.get(call_sid, {}).get("turns", []))
                await broadcaster.transcript_update(call_sid, "ai", response_text, turn_index, latency_ms)
                
                # Track AI turn
                if call_sid in active_calls:
                    active_calls[call_sid]["turns"].append({
                        "speaker": "ai", 
                        "text": response_text,
                        "timestamp": datetime.now().isoformat(),
                        "latency_ms": latency_ms
                    })
                
                # 4. Generate TTS audio
                await broadcaster.processing_status(call_sid, "speaking")
                audio_response = await tts.synthesize(response_text)
                
                if not audio_response:
                    logger.warning("TTS failed to generate audio")
                    return
                
                # 5. Send audio to caller
                await send_audio_to_twilio(audio_response)
                
                # Back to listening
                await broadcaster.processing_status(call_sid, "listening")
                
                # 6. Check if AI said goodbye - end the call
                # Don't auto-hangup on quick responses (might be echo)
                from app.prompts.system import get_quick_response
                is_quick = get_quick_response(transcript) is not None
                response_lower = response_text.lower()
                if not is_quick and any(phrase in response_lower for phrase in GOODBYE_PHRASES):
                    logger.info(f"🔚 AI said goodbye, scheduling call end for {call_sid}")
                    # Wait for audio to finish playing before hanging up
                    await asyncio.sleep(3)
                    await end_call("ai_goodbye")
                
            except Exception as e:
                logger.error(f"Error processing speech: {e}", exc_info=True)
                await broadcaster.error(call_sid, "processing_error", str(e))
    
    try:
        async for message in websocket.iter_text():
            try:
                data = json.loads(message)
                event = data.get("event")
                
                if event == "connected":
                    logger.info("Twilio Media Stream connected")
                
                elif event == "start":
                    # Stream starting - get metadata
                    start_data = data.get("start", {})
                    stream_sid = start_data.get("streamSid")
                    call_sid = start_data.get("customParameters", {}).get("call_sid")
                    caller = start_data.get("customParameters", {}).get("caller")
                    
                    logger.info(f"Stream started: {stream_sid} for call {call_sid}")
                    
                    # Initialize conversation with Claude
                    if call_sid:
                        claude.start_conversation(
                            call_sid=call_sid,
                            caller_number=caller or "unknown",
                            knowledge=knowledge_service.data
                        )
                        
                        # Update call status
                        if call_sid in active_calls:
                            active_calls[call_sid]["status"] = "connected"
                            active_calls[call_sid]["stream_sid"] = stream_sid
                        
                        # Send opening greeting via TTS
                        await broadcaster.processing_status(call_sid, "speaking")
                        greeting = claude.get_opening_greeting(knowledge_service.data)
                        
                        # Broadcast the greeting to dashboard
                        await broadcaster.transcript_update(call_sid, "ai", greeting, 0)
                        if call_sid in active_calls:
                            active_calls[call_sid]["turns"].append({
                                "speaker": "ai",
                                "text": greeting,
                                "timestamp": datetime.now().isoformat()
                            })
                        
                        greeting_audio = await tts.synthesize(greeting)
                        if greeting_audio:
                            await send_audio_to_twilio(greeting_audio)
                        
                        await broadcaster.processing_status(call_sid, "listening")
                
                elif event == "media":
                    # Incoming audio from caller
                    if is_speaking:
                        # Ignore incoming audio while we're speaking (barge-in disabled for now)
                        continue
                    
                    media_data = data.get("media", {})
                    payload = media_data.get("payload")
                    
                    if payload:
                        # Decode base64 audio
                        audio_chunk = base64_decode_audio(payload)
                        
                        # Add to buffer, check if speech segment complete
                        complete_audio = audio_buffer.add_audio(audio_chunk)
                        
                        if complete_audio:
                            # Process in background to not block WebSocket
                            asyncio.create_task(process_speech(complete_audio))
                
                elif event == "mark":
                    # Our audio finished playing
                    mark_name = data.get("mark", {}).get("name")
                    logger.debug(f"Mark received: {mark_name}")
                
                elif event == "stop":
                    # Stream ending
                    logger.info(f"Stream stopping for call {call_sid}")
                    
                    # Process any remaining audio
                    remaining = audio_buffer.flush()
                    if remaining:
                        await process_speech(remaining)
                    
                    break
                
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from Twilio: {message[:100]}")
                continue
                
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for call {call_sid}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        if call_sid:
            await broadcaster.error(call_sid, "websocket_error", str(e))
    finally:
        # Cleanup
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
            
            # Broadcast call ended to dashboard
            await broadcaster.call_ended(call_sid, duration_seconds)
        
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