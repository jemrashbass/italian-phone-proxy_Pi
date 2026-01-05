"""
Dashboard WebSocket router for real-time call monitoring.

Broadcasts call events to connected dashboard clients.
Includes location send notifications for delivery drivers.
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Set, Dict, Any, Optional
import asyncio
import json
import logging
from datetime import datetime

router = APIRouter()
logger = logging.getLogger(__name__)

# Connected dashboard clients
dashboard_clients: Set[WebSocket] = set()

# Current call state for new connections
active_calls: Dict[str, Dict[str, Any]] = {}

# Pending location sends (call_sid -> task)
pending_location_sends: Dict[str, asyncio.Task] = {}


class DashboardBroadcaster:
    """Singleton broadcaster for dashboard events."""
    
    @staticmethod
    async def broadcast(event: Dict[str, Any]):
        """Broadcast event to all connected dashboard clients."""
        client_count = len(dashboard_clients)
        logger.info(f"📡 Broadcasting {event.get('type')} to {client_count} clients")
        
        if not dashboard_clients:
            logger.warning("📡 No dashboard clients connected - broadcast skipped")
            return
            
        message = json.dumps(event, default=str)
        disconnected = set()
        
        for client in dashboard_clients:
            try:
                await client.send_text(message)
                logger.debug(f"📡 Sent to client successfully")
            except Exception as e:
                logger.warning(f"📡 Failed to send to dashboard client: {e}")
                disconnected.add(client)
        
        # Clean up disconnected clients
        for client in disconnected:
            dashboard_clients.discard(client)
        
        logger.info(f"📡 Broadcast complete: {event.get('type')}")
    
    @staticmethod
    async def call_started(call_sid: str, caller: str, called: str):
        """Notify dashboard that a call has started."""
        logger.info(f"📡 call_started: {call_sid} from {caller}")
        
        active_calls[call_sid] = {
            "call_sid": call_sid,
            "caller": caller,
            "called": called,
            "started_at": datetime.now().isoformat(),
            "status": "connected",
            "turns": [],
            "location_send_pending": False
        }
        
        await DashboardBroadcaster.broadcast({
            "type": "call_started",
            "call_sid": call_sid,
            "caller": caller,
            "called": called,
            "timestamp": datetime.now().isoformat()
        })
    
    @staticmethod
    async def transcript_update(call_sid: str, speaker: str, text: str, 
                                 turn_index: int, latency_ms: int = None):
        """Notify dashboard of new transcript."""
        logger.info(f"📡 transcript_update: {speaker} said '{text[:50]}...' (turn {turn_index})")
        
        turn = {
            "index": turn_index,
            "speaker": speaker,
            "text": text,
            "timestamp": datetime.now().isoformat(),
            "latency_ms": latency_ms
        }
        
        if call_sid in active_calls:
            active_calls[call_sid]["turns"].append(turn)
        
        await DashboardBroadcaster.broadcast({
            "type": "transcript",
            "call_sid": call_sid,
            "speaker": speaker,
            "text": text,
            "turn_index": turn_index,
            "latency_ms": latency_ms,
            "timestamp": datetime.now().isoformat()
        })
    
    @staticmethod
    async def processing_status(call_sid: str, status: str, details: str = None):
        """Notify dashboard of processing status (transcribing, thinking, speaking)."""
        logger.info(f"📡 processing_status: {call_sid} -> {status}")
        
        await DashboardBroadcaster.broadcast({
            "type": "processing",
            "call_sid": call_sid,
            "status": status,
            "details": details,
            "timestamp": datetime.now().isoformat()
        })
    
    @staticmethod
    async def call_ended(call_sid: str, duration_seconds: int = None, 
                         summary: str = None):
        """Notify dashboard that a call has ended."""
        logger.info(f"📡 call_ended: {call_sid} (duration: {duration_seconds}s)")
        
        # Cancel any pending location send
        if call_sid in pending_location_sends:
            pending_location_sends[call_sid].cancel()
            del pending_location_sends[call_sid]
        
        if call_sid in active_calls:
            del active_calls[call_sid]
        
        await DashboardBroadcaster.broadcast({
            "type": "call_ended",
            "call_sid": call_sid,
            "duration_seconds": duration_seconds,
            "summary": summary,
            "timestamp": datetime.now().isoformat()
        })
    
    @staticmethod
    async def error(call_sid: str, error_type: str, message: str):
        """Notify dashboard of an error."""
        logger.error(f"📡 error: {call_sid} - {error_type}: {message}")
        
        await DashboardBroadcaster.broadcast({
            "type": "error",
            "call_sid": call_sid,
            "error_type": error_type,
            "message": message,
            "timestamp": datetime.now().isoformat()
        })

    @staticmethod
    async def analytics_event(call_sid: str, event: dict):
        """Broadcast analytics event for real-time dashboard updates."""
        await DashboardBroadcaster.broadcast({
            "type": "analytics_event",
            "call_sid": call_sid,
            "event": event,
            "timestamp": datetime.now().isoformat()
        })

    @staticmethod
    async def location_send_pending(
        call_sid: str, 
        caller: str,
        confidence: float,
        reason: str,
        timeout_seconds: int = 30
    ):
        """
        Notify dashboard that location SMS should be sent.
        
        Shows notification with countdown - auto-sends after timeout unless cancelled.
        """
        logger.info(f"📍 Location send pending for {call_sid} (confidence: {confidence:.0%})")
        
        if call_sid in active_calls:
            active_calls[call_sid]["location_send_pending"] = True
        
        await DashboardBroadcaster.broadcast({
            "type": "location_send_pending",
            "call_sid": call_sid,
            "caller": caller,
            "confidence": confidence,
            "reason": reason,
            "timeout_seconds": timeout_seconds,
            "timestamp": datetime.now().isoformat()
        })
    
    @staticmethod
    async def location_sent(call_sid: str, caller: str, trigger: str, success: bool):
        """Notify dashboard that location SMS was sent (or failed)."""
        logger.info(f"📍 Location {'sent' if success else 'failed'} for {call_sid} (trigger: {trigger})")
        
        if call_sid in active_calls:
            active_calls[call_sid]["location_send_pending"] = False
            active_calls[call_sid]["location_sent"] = success
        
        await DashboardBroadcaster.broadcast({
            "type": "location_sent",
            "call_sid": call_sid,
            "caller": caller,
            "trigger": trigger,
            "success": success,
            "timestamp": datetime.now().isoformat()
        })
    
    @staticmethod
    async def location_cancelled(call_sid: str):
        """Notify dashboard that location send was cancelled."""
        logger.info(f"📍 Location send cancelled for {call_sid}")
        
        if call_sid in active_calls:
            active_calls[call_sid]["location_send_pending"] = False
        
        await DashboardBroadcaster.broadcast({
            "type": "location_cancelled",
            "call_sid": call_sid,
            "timestamp": datetime.now().isoformat()
        })


# Global broadcaster instance
broadcaster = DashboardBroadcaster()


async def schedule_location_send(
    call_sid: str,
    caller: str,
    timeout_seconds: int = 30
):
    """
    Schedule automatic location send after timeout.
    
    Can be cancelled by calling cancel_location_send().
    """
    from app.services.messaging import get_messaging_service
    
    async def send_after_timeout():
        try:
            await asyncio.sleep(timeout_seconds)
            
            # Check if still pending (not cancelled)
            if call_sid in active_calls and active_calls[call_sid].get("location_send_pending"):
                logger.info(f"📍 Auto-sending location to {caller} (timeout)")
                
                # For TEST calls, simulate success without actually sending SMS
                if call_sid.startswith("TEST-"):
                    logger.info(f"📍 TEST: Simulating auto SMS send to {caller}")
                    await broadcaster.location_sent(
                        call_sid, 
                        caller, 
                        "timeout", 
                        True  # Simulate success
                    )
                else:
                    # Real call - actually send SMS
                    messaging = get_messaging_service()
                    result = messaging.send_sms(to_number=caller)
                    
                    await broadcaster.location_sent(
                        call_sid, 
                        caller, 
                        "timeout", 
                        result.success
                    )
        except asyncio.CancelledError:
            logger.info(f"📍 Location send cancelled for {call_sid}")
        except Exception as e:
            logger.error(f"📍 Location send error: {e}")
    
    # Cancel any existing task for this call
    if call_sid in pending_location_sends:
        pending_location_sends[call_sid].cancel()
    
    # Schedule new task
    task = asyncio.create_task(send_after_timeout())
    pending_location_sends[call_sid] = task


def cancel_location_send(call_sid: str) -> bool:
    """Cancel pending location send for a call."""
    if call_sid in pending_location_sends:
        pending_location_sends[call_sid].cancel()
        del pending_location_sends[call_sid]
        return True
    return False


@router.websocket("/ws")
async def dashboard_websocket(websocket: WebSocket):
    """WebSocket endpoint for dashboard real-time updates."""
    await websocket.accept()
    dashboard_clients.add(websocket)
    
    logger.info(f"📡 Dashboard client connected. Total clients: {len(dashboard_clients)}")
    
    try:
        # Send current state on connect
        await websocket.send_text(json.dumps({
            "type": "init",
            "active_calls": list(active_calls.values()),
            "timestamp": datetime.now().isoformat()
        }, default=str))
        
        # Keep connection alive and handle any client messages
        while True:
            try:
                # Wait for messages (ping/pong or commands)
                message = await asyncio.wait_for(
                    websocket.receive_text(), 
                    timeout=30.0
                )
                
                # Handle client commands
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")
                    
                    if msg_type == "ping":
                        await websocket.send_text(json.dumps({
                            "type": "pong",
                            "timestamp": datetime.now().isoformat()
                        }))
                    
                    elif msg_type == "send_location":
                        # Manual send from dashboard/app
                        call_sid = data.get("call_sid")
                        caller = data.get("caller")
                        
                        logger.info(f"📍 Received send_location request: call_sid={call_sid}, caller={caller}")
                        
                        if call_sid and caller:
                            try:
                                # Cancel timeout task
                                cancel_location_send(call_sid)
                                
                                # For TEST calls, simulate success without actually sending SMS
                                if call_sid.startswith("TEST-"):
                                    logger.info(f"📍 TEST: Simulating SMS send to {caller}")
                                    await broadcaster.location_sent(
                                        call_sid,
                                        caller,
                                        "manual",
                                        True  # Simulate success
                                    )
                                else:
                                    # Real call - actually send SMS
                                    from app.services.messaging import get_messaging_service
                                    
                                    messaging = get_messaging_service()
                                    result = messaging.send_sms(to_number=caller)
                                    
                                    logger.info(f"📍 SMS send result: success={result.success}, error={result.error}")
                                    
                                    await broadcaster.location_sent(
                                        call_sid,
                                        caller,
                                        "manual",
                                        result.success
                                    )
                            except Exception as e:
                                logger.error(f"📍 Error handling send_location: {e}", exc_info=True)
                                # Still try to notify about failure
                                await broadcaster.location_sent(
                                    call_sid,
                                    caller,
                                    "manual",
                                    False
                                )
                        else:
                            logger.warning(f"📍 send_location missing call_sid or caller")
                    
                    elif msg_type == "cancel_location":
                        # Cancel location send
                        call_sid = data.get("call_sid")
                        if call_sid:
                            cancel_location_send(call_sid)
                            await broadcaster.location_cancelled(call_sid)
                            
                except json.JSONDecodeError:
                    pass
                    
            except asyncio.TimeoutError:
                # Send heartbeat
                try:
                    await websocket.send_text(json.dumps({
                        "type": "heartbeat",
                        "active_call_count": len(active_calls),
                        "timestamp": datetime.now().isoformat()
                    }))
                except Exception:
                    break
                    
    except WebSocketDisconnect:
        logger.info("📡 Dashboard client disconnected")
    except Exception as e:
        logger.error(f"📡 Dashboard WebSocket error: {e}")
    finally:
        dashboard_clients.discard(websocket)
        logger.info(f"📡 Dashboard client removed. Total clients: {len(dashboard_clients)}")


@router.get("/status")
async def dashboard_status():
    """Get current dashboard status."""
    return {
        "connected_clients": len(dashboard_clients),
        "active_calls": len(active_calls),
        "calls": list(active_calls.values()),
        "pending_location_sends": list(pending_location_sends.keys())
    }


# =============================================================================
# TEST ENDPOINTS
# =============================================================================

@router.post("/test")
async def test_broadcast():
    """
    TEST ENDPOINT: Trigger a fake call to verify WebSocket broadcast works.
    
    Usage: curl -X POST https://phone.rashbass.org/api/dashboard/test
    
    This simulates a complete call flow to verify the dashboard receives messages.
    Quick test - completes in about 3 seconds.
    """
    import uuid
    
    test_call_sid = f"TEST-{uuid.uuid4().hex[:8]}"
    test_caller = "+39 328 TEST"
    
    logger.info(f"🧪 TEST: Starting fake call {test_call_sid}")
    
    # Simulate call flow
    await broadcaster.call_started(test_call_sid, test_caller, "+44 2070 460437")
    await asyncio.sleep(0.5)
    
    await broadcaster.processing_status(test_call_sid, "speaking")
    await asyncio.sleep(0.3)
    
    await broadcaster.transcript_update(
        test_call_sid, 
        "ai", 
        "Pronto. Mi scusi, sono inglese e il mio italiano non è perfetto.", 
        0
    )
    await asyncio.sleep(0.5)
    
    await broadcaster.processing_status(test_call_sid, "listening")
    await asyncio.sleep(1.0)
    
    await broadcaster.processing_status(test_call_sid, "transcribing")
    await asyncio.sleep(0.3)
    
    await broadcaster.transcript_update(
        test_call_sid,
        "caller",
        "Buongiorno, sono il corriere. Ho un pacco per Via Barachini.",
        1
    )
    await asyncio.sleep(0.5)
    
    # Simulate delivery detection
    await broadcaster.location_send_pending(
        test_call_sid,
        test_caller,
        confidence=0.85,
        reason="Delivery detected (corriere, pacco, Via)",
        timeout_seconds=15  # Shorter for test
    )
    
    await asyncio.sleep(0.5)
    
    await broadcaster.processing_status(test_call_sid, "thinking")
    await asyncio.sleep(0.3)
    
    await broadcaster.transcript_update(
        test_call_sid,
        "ai",
        "Sì, è l'indirizzo giusto. Via Paolo Barachini 7, San Giuliano Terme. Cancello verde.",
        2,
        latency_ms=850
    )
    await asyncio.sleep(0.5)
    
    await broadcaster.call_ended(test_call_sid, duration_seconds=15)
    
    logger.info(f"🧪 TEST: Completed fake call {test_call_sid}")
    
    return {
        "status": "test_complete",
        "call_sid": test_call_sid,
        "message": "Check the dashboard - you should have seen a fake call with location send notification"
    }


@router.post("/test-extended")
async def test_extended_call(
    duration: str = Query("medium", pattern="^(short|medium|long)$"),
    auto_end: bool = Query(True),
    location_timeout: int = Query(30, ge=10, le=120)
):
    """
    EXTENDED TEST: Simulate a realistic delivery driver conversation.
    
    Usage: 
        curl -X POST "https://phone.rashbass.org/api/dashboard/test-extended"
        curl -X POST "https://phone.rashbass.org/api/dashboard/test-extended?duration=long"
        curl -X POST "https://phone.rashbass.org/api/dashboard/test-extended?auto_end=false"
    
    Parameters:
        - duration: "short" (30s), "medium" (60s), "long" (90s)
        - auto_end: Whether to automatically end the call (default: true)
        - location_timeout: Seconds for SMS countdown (default: 30)
    
    This simulates a full delivery driver conversation with realistic timing,
    giving you time to test SMS send/cancel and other interactive features.
    """
    import uuid
    
    # Timing based on duration
    timings = {
        "short": {"pause": 2, "thinking": 1, "speaking": 1.5},
        "medium": {"pause": 4, "thinking": 2, "speaking": 2.5},
        "long": {"pause": 6, "thinking": 3, "speaking": 3.5}
    }
    t = timings[duration]
    
    test_call_sid = f"TEST-{uuid.uuid4().hex[:8]}"
    test_caller = "+39 328 232 8203"  # Realistic Italian mobile
    test_called = "+44 207 046 0437"
    
    logger.info(f"🧪 EXTENDED TEST: Starting {duration} call {test_call_sid}")
    
    # ========== CALL START ==========
    await broadcaster.call_started(test_call_sid, test_caller, test_called)
    await asyncio.sleep(1)
    
    # ========== TURN 0: AI Greeting ==========
    await broadcaster.processing_status(test_call_sid, "speaking")
    await asyncio.sleep(0.5)
    
    greeting = (
        "Pronto. Sì, sono Jeremy. "
        "Mi scusi, sono inglese e il mio italiano non è perfetto — "
        "parlo lentamente ma capisco bene. Mi dica pure."
    )
    await broadcaster.transcript_update(test_call_sid, "ai", greeting, 0)
    await asyncio.sleep(t["speaking"])
    
    await broadcaster.processing_status(test_call_sid, "listening")
    await asyncio.sleep(t["pause"])
    
    # ========== TURN 1: Caller introduces themselves ==========
    await broadcaster.processing_status(test_call_sid, "transcribing")
    await asyncio.sleep(0.8)
    
    await broadcaster.transcript_update(
        test_call_sid,
        "caller",
        "Buongiorno, sono il corriere di Amazon. Ho un pacco per Via Paolo Barachini 86.",
        1
    )
    await asyncio.sleep(0.5)
    
    # ========== LOCATION DETECTION - This is what we want to test! ==========
    await broadcaster.location_send_pending(
        test_call_sid,
        test_caller,
        confidence=0.92,
        reason="Corriere Amazon asking about Via Barachini - likely needs directions",
        timeout_seconds=location_timeout
    )
    
    await asyncio.sleep(0.3)
    await broadcaster.processing_status(test_call_sid, "thinking")
    await asyncio.sleep(t["thinking"])
    
    # ========== TURN 2: AI confirms address ==========
    await broadcaster.processing_status(test_call_sid, "speaking")
    await asyncio.sleep(0.3)
    
    await broadcaster.transcript_update(
        test_call_sid,
        "ai",
        "Sì, è l'indirizzo giusto. Sono a casa. Dove si trova adesso?",
        2,
        latency_ms=1850
    )
    await asyncio.sleep(t["speaking"])
    
    await broadcaster.processing_status(test_call_sid, "listening")
    await asyncio.sleep(t["pause"])
    
    # ========== TURN 3: Caller asks for directions ==========
    await broadcaster.processing_status(test_call_sid, "transcribing")
    await asyncio.sleep(0.6)
    
    await broadcaster.transcript_update(
        test_call_sid,
        "caller",
        "Sono sulla strada principale, vicino alla chiesa. Ma non trovo Via Barachini. Mi può aiutare?",
        3
    )
    await asyncio.sleep(0.5)
    
    await broadcaster.processing_status(test_call_sid, "thinking")
    await asyncio.sleep(t["thinking"])
    
    # ========== TURN 4: AI gives directions ==========
    await broadcaster.processing_status(test_call_sid, "speaking")
    await asyncio.sleep(0.3)
    
    await broadcaster.transcript_update(
        test_call_sid,
        "ai",
        "Dalla chiesa, giri a destra. Dopo il bar, la seconda a sinistra. Cancello verde, numero 86.",
        4,
        latency_ms=2150
    )
    await asyncio.sleep(t["speaking"])
    
    await broadcaster.processing_status(test_call_sid, "listening")
    await asyncio.sleep(t["pause"])
    
    # ========== TURN 5: Caller confirms ==========
    await broadcaster.processing_status(test_call_sid, "transcribing")
    await asyncio.sleep(0.5)
    
    await broadcaster.transcript_update(
        test_call_sid,
        "caller",
        "Ah sì, ho capito. Cancello verde. Arrivo tra cinque minuti.",
        5
    )
    await asyncio.sleep(0.5)
    
    await broadcaster.processing_status(test_call_sid, "thinking")
    await asyncio.sleep(t["thinking"] * 0.5)  # Shorter for simple response
    
    # ========== TURN 6: AI confirms and goodbye ==========
    await broadcaster.processing_status(test_call_sid, "speaking")
    await asyncio.sleep(0.3)
    
    await broadcaster.transcript_update(
        test_call_sid,
        "ai",
        "Perfetto, l'aspetto. A tra poco!",
        6,
        latency_ms=980
    )
    await asyncio.sleep(t["speaking"])
    
    await broadcaster.processing_status(test_call_sid, "listening")
    await asyncio.sleep(t["pause"] * 0.5)
    
    # ========== TURN 7: Caller goodbye ==========
    await broadcaster.processing_status(test_call_sid, "transcribing")
    await asyncio.sleep(0.4)
    
    await broadcaster.transcript_update(
        test_call_sid,
        "caller",
        "Grazie mille. Arrivederci!",
        7
    )
    await asyncio.sleep(0.5)
    
    await broadcaster.processing_status(test_call_sid, "thinking")
    await asyncio.sleep(0.8)
    
    # ========== TURN 8: AI goodbye ==========
    await broadcaster.processing_status(test_call_sid, "speaking")
    await asyncio.sleep(0.3)
    
    await broadcaster.transcript_update(
        test_call_sid,
        "ai",
        "Arrivederci!",
        8,
        latency_ms=650
    )
    await asyncio.sleep(1.5)
    
    # ========== CALL END (if auto_end) ==========
    if auto_end:
        # Calculate approximate duration
        total_duration = int(
            1 +  # initial
            t["speaking"] + t["pause"] +  # turn 0
            0.8 + 0.5 + 0.3 + t["thinking"] +  # turn 1
            0.3 + t["speaking"] + t["pause"] +  # turn 2
            0.6 + 0.5 + t["thinking"] +  # turn 3
            0.3 + t["speaking"] + t["pause"] +  # turn 4
            0.5 + 0.5 + t["thinking"] * 0.5 +  # turn 5
            0.3 + t["speaking"] + t["pause"] * 0.5 +  # turn 6
            0.4 + 0.5 + 0.8 +  # turn 7
            0.3 + 1.5  # turn 8
        )
        
        await broadcaster.call_ended(test_call_sid, duration_seconds=total_duration)
        logger.info(f"🧪 EXTENDED TEST: Completed call {test_call_sid} ({total_duration}s)")
        
        return {
            "status": "test_complete",
            "call_sid": test_call_sid,
            "duration": duration,
            "duration_seconds": total_duration,
            "location_timeout": location_timeout,
            "message": f"Extended {duration} test call completed. Check your app!"
        }
    else:
        logger.info(f"🧪 EXTENDED TEST: Call {test_call_sid} left active (auto_end=false)")
        
        return {
            "status": "call_active",
            "call_sid": test_call_sid,
            "duration": duration,
            "location_timeout": location_timeout,
            "message": (
                f"Call left active for testing. "
                f"End manually with: curl -X POST 'https://phone.rashbass.org/api/dashboard/test-end/{test_call_sid}'"
            )
        }


@router.post("/test-end/{call_sid}")
async def test_end_call(call_sid: str, duration_seconds: int = Query(60)):
    """
    Manually end a test call that was started with auto_end=false.
    
    Usage: curl -X POST "https://phone.rashbass.org/api/dashboard/test-end/TEST-abc123"
    """
    if call_sid not in active_calls:
        return {"status": "not_found", "call_sid": call_sid}
    
    await broadcaster.call_ended(call_sid, duration_seconds=duration_seconds)
    
    logger.info(f"🧪 TEST: Manually ended call {call_sid}")
    
    return {
        "status": "ended",
        "call_sid": call_sid,
        "duration_seconds": duration_seconds
    }


@router.post("/test-location-event/{call_sid}")
async def test_location_event(
    call_sid: str,
    event: str = Query(..., pattern="^(pending|sent|cancelled)$"),
    timeout: int = Query(30)
):
    """
    Trigger a location event on an active test call.
    
    Usage:
        curl -X POST "https://phone.rashbass.org/api/dashboard/test-location-event/TEST-abc?event=pending"
        curl -X POST "https://phone.rashbass.org/api/dashboard/test-location-event/TEST-abc?event=sent"
        curl -X POST "https://phone.rashbass.org/api/dashboard/test-location-event/TEST-abc?event=cancelled"
    """
    if call_sid not in active_calls:
        return {"status": "not_found", "call_sid": call_sid}
    
    caller = active_calls[call_sid].get("caller", "+39 328 TEST")
    
    if event == "pending":
        await broadcaster.location_send_pending(
            call_sid,
            caller,
            confidence=0.88,
            reason="Manual test trigger",
            timeout_seconds=timeout
        )
    elif event == "sent":
        await broadcaster.location_sent(call_sid, caller, trigger="manual", success=True)
    elif event == "cancelled":
        await broadcaster.location_cancelled(call_sid)
    
    return {
        "status": "event_sent",
        "call_sid": call_sid,
        "event": event
    }


@router.post("/test-transcript/{call_sid}")
async def test_add_transcript(
    call_sid: str,
    speaker: str = Query(..., pattern="^(caller|ai)$"),
    text: str = Query(...),
    latency_ms: int = Query(None)
):
    """
    Add a transcript turn to an active test call.
    
    Usage:
        curl -X POST "https://phone.rashbass.org/api/dashboard/test-transcript/TEST-abc?speaker=caller&text=Sono%20arrivato"
        curl -X POST "https://phone.rashbass.org/api/dashboard/test-transcript/TEST-abc?speaker=ai&text=Perfetto!&latency_ms=850"
    """
    if call_sid not in active_calls:
        return {"status": "not_found", "call_sid": call_sid}
    
    # Get current turn count
    turns = active_calls[call_sid].get("turns", [])
    turn_index = len(turns)
    
    await broadcaster.transcript_update(
        call_sid,
        speaker,
        text,
        turn_index,
        latency_ms=latency_ms
    )
    
    return {
        "status": "transcript_added",
        "call_sid": call_sid,
        "speaker": speaker,
        "turn_index": turn_index
    }


@router.post("/test-location")
async def test_location_send():
    """
    TEST ENDPOINT: Test location SMS sending.
    
    Usage: curl -X POST https://phone.rashbass.org/api/dashboard/test-location
    
    Tests the messaging service preview (doesn't actually send).
    """
    from app.services.messaging import get_messaging_service
    
    messaging = get_messaging_service()
    
    return {
        "service_enabled": messaging._twilio_client is not None,
        "preview": messaging.get_message_preview()
    }