# 🇮🇹 Italian Phone Proxy

**AI Voice Agent for Managing Italian Phone Calls**

An AI-powered phone assistant that can answer and make calls in Italian on your behalf, handling simple but essential tasks of daily life — arranging boiler services, coordinating fibre installation, directing delivery drivers.

## Overview

This is **not** a fully autonomous agent — it's a **polite Italian-speaking call buffer + interpreter + junior assistant** who can answer, listen, clarify, and bring you in at the right moment.

### Key Features

- 📄 **Document Extraction**: Upload Italian utility bills and let Claude Vision extract account numbers, addresses, and other key information
- 🧠 **Knowledge Base**: Structured storage for identity, location, accounts, and preferences
- 📞 **Phone Integration**: Twilio-based telephony with call forwarding from Italian numbers
- 🎛️ **Dashboard**: Web interface for monitoring calls, managing documents, and editing configuration
- 🔊 **Listen-In Mode**: (Phase 2) Monitor calls in real-time and intervene when needed

## Architecture

```
Italian Numbers → Call Forward → Twilio → Cloudflare Tunnel → RPi → Claude + Whisper → Dashboard
```

### Tech Stack

| Layer | Technology |
|-------|------------|
| Orchestration | Python / FastAPI |
| Telephony | Twilio |
| Speech-to-Text | Whisper API (OpenAI) |
| LLM Brain | Claude API (Anthropic) |
| Text-to-Speech | OpenAI TTS / ElevenLabs |
| Dashboard | Static HTML + JS |

## Quick Start

### Prerequisites

- Docker & Docker Compose
- API Keys:
  - Anthropic (Claude API)
  - OpenAI (Whisper + TTS)
  - Twilio (telephony)

### Setup

```bash
# Clone the repository
git clone <repo-url>
cd italian-phone-proxy

# Run setup script
chmod +x scripts/setup.sh
./scripts/setup.sh

# Configure environment
cp .env.example .env
# Edit .env with your API keys

# Build and start
docker-compose up -d --build

# View logs
docker-compose logs -f api

# Access dashboard
open http://localhost:8080
```

### First Steps

1. **Upload a utility bill** at `/documents.html`
2. Review the AI extraction
3. **Approve** to merge into knowledge base
4. **Edit knowledge** at `/config.html` to add directions, preferences
5. (Phase 2) Configure Twilio and test incoming calls

## Project Structure

```
italian-phone-proxy/
├── docker-compose.yml      # Service orchestration
├── .env.example            # Environment template
│
├── api/                    # Main Python service
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py         # FastAPI application
│       ├── routers/        # API endpoints
│       ├── services/       # Business logic
│       ├── prompts/        # AI prompts
│       └── static/         # Dashboard HTML
│
├── data/                   # Persistent data
│   ├── config/
│   │   └── knowledge.json  # Knowledge base
│   ├── documents/          # Uploaded files
│   ├── extractions/        # AI extractions
│   └── transcripts/        # Call records
│
└── scripts/
    └── setup.sh            # Initial setup
```

## API Endpoints

### Documents
- `POST /api/documents/upload` — Upload a document
- `POST /api/documents/extract/{id}` — Extract information
- `POST /api/documents/approve/{id}` — Merge to knowledge
- `GET /api/documents/pending` — List pending documents

### Configuration
- `GET /api/config/knowledge` — Get full knowledge base
- `PATCH /api/config/knowledge` — Update a field

### Calls
- `GET /api/calls/history` — Get call history
- `GET /api/calls/history/{id}` — Get call details
- `POST /api/calls/test` — Create test call record

### Twilio (Phase 2)
- `POST /api/twilio/voice` — Incoming call webhook
- `WS /api/twilio/stream` — Media stream
- `POST /api/twilio/status` — Status callback

## Development Phases

- [x] **Phase 0.5**: Document Extraction & Knowledge
- [ ] **Phase 1**: Telephony Skeleton (Twilio setup)
- [ ] **Phase 2**: Speech Pipeline (Whisper + TTS)
- [ ] **Phase 3**: Claude Conversation Loop
- [ ] **Phase 4**: Live Dashboard (listen-in, take-over)
- [ ] **Phase 5**: WhatsApp Integration

## Estimated Costs

~€12-15/month for ~30 calls (5 min average):
- Italian Twilio number: ~€1/mo
- Per-minute telephony: ~€3-5/mo  
- API usage (Whisper + Claude + TTS): ~€5-8/mo

## License

MIT

---

*December 2025*
