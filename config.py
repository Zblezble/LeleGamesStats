"""Environment configuration and date helpers.

Set these as environment variables before running:
  DISCORD_BOT_TOKEN - your Discord bot token (required)
  SCORE_CHANNEL_ID  - the channel to watch (optional; if unset, watches all channels)
  BOT_TZ            - timezone for daily board cutoff, e.g. "Europe/Warsaw"
                      (optional; defaults to the server's local time)
  DISABLED_GAMES    - comma-separated game names to ignore, e.g. "Wordle"
                      (optional; everything is enabled by default)
  DEBUG_LOG         - set to 1 to dump every ingested message to the console
                      (or run `python main.py --debug`)
"""
import os
import sys
from datetime import datetime

BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
SCORE_CHANNEL_ID = int(os.getenv("SCORE_CHANNEL_ID", "0")) or None
DB_PATH = "scores.db"

DISABLED_GAMES = {g.strip().lower() for g in os.getenv("DISABLED_GAMES", "").split(",") if g.strip()}

try:
    from zoneinfo import ZoneInfo
    BOT_TZ = ZoneInfo(os.environ["BOT_TZ"]) if os.getenv("BOT_TZ") else None
except Exception:
    BOT_TZ = None  # unknown/missing tz database: fall back to server-local time

# Console dump of every ingested message: `python main.py --debug` (or DEBUG_LOG=1).
DEBUG_LOG = "--debug" in sys.argv or bool(os.getenv("DEBUG_LOG"))


def today_str() -> str:
    now = datetime.now(BOT_TZ) if BOT_TZ else datetime.now()
    return now.strftime("%Y-%m-%d")


def date_label(board_date: str) -> str:
    """'2026-11-03' -> 'Tue 3 Nov' (falls back to the raw string on parse failure)."""
    try:
        dt = datetime.strptime(board_date, "%Y-%m-%d")
        return f"{dt.strftime('%a')} {dt.day} {dt.strftime('%b')}"
    except ValueError:
        return board_date
