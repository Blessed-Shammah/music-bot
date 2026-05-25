import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "playlists.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS playlists (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                name    TEXT UNIQUE NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS playlist_tracks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
                position    INTEGER NOT NULL,
                title       TEXT NOT NULL,
                url         TEXT NOT NULL,
                duration    TEXT,
                channel     TEXT
            );
        """)


def save_playlist(name: str, tracks: list[dict]) -> bool:
    """Create or overwrite a named playlist. Returns True on success."""
    if not tracks:
        return False
    with _connect() as conn:
        conn.execute("DELETE FROM playlists WHERE name = ?", (name,))
        cur = conn.execute("INSERT INTO playlists (name) VALUES (?)", (name,))
        pid = cur.lastrowid
        conn.executemany(
            "INSERT INTO playlist_tracks (playlist_id, position, title, url, duration, channel) VALUES (?,?,?,?,?,?)",
            [(pid, i, t["title"], t["url"], t.get("duration", ""), t.get("channel", "")) for i, t in enumerate(tracks)],
        )
    return True


def load_playlist(name: str) -> Optional[list[dict]]:
    """Return tracks for a playlist, or None if not found."""
    with _connect() as conn:
        row = conn.execute("SELECT id FROM playlists WHERE name = ?", (name,)).fetchone()
        if not row:
            return None
        rows = conn.execute(
            "SELECT title, url, duration, channel FROM playlist_tracks WHERE playlist_id = ? ORDER BY position",
            (row["id"],),
        ).fetchall()
        return [dict(r) for r in rows]


def list_playlists() -> list[dict]:
    """Return all playlists with name, track count, created_at."""
    with _connect() as conn:
        rows = conn.execute("""
            SELECT p.name, COUNT(t.id) as track_count, p.created_at
            FROM playlists p
            LEFT JOIN playlist_tracks t ON t.playlist_id = p.id
            GROUP BY p.id
            ORDER BY p.name
        """).fetchall()
        return [dict(r) for r in rows]


def delete_playlist(name: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM playlists WHERE name = ?", (name,))
        return cur.rowcount > 0


def rename_playlist(old: str, new: str) -> bool:
    try:
        with _connect() as conn:
            cur = conn.execute("UPDATE playlists SET name = ? WHERE name = ?", (new, old))
            return cur.rowcount > 0
    except sqlite3.IntegrityError:
        return False
