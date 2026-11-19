# -*- coding: utf-8 -*-
"""Focused regressions for the fixed-attempt game history chart.

Run: python -X utf8 test_stats_charts.py   (exits 1 on failure)
Renderer cases are pure; command-data cases use a throwaway SQLite file.
"""
import asyncio
import inspect
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from typing import Any, cast

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

import config
import commands
import db
import discord
import games
import stats_charts
from stats_charts import DailyAttempt, DailyScore


def day(offset_from_november=1, month=11, year=2026):
    return date(year, month, offset_from_november)


def solved(day_value, attempts):
    return DailyAttempt(day_value, "solved", attempts)


def dnf(day_value):
    return DailyAttempt(day_value, "dnf", None)


def missing(day_value):
    return DailyAttempt(day_value, "missing", None)


def scored(day_value, score, maximum=None):
    return DailyScore(day_value, "score", score, maximum)


def score_dnf(day_value):
    return DailyScore(day_value, "dnf", None, None)


def score_missing(day_value):
    return DailyScore(day_value, "missing", None, None)


def add_score(board_date, user_id, user_name, game, puzzle_id,
              solved_value, rank_score, display_score):
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.execute(
            "INSERT INTO scores (board_date, user_id, user_name, game, puzzle_id,"
            " solved, rank_score, display_score) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (board_date, user_id, user_name, game, puzzle_id,
             solved_value, rank_score, display_score),
        )
        conn.commit()


def fresh_db(today="2026-11-18"):
    fd, path = tempfile.mkstemp(prefix="stats_chart_test_", suffix=".db")
    os.close(fd)
    old_path = config.DB_PATH
    old_today = config.today_str
    config.DB_PATH = path
    config.today_str = lambda: today
    db.init_db()
    return old_path, old_today, path


def cleanup(old_path, old_today, path):
    config.DB_PATH = old_path
    config.today_str = old_today
    try:
        os.remove(path)
    except OSError:
        pass


