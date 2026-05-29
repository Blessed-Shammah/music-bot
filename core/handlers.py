"""
Shared message processing brain.
All adapters (Telegram, WhatsApp, Web) call into here.
Returns structured BotResponse objects — each adapter formats them for its platform.
"""
import uuid
from dataclasses import dataclass, field
from typing import Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from search import search_youtube
from player import MpvController, ensure_mpv_running
from queue_manager import QueueManager
from playlist_manager import (
    init_db, save_playlist, load_playlist,
    list_playlists, delete_playlist, rename_playlist,
)
from config import MAX_SEARCH_RESULTS, GROQ_ENABLED

init_db()

player = MpvController()
queue = QueueManager()

# Shared track store: tid -> track dict
_store: dict[str, dict] = {}


@dataclass
class SearchResult:
    tid: str
    title: str
    channel: str
    duration: str
    url: str


@dataclass
class BotResponse:
    text: str
    results: list[SearchResult] = field(default_factory=list)
    kind: str = "text"          # "text" | "results" | "playlists" | "error"
    playlists: list[dict] = field(default_factory=list)


def _store_track(track: dict) -> str:
    tid = str(uuid.uuid4())[:8]
    _store[tid] = track
    return tid


def get_track(tid: str) -> Optional[dict]:
    return _store.get(tid)


def _fmt(track: dict) -> str:
    return f"{track['title']} · {track.get('duration', '?')}"


def _seconds_to_str(s: float) -> str:
    m, sec = divmod(int(s), 60)
    return f"{m}:{sec:02d}"


# ── Search ────────────────────────────────────────────────────────────────

async def handle_search(query: str) -> BotResponse:
    results_raw = await search_youtube(query, MAX_SEARCH_RESULTS)
    if not results_raw:
        return BotResponse("No results found. Try a different search.", kind="error")

    results = []
    for r in results_raw:
        tid = _store_track(r)
        results.append(SearchResult(
            tid=tid,
            title=r["title"],
            channel=r.get("channel", ""),
            duration=r.get("duration", "?"),
            url=r["url"],
        ))
    set_last_results(results)
    return BotResponse(
        text=f"Found {len(results)} results for \"{query}\"",
        results=results,
        kind="results",
    )


# ── Playback actions ──────────────────────────────────────────────────────

async def action_play(tid: str, video: bool = False) -> BotResponse:
    track = get_track(tid)
    if not track:
        return BotResponse("Track expired — search again.", kind="error")
    try:
        await ensure_mpv_running(player)
    except RuntimeError as e:
        return BotResponse(str(e), kind="error")
    await player.set_loop_file(False)
    queue.set_current(track)
    ok = await player.play(track["url"], video=video)
    if not ok:
        return BotResponse("⚠️ mpv didn't respond. Try: sudo apt install mpv")
    mode = "📺 Playing video" if video else "▶ Playing"
    return BotResponse(f"{mode}: {_fmt(track)}")


async def action_next(tid: str) -> BotResponse:
    track = get_track(tid)
    if not track:
        return BotResponse("Track expired — search again.", kind="error")
    queue.play_next(track)
    return BotResponse(f"⏭ Playing next: {track['title']}")


async def action_queue(tid: str) -> BotResponse:
    track = get_track(tid)
    if not track:
        return BotResponse("Track expired — search again.", kind="error")
    pos = queue.add_to_queue(track)
    return BotResponse(f"➕ Added at position {pos}: {track['title']}")


# ── Commands ──────────────────────────────────────────────────────────────

async def cmd_playing() -> BotResponse:
    title = await player.get_current_title()
    pos = await player.get_time_pos()
    dur = await player.get_duration()
    vol = await player.get_volume()
    current = queue.current()

    name = title or (current["title"] if current else None)
    if not name:
        return BotResponse("Nothing is playing right now.")

    progress = ""
    if pos is not None and dur:
        filled = int((pos / dur) * 20)
        bar = "█" * filled + "░" * (20 - filled)
        progress = f"\n{bar} {_seconds_to_str(pos)} / {_seconds_to_str(dur)}"

    vol_str = f"  🔊 {vol}%" if vol is not None else ""
    return BotResponse(f"▶ {name}{progress}\n{queue.status()}{vol_str}")


async def cmd_pause() -> BotResponse:
    await player.pause_toggle()
    return BotResponse("⏸ Toggled pause.")


