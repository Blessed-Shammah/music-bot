import asyncio
from functools import partial
import yt_dlp


def _search_sync(query: str, max_results: int) -> list[dict]:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",  # flat only for playlist entries, full info for search
        "skip_download": True,
        "default_search": f"ytsearch{max_results}",
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(query, download=False)
            entries = info.get("entries", []) if info else []
            results = []
            for entry in entries:
                if not entry:
                    continue
                vid_id = entry.get("id", "")
                # Always build a reliable full URL from the video ID
                url = (
                    entry.get("webpage_url")
                    or (f"https://www.youtube.com/watch?v={vid_id}" if vid_id else "")
                )
                if not url:
                    continue
                duration_sec = entry.get("duration") or 0
                minutes, seconds = divmod(int(duration_sec), 60)
                duration = f"{minutes}:{seconds:02d}" if duration_sec else "?"
                results.append({
                    "title": entry.get("title") or "Unknown",
                    "url": url,
                    "duration": duration,
                    "channel": entry.get("uploader") or entry.get("channel") or "Unknown",
                    "thumbnail": entry.get("thumbnail", ""),
                })
            return results
    except Exception as e:
        print(f"[search] yt-dlp error: {e}")
        return []


async def search_youtube(query: str, max_results: int = 5) -> list[dict]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_search_sync, query, max_results))


def _resolve_sync(youtube_url: str) -> str:
    """Extract the direct audio stream URL from a YouTube watch URL."""
    opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            # For formats with a direct URL
            if info.get("url"):
                return info["url"]
            # For entries with multiple formats, pick best audio
            formats = info.get("formats", [])
            audio = [f for f in formats if f.get("acodec") != "none" and f.get("vcodec") == "none"]
            if audio:
                return audio[-1]["url"]
            if formats:
                return formats[-1]["url"]
    except Exception as e:
        print(f"[resolve] yt-dlp error: {e}")
    return youtube_url  # fallback: return original, let mpv try


async def resolve_stream_url(youtube_url: str) -> str:
    """Async wrapper — resolves YouTube URL to a direct CDN audio stream."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_resolve_sync, youtube_url))
