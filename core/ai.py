"""
Groq-powered music assistant using tool calling (function calling).

Instead of rigid JSON intent classification, the LLM acts as a real assistant:
- Reads the conversation naturally
- Decides which tool(s) to call (search, play, control, web_search, etc.)
- Responds conversationally between actions
- Handles multilingual input, context, follow-ups like Claude/GPT would
"""
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Optional, Any

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


# ── Tool definitions (what the LLM can call) ─────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_music",
            "description": "Search YouTube for songs, artists, albums, podcasts, or live streams. Returns a numbered list for the user to pick from.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query in English"},
                    "video": {"type": "boolean", "description": "True if user wants to watch video fullscreen", "default": False},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_music",
            "description": "Play a specific song/artist/stream immediately (skips the search list). Use when user names something specific and clearly wants it to play now.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to play, in English"},
                    "video": {"type": "boolean", "description": "True to play as fullscreen video", "default": False},
                    "loop": {"type": "string", "enum": ["", "one", "queue"], "description": "Loop mode", "default": ""},
                    "mode": {"type": "string", "enum": ["play", "next", "queue"], "description": "play=immediate, next=after current, queue=add to end", "default": "play"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "playback_control",
            "description": "Control playback: pause, resume, skip, previous, loop on/off, shuffle, clear queue, show now playing, set volume.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["pause", "resume", "skip", "prev", "loop_on", "loop_off", "loopq", "shuffle", "playing", "clear", "stop", "play_all", "audio_mode"],
                        "description": "The control action to perform",
                    },
                    "volume": {"type": "integer", "description": "Volume level 0-150, only for volume action"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ai_playlist",
            "description": "Generate and play a curated playlist for a vibe, mood, era, or theme. e.g. 'GOATED hip hop', 'chill afrobeats', '90s RnB classics', 'workout bangers'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "theme": {"type": "string", "description": "The vibe, mood, era, or theme"},
                    "playlist_name": {"type": "string", "description": "Optional name to save the playlist as"},
                },
                "required": ["theme"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_playlist",
            "description": "Save, load, list, or delete playlists. Also create a playlist from the current session history.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["save", "load", "list", "delete", "history"], "description": "What to do"},
                    "name": {"type": "string", "description": "Playlist name (for save/load/delete)"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for news, articles, podcast episodes, or any information that isn't playable music. Use when user asks about latest news, podcast updates, artist info, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query in English"},
                },
                "required": ["query"],
            },
        },
    },
]


SYSTEM_PROMPT = """You are a smart, friendly music and media assistant — like a knowledgeable DJ and music concierge combined.

You can search and play music, podcasts, live streams, and videos from YouTube. You can control playback, manage playlists, and answer questions about music and artists.

Personality:
- Warm, conversational, and enthusiastic about music
- Respond naturally like a real assistant — not like a command parser
- Keep replies short and relevant; don't list commands unless asked
- Use the user's language if possible (Swahili, English, etc.) but always search YouTube in English

Tool use guidelines:
- "play X" → play_music immediately (don't search first)
- "find/show me/search X" → search_music to show options
- "watch X" / "show video X" → search_music or play_music with video=true (ONLY set video=true when user explicitly says watch/video)
- "play as audio" / "switch to audio" / "audio only" → playback_control action=audio_mode (NEVER use play_music for this)
- IMPORTANT: video must always be a boolean true or false, never a string
- "on loop" / "loop it" / "repeat this" → playback_control action=loop_on (always ENABLE, never toggle)
- "loop off" / "stop looping" → playback_control action=loop_off
- "not playing" / "it stopped" → playback_control action=resume
- "pause that" / "hold on" → playback_control action=pause
- Vibe/mood/theme/era requests ("chill playlist", "90s hits", "workout bangers") → ai_playlist
- "make a playlist together" / "create a playlist for us" / "can you do a whole playlist?" → ai_playlist (you pick the songs based on context/mood)
- If user says "play X on loop" → play_music with loop="one"
- News/info/podcast updates → web_search
- IMPORTANT: Use ONE tool per turn unless the second tool directly depends on the first result. Don't chain loop_on after play — use the loop parameter in play_music instead.

Always confirm what you did in a natural, brief sentence after acting.
"""


@dataclass
class AgentResult:
    """Returned to the handler layer — contains the final text and any structured data."""
    text: str
    kind: str = "text"           # text | results | playlists | error
    results: list = field(default_factory=list)
    playlists: list = field(default_factory=list)
    # Tool calls the agent decided to make — handler executes them
    tool_calls: list[dict] = field(default_factory=list)


async def run_agent(message: str, history: list[dict] | None = None) -> AgentResult:
    """
    Run one turn of the music assistant agent.
    Returns an AgentResult with tool_calls for the handler to execute,
    plus a conversational text reply.
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages.extend(history[-8:])   # last 4 exchanges
    messages.append({"role": "user", "content": message})

    try:
        resp = await get_client().chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.4,
            max_tokens=600,
        )
        msg = resp.choices[0].message
        text = msg.content or ""
        calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except Exception:
                    args = {}
                calls.append({"name": tc.function.name, "args": args})
        return AgentResult(text=text, tool_calls=calls)
    except Exception as e:
        print(f"[ai] agent error: {e}")
        return AgentResult(text="", tool_calls=[{"name": "search_music", "args": {"query": message}}])


# ── Kept for playlist curation (separate creative call) ──────────────────────

PLAYLIST_GEN_SYSTEM = """You are a world-class music curator. The user describes a vibe, era, or theme.
Return ONLY valid JSON with a list of 8-10 specific, well-known songs that perfectly match.
Format: {"songs": ["Artist - Song Title", ...], "playlist_name": "Short catchy playlist name"}
Pick real, popular songs. Prioritize variety — different artists, no filler.
"""


async def generate_playlist_songs(theme: str) -> tuple[list[str], str]:
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
