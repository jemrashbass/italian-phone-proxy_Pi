# Italian Phone Proxy — Telephony Implementation

**Session Date:** 1 January 2026  
**Phase:** Twilio Integration & Speech Pipeline

---

## What Was Built

This session implemented the complete telephony pipeline for handling Italian phone calls:

### New Files Created

```
api/app/
├── main.py                    # Updated with Twilio router
├── routers/
│   ├── __init__.py            # Package init
│   ├── twilio.py              # 🆕 Voice webhook + WebSocket media stream
│   └── calls.py               # 🆕 Call history + outbound calls
├── services/
│   ├── __init__.py            # Package init
│   ├── audio.py               # 🆕 Audio conversion (mulaw ↔ PCM)
│   ├── whisper.py             # 🆕 OpenAI Whisper STT
│   ├── tts.py                 # 🆕 OpenAI TTS
│   └── claude.py              # 🆕 Claude conversation handling
└── prompts/
    ├── __init__.py            # Package init
    └── system.py              # 🆕 Italian phone agent prompt
```

### Pipeline Flow

```
📞 Incoming Call
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│                         TWILIO                               │
│  Phone → Twilio Number → Webhook → WebSocket Media Stream   │
└─────────────────────────────────────────────────────────────┘
      │
      ▼ (mulaw 8kHz audio chunks)
┌─────────────────────────────────────────────────────────────┐
│                      AUDIO BUFFER                            │
│  Accumulate chunks → Detect silence → Trigger processing    │
└─────────────────────────────────────────────────────────────┘
      │
      ▼ (complete speech segment)
┌─────────────────────────────────────────────────────────────┐
│                    WHISPER API (OpenAI)                      │
│  mulaw → PCM → 16kHz WAV → Transcription (Italian)          │
└─────────────────────────────────────────────────────────────┘
      │
      ▼ (Italian text transcript)
┌─────────────────────────────────────────────────────────────┐
│                     CLAUDE API                               │
│  System prompt + Knowledge + History → Italian response     │
└─────────────────────────────────────────────────────────────┘
      │
      ▼ (Italian response text)
┌─────────────────────────────────────────────────────────────┐
│                    TTS API (OpenAI)                          │
│  Text → 24kHz PCM → 8kHz mulaw → base64                     │
└─────────────────────────────────────────────────────────────┘
      │
      ▼ (audio back to caller)
┌─────────────────────────────────────────────────────────────┐
│                    TWILIO WEBSOCKET                          │
│  Send audio chunks → Caller hears response                  │
└─────────────────────────────────────────────────────────────┘
```

---

## Deployment Instructions

### 1. Copy Files to Raspberry Pi

From your Mac, copy the new files to the Pi:

```bash
# Create a tarball of the new files
cd /path/to/generated/files
tar -czvf telephony-update.tar.gz italian-phone-proxy/

# Copy to Pi
scp telephony-update.tar.gz pi@trypi5:~/

# SSH to Pi
ssh pi@trypi5

# Extract (careful not to overwrite existing working files)
cd ~/italian-phone-proxy
tar -xzvf ~/telephony-update.tar.gz --strip-components=1
```

**Or copy individual files:**

```bash
# On Mac, from the directory with generated files:
scp -r italian-phone-proxy/api/app/services/* pi@trypi5:~/italian-phone-proxy/api/app/services/
scp -r italian-phone-proxy/api/app/prompts/* pi@trypi5:~/italian-phone-proxy/api/app/prompts/
scp italian-phone-proxy/api/app/routers/twilio.py pi@trypi5:~/italian-phone-proxy/api/app/routers/
scp italian-phone-proxy/api/app/routers/calls.py pi@trypi5:~/italian-phone-proxy/api/app/routers/
scp italian-phone-proxy/api/app/main.py pi@trypi5:~/italian-phone-proxy/api/app/
scp italian-phone-proxy/api/requirements.txt pi@trypi5:~/italian-phone-proxy/api/
```

### 2. Update Requirements

```bash
ssh pi@trypi5
cd ~/italian-phone-proxy

# Rebuild the container to get new dependencies
docker compose build api
docker compose up -d api

# Check logs
docker compose logs -f api
```

### 3. Verify Environment Variables

Make sure your `.env` file has all required keys:

```bash
cat ~/italian-phone-proxy/.env
```

Required variables:
```
ANTHROPIC_API_KEY=sk-ant-api03-...
OPENAI_API_KEY=sk-...
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=+44...
```

### 4. Configure Twilio Webhook

