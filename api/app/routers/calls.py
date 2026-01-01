"""
Call history and management routes.
"""
from fastapi import APIRouter, HTTPException
from pathlib import Path
from datetime import datetime
import json
from typing import Optional

router = APIRouter()

TRANSCRIPTS_DIR = Path("/app/data/transcripts")


@router.get("/history")
async def get_call_history(limit: int = 20, offset: int = 0):
    """Get call history with transcripts."""
    
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Get all transcript files, sorted by modification time (newest first)
    files = sorted(
        TRANSCRIPTS_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    
    # Paginate
    paginated = files[offset:offset + limit]
    
    calls = []
    for path in paginated:
        with open(path) as f:
            call_data = json.load(f)
            calls.append({
                "call_id": path.stem,
                "timestamp": call_data.get("timestamp"),
                "caller": call_data.get("caller"),
                "duration": call_data.get("duration"),
                "summary": call_data.get("summary", ""),
                "status": call_data.get("status", "completed")
            })
    
    return {
        "calls": calls,
        "total": len(files),
        "limit": limit,
        "offset": offset
    }


@router.get("/history/{call_id}")
async def get_call_detail(call_id: str):
    """Get full details and transcript for a specific call."""
    
    path = TRANSCRIPTS_DIR / f"{call_id}.json"
    
    if not path.exists():
        raise HTTPException(status_code=404, detail="Call not found")
    
    with open(path) as f:
        return json.load(f)


@router.get("/active")
async def get_active_call():
    """Get currently active call info (for dashboard)."""
    
    # TODO: Implement active call tracking
    # This will be populated when a call is in progress
    
    return {
        "active": False,
        "call_id": None,
        "caller": None,
        "started_at": None,
        "transcript": []
    }


@router.post("/test")
async def create_test_call():
    """Create a test call record for development."""
    
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    
    call_id = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    test_data = {
        "call_id": call_id,
        "timestamp": datetime.now().isoformat(),
        "caller": "+39 333 123 4567",
        "called": "+39 06 123 4567",
        "duration": 45,
        "status": "completed",
        "summary": "Test call for development",
        "transcript": [
            {
                "speaker": "caller",
                "text": "Pronto, buongiorno. Sono il corriere.",
                "timestamp": "00:00:02"
            },
            {
                "speaker": "ai",
                "text": "Buongiorno. Sì, mi dica.",
                "timestamp": "00:00:05"
            },
            {
                "speaker": "caller",
                "text": "Ho un pacco per lei. Dove posso lasciarlo?",
                "timestamp": "00:00:08"
            },
            {
                "speaker": "ai",
                "text": "Può lasciare il pacco dal vicino, per favore.",
                "timestamp": "00:00:12"
            }
        ]
    }
    
    with open(TRANSCRIPTS_DIR / f"{call_id}.json", "w") as f:
        json.dump(test_data, f, indent=2, ensure_ascii=False)
    
    return {
        "status": "created",
        "call_id": call_id,
        "message": "Test call record created"
    }
