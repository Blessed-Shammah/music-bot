import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
MPV_SOCKET = os.getenv("MPV_SOCKET", "/tmp/mpv-socket")
MAX_SEARCH_RESULTS = int(os.getenv("MAX_SEARCH_RESULTS", "5"))

# Twilio (WhatsApp)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
TWILIO_WHATSAPP_TO = os.getenv("TWILIO_WHATSAPP_TO", "")  # your personal WhatsApp number

# Groq AI
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_ENABLED = bool(GROQ_API_KEY)

# Web UI
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))

TELEGRAM_ENABLED = bool(TELEGRAM_TOKEN and TELEGRAM_TOKEN != "your_telegram_token_here")
