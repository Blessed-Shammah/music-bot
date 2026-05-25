#!/usr/bin/env bash
set -e

if ! command -v mpv &>/dev/null; then
  echo "Error: mpv is not installed. Run: sudo apt install mpv"
  exit 1
fi

if [ ! -f .env ]; then
  echo "Error: .env file not found. Copy .env.example to .env and add your token."
  exit 1
fi

if [ -d venv ]; then
  source venv/bin/activate
fi

exec python bot.py
