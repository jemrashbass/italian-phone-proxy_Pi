"""
Messaging API Router.

Endpoints for SMS location sharing with delivery drivers.

Endpoints:
- POST /api/messaging/send-location - Send location SMS immediately
- POST /api/messaging/queue-location - Queue location with countdown
- POST /api/messaging/send-now/{call_sid} - Send queued message immediately  
- DELETE /api/messaging/queue/{call_sid} - Cancel queued send
- GET /api/messaging/queue - Get all queued messages
- POST /api/messaging/detect - Test delivery context detection
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging

from app.services.messaging import get_messaging_service

logger = logging.getLogger(__name__)
router = APIRouter()


class SendLocationRequest(BaseModel):
    """Request to send location SMS."""
    to_number: str
    message: Optional[str] = None  # If None, uses template from config


class QueueLocationRequest(BaseModel):
    """Request to queue location SMS."""
    call_sid: str
    to_number: str
    delay_seconds: Optional[int] = None  # If None, uses config default


class DetectRequest(BaseModel):
    """Request to test delivery context detection."""
    text: str


@router.post("/send-location")
async def send_location(request: SendLocationRequest):
    """
    Send location SMS immediately.
    
    Uses the configured message template unless a custom message is provided.
    """
    service = get_messaging_service()
    
    result = service.send_sms(request.to_number, request.message)
    
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error)
    
    return result.to_dict()


@router.post("/queue-location")
async def queue_location(request: QueueLocationRequest):
    """
    Queue a location SMS to be sent after a delay.
    
    The message will auto-send after the configured delay unless cancelled.
    Dashboard will show countdown and allow immediate send or cancel.
    """
    service = get_messaging_service()
    
    result = await service.queue_location_send(
        call_sid=request.call_sid,
        to_number=request.to_number,
        delay_seconds=request.delay_seconds
    )
    
    return result


@router.post("/send-now/{call_sid}")
async def send_now(call_sid: str):
    """
    Send a queued location SMS immediately, skipping the countdown.
    """
    service = get_messaging_service()
    
    result = await service.send_now(call_sid)
    
    if not result.success:
        if result.error == "No queued message found":
            raise HTTPException(status_code=404, detail=result.error)
        raise HTTPException(status_code=500, detail=result.error)
    
    return result.to_dict()


@router.delete("/queue/{call_sid}")
async def cancel_queued(call_sid: str):
    """
    Cancel a queued location send.
    """
    service = get_messaging_service()
    
    result = await service.cancel_queued_send(call_sid)
    
    return result


@router.get("/queue")
async def get_queue():
    """
    Get status of all queued messages.
    """
    service = get_messaging_service()
    
    return {
        "queued": service.get_queue_status()
    }


@router.post("/detect")
async def detect_delivery_context(request: DetectRequest):
    """
    Test delivery context detection using keywords.
    
    Returns whether the text suggests a delivery/directions scenario
    that should trigger a location send suggestion.
    """
    service = get_messaging_service()
    
    result = service.detect_delivery_context(request.text)
    
    return result


@router.post("/detect-claude")
async def detect_delivery_context_claude(request: DetectRequest):
    """
    Test delivery context detection using Claude AI.
    
    This is the smarter detection that understands context:
    - Delivery drivers (corriere, postino, Amazon, etc.)
    - Service engineers (tecnico, idraulico, elettricista, etc.)
    - Anyone asking for directions
    
    Much more accurate than keyword matching!
    """
    service = get_messaging_service()
    
    result = await service.detect_delivery_context_with_claude(request.text)
    
    return result


@router.get("/config")
async def get_messaging_config():
    """
    Get current messaging configuration.
    
    Configuration is read from knowledge.json (location_sharing section).
    """
    service = get_messaging_service()
    return service.get_config()


@router.get("/preview")
async def preview_message():
    """
    Preview the formatted location message.
    """
    service = get_messaging_service()
    return service.get_message_preview()