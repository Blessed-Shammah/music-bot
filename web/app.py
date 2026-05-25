"""
FastAPI server:
1. Serve the web chat UI
2. WebSocket endpoint for chat + live playback polling
3. Twilio WhatsApp webhook
"""
import asyncio
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Form
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pathlib import Path

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.handlers import dispatch, action_play, action_next, action_queue, get_track
from adapters.whatsapp import handle_whatsapp_message

app = FastAPI(title="Music Chat")

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_connections: list[WebSocket] = []


async def broadcast(data: dict) -> None:
    dead = []
    for ws in _connections:
        try:
            await ws.send_text(json.dumps(data))
        except Exception:
            dead.append(ws)
    for ws in dead:
        _connections.remove(ws)


# ── Live playback ticker — pushes position to all clients every second ────

async def playback_ticker() -> None:
    import os
    from core.handlers import player, queue
    while True:
        await asyncio.sleep(1)
        if not _connections:
            continue
        # Skip entirely if mpv socket doesn't exist — avoids connection refused spam
        if not os.path.exists(player.socket_path):
            continue
        try:
            pos = await player.get_time_pos()
            dur = await player.get_duration()
            current = queue.current()
            if pos is not None and dur and current:
                await broadcast({
                    "type": "tick",
                    "pos": round(pos, 1),
                    "dur": round(dur, 1),
                    "title": current.get("title", ""),
                    "channel": current.get("channel", ""),
                })
        except Exception:
            pass


@app.on_event("startup")
async def startup():
    asyncio.create_task(playback_ticker())


# ── Web UI ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse((STATIC_DIR / "index.html").read_text())


# ── WebSocket chat ────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _connections.append(ws)
    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            msg_type = data.get("type")

            if msg_type == "message":
                text = data.get("text", "").strip()
                if not text:
                    continue
                response = await dispatch(text)
                await ws.send_text(json.dumps({
                    "type": response.kind,
                    "text": response.text,
                    "results": [
                        {"tid": r.tid, "title": r.title,
                         "channel": r.channel, "duration": r.duration}
                        for r in response.results
                    ] if response.results else [],
                    "playlists": response.playlists,
                }))

            elif msg_type == "action":
                action = data.get("action")
                tid = data.get("tid", "")
                fn_map = {"play": action_play, "next": action_next, "queue": action_queue}
                fn = fn_map.get(action)
                if fn:
                    resp = await fn(tid)
                    await ws.send_text(json.dumps({"type": "text", "text": resp.text}))
                    if action == "play":
                        track = get_track(tid)
                        if track:
                            await broadcast({"type": "now_playing",
                                             "title": track["title"],
                                             "channel": track.get("channel", ""),
                                             "duration": track.get("duration", "")})

            elif msg_type == "pl_load":
                name = data.get("name", "")
                from core.handlers import cmd_load
                resp = await cmd_load([name])
                await ws.send_text(json.dumps({"type": "text", "text": resp.text}))

    except WebSocketDisconnect:
        if ws in _connections:
            _connections.remove(ws)


# ── Twilio WhatsApp webhook ───────────────────────────────────────────────

@app.post("/whatsapp/webhook")
async def whatsapp_webhook(From: str = Form(...), Body: str = Form(...)):
    twiml = await handle_whatsapp_message(From, Body)
    return Response(content=twiml, media_type="application/xml")
