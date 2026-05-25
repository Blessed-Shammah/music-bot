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
            reader, writer = await asyncio.wait_for(
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
            ["mpv", "--no-video", "--idle=yes", f"--input-ipc-server={self.socket_path}"],
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

    async def play(self, url: str) -> bool:
        result = await self._send(["loadfile", url, "replace"])
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