1. Log into [Twilio Console](https://console.twilio.com/)
2. Go to **Phone Numbers** → **Manage** → **Active numbers**
3. Click on your UK number
4. Under **Voice Configuration**:
   - **A Call Comes In**: Webhook
   - **URL**: `https://phone.rashbass.org/api/twilio/voice`
   - **HTTP Method**: POST
5. Under **Status Callback URL** (optional):
   - **URL**: `https://phone.rashbass.org/api/twilio/status`
6. Click **Save configuration**

### 5. Test the Pipeline

```bash
# Check health endpoint
curl https://phone.rashbass.org/health

# Should return:
# {
#   "status": "healthy",
#   "service": "italian-phone-proxy",
#   "version": "0.2.0",
#   "features": {
#     "documents": true,
#     "telephony": true,
#     "whisper": true,
#     "claude": true,
#     "twilio": true
#   }
# }

# Check API status
curl https://phone.rashbass.org/api/status
```

### 6. Make a Test Call

Call your Twilio number from any phone. You should hear:
1. "Pronto. Un momento per favore." (Twilio's built-in TTS)
2. Then the AI greeting via OpenAI TTS

Watch the logs:
```bash
docker compose logs -f api
```

You should see:
```
📞 Incoming call: CAxxxx from +39xxx to +44xxx
Connecting call CAxxxx to WebSocket: wss://phone.rashbass.org/api/twilio/stream
WebSocket connection accepted
Stream started: MZxxxx for call CAxxxx
Started conversation for call CAxxxx from +39xxx
🎤 Caller said: [transcript]
🤖 AI response: [response]
```

---

## Configuration Notes

### Audio Settings

The `audio.py` service handles conversion between formats:

| Format | Sample Rate | Bits | Use |
|--------|-------------|------|-----|
| Twilio mulaw | 8 kHz | 8-bit | Phone audio |
| Whisper input | 16 kHz | 16-bit WAV | Speech-to-text |
| OpenAI TTS output | 24 kHz | 16-bit PCM | Text-to-speech |

### Silence Detection

The `AudioBuffer` class detects end of speech using:
- **Silence threshold**: 500 RMS (adjust if needed)
- **Silence duration**: 800ms (0.8 seconds of quiet = end of turn)
- **Minimum speech**: 300ms (ignore very short sounds)

To adjust sensitivity, edit `audio.py`:
```python
SILENCE_THRESHOLD = 500  # Lower = more sensitive
SILENCE_DURATION_MS = 800  # Shorter = faster turn-taking
```

### Claude Model

Using `claude-sonnet-4-20250514` for good balance of speed and quality. To change:

```python
# In services/claude.py
self.model = "claude-sonnet-4-20250514"  # or claude-3-5-haiku for faster
```

### TTS Voice

Using OpenAI's `nova` voice (good Italian). Options:
- `alloy` - neutral
- `echo` - male
- `nova` - female (recommended for Italian)
- `onyx` - deep male
- `shimmer` - soft female

To change, edit `services/tts.py`:
```python
self.voice = "nova"  # Change here
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/status` | GET | Detailed status with active calls |
| `/api/twilio/voice` | POST | Incoming call webhook (Twilio) |
| `/api/twilio/stream` | WS | WebSocket for audio streaming |
| `/api/twilio/status` | POST | Call status callback |
| `/api/twilio/active` | GET | List active calls |
| `/api/calls/history` | GET | Call history |
| `/api/calls/outbound` | POST | Initiate outbound call |

---

## Troubleshooting

### No audio from AI
1. Check OpenAI API key is valid
2. Check logs for TTS errors
3. Verify audio conversion is working

### Transcription empty
1. Check silence threshold (may be too high)
2. Check Whisper API key
3. Verify audio is actually reaching the buffer

### Claude not responding
1. Check Anthropic API key
2. Check conversation state is being created
3. Verify system prompt is loading knowledge

### WebSocket disconnecting
1. Check Cloudflare Tunnel is stable
2. Check for errors in docker logs
3. Verify Twilio is connecting to correct URL

### Call forwarding not working
1. Verify USSD codes on Iliad
2. Check Twilio number is receiving calls
3. Test with direct call to Twilio number first

---

## Next Steps

1. **Test with real calls** - Call the number and have a conversation
2. **Tune silence detection** - Adjust thresholds based on real usage
3. **Add dashboard WebSocket** - Live transcript display
4. **Implement listen-in mode** - Audio streaming to browser
5. **Add iOS app** - Mobile dashboard for monitoring

---

*Implementation completed: 1 January 2026*
