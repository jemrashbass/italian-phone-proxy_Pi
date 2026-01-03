"""
Messaging Service.

Handles SMS location sharing for delivery drivers.
Supports:
- Manual send (immediate)
- Queued send with countdown (auto-send after delay unless cancelled)
- Detection of delivery context from conversation

Uses Twilio SMS API.
Configuration is stored in knowledge.json under location_sharing.
"""
import asyncio
import logging
import os
from datetime import datetime
from typing import Optional, Callable, Awaitable, Any
from dataclasses import dataclass, asdict

from twilio.rest import Client

logger = logging.getLogger(__name__)


# Default configuration values
DEFAULT_LOCATION_SHARING = {
    "coordinates": {"lat": None, "lng": None},
    "google_maps_url": "",
    "sms_template": "📍 Ecco la posizione esatta:\n{address}\n\n🗺 {location_url}",
    "auto_send_enabled": True,
    "auto_send_delay_seconds": 30,
    "delivery_keywords": ["consegna", "corriere", "pacco", "delivery", "spedizione", "pacchetto"],
    "address_keywords": ["indirizzo", "dove", "posizione", "strada", "via", "directions", "arrivare"]
}


@dataclass
class QueuedMessage:
    """A message queued for sending."""
    call_sid: str
    to_number: str
    message: str
    queued_at: str
    send_at: str  # ISO timestamp when it should be sent
    delay_seconds: int
    status: str = "pending"  # pending, sent, cancelled


@dataclass
class MessageResult:
    """Result of a send operation."""
    success: bool
    to_number: str
    message_sid: Optional[str] = None
    error: Optional[str] = None
    timestamp: str = ""
    
    def to_dict(self) -> dict:
        return asdict(self)


