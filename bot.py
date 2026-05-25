import uuid
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes,
)

from config import TELEGRAM_TOKEN, MAX_SEARCH_RESULTS
from search import search_youtube
from player import MpvController, ensure_mpv_running
from queue_manager import QueueManager
from playlist_manager import (
    init_db, save_playlist, load_playlist,
    list_playlists, delete_playlist, rename_playlist,
)

init_db()

player = MpvController()
queue = QueueManager()

_track_store: dict[str, dict] = {}


def _store(track: dict) -> str:
    tid = str(uuid.uuid4())[:8]
    _track_store[tid] = track
    return tid


def _get(tid: str) -> dict | None:
    return _track_store.get(tid)


def _fmt(track: dict) -> str:
    return f"`{track['title']}` · {track.get('duration', '?')}"


def _seconds_to_str(s: float) -> str:
    m, sec = divmod(int(s), 60)
    return f"{m}:{sec:02d}"


# ── /start ───────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "🎵 *Music Chat Bot*\n\n"
        "Type any song name to search. Then tap a button to play, queue, or save.\n\n"
        "*Playback*\n"
        "`/playing` — current track + progress\n"
        "`/pause` — pause / resume\n"
        "`/skip` — next track\n"
        "`/prev` — previous track\n"
        "`/seek <sec>` — jump forward/back (e.g. `/seek -15`)\n"
        "`/vol <0-150>` — set volume\n"
        "`/loop` — loop current song 🔂\n"
        "`/loopq` — loop entire queue 🔁\n"
        "`/shuffle` — shuffle the queue\n\n"
        "*Queue*\n"
        "`/queue` — show queue\n"
        "`/remove <n>` — remove track #n\n"
        "`/clear` — clear queue\n\n"
        "*Playlists*\n"
        "`/save <name>` — save current queue as playlist\n"
        "`/load <name>` — load a saved playlist\n"
        "`/playlists` — list saved playlists\n"
        "`/delplaylist <name>` — delete a playlist\n"
        "`/rename <old> <new>` — rename a playlist"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ── Search ───────────────────────────────────────────────────────────────

