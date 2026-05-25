"""
Unified entry point — runs all three interfaces simultaneously:
  1. Telegram bot (long polling)
  2. FastAPI web server (web UI + WhatsApp webhook)
"""
import asyncio
import uvicorn
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes,
)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup

from config import TELEGRAM_TOKEN, TELEGRAM_ENABLED, WEB_HOST, WEB_PORT
from core.handlers import (
    dispatch, action_play, action_next, action_queue,
    cmd_load, BotResponse,
)


# ── Telegram adapter ──────────────────────────────────────────────────────

def _tg_keyboard(results: list) -> InlineKeyboardMarkup:
    rows = []
    for r in results:
        rows.append([
            InlineKeyboardButton("▶ Play", callback_data=f"play:{r.tid}"),
            InlineKeyboardButton("⏭ Next", callback_data=f"next:{r.tid}"),
            InlineKeyboardButton("➕ Queue", callback_data=f"queue:{r.tid}"),
        ])
    return InlineKeyboardMarkup(rows)


def _tg_pl_keyboard(playlists: list) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"▶ {pl['name']}", callback_data=f"pl_load:{pl['name']}")] for pl in playlists]
    return InlineKeyboardMarkup(rows)


def _format_results_tg(response: BotResponse) -> str:
    lines = []
    for i, r in enumerate(response.results, 1):
        lines.append(f"*{i}.* `{r.title}`\n    {r.channel} · {r.duration}")
    return "\n\n".join(lines)


async def tg_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    wait = await update.message.reply_text("🔍 ..." if not text.startswith("/") else "⏳")
    response = await dispatch(text)

    if response.kind == "results":
        await wait.edit_text(
            _format_results_tg(response),
            reply_markup=_tg_keyboard(response.results),
            parse_mode="Markdown",
        )
    elif response.kind == "playlists":
        pl_lines = [f"• *{pl['name']}* — {pl['track_count']} tracks" for pl in response.playlists]
        await wait.edit_text(
            "📚 *Saved Playlists*\n\n" + "\n".join(pl_lines),
            reply_markup=_tg_pl_keyboard(response.playlists),
            parse_mode="Markdown",
        )
    else:
        await wait.edit_text(response.text, parse_mode="Markdown")


async def tg_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cb = update.callback_query
    await cb.answer()
    data = cb.data

    if data.startswith("pl_load:"):
        name = data.split(":", 1)[1]
        resp = await cmd_load([name])
        await cb.answer(resp.text[:200], show_alert=True)
        return

    action, tid = data.split(":", 1)
    fn = {"play": action_play, "next": action_next, "queue": action_queue}.get(action)
    if fn:
        resp = await fn(tid)
        await cb.answer(resp.text[:200])


def build_telegram_app() -> Application:
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT, tg_message))
    app.add_handler(CallbackQueryHandler(tg_callback))
    return app


# ── Combined runner ───────────────────────────────────────────────────────

async def run_all() -> None:
    from web.app import app as fastapi_app

    # Uvicorn config
    uv_config = uvicorn.Config(
        fastapi_app,
        host=WEB_HOST,
        port=WEB_PORT,
        log_level="warning",
    )
    uv_server = uvicorn.Server(uv_config)

    tg_app = None
    if TELEGRAM_ENABLED:
        tg_app = build_telegram_app()
        await tg_app.initialize()
        await tg_app.start()
        await tg_app.updater.start_polling(drop_pending_updates=True)
        print("✅ Telegram bot running")
    else:
        print("⚠️  Telegram token not set — running without Telegram")

    print(f"✅ Web UI at http://localhost:{WEB_PORT}")
    print(f"✅ WhatsApp webhook at http://localhost:{WEB_PORT}/whatsapp/webhook")
    print(f"   (expose with: ngrok http {WEB_PORT})")

    try:
        await uv_server.serve()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        print("\nShutting down...")
        # Kill mpv and remove stale socket
        import subprocess, os
        subprocess.run(["pkill", "mpv"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            os.remove("/tmp/mpv-socket")
        except FileNotFoundError:
            pass
        if tg_app:
            await tg_app.updater.stop()
            await tg_app.stop()
            await tg_app.shutdown()
        print("Bye.")


if __name__ == "__main__":
    try:
        asyncio.run(run_all())
    except KeyboardInterrupt:
        pass
