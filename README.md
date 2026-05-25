# Music Chat Bot

Control your music from anywhere — WhatsApp, Telegram, or a browser. Powered by Groq AI so it understands plain English, not just commands.

```
Your Phone (WhatsApp / Telegram)
              ↕
      Bot running on your PC   ←→   Browser (localhost:8080)
              ↕
      mpv plays through your speakers
```

---

## Features

- **Natural language** — say "play hotline bling", "skip this", "hi", or paste a song list
- **WhatsApp** — via Twilio sandbox with interactive buttons
- **Telegram** — inline keyboards, optional (works without it)
- **Web UI** — browser chat at `localhost:8080`, dark/light toggle
- **Playlists** — saved to SQLite, survive restarts
- **Smart controls** — loop, shuffle, queue, seek, volume, previous track

---

## Requirements

| Tool | Install |
|------|---------|
| Python 3.11+ | `sudo apt install python3` |
| mpv | `sudo apt install mpv` |
| pip | comes with Python |
| ngrok | [ngrok.com/download](https://ngrok.com/download) — for WhatsApp webhook |

---

## Setup

### 1. Create a virtual environment

```bash
cd ~/xcode/music-chat
python3 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
nano .env   # fill in your keys
```

Your `.env` should look like this:

```env
# Telegram (optional — bot works without it)
TELEGRAM_TOKEN=your_telegram_token_here

# Groq AI — free at console.groq.com
GROQ_API_KEY=gsk_your_key_here

# Twilio WhatsApp
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
TWILIO_WHATSAPP_TO=whatsapp:+your_number

# Player & Web
MPV_SOCKET=/tmp/mpv-socket
MAX_SEARCH_RESULTS=5
WEB_HOST=0.0.0.0
WEB_PORT=8080
```

### 4. Run the bot

```bash
source venv/bin/activate   # if not already active
python main.py
```

You should see:
```
⚠️  Telegram token not set — running without Telegram
✅ Web UI at http://localhost:8080
✅ WhatsApp webhook at http://localhost:8080/whatsapp/webhook
   (expose with: ngrok http 8080)
```

---

## Getting your API keys

### Groq API key (free)
1. Go to [console.groq.com](https://console.groq.com)
2. Sign up → **API Keys** → **Create API Key**
3. Copy into `.env` as `GROQ_API_KEY`

### Telegram bot token (optional)
1. Open Telegram → search `@BotFather`
2. Send `/newbot` → follow prompts → copy the token
3. Paste into `.env` as `TELEGRAM_TOKEN`

### Twilio WhatsApp (sandbox — free)
1. Sign up at [console.twilio.com](https://console.twilio.com)
2. Go to **Messaging → Try it out → Send a WhatsApp message**
3. From your phone WhatsApp, send `join <sandbox-word>` to `+1 415 523 8886`
4. Copy **Account SID** and **Auth Token** from the console dashboard into `.env`
5. Expose your bot with ngrok (see below) and paste the URL into Twilio

> **Note:** Sandbox membership expires every 72 hours. Rejoin by sending the join code again.

---

## WhatsApp webhook setup

Every time you start the bot, run ngrok in a separate terminal:

```bash
ngrok http 8080
```

Copy the `https://xxxx.ngrok-free.app` URL and paste it into Twilio:

1. Twilio Console → **Messaging → Try it out → Send a WhatsApp message**
2. Click **Sandbox settings** tab
3. Set **"When a message comes in"** to:
   ```
   https://xxxx.ngrok-free.app/whatsapp/webhook
   ```
   Method: **POST**
4. Leave **Status callback URL** blank
5. Click **Save**

---

## Using the bot

### Natural language (AI-powered)
Just talk to it:

| You say | What happens |
|---------|--------------|
| `hi` | Friendly greeting |
| `hotline bling` | Searches YouTube, shows 5 results with buttons |
| `play hotline bling` | Searches + plays instantly |
| `play god's plan next` | Searches + queues as next track |
| `add one dance to queue` | Searches + adds to queue |
| `skip` / `pause` / `shuffle` | Executes the command |

### Song lists — paste and play
Send a list of songs and the bot searches and queues them all:

```
1. Hotline Bling Drake
2. God's Plan Drake
3. One Dance Drake
```

Add "save as my playlist name" and it saves as a playlist too.

### WhatsApp buttons
```
You: hotline bling
Bot: 🎵 Search Results
     1. Drake - Hotline Bling · 4:56
     2. ...
     [1] [2] [3]    ← tap a number

You tap 1:
Bot: Drake - Hotline Bling
     [▶ Play] [⏭ Next] [➕ Queue]   ← tap action

You tap ▶ Play:
Bot: ▶ Playing: Drake - Hotline Bling · 4:56
```

### Slash commands (all interfaces)

**Playback**
| Command | Action |
|---------|--------|
| `/playing` | Now playing + progress bar + volume |
| `/pause` | Pause / resume |
| `/skip` | Skip to next track |
| `/prev` | Previous track |
| `/seek <sec>` | Jump e.g. `/seek -15` or `/seek 60` |
| `/vol <0-150>` | Set volume |
| `/loop` | 🔂 Loop current song |
| `/loopq` | 🔁 Loop entire queue |
| `/shuffle` | 🔀 Shuffle queue |

**Queue**
| Command | Action |
|---------|--------|
| `/queue` | Show queue |
| `/remove <n>` | Remove track #n |
| `/clear` | Clear queue |

**Playlists**
| Command | Action |
|---------|--------|
| `/save <name>` | Save current queue as playlist |
| `/load <name>` | Load and play a playlist |
| `/playlists` | List all playlists (with load buttons) |
| `/delplaylist <name>` | Delete a playlist |
| `/rename old > new` | Rename a playlist |

---

## Auto-start on boot (Linux)

```bash
# Edit the service file first
nano music-chat.service
# Update WorkingDirectory and ExecStart to your actual paths

cp music-chat.service ~/.config/systemd/user/music-chat.service
systemctl --user enable --now music-chat
systemctl --user status music-chat
```

---

## Project structure

```
music-chat/
├── core/
│   ├── handlers.py      # shared logic — all interfaces call this
│   └── ai.py            # Groq intent parser
├── adapters/
│   └── whatsapp.py      # Twilio WhatsApp adapter
├── web/
│   ├── app.py           # FastAPI server (WebSocket + webhook)
│   └── static/
│       └── index.html   # Web chat UI
├── main.py              # entry point — runs everything
├── bot.py               # legacy Telegram-only entry (kept for reference)
├── search.py            # YouTube search via yt-dlp
├── player.py            # mpv IPC controller
├── queue_manager.py     # in-memory queue with loop/shuffle
├── playlist_manager.py  # SQLite playlist storage
├── config.py            # environment config
├── requirements.txt
├── .env.example
├── start.sh
└── music-chat.service   # systemd unit
```

---

## Troubleshooting

**`ModuleNotFoundError`** — run `pip install -r requirements.txt` inside your venv

**`mpv: command not found`** — `sudo apt install mpv`

**`TELEGRAM_TOKEN` error** — Telegram is optional, leave it as `your_telegram_token_here` to skip it

**WhatsApp not receiving messages** — check ngrok is running and the URL in Twilio Sandbox settings is updated (ngrok URL changes every restart on free tier)

**Sandbox expired** — send `join <your-sandbox-word>` to `+1 415 523 8886` on WhatsApp again

**No search results** — yt-dlp occasionally hits rate limits, wait 30 seconds and retry

**Web UI not loading** — visit `http://localhost:8080` (not https)
