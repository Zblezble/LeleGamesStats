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
            "5 │     │   ▄\n"
            "4 │     │   ▄\n"
            "3 │   ▄ │   ▄\n"
            "2 │   ▄ │   ▄\n"
            "1 │ ▄ ▄ │   ▄\n"
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
        self.assertEqual(chart.splitlines()[4], "5 │ │ │ │")
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
            "Travle": 14,
        }
        self.assertEqual(
            {name: meta["max_attempts"]
             for name, meta in games.FIXED_ATTEMPT_GAMES.items()},
            expected,
        )
        self.assertEqual(stats_charts.max_attempts_for("Regionle"), 7)
        self.assertEqual(stats_charts.max_attempts_for("Travle"), 14)
        self.assertTrue(
            stats_charts.fixed_attempt_meta("Travle").get("zero_is_best"))
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
            add_score("2026-11-08", 1, "Alice", "Roughly (How big)", "#1", 1, -79.0099, "~79% · best 99%")
            add_score("2026-11-08", 1, "Alice", "Roughly", "#2", 1, -65.0, "~65% · best 95%")
            self.assertEqual(
                stats_charts.resolve_chart_game(1, "Roughly (How big)", day(5), day(9)),
                (None, []),
            )
            self.assertEqual(
                stats_charts.resolve_chart_game(1, "Roughly", day(5), day(9)),
                (None, []),
            )
        finally:
            cleanup(old_path, old_today, path)

    def test_autocomplete_offers_only_chartable_games(self):
        old_path, old_today, path = fresh_db("2026-11-09")
        try:
            add_score("2026-11-08", 1, "Alice", "Roughly (How big)", "#1", 1, -79.0099, "~79% · best 99%")
            add_score("2026-11-08", 1, "Alice", "Globle", "#2", 1, 5.0, "5 guesses")
            choices = asyncio.run(commands._chart_game_autocomplete(None, ""))
            values = {choice.value for choice in choices}
            self.assertIn("Worldle", values)
            self.assertIn("Chessle", values)
            self.assertIn("Magnitudle", values)
            self.assertIn("Trivmount", values)
            self.assertIn("Maptap", values)
            self.assertIn("Globle", values)
            self.assertIn("Travle", values)
            self.assertIn("Metazooa", values)
            self.assertIn("Redactle", values)
            self.assertIn("Songless", values)
            self.assertIn("Roughly (Where from)", values)
            self.assertIn("Farflung", values)
            self.assertIn("Thursday Thirty", values)
            self.assertNotIn("Roughly (How big)", values)
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

    def test_guess_registry_and_metadata(self):
        self.assertEqual(
            games.GUESS_CHART_GAMES,
            {
                "Globle": {
                    "renderer": "scaled_guess", "default_max": 10, "unit": "guesses",
                },
                "Metazooa": {
                    "renderer": "scaled_guess", "default_max": 10,
                    "max_attempts": 20, "unit": "guesses",
                },
            },
        )
        self.assertEqual(games.guess_chart_family("Globle"), "Globle")
        self.assertEqual(games.guess_chart_family("Metazooa"), "Metazooa")
        self.assertEqual(stats_charts.guess_chart_meta("Globle")["default_max"], 10)
        self.assertEqual(stats_charts.guess_chart_meta("Metazooa")["max_attempts"], 20)
        self.assertIsNone(games.guess_chart_family("Travle"))

    def test_scaled_guess_chart_defaults_to_ten_and_scales_up(self):
        results = [
            solved(day(1), 5),
            solved(day(2), 10),
            dnf(day(3)),
            missing(day(4)),
        ]
        chart = stats_charts.render_scaled_guess_chart(
            results, 10, day(1), day(4), title="Globle",
        )
        lines = chart.splitlines()
        self.assertEqual(lines[0], "GLOBLE · 2026-11-01 to 2026-11-04")
        self.assertEqual(lines[3], "10 │   ▄ X")
        self.assertEqual(lines[8], " 5 │ ▄ ▄ │")
        self.assertEqual(lines[6], " 7 │   ▄ │")
        self.assertNotIn(" 0 │", chart)

        dynamic = stats_charts.render_scaled_guess_chart(
            [solved(day(1), 17), solved(day(2), 5)],
            10, day(1), day(2), title="Globle",
        )
        self.assertIn("17 │ ▄", dynamic)
        self.assertIn(" 5 │ ▄ ▄", dynamic)
        self.assertNotIn("18 │", dynamic)

    def test_globle_rows_map_to_guess_chart_states(self):
        old_path, old_today, path = fresh_db("2026-11-09")
        try:
            add_score("2026-11-08", 1, "Alice", "Globle", "#1", 1, 5.0, "5 guesses")
            add_score("2026-11-09", 1, "Alice", "Globle", "#2", 0, 999.0, "DNF")
            add_score("2026-11-10", 1, "Alice", "Globle", "#3", 1, 99.0, "bad")
            results = stats_charts.load_guesses(1, "Globle", day(8), day(10))
            self.assertEqual(results, [
                solved(day(8), 5),
                dnf(day(9)),
                missing(day(10)),
            ])
            resolved, variants = stats_charts.resolve_chart_game(
                1, "Globle", day(8), day(9))
            self.assertEqual((resolved, variants), ("Globle", []))
        finally:
            cleanup(old_path, old_today, path)

    def test_twenty_day_globle_chart_uses_compact_guess_blocks(self):
        results = [solved(day(index), 4) for index in range(1, 21)]
        chart = stats_charts.render_scaled_guess_chart(
            results, 10, day(1), day(20), period=20, title="Globle",
        )
        self.assertIn(stats_charts.ATTEMPT_COMPACT_SYMBOL * 20, chart)
        self.assertIn("   01      09      17", chart)

    def test_travle_rows_support_zero_hints_and_dnf(self):
        old_path, old_today, path = fresh_db("2026-11-13")
        try:
            add_score("2026-11-08", 1, "Alice", "Travle", "#1", 1, 0.0, "+0")
            add_score("2026-11-09", 1, "Alice", "Travle", "#2", 1, 3.0, "+2 (1 rada)")
            add_score("2026-11-10", 1, "Alice", "Travle", "#3", 0, 999.0, "X")
            add_score("2026-11-11", 1, "Alice", "Travle", "#4", 0, 503.0, "DNF (3 pryč)")
            add_score("2026-11-12", 1, "Alice", "Travle", "#5", 1, 20.0, "+15")
            results = stats_charts.load_attempts(1, "Travle", day(8), day(12))
            self.assertEqual(results, [
                DailyAttempt(day(8), "solved", 0),
                DailyAttempt(day(9), "solved", 2, True),
                DailyAttempt(day(10), "dnf", None),
                DailyAttempt(day(11), "dnf", None),
                missing(day(12)),
            ])
            resolved, variants = stats_charts.resolve_chart_game(
                1, "Travle", day(8), day(11))
            self.assertEqual((resolved, variants), ("Travle", []))
        finally:
            cleanup(old_path, old_today, path)

    def test_travle_chart_shows_zero_and_hint_markers(self):
        results = [
            DailyAttempt(day(1), "solved", 0),
            DailyAttempt(day(2), "solved", 2, True),
            DailyAttempt(day(3), "dnf", None),
            missing(day(4)),
        ]
        chart = stats_charts.render_attempt_chart(
            results, 14, day(1), day(4), title="Travle",
            axis_label="Extra guesses", zero_is_best=True, show_hints=True,
        )
        lines = chart.splitlines()
        self.assertEqual(lines[0], "TRAVLE · 2026-11-01 to 2026-11-04")
        self.assertEqual(lines[3], "14 │     X")
        self.assertEqual(lines[4], "13 │     │")
        self.assertEqual(lines[16], " 1 │   ▄ │")
        self.assertEqual(lines[14], " 3 │   ? │")
        self.assertEqual(lines[15], " 2 │   ▄ │")
        self.assertEqual(lines[17], " 0 │ ▄ ▄ │")

        summary = stats_charts.summarize_attempts(results, unit="extra guesses")
        self.assertEqual(
            summary,
            "Played: 3/4 days\nSolved: 2/3 (67%)\nAvg: 1.0 extra guesses\n"
            "Best: 0 extra guesses",
        )

    def test_metazooa_rows_use_twenty_guess_limit(self):
        old_path, old_today, path = fresh_db("2026-11-13")
        try:
            add_score("2026-11-08", 1, "Alice", "Metazooa", "#1", 1, 1.0, "1 guesses")
            add_score("2026-11-09", 1, "Alice", "Metazooa", "#2", 1, 20.0, "20 guesses")
            add_score("2026-11-10", 1, "Alice", "Metazooa", "#3", 0, 999.0, "DNF")
            add_score("2026-11-11", 1, "Alice", "Metazooa", "#4", 1, 21.0, "21 guesses")
            results = stats_charts.load_guesses(1, "Metazooa", day(8), day(11))
            self.assertEqual(results, [
                solved(day(8), 1),
                solved(day(9), 20),
                dnf(day(10)),
                missing(day(11)),
            ])
            resolved, variants = stats_charts.resolve_chart_game(
                1, "Metazooa", day(8), day(10))
            self.assertEqual((resolved, variants), ("Metazooa", []))

            chart = stats_charts.render_scaled_guess_chart(
                results, 10, day(8), day(11), title="Metazooa", max_attempts=20,
            )
            self.assertIn("20 │   ▄ X", chart)
            self.assertIn("10 │   ▄", chart)
            self.assertIn(" 1 │ ▄ ▄", chart)
            self.assertNotIn("21 │", chart)
        finally:
            cleanup(old_path, old_today, path)

    def test_score_registry_and_metadata(self):
        expected_renderers = {
            "Trivmount": "fixed_score",
            "History in Order": "fixed_score",
            "Majority": "fixed_score",
            "Songspot": "fixed_score",
            "Songless": "fixed_score",
            "Centumth": "scaled_score",
            "Magnitudle": "scaled_score",
            "Maptap": "scaled_score",
            "Redactle": "scaled_score",
            "Roughly (Where from)": "scaled_score",
            "Farflung": "scaled_score",
            "Thursday Thirty": "scaled_score",
        }
        self.assertEqual(
            {name: meta["renderer"]
             for name, meta in games.SCORE_CHART_GAMES.items()},
            expected_renderers,
        )
        self.assertEqual(stats_charts.score_chart_meta("Trivmount")["max_score"], 12)
        self.assertEqual(stats_charts.score_chart_meta("Maptap")["max_score"], None)
        self.assertEqual(stats_charts.score_chart_meta("Redactle")["max_score"], 100)
        self.assertTrue(
            stats_charts.score_chart_meta("Redactle").get("lower_is_better"))
        self.assertTrue(
            stats_charts.score_chart_meta("Redactle").get("cap_outliers"))
        self.assertEqual(stats_charts.score_chart_meta("Songless")["max_score"], 5)
        self.assertTrue(
            stats_charts.score_chart_meta("Songless").get("zero_axis"))
        self.assertEqual(
            stats_charts.score_chart_meta("Roughly (Where from)")["max_score"], 100)
        self.assertTrue(
            stats_charts.score_chart_meta("Roughly (Where from)").get("fixed_axis"))
        self.assertTrue(
            stats_charts.score_chart_meta("Roughly (Where from)").get("estimated"))
        self.assertEqual(
            stats_charts.score_chart_meta("Thursday Thirty")["max_score"], 30)
        self.assertTrue(
            stats_charts.score_chart_meta("Thursday Thirty").get("fixed_axis"))
        self.assertTrue(
            stats_charts.score_chart_meta("Thursday Thirty").get("weekly"))
        self.assertIsNone(games.score_chart_family("Roughly (How big)"))
        self.assertEqual(
            stats_charts.score_chart_meta("Farflung")["max_score"], 500)
        self.assertTrue(
            stats_charts.score_chart_meta("Farflung").get("fixed_axis"))

    def test_score_states_are_validated(self):
        scored(day(1), 0, 12)
        scored(day(1), 12, 12)
        score_dnf(day(1))
        score_missing(day(1))
        DailyScore(day(1), "score", 18, None, 2)
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
        for invalid_hints in (-1, True, "2"):
            with self.subTest(hints=invalid_hints):
                with self.assertRaises(ValueError):
                    DailyScore(day(1), "score", 18, None, invalid_hints)

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
            "11 │     │   ▄\n"
            "10 │ ▄   │   ▄\n"
            " 9 │ ▄   │   ▄\n"
            " 8 │ ▄   │   ▄\n"
            " 7 │ ▄   │   ▄\n"
            " 6 │ ▄   │   ▄\n"
            " 5 │ ▄   │   ▄\n"
            " 4 │ ▄   │   ▄\n"
            " 3 │ ▄   │   ▄\n"
            " 2 │ ▄   │   ▄\n"
            " 1 │ ▄   │   ▄\n"
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
        self.assertEqual(lines[4], " 900 │ ▉   │")
        self.assertEqual(lines[12], " 100 │ ▉   │   ▉")
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

    def test_redactle_uses_raw_guesses_and_caps_outliers(self):
        old_path, old_today, path = fresh_db("2026-11-13")
        try:
            add_score("2026-11-08", 1, "Alice", "Redactle", "#1", 1, 18.0, "18g (1m10s)")
            add_score("2026-11-09", 1, "Alice", "Redactle", "#2", 1, 44.0, "43g, 1h (6m16s)")
            add_score("2026-11-10", 1, "Alice", "Redactle", "#3", 1, 100.0, "100g")
            add_score("2026-11-11", 1, "Alice", "Redactle", "#4", 1, 1000.0, "1000g")
            add_score("2026-11-12", 1, "Alice", "Redactle", "#5", 0, 10055.0, "DNF (55g)")
            results = stats_charts.load_scores(1, "Redactle", day(8), day(12))
            self.assertEqual(results, [
                DailyScore(day(8), "score", 18, None, 0),
                DailyScore(day(9), "score", 43, None, 1),
                DailyScore(day(10), "score", 100, None, 0),
                DailyScore(day(11), "score", 1000, None, 0),
                score_dnf(day(12)),
            ])
            resolved, variants = stats_charts.resolve_chart_game(
                1, "Redactle", day(8), day(12))
            self.assertEqual((resolved, variants), ("Redactle", []))

            chart = stats_charts.render_scaled_score_chart(
                results, 100, day(8), day(12), title="Redactle", unit="guesses",
                lower_is_better=True, cap_outliers=True,
            )
            lines = chart.splitlines()
            self.assertEqual(lines[1], "Guesses (lower = better)")
            self.assertEqual(lines[3], "100 │     ▉ ▉ X")
            self.assertEqual(lines[4], " 90 │     ▉ ▉ │")
            self.assertNotIn("1100 │", chart)
            self.assertNotIn("10000 │", chart)
            self.assertIn(" 10 │ ▉", chart)
            self.assertEqual(
                stats_charts.summarize_scaled_scores(
                    results, unit="guesses", lower_is_better=True,
                    include_hints=True,
                ),
                "Played: 5/5 days\nAvg: 290.2 guesses\nBest: 18 guesses\nHints: 1",
            )
        finally:
            cleanup(old_path, old_today, path)

    def test_songless_uses_solved_songs_and_zero_axis(self):
        old_path, old_today, path = fresh_db("2026-11-12")
        try:
            add_score("2026-11-08", 1, "Alice", "Songless", "#1", 1, -500.0, "5/5 (Roc:1 Pop:2)")
            add_score("2026-11-09", 1, "Alice", "Songless", "#2", 1, 0.0, "0/5")
            add_score("2026-11-10", 1, "Alice", "Songless", "#3", 0, 999.0, "DNF")
            add_score("2026-11-11", 1, "Alice", "Songless", "#4", 1, -600.0, "6/5")
            results = stats_charts.load_scores(1, "Songless", day(8), day(11))
            self.assertEqual(results, [
                scored(day(8), 5, 5),
                scored(day(9), 0, 5),
                score_dnf(day(10)),
                score_missing(day(11)),
            ])
            resolved, variants = stats_charts.resolve_chart_game(
                1, "Songless", day(8), day(11))
            self.assertEqual((resolved, variants), ("Songless", []))

            chart = stats_charts.render_fixed_score_chart(
                results, 5, day(8), day(11), title="Songless", unit="songs",
                zero_axis=True,
            )
            lines = chart.splitlines()
            self.assertEqual(lines[1], "Songs (higher = better)")
            self.assertEqual(lines[3], "5 │ ▄   X")
            self.assertEqual(lines[4], "4 │ ▄   │")
            self.assertEqual(lines[8], "0 │   0 │")
            self.assertEqual(
                stats_charts.summarize_fixed_scores(results, 5),
                "Played: 3/4 days\nAvg: 2.5/5\nBest: 5/5\nPerfect: 1",
            )
        finally:
            cleanup(old_path, old_today, path)

    def test_farflung_uses_distance_and_ignores_rarity_height(self):
        old_path, old_today, path = fresh_db("2026-11-18")
        try:
            add_score("2026-11-15", 1, "Alice", "Farflung", "#49", 1,
                      -230.0002, "230/500 km · best Rare")
            add_score("2026-11-16", 1, "Alice", "Farflung", "#50", 1,
                      -500.0004, "500/500 km · best Farflung")
            add_score("2026-11-17", 1, "Alice", "Farflung", "#51", 1,
                      -120.0, "120/500 km")
            results = stats_charts.load_scores(1, "Farflung", day(15), day(17))
            self.assertEqual(results, [
                scored(day(15), 230, 500),
                scored(day(16), 500, 500),
                scored(day(17), 120, 500),
            ])
            resolved, variants = stats_charts.resolve_chart_game(
                1, "Farflung", day(15), day(17))
            self.assertEqual((resolved, variants), ("Farflung", []))

            chart = stats_charts.render_scaled_score_chart(
                results, 500, day(15), day(17), title="Farflung",
                unit="km", fixed_axis=True,
                axis_label="Distance (higher = better)",
            )
            lines = chart.splitlines()
            self.assertEqual(lines[1], "Distance (higher = better)")
            self.assertIn("500 │   ▉", lines[3])
            self.assertIn("250 │ ▉ ▉", lines[8])
            self.assertIn("100 │ ▉ ▉ ▉", lines[11])
            self.assertNotIn("best Rare", chart)
            self.assertNotIn("best Farflung", chart)
            self.assertEqual(
                stats_charts.summarize_scaled_scores(results, unit="km"),
                "Played: 3/3 days\nAvg: 283.3 km\nBest: 500 km",
            )
        finally:
            cleanup(old_path, old_today, path)

    def test_roughly_where_uses_grid_averages_on_fixed_axis(self):
        old_path, old_today, path = fresh_db("2026-11-13")
        try:
            add_score("2026-11-08", 1, "Alice", "Roughly (Where from)", "#1", 1,
                      -65.0095, "~65% · best 95%")
            add_score("2026-11-09", 1, "Alice", "Roughly (Where from)", "#2", 1,
                      -92.5, "~92.5% · best 80%")
            add_score("2026-11-10", 1, "Alice", "Roughly (Where from)", "#3", 1,
                      -97.0, "Top 3% (97%)")
            add_score("2026-11-11", 1, "Alice", "Roughly (How big)", "#4", 1,
                      -79.0099, "~79% · best 99%")
            add_score("2026-11-12", 1, "Alice", "Roughly (Where from)", "#5", 0,
                      999.0, "DNF")
            results = stats_charts.load_scores(1, "Roughly (Where from)", day(8), day(12))
            self.assertEqual(results, [
                DailyScore(day(8), "score", 65.0, None, None),
                DailyScore(day(9), "score", 92.5, None, None),
                score_missing(day(10)),
                score_missing(day(11)),
                score_dnf(day(12)),
            ])
            resolved, variants = stats_charts.resolve_chart_game(
                1, "Roughly (Where from)", day(8), day(12))
            self.assertEqual((resolved, variants), ("Roughly (Where from)", []))

            chart = stats_charts.render_scaled_score_chart(
                results, 100, day(8), day(12), title="Roughly (Where from)",
                unit="%", fixed_axis=True, estimated=True, axis_suffix="%",
                axis_label="Estimated grid average (higher = better)",
            )
            lines = chart.splitlines()
            self.assertEqual(
                lines[1], "Estimated grid average (higher = better)")
            self.assertEqual(lines[3], "100% │         X")
            self.assertEqual(lines[4], " 90% │   ▉     │")
            self.assertEqual(lines[6], " 70% │ ▉ ▉     │")
            self.assertNotIn("Top 3%", chart)
            self.assertNotIn("~79% · best 99%", chart)
            self.assertEqual(
                stats_charts.summarize_scaled_scores(
                    results, unit="%", estimated=True,
                ),
                "Played: 3/5 days\nAvg: ~78.8%\nBest: ~92.5%",
            )
        finally:
            cleanup(old_path, old_today, path)

    def test_thursday_thirty_uses_last_thursdays(self):
        old_path, old_today, path = fresh_db("2026-11-18")
        try:
            self.assertEqual(
                stats_charts.weekly_thursdays(date(2025, 1, 2), 3),
                [date(2024, 12, 19), date(2024, 12, 26), date(2025, 1, 2)],
            )
            self.assertEqual(
                stats_charts.weekly_thursdays(date(2025, 1, 5), 3),
                [date(2024, 12, 19), date(2024, 12, 26), date(2025, 1, 2)],
            )
            with self.assertRaises(ValueError):
                stats_charts.weekly_thursdays(date(2025, 1, 2), 0)

            add_score("2024-12-26", 1, "Alice", "Thursday Thirty", "#1", 1, -10.0, "10/30 (33%)")
            add_score("2025-01-01", 1, "Alice", "Thursday Thirty", "#3", 1, -5.0, "5/30")
            add_score("2025-01-02", 1, "Alice", "Thursday Thirty", "#4", 1, -30.0, "30/30 (100%)")
            add_score("2025-01-02", 1, "Alice", "Thursday Thirty", "#5", 1, -29.0, "29/30 (97%)")
            dates = stats_charts.weekly_thursdays(date(2025, 1, 2), 3)
            results = stats_charts.load_scores_on_dates(1, "Thursday Thirty", dates)
            self.assertEqual(results, [
                score_missing(dates[0]),
                scored(dates[1], 10, 30),
                scored(dates[2], 29, 30),
            ])
            resolved, variants = stats_charts.resolve_chart_game(
                1, "Thursday Thirty", dates[0], dates[2])
            self.assertEqual((resolved, variants), ("Thursday Thirty", []))

            chart = stats_charts.render_scaled_score_chart(
                results, 30, dates[0], dates[2], title="Thursday Thirty",
                unit="correct", fixed_axis=True, expected_dates=dates,
            )
            lines = chart.splitlines()
            self.assertEqual(lines[1], "Raw correct (higher = better)")
            self.assertIn("30 │     ▉", lines[3])
            self.assertIn(" 9 │   ▉", lines[10])
            self.assertIn(" 3 │   ▉", lines[12])
            self.assertNotIn(" 0 │", chart)
            self.assertEqual(
                stats_charts.summarize_scaled_scores(
                    results, unit="correct", include_perfect=True,
                ),
                "Played: 2/3 days\nAvg: 19.5 correct\nBest: 29 correct\nPerfect: 0",
            )
        finally:
            cleanup(old_path, old_today, path)

    def test_roughly_where_alias_resolves_to_chart_family(self):
        old_path, old_today, path = fresh_db("2026-11-18")
        try:
            add_score("2026-11-17", 1, "Alice", "Roughly (Where)", "#1", 1,
                      -65.0095, "~65% · best 95%")
            self.assertEqual(
                games.score_chart_family("Roughly (Where)"),
                "Roughly (Where from)",
            )
            resolved, variants = stats_charts.resolve_chart_game(
                1, "Roughly (Where from)", day(11), day(18))
            self.assertEqual((resolved, variants), ("Roughly (Where)", []))
            results = stats_charts.load_scores(1, "Roughly (Where)", day(17), day(17))
            self.assertEqual(
                results,
                [DailyScore(day(17), "score", 65.0, None, None)],
            )
        finally:
            cleanup(old_path, old_today, path)

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
