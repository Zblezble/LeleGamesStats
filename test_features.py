# -*- coding: utf-8 -*-
"""Focused regressions: weekly daily-podium summation and safe forfeits.

Run: python -X utf8 test_features.py   (exits 1 on failure)
Every test uses a temporary SQLite file and explicit rows. Dates are far from
today so the suite never touches scores.db or depends on the wall clock.
"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

import config
import db
import embeds


def fresh_db():
    """Point config at a throwaway database; return the previous path for cleanup."""
    fd, path = tempfile.mkstemp(prefix="features_test_", suffix=".db")
    os.close(fd)
    old_path = config.DB_PATH
    config.DB_PATH = path
    db.init_db()
    return old_path, path


def cleanup(old_path, path):
    config.DB_PATH = old_path
    try:
        os.remove(path)
    except OSError:
        pass


def add_score(board_date, user_id, user_name, game, puzzle_id,
              solved, rank_score, display_score):
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.execute(
            "INSERT INTO scores (board_date, user_id, user_name, game, puzzle_id,"
            " solved, rank_score, display_score) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (board_date, user_id, user_name, game, puzzle_id,
             solved, rank_score, display_score),
        )
        conn.commit()


def test_forfeit_requires_an_existing_entry():
    old_path, path = fresh_db()
    try:
        # Nobody has played this game today: no placeholder group may be created.
        assert db.forfeit_entry("2025-02-03", 1, "Alice", "Wordle") is None
        with sqlite3.connect(config.DB_PATH) as conn:
            assert conn.execute("SELECT count(*) FROM scores").fetchone()[0] == 0

        add_score("2025-02-03", 2, "Bob", "Wordle", "#77", 1, 1.0, "3/6")
        assert db.forfeit_entry("2025-02-03", 1, "Alice", "Wordle") == ("#77", False)

        # Re-forfeiting upserts the same row instead of duplicating it.
        assert db.forfeit_entry("2025-02-03", 1, "Alice", "Wordle") == ("#77", True)
        with sqlite3.connect(config.DB_PATH) as conn:
            rows = conn.execute(
                "SELECT user_id, game, puzzle_id, solved, rank_score, display_score"
                " FROM scores WHERE board_date = ? ORDER BY user_id",
                ("2025-02-03",),
            ).fetchall()
        assert rows == [
            (1, "Wordle", "#77", 0, 999.0, "DNF"),
            (2, "Wordle", "#77", 1, 1.0, "3/6"),
        ], rows

        # Submode rows keep their full game name and inferred puzzle id.
        add_score("2025-02-04", 3, "Cara", "Trivmount (Hard)", "#90", 1, 1.0, "5/5")
        assert db.forfeit_entry("2025-02-04", 1, "Alice", "Trivmount") == ("#90", False)
        with sqlite3.connect(config.DB_PATH) as conn:
            row = conn.execute(
                "SELECT game, puzzle_id, solved, rank_score, display_score"
                " FROM scores WHERE board_date = ? AND user_id = ?",
                ("2025-02-04", 1),
            ).fetchone()
        assert row == ("Trivmount (Hard)", "#90", 0, 10000.0, "DNF"), row
    finally:
        cleanup(old_path, path)


def test_weekly_sums_daily_podiums_without_phantom_competition():
    old_path, path = fresh_db()
    old_today = config.today_str
    old_prison = config.PRISON_ENABLED
    config.today_str = lambda: "2025-01-12"  # fixed, clearly not the real today
    config.PRISON_ENABLED = False
    try:
        # One author, same game/puzzle id on two days: each day is solo, so no points.
        add_score("2025-01-06", 1, "Alice", "Wordle", "#1", 1, 1.0, "2/6")
        add_score("2025-01-07", 1, "Alice", "Wordle", "#1", 1, 1.0, "2/6")
        points, _names = embeds.compute_daily_points("2025-01-06")
        assert points == {}, points
        embed = embeds.build_weekly_embed(days=7)
        assert embed is not None
        weekly = next(f.value for f in embed.fields if f.name == "Weekly points")
        assert weekly is not None
        assert "Alice" not in weekly and "No podium points" in weekly, weekly

        # A real second player on one day earns that day's podium only (3 + 2).
        add_score("2025-01-06", 2, "Bob", "Wordle", "#1", 1, 2.0, "3/6")
        assert embeds.compute_daily_points("2025-01-06") == ({1: 3, 2: 2}, {1: "Alice", 2: "Bob"})
        assert embeds.compute_daily_points("2025-01-07") == ({}, {1: "Alice"})
        embed = embeds.build_weekly_embed(days=7)
        assert embed is not None
        weekly = next(f.value for f in embed.fields if f.name == "Weekly points")
        assert weekly == "Alice `3.0` · Bob `2.0`", weekly
    finally:
        config.today_str = old_today
        config.PRISON_ENABLED = old_prison
        cleanup(old_path, path)


if __name__ == "__main__":
    test_forfeit_requires_an_existing_entry()
    test_weekly_sums_daily_podiums_without_phantom_competition()
    print("All feature tests passed.")
