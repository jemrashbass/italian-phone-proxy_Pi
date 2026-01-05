# Italian Phone Proxy

**AI Voice Agent for Managing Italian Phone Calls**

An intelligent voice assistant that answers phone calls in Italian, handles conversations naturally, and solves the daily communication challenges faced by non-native speakers living in Italy.

![Version](https://img.shields.io/badge/version-0.4.0-blue)
![Status](https://img.shields.io/badge/status-production-green)
![License](https://img.shields.io/badge/license-private-lightgrey)

---

## 🎯 The Problem

Living in Italy as a non-native speaker presents a unique challenge: while reading Italian is manageable, real-time phone conversations are difficult. Unlike many modern economies where online tools suffice, Italian daily life still runs primarily through phone calls:

- 📦 **Delivery drivers** calling for directions
- 🔧 **Service engineers** scheduling appointments
- ⚡ **Utility companies** discussing bills and service
- 📡 **ISP technicians** coordinating installations
- 🛒 **Sales calls** that need polite declining

This project solves that problem with an AI agent that:
1. Answers calls with natural Italian conversation
2. Knows your identity, address, and account details
3. Gives directions to delivery drivers (with automatic SMS location sharing!)
4. Handles routine utility enquiries
5. Politely declines sales calls
6. Lets you monitor and intervene in real-time

---

## ✨ Features

### Core Voice Agent
- **🇮🇹 Native Italian conversation** - Natural speech using Claude AI
- **🎤 Speech-to-text** - OpenAI Whisper with excellent Italian accuracy
- **🔊 Text-to-speech** - OpenAI TTS with natural male Italian voice
- **📞 Twilio integration** - Professional telephony with UK number
- **👋 Smart call ending** - Detects goodbye phrases and hangs up gracefully

### SMS Location Sharing
- **📍 Automatic detection** - Claude identifies when callers need directions
- **🗺️ Google Maps link** - Tappable link sent via SMS
- **⏱️ 30-second countdown** - Cancel or send immediately from dashboard
- **📨 Reply forwarding** - Driver replies forwarded to your mobile
- **🚚 Works for anyone** - Delivery drivers, service engineers, visitors

### Real-Time Dashboard
- **📺 Live call monitoring** - Watch transcripts as they happen
- **💬 WhatsApp-style UI** - Familiar chat interface
- **📊 Call analytics** - Latency breakdown per component
- **🔮 AI insights** - Claude analyzes calls and suggests optimizations
- **⚙️ Runtime configuration** - Adjust parameters without restart

### Document Processing
- **📄 Bill extraction** - Upload utility bills, extract account details
- **👁️ Claude Vision** - Automatic OCR and data extraction
- **✅ Review workflow** - Approve extracted data before saving
- **📚 Knowledge base** - All accounts in one searchable place

### Analytics & Optimization
- **📈 Granular timing** - Whisper, Claude, TTS latency per turn
- **🚩 Quality flags** - Echo detection, low confidence, slow responses
- **🎯 AI recommendations** - Suggested parameter changes with expected impact
- **📉 Trend tracking** - Performance over time

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              INTERNET                                    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
            ┌──────────────┐               ┌──────────────────┐
            │    TWILIO    │               │   CLOUDFLARE     │
            │  UK Number   │               │     TUNNEL       │
            │  +447886...  │               │ phone.rashbass.org│
            └──────┬───────┘               └────────┬─────────┘
                   │                                │
                   │ WebSocket (audio)              │ HTTPS
                   │                                │
                   └────────────────┬───────────────┘
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         RASPBERRY PI 5                                   │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                    Docker: phone-proxy-api                          │ │
│  │                          Port 8080                                  │ │
│  │                                                                     │ │
│  │  ┌─────────────────────────────────────────────────────────────┐   │ │
│  │  │                    FastAPI Application                       │   │ │
│  │  │                                                              │   │ │
│  │  │  Routers:              Services:           External APIs:    │   │ │
│  │  │  ├─ twilio.py          ├─ audio.py         ├─ Whisper (STT)  │   │ │
│  │  │  ├─ dashboard.py       ├─ whisper.py       ├─ Claude (LLM)   │   │ │
│  │  │  ├─ calls.py           ├─ claude.py        ├─ OpenAI TTS     │   │ │
│  │  │  ├─ documents.py       ├─ tts.py           └─ Claude Vision  │   │ │
│  │  │  ├─ config.py          ├─ messaging.py                       │   │ │
│  │  │  ├─ analytics.py       ├─ analytics.py                       │   │ │
│  │  │  ├─ system_config.py   ├─ system_config.py                   │   │ │
│  │  │  ├─ messaging.py       ├─ insights.py                        │   │ │
│  │  │  └─ sms.py             └─ knowledge.py                       │   │ │
│  │  └─────────────────────────────────────────────────────────────┘   │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                 Docker: cloudflared-italia                          │ │
│  │              Tunnel → phone.rashbass.org                            │ │
│  └────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

### Call Flow

```
📞 Incoming Call (Italian mobile forwards to Twilio)
       │
       ▼
┌──────────────────┐
│  Twilio Number   │  Receives call, opens WebSocket
│  +447886078862   │
└────────┬─────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────┐
│                      AUDIO PIPELINE                           │
│                                                               │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐   │
│  │ Twilio  │───▶│ Buffer  │───▶│ Whisper │───▶│ Claude  │   │
│  │ mulaw   │    │ Silence │    │  STT    │    │  LLM    │   │
│  │ 8kHz    │    │ 1200ms  │    │ Italian │    │ Italian │   │
│  └─────────┘    └─────────┘    └─────────┘    └────┬────┘   │
│                                                     │        │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐         │        │
│  │ Twilio  │◀───│ Resample│◀───│ OpenAI  │◀────────┘        │
│  │ mulaw   │    │ 24k→8k  │    │  TTS    │                  │
│  │ 8kHz    │    │         │    │ "onyx"  │                  │
│  └─────────┘    └─────────┘    └─────────┘                  │
│         │                                                    │
│         │  ┌─────────────────────────────────────────────┐  │
│         └──│  📍 Delivery Detection (parallel)           │  │
│            │  Claude analyzes: "Is caller asking for     │  │
│            │  directions?" → Queue SMS with countdown    │  │
│            └─────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
         │
         │ WebSocket broadcast
         ▼
┌──────────────────┐
│    Dashboard     │  Real-time transcript + SMS controls
│    Browser       │
└──────────────────┘
```

---

## 🛠️ Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Telephony** | Twilio | Phone number, call handling, SMS |
| **Speech-to-Text** | OpenAI Whisper | Italian transcription |
| **LLM** | Claude (Anthropic) | Conversation, analysis, detection |
| **Text-to-Speech** | OpenAI TTS | Natural Italian voice |
| **Backend** | FastAPI (Python) | API server, WebSocket handling |
| **Hosting** | Raspberry Pi 5 | Local deployment in London |
| **Tunnel** | Cloudflare Tunnel | Secure HTTPS exposure |
| **Container** | Docker Compose | Service orchestration |
| **Frontend** | HTML/CSS/JavaScript | Dashboard UI |

---

## 📁 Directory Structure

```
italian-phone-proxy/
│
├── docker-compose.yml          # Container orchestration
├── .env                        # API keys and secrets (not in repo)
├── README.md                   # This file
│
├── api/                        # Main Python service
│   ├── Dockerfile              # Python 3.11 slim image
│   ├── requirements.txt        # Python dependencies
│   │
│   └── app/
│       ├── __init__.py
│       ├── main.py             # FastAPI entry point
│       │
│       ├── routers/            # API endpoints
│       │   ├── twilio.py       # Voice webhook + WebSocket stream
│       │   ├── sms.py          # SMS incoming webhook + forwarding
│       │   ├── messaging.py    # Location SMS API
│       │   ├── dashboard.py    # WebSocket for live UI updates
│       │   ├── calls.py        # Call history + stats
│       │   ├── documents.py    # Document upload + extraction
│       │   ├── config.py       # Knowledge base editor
│       │   ├── analytics.py    # Call analytics API
│       │   └── system_config.py # Runtime configuration API
│       │
│       ├── services/           # Business logic
│       │   ├── audio.py        # Audio format conversion
│       │   ├── whisper.py      # OpenAI Whisper STT
│       │   ├── claude.py       # Claude conversation management
│       │   ├── tts.py          # OpenAI TTS
│       │   ├── messaging.py    # SMS location service
│       │   ├── analytics.py    # Event tracking + metrics
│       │   ├── insights.py     # AI-powered analysis
│       │   ├── system_config.py # Parameter management
│       │   ├── extractor.py    # Claude Vision document extraction
│       │   └── knowledge.py    # Knowledge base management
│       │
│       ├── prompts/            # AI prompts
│       │   ├── system.py       # Phone agent system prompt
│       │   └── extraction.py   # Document extraction prompt
│       │
│       └── static/             # Web dashboard
│           ├── index.html      # Live call monitoring
│           ├── calls.html      # Call history viewer
│           ├── documents.html  # Document upload/extraction
│           ├── config.html     # Knowledge base + SMS config
│           ├── analytics.html  # Call analytics dashboard
│           └── system.html     # System configuration
│
├── data/                       # Persistent data (Docker volume)
│   ├── config/
│   │   ├── knowledge.json      # Identity, address, accounts, SMS config
│   │   └── system.json         # Runtime parameters
│   │
│   ├── documents/
│   │   ├── raw/                # Uploaded, pending extraction
│   │   └── processed/          # Extracted and approved
│   │
│   ├── extractions/            # JSON extraction results
│   ├── transcripts/            # Call transcript JSON files
│   └── analytics/              # Per-call analytics data
│
└── docs/                       # Documentation
    ├── TELEPHONY_IMPLEMENTATION.md
    ├── CALL_ANALYTICS_SCHEMA.md
    ├── SMS_LOCATION_IMPLEMENTATION_SUMMARY.md
    └── SESSION_SUMMARY_*.md
```

---

## 🚀 Setup & Deployment

### Prerequisites

- Raspberry Pi 5 (or any Linux server)
- Docker and Docker Compose
- Domain with Cloudflare (for tunnel)
- Twilio account with:
  - UK phone number (SMS-enabled)
  - Italy geo permissions for SMS
- API keys for:
  - Anthropic (Claude)
  - OpenAI (Whisper + TTS)

### 1. Clone and Configure

```bash
git clone https://github.com/yourusername/italian-phone-proxy.git
cd italian-phone-proxy

# Create environment file
cat > .env << 'EOF'
ANTHROPIC_API_KEY=sk-ant-api03-...
OPENAI_API_KEY=sk-...
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=+447886078862
OWNER_MOBILE_NUMBER=+447796315426
EOF
```

### 2. Start Services

```bash
docker compose up -d
```

### 3. Configure Cloudflare Tunnel

See [SETUP_CLOUDFLARE_TUNNEL.md](docs/SETUP_CLOUDFLARE_TUNNEL.md) for detailed instructions.

### 4. Configure Twilio Webhooks

In Twilio Console → Phone Numbers → Your Number:

**Voice Configuration:**
| Setting | Value |
|---------|-------|
| A Call Comes In | `https://your-domain.com/api/twilio/voice` (POST) |
| Call Status Changes | `https://your-domain.com/api/twilio/status` (POST) |

**Messaging Configuration:**
| Setting | Value |
|---------|-------|
| A Message Comes In | `https://your-domain.com/api/twilio/sms-incoming` (POST) |

### 5. Set Up Call Forwarding

On your Italian mobile (Iliad example):
```
**21*+447886078862#   # Forward all calls
##21#                  # Disable forwarding
```

---

## ⚙️ Configuration

### Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Claude API key |
| `OPENAI_API_KEY` | Whisper + TTS API key |
| `TWILIO_ACCOUNT_SID` | Twilio account |
| `TWILIO_AUTH_TOKEN` | Twilio auth |
| `TWILIO_PHONE_NUMBER` | Your Twilio number (E.164) |
| `OWNER_MOBILE_NUMBER` | Your mobile for SMS forwarding |

### Runtime Parameters (System Config)

Adjustable via dashboard without restart:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `audio.silence_duration_ms` | 1200 | Silence before processing |
| `audio.min_speech_duration_ms` | 500 | Minimum speech to process |
| `audio.silence_threshold` | 500 | RMS threshold for silence |
| `claude.model` | claude-sonnet-4-20250514 | Model for conversation |
| `claude.max_tokens` | 80 | Max response length |
| `claude.context_turns` | 4 | Conversation history depth |
| `tts.voice` | onyx | OpenAI voice |
| `tts.speed` | 0.9 | Speech rate |

### Knowledge Base (knowledge.json)

Contains your personal information:
- Identity (name, phone greeting)
- Address (full Italian format with directions)
- Utility accounts (Eni, Vodafone, water, etc.)
- Location sharing config (GPS, SMS template)

---

## 🌐 API Reference

### Telephony
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/twilio/voice` | POST | Incoming call webhook |
| `/api/twilio/stream` | WS | Audio WebSocket |
| `/api/twilio/status` | POST | Call status callback |
| `/api/twilio/sms-incoming` | POST | Incoming SMS webhook |

### Messaging
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/messaging/send-location` | POST | Send SMS immediately |
| `/api/messaging/queue-location` | POST | Queue with countdown |
| `/api/messaging/send-now/{call_sid}` | POST | Send queued now |
| `/api/messaging/queue/{call_sid}` | DELETE | Cancel queued |
| `/api/messaging/detect-claude` | POST | Test AI detection |

### Calls & Analytics
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/calls/history` | GET | Call history |
| `/api/calls/stats` | GET | Call statistics |
| `/api/analytics/calls` | GET | Calls with metrics |
| `/api/analytics/call/{id}` | GET | Full call analytics |
| `/api/analytics/call/{id}/insights` | GET | AI analysis |

### Configuration
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/config/knowledge` | GET/PATCH | Knowledge base |
| `/api/config/system` | GET | System config |
| `/api/config/system` | PATCH | Update parameter |

### Dashboard
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/dashboard/ws` | WS | Real-time updates |
| `/health` | GET | Health check |
| `/api/status` | GET | Detailed status |

---

## 📊 Dashboard Pages

| Page | URL | Purpose |
|------|-----|---------|
| **Live** | `/dashboard/` | Real-time call monitoring |
| **Calls** | `/dashboard/calls.html` | Call history browser |
| **Documents** | `/dashboard/documents.html` | Bill upload & extraction |
| **Config** | `/dashboard/config.html` | Knowledge base + SMS settings |
| **Analytics** | `/dashboard/analytics.html` | Call performance analysis |
| **System** | `/dashboard/system.html` | Runtime configuration |

---

## 💰 Cost Estimate

| Service | Monthly Cost |
|---------|--------------|
| Twilio UK number | £0.83 |
| Twilio minutes (~30 calls × 3 min) | ~£2-3 |
| Twilio SMS (~30 messages) | ~£1-2 |
| OpenAI API (Whisper + TTS) | ~£3-5 |
| Anthropic API (Claude) | ~£5-8 |
| **Total** | **~£12-18/month** |

---

## 📈 Performance

Current optimized baseline (as of January 2026):

| Metric | Value |
|--------|-------|
| Average total latency | ~5,200ms |
| Whisper (STT) | ~1,450ms (28%) |
| Claude (LLM) | ~2,400ms (47%) |
| TTS | ~1,350ms (25%) |
| Average response tokens | 19 |

The "Sono inglese" opening sets expectations for slightly slower responses, making this latency acceptable.

---

## 🗓️ Development History

| Date | Milestone |
|------|-----------|
| Dec 2025 | Initial brainstorm and architecture design |
| 1 Jan 2026 | Infrastructure setup, Cloudflare Tunnel, document extraction |
| 1 Jan 2026 | Telephony pipeline: Twilio → Whisper → Claude → TTS |
| 2 Jan 2026 | Dashboard UI, WebSocket updates, conversation history |
| 2 Jan 2026 | Call analytics system with granular timing |
| 3 Jan 2026 | AI insights, runtime config, auto-hangup |
| 3 Jan 2026 | SMS location sharing with Claude detection |
| 3 Jan 2026 | SMS reply forwarding to owner's mobile |

---

## 🔮 Future Enhancements

- [ ] **WhatsApp Integration** - Native location pins, richer messaging
- [ ] **Companion Mobile App** - iOS/Android for monitoring on the go
- [ ] **Listen-in Mode** - Live audio streaming to browser
- [ ] **Take-over Button** - Human intervention during calls
- [ ] **Email Watcher** - Auto-ingest bills from email
- [ ] **Outbound Calls** - AI-initiated calls for appointments
- [ ] **Multi-language** - Support for other languages

---

## 🤝 Contributing

This is currently a private project. For questions or collaboration, please contact the maintainer.

---

## 📄 License

Private - All rights reserved.

---

## 🙏 Acknowledgments

- **Anthropic** - Claude AI for conversation and analysis
- **OpenAI** - Whisper STT and TTS APIs
- **Twilio** - Reliable telephony infrastructure
- **Cloudflare** - Secure tunnel for home hosting

---

*Built with ❤️ for making Italian life a little easier.*

**Current Version:** 0.4.0  
**Status:** Production - Handling real Italian phone calls  
**Location:** Raspberry Pi 5, London → phone.rashbass.org