async def cmd_skip() -> BotResponse:
    if queue.loop_one:
        return BotResponse("🔂 Loop-one is on — use /loop to turn it off first.")
    next_track = queue.pop_next()
    if next_track:
        queue.set_current(next_track)
        await ensure_mpv_running(player)
        await player.play(next_track["url"])
        return BotResponse(f"⏭ {_fmt(next_track)}")
    await player.stop()
    return BotResponse("⏹ Queue empty, stopped.")


async def cmd_prev() -> BotResponse:
    prev = queue.previous()
    if prev:
        await ensure_mpv_running(player)
        await player.play(prev["url"])
        queue._current = prev
        return BotResponse(f"⏮ {_fmt(prev)}")
    return BotResponse("No previous track.")


async def cmd_seek(args: list[str]) -> BotResponse:
    if not args:
        return BotResponse("Usage: /seek <seconds>  e.g. /seek -15 or /seek 30")
    try:
        secs = int(args[0])
    except ValueError:
        return BotResponse("Please give a number of seconds.")
    await player.seek(secs)
    direction = "forward" if secs >= 0 else "back"
    return BotResponse(f"⏩ Seeked {direction} {abs(secs)}s")


async def cmd_vol(args: list[str]) -> BotResponse:
    if not args:
        vol = await player.get_volume()
        return BotResponse(f"🔊 Volume: {vol}%\nUsage: /vol <0-150>")
    try:
        level = int(args[0])
    except ValueError:
        return BotResponse("Usage: /vol <0-150>")
    await player.set_volume(level)
    return BotResponse(f"🔊 Volume set to {level}%")


async def cmd_loop() -> BotResponse:
    enabled = queue.toggle_loop_one()
    await player.set_loop_file(enabled)
    return BotResponse("🔂 Loop one ON" if enabled else "➡️ Loop one OFF")


async def cmd_loop_on() -> BotResponse:
    queue.loop_one = True
    queue.loop_queue = False
    await player.set_loop_file(True)
    return BotResponse("🔂 Looping this song")


async def cmd_loop_off() -> BotResponse:
    queue.loop_one = False
    queue.loop_queue = False
    await player.set_loop_file(False)
    return BotResponse("➡️ Loop OFF")


async def cmd_loopq() -> BotResponse:
    enabled = queue.toggle_loop_queue()
    return BotResponse("🔁 Loop queue ON" if enabled else "➡️ Loop queue OFF")


async def cmd_resume() -> BotResponse:
    """Resume: unpause if paused, else replay current track."""
    current = queue.current()
    if not current:
        return BotResponse("Nothing to resume — search for something to play.")
    try:
        await ensure_mpv_running(player)
    except RuntimeError as e:
        return BotResponse(str(e), kind="error")
    # Try unpausing first; if mpv isn't playing anything, replay
    pos = await player.get_time_pos()
    if pos is None:
        await player.play(current["url"])
        return BotResponse(f"▶ Playing: {_fmt(current)}")
    await player.pause_toggle()
    return BotResponse(f"▶ Resumed: {_fmt(current)}")


async def cmd_shuffle() -> BotResponse:
    if not queue.get_queue():
        return BotResponse("Queue is empty.")
    queue.shuffle()
    items = queue.get_queue()
    return BotResponse(f"🔀 Shuffled {len(items)} tracks. Next: {items[0]['title']}")


async def cmd_queue_list() -> BotResponse:
    items = queue.get_queue()
    current = queue.current()
    lines = []
    if current:
        lines.append(f"▶ Now: {_fmt(current)}")
    if items:
        for i, t in enumerate(items, 1):
            lines.append(f"{i}. {_fmt(t)}")
    else:
        lines.append("Queue is empty.")
    lines.append(queue.status())
    return BotResponse("\n".join(lines))


async def cmd_remove(args: list[str]) -> BotResponse:
    if not args:
        return BotResponse("Usage: /remove <number>")
    try:
        idx = int(args[0]) - 1
    except ValueError:
        return BotResponse("Please give a track number.")
    removed = queue.remove_at(idx)
    if removed:
        return BotResponse(f"🗑 Removed: {removed['title']}")
    return BotResponse("Track not found at that position.")


async def cmd_clear() -> BotResponse:
    queue.clear()
    return BotResponse("🗑 Queue cleared.")


async def cmd_save(args: list[str]) -> BotResponse:
    if not args:
        return BotResponse("Usage: /save <playlist name>")
    name = " ".join(args)
    tracks = queue.get_queue()
    current = queue.current()
    all_tracks = ([current] if current else []) + tracks
    if not all_tracks:
        return BotResponse("Nothing to save — queue is empty.")
    save_playlist(name, all_tracks)
    return BotResponse(f"💾 Saved \"{name}\" ({len(all_tracks)} tracks)")


async def cmd_load(args: list[str]) -> BotResponse:
    if not args:
        return BotResponse("Usage: /load <playlist name>")
    name = " ".join(args)
    tracks = load_playlist(name)
    if tracks is None:
        return BotResponse(f"No playlist named \"{name}\".")
    queue.clear()
    first, *rest = tracks
    queue.set_current(first)
    for t in rest:
        queue.add_to_queue(t)
    await ensure_mpv_running(player)
    await player.set_loop_file(False)
    await player.play(first["url"])
    return BotResponse(f"▶ Loaded \"{name}\" — {len(tracks)} tracks\nNow playing: {_fmt(first)}")


async def cmd_playlists() -> BotResponse:
    pls = list_playlists()
    if not pls:
        return BotResponse("No saved playlists yet.\nUse /save <name> to create one.")
    return BotResponse(
        text=f"{len(pls)} saved playlists",
        playlists=pls,
        kind="playlists",
    )


async def cmd_delplaylist(args: list[str]) -> BotResponse:
    if not args:
        return BotResponse("Usage: /delplaylist <name>")
    name = " ".join(args)
    if delete_playlist(name):
        return BotResponse(f"🗑 Deleted playlist \"{name}\".")
    return BotResponse(f"No playlist named \"{name}\".")


async def cmd_rename(args: list[str]) -> BotResponse:
    if not args:
        return BotResponse("Usage: /rename <old> > <new>")
    raw = " ".join(args)
    if ">" in raw:
        old, new = [s.strip() for s in raw.split(">", 1)]
    else:
        mid = len(args) // 2
        old, new = " ".join(args[:mid]), " ".join(args[mid:])
    if rename_playlist(old, new):
        return BotResponse(f"✏️ Renamed \"{old}\" → \"{new}\"")
    return BotResponse("Could not rename — check the name exists and new name isn't taken.")


# ── Bulk search (list of songs → queue all + optional playlist save) ──────

async def handle_bulk_search(songs: list, playlist_name: str = "") -> BotResponse:
    """Search each song (str queries or pre-resolved dicts), queue all, optionally save."""
    if not songs:
        return BotResponse("No songs found in your list.", kind="error")

    found: list[dict] = []
    not_found: list[str] = []

    for song in songs[:15]:
        if isinstance(song, dict):          # already a resolved track (from history/play_all)
            found.append(song)
        else:
            results = await search_youtube(song, max_results=1)
            if results:
                found.append(results[0])
            else:
                not_found.append(song)

    if not found:
        return BotResponse("Couldn't find any of those songs. Try different names.")

    # Queue all found tracks — resolve first track stream URL immediately
    await ensure_mpv_running(player)
    first_played = False
    for track in found:
        if not first_played and not queue.current():
            queue.set_current(track)
            await player.play(track["url"])
            first_played = True
        else:
            queue.add_to_queue(track)

    # Optionally save as playlist
    if playlist_name:
        save_playlist(playlist_name, found)
        saved_msg = f"\n💾 Saved as playlist \"{playlist_name}\""
    else:
        saved_msg = ""

    lines = [f"✅ Queued {len(found)} tracks:{saved_msg}\n"]
    for i, t in enumerate(found, 1):
        lines.append(f"{i}. {t['title']} · {t.get('duration','?')}")
    if not_found:
        lines.append(f"\n⚠️ Not found: {', '.join(not_found)}")

    return BotResponse("\n".join(lines))


# ── History playlist ──────────────────────────────────────────────────────

