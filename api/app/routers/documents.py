"""
Document upload and extraction routes.
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse
from pathlib import Path
import shutil
import uuid
from datetime import datetime

from app.services.extractor import DocumentExtractor
from app.services.knowledge import KnowledgeService

router = APIRouter()

UPLOAD_DIR = Path("/app/data/documents/raw")
PROCESSED_DIR = Path("/app/data/documents/processed")
EXTRACTIONS_DIR = Path("/app/data/extractions")


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """Upload a document for extraction."""
    
    # Validate file type
    allowed_types = {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/webp"
    }
    
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"File type {file.content_type} not supported. Use PDF, JPEG, PNG, or WebP."
        )
    
    # Generate unique filename
    ext = Path(file.filename).suffix
    doc_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
    file_path = UPLOAD_DIR / doc_id
    
    # Ensure directory exists
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    
    # Save file
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    return {
        "document_id": doc_id,
        "filename": file.filename,
        "status": "uploaded",
        "message": "Document uploaded. Call /extract/{document_id} to process."
    }


@router.post("/extract/{document_id}")
async def extract_document(document_id: str, request: Request):
    """Extract information from an uploaded document."""
    
    file_path = UPLOAD_DIR / document_id
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Run extraction
    extractor = DocumentExtractor()
    result = await extractor.extract(file_path)
    
    # Ensure directory exists
    EXTRACTIONS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Save extraction result
    extraction_path = EXTRACTIONS_DIR / f"{document_id}.json"
    import json
    with open(extraction_path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    return {
        "document_id": document_id,
        "extraction": result,
        "status": "extracted"
    }


@router.post("/approve/{document_id}")
async def approve_extraction(document_id: str, request: Request):
    """Approve extraction and merge into knowledge base."""
    
    extraction_path = EXTRACTIONS_DIR / f"{document_id}.json"
    
    if not extraction_path.exists():
        raise HTTPException(status_code=404, detail="Extraction not found")
    
    import json
    with open(extraction_path) as f:
        extraction = json.load(f)
    
    # Merge into knowledge
    knowledge: KnowledgeService = request.app.state.knowledge
    conflicts = knowledge.merge(extraction)
    knowledge.save()
    
    # Ensure processed directory exists
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    
    # Move document to processed
    raw_path = UPLOAD_DIR / document_id
    if raw_path.exists():
        shutil.move(str(raw_path), str(PROCESSED_DIR / document_id))
    
    return {
        "status": "approved",
        "conflicts": conflicts,
        "message": "Extraction merged into knowledge base"
    }


@router.delete("/discard/{document_id}")
async def discard_extraction(document_id: str):
    """Discard an extraction and optionally the source document."""
    
    extraction_path = EXTRACTIONS_DIR / f"{document_id}.json"
    raw_path = UPLOAD_DIR / document_id
    
    deleted = []
    
    if extraction_path.exists():
        extraction_path.unlink()
        deleted.append("extraction")
    
    if raw_path.exists():
        raw_path.unlink()
        deleted.append("document")
    
    if not deleted:
        raise HTTPException(status_code=404, detail="Nothing found to discard")
    
    return {
        "status": "discarded",
        "deleted": deleted
    }


@router.get("/pending")
async def list_pending_documents():
    """List documents awaiting extraction or approval."""
    
    pending = []
    
    # Ensure directory exists
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    EXTRACTIONS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Documents awaiting extraction (skip dotfiles)
    for path in UPLOAD_DIR.glob("*"):
        if path.is_file() and not path.name.startswith("."):
            extraction_exists = (EXTRACTIONS_DIR / f"{path.name}.json").exists()
            pending.append({
                "document_id": path.name,
                "status": "extracted" if extraction_exists else "uploaded",
                "uploaded_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat()
            })
    
    return {"pending": pending}


@router.get("/extraction/{document_id}")
async def get_extraction(document_id: str):
    """Get extraction result for a document."""
    
    extraction_path = EXTRACTIONS_DIR / f"{document_id}.json"
    
    if not extraction_path.exists():
        raise HTTPException(status_code=404, detail="Extraction not found")
    
    import json
    with open(extraction_path) as f:
        return json.load(f)