class MessagingService:
    """
    Service for sending SMS messages.
    
    Provides:
    - Immediate SMS sending
    - Queued sending with countdown
    - Delivery context detection
    
    Configuration is read from knowledge.json (location_sharing section).
    """
    
    def __init__(self):
        self._twilio_client: Optional[Client] = None
        self._twilio_number: Optional[str] = None
        self._queued_messages: dict[str, QueuedMessage] = {}  # call_sid -> message
        self._countdown_tasks: dict[str, asyncio.Task] = {}  # call_sid -> task
        self._broadcaster: Optional[Callable[[dict], Awaitable[None]]] = None
        self._knowledge_service = None  # Set via set_knowledge_service
        
    def _get_twilio_client(self) -> Client:
        """Get or create Twilio client."""
        if self._twilio_client is None:
            account_sid = os.getenv("TWILIO_ACCOUNT_SID")
            auth_token = os.getenv("TWILIO_AUTH_TOKEN")
            self._twilio_number = os.getenv("TWILIO_PHONE_NUMBER")
            
            if not all([account_sid, auth_token, self._twilio_number]):
                raise ValueError("Twilio credentials not configured")
            
            self._twilio_client = Client(account_sid, auth_token)
            logger.info(f"Twilio client initialized with number {self._twilio_number}")
        
        return self._twilio_client
    
    def set_knowledge_service(self, knowledge_service) -> None:
        """Set the knowledge service for reading config."""
        self._knowledge_service = knowledge_service
        logger.info("Messaging service connected to knowledge service")
    
    def set_broadcaster(self, broadcaster: Callable[[dict], Awaitable[None]]) -> None:
        """Set the function used to broadcast events to dashboard."""
        self._broadcaster = broadcaster
        logger.info("Messaging service connected to broadcaster")
    
    async def _broadcast(self, event: dict) -> None:
        """Broadcast an event to connected clients."""
        if self._broadcaster:
            try:
                await self._broadcaster(event)
            except Exception as e:
                logger.error(f"Failed to broadcast: {e}")
    
    def _get_location_sharing_config(self) -> dict:
        """
        Get location sharing config from knowledge.json.
        
        Returns dict with all location_sharing settings, using defaults for missing values.
        """
        config = dict(DEFAULT_LOCATION_SHARING)
        config["coordinates"] = dict(DEFAULT_LOCATION_SHARING["coordinates"])
        
        if self._knowledge_service:
            try:
                knowledge_data = self._knowledge_service.data
                ls = knowledge_data.get("location_sharing", {})
                
                # Merge with defaults
                if ls.get("coordinates"):
                    config["coordinates"] = ls["coordinates"]
                if ls.get("google_maps_url"):
                    config["google_maps_url"] = ls["google_maps_url"]
                if ls.get("sms_template"):
                    config["sms_template"] = ls["sms_template"]
                if "auto_send_enabled" in ls:
                    config["auto_send_enabled"] = ls["auto_send_enabled"]
                if ls.get("auto_send_delay_seconds"):
                    config["auto_send_delay_seconds"] = ls["auto_send_delay_seconds"]
                if ls.get("delivery_keywords"):
                    config["delivery_keywords"] = ls["delivery_keywords"]
                if ls.get("address_keywords"):
                    config["address_keywords"] = ls["address_keywords"]
                    
            except Exception as e:
                logger.warning(f"Failed to load location_sharing from knowledge: {e}")
        
        return config
    
    def _get_address_formatted(self) -> str:
        """Get formatted address from knowledge.json."""
        if not self._knowledge_service:
            return ""
        
        try:
            addr = self._knowledge_service.data.get("location", {}).get("address", {})
            parts = []
            
            if addr.get("via"):
                via_part = addr["via"]
                if addr.get("numero"):
                    via_part = f"{via_part} {addr['numero']}"
                parts.append(via_part)
            
            if addr.get("comune"):
                comune_part = addr["comune"]
                if addr.get("provincia"):
                    comune_part = f"{comune_part} ({addr['provincia']})"
                parts.append(comune_part)
            
            return ", ".join(parts)
        except Exception as e:
            logger.warning(f"Failed to format address: {e}")
            return ""
    
    def _format_message(self) -> str:
        """Format the location message using template from knowledge.json."""
        config = self._get_location_sharing_config()
        template = config["sms_template"]
        
        # Replace placeholders
        message = template.replace("{location_url}", config["google_maps_url"] or "")
        message = message.replace("{lat}", str(config["coordinates"].get("lat", "")))
        message = message.replace("{lng}", str(config["coordinates"].get("lng", "")))
        message = message.replace("{address}", self._get_address_formatted())
        
        return message
    
    def get_message_preview(self) -> dict:
        """Get a preview of the formatted SMS message."""
        config = self._get_location_sharing_config()
        return {
            "message": self._format_message(),
            "location_url": config["google_maps_url"],
            "coordinates": config["coordinates"],
            "auto_send_enabled": config["auto_send_enabled"],
            "auto_send_delay_seconds": config["auto_send_delay_seconds"]
        }
    
    def get_config(self) -> dict:
        """Get the current messaging configuration."""
        config = self._get_location_sharing_config()
        return {
            "coordinates": config["coordinates"],
            "google_maps_url": config["google_maps_url"],
            "sms_template": config["sms_template"],
            "auto_send_enabled": config["auto_send_enabled"],
            "auto_send_delay_seconds": config["auto_send_delay_seconds"],
            "delivery_keywords": config["delivery_keywords"],
            "address_keywords": config["address_keywords"]
        }
    
    def send_sms(self, to_number: str, message: Optional[str] = None) -> MessageResult:
        """
        Send an SMS immediately.
        
        Args:
            to_number: Recipient phone number (E.164 format)
            message: Optional custom message. If None, uses location template.
            
        Returns:
            MessageResult with success status and message SID
        """
        try:
            client = self._get_twilio_client()
            
            if message is None:
                message = self._format_message()
            
            # Clean phone number
            to_number = to_number.strip()
            if not to_number.startswith("+"):
                # Assume Italian number if no country code
                if to_number.startswith("0"):
                    to_number = "+39" + to_number[1:]
                elif to_number.startswith("3"):
                    to_number = "+39" + to_number
                else:
                    to_number = "+" + to_number
            
            logger.info(f"Sending SMS to {to_number}")
            
            result = client.messages.create(
                body=message,
                from_=self._twilio_number,
                to=to_number
            )
            
            logger.info(f"SMS sent successfully: {result.sid}")
            
            return MessageResult(
                success=True,
                to_number=to_number,
                message_sid=result.sid,
                timestamp=datetime.utcnow().isoformat() + "Z"
            )
            
        except Exception as e:
            logger.error(f"Failed to send SMS to {to_number}: {e}")
            return MessageResult(
                success=False,
                to_number=to_number,
                error=str(e),
                timestamp=datetime.utcnow().isoformat() + "Z"
            )
    
    async def queue_location_send(
        self,
        call_sid: str,
        to_number: str,
        delay_seconds: Optional[int] = None
    ) -> dict:
        """
        Queue a location SMS for sending after a delay.
        
        The message will be sent automatically after delay_seconds unless cancelled.
        Broadcasts countdown updates to the dashboard.
        
        Args:
            call_sid: Call SID to associate with (for cancellation)
            to_number: Recipient phone number
            delay_seconds: Override config delay (optional)
            
        Returns:
            Queue status dict
        """
        config = self._get_location_sharing_config()
        
        if delay_seconds is None:
            delay_seconds = config["auto_send_delay_seconds"]
        
        # Cancel any existing queue for this call
        await self.cancel_queued_send(call_sid)
        
        now = datetime.utcnow()
        
        queued = QueuedMessage(
            call_sid=call_sid,
            to_number=to_number,
            message=self._format_message(),
            queued_at=now.isoformat() + "Z",
            send_at=(datetime.utcnow()).isoformat() + "Z",  # Will be updated
            delay_seconds=delay_seconds
        )
        
        self._queued_messages[call_sid] = queued
        
        # Start countdown task
        task = asyncio.create_task(self._countdown_and_send(call_sid, delay_seconds))
        self._countdown_tasks[call_sid] = task
        
        logger.info(f"Queued location SMS for {to_number} in {delay_seconds}s (call: {call_sid})")
        
        # Broadcast suggestion to dashboard
        await self._broadcast({
            "type": "location_suggested",
            "call_sid": call_sid,
            "to_number": to_number,
            "delay_seconds": delay_seconds,
            "auto_send_enabled": config["auto_send_enabled"],
            "timestamp": now.isoformat() + "Z"
        })
        
        return {
            "status": "queued",
            "call_sid": call_sid,
            "to_number": to_number,
            "delay_seconds": delay_seconds,
            "auto_send_enabled": config["auto_send_enabled"]
        }
    
    async def _countdown_and_send(self, call_sid: str, delay_seconds: int) -> None:
        """
        Countdown and send the SMS.
        
        Broadcasts countdown updates every second for the last 10 seconds.
        """
        config = self._get_location_sharing_config()
        
        try:
            # Wait for most of the delay (broadcast updates for last 10s)
            if delay_seconds > 10:
                await asyncio.sleep(delay_seconds - 10)
                delay_seconds = 10
            
            # Countdown for the last 10 seconds (or full delay if < 10)
            for remaining in range(delay_seconds, 0, -1):
                # Check if still queued
                if call_sid not in self._queued_messages:
                    logger.info(f"Location send cancelled for {call_sid}")
                    return
                
                # Broadcast countdown
                await self._broadcast({
                    "type": "location_countdown",
                    "call_sid": call_sid,
                    "seconds_remaining": remaining,
                    "timestamp": datetime.utcnow().isoformat() + "Z"
                })
                
                await asyncio.sleep(1)
            
            # Final check before sending
            if call_sid not in self._queued_messages:
                return
            
            queued = self._queued_messages[call_sid]
            
            # Re-check config in case it changed
            config = self._get_location_sharing_config()
            
            # Only auto-send if enabled
            if not config["auto_send_enabled"]:
                logger.info(f"Auto-send disabled, not sending for {call_sid}")
                await self._broadcast({
                    "type": "location_expired",
                    "call_sid": call_sid,
                    "reason": "auto_send_disabled",
                    "timestamp": datetime.utcnow().isoformat() + "Z"
                })
                del self._queued_messages[call_sid]
                return
            
            # Send the SMS
            result = self.send_sms(queued.to_number, queued.message)
            
            # Update status
            queued.status = "sent" if result.success else "failed"
            
            # Broadcast result
            await self._broadcast({
                "type": "location_sent" if result.success else "location_failed",
                "call_sid": call_sid,
                "to_number": queued.to_number,
                "message_sid": result.message_sid,
                "error": result.error,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            })
            
            # Cleanup
            del self._queued_messages[call_sid]
            
        except asyncio.CancelledError:
            logger.info(f"Countdown cancelled for {call_sid}")
            raise
        except Exception as e:
            logger.error(f"Error in countdown for {call_sid}: {e}")
            if call_sid in self._queued_messages:
                del self._queued_messages[call_sid]
        finally:
            if call_sid in self._countdown_tasks:
                del self._countdown_tasks[call_sid]
    
    async def cancel_queued_send(self, call_sid: str) -> dict:
        """
        Cancel a queued location send.
        
        Args:
            call_sid: Call SID to cancel
            
        Returns:
            Cancellation status dict
        """
        was_queued = call_sid in self._queued_messages
        
        # Cancel the task
        if call_sid in self._countdown_tasks:
            self._countdown_tasks[call_sid].cancel()
            try:
                await self._countdown_tasks[call_sid]
            except asyncio.CancelledError:
                pass
            del self._countdown_tasks[call_sid]
        
        # Remove from queue
        if call_sid in self._queued_messages:
            del self._queued_messages[call_sid]
        
        if was_queued:
            logger.info(f"Cancelled queued location send for {call_sid}")
            
            await self._broadcast({
                "type": "location_cancelled",
                "call_sid": call_sid,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            })
        
        return {
            "status": "cancelled" if was_queued else "not_found",
            "call_sid": call_sid
        }
    
    async def send_now(self, call_sid: str) -> MessageResult:
        """
        Send a queued location immediately (skip countdown).
        
        Args:
            call_sid: Call SID of queued message
            
        Returns:
            MessageResult
        """
        if call_sid not in self._queued_messages:
            return MessageResult(
                success=False,
                to_number="",
                error="No queued message found"
            )
        
        queued = self._queued_messages[call_sid]
        
        # Cancel countdown task
        if call_sid in self._countdown_tasks:
            self._countdown_tasks[call_sid].cancel()
            try:
                await self._countdown_tasks[call_sid]
            except asyncio.CancelledError:
                pass
            del self._countdown_tasks[call_sid]
        
        # Send immediately
        result = self.send_sms(queued.to_number, queued.message)
        
        # Broadcast result
        await self._broadcast({
            "type": "location_sent" if result.success else "location_failed",
            "call_sid": call_sid,
            "to_number": queued.to_number,
            "message_sid": result.message_sid,
            "error": result.error,
            "manual": True,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        })
        
        # Cleanup
        del self._queued_messages[call_sid]
        
        return result
    
    def detect_delivery_context(self, text: str) -> dict:
        """
        Detect if text indicates a delivery/directions context using keywords.
        
        DEPRECATED: Use detect_delivery_context_with_claude() for better accuracy.
        
        Looks for delivery keywords AND address/directions keywords.
        
        Args:
            text: Text to analyze (typically the conversation so far)
            
        Returns:
            Detection result with confidence
        """
        config = self._get_location_sharing_config()
        
        text_lower = text.lower()
        
        # Get keywords from config (already lists)
        delivery_keywords = config["delivery_keywords"]
        address_keywords = config["address_keywords"]
        
        # Handle if they're stored as comma-separated string
        if isinstance(delivery_keywords, str):
            delivery_keywords = [k.strip() for k in delivery_keywords.split(",")]
        if isinstance(address_keywords, str):
            address_keywords = [k.strip() for k in address_keywords.split(",")]
        
        # Count matches
        delivery_matches = [k for k in delivery_keywords if k.lower() in text_lower]
        address_matches = [k for k in address_keywords if k.lower() in text_lower]
        
        has_delivery = len(delivery_matches) > 0
        has_address = len(address_matches) > 0
        
        # Require BOTH delivery AND address context
        should_suggest = has_delivery and has_address
        
        # Calculate confidence
        confidence = 0.0
        if should_suggest:
            # More matches = higher confidence
            confidence = min(1.0, (len(delivery_matches) + len(address_matches)) / 4)
        
        return {
            "should_suggest": should_suggest,
            "confidence": confidence,
            "delivery_keywords_found": delivery_matches,
            "address_keywords_found": address_matches
        }
    
    async def detect_delivery_context_with_claude(self, conversation_text: str) -> dict:
        """
        Use Claude to detect if someone is asking for directions to the address.
        
        Much more robust than keyword matching - can detect:
        - Delivery drivers (corriere, postino, Amazon, etc.)
        - Service engineers (tecnico, idraulico, elettricista, etc.)  
        - Anyone lost and asking for directions
        
        Args:
            conversation_text: The full conversation transcript so far
            
        Returns:
            Detection result with should_suggest boolean and reasoning
        """
        import anthropic
        import os
        
        try:
            client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            
            # Get our address from knowledge for context
            address = self._get_address_formatted()
            
            prompt = f"""Analyze this phone conversation transcript and determine if the caller is trying to find/reach a physical address.

The address being discussed is: {address}

Conversation:
{conversation_text}

Answer these questions:
1. Is the caller trying to physically reach/find this location? (delivery driver, service engineer, visitor, etc.)
2. Are they having trouble finding it or asking for directions?

Respond in JSON format only:
{{"should_send_location": true/false, "reason": "brief explanation", "caller_type": "corriere/tecnico/visitor/other/none"}}"""

            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=150,
                messages=[{"role": "user", "content": prompt}]
            )
            
            # Parse response
            response_text = response.content[0].text.strip()
            
            # Try to extract JSON
            import json
            try:
                # Handle potential markdown code blocks
                if "```" in response_text:
                    response_text = response_text.split("```")[1]
                    if response_text.startswith("json"):
                        response_text = response_text[4:]
                
                result = json.loads(response_text)
                
                return {
                    "should_suggest": result.get("should_send_location", False),
                    "confidence": 0.9 if result.get("should_send_location") else 0.1,
                    "reason": result.get("reason", ""),
                    "caller_type": result.get("caller_type", "unknown"),
                    "method": "claude"
                }
            except json.JSONDecodeError:
                # If we can't parse JSON, look for yes/no patterns
                should_suggest = "true" in response_text.lower() or "should_send_location\": true" in response_text.lower()
                return {
                    "should_suggest": should_suggest,
                    "confidence": 0.7 if should_suggest else 0.3,
                    "reason": response_text[:100],
                    "caller_type": "unknown",
                    "method": "claude_fallback"
                }
                
        except Exception as e:
            logger.error(f"Claude detection failed, falling back to keywords: {e}")
            # Fall back to keyword detection
            result = self.detect_delivery_context(conversation_text)
            result["method"] = "keyword_fallback"
            return result
    
    def get_queue_status(self) -> list[dict]:
        """Get status of all queued messages."""
        return [
            {
                "call_sid": q.call_sid,
                "to_number": q.to_number,
                "queued_at": q.queued_at,
                "delay_seconds": q.delay_seconds,
                "status": q.status
            }
            for q in self._queued_messages.values()
        ]


# Singleton instance
_messaging_service: Optional[MessagingService] = None


def get_messaging_service() -> MessagingService:
    """Get or create the messaging service singleton."""
    global _messaging_service
    if _messaging_service is None:
        _messaging_service = MessagingService()
    return _messaging_service