async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.message.text.strip()
    msg = await update.message.reply_text(f"🔍 Searching `{query}`...", parse_mode="Markdown")

    results = await search_youtube(query, MAX_SEARCH_RESULTS)
    if not results:
        await msg.edit_text("No results found. Try a different search.")
        return

    lines, keyboards = [], []
    for i, track in enumerate(results, 1):
        tid = _store(track)
        lines.append(f"*{i}.* `{track['title']}`\n    {track['channel']} · {track.get('duration', '?')}")
        keyboards.append([
            InlineKeyboardButton("▶ Play", callback_data=f"play:{tid}"),
            InlineKeyboardButton("⏭ Next", callback_data=f"next:{tid}"),
            InlineKeyboardButton("➕ Queue", callback_data=f"queue:{tid}"),
        ])

    await msg.edit_text(
        "\n\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboards),
        parse_mode="Markdown",
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cb = update.callback_query
    await cb.answer()

    action, tid = cb.data.split(":", 1)
    track = _get(tid)
    if not track:
        await cb.answer("Session expired — search again.", show_alert=True)
        return

    await ensure_mpv_running(player)

    if action == "play":
        queue.set_current(track)
        await player.set_loop_file(False)
        await player.play(track["url"])
        await cb.answer(f"▶ {track['title'][:40]}")

    elif action == "next":
        queue.play_next(track)
        await cb.answer(f"⏭ Up next: {track['title'][:40]}")

    elif action == "queue":
        pos = queue.add_to_queue(track)
        await cb.answer(f"➕ Position {pos} in queue")

    elif action == "pl_load":
        # tid is playlist name here
        tracks = load_playlist(tid)
        if not tracks:
            await cb.answer("Playlist not found.", show_alert=True)
            return
        queue.clear()
        first, *rest = tracks
        queue.set_current(first)
        for t in rest:
            queue.add_to_queue(t)
        await player.set_loop_file(False)
        await player.play(first["url"])
        await cb.answer(f"▶ Loaded '{tid}' ({len(tracks)} tracks)")


# ── Playback commands ────────────────────────────────────────────────────

async def cmd_playing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    title = await player.get_current_title()
    pos = await player.get_time_pos()
    dur = await player.get_duration()
    vol = await player.get_volume()
    current = queue.current()

    name = title or (current["title"] if current else None)
    if not name:
        await update.message.reply_text("Nothing is playing.")
        return

    progress = ""
    if pos is not None and dur:
        filled = int((pos / dur) * 20)
        bar = "█" * filled + "░" * (20 - filled)
        progress = f"\n`{bar}` {_seconds_to_str(pos)} / {_seconds_to_str(dur)}"

    loop_status = queue.status()
    vol_str = f"🔊 {vol}%" if vol is not None else ""

    await update.message.reply_text(
        f"▶ `{name}`{progress}\n{loop_status}  {vol_str}",
        parse_mode="Markdown",
    )


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await player.pause_toggle()
    await update.message.reply_text("⏸ Toggled pause.")


async def cmd_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if queue.loop_one:
        await update.message.reply_text("🔂 Loop-one is on — use /loop to turn it off first.")
        return
    next_track = queue.pop_next()
    if next_track:
        queue.set_current(next_track)
        await ensure_mpv_running(player)
        await player.play(next_track["url"])
        await update.message.reply_text(f"⏭ {_fmt(next_track)}", parse_mode="Markdown")
    else:
        await player.stop()
        await update.message.reply_text("⏹ Queue empty, stopped.")


async def cmd_prev(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    prev = queue.previous()
    if prev:
        await ensure_mpv_running(player)
        await player.play(prev["url"])
        queue._current = prev
        await update.message.reply_text(f"⏮ {_fmt(prev)}", parse_mode="Markdown")
    else:
        await update.message.reply_text("No previous track.")


async def cmd_seek(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/seek <seconds>` e.g. `/seek -15` or `/seek 30`", parse_mode="Markdown")
        return
    try:
        secs = int(args[0])
    except ValueError:
        await update.message.reply_text("Please give a number of seconds.")
        return
    await player.seek(secs)
    direction = "forward" if secs >= 0 else "back"
    await update.message.reply_text(f"⏩ Seeked {direction} {abs(secs)}s")


async def cmd_vol(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        vol = await player.get_volume()
        await update.message.reply_text(f"🔊 Volume: {vol}%\nUsage: `/vol <0-150>`", parse_mode="Markdown")
        return
    try:
        level = int(args[0])
    except ValueError:
        await update.message.reply_text("Usage: `/vol <0-150>`", parse_mode="Markdown")
        return
    await player.set_volume(level)
    await update.message.reply_text(f"🔊 Volume set to {level}%")


async def cmd_loop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    enabled = queue.toggle_loop_one()
    await player.set_loop_file(enabled)
    status = "🔂 Loop one ON" if enabled else "➡️ Loop one OFF"
    await update.message.reply_text(status)


async def cmd_loopq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    enabled = queue.toggle_loop_queue()
    status = "🔁 Loop queue ON" if enabled else "➡️ Loop queue OFF"
    await update.message.reply_text(status)


async def cmd_shuffle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not queue.get_queue():
        await update.message.reply_text("Queue is empty.")
        return
    queue.shuffle()
    items = queue.get_queue()
    await update.message.reply_text(
        f"🔀 Shuffled {len(items)} tracks. Next up: `{items[0]['title']}`",
        parse_mode="Markdown",
    )


# ── Queue commands ───────────────────────────────────────────────────────

async def cmd_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    items = queue.get_queue()
    current = queue.current()
    lines = []
    if current:
        lines.append(f"▶ *Now:* {_fmt(current)}")
    if items:
        lines.append("")
        for i, t in enumerate(items, 1):
            lines.append(f"{i}. {_fmt(t)}")
    else:
        lines.append("_Queue is empty_")
    lines.append(f"\n{queue.status()}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/remove <number>`", parse_mode="Markdown")
        return
    try:
        idx = int(args[0]) - 1
    except ValueError:
        await update.message.reply_text("Please give a track number.")
        return
    removed = queue.remove_at(idx)
    if removed:
        await update.message.reply_text(f"🗑 Removed: `{removed['title']}`", parse_mode="Markdown")
    else:
        await update.message.reply_text("Track not found at that position.")


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    queue.clear()
    await update.message.reply_text("🗑 Queue cleared.")


# ── Playlist commands ────────────────────────────────────────────────────

async def cmd_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: `/save <playlist name>`", parse_mode="Markdown")
        return
    name = " ".join(context.args)
    tracks = queue.get_queue()
    current = queue.current()
    all_tracks = ([current] if current else []) + tracks
    if not all_tracks:
        await update.message.reply_text("Nothing to save — queue is empty.")
        return
    save_playlist(name, all_tracks)
    await update.message.reply_text(
        f"💾 Saved *{name}* ({len(all_tracks)} tracks)", parse_mode="Markdown"
    )


async def cmd_load(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: `/load <playlist name>`", parse_mode="Markdown")
        return
    name = " ".join(context.args)
    tracks = load_playlist(name)
    if tracks is None:
        await update.message.reply_text(f"No playlist named *{name}*.", parse_mode="Markdown")
        return
    queue.clear()
    first, *rest = tracks
    queue.set_current(first)
    for t in rest:
        queue.add_to_queue(t)
    await ensure_mpv_running(player)
    await player.set_loop_file(False)
    await player.play(first["url"])
    await update.message.reply_text(
        f"▶ Loaded *{name}* — {len(tracks)} tracks\nNow playing: {_fmt(first)}",
        parse_mode="Markdown",
    )


async def cmd_playlists(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    playlists = list_playlists()
    if not playlists:
        await update.message.reply_text("No saved playlists yet.\nUse `/save <name>` to create one.", parse_mode="Markdown")
        return

    lines = ["📚 *Saved Playlists*\n"]
    keyboards = []
    for pl in playlists:
        lines.append(f"• *{pl['name']}* — {pl['track_count']} tracks")
        keyboards.append([
            InlineKeyboardButton(f"▶ {pl['name']}", callback_data=f"pl_load:{pl['name']}"),
        ])

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboards),
        parse_mode="Markdown",
    )


async def cmd_delplaylist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: `/delplaylist <name>`", parse_mode="Markdown")
        return
    name = " ".join(context.args)
    if delete_playlist(name):
        await update.message.reply_text(f"🗑 Deleted playlist *{name}*.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"No playlist named *{name}*.", parse_mode="Markdown")


async def cmd_rename(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: `/rename <old name> <new name>`", parse_mode="Markdown")
        return
    # Support multi-word names split by ">" — e.g. /rename old name > new name
    raw = " ".join(context.args)
    if ">" in raw:
        old, new = [s.strip() for s in raw.split(">", 1)]
    else:
        parts = context.args
        mid = len(parts) // 2
        old, new = " ".join(parts[:mid]), " ".join(parts[mid:])
    if rename_playlist(old, new):
        await update.message.reply_text(f"✏️ Renamed *{old}* → *{new}*", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"Could not rename — check the name exists and the new name isn't taken.", parse_mode="Markdown")


# ── App entry ────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))

    # Playback
    app.add_handler(CommandHandler("playing", cmd_playing))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("skip", cmd_skip))
    app.add_handler(CommandHandler("prev", cmd_prev))
    app.add_handler(CommandHandler("seek", cmd_seek))
    app.add_handler(CommandHandler("vol", cmd_vol))
    app.add_handler(CommandHandler("loop", cmd_loop))
    app.add_handler(CommandHandler("loopq", cmd_loopq))
    app.add_handler(CommandHandler("shuffle", cmd_shuffle))

    # Queue
    app.add_handler(CommandHandler("queue", cmd_queue))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("clear", cmd_clear))

    # Playlists
    app.add_handler(CommandHandler("save", cmd_save))
    app.add_handler(CommandHandler("load", cmd_load))
    app.add_handler(CommandHandler("playlists", cmd_playlists))
    app.add_handler(CommandHandler("delplaylist", cmd_delplaylist))
    app.add_handler(CommandHandler("rename", cmd_rename))

    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search))

    print("Bot running. Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
