"""
DuckDuckGo web search fallback for non-music queries (news, podcasts, info).
No API key required — uses the free DDG instant answer + HTML search.
"""
import asyncio
from functools import partial
from duckduckgo_search import DDGS


def _search_sync(query: str, max_results: int = 5) -> list[dict]:
    try:
        with DDGS() as ddg:
            results = list(ddg.text(query, max_results=max_results))
        return results  # each: {title, href, body}
    except Exception as e:
        print(f"[websearch] DDG error: {e}")
        return []


async def web_search(query: str, max_results: int = 5) -> list[dict]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_search_sync, query, max_results))


def format_results(results: list[dict]) -> str:
    if not results:
        return "No results found."
    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        body = r.get("body", "")[:120].rstrip()
        href = r.get("href", "")
        lines.append(f"{i}. *{title}*\n   {body}…\n   {href}")
    return "\n\n".join(lines)
