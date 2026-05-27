"""
Twilio WhatsApp adapter — clean text-based UX with keyboard shortcuts.

Shortcuts after a search:
  1p / 2p   → play audio
  1v / 2v   → play video (fullscreen on PC)
  1n / 2n   → play next
  1q / 2q   → queue
  just "1"  → shows shortcut reminder for that track
  play all  → queue all results
"""
import re
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.handlers import (
    dispatch, action_play, action_next, action_queue,
    BotResponse, handle_bulk_search,
)
from config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse

# Per-user pending search results: phone_number -> list of SearchResult
_pending: dict[str, list] = {}

# Per-user conversation history for natural AI context (last 6 messages)
_history: dict[str, list[dict]] = {}

_client: Optional[Client] = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    return _client


EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response/>'


def twiml_reply(text: str) -> str:
    if not text:
        return EMPTY_TWIML
    resp = MessagingResponse()
    resp.message(text)
    return str(resp)


def _format_results_text(results: list) -> str:
    lines = ["🎵 *Results* — reply with number + action:\n"
             "  _1p_ play · _1v_ video · _1n_ next · _1q_ queue\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r.title}\n   {r.channel} · {r.duration}")
    return "\n".join(lines)


async def handle_whatsapp_message(from_number: str, body: str) -> str:
    body_stripped = body.strip()
    normalized = body_stripped.lower()

    # ── "play all" → queue all pending results ────────────────────────────
    if normalized in ("play all", "all", "queue all") and from_number in _pending:
        tracks = [{"title": r.title, "url": r.url,
                   "duration": r.duration, "channel": r.channel}
                  for r in _pending[from_number]]
        resp = await handle_bulk_search(tracks)
        return twiml_reply(resp.text)

    # ── Number + action shortcut: 1p / 2v / 3n / 4q ──────────────────────
    num_match = re.match(r'^(\d+)([pvnq]?)$', body_stripped, re.IGNORECASE)
    if num_match and from_number in _pending:
        idx = int(num_match.group(1)) - 1
        shortcut = num_match.group(2).lower()
        results = _pending[from_number]

        if 0 <= idx < len(results):
            result = results[idx]

            if shortcut == "p":
                response = await action_play(result.tid)
                return twiml_reply(response.text)
            elif shortcut == "v":
                response = await action_play(result.tid, video=True)
                return twiml_reply(response.text)
            elif shortcut == "n":
                response = await action_next(result.tid)
                return twiml_reply(response.text)
            elif shortcut == "q":
                response = await action_queue(result.tid)
                return twiml_reply(response.text)
            else:
                # Bare number — remind them of shortcuts for this track
                r = results[idx]
                return twiml_reply(
                    f"*{idx+1}. {r.title}*\n"
                    f"{r.channel} · {r.duration}\n\n"
                    f"Reply:\n"
                    f"  *{idx+1}p* — ▶ Play audio\n"
                    f"  *{idx+1}v* — 📺 Video fullscreen\n"
                    f"  *{idx+1}n* — ⏭ Play next\n"
                    f"  *{idx+1}q* — ➕ Queue"
                )

    # ── Regular dispatch (search, commands, AI) ───────────────────────────
    user_history = _history.setdefault(from_number, [])
    response: BotResponse = await dispatch(body_stripped, history=user_history)

    # Record exchange for context (cap at 6 messages = 3 turns)
    user_history.append({"role": "user", "content": body_stripped})
    user_history.append({"role": "assistant", "content": response.text})
    if len(user_history) > 6:
        user_history[:] = user_history[-6:]

    if response.kind == "results":
        _pending[from_number] = response.results
        return twiml_reply(_format_results_text(response.results))

    if response.kind == "playlists":
        lines = ["📚 *Saved Playlists*\nUse /load <name> to play one\n"]
        for pl in response.playlists:
            lines.append(f"• {pl['name']} — {pl['track_count']} tracks")
        return twiml_reply("\n".join(lines))

    return twiml_reply(response.text)


async def send_whatsapp(to: str, message: str) -> None:
    get_client().messages.create(
        from_=TWILIO_WHATSAPP_FROM,
        to=to,
        body=message,
    )
