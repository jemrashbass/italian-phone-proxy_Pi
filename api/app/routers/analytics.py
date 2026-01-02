"""
Analytics API router.

Provides endpoints for:
- Listing calls with analytics summaries
- Getting detailed analytics for a specific call
- Retrieving raw event streams
- Aggregate statistics across calls
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.services.analytics import get_analytics_service

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/calls")
async def list_calls(
    limit: int = Query(default=50, ge=1, le=200, description="Maximum calls to return")
):
    """
    List calls with analytics summaries.
    
    Returns most recent calls first with key metrics:
    - call_sid, caller, started_at
    - duration, turns, avg_latency_ms
    - quality_flags (issues detected)
    """
    analytics = get_analytics_service()
    calls = analytics.list_calls(limit=limit)
    
    return {
        "calls": calls,
        "count": len(calls)
    }


@router.get("/call/{call_sid}")
async def get_call_analytics(call_sid: str):
    """
    Get full analytics for a specific call.
    
    Returns:
    - events: Raw event stream
    - turns: Computed turn metrics with latency breakdown
    - analytics: Call-level summary statistics
    """
    analytics = get_analytics_service()
    call_data = analytics.get_call(call_sid)
    
    if not call_data:
        raise HTTPException(status_code=404, detail=f"Call {call_sid} not found")
    
    return call_data


@router.get("/call/{call_sid}/events")
async def get_call_events(call_sid: str):
    """
    Get raw event stream for a call.
    
    Useful for detailed timeline rendering.
    """
    analytics = get_analytics_service()
    events = analytics.get_events(call_sid)
    
    if not events:
        raise HTTPException(status_code=404, detail=f"No events found for call {call_sid}")
    
    return {
        "call_sid": call_sid,
        "events": events,
        "count": len(events)
    }


@router.get("/call/{call_sid}/turns")
async def get_call_turns(call_sid: str):
    """
    Get computed turn metrics for a call.
    
    Each turn includes:
    - transcript and anchor words
    - latency breakdown (whisper, claude, tts)
    - quality flags
    """
    analytics = get_analytics_service()
    call_data = analytics.get_call(call_sid)
    
    if not call_data:
        raise HTTPException(status_code=404, detail=f"Call {call_sid} not found")
    
    return {
        "call_sid": call_sid,
        "turns": call_data.get("turns", []),
        "count": len(call_data.get("turns", []))
    }


@router.get("/aggregate")
async def get_aggregate_stats(
    days: int = Query(default=7, ge=1, le=30, description="Number of days to aggregate")
):
    """
    Get aggregate statistics across recent calls.
    
    Useful for identifying systemic issues:
    - Average latency trends
    - Common quality flags
    - Call volume
    """
    analytics = get_analytics_service()
    stats = analytics.get_aggregate_stats(days=days)
    
    return stats


@router.get("/health")
async def analytics_health():
    """
    Check analytics service health.
    
    Verifies storage is accessible.
    """
    analytics = get_analytics_service()
    
    try:
        # Try listing calls as a health check
        calls = analytics.list_calls(limit=1)
        return {
            "status": "healthy",
            "calls_stored": len(calls) > 0
        }
    except Exception as e:
        logger.error(f"Analytics health check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/compare")
async def compare_calls(
    call_sids: str = Query(..., description="Comma-separated call SIDs to compare")
):
    """
    Compare analytics across multiple calls.
    
    Useful for A/B testing parameter changes.
    """
    analytics = get_analytics_service()
    
    sids = [s.strip() for s in call_sids.split(",") if s.strip()]
    
    if len(sids) < 2:
        raise HTTPException(status_code=400, detail="Provide at least 2 call SIDs to compare")
    
    if len(sids) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 calls can be compared")
    
    comparison = []
    for sid in sids:
        call_data = analytics.get_call(sid)
        if call_data and "analytics" in call_data:
            summary = call_data["analytics"]
            comparison.append({
                "call_sid": sid,
                "duration_seconds": summary.get("duration_seconds", 0),
                "turns": summary.get("total_turns", 0),
                "avg_total_ms": summary.get("avg_total_ms", 0),
                "avg_whisper_ms": summary.get("avg_whisper_ms", 0),
                "avg_claude_ms": summary.get("avg_claude_ms", 0),
                "avg_tts_ms": summary.get("avg_tts_ms", 0),
                "avg_confidence": summary.get("avg_whisper_confidence", 0),
                "flags": list(summary.get("flags_summary", {}).keys())
            })
    
    if not comparison:
        raise HTTPException(status_code=404, detail="No valid calls found")
    
    return {
        "calls": comparison,
        "summary": {
            "avg_latency_range": f"{min(c['avg_total_ms'] for c in comparison)}-{max(c['avg_total_ms'] for c in comparison)}ms",
            "total_turns": sum(c["turns"] for c in comparison)
        }
    }