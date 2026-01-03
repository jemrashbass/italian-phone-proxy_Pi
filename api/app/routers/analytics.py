"""
Analytics API Router.

Provides endpoints for accessing call analytics data and insights.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from app.services.analytics import get_analytics_service
from app.services.insights import get_insights_service
from app.services.system_config import get_system_config_service

router = APIRouter()


@router.get("/calls")
async def list_calls(limit: int = Query(50, ge=1, le=200)):
    """
    List calls with analytics summaries.
    
    Returns most recent calls first with key metrics.
    """
    service = get_analytics_service()
    calls = service.list_calls(limit=limit)
    return {"calls": calls, "count": len(calls)}


@router.get("/call/{call_sid}")
async def get_call(call_sid: str):
    """
    Get full analytics for a specific call.
    
    Returns events, turns, and summary.
    """
    service = get_analytics_service()
    call_data = service.get_call(call_sid)
    
    if not call_data:
        raise HTTPException(status_code=404, detail=f"Call {call_sid} not found")
    
    return call_data


@router.get("/call/{call_sid}/events")
async def get_call_events(call_sid: str):
    """
    Get raw event stream for a call.
    
    Returns chronological list of all instrumentation events.
    """
    service = get_analytics_service()
    events = service.get_events(call_sid)
    
    if not events:
        raise HTTPException(status_code=404, detail=f"Events for call {call_sid} not found")
    
    return {"call_sid": call_sid, "events": events}


@router.get("/call/{call_sid}/turns")
async def get_call_turns(call_sid: str):
    """
    Get computed turn metrics for a call.
    
    Returns turn-by-turn latency breakdown and quality flags.
    """
    service = get_analytics_service()
    call_data = service.get_call(call_sid)
    
    if not call_data:
        raise HTTPException(status_code=404, detail=f"Call {call_sid} not found")
    
    return {"call_sid": call_sid, "turns": call_data.get("turns", [])}


@router.get("/aggregate")
async def get_aggregate_stats(days: int = Query(7, ge=1, le=30)):
    """
    Get aggregate statistics across recent calls.
    
    Useful for identifying systemic issues and trends.
    """
    service = get_analytics_service()
    return service.get_aggregate_stats(days=days)


@router.get("/compare")
async def compare_calls(call_sids: str = Query(..., description="Comma-separated call SIDs")):
    """
    Side-by-side comparison of multiple calls.
    
    Useful for A/B testing configuration changes.
    """
    service = get_analytics_service()
    sids = [s.strip() for s in call_sids.split(",")]
    
    results = []
    for sid in sids:
        call_data = service.get_call(sid)
        if call_data:
            results.append({
                "call_sid": sid,
                "analytics": call_data.get("analytics", {}),
                "turn_count": len(call_data.get("turns", []))
            })
    
    return {"calls": results}


# =============================================================================
# INSIGHTS ENDPOINTS
# =============================================================================

@router.get("/call/{call_sid}/insights")
async def get_call_insights(call_sid: str):
    """
    Get AI-powered insights and recommendations for a call.
    
    Uses Claude to analyze the call's performance data and suggest
    parameter changes for optimization.
    
    Returns:
        - Assessment summary
        - Performance rating
        - Specific recommendations with priority
        - Quick wins
        - Items requiring investigation
    """
    analytics_service = get_analytics_service()
    insights_service = get_insights_service()
    config_service = get_system_config_service()
    
    # Get call data
    call_data = analytics_service.get_call(call_sid)
    if not call_data:
        raise HTTPException(status_code=404, detail=f"Call {call_sid} not found")
    
    # Get current config
    current_config = config_service.get_flat_config()
    
    # Generate insights
    insights = await insights_service.analyze_call(call_data, current_config)
    
    return insights.to_dict()


@router.post("/compare-impact")
async def compare_call_impact(
    before_call_sid: str = Query(..., description="Call SID before config changes"),
    after_call_sid: str = Query(..., description="Call SID after config changes")
):
    """
    Compare two calls to measure impact of configuration changes.
    
    Provides before/after metrics and calculated deltas.
    """
    analytics_service = get_analytics_service()
    insights_service = get_insights_service()
    config_service = get_system_config_service()
    
    # Get call data
    before_call = analytics_service.get_call(before_call_sid)
    after_call = analytics_service.get_call(after_call_sid)
    
    if not before_call:
        raise HTTPException(status_code=404, detail=f"Call {before_call_sid} not found")
    if not after_call:
        raise HTTPException(status_code=404, detail=f"Call {after_call_sid} not found")
    
    # Get config changes between calls
    history = config_service.get_history(limit=20)
    
    # Filter to changes between the two calls
    # (This is a simplified approach - could be more precise with timestamps)
    recent_changes = history[:5] if history else []
    
    comparison = await insights_service.compare_calls(
        before_call=before_call,
        after_call=after_call,
        config_changes=recent_changes
    )
    
    return comparison
