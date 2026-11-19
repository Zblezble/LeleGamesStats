# -*- coding: utf-8 -*-
import math
import os
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

import config
import db
import difficulty
import embeds

TODAY = "2026-11-14"


@contextmanager
def temporary_database():
    """Use a separate SQLite file, restoring path and thresholds afterward."""
    fd, path = tempfile.mkstemp(prefix="lele-difficulty-tests-", suffix=".db")
    os.close(fd)
    old_path = config.DB_PATH
    old_attempts = config.DIFFICULTY_MIN_HISTORY_ATTEMPTS
    old_puzzles = config.DIFFICULTY_MIN_HISTORY_PUZZLES
    old_today = config.today_str
    config.DB_PATH = path
    config.DIFFICULTY_MIN_HISTORY_ATTEMPTS = 3
    config.DIFFICULTY_MIN_HISTORY_PUZZLES = 2
    config.today_str = lambda: TODAY
    try:
        db.init_db()
        yield path
    finally:
        config.DB_PATH = old_path
        config.DIFFICULTY_MIN_HISTORY_ATTEMPTS = old_attempts
        config.DIFFICULTY_MIN_HISTORY_PUZZLES = old_puzzles
        config.today_str = old_today
        try:
            os.remove(path)
        except OSError:
            pass


def score(conn, date, uid, game="Wordle", puzzle="today", solved=1, rank: object = 2, display: object = "2/6"):
    """Insert the current canonical on-conflict record for this attempt."""
    conn.execute(
        "INSERT INTO scores (board_date,user_id,user_name,game,puzzle_id,solved,rank_score,display_score)"
        " VALUES (?,?,?,?,?,?,?,?) "
        "ON CONFLICT(board_date,user_id,game,puzzle_id) DO UPDATE SET "
        " solved=excluded.solved, rank_score=excluded.rank_score, "
        " display_score=excluded.display_score",
        (date, uid, f"uid-{uid}", game, puzzle, solved, rank, display),
    )
    conn.commit()


def history(conn, game="Wordle", *, rank: object = 6, display: object = "6/6", count=10):
    """Give one game a valid baseline of 30 attempts and 10 distinct puzzles."""
    for index in range(count):
        day = (datetime(2026, 10, 1) + timedelta(days=index)).strftime("%Y-%m-%d")
        for uid in (11, 12, 13):
            score(conn, day, uid, game, f"old-{index}", 1, rank, display)


def add_day(conn, date, game="Wordle", *, scores):
    """Insert a single game's results on a date, one for each player."""
    for uid, rank, display in scores:
        score(conn, date, uid, game, "current", 1, rank, display)


