#!/usr/bin/env bash
set -e

BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
CYAN="\033[0;36m"
RESET="\033[0m"

info()    { echo -e "${CYAN}${BOLD}[•]${RESET} $1"; }
success() { echo -e "${GREEN}${BOLD}[✓]${RESET} $1"; }
warn()    { echo -e "${YELLOW}${BOLD}[!]${RESET} $1"; }
error()   { echo -e "${RED}${BOLD}[✗]${RESET} $1"; exit 1; }

echo ""
echo -e "${BOLD}╔══════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║        Music Chat Bot  Setup         ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════╝${RESET}"
echo ""

# ── 1. System dependencies ────────────────────────────────────────────────

info "Checking system dependencies..."

if ! command -v python3 &>/dev/null; then
    error "Python 3 is not installed. Run: sudo apt install python3"
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [ "$PYTHON_VERSION" -lt 11 ]; then
    error "Python 3.11+ required. Found: $(python3 --version)"
fi
success "Python $(python3 --version | cut -d' ' -f2) found"

if ! command -v mpv &>/dev/null; then
    info "Installing mpv..."
    sudo apt-get install -y mpv || error "Failed to install mpv. Run: sudo apt install mpv"
fi
success "mpv $(mpv --version | head -1 | cut -d' ' -f2) found"

if ! command -v pip3 &>/dev/null && ! python3 -m pip --version &>/dev/null 2>&1; then
    info "Installing pip..."
    sudo apt-get install -y python3-pip || error "Failed to install pip"
fi
success "pip found"

# ── 2. Virtual environment ────────────────────────────────────────────────

info "Setting up virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    success "Virtual environment created"
else
    success "Virtual environment already exists"
fi

source venv/bin/activate

# ── 3. Python dependencies ────────────────────────────────────────────────

info "Installing Python dependencies..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
success "All Python packages installed"

# ── 4. Environment file ───────────────────────────────────────────────────

if [ ! -f ".env" ]; then
    cp .env.example .env
    info "Created .env from template"
else
    info ".env already exists — skipping"
fi

# ── 5. Collect API keys interactively ────────────────────────────────────

echo ""
echo -e "${BOLD}Configure your API keys${RESET}"
echo -e "${YELLOW}Press Enter to skip any key (you can edit .env later)${RESET}"
echo ""

read -rp "  Telegram Bot Token (from @BotFather, optional): " TG_TOKEN
read -rp "  Groq API Key       (from console.groq.com):     " GROQ_KEY
read -rp "  Twilio Account SID (from console.twilio.com):   " TWILIO_SID
read -rp "  Twilio Auth Token  (from console.twilio.com):   " TWILIO_TOKEN
read -rp "  Your WhatsApp number (e.g. +254717048047):      " WA_NUMBER

# Write collected keys to .env
if [ -n "$TG_TOKEN" ];    then sed -i "s|TELEGRAM_TOKEN=.*|TELEGRAM_TOKEN=$TG_TOKEN|" .env; fi
if [ -n "$GROQ_KEY" ];    then sed -i "s|GROQ_API_KEY=.*|GROQ_API_KEY=$GROQ_KEY|" .env; fi
if [ -n "$TWILIO_SID" ];  then sed -i "s|TWILIO_ACCOUNT_SID=.*|TWILIO_ACCOUNT_SID=$TWILIO_SID|" .env; fi
if [ -n "$TWILIO_TOKEN" ];then sed -i "s|TWILIO_AUTH_TOKEN=.*|TWILIO_AUTH_TOKEN=$TWILIO_TOKEN|" .env; fi
if [ -n "$WA_NUMBER" ];   then
    WA_FULL="whatsapp:${WA_NUMBER}"
    sed -i "s|TWILIO_WHATSAPP_TO=.*|TWILIO_WHATSAPP_TO=$WA_FULL|" .env
fi

success ".env configured"

# ── 6. Systemd auto-start (optional) ─────────────────────────────────────

echo ""
read -rp "  Set up auto-start on boot (systemd)? [y/N]: " SETUP_SYSTEMD

if [[ "$SETUP_SYSTEMD" =~ ^[Yy]$ ]]; then
    UNIT_DIR="$HOME/.config/systemd/user"
    mkdir -p "$UNIT_DIR"

    WORK_DIR="$(pwd)"
    PYTHON_BIN="$(pwd)/venv/bin/python"

    cat > "$UNIT_DIR/music-chat.service" <<EOF
[Unit]
Description=Music Chat Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=$WORK_DIR
ExecStart=$PYTHON_BIN main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

    systemctl --user daemon-reload
    systemctl --user enable music-chat
    success "Systemd service installed — starts on login"
    info "Control with: systemctl --user start|stop|status music-chat"
fi

# ── 7. Done ───────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════╗${RESET}"
echo -e "${GREEN}${BOLD}║           Setup complete! 🎵          ║${RESET}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════╝${RESET}"
echo ""
echo -e "  Run the bot:     ${BOLD}source venv/bin/activate && python main.py${RESET}"
echo -e "  Web UI:          ${BOLD}http://localhost:8080${RESET}"
echo -e "  WhatsApp:        ${BOLD}ngrok http 8080${RESET}  → paste URL in Twilio sandbox settings"
echo -e "  Edit config:     ${BOLD}nano .env${RESET}"
echo ""
