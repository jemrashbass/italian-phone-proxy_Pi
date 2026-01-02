"""
Call history and outbound call management.
"""
import os
import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from twilio.rest import Client as TwilioClient

router = APIRouter()
logger = logging.getLogger(__name__)

# In-memory call log (future: persist to file/database)
call_log: list[dict] = []


class OutboundCallRequest(BaseModel):
    """Request to initiate an outbound call."""
    to_number: str
    scenario: Optional[str] = None
    notes: Optional[str] = None


@router.get("/history")
async def get_call_history(limit: int = 20):
    """
    Get recent call history.
    
    Returns list of calls with transcripts and status.
    """
    # Import active calls from twilio router
    from app.routers.twilio import active_calls
    
    # Combine with historical log
    all_calls = list(active_calls.values()) + call_log
    
    # Sort by start time, most recent first
    all_calls.sort(
        key=lambda x: x.get("started_at", ""),
        reverse=True
    )
    
    return {
        "calls": all_calls[:limit],
        "total": len(all_calls)
    }


@router.post("/outbound")
async def initiate_outbound_call(call_request: OutboundCallRequest, request: Request):
    """
    Initiate an outbound call.
    
    The AI will handle the call according to the specified scenario.
    """
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_PHONE_NUMBER")
    
    if not all([account_sid, auth_token, from_number]):
        raise HTTPException(status_code=500, detail="Twilio not configured")
    
    try:
        client = TwilioClient(account_sid, auth_token)
        
        # Build webhook URL for this server
        host = request.headers.get("host", "phone.rashbass.org")
        voice_url = f"https://{host}/api/twilio/voice"
        status_url = f"https://{host}/api/twilio/status"
        
        # Initiate the call
        call = client.calls.create(
            to=call_request.to_number,
            from_=from_number,
            url=voice_url,
            status_callback=status_url,
            status_callback_event=["initiated", "ringing", "answered", "completed"]
        )
        
        logger.info(f"📞 Outbound call initiated: {call.sid} to {call_request.to_number}")
        
        # Log the call
        call_log.append({
            "call_sid": call.sid,
            "direction": "outbound",
            "to": call_request.to_number,
            "from": from_number,
            "scenario": call_request.scenario,
            "notes": call_request.notes,
            "started_at": datetime.now().isoformat(),
            "status": "initiated"
        })
        
        return {
            "success": True,
            "call_sid": call.sid,
            "status": "initiated",
            "to": call_request.to_number
        }
        
    except Exception as e:
        logger.error(f"Failed to initiate outbound call: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/transcript/{call_sid}")
async def get_call_transcript(call_sid: str):
    """
    Get the full transcript for a call.
    """
    from app.services.claude import get_claude_service
    
    claude = get_claude_service()
    state = claude.get_conversation(call_sid)
    
    if not state:
        # Check call log
        for call in call_log:
            if call.get("call_sid") == call_sid:
                return {
                    "call_sid": call_sid,
                    "transcript": call.get("transcript", []),
                    "status": call.get("status")
                }
        raise HTTPException(status_code=404, detail="Call not found")
    
    return {
        "call_sid": call_sid,
        "transcript": state.history,
        "turn_count": state.turn_count
    }


@router.delete("/history")
async def clear_call_history():
    """Clear the call history (for testing)."""
    global call_log
    call_log = []
    return {"status": "cleared"}
