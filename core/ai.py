"""
Groq-powered intent parser.
Converts any natural language message into a structured Intent so the bot
understands "hi", "play hotline bling next", or a pasted song list.

Uses Groq's OpenAI-compatible API (llama-3.3-70b-versatile) — ~100-200ms.
"""
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

from openai import AsyncOpenAI

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import GROQ_API_KEY

_client: Optional[AsyncOpenAI] = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
        )
    return _client


PLAYLIST_GEN_SYSTEM = """You are a world-class music curator. The user describes a vibe, era, or theme.
Return ONLY valid JSON with a list of 8-10 specific, well-known songs that perfectly match.
Format: {"songs": ["Artist - Song Title", ...], "playlist_name": "Short catchy playlist name"}
Pick real, popular songs. Prioritize variety — different artists, no filler.
"""


async def generate_playlist_songs(theme: str) -> tuple[list[str], str]:
    """Ask Groq to generate a curated list of specific songs for a theme."""
    try:
        resp = await get_client().chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": PLAYLIST_GEN_SYSTEM},
                {"role": "user", "content": theme},
            ],
            temperature=0.7,
            max_tokens=500,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
        return data.get("songs", []), data.get("playlist_name", theme[:30])
    except Exception as e:
        print(f"[ai] playlist gen error: {e}")
        return [], theme[:30]


@dataclass
class Intent:
    type: str           # search | action | command | chat | bulk_search | ai_playlist | history_playlist | info
    query: str = ""     # for search/action/info: the cleaned query
    action: str = ""    # for action: play | next | queue
    loop: str = ""      # "" | "one" | "queue" — loop modifier
    command: str = ""   # skip|pause|resume|loop_on|loop_off|loop|loopq|shuffle|playing|clear|prev|stop|play_all
    message: str = ""   # for chat: a friendly reply
    video: bool = False # true when user wants to watch video (show on screen)
    songs: list[str] = field(default_factory=list)
    playlist_name: str = ""
    theme: str = ""


_SYSTEM = """You are a friendly music/media bot assistant. Parse the user's message and return ONLY valid JSON.

Intent types:
- "search"           — find a song, artist, podcast, live stream, or any media on YouTube
- "action"           — play/queue a SPECIFIC named song/stream immediately
- "command"          — playback control (no content named): skip, pause, loop, loopq, shuffle, playing, clear, prev, stop, play_all
- "chat"             — pure greetings or thanks with NO media/info request implied
- "bulk_search"      — a LIST of 2+ specific songs to queue
- "ai_playlist"      — user describes a vibe/theme/era and wants the bot to pick songs
- "history_playlist" — user wants a playlist made from songs already played this session
- "info"             — user wants information/news/web results (not playable content): e.g. "latest posts from X podcast", "news about Y", "what happened with Z"

JSON schema:
{
  "type": "search"|"action"|"command"|"chat"|"bulk_search"|"ai_playlist"|"history_playlist"|"info",
  "query": "clean search query in English (search/action/info)",
  "action": "play"|"next"|"queue",
  "loop": ""|"one"|"queue",
  "video": false,
  "command": "skip|pause|resume|loop_on|loop_off|loop|loopq|shuffle|playing|clear|prev|stop|play_all",
  "message": "short friendly reply (chat only, 1-2 sentences max)",
  "songs": ["Artist - Song", ...],
  "playlist_name": "name to save as",
  "theme": "the vibe/theme for ai_playlist"
}

Rules:
- MULTILINGUAL: User may write in Swahili, French, Arabic, or any language. Always translate query to English for YouTube search. e.g. "Iko nini podcast" (Swahili) → search, query="latest podcast episodes"
- Short ambiguous follow-ups ("latest info", "more", "what about X") → use conversation history to infer intent, default to search
- "play X" → action, action=play, query=X
- "play X on loop/repeat" → action, action=play, query=X, loop=one
- "next X" / "play X next" → action, action=next
- "queue X" → action, action=queue
- "on loop" / "loop this" / "loop it" / "repeat this" / "put it on loop" → command, command=loop_on  (ALWAYS enable, never toggle)
- "loop off" / "stop looping" / "no loop" / "disable loop" → command, command=loop_off
- "pause" / "pause that" / "pause it" / "hold on" / "stop that" → command, command=pause
- "resume" / "play" (no song named) / "continue" / "unpause" → command, command=resume
- "not playing" / "it stopped" / "nothing is playing" / "play it again" → command, command=resume
- "watch X" / "show video X" / "play video X" / "show me X" → action, action=play, video=true, query=X
- bare song/artist/podcast name → search
- "latest episodes of X podcast" / "X podcast news" / "what has X posted" → info, query="X podcast latest 2024"
- news queries, article queries, "what happened with X" → info
- 2+ songs listed → bulk_search
- vibe/mood/genre/era request → ai_playlist, theme=the description
- "playlist of songs we played" / "session history" → history_playlist
- "play all" / "queue all" → command, command=play_all
- chat: ONLY for pure greetings/thanks. If there's ANY media/content/info request implied, use search or info instead.
- chat replies: warm and brief — 1 line max. Never list commands unless asked.
- Return valid JSON only, no markdown fences
"""


async def parse_intent(message: str, history: list[dict] | None = None) -> Intent:
    """Parse a user message into a structured Intent using Groq."""
    try:
        messages = [{"role": "system", "content": _SYSTEM}]
        if history:
            messages.extend(history[-6:])   # last 3 exchanges for context
        messages.append({"role": "user", "content": message})
        resp = await get_client().chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0,
            max_tokens=300,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
        return Intent(
            type=data.get("type", "search"),
            query=data.get("query", ""),
            action=data.get("action", ""),
            loop=data.get("loop", ""),
            command=data.get("command", ""),
            message=data.get("message", ""),
            video=bool(data.get("video", False)),
            songs=data.get("songs", []),
            playlist_name=data.get("playlist_name", ""),
            theme=data.get("theme", ""),
        )
    except Exception as e:
        print(f"[ai] Groq error: {e} — falling back to search")
        # Safe fallback: treat as search
        return Intent(type="search", query=message)