class DifficultyTests(unittest.TestCase):
    def test_empirical_midrank(self):
        self.assertEqual(difficulty.empirical_percentile(2, [1, 3, 8]), 200.0 / 3.0)
        self.assertEqual(difficulty.empirical_percentile(3, [3, 3, 3]), 50.0)
        self.assertIsNone(difficulty.empirical_percentile(0, []))

    def test_result_classification_and_zero(self):
        self.assertEqual(difficulty._rank("Maptap", 1, 0, "0 pts"), (0, 0.0))
        self.assertEqual(difficulty._rank("History in Order", 0, -4, "4/6"), (0, -4.0))
        self.assertEqual(difficulty._rank("Trivmount", 0, 9900, "11/12"), (0, 9900.0))
        self.assertEqual(difficulty._rank("Wordle", 0, 999, "X/6"), (1, 0.0))

    def test_invalid_attempts_are_excluded(self):
        for fields in (
            ("Wordle", 1, math.nan, "1/6"),
            ("Wordle", 1, math.inf, "1/6"),
            ("Wordle", 1, True, "1/6"),
            ("Wordle", 1, "2", "2/6"),
            ("Wordle", None, 2, "2/6"),
            ("Wordle", 1, 2, None),
            ("UnknownGame", 1, 2, "2/6"),
            ("History in Order", 0, 10000, "7/6"),
        ):
            with self.subTest(fields=fields):
                self.assertIsNone(difficulty._rank(*fields))

    def test_history_thresholds_and_date_boundaries(self):
        with temporary_database() as _:
            with sqlite3.connect(config.DB_PATH) as conn:
                original_minimum = config.DIFFICULTY_MIN_HISTORY_ATTEMPTS
                config.DIFFICULTY_MIN_HISTORY_ATTEMPTS = 7
                history(conn, count=2)
                self.assertIsNone(difficulty._history_for(TODAY, "Wordle", "headline"))
                score(conn, "2026-11-03", 99, rank=6)
                self.assertIsNotNone(difficulty._history_for(TODAY, "Wordle", "headline"))
                config.DIFFICULTY_MIN_HISTORY_ATTEMPTS = original_minimum
                # `count` isn't a number of rows from another game or variant.
                assert conn.execute("SELECT count(*) FROM scores").fetchone()[0] == 7

    def test_daily_participants_and_shrinkage(self):
        with temporary_database() as _:
            with sqlite3.connect(config.DB_PATH) as conn:
                history(conn)
                score(conn, TODAY, 1, rank=2)
                score(conn, TODAY, 2, rank=999, solved=0, display="X/6")
                expected_name = "Wordle"
                result = difficulty.analyze_day(TODAY)
                self.assertEqual(len(result), 1, result)
                self.assertEqual(result[0]["players"], 2, result)
                self.assertEqual(result[0]["percentile"], 50.0, result)
                assert conn.execute("SELECT count(*) FROM scores").fetchone()[0] == 32

    def test_solo_attempt_cannot_create_daily_contest(self):
        with temporary_database() as _:
            with sqlite3.connect(config.DB_PATH) as conn:
                history(conn)
                score(conn, TODAY, 1, rank=1)
                self.assertEqual(difficulty.analyze_day(TODAY), [])

    def test_two_puzzles_stay_independent(self):
        with temporary_database() as _:
            with sqlite3.connect(config.DB_PATH) as conn:
                history(conn)
                score(conn, TODAY, 1, puzzle="a", rank=2)
                score(conn, TODAY, 3, puzzle="a", solved=0, display="X/6")
                score(conn, TODAY, 3, puzzle="a", rank=4)
                score(conn, TODAY, 2, puzzle="b", rank=999, solved=0, display="X/6")
                score(conn, TODAY, 4, puzzle="b", rank=6)
                results = difficulty.analyze_day(TODAY)
                self.assertEqual(len(results), 2, results)
                self.assertEqual({row["puzzle_id"] for row in results}, {"a", "b"})
                self.assertTrue(all(row["players"] == 2 for row in results), results)

    def test_bad_player_cannot_pad_participant_count(self):
        with temporary_database() as _:
            with sqlite3.connect(config.DB_PATH) as conn:
                history(conn)
                score(conn, TODAY, 1, rank=2)
                score(conn, TODAY, 2, rank="NaN", display="2/6")
                self.assertEqual(difficulty.analyze_day(TODAY), [])

    def test_roughly_grid_primary_best_and_version_separation(self):
        with temporary_database() as _:
            with sqlite3.connect(config.DB_PATH) as conn:
                history(conn, game="Roughly (Where from)", rank=-65.0095,
                        display="~65% · best 95%")
                low = difficulty._rank("Roughly (Where from)", 1, -65.006, "~65% · best 60%")
                high = difficulty._rank("Roughly (Where from)", 1, -65.0095, "~65% · best 95%")
                assert low is not None and high is not None
                self.assertTrue(high < low)
                self.assertIsNotNone(difficulty._history_for(TODAY, "Roughly (Where from)", "grid"))
                self.assertIsNone(difficulty._history_for(TODAY, "Roughly (Where from)", "headline"))

    def test_variant_isolation(self):
        with temporary_database() as _:
            with sqlite3.connect(config.DB_PATH) as conn:
                history(conn, game="Chessle (Medium)", rank=2)
                self.assertIsNone(difficulty._history_for(TODAY, "Chessle (Hard)", "headline"))
                history(conn, game="Chessle (Hard)", rank=4)
                self.assertIsNotNone(difficulty._history_for(TODAY, "Chessle (Hard)", "headline"))

    def test_weekly_instance_averaging_and_cutoffs(self):
        with temporary_database() as _:
            with sqlite3.connect(config.DB_PATH) as conn:
                history(conn)
                score(conn, "2026-11-13", 1, rank=2)
                score(conn, "2026-11-13", 2, rank=999, solved=0, display="X/6")
                first = difficulty.analyze_day("2026-11-13")
                score(conn, TODAY, 1, rank=2)
                score(conn, TODAY, 2, rank=999, solved=0, display="X/6")
                self.assertEqual(difficulty.analyze_day("2026-11-13"), first)
                second = difficulty.analyze_day(TODAY)
                self.assertEqual(len(second), 1)
                self.assertIsInstance(second[0]["percentile"], float)
                # One instance cannot supply the required weekly contrast.
                self.assertEqual(difficulty.analyze_week(TODAY, days=1), [])
                weekly = difficulty.analyze_week(TODAY, days=2)
                self.assertEqual(len(weekly), 1)
                self.assertEqual(weekly[0]["instances"], 2)
                self.assertEqual(
                    weekly[0]["percentile"],
                    (first[0]["percentile"] + second[0]["percentile"]) / 2,
                )

    def test_history_reprocess_and_updates_are_deterministic(self):
        with temporary_database() as _:
            with sqlite3.connect(config.DB_PATH) as conn:
                history(conn)
                score(conn, TODAY, 1, rank=2)
                score(conn, TODAY, 2, rank=999, solved=0, display="X/6")
                baseline = difficulty.analyze_day(TODAY)
                self.assertEqual(baseline, difficulty.analyze_day(TODAY))
                conn.execute("UPDATE scores SET solved = 1, rank_score = 6, display_score = ? "
                             "WHERE board_date = ? AND user_id = ? AND game = ? AND puzzle_id = ?",
                             ("6/6", TODAY, 2, "Wordle", "today"))
                conn.commit()
                altered = difficulty.analyze_day(TODAY)
                self.assertNotEqual(altered, baseline)
                self.assertEqual(altered[0]["percentile"], 60.0, altered)

    def test_full_wrap_and_weekly_wrapper(self):
        with temporary_database() as _:
            with sqlite3.connect(config.DB_PATH) as conn:
                history(conn)
                score(conn, TODAY, 1, puzzle="puzzle-A", rank=2)
                score(conn, TODAY, 2, puzzle="puzzle-A", rank=3)
                score(conn, TODAY, 1, puzzle="puzzle-B", rank=999, solved=0, display="X/6")
                score(conn, TODAY, 2, puzzle="puzzle-B", rank=6)
                embed = embeds.build_wrap_embed(TODAY)
                assert embed is not None
                text = "\n".join(field.value or "" for field in embed.fields)
                self.assertIn("percentile", text)
                self.assertIn("players", text)
                self.assertIn("Higher percentile = easier than usual for the group.", text)


if __name__ == "__main__":
    unittest.main()