async def handle_history_playlist(playlist_name: str = "") -> BotResponse:
    """Save all songs played this session as a playlist and play on loop."""
    history = queue.get_session_history()
    if not history:
        return BotResponse("No songs played yet this session. Play something first!")

    name = playlist_name or "Session Mix"
    save_playlist(name, history)

    # Load it into queue and loop
    queue.clear()
    first, *rest = history
    queue.set_current(first)
    for t in rest:
        queue.add_to_queue(t)
    queue.loop_queue = True
    queue.loop_one = False

    await ensure_mpv_running(player)
    await player.play(first["url"])

    lines = [f"💾 Saved \"{name}\" — {len(history)} tracks\n▶ Playing on loop:\n"]
    for i, t in enumerate(history, 1):
        lines.append(f"{i}. {t['title']}")
    return BotResponse("\n".join(lines))


# ── AI-curated playlist ───────────────────────────────────────────────────

async def handle_ai_playlist(theme: str, playlist_name: str = "", loop: str = "") -> BotResponse:
    """Use Groq to curate songs for a theme, then bulk-search and play them."""
    from core.ai import generate_playlist_songs
    songs, ai_name = await generate_playlist_songs(theme)
    if not songs:
        return BotResponse(f"Couldn't generate a playlist for \"{theme}\" — try describing the vibe differently.")

    name = playlist_name or ai_name
    result = await handle_bulk_search(songs, name)

    # Apply loop only when explicitly requested
    if loop == "one":
        queue.loop_one = True
        await player.set_loop_file(True)
        result = BotResponse(result.text + "\n🔂 Looping first track")
    elif loop == "queue":
        queue.loop_queue = True
        result = BotResponse(result.text + "\n🔁 Looping playlist")

    return result


# ── Play all pending results ──────────────────────────────────────────────

# Shared store for last search results per adapter (whatsapp fills this too)
_last_results: list[dict] = []


def set_last_results(results: list) -> None:
    global _last_results
    _last_results = [{"title": r.title, "url": r.url,
                      "duration": r.duration, "channel": r.channel}
                     for r in results]


async def handle_play_all() -> BotResponse:
    """Queue and play all results from the last search."""
    if not _last_results:
        return BotResponse("No recent search results to play. Search for something first.")
    return await handle_bulk_search(_last_results)


# ── Command router (slash commands) ──────────────────────────────────────

async def _route_command(cmd: str, args: list[str]) -> BotResponse:
    no_arg_map = {
        "start": lambda: BotResponse(
            "🎵 Music Chat\n\nJust tell me what to play — or send a list of songs!\n\n"
            "Try: \"play Hotline Bling\", \"next God's Plan\", or paste a song list.\n\n"
            "Commands: /playing /pause /skip /prev /loop /loopq /shuffle "
            "/queue /clear /playlists"
        ),
        "help":     lambda: _route_command("start", []),
        "playing":  cmd_playing,
        "pause":    cmd_pause,
        "resume":   cmd_resume,
        "play":     cmd_resume,
        "skip":     cmd_skip,
        "prev":     cmd_prev,
        "loop":     cmd_loop,
        "loop_on":  cmd_loop_on,
        "loop_off": cmd_loop_off,
        "loopq":    cmd_loopq,
        "shuffle":  cmd_shuffle,
        "queue":    cmd_queue_list,
        "clear":    cmd_clear,
        "playlists": cmd_playlists,
        "stop":     cmd_clear,
        "play_all": handle_play_all,
    }
    args_map = {
        "seek":        cmd_seek,
        "vol":         cmd_vol,
        "remove":      cmd_remove,
        "save":        cmd_save,
        "load":        cmd_load,
        "delplaylist": cmd_delplaylist,
        "rename":      cmd_rename,
    }
    import inspect
    if cmd in no_arg_map:
        fn = no_arg_map[cmd]
        result = fn()
        return (await result) if inspect.isawaitable(result) else result
    elif cmd in args_map:
        return await args_map[cmd](args)
    return BotResponse(f"Unknown command /{cmd} — type /help")


# ── Agent tool executor ───────────────────────────────────────────────────

