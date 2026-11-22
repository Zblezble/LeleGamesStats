# -*- coding: utf-8 -*-
"""Personal performance-trend regressions using historical percentile baselines.

Run: python -X utf8 tests/test_trends.py   (exits 1 on failure)
Every case uses a throwaway SQLite file and fixed dates far from the wall clock.
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

import commands
import config
import db
import difficulty
from difficulty import TrendResult


def temporary_database():
    fd, path = tempfile.mkstemp(prefix="lele-trend-tests-", suffix=".db")
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


def score(conn, day, uid, game="Wordle", puzzle="today", solved=1,
          rank: object = 2, display: object = "2/6"):
    conn.execute(
        "INSERT INTO scores (board_date,user_id,user_name,game,puzzle_id,"
        "solved,rank_score,display_score) VALUES (?,?,?,?,?,?,?,?)",
        (day.isoformat(), uid, f"uid-{uid}", game, puzzle, solved, rank, display),
    )
    conn.commit()


def baseline(conn, dates, game, rank, display):
    """Create 30 attempts and 10 distinct puzzle IDs across the supplied dates."""
    pin_count = 3
    for index, day in enumerate(dates):
        for uid in (11, 12, 13):
            for pin in range(pin_count):
                score(conn, day, uid, game, f"base-{index}-{pin}", 1, rank, display)


def add_window_results(conn, game, display_for_rank, previous_ranks,
                       recent_ranks, previous_dates, recent_dates,
                       puzzles=("trend",)):
    """Insert one valid result for each supplied rank/date combination."""
    for rank, day in zip(previous_ranks, previous_dates):
        for offset, puzzle in enumerate(puzzles):
            score(conn, day, 1, game, f"prev-{offset}", 1, rank,
                  display_for_rank(rank))
    for rank, day in zip(recent_ranks, recent_dates):
        for offset, puzzle in enumerate(puzzles):
            score(conn, day, 1, game, f"recent-{offset}", 1, rank,
                  display_for_rank(rank))


class TrendTests(unittest.TestCase):
    def test_classification_thresholds_are_inclusive(self):
        self.assertEqual(difficulty._classify_trend(15.0), "improving")
        self.assertEqual(difficulty._classify_trend(14.999), "stable")
        self.assertEqual(difficulty._classify_trend(-15.0), "declining")
        self.assertEqual(difficulty._classify_trend(-14.999), "stable")
        self.assertEqual(difficulty._classify_trend(0.0), "stable")

    def test_daily_trend_classifications(self):
        cases = (
            ("declining", 2, 6, -57.142857142857146),
            ("improving", 6, 2, 50.0),
            ("stable", 3, 3, 0.0),
        )
        for name, previous_rank, recent_rank, expected_change in cases:
            with self.subTest(name=name):
                old_path, path = temporary_database()
                try:
                    with sqlite3.connect(config.DB_PATH) as conn:
                        baseline(
                            conn,
                            [date(2026, 9, 1) + timedelta(days=index)
                             for index in range(10)],
                            "Wordle", 6.0, "6/6",
                        )
                        add_window_results(
                            conn, "Wordle", lambda rank: f"{rank}/6",
                            [previous_rank] * 5, [recent_rank] * 5,
                            [date(2026, 11, 2) + timedelta(days=2 * index)
                             for index in range(5)],
                            [date(2026, 11, 17) + timedelta(days=2 * index)
                             for index in range(5)],
                        )
                    result = difficulty.calculate_game_trend(
                        1, "Wordle", date(2026, 11, 30))
                    self.assertEqual(result.status, name)
                    self.assertEqual(result.period_days, 30)
                    self.assertEqual(result.previous_count, 5)
                    self.assertEqual(result.recent_count, 5)
                    previous_average = result.previous_average
                    recent_average = result.recent_average
                    change_pp = result.change_pp
                    self.assertIsNotNone(previous_average)
                    self.assertIsNotNone(recent_average)
                    self.assertIsNotNone(change_pp)
                    if previous_average is None or recent_average is None:
                        self.fail("A classified trend must include averages.")
                    if name == "declining":
                        self.assertGreater(previous_average, recent_average)
                    elif name == "improving":
                        self.assertLess(previous_average, recent_average)
                    else:
                        self.assertEqual(result.status, "stable")
                finally:
                    cleanup(old_path, path)

    def test_daily_windows_exclude_outside_results_and_future_data(self):
        old_path, path = temporary_database()
        try:
            with sqlite3.connect(config.DB_PATH) as conn:
                baseline(
                    conn,
                    [date(2026, 9, 1) + timedelta(days=index)
                     for index in range(10)],
                    "Wordle", 6.0, "6/6",
                )
                add_window_results(
                    conn, "Wordle", lambda rank: f"{rank}/6", [3] * 5, [3] * 5,
                    [date(2026, 11, 2) + timedelta(days=2 * index)
                     for index in range(5)],
                    [date(2026, 11, 17) + timedelta(days=2 * index)
                     for index in range(5)],
                )
                # Both are outside the queried 30-day trend windows.
                score(conn, date(2026, 10, 31), 1, puzzle="before")
                score(conn, date(2026, 12, 1), 1, puzzle="after")
            first = difficulty.calculate_game_trend(1, "Wordle", date(2026, 11, 30))
            self.assertEqual(first.status, "stable")
            self.assertEqual(first.previous_count, 5)
            self.assertEqual(first.recent_count, 5)

            # A result after the requested end date must not affect that trend.
            with sqlite3.connect(config.DB_PATH) as conn:
                score(conn, date(2026, 12, 1), 1, puzzle="future")
            second = difficulty.calculate_game_trend(1, "Wordle", date(2026, 11, 30))
            self.assertEqual(first, second)
        finally:
            cleanup(old_path, path)

    def test_same_day_puzzles_are_counted_separately(self):
        old_path, path = temporary_database()
        try:
            with sqlite3.connect(config.DB_PATH) as conn:
                baseline(
                    conn,
                    [date(2026, 9, 1) + timedelta(days=index)
                     for index in range(10)],
                    "Wordle", 6.0, "6/6",
                )
                add_window_results(
                    conn, "Wordle", lambda rank: f"{rank}/6", [3] * 5,
                    [3] * 4,
                    [date(2026, 11, 2) + timedelta(days=2 * index)
                     for index in range(5)],
                    [date(2026, 11, 17) + timedelta(days=2 * index)
                     for index in range(4)],
                )
                # Two valid puzzle results on one recent day count separately.
                score(conn, date(2026, 11, 23), 1, puzzle="same-a", rank=3,
                      display="3/6")
                score(conn, date(2026, 11, 23), 1, puzzle="same-b", rank=3,
                      display="3/6")
            result = difficulty.calculate_game_trend(1, "Wordle", date(2026, 11, 30))
            self.assertEqual(result.status, "stable")
            self.assertEqual(result.previous_count, 5)
            self.assertEqual(result.recent_count, 6)
        finally:
            cleanup(old_path, path)

    def test_dnf_is_a_valid_trend_result(self):
        old_path, path = temporary_database()
        try:
            with sqlite3.connect(config.DB_PATH) as conn:
                baseline(
                    conn,
                    [date(2026, 9, 1) + timedelta(days=index)
                     for index in range(10)],
                    "Wordle", 6.0, "6/6",
                )
                add_window_results(
                    conn, "Wordle", lambda rank: f"{rank}/6", [3] * 5, [3] * 4,
                    [date(2026, 11, 2) + timedelta(days=2 * index)
                     for index in range(5)],
                    [date(2026, 11, 17) + timedelta(days=2 * index)
                     for index in range(4)],
                )
                score(conn, date(2026, 11, 25), 1, puzzle="dnf", solved=0,
                      rank=999, display="X/6")
            result = difficulty.calculate_game_trend(1, "Wordle", date(2026, 11, 30))
            self.assertEqual(result.previous_count, 5)
            self.assertEqual(result.recent_count, 5)
            self.assertEqual(result.status, "declining")
            previous_average = result.previous_average
            recent_average = result.recent_average
            if previous_average is None or recent_average is None:
                self.fail("A classified trend must include averages.")
            self.assertLess(recent_average, previous_average)
        finally:
            cleanup(old_path, path)

    def test_valid_zero_score_is_included(self):
        old_path, path = temporary_database()
        try:
            with sqlite3.connect(config.DB_PATH) as conn:
                baseline(
                    conn,
                    [date(2026, 9, 1) + timedelta(days=index)
                     for index in range(10)],
                    "Maptap", -50.0, "50 pts",
                )
                add_window_results(
                    conn, "Maptap", lambda rank: f"{abs(rank):.0f} pts",
                    [-50] * 5, [-50] * 4,
                    [date(2026, 11, 2) + timedelta(days=2 * index)
                     for index in range(5)],
                    [date(2026, 11, 17) + timedelta(days=2 * index)
                     for index in range(4)],
                )
                score(conn, date(2026, 11, 25), 1, game="Maptap", puzzle="zero",
                      rank=0, display="0 pts")
            result = difficulty.calculate_game_trend(1, "Maptap", date(2026, 11, 30))
            self.assertEqual(result.previous_count, 5)
            self.assertEqual(result.recent_count, 5)
            self.assertIn(result.status, ("stable", "declining"))
            previous_average = result.previous_average
            recent_average = result.recent_average
            if previous_average is None or recent_average is None:
                self.fail("A classified trend must include averages.")
            self.assertLessEqual(recent_average, previous_average)
        finally:
            cleanup(old_path, path)

    def test_weekly_game_uses_180_day_windows(self):
        old_path, path = temporary_database()
        try:
            with sqlite3.connect(config.DB_PATH) as conn:
                # Three puzzle IDs x three users x weekly dates creates enough
                # baseline attempts and distinct puzzle IDs for every rolling
                # 90-day difficulty-history window used by the trend dates.
                baseline(
                    conn,
                    [date(2025, 6, 19) + timedelta(weeks=index)
                     for index in range(9)],
                    "Thursday Thirty", -6.0, "6/30",
                )
                baseline(
                    conn,
                    [date(2025, 12, 11) + timedelta(weeks=index)
                     for index in range(5)],
                    "Thursday Thirty", -6.0, "6/30",
                )
                previous_dates = [date(2025, 9, 11) + timedelta(weeks=index)
                                  for index in range(5)]
                recent_dates = [date(2026, 2, 5) + timedelta(weeks=index)
                                for index in range(5)]
                add_window_results(
                    conn, "Thursday Thirty", lambda rank: f"{abs(rank):.0f}/30",
                    [-6] * 5, [-6] * 5, previous_dates, recent_dates,
                )
            result = difficulty.calculate_game_trend(
                1, "Thursday Thirty", date(2026, 3, 5))
            self.assertEqual(result.period_days, 180)
            self.assertEqual(result.previous_count, 5)
            self.assertEqual(result.recent_count, 5)
            self.assertEqual(result.status, "stable")
        finally:
            cleanup(old_path, path)

    def test_variants_and_insufficient_data_are_independent(self):
        old_path, path = temporary_database()
        try:
            with sqlite3.connect(config.DB_PATH) as conn:
                baseline(
                    conn,
                    [date(2026, 9, 1) + timedelta(days=index)
                     for index in range(10)],
                    "Chessle (Medium)", 3.0, "3/6",
                )
                add_window_results(
                    conn, "Chessle (Medium)", lambda rank: f"{rank}/6",
                    [3] * 5, [3] * 5,
                    [date(2026, 11, 2) + timedelta(days=2 * index)
                     for index in range(5)],
                    [date(2026, 11, 17) + timedelta(days=2 * index)
                     for index in range(5)],
                )
                # A different Chessle variant must not affect the Medium trend.
                score(conn, date(2026, 11, 20), 1, game="Chessle (Hard)",
                      puzzle="hard", rank=4, display="4/6")
            medium = difficulty.calculate_game_trend(
                1, "Chessle (Medium)", date(2026, 11, 30))
            hard = difficulty.calculate_game_trend(
                1, "Chessle (Hard)", date(2026, 11, 30))
            self.assertEqual(medium.status, "stable")
            self.assertEqual(medium.previous_count, 5)
            self.assertEqual(medium.recent_count, 5)
            self.assertEqual(hard.status, "insufficient")
            self.assertEqual((hard.previous_count, hard.recent_count), (0, 0))
        finally:
            cleanup(old_path, path)

    def test_insufficient_trend_has_no_averages(self):
        old_path, path = temporary_database()
        try:
            with sqlite3.connect(config.DB_PATH) as conn:
                baseline(
                    conn,
                    [date(2026, 9, 1) + timedelta(days=index)
                     for index in range(10)],
                    "Wordle", 6.0, "6/6",
                )
                add_window_results(
                    conn, "Wordle", lambda rank: f"{rank}/6", [3] * 4, [3] * 5,
                    [date(2026, 11, 2) + timedelta(days=2 * index)
                     for index in range(4)],
                    [date(2026, 11, 17) + timedelta(days=2 * index)
                     for index in range(5)],
                )
            result = difficulty.calculate_game_trend(1, "Wordle", date(2026, 11, 30))
            self.assertEqual(result.status, "insufficient")
            self.assertEqual(result.previous_count, 4)
            self.assertEqual(result.recent_count, 5)
            self.assertIsNone(result.previous_average)
            self.assertIsNone(result.recent_average)
            self.assertIsNone(result.change_pp)
        finally:
            cleanup(old_path, path)

    def test_discord_trend_rendering(self):
        improving = TrendResult(
            status="improving", previous_average=48.4, recent_average=67.2,
            change_pp=18.8, previous_count=7, recent_count=9, period_days=30,
        )
        self.assertEqual(
            commands._format_game_trend(improving),
            "📈 Trend (30 days): Improving\n"
            "Previous: 48 → Recent: 67 (+19 pp)",
        )
        insufficient = TrendResult(
            status="insufficient", previous_average=None, recent_average=None,
            change_pp=None, previous_count=2, recent_count=4, period_days=30,
        )
        self.assertEqual(
            commands._format_game_trend(insufficient),
            "❔ Trend: Not enough data",
        )


if __name__ == "__main__":
    unittest.main()
