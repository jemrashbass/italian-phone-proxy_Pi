"""
Configuration and knowledge management routes.
"""
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, Optional

router = APIRouter()


class KnowledgeUpdate(BaseModel):
    """Model for partial knowledge updates."""
    path: str  # Dot-notation path, e.g., "identity.name"
    value: Any


@router.get("/knowledge")
async def get_knowledge(request: Request):
    """Get the full knowledge base."""
    return request.app.state.knowledge.data


@router.get("/knowledge/{section}")
async def get_knowledge_section(section: str, request: Request):
    """Get a specific section of the knowledge base."""
    data = request.app.state.knowledge.data
    
    if section not in data:
        raise HTTPException(status_code=404, detail=f"Section '{section}' not found")
    
    return {section: data[section]}


@router.patch("/knowledge")
async def update_knowledge(update: KnowledgeUpdate, request: Request):
    """Update a specific field in the knowledge base."""
    knowledge = request.app.state.knowledge
    
    # Navigate to the field using dot notation
    parts = update.path.split(".")
    target = knowledge.data
    
    for part in parts[:-1]:
        if part not in target:
            target[part] = {}
        target = target[part]
    
    # Set the value
    old_value = target.get(parts[-1])
    target[parts[-1]] = update.value
    
    # Save changes
    knowledge.save()
    
    return {
        "status": "updated",
        "path": update.path,
        "old_value": old_value,
        "new_value": update.value
    }


@router.post("/knowledge/reload")
async def reload_knowledge(request: Request):
    """Reload knowledge from disk."""
    request.app.state.knowledge.load()
    return {"status": "reloaded"}


@router.get("/prompt")
async def get_system_prompt(request: Request):
    """Get the formatted system prompt with current knowledge."""
    knowledge_json = request.app.state.knowledge.get_for_prompt()
    
    # This is a simplified version - the full prompt will be in app/prompts/system.py
    prompt = f"""Sei un assistente vocale italiano che risponde alle chiamate per conto del proprietario.

CONOSCENZA:
{knowledge_json}

REGOLE:
- Parla lentamente e chiaramente
- Conferma sempre i dettagli importanti
- Non fornire mai dati bancari
- In caso di dubbio, offri di far richiamare il proprietario
"""
    
    return {"prompt": prompt}
