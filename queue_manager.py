import random
from collections import deque
from typing import Optional


class QueueManager:
    def __init__(self):
        self._queue: deque[dict] = deque()
        self._current: Optional[dict] = None
        self._history: list[dict] = []       # last 20 for prev button
        self._session: list[dict] = []        # ALL played this session
        self.loop_one: bool = False
        self.loop_queue: bool = False

    # ── Queue manipulation ───────────────────────────────────────────────

    def add_to_queue(self, track: dict) -> int:
        self._queue.append(track)
        return len(self._queue)

    def play_next(self, track: dict) -> None:
        self._queue.appendleft(track)

    def get_queue(self) -> list[dict]:
        return list(self._queue)

    def pop_next(self) -> Optional[dict]:
        if self._queue:
            return self._queue.popleft()
        # If loop_queue is on, re-enqueue history and pop first
        if self.loop_queue and self._history:
            for t in self._history:
                self._queue.append(t)
            self._history.clear()
            return self._queue.popleft()
        return None

    def clear(self) -> None:
        self._queue.clear()
        self._history.clear()

    def shuffle(self) -> None:
        items = list(self._queue)
        random.shuffle(items)
        self._queue = deque(items)

    def remove_at(self, index: int) -> Optional[dict]:
        items = list(self._queue)
        if 0 <= index < len(items):
            removed = items.pop(index)
            self._queue = deque(items)
            return removed
        return None

    def move(self, from_idx: int, to_idx: int) -> bool:
        items = list(self._queue)
        if not (0 <= from_idx < len(items) and 0 <= to_idx < len(items)):
            return False
        track = items.pop(from_idx)
        items.insert(to_idx, track)
        self._queue = deque(items)
        return True

    # ── Current track ────────────────────────────────────────────────────

    def current(self) -> Optional[dict]:
        return self._current

    def set_current(self, track: dict) -> None:
        if self._current:
            self._history.append(self._current)
            if len(self._history) > 20:
                self._history.pop(0)
        self._current = track
        # Track full session history (deduplicated by url)
        if not any(t["url"] == track["url"] for t in self._session):
            self._session.append(track)

    def get_session_history(self) -> list[dict]:
        """All unique tracks played this session, oldest first."""
        result = list(self._session)
        if self._current and not any(t["url"] == self._current["url"] for t in result):
            result.append(self._current)
        return result

    def previous(self) -> Optional[dict]:
        if self._history:
            return self._history.pop()
        return None

    # ── Loop modes ───────────────────────────────────────────────────────

    def toggle_loop_one(self) -> bool:
        self.loop_one = not self.loop_one
        if self.loop_one:
            self.loop_queue = False
        return self.loop_one

    def toggle_loop_queue(self) -> bool:
        self.loop_queue = not self.loop_queue
        if self.loop_queue:
            self.loop_one = False
        return self.loop_queue

    def status(self) -> str:
        if self.loop_one:
            return "🔂 Loop one"
        if self.loop_queue:
            return "🔁 Loop queue"
        return "➡️ No loop"
