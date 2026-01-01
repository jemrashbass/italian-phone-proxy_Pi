"""
Twilio webhook handlers.
"""
from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import PlainTextResponse
import logging
import json

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/voice")
async def handle_incoming_call(request: Request):
    """Handle incoming voice call from Twilio."""
    
    form_data = await request.form()
    caller = form_data.get("From", "Unknown")
    called = form_data.get("To", "Unknown")
    call_sid = form_data.get("CallSid", "Unknown")
    
    logger.info(f"Incoming call from {caller} to {called} (SID: {call_sid})")
    
    # TwiML response - for now, just a greeting
    # Phase 2 will add Media Streams for real-time audio
    twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Google.it-IT-Wavenet-A" language="it-IT">
        Pronto. Mi scusi, sono inglese e il mio italiano non è perfetto.
        Un momento per favore, la passo al proprietario.
    </Say>
    <Pause length="2"/>
    <Say voice="Google.it-IT-Wavenet-A" language="it-IT">
        Grazie per la pazienza. Arrivederci.
    </Say>
</Response>"""
    
    return PlainTextResponse(content=twiml, media_type="application/xml")


@router.websocket("/stream")
async def media_stream(websocket: WebSocket):
    """Handle real-time audio stream from Twilio."""
    await websocket.accept()
    
    logger.info("WebSocket connection established for media stream")
    
    # TODO: Phase 2 - Implement full audio pipeline
    # 1. Receive audio chunks from Twilio
    # 2. Buffer and send to Whisper API for STT
    # 3. Feed transcript to Claude with system prompt
    # 4. Generate response with TTS
    # 5. Stream audio back to Twilio
    # 6. Broadcast transcript to dashboard via separate WebSocket
    
    try:
        async for message in websocket.iter_text():
            data = json.loads(message)
            event_type = data.get("event")
            
            if event_type == "connected":
                logger.info("Twilio media stream connected")
            elif event_type == "start":
                stream_sid = data.get("start", {}).get("streamSid")
                logger.info(f"Media stream started: {stream_sid}")
            elif event_type == "media":
                # Audio payload in base64
                # payload = data.get("media", {}).get("payload")
                pass  # Process audio in Phase 2
            elif event_type == "stop":
                logger.info("Media stream stopped")
                break
                
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        logger.info("WebSocket connection closed")


@router.post("/status")
async def call_status(request: Request):
    """Handle call status callbacks."""
    
    form_data = await request.form()
    call_sid = form_data.get("CallSid")
    status = form_data.get("CallStatus")
    duration = form_data.get("CallDuration", "0")
    
    logger.info(f"Call {call_sid} status: {status} (duration: {duration}s)")
    
    # TODO: Store call records for history
    
    return {"status": "received"}


@router.post("/outbound")
async def initiate_outbound_call(request: Request):
    """Initiate an outbound call (for future implementation)."""
    
    # TODO: Phase 3 - Implement outbound calling
    # 1. Accept target number and scenario
    # 2. Create Twilio call with webhook URL
    # 3. Return call SID for tracking
    
    return {
        "status": "not_implemented",
        "message": "Outbound calling will be implemented in Phase 3"
    }
