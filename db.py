"""SQLite schema and the ingest audit log."""
import sqlite3

import config


def init_db():
    with sqlite3.connect(config.DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_date TEXT,
                user_id INTEGER,
                user_name TEXT,
                game TEXT,
                puzzle_id TEXT,
                solved INTEGER,
                rank_score REAL,
                display_score TEXT,
                extra_url TEXT,
                ingest_id INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(board_date, user_id, game, puzzle_id)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS daily_boards (
                board_date TEXT PRIMARY KEY,
                channel_id INTEGER,
                message_id INTEGER
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS channel_settings (
                channel_id INTEGER PRIMARY KEY,
                layout TEXT NOT NULL DEFAULT 'grid'
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS ingest_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_date TEXT,
                user_id INTEGER,
                user_name TEXT,
                raw_text TEXT,
                parsed_summary TEXT,
                status TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        # Migration for existing deployments: scores.ingest_id links a stored
        # result to the ingest_log row that created it (powers /undo).
        cols = {r[1] for r in c.execute("PRAGMA table_info(scores)").fetchall()}
        if "ingest_id" not in cols:
            c.execute("ALTER TABLE scores ADD COLUMN ingest_id INTEGER")
            conn.commit()


def log_ingest(board_date: str, user_id: int, user_name: str, raw_text: str,
               parsed_summary: str, status: str) -> int:
    """Record an ingested message; returns the ingest_log row id."""
    with sqlite3.connect(config.DB_PATH) as conn:
        cur = conn.execute(
            "INSERT INTO ingest_log (board_date, user_id, user_name, raw_text, parsed_summary, status) VALUES (?, ?, ?, ?, ?, ?)",
            (board_date, user_id, user_name, raw_text, parsed_summary, status)
        )
        conn.commit()
        ingest_id = cur.lastrowid or 0  # INSERT always assigns lastrowid
    if config.DEBUG_LOG:
        print(f"[ingest:{status}] {user_name}: {parsed_summary or raw_text[:200]}")
    return ingest_id


def undo_latest_ingest(board_date: str, user_id: int):
    """Delete the scores created by the user's newest 'ok' ingest of the day and
    mark that ingest undone. Returns (parsed_summary, rows_deleted) or None."""
    with sqlite3.connect(config.DB_PATH) as conn:
        c = conn.cursor()
        row = c.execute(
            "SELECT id, parsed_summary FROM ingest_log"
            " WHERE board_date = ? AND user_id = ? AND status = 'ok'"
            " ORDER BY id DESC LIMIT 1",
            (board_date, user_id)
        ).fetchone()
        if not row:
            return None
        ingest_id, summary = row
        deleted = c.execute("DELETE FROM scores WHERE ingest_id = ?", (ingest_id,)).rowcount
        c.execute("UPDATE ingest_log SET status = 'undone' WHERE id = ?", (ingest_id,))
        conn.commit()
        return summary, deleted
