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


def log_ingest(board_date: str, user_id: int, user_name: str, raw_text: str,
               parsed_summary: str, status: str):
    """Record every ingested message (ok or broken) — audit trail and future /undo source."""
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.execute(
            "INSERT INTO ingest_log (board_date, user_id, user_name, raw_text, parsed_summary, status) VALUES (?, ?, ?, ?, ?, ?)",
            (board_date, user_id, user_name, raw_text, parsed_summary, status)
        )
        conn.commit()
    if config.DEBUG_LOG:
        print(f"[ingest:{status}] {user_name}: {parsed_summary or raw_text[:200]}")
