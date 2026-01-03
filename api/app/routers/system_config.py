"""
System Configuration API Router.

Provides endpoints for viewing and modifying system configuration.
Extends the existing config router with system-level settings.
"""
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, Optional, List

from app.services.system_config import get_system_config_service

router = APIRouter()


class SystemConfigUpdate(BaseModel):
    """Model for updating a single config parameter."""
    path: str  # Dot-notation path, e.g., "audio.silence_duration_ms"
    value: Any
    source: str = "api"  # "api", "manual", "recommendation"
    recommendation_id: Optional[str] = None


class MultiConfigUpdate(BaseModel):
    """Model for updating multiple config parameters."""
    updates: List[SystemConfigUpdate]
    source: str = "api"


# =============================================================================
# SYSTEM CONFIG ENDPOINTS
# =============================================================================

@router.get("/system")
async def get_system_config():
    """
    Get current system configuration.
    
    Returns complete configuration organized by section.
    """
    service = get_system_config_service()
    config = service.config
    
    return {
        "config": config.to_dict(),
        "flat": service.get_flat_config(),
        "metadata": service.get_parameter_metadata()
    }


@router.get("/system/flat")
async def get_flat_config():
    """
    Get configuration as flat key-value pairs.
    
    Useful for simple display and editing.
    """
    service = get_system_config_service()
    return service.get_flat_config()


@router.get("/system/metadata")
async def get_config_metadata():
    """
    Get metadata about all configurable parameters.
    
    Includes validation rules, descriptions, and UI hints.
    """
    service = get_system_config_service()
    return service.get_parameter_metadata()


@router.patch("/system")
async def update_system_config(update: SystemConfigUpdate):
    """
    Update a single system configuration parameter.
    
    Changes take effect immediately without restart.
    """
    service = get_system_config_service()
    
    try:
        change = service.set(
            path=update.path,
            value=update.value,
            source=update.source,
            recommendation_id=update.recommendation_id
        )
        return {"status": "updated", "change": change}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/system/batch")
async def update_system_config_batch(updates: MultiConfigUpdate):
    """
    Update multiple system configuration parameters at once.
    
    All changes are applied atomically.
    """
    service = get_system_config_service()
    
    try:
        changes = service.set_multiple(
            updates=[{"path": u.path, "value": u.value, "recommendation_id": u.recommendation_id} 
                    for u in updates.updates],
            source=updates.source
        )
        return {"status": "updated", "changes": changes}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/system/history")
async def get_config_history(limit: int = 50):
    """
    Get recent configuration change history.
    
    Shows what changed, when, and why.
    """
    service = get_system_config_service()
    history = service.get_history(limit=limit)
    
    return {
        "history": history,
        "count": len(history)
    }


@router.post("/system/reload")
async def reload_system_config():
    """
    Reload system configuration from disk.
    
    Useful if config file was edited externally.
    """
    service = get_system_config_service()
    config = service.load()
    
    return {
        "status": "reloaded",
        "version": config.version,
        "updated_at": config.updated_at
    }


@router.get("/system/{section}")
async def get_config_section(section: str):
    """
    Get a specific section of system configuration.
    
    Valid sections: audio, claude, tts, analytics
    """
    service = get_system_config_service()
    config = service.config
    
    section_map = {
        "audio": config.audio,
        "claude": config.claude,
        "tts": config.tts,
        "analytics": config.analytics
    }
    
    if section not in section_map:
        raise HTTPException(
            status_code=404, 
            detail=f"Unknown section: {section}. Valid sections: {list(section_map.keys())}"
        )
    
    return {
        "section": section,
        "config": section_map[section].to_dict()
    }