async def _execute_tool(name: str, args: dict) -> BotResponse:
    """Execute a single tool call from the agent and return a BotResponse."""

    if name == "search_music":
        query = args.get("query", "")
        video = args.get("video", False)
        results_raw = await search_youtube(query, MAX_SEARCH_RESULTS)
        if not results_raw:
            sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
            from adapters.websearch import web_search, format_results
            web_results = await web_search(query)
            if web_results:
                return BotResponse(f"No YouTube results — here's what I found:\n\n{format_results(web_results)}")
            return BotResponse(f"Nothing found for \"{query}\".", kind="error")
        sr_list = []
        for r in results_raw:
            tid = _store_track(r)
            sr_list.append(SearchResult(tid=tid, title=r["title"],
                                        channel=r.get("channel", ""), duration=r.get("duration", "?"),
                                        url=r["url"]))
        set_last_results(sr_list)
        # Tag results with video intent so adapters know
        return BotResponse(text=f"Found {len(sr_list)} results for \"{query}\"",
                           results=sr_list, kind="results")

    if name == "play_music":
        query = args.get("query", "")
        video = args.get("video", False)
        mode = args.get("mode", "play")
        loop = args.get("loop", "")
        results = await search_youtube(query, max_results=1)
        if not results:
            return BotResponse(f"Couldn't find \"{query}\".", kind="error")
        track = results[0]
        tid = _store_track(track)
        if mode == "next":
            resp = await action_next(tid)
        elif mode == "queue":
            resp = await action_queue(tid)
        else:
            resp = await action_play(tid, video=video)
        if loop == "one":
            queue.loop_one = True
            queue.loop_queue = False
            await player.set_loop_file(True)
            resp = BotResponse(resp.text + "\n🔂 Looping this song")
        elif loop == "queue":
            queue.loop_queue = True
            queue.loop_one = False
            resp = BotResponse(resp.text + "\n🔁 Looping queue")
        return resp

    if name == "playback_control":
        action = args.get("action", "")
        if action == "volume" and "volume" in args:
            return await cmd_vol([str(args["volume"])])
        return await _route_command(action, [])

    if name == "ai_playlist":
        theme = args.get("theme", "")
        playlist_name = args.get("playlist_name", "")
        return await handle_ai_playlist(theme, playlist_name)

    if name == "manage_playlist":
        action = args.get("action", "")
        pname = args.get("name", "")
        if action == "save":
            return await cmd_save([pname] if pname else [])
        if action == "load":
            return await cmd_load([pname] if pname else [])
        if action == "list":
            return await cmd_playlists()
        if action == "delete":
            return await cmd_delplaylist([pname] if pname else [])
        if action == "history":
            return await handle_history_playlist(pname)

    if name == "web_search":
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        from adapters.websearch import web_search, format_results
        results = await web_search(args.get("query", ""))
        return BotResponse(format_results(results))

    return BotResponse(f"Unknown tool: {name}", kind="error")


# ── AI-powered dispatcher ─────────────────────────────────────────────────

async def dispatch(text: str, history: list[dict] | None = None) -> BotResponse:
    """
    Single entry point for all adapters.
    Slash commands bypass AI. Natural language goes through the Groq tool-calling agent.
    """
    text = text.strip()

    # Slash commands always bypass AI
    if text.startswith("/"):
        parts = text[1:].split()
        cmd = parts[0].lower() if parts else ""
        return await _route_command(cmd, parts[1:])

    if GROQ_ENABLED:
        from core.ai import run_agent
        result = await run_agent(text, history=history)

        # If the agent made tool calls, execute them and collect responses
        if result.tool_calls:
            responses = []
            last_resp = None
            for call in result.tool_calls:
                last_resp = await _execute_tool(call["name"], call["args"])
                responses.append(last_resp)

            # If multiple tools ran, merge text; use the last structured response
            if len(responses) == 1:
                final = responses[0]
            else:
                combined_text = "\n\n".join(r.text for r in responses if r.text)
                # Use the last response that has structured data, otherwise plain text
                structured = next((r for r in reversed(responses) if r.kind != "text"), None)
                final = structured or BotResponse(combined_text)
                if structured and result.text:
                    final = BotResponse(result.text or combined_text,
                                        results=structured.results,
                                        kind=structured.kind,
                                        playlists=structured.playlists)

            # Prepend the agent's conversational reply if it said something
            if result.text and final.kind == "text":
                final = BotResponse(result.text, kind="text")
            elif result.text and final.kind == "results":
                # Agent narrated + returned results — use agent text as context
                pass
            return final

        # Agent chose not to call any tool — pure conversational reply
        return BotResponse(result.text or "I didn't quite get that — what would you like to hear?")

    # No Groq — plain search
    return await handle_search(text)
