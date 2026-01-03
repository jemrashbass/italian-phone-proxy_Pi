"""
Location Integration Module

Connects delivery detection with SMS location sending.
Call this after each conversation turn to check for delivery context.
"""
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Default timeout for auto-send (seconds)
DEFAULT_LOCATION_TIMEOUT = 30


async def check_and_trigger_location_send(
    call_sid: str,
    caller: str,
    transcript_text: str,
    speaker: str,
    timeout_seconds: int = DEFAULT_LOCATION_TIMEOUT
):
    """
    Check if delivery context detected and trigger location send notification.
    
    Call this after each transcript update to detect delivery conversations.
    
    Args:
        call_sid: Current call SID
        caller: Caller's phone number
        transcript_text: The transcript text to analyze
        speaker: Who said it ("caller" or "ai")
        timeout_seconds: How long to wait before auto-sending
    """
    from app.services.delivery_detection import get_delivery_detector
    from app.routers.dashboard import broadcaster, schedule_location_send, active_calls
    
    detector = get_delivery_detector()
    
    # Add this turn to the detector
    detector.add_turn(call_sid, transcript_text, speaker)
    
    # Analyze the conversation
    context = detector.analyze_conversation(call_sid)
    
    if context.should_send_location:
        # Check if we haven't already triggered for this call
        call_data = active_calls.get(call_sid, {})
        if call_data.get("location_send_pending") or call_data.get("location_sent"):
            logger.debug(f"📍 Location already pending/sent for {call_sid}, skipping")
            return
        
        logger.info(f"📍 Delivery detected for {call_sid}: {context.reason}")
        
        # Notify dashboard
        await broadcaster.location_send_pending(
            call_sid=call_sid,
            caller=caller,
            confidence=context.confidence,
            reason=context.reason,
            timeout_seconds=timeout_seconds
        )
        
        # Schedule auto-send after timeout
        await schedule_location_send(
            call_sid=call_sid,
            caller=caller,
            timeout_seconds=timeout_seconds
        )


async def send_location_immediately(
    call_sid: str,
    caller: str
) -> dict:
    """
    Send location SMS immediately (manual trigger).
    
    Args:
        call_sid: Current call SID
        caller: Caller's phone number
        
    Returns:
        Result dict with success status
    """
    from app.services.messaging import get_messaging_service
    from app.routers.dashboard import broadcaster, cancel_location_send
    
    # Cancel any pending auto-send
    cancel_location_send(call_sid)
    
    # Send immediately
    messaging = get_messaging_service()
    result = messaging.send_location_sms(
        to_number=caller,
        call_sid=call_sid,
        trigger="manual"
    )
    
    # Notify dashboard
    await broadcaster.location_sent(
        call_sid=call_sid,
        caller=caller,
        trigger="manual",
        success=result.get("success", False)
    )
    
    return result


def cleanup_call(call_sid: str):
    """
    Clean up delivery detection data when call ends.
    
    Args:
        call_sid: Call SID to clean up
    """
    from app.services.delivery_detection import get_delivery_detector
    from app.routers.dashboard import cancel_location_send
    
    # Cancel any pending location send
    cancel_location_send(call_sid)
    
    # Clear detection data
    detector = get_delivery_detector()
    detector.clear_call(call_sid)
    
    logger.debug(f"📍 Cleaned up location data for {call_sid}")