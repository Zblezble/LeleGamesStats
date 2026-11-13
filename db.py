"""SQLite schema and the ingest audit log."""
import csv
import io
import sqlite3
from datetime import datetime, timedelta

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
        c.execute("""
            CREATE TABLE IF NOT EXISTS day_wraps (
                board_date TEXT PRIMARY KEY,
                message_id INTEGER
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS prisoners (
                board_date TEXT,
                user_id INTEGER,
                user_name TEXT,
                prison_reason TEXT,
                UNIQUE(board_date, user_id)
            )
        """)
        conn.commit()

        # Migration for existing deployments: scores.ingest_id links a stored
        # result to the ingest_log row that created it (powers /undo).
        cols = {r[1] for r in c.execute("PRAGMA table_info(scores)").fetchall()}
        if "ingest_id" not in cols:
            c.execute("ALTER TABLE scores ADD COLUMN ingest_id INTEGER")
            conn.commit()


def wrap_already_posted(board_date: str) -> bool:
    with sqlite3.connect(config.DB_PATH) as conn:
        return conn.execute("SELECT 1 FROM day_wraps WHERE board_date = ?", (board_date,)).fetchone() is not None


def mark_wrap_posted(board_date: str, message_id: int):
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.execute("INSERT OR REPLACE INTO day_wraps (board_date, message_id) VALUES (?, ?)",
                     (board_date, message_id))
        conn.commit()


def day_has_scores(board_date: str) -> bool:
    with sqlite3.connect(config.DB_PATH) as conn:
        return conn.execute("SELECT 1 FROM scores WHERE board_date = ? LIMIT 1", (board_date,)).fetchone() is not None


def prison_count(user_id: int) -> int:
    """Return how many different days the user has been jailed, across all dates."""
    with sqlite3.connect(config.DB_PATH) as conn:
        return conn.execute("SELECT count(*) FROM prisoners WHERE user_id = ?", (user_id,)).fetchone()[0]


def prison_breakdown(start_date: str, end_date: str):
    """Return (user_name, user_id, prison_days) for a date range, newest name last.

    One row is charged per calendar day; unique-sentencing already enforces at most
    one jail day per person per date. Sorted by descending days, then name.
    """
    with sqlite3.connect(config.DB_PATH) as conn:
        return conn.execute(
            "SELECT user_name, user_id, count(*) as prison_days FROM prisoners"
            " WHERE board_date BETWEEN ? AND ?"
            " GROUP BY user_id, user_name"
            " ORDER BY prison_days DESC, user_name ASC",
            (start_date, end_date)
        ).fetchall()


def add_prisoner(board_date: str, user_id: int, user_name: str, game: str) -> bool:
    """Jail this player for the day. Returns True only for the first jail sentence today."""
    with sqlite3.connect(config.DB_PATH) as conn:
        c = conn.execute(
            "INSERT OR IGNORE INTO prisoners (board_date, user_id, user_name, prison_reason) VALUES (?, ?, ?, ?)",
            (board_date, user_id, user_name, f"First-attempt win on {game}")
        )
        conn.commit()
        return c.rowcount > 0


def jailed_users(board_date: str) -> dict[int, str]:
    """Map of user ids permanently jailed for this day to display names."""
    with sqlite3.connect(config.DB_PATH) as conn:
        return dict(conn.execute("SELECT user_id, user_name FROM prisoners WHERE board_date = ?", (board_date,)).fetchall())


def is_jailed(board_date: str, user_id: int) -> bool:
    with sqlite3.connect(config.DB_PATH) as conn:
        return conn.execute("SELECT 1 FROM prisoners WHERE board_date = ? AND user_id = ?", (board_date, user_id)).fetchone() is not None


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


def remove_entries(board_date: str, game: str, puzzle_id: str, user_id: int | None = None):
    """Remove score entries matching (date, game, puzzle_id[, user]) — admin cleanup.
    Game matches by name or by submode prefix; puzzle_id accepts '142' or '#142'.
    Returns dict(count, game, puzzle_id, users) if anything was deleted, else None."""
    with sqlite3.connect(config.DB_PATH) as conn:
        c = conn.cursor()
        pid_variants = [puzzle_id] if puzzle_id.startswith("#") else [puzzle_id, f"#{puzzle_id}"]
        rows = c.execute(
            "SELECT DISTINCT game, puzzle_id, user_id, user_name FROM scores"
            " WHERE board_date = ?"
            " AND (game = ? COLLATE NOCASE OR game LIKE (? || ' (%') COLLATE NOCASE)"
            f" AND puzzle_id IN ({','.join('?' * len(pid_variants))})"
            + (" AND user_id = ?" if user_id else ""),
            (board_date, game, game, *pid_variants, *((user_id,) if user_id else ()))
        ).fetchall()
        if not rows:
            return None
        for g_row, pid_row, uid, _ in rows:
            c.execute(
                "DELETE FROM scores WHERE board_date = ? AND game = ? AND puzzle_id = ? AND user_id = ?",
                (board_date, g_row, pid_row, uid)
            )
        conn.commit()
        users = sorted({uname for _, _, _, uname in rows})
        games_found = sorted({g for g, _, _, _ in rows})
        pids_found = sorted({p for _, p, _, _ in rows})
        return {"count": len(rows), "games": games_found, "puzzle_ids": pids_found, "users": users}


def forfeit_entry(board_date: str, user_id: int, user_name: str, game_key: str):
    """Record a manual forfeit (DNF) for games with no built-in 'give up' share text.
    Puzzle id follows whatever other players posted today for this game, else the date.
    Returns (puzzle_id, overwritten_entry) after upserting."""
    with sqlite3.connect(config.DB_PATH) as conn:
        c = conn.cursor()
        row = c.execute(
            "SELECT puzzle_id, game FROM scores WHERE board_date = ?"
            " AND (game = ? COLLATE NOCASE OR game LIKE (? || ' (%') COLLATE NOCASE)"
            " ORDER BY timestamp DESC LIMIT 1",
            (board_date, game_key, game_key)
        ).fetchone()
        puzzle_id = row[0] if row else board_date
        game = row[1] if row else game_key
        overwritten = c.execute(
            "SELECT 1 FROM scores WHERE board_date = ? AND game = ? AND puzzle_id = ? AND user_id = ?",
            (board_date, game, puzzle_id, user_id)
        ).fetchone() is not None
        rank = 10000.0 if game_key == "Trivmount" else 999.0
        c.execute("""
            INSERT INTO scores (board_date, user_id, user_name, game, puzzle_id, solved, rank_score, display_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(board_date, user_id, game, puzzle_id) DO UPDATE SET
                solved=0, rank_score=excluded.rank_score, display_score=excluded.display_score
        """, (board_date, user_id, user_name, game, puzzle_id, 0, rank, "DNF"))
        conn.commit()
        return puzzle_id, bool(overwritten)


def export_scores_csv(days: int = 7) -> tuple[str, str, str]:
    """Export the last ``days`` days of current scores as CSV text.

    Returns ``(csv_text, start_date, end_date)`` where both dates are inclusive
    ISO ``YYYY-MM-DD`` strings. ``end_date`` is UTC today from
    ``config.today_str()``; ``days`` defaults to 7 and is clamped to 1..31.
    Cells beginning with a spreadsheet formula trigger (``=``, ``+``, ``-``,
    ``@``, tab, or CR) are prefixed with a single quote to keep exports inert.
    """
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 7
    days = max(1, min(days, 31))

    end_date = config.today_str()
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    start_date = (end_dt - timedelta(days=days - 1)).strftime("%Y-%m-%d")

    columns = [
        "board_date", "game", "puzzle_id", "user_id", "user_name", "solved",
        "rank_score", "display_score", "extra_url", "timestamp", "ingest_id",
    ]

    def formula_safe(value):
        text = "" if value is None else str(value)
        return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text

    with sqlite3.connect(config.DB_PATH) as conn:
        rows = conn.execute(
            "SELECT board_date, game, puzzle_id, user_id, user_name, solved,"
            " rank_score, display_score, extra_url, timestamp, ingest_id"
            " FROM scores WHERE board_date BETWEEN ? AND ?"
            " ORDER BY board_date ASC, game ASC, user_id ASC, puzzle_id ASC",
            (start_date, end_date),
        ).fetchall()

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows([formula_safe(value) for value in row] for row in rows)
    return out.getvalue(), start_date, end_date


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