class AttemptModelTests(unittest.TestCase):
    def test_daily_attempt_states_are_validated(self):
        DailyAttempt(day(1), "solved", 1)
        DailyAttempt(day(1), "dnf", None)
        DailyAttempt(day(1), "missing", None)
        invalid_cases: list[tuple[Any, int | None]] = [
            ("solved", 0),
            ("solved", True),
            ("solved", None),
            ("dnf", 4),
            ("missing", 2),
            ("invented", 3),
        ]
        for invalid in invalid_cases:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    DailyAttempt(day(1), invalid[0], invalid[1])

    def test_renderer_snapshot_is_aligned_and_distinguishes_states(self):
        results = [
            solved(day(5), 1),
            solved(day(6), 3),
            dnf(day(7)),
            missing(day(8)),
            solved(day(9), 6),
        ]
        actual = stats_charts.render_attempt_chart(
            results, 6, day(5), day(9), title="Test",
        )
        expected = (
            "TEST · 2026-11-05 to 2026-11-09\n"
            "Guesses (lower = better)\n"
            "\n"
            "6 │     X   ▄\n"
            "5 │         ▄\n"
            "4 │         ▄\n"
            "3 │   ▄     ▄\n"
            "2 │   ▄     ▄\n"
            "1 │ ▄ ▄     ▄\n"
            "  └──────────\n"
            "   05      09"
        )
        self.assertEqual(actual, expected)

    def test_solved_maximum_is_a_full_bar_not_dnf(self):
        results = [solved(day(1), 6), dnf(day(2))]
        chart = stats_charts.render_attempt_chart(results, 6, day(1), day(2))
        top_row = chart.splitlines()[3]
        self.assertEqual(top_row, "6 │ ▄ X")

    def test_all_missing_and_all_dnf_are_valid(self):
        all_missing = [missing(day(index)) for index in range(1, 4)]
        chart = stats_charts.render_attempt_chart(all_missing, 6, day(1), day(3))
        attempt_rows = chart.splitlines()[3:9]
        self.assertTrue(all(stats_charts.ATTEMPT_SYMBOL not in row and " X" not in row for row in attempt_rows),
                        attempt_rows)
        self.assertEqual(
            stats_charts.summarize_attempts(all_missing),
            "Played: 0/3 days\nSolved: 0/0 (—)\nAvg: —\nBest: —",
        )

        all_dnf = [dnf(day(index)) for index in range(1, 4)]
        chart = stats_charts.render_attempt_chart(all_dnf, 6, day(1), day(3))
        self.assertEqual(chart.splitlines()[3], "6 │ X X X")
        self.assertEqual(
            stats_charts.summarize_attempts(all_dnf),
            "Played: 3/3 days\nSolved: 0/3 (0%)\nAvg: —\nBest: —",
        )

    def test_summary_excludes_dnf_from_average_but_not_solve_rate(self):
        results = [
            solved(day(1), 2),
            solved(day(2), 4),
            dnf(day(3)),
            missing(day(4)),
        ]
        self.assertEqual(
            stats_charts.summarize_attempts(results),
            "Played: 3/4 days\nSolved: 2/3 (67%)\nAvg: 3.0 guesses\nBest: 2 guesses",
        )

    def test_inclusive_ranges_and_boundaries(self):
        results_14 = [solved(day(index), 1) for index in range(5, 19)]
        chart = stats_charts.render_attempt_chart(results_14, 6, day(5), day(18))
        self.assertIn("2026-11-05 to 2026-11-18", chart)
        self.assertEqual(len(results_14), 14)

        start = date(2025, 10, 29)
        end = date(2025, 11, 11)
        results = [solved(start, 1), solved(end, 2)]
        results[1:1] = [missing(start.fromordinal(start.toordinal() + offset))
                        for offset in range(1, 13)]
        chart = stats_charts.render_attempt_chart(results, 6, start, end)
        self.assertIn("2025-10-29 to 2025-11-11", chart)
        self.assertEqual(len(results), 14)

        results_30 = [missing(day(index)) for index in range(1, 31)]
        chart = stats_charts.render_attempt_chart(results_30, 7, day(1), day(30))
        self.assertIn("2026-11-01 to 2026-11-30", chart)
        self.assertEqual(len(results_30), 30)

    def test_rejects_bad_periods_and_attempt_heights(self):
        with self.assertRaises(ValueError):
            stats_charts.render_attempt_chart([], 6, day(1), day(1))
        with self.assertRaises(ValueError):
            stats_charts.render_attempt_chart(
                [solved(day(1), 7)], 6, day(1), day(1))
        with self.assertRaises(ValueError):
            stats_charts.render_attempt_chart(
                [missing(day(1))], 6, day(2), day(1))
        with self.assertRaises(TypeError):
            stats_charts.render_attempt_chart(
                cast(list[DailyAttempt], [(day(1), "solved", 1)]), 6, day(1), day(1))

    def test_supported_fixed_attempt_registry_and_variants(self):
        expected = {
            "Wordle": 6,
            "Worldle": 6,
            "Flagle": 6,
            "Tradle": 6,
            "Mathle": 6,
            "Regionle": 7,
            "Chessle": 6,
        }
        self.assertEqual(
            {name: meta["max_attempts"]
             for name, meta in games.FIXED_ATTEMPT_GAMES.items()},
            expected,
        )
        self.assertEqual(stats_charts.max_attempts_for("Regionle"), 7)
        self.assertEqual(
            stats_charts.max_attempts_for("Chessle (Medium)"), 6)
        self.assertEqual(
            games.fixed_attempt_family("Regionle (US States)"), "Regionle")
        self.assertIsNone(games.fixed_attempt_family("Songless"))
        self.assertIsNone(games.fixed_attempt_family("Trivmount"))

    def test_stored_rows_map_to_chart_states(self):
        old_path, old_today, path = fresh_db("2026-11-09")
        try:
            add_score("2026-11-05", 1, "Alice", "Worldle", "#1", 1, 3.98, "4/6 (100%)")
            add_score("2026-11-06", 1, "Alice", "Worldle", "#2", 0, 99.0, "X/6")
            add_score("2026-11-07", 1, "Alice", "Worldle", "#3", 1, 6.0, "6/6 (100%)")
            # Invalid or non-attempt values do not become invented bars.
            add_score("2026-11-08", 1, "Alice", "Worldle", "#4", 1, 7.0, "7/6")
            add_score("2026-11-09", 1, "Alice", "Trivmount", "#5", 1, -100.0, "12/12")

            results = stats_charts.load_attempts(
                1, "Worldle", day(5), day(9))
            self.assertEqual(results[0], solved(day(5), 4))
            self.assertEqual(results[1], dnf(day(6)))
            self.assertEqual(results[2], solved(day(7), 6))
            self.assertEqual(results[3], missing(day(8)))
            self.assertEqual(results[4], missing(day(9)))
        finally:
            cleanup(old_path, old_today, path)

    def test_latest_result_wins_on_multiple_puzzle_instances(self):
        old_path, old_today, path = fresh_db("2026-11-09")
        try:
            add_score("2026-11-08", 1, "Alice", "Chessle (Medium)", "#1", 1, 4.0, "4/6")
            add_score("2026-11-08", 1, "Alice", "Chessle (Medium)", "#2", 1, 2.0, "2/6")
            add_score("2026-11-08", 1, "Alice", "Chessle (Medium)", "#3", 0, 99.0, "X/6")
            results = stats_charts.load_attempts(
                1, "Chessle (Medium)", day(8), day(8))
            self.assertEqual(results, [dnf(day(8))])
        finally:
            cleanup(old_path, old_today, path)

    def test_base_name_falls_back_to_sole_variant(self):
        old_path, old_today, path = fresh_db("2026-11-09")
        try:
            add_score("2026-11-08", 1, "Alice", "Chessle (Medium)", "#1", 1, 2.0, "2/6")
            resolved, variants = stats_charts.resolve_chart_game(
                1, "Chessle", day(5), day(9))
            self.assertEqual((resolved, variants), ("Chessle (Medium)", []))
        finally:
            cleanup(old_path, old_today, path)

    def test_multiple_variants_use_the_designated_active_variant(self):
        old_path, old_today, path = fresh_db("2026-11-09")
        try:
            add_score("2026-11-08", 1, "Alice", "Chessle (Medium)", "#1", 1, 2.0, "2/6")
            add_score("2026-11-09", 1, "Alice", "Chessle (Hard)", "#2", 1, 3.0, "3/6")
            resolved, variants = stats_charts.resolve_chart_game(
                1, "Chessle", day(5), day(9))
            self.assertEqual((resolved, variants), ("Chessle (Medium)", []))

            # An explicit variant remains supported for manual queries, but an
            # explicit missing variant must not be replaced by another variant.
            resolved, variants = stats_charts.resolve_chart_game(
                1, "Chessle (Hard)", day(5), day(9))
            self.assertEqual((resolved, variants), ("Chessle (Hard)", []))
            resolved, variants = stats_charts.resolve_chart_game(
                1, "Chessle (Expert)", day(5), day(9))
            self.assertEqual((resolved, variants), (None, []))
        finally:
            cleanup(old_path, old_today, path)

    def test_magnitudle_uses_size_it_up_results(self):
        old_path, old_today, path = fresh_db("2026-11-09")
        try:
            add_score("2026-11-08", 1, "Alice", "Magnitudle (Size It Up)", "#1", 1, -230.0, "230/500")
            add_score("2026-11-09", 1, "Alice", "Magnitudle (Other)", "#2", 1, -100.0, "100/500")
            resolved, variants = stats_charts.resolve_chart_game(
                1, "Magnitudle", day(5), day(9))
            self.assertEqual(
                (resolved, variants),
                ("Magnitudle (Size It Up)", []),
            )
        finally:
            cleanup(old_path, old_today, path)

    def test_unsupported_game_is_not_resolved(self):
        old_path, old_today, path = fresh_db("2026-11-09")
        try:
            add_score("2026-11-08", 1, "Alice", "Songless", "#1", 1, -100.0, "2/2 (Roc:1 Pop:2)")
            add_score("2026-11-08", 1, "Alice", "Globle", "#2", 1, 5.0, "5 guesses")
            self.assertEqual(
                stats_charts.resolve_chart_game(1, "Songless", day(5), day(9)),
                (None, []),
            )
            self.assertEqual(
                stats_charts.resolve_chart_game(1, "Globle", day(5), day(9)),
                (None, []),
            )
        finally:
            cleanup(old_path, old_today, path)

    def test_autocomplete_offers_only_chartable_games(self):
        old_path, old_today, path = fresh_db("2026-11-09")
        try:
            add_score("2026-11-08", 1, "Alice", "Songless", "#1", 1, -100.0, "2/2 (Roc:1 Pop:2)")
            add_score("2026-11-08", 1, "Alice", "Globle", "#2", 1, 5.0, "5 guesses")
            choices = asyncio.run(commands._chart_game_autocomplete(None, ""))
            values = {choice.value for choice in choices}
            self.assertIn("Worldle", values)
            self.assertIn("Chessle", values)
            self.assertIn("Magnitudle", values)
            self.assertIn("Trivmount", values)
            self.assertIn("Maptap", values)
            self.assertNotIn("Songless", values)
            self.assertNotIn("Globle", values)
            self.assertNotIn("Chessle (Medium)", values)
            self.assertNotIn("Magnitudle (Size It Up)", values)
        finally:
            cleanup(old_path, old_today, path)

    def test_disabled_games_are_hidden_from_chart_autocomplete(self):
        old_disabled = config.DISABLED_GAMES
        config.DISABLED_GAMES = {"wordle"}
        try:
            choices = asyncio.run(commands._chart_game_autocomplete(None, ""))
            values = {choice.value for choice in choices}
            self.assertNotIn("Wordle", values)
            self.assertIn("Worldle", values)
        finally:
            config.DISABLED_GAMES = old_disabled

    def test_wordle_chart_metadata_remains_available_when_disabled(self):
        self.assertEqual(games.fixed_attempt_family("Wordle"), "Wordle")
        self.assertEqual(stats_charts.max_attempts_for("Wordle"), 6)

    def test_score_registry_and_metadata(self):
        expected_renderers = {
            "Trivmount": "fixed_score",
            "History in Order": "fixed_score",
            "Majority": "fixed_score",
            "Songspot": "fixed_score",
            "Centumth": "scaled_score",
            "Magnitudle": "scaled_score",
            "Maptap": "scaled_score",
        }
        self.assertEqual(
            {name: meta["renderer"]
             for name, meta in games.SCORE_CHART_GAMES.items()},
            expected_renderers,
        )
        self.assertEqual(stats_charts.score_chart_meta("Trivmount")["max_score"], 12)
        self.assertEqual(stats_charts.score_chart_meta("Maptap")["max_score"], None)
        self.assertEqual(games.score_chart_family("Magnitudle (Size It Up)"), "Magnitudle")
        self.assertIsNone(games.score_chart_family("Songless"))

    def test_score_states_are_validated(self):
        scored(day(1), 0, 12)
        scored(day(1), 12, 12)
        score_dnf(day(1))
        score_missing(day(1))
        for invalid in (
            ("score", -1, 12),
            ("score", 13, 12),
            ("score", None, 12),
            ("dnf", 3, None),
            ("missing", 0, None),
            ("invented", 3, None),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    DailyScore(day(1), invalid[0], invalid[1], invalid[2])

    def test_fixed_score_chart_boundaries_zero_and_missing(self):
        results = [
            scored(day(9), 10, 12),
            scored(day(10), 0, 12),
            score_dnf(day(11)),
            score_missing(day(12)),
            scored(day(13), 12, 12),
        ]
        actual = stats_charts.render_fixed_score_chart(
            results, 12, day(9), day(13), title="Trivmount", unit="correct",
        )
        expected = (
            "TRIVMOUNT · 2026-11-09 to 2026-11-13\n"
            "Correct (higher = better)\n"
            "\n"
            "12 │     X   ▄\n"
            "11 │         ▄\n"
            "10 │ ▄       ▄\n"
            " 9 │ ▄       ▄\n"
            " 8 │ ▄       ▄\n"
            " 7 │ ▄       ▄\n"
            " 6 │ ▄       ▄\n"
            " 5 │ ▄       ▄\n"
            " 4 │ ▄       ▄\n"
            " 3 │ ▄       ▄\n"
            " 2 │ ▄       ▄\n"
            " 1 │ ▄       ▄\n"
            "   └──────────\n"
            "    09      13"
        )
        self.assertEqual(actual, expected)
        self.assertEqual(
            stats_charts.summarize_fixed_scores(results, 12),
            "Played: 4/5 days\nAvg: 7.3/12\nBest: 12/12\nPerfect: 1",
        )

    def test_fixed_score_chart_uses_variable_display_maximums(self):
        results = [
            scored(day(1), 6, 7),
            scored(day(2), 8, 10),
            score_missing(day(3)),
        ]
        chart = stats_charts.render_fixed_score_chart(
            results, None, day(1), day(3), title="History", unit="correct",
        )
        self.assertIn("10 │", chart)
        self.assertIn(" 8 │", chart)
        self.assertNotIn("11 │", chart)
        self.assertEqual(
            stats_charts.summarize_fixed_scores(results),
            "Played: 2/3 days\nAvg: 7.0/10\nBest: 8/10\nPerfect: 0",
        )

    def test_scaled_score_chart_scales_without_changing_raw_scores(self):
        results = [
            scored(day(9), 962, None),
            scored(day(10), 0, None),
            score_dnf(day(11)),
            score_missing(day(12)),
            scored(day(13), 100, None),
        ]
        chart = stats_charts.render_scaled_score_chart(
            results, None, day(9), day(13), title="Maptap", unit="pts",
        )
        lines = chart.splitlines()
        self.assertEqual(lines[0], "MAPTAP · 2026-11-09 to 2026-11-13")
        self.assertEqual(lines[3], "1000 │ ▉   X")
        self.assertEqual(lines[4], " 900 │ ▉")
        self.assertEqual(lines[12], " 100 │ ▉       ▉")
        self.assertEqual(lines[13], "     └──────────")
        self.assertNotIn("   0 │", chart)
        self.assertEqual(
            stats_charts.summarize_scaled_scores(results),
            "Played: 4/5 days\nAvg: 354 pts\nBest: 962 pts",
        )

    def test_scaled_score_chart_uses_nearest_bucket_rounding(self):
        results = [
            scored(day(1), 49, None),
            scored(day(2), 50, None),
            scored(day(3), 149, None),
            scored(day(4), 150, None),
            scored(day(5), 932, None),
        ]
        chart = stats_charts.render_scaled_score_chart(
            results, 1000, day(1), day(5), title="Maptap", unit="pts",
        )
        rows = chart.splitlines()
        self.assertNotIn(stats_charts.SCORE_SYMBOL, rows[3])       # 932 rounds to 900, not 1000
        self.assertEqual(rows[12], " 100 │   ▉ ▉ ▉ ▉")
        self.assertEqual(rows[11], " 200 │       ▉ ▉")
        self.assertEqual(rows[10], " 300 │         ▉")
        self.assertEqual(rows[4], " 900 │         ▉")

    def test_stored_scores_map_to_score_chart_states(self):
        old_path, old_today, path = fresh_db("2026-11-18")
        try:
            add_score("2026-11-09", 1, "Alice", "Trivmount", "#1", 1, -91.6667, "11/12")
            add_score("2026-11-10", 1, "Alice", "History in Order", "#2", 0, -8.0, "8/10")
            add_score("2026-11-11", 1, "Alice", "Majority", "#3", 1, -252.0, "2/5 (52%)")
            add_score("2026-11-12", 1, "Alice", "Songspot", "#4", 1, -79.999, "4/5 · 3,450 pts")
            add_score("2026-11-13", 1, "Alice", "Centumth", "#5", 1, -217.0, "217/490")
            add_score("2026-11-14", 1, "Alice", "Magnitudle (Size It Up)", "#6", 1, -230.0, "230/500")
            add_score("2026-11-15", 1, "Alice", "Maptap", "#7", 1, 0.0, "0 pts")
            add_score("2026-11-16", 1, "Alice", "Trivmount", "#8", 0, 10000.0, "DNF")
            add_score("2026-11-17", 1, "Alice", "Trivmount", "#9", 1, -108.3333, "13/12")

            self.assertEqual(
                stats_charts.load_scores(1, "Trivmount", day(9), day(17)),
                [
                    scored(day(9), 11, 12),
                    score_missing(day(10)),
                    score_missing(day(11)),
                    score_missing(day(12)),
                    score_missing(day(13)),
                    score_missing(day(14)),
                    score_missing(day(15)),
                    score_dnf(day(16)),
                    score_missing(day(17)),
                ],
            )
            self.assertEqual(
                stats_charts.load_scores(1, "History in Order", day(10), day(10)),
                [scored(day(10), 8, 10)],
            )
            self.assertEqual(
                stats_charts.load_scores(1, "Majority", day(11), day(11)),
                [scored(day(11), 2, 5)],
            )
            self.assertEqual(
                stats_charts.load_scores(1, "Songspot", day(12), day(12)),
                [scored(day(12), 4, 5)],
            )
            self.assertEqual(
                stats_charts.load_scores(1, "Centumth", day(13), day(13)),
                [scored(day(13), 217, 490)],
            )
            self.assertEqual(
                stats_charts.load_scores(1, "Magnitudle (Size It Up)", day(14), day(14)),
                [scored(day(14), 230, 500)],
            )
            self.assertEqual(
                stats_charts.load_scores(1, "Maptap", day(15), day(15)),
                [scored(day(15), 0, None)],
            )
        finally:
            cleanup(old_path, old_today, path)

    def test_score_chart_command_is_private_and_uses_score_summary(self):
        old_path, old_today, path = fresh_db("2026-11-18")
        try:
            add_score("2026-11-18", 1, "Alice", "Trivmount", "#1", 1, -100.0, "12/12")

            class FakeResponse:
                def __init__(self):
                    self.calls = []

                async def send_message(self, **kwargs):
                    self.calls.append(kwargs)

            class FakeInteraction:
                def __init__(self):
                    self.response = FakeResponse()

            class FakeUser:
                id = 1
                display_name = "Alice"

            interaction = cast(Any, FakeInteraction())
            asyncio.run(commands._send_game_chart(
                interaction, cast(Any, FakeUser()), "Trivmount"))
            self.assertEqual(len(interaction.response.calls), 1)
            self.assertTrue(interaction.response.calls[0]["ephemeral"])
            embed = interaction.response.calls[0]["embed"]
            self.assertEqual(embed.fields[1].value,
                             "Played: 1/10 days\nAvg: 12.0/12\nBest: 12/12\nPerfect: 1")

            public_interaction = cast(Any, FakeInteraction())
            asyncio.run(commands._send_game_chart(
                public_interaction, cast(Any, FakeUser()), "Trivmount", public=True))
            self.assertFalse(public_interaction.response.calls[0]["ephemeral"])
        finally:
            cleanup(old_path, old_today, path)

    def test_all_time_stats_helper_preserves_existing_shape(self):
        old_path, old_today, path = fresh_db("2026-11-09")
        try:
            add_score("2026-11-08", 1, "Alice", "Wordle", "#1", 1, 1.0, "1/6")
            add_score("2026-11-08", 2, "Bob", "Wordle", "#1", 1, 2.0, "2/6")
            embed = __import__("commands").build_all_time_stats_embed(1, "Alice")
            self.assertIsNotNone(embed)
            self.assertEqual(embed.title, "All-time stats: Alice")
            names = [field.name for field in embed.fields]
            self.assertIn("Prison days", names)
            self.assertIn("Streak", names)
            self.assertIn("By game", names)
        finally:
            cleanup(old_path, old_today, path)

    def test_rendered_history_fits_discord_embed_limits(self):
        period = stats_charts.CHART_PERIOD_DAYS
        results = [solved(day(index), (index % 6) + 1) for index in range(1, period + 1)]
        chart = stats_charts.render_attempt_chart(
            results, 6, day(1), day(period))
        self.assertLessEqual(
            max(len(line) for line in chart.splitlines()[3:9]), 24
        )
        embed = discord.Embed(title="History")
        embed.add_field(name="Chart", value=f"```text\n{chart}\n```", inline=False)
        embed.add_field(
            name="Summary",
            value=stats_charts.summarize_attempts(results),
            inline=False,
        )
        self.assertLessEqual(len(embed), 6000)
        for field in embed.fields:
            self.assertLessEqual(len(field.value or ""), 1024)

    def test_chart_period_options_and_defaults(self):
        self.assertEqual(stats_charts.CHART_PERIOD_DAYS, 10)
        self.assertEqual(stats_charts.CHART_PERIOD_CHOICES, (10, 20))
        parameters = inspect.signature(commands.stats).parameters
        self.assertEqual(
            list(parameters), ["interaction", "game", "period", "user", "public"]
        )
        self.assertEqual(parameters["period"].default, 10)
        self.assertNotIn("player", parameters)
        choices = cast(Any, commands.stats).__discord_app_commands_param_choices__["period"]
        self.assertEqual([choice.value for choice in choices], [10, 20])

    def test_twenty_day_chart_uses_compact_same_width_layout(self):
        spaced_results = [
            solved(day(index), (index % 6) + 1) for index in range(1, 11)
        ]
        compact_results = [
            solved(day(index), (index % 6) + 1) for index in range(1, 21)
        ]
        spaced = stats_charts.render_attempt_chart(
            spaced_results, 6, day(1), day(10), period=10,
        )
        compact = stats_charts.render_attempt_chart(
            compact_results, 6, day(1), day(20), period=20,
        )
        spaced_rows = spaced.splitlines()[3:9]
        compact_rows = compact.splitlines()[3:9]
        self.assertEqual(
            max(len(row) for row in spaced_rows),
            max(len(row) for row in compact_rows),
        )
        self.assertTrue(all(stats_charts.ATTEMPT_COMPACT_SYMBOL in row for row in compact_rows))
        self.assertIn(stats_charts.ATTEMPT_COMPACT_SYMBOL * 20, compact)
        self.assertIn("   01      09      17", compact)

        scaled = stats_charts.render_scaled_score_chart(
            [scored(day(index), 500, 1000) for index in range(1, 21)],
            1000, day(1), day(20), period=20,
        )
        self.assertIn(stats_charts.SCORE_COMPACT_SYMBOL * 20, scaled)
        self.assertIn("   01      09      17", scaled)

    def test_chart_is_private_by_default_and_public_on_request(self):
        old_path, old_today, path = fresh_db("2026-11-18")
        try:
            add_score("2026-11-18", 1, "Alice", "Worldle", "#1", 1, 2.0, "2/6")

            class FakeResponse:
                def __init__(self):
                    self.calls = []

                async def send_message(self, **kwargs):
                    self.calls.append(kwargs)

            class FakeInteraction:
                def __init__(self):
                    self.response = FakeResponse()

            class FakeUser:
                id = 1
                display_name = "Alice"

            interaction = cast(Any, FakeInteraction())
            asyncio.run(commands._send_game_chart(
                interaction, cast(Any, FakeUser()), "Worldle"))
            self.assertEqual(len(interaction.response.calls), 1)
            self.assertTrue(interaction.response.calls[0]["ephemeral"])
            self.assertEqual(
                interaction.response.calls[0]["embed"].fields[0].name,
                "Last 10 days",
            )

            public_interaction = cast(Any, FakeInteraction())
            asyncio.run(commands._send_game_chart(
                public_interaction, cast(Any, FakeUser()), "Worldle", public=True))
            self.assertEqual(len(public_interaction.response.calls), 1)
            self.assertFalse(public_interaction.response.calls[0]["ephemeral"])
            self.assertEqual(
                public_interaction.response.calls[0]["embed"].fields[0].name,
                "Last 10 days",
            )
        finally:
            cleanup(old_path, old_today, path)


if __name__ == "__main__":
    unittest.main()
