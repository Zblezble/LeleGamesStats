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
from stats_charts import DailyAttempt


def day(offset_from_november=1, month=11, year=2026):
    return date(year, month, offset_from_november)


def solved(day_value, attempts):
    return DailyAttempt(day_value, "solved", attempts)


def dnf(day_value):
    return DailyAttempt(day_value, "dnf", None)


def missing(day_value):
    return DailyAttempt(day_value, "missing", None)


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
            "6 │     X   █\n"
            "5 │\n"
            "4 │\n"
            "3 │   █\n"
            "2 │\n"
            "1 │ █\n"
            "  └──────────\n"
            "   05      09\n"
            "\n"
            "█ = attempt · X = DNF · blank = no result"
        )
        self.assertEqual(actual, expected)

    def test_solved_maximum_is_a_full_bar_not_dnf(self):
        results = [solved(day(1), 6), dnf(day(2))]
        chart = stats_charts.render_attempt_chart(results, 6, day(1), day(2))
        top_row = chart.splitlines()[3]
        self.assertEqual(top_row, "6 │ █ X")

    def test_all_missing_and_all_dnf_are_valid(self):
        all_missing = [missing(day(index)) for index in range(1, 4)]
        chart = stats_charts.render_attempt_chart(all_missing, 6, day(1), day(3))
        attempt_rows = chart.splitlines()[3:9]
        self.assertTrue(all("█" not in row and " X" not in row for row in attempt_rows),
                        attempt_rows)
        self.assertIn("blank = no result", chart)
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

    def test_multiple_variants_require_an_exact_choice(self):
        old_path, old_today, path = fresh_db("2026-11-09")
        try:
            add_score("2026-11-08", 1, "Alice", "Chessle (Medium)", "#1", 1, 2.0, "2/6")
            add_score("2026-11-09", 1, "Alice", "Chessle (Hard)", "#2", 1, 3.0, "3/6")
            resolved, variants = stats_charts.resolve_chart_game(
                1, "Chessle", day(5), day(9))
            self.assertIsNone(resolved)
            self.assertEqual(variants, ["Chessle (Hard)", "Chessle (Medium)"])
            resolved, variants = stats_charts.resolve_chart_game(
                1, "Chessle (Medium)", day(5), day(9))
            self.assertEqual((resolved, variants), ("Chessle (Medium)", []))

            # An explicit missing variant must not be replaced by another variant.
            resolved, variants = stats_charts.resolve_chart_game(
                1, "Chessle (Expert)", day(5), day(9))
            self.assertEqual((resolved, variants), (None, []))
        finally:
            cleanup(old_path, old_today, path)

    def test_unsupported_game_is_not_resolved(self):
        old_path, old_today, path = fresh_db("2026-11-09")
        try:
            add_score("2026-11-08", 1, "Alice", "Songless", "#1", 1, -100.0, "2/2 (Roc:1 Pop:2)")
            add_score("2026-11-08", 1, "Alice", "Trivmount", "#2", 1, -100.0, "12/12")
            self.assertEqual(
                stats_charts.resolve_chart_game(1, "Songless", day(5), day(9)),
                (None, []),
            )
            self.assertEqual(
                stats_charts.resolve_chart_game(1, "Trivmount", day(5), day(9)),
                (None, []),
            )
        finally:
            cleanup(old_path, old_today, path)

    def test_autocomplete_offers_only_fixed_attempt_games(self):
        old_path, old_today, path = fresh_db("2026-11-09")
        try:
            add_score("2026-11-08", 1, "Alice", "Songless", "#1", 1, -100.0, "2/2 (Roc:1 Pop:2)")
            add_score("2026-11-08", 1, "Alice", "Trivmount", "#2", 1, -100.0, "12/12")
            choices = asyncio.run(commands._chart_game_autocomplete(None, ""))
            values = {choice.value for choice in choices}
            self.assertIn("Worldle", values)
            self.assertIn("Chessle", values)
            self.assertNotIn("Songless", values)
            self.assertNotIn("Trivmount", values)
        finally:
            cleanup(old_path, old_today, path)

    def test_wordle_is_chartable_even_when_disabled_for_ingest(self):
        self.assertEqual(games.fixed_attempt_family("Wordle"), "Wordle")
        self.assertEqual(stats_charts.max_attempts_for("Wordle"), 6)

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
        results = [solved(day(index), (index % 6) + 1) for index in range(1, 21)]
        chart = stats_charts.render_attempt_chart(results, 6, day(1), day(20))
        self.assertLessEqual(max(len(line) for line in chart.splitlines()), 44)
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

    def test_chart_periods_use_mobile_friendly_defaults(self):
        signature = inspect.signature(commands.stats)
        self.assertEqual(signature.parameters["period"].default, 10)
        choices = cast(Any, commands.stats).__discord_app_commands_param_choices__.get("period", [])
        self.assertEqual([choice.value for choice in choices], [10, 20])

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
                interaction, cast(Any, FakeUser()), "Worldle", 10))
            self.assertEqual(len(interaction.response.calls), 1)
            self.assertTrue(interaction.response.calls[0]["ephemeral"])
            self.assertEqual(
                interaction.response.calls[0]["embed"].fields[0].name,
                "Last 10 days",
            )

            public_interaction = cast(Any, FakeInteraction())
            asyncio.run(commands._send_game_chart(
                public_interaction, cast(Any, FakeUser()), "Worldle", 20, public=True))
            self.assertEqual(len(public_interaction.response.calls), 1)
            self.assertFalse(public_interaction.response.calls[0]["ephemeral"])
            self.assertEqual(
                public_interaction.response.calls[0]["embed"].fields[0].name,
                "Last 20 days",
            )
        finally:
            cleanup(old_path, old_today, path)


if __name__ == "__main__":
    unittest.main()
