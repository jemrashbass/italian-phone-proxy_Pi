"""
Italian Phone Proxy - Main FastAPI Application
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from app.routers import documents, config, twilio, calls
from app.services.knowledge import KnowledgeService

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("Starting Italian Phone Proxy...")
    
    # Initialize knowledge service
    app.state.knowledge = KnowledgeService()
    app.state.knowledge.load()
    
    yield
    
    logger.info("Shutting down...")


app = FastAPI(
    title="Italian Phone Proxy",
    description="AI Voice Agent for Managing Italian Phone Calls",
    version="0.1.0",
    lifespan=lifespan
)

# CORS for dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(documents.router, prefix="/api/documents", tags=["Documents"])
app.include_router(config.router, prefix="/api/config", tags=["Configuration"])
app.include_router(twilio.router, prefix="/api/twilio", tags=["Twilio"])
app.include_router(calls.router, prefix="/api/calls", tags=["Calls"])

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "italian-phone-proxy"}


# Static files (dashboard)
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")


