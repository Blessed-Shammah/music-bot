"""
Twilio WhatsApp adapter with interactive quick-reply buttons.

Flow:
  Search  → bot sends numbered list + "Pick a number" quick-reply buttons (1-5)
  Pick #  → bot sends action quick-reply buttons (▶ Play / ⏭ Next / ➕ Queue)
  Action  → bot executes and confirms

Templates are created once via Twilio Content API and their SIDs cached in memory.
"""
import json
import re
import os
import sys
from typing import Optional

from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.handlers import dispatch, action_play, action_next, action_queue, BotResponse, handle_bulk_search
from config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, TWILIO_WHATSAPP_TO

# Per-user pending search results: phone_number -> list of SearchResult
_pending: dict[str, list] = {}

# Cached Content template SIDs (created once, reused forever)
_sid_pick: Optional[str] = None    # "Pick a track" buttons: 1 2 3 4 5
_sid_action: Optional[str] = None  # "What to do" buttons: Play Next Queue

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


# ── Content API template management ──────────────────────────────────────

def _create_template(friendly_name: str, body: str, buttons: list[str]) -> str:
    """Create a quick-reply Content template and return its SID."""
    client = get_client()
    actions = [{"title": b, "id": b.lower().replace(" ", "_")} for b in buttons]
    content = client.content.v1.contents.create(
        friendly_name=friendly_name,
        types={
            "twilio/quick-reply": {
                "body": body,
                "actions": actions,
            }
        },
        language="en",
        variables={"1": "placeholder"},
    )
    return content.sid


def _get_or_create_pick_sid(n: int) -> str:
    global _sid_pick
    if not _sid_pick:
        buttons = [str(i) for i in range(1, min(n, 3) + 1)]  # WhatsApp max 3 buttons
        _sid_pick = _create_template(
            "music_pick_track",
            "{{1}}",  # dynamic body via variable
            buttons,
        )
    return _sid_pick


def _get_or_create_action_sid() -> str:
    global _sid_action
    if not _sid_action:
        _sid_action = _create_template(
            "music_track_action",
            "{{1}}",
            ["▶ Play", "⏭ Next", "➕ Queue"],
        )
    return _sid_action


def _send_interactive(to: str, content_sid: str, body: str) -> None:
    """Send an interactive Content template message."""
    get_client().messages.create(
        from_=TWILIO_WHATSAPP_FROM,
        to=to,
        content_sid=content_sid,
        content_variables=json.dumps({"1": body}),
    )


# ── Message handling ──────────────────────────────────────────────────────

def _format_results_text(results: list) -> str:
    lines = ["🎵 *Search Results*\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r.title}\n   {r.channel} · {r.duration}")
    return "\n".join(lines)


async def handle_whatsapp_message(from_number: str, body: str) -> str:
    body_stripped = body.strip()
    normalized = body_stripped.lower()

    # ── "play all" → queue all pending results ────────────────────────────
    if normalized in ("play all", "all") and from_number in _pending:
        tracks = [{"title": r.title, "url": r.url,
                   "duration": r.duration, "channel": r.channel}
                  for r in _pending[from_number]]
        resp = await handle_bulk_search(tracks)
        return twiml_reply(resp.text)

    # ── Button callback IDs come back exactly as set (e.g. "▶ play", "1", "2") ──
    # Handle action button responses
    action_map = {
        "▶ play": action_play,
        "⏭ next": action_next,
        "➕ queue": action_queue,
        "play": action_play,
        "next": action_next,
        "queue": action_queue,
    }
    if normalized in action_map and f"{from_number}_selected" in _pending:
        tid = _pending.pop(f"{from_number}_selected")
        fn = action_map[normalized]
        response = await fn(tid)
        return twiml_reply(response.text)

    # Handle number selection (button or typed)
    num_match = re.match(r'^(\d+)([pnq]?)$', body_stripped, re.IGNORECASE)
    if num_match and from_number in _pending:
        idx = int(num_match.group(1)) - 1
        shortcut = num_match.group(2).lower()
        results = _pending[from_number]

        if 0 <= idx < len(results):
            result = results[idx]
            # Direct shortcut: 1p / 1n / 1q
            if shortcut in ("p", "n", "q"):
                fn = {"p": action_play, "n": action_next, "q": action_queue}[shortcut]
                response = await fn(result.tid)
                return twiml_reply(response.text)

            # No shortcut — show action buttons for this track
            track_line = f"{result.title} · {result.duration}"
            try:
                sid = _get_or_create_action_sid()
                _pending[f"{from_number}_selected"] = result.tid
                _send_interactive(from_number, sid, track_line)
                return twiml_reply("")  # empty TwiML — interactive msg sent separately
            except Exception:
                # Fallback to text if Content API fails
                return twiml_reply(
                    f"*{result.title}*\nReply: {idx+1}p=Play  {idx+1}n=Next  {idx+1}q=Queue"
                )

    # ── Regular dispatch (search, commands) ──────────────────────────────
    response: BotResponse = await dispatch(body_stripped)

    if response.kind == "results":
        _pending[from_number] = response.results
        results_text = _format_results_text(response.results)
        n = len(response.results)

        # Try interactive buttons (max 3 due to WhatsApp limit)
        try:
            sid = _get_or_create_pick_sid(n)
            _send_interactive(from_number, sid, results_text + "\n\nTap a number to select:")
            return twiml_reply("")
        except Exception:
            # Fallback: plain text with instructions
            return twiml_reply(results_text + "\n\nReply with number (e.g. 1) to select")

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
