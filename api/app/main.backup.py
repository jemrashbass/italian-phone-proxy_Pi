"""
Italian Phone Proxy - Main FastAPI Application

AI Voice Agent for Managing Italian Phone Calls.
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
import os

from app.routers import documents, config, twilio, calls, dashboard, analytics, system_config
from app.services.knowledge import KnowledgeService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("🚀 Starting Italian Phone Proxy...")
    
    # Initialize knowledge service
    app.state.knowledge = KnowledgeService()
    app.state.knowledge.load()
    logger.info(f"📚 Knowledge loaded: {app.state.knowledge.data.get('identity', {}).get('name', 'Unknown')}")
    
    # Connect analytics service to dashboard broadcaster
    from app.services.analytics import get_analytics_service
    from app.routers.dashboard import broadcaster
    analytics_service = get_analytics_service()
    analytics_service.set_broadcaster(broadcaster)
    logger.info("📊 Analytics service connected to broadcaster")
    
    # Initialize system config service
    from app.services.system_config import get_system_config_service
    config_service = get_system_config_service()
    config_service.load()
    logger.info(f"⚙️ System config loaded (v{config_service.config.version})")
    
    # Log configuration
    logger.info(f"🔑 Anthropic API: {'configured' if os.getenv('ANTHROPIC_API_KEY') else 'MISSING'}")
    logger.info(f"🔑 OpenAI API: {'configured' if os.getenv('OPENAI_API_KEY') else 'MISSING'}")
    logger.info(f"🔑 Twilio: {'configured' if os.getenv('TWILIO_ACCOUNT_SID') else 'MISSING'}")
    
    yield
    
    logger.info("👋 Shutting down Italian Phone Proxy...")


app = FastAPI(
    title="Italian Phone Proxy",
    description="AI Voice Agent for Managing Italian Phone Calls",
    version="0.3.0",
    lifespan=lifespan
)

# CORS for dashboard and external access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all for now - tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(documents.router, prefix="/api/documents", tags=["Documents"])
app.include_router(config.router, prefix="/api/config", tags=["Configuration"])
app.include_router(system_config.router, prefix="/api/config", tags=["System Configuration"])
app.include_router(twilio.router, prefix="/api/twilio", tags=["Twilio"])
app.include_router(calls.router, prefix="/api/calls", tags=["Calls"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["Analytics"])

# Static files (dashboard) - must be last
# Check if static directory exists before mounting
import os
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/dashboard", StaticFiles(directory=static_dir, html=True), name="static")
else:
    logger.warning(f"Static directory not found: {static_dir}")


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring and Cloudflare Tunnel."""
    return {
        "status": "healthy",
        "service": "italian-phone-proxy",
        "version": "0.3.0",
        "features": {
            "documents": True,
            "telephony": True,
            "whisper": bool(os.getenv("OPENAI_API_KEY")),
            "claude": bool(os.getenv("ANTHROPIC_API_KEY")),
            "twilio": bool(os.getenv("TWILIO_ACCOUNT_SID")),
            "analytics": True,
            "system_config": True
        }
    }


@app.get("/api/status")
async def api_status():
    """Detailed API status including knowledge, active calls, and dashboard."""
    from app.routers.twilio import active_calls as twilio_calls
    from app.routers.dashboard import active_calls as dashboard_calls, dashboard_clients
    from app.services.system_config import get_system_config_service
    
    config_service = get_system_config_service()
    
    return {
        "service": "italian-phone-proxy",
        "status": "healthy",
        "knowledge_loaded": hasattr(app.state, 'knowledge'),
        "identity": app.state.knowledge.data.get("identity", {}).get("name") if hasattr(app.state, 'knowledge') else None,
        "active_calls": len(dashboard_calls),
        "dashboard_clients": len(dashboard_clients),
        "calls": list(dashboard_calls.values()),
        "config_version": config_service.config.version
    }
