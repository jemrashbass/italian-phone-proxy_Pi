"""
Dashboard WebSocket router for real-time call monitoring.

Broadcasts call events to connected dashboard clients.
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Set, Dict, Any
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
            "turns": []
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


# Global broadcaster instance
broadcaster = DashboardBroadcaster()


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
                    if data.get("type") == "ping":
                        await websocket.send_text(json.dumps({
                            "type": "pong",
                            "timestamp": datetime.now().isoformat()
                        }))
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
        "calls": list(active_calls.values())
    }


@router.post("/test")
async def test_broadcast():
    """
    TEST ENDPOINT: Trigger a fake call to verify WebSocket broadcast works.
    
    Usage: curl -X POST https://phone.rashbass.org/api/dashboard/test
    
    This simulates a complete call flow to verify the dashboard receives messages.
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
    
    await broadcaster.processing_status(test_call_sid, "thinking")
    await asyncio.sleep(0.3)
    
    await broadcaster.transcript_update(
        test_call_sid,
        "ai",
        "Sì, è l'indirizzo giusto. Via Paolo Barachini 86, San Giuliano Terme.",
        2,
        latency_ms=850
    )
    await asyncio.sleep(0.5)
    
    await broadcaster.call_ended(test_call_sid, duration_seconds=15)
    
    logger.info(f"🧪 TEST: Completed fake call {test_call_sid}")
    
    return {
        "status": "test_complete",
        "call_sid": test_call_sid,
        "message": "Check the dashboard - you should have seen a fake call appear and complete"
    }