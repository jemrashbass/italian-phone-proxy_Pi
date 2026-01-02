"""
Call history and outbound call management.

Provides:
- /history - List all past calls with transcripts
- /transcript/{call_sid} - Get full transcript for a call
- /outbound - Initiate outbound calls
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)

TRANSCRIPTS_DIR = Path("/app/data/transcripts")


class OutboundCallRequest(BaseModel):
    """Request to initiate an outbound call."""
    to_number: str
    scenario: Optional[str] = None
    notes: Optional[str] = None


@router.get("/history")
async def get_call_history(limit: int = 50, offset: int = 0):
    """
    Get call history with transcripts.
    
    Returns list of calls sorted by most recent first.
    """
    calls = []
    
    if TRANSCRIPTS_DIR.exists():
        # Get all transcript files
        files = sorted(
            TRANSCRIPTS_DIR.glob("*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True  # Most recent first
        )
        
        # Apply pagination
        for filepath in files[offset:offset + limit]:
            try:
                with open(filepath) as f:
                    call_data = json.load(f)
                    
                # Add call_sid from filename if not in data
                if "call_sid" not in call_data:
                    call_data["call_sid"] = filepath.stem
                
                # Calculate summary stats
                turns = call_data.get("turns", [])
                caller_turns = [t for t in turns if t.get("speaker") == "caller"]
                ai_turns = [t for t in turns if t.get("speaker") == "ai"]
                
                # Get average latency
                latencies = [t.get("latency_ms") for t in turns if t.get("latency_ms")]
                avg_latency = int(sum(latencies) / len(latencies)) if latencies else None
                
                calls.append({
                    "call_sid": call_data.get("call_sid", filepath.stem),
                    "caller": call_data.get("caller", "Unknown"),
                    "called": call_data.get("called", "Unknown"),
                    "started_at": call_data.get("started_at"),
                    "ended_at": call_data.get("ended_at"),
                    "duration_seconds": call_data.get("duration_seconds"),
                    "status": call_data.get("status", "ended"),
                    "turn_count": len(turns),
                    "caller_turns": len(caller_turns),
                    "ai_turns": len(ai_turns),
                    "avg_latency_ms": avg_latency,
                    "preview": turns[0].get("text", "")[:100] if turns else None,
                    "has_transcript": len(turns) > 0
                })
                
            except Exception as e:
                logger.error(f"Error reading transcript {filepath}: {e}")
                continue
    
    return {
        "calls": calls,
        "total": len(list(TRANSCRIPTS_DIR.glob("*.json"))) if TRANSCRIPTS_DIR.exists() else 0,
        "limit": limit,
        "offset": offset
    }


@router.get("/transcript/{call_sid}")
async def get_transcript(call_sid: str):
    """
    Get full transcript for a specific call.
    
    Returns all conversation turns with timestamps.
    """
    filepath = TRANSCRIPTS_DIR / f"{call_sid}.json"
    
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Transcript not found")
    
    try:
        with open(filepath) as f:
            call_data = json.load(f)
        
        return {
            "call_sid": call_sid,
            "caller": call_data.get("caller"),
            "called": call_data.get("called"),
            "started_at": call_data.get("started_at"),
            "ended_at": call_data.get("ended_at"),
            "duration_seconds": call_data.get("duration_seconds"),
            "status": call_data.get("status"),
            "turns": call_data.get("turns", [])
        }
        
    except Exception as e:
        logger.error(f"Error reading transcript {call_sid}: {e}")
        raise HTTPException(status_code=500, detail="Error reading transcript")


@router.get("/stats")
async def get_call_stats():
    """
    Get aggregate statistics about calls.
    """
    if not TRANSCRIPTS_DIR.exists():
        return {
            "total_calls": 0,
            "total_duration_seconds": 0,
            "avg_duration_seconds": 0,
            "avg_turns_per_call": 0,
            "avg_latency_ms": 0
        }
    
    total_calls = 0
    total_duration = 0
    total_turns = 0
    all_latencies = []
    calls_today = 0
    calls_this_week = 0
    
    today = datetime.now().date()
    
    for filepath in TRANSCRIPTS_DIR.glob("*.json"):
        try:
            with open(filepath) as f:
                call_data = json.load(f)
            
            total_calls += 1
            
            # Duration
            duration = call_data.get("duration_seconds", 0)
            if duration:
                total_duration += duration
            
            # Turns
            turns = call_data.get("turns", [])
            total_turns += len(turns)
            
            # Latencies
            for turn in turns:
                if turn.get("latency_ms"):
                    all_latencies.append(turn["latency_ms"])
            
            # Date stats
            started = call_data.get("started_at")
            if started:
                try:
                    call_date = datetime.fromisoformat(started).date()
                    if call_date == today:
                        calls_today += 1
                    days_ago = (today - call_date).days
                    if days_ago < 7:
                        calls_this_week += 1
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"Error reading {filepath} for stats: {e}")
            continue
    
    return {
        "total_calls": total_calls,
        "calls_today": calls_today,
        "calls_this_week": calls_this_week,
        "total_duration_seconds": total_duration,
        "avg_duration_seconds": int(total_duration / total_calls) if total_calls else 0,
        "total_turns": total_turns,
        "avg_turns_per_call": round(total_turns / total_calls, 1) if total_calls else 0,
        "avg_latency_ms": int(sum(all_latencies) / len(all_latencies)) if all_latencies else 0
    }


@router.post("/outbound")
async def initiate_outbound_call(request: OutboundCallRequest):
    """
    Initiate an outbound call.
    
    This is a placeholder - full implementation requires
    Twilio outbound call setup.
    """
    logger.info(f"Outbound call requested to {request.to_number}")
    
    # TODO: Implement outbound calling
    # 1. Create TwiML for outbound call
    # 2. Use Twilio client to initiate call
    # 3. Connect to same WebSocket handler
    
    return {
        "status": "not_implemented",
        "message": "Outbound calls coming soon",
        "requested_number": request.to_number
    }


@router.delete("/transcript/{call_sid}")
async def delete_transcript(call_sid: str):
    """Delete a call transcript."""
    filepath = TRANSCRIPTS_DIR / f"{call_sid}.json"
    
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Transcript not found")
    
    try:
        os.remove(filepath)
        logger.info(f"Deleted transcript {call_sid}")
        return {"status": "deleted", "call_sid": call_sid}
    except Exception as e:
        logger.error(f"Error deleting transcript {call_sid}: {e}")
        raise HTTPException(status_code=500, detail="Error deleting transcript")