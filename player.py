import asyncio
import json
import os
import shutil
import subprocess
from typing import Optional

from config import MPV_SOCKET


class MpvController:
    def __init__(self, socket_path: str = MPV_SOCKET):
        self.socket_path = socket_path

    async def _can_connect(self) -> bool:
        """Check if the socket file exists AND mpv actually responds."""
        if not os.path.exists(self.socket_path):
            return False
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self.socket_path), timeout=1.0
            )
            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            return False

    async def is_running(self) -> bool:
        return await self._can_connect()

    async def start_mpv(self) -> None:
        if not shutil.which("mpv"):
            raise RuntimeError("mpv is not installed. Run: sudo apt install mpv")

        # Remove stale socket file left by a dead previous process
        if os.path.exists(self.socket_path):
            try:
                os.remove(self.socket_path)
            except OSError:
                pass

        subprocess.Popen(
            [
                "mpv", "--vid=no", "--idle=yes",
                f"--input-ipc-server={self.socket_path}",
                "--ytdl=yes",
                "--ytdl-raw-options=no-playlist=,cookies-from-browser=firefox",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Poll until socket appears and accepts connections (up to 5s)
        for _ in range(50):
            await asyncio.sleep(0.1)
            if await self._can_connect():
                print("[mpv] started and socket ready")
                return

        raise RuntimeError("mpv started but socket never became ready. Check mpv installation.")

    async def _send(self, command: list) -> Optional[dict]:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self.socket_path), timeout=2.0
            )
            payload = json.dumps({"command": command}) + "\n"
            writer.write(payload.encode())
            await writer.drain()
            data = await asyncio.wait_for(reader.readline(), timeout=3.0)
            writer.close()
            await writer.wait_closed()
            return json.loads(data)
        except Exception as e:
            print(f"[mpv] _send error: {e}")
            return None

    async def _ramp(self, from_vol: float, to_vol: float, duration_ms: int, steps: int = 30) -> None:
        """S-curve volume ramp — feels musical, not mechanical."""
        import math
        step_ms = duration_ms / steps
        for i in range(steps):
            t = (i + 1) / steps
            # Sinusoidal S-curve: slow start, fast middle, slow end
            curve = (1 - math.cos(math.pi * t)) / 2
            vol = from_vol + (to_vol - from_vol) * curve
            await self._send(["set_property", "volume", max(0.0, vol)])
            await asyncio.sleep(step_ms / 1000)

    async def play(self, url: str, video: bool = False, transition_ms: int = 1800) -> bool:
        vol_result = await self._send(["get_property", "volume"])
        target_vol = vol_result.get("data", 100) if vol_result and vol_result.get("error") == "success" else 100

        is_playing_result = await self._send(["get_property", "idle-active"])
        is_idle = is_playing_result and is_playing_result.get("data") is True

        if not is_idle:
            # Fade out to ~35% — new track punches in while still warm (DJ feel)
            await self._ramp(target_vol, target_vol * 0.35, transition_ms // 2)

        await self._send(["set_property", "vid", "auto" if video else "no"])
        if video:
            await self._send(["set_property", "fullscreen", True])
        await self._send(["set_property", "volume", 0])
        result = await self._send(["loadfile", url, "replace"])
        if result is None:
            return False

        # Wait for new track to start buffering
        for _ in range(40):
            await asyncio.sleep(0.1)
            check = await self._send(["get_property", "idle-active"])
            if check and check.get("data") is False:
                break

        # Fade in from 0 → full volume
        await self._ramp(0, target_vol, transition_ms)
        return True

    async def exit_fullscreen(self) -> bool:
        result = await self._send(["set_property", "fullscreen", False])
        return result is not None

    async def queue_append(self, url: str) -> bool:
        result = await self._send(["loadfile", url, "append"])
        return result is not None

    async def pause_toggle(self) -> bool:
        result = await self._send(["cycle", "pause"])
        return result is not None

    async def stop(self) -> bool:
        result = await self._send(["stop"])
        return result is not None

    async def get_current_title(self) -> Optional[str]:
        result = await self._send(["get_property", "media-title"])
        if result and result.get("error") == "success":
            return result.get("data")
        return None

    async def set_loop_file(self, enabled: bool) -> bool:
        result = await self._send(["set_property", "loop-file", "inf" if enabled else "no"])
        return result is not None

    async def set_loop_playlist(self, enabled: bool) -> bool:
        result = await self._send(["set_property", "loop-playlist", "inf" if enabled else "no"])
        return result is not None

    async def get_volume(self) -> Optional[int]:
        result = await self._send(["get_property", "volume"])
        if result and result.get("error") == "success":
            return int(result.get("data", 100))
        return None

    async def set_volume(self, level: int) -> bool:
        level = max(0, min(150, level))
        result = await self._send(["set_property", "volume", level])
        return result is not None

    async def seek(self, seconds: int) -> bool:
        result = await self._send(["seek", seconds, "relative"])
        return result is not None

    async def get_time_pos(self) -> Optional[float]:
        result = await self._send(["get_property", "time-pos"])
        if result and result.get("error") == "success":
            return result.get("data")
        return None

    async def get_duration(self) -> Optional[float]:
        result = await self._send(["get_property", "duration"])
        if result and result.get("error") == "success":
            return result.get("data")
        return None


async def ensure_mpv_running(controller: MpvController) -> None:
    if not await controller.is_running():
        await controller.start_mpv()
