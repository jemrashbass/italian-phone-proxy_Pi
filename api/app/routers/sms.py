"""
SMS Webhook Handler.

Receives incoming SMS messages and forwards them to the owner's mobile.
Also logs to dashboard for visibility.
"""
import logging
import os
from datetime import datetime
from fastapi import APIRouter, Request, Form
from fastapi.responses import PlainTextResponse

from twilio.rest import Client as TwilioClient
from twilio.twiml.messaging_response import MessagingResponse

logger = logging.getLogger(__name__)
router = APIRouter()


def get_twilio_client() -> TwilioClient:
    """Get Twilio client."""
    return TwilioClient(
        os.getenv("TWILIO_ACCOUNT_SID"),
        os.getenv("TWILIO_AUTH_TOKEN")
    )


def format_forward_message(from_number: str, body: str) -> str:
    """Format the forwarded message."""
    return f"📱 SMS from {from_number}:\n\n{body}"


@router.post("/sms-incoming")
async def sms_incoming(
    request: Request,
    From: str = Form(...),
    To: str = Form(...),
    Body: str = Form(default=""),
    MessageSid: str = Form(default=""),
    NumMedia: str = Form(default="0"),
):
    """
    Handle incoming SMS messages.
    
    Twilio sends:
    - From: sender's phone number
    - To: your Twilio number
    - Body: message text
    - MessageSid: unique message ID
    - NumMedia: number of media attachments
    
    We forward the message to the owner's mobile number.
    """
    logger.info(f"📨 Incoming SMS from {From}: {Body[:50]}...")
    
    # Get owner's mobile number
    owner_mobile = os.getenv("OWNER_MOBILE_NUMBER")
    twilio_number = os.getenv("TWILIO_PHONE_NUMBER")
    
    # Broadcast to dashboard if available
    try:
        from app.routers.dashboard import broadcaster
        await broadcaster.broadcast({
            "type": "sms_received",
            "from": From,
            "body": Body,
            "message_sid": MessageSid,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        })
    except Exception as e:
        logger.warning(f"Could not broadcast SMS to dashboard: {e}")
    
    # Forward to owner's mobile
    if owner_mobile and twilio_number:
        try:
            client = get_twilio_client()
            
            forward_body = format_forward_message(From, Body)
            
            result = client.messages.create(
                body=forward_body,
                from_=twilio_number,
                to=owner_mobile
            )
            
            logger.info(f"✅ Forwarded SMS to {owner_mobile}: {result.sid}")
            
        except Exception as e:
            logger.error(f"❌ Failed to forward SMS: {e}")
    else:
        logger.warning("OWNER_MOBILE_NUMBER not configured - SMS not forwarded")
    
    # Return empty TwiML response (don't auto-reply to sender)
    response = MessagingResponse()
    return PlainTextResponse(
        content=str(response),
        media_type="application/xml"
    )


@router.get("/sms-status")
async def sms_status():
    """Check SMS forwarding configuration status."""
    owner_mobile = os.getenv("OWNER_MOBILE_NUMBER")
    twilio_number = os.getenv("TWILIO_PHONE_NUMBER")
    
    return {
        "forwarding_enabled": bool(owner_mobile),
        "owner_mobile_configured": bool(owner_mobile),
        "owner_mobile_masked": f"***{owner_mobile[-4:]}" if owner_mobile else None,
        "twilio_number": twilio_number
    }