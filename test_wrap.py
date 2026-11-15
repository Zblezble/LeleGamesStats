# -*- coding: utf-8 -*-
"""Focused regressions for daily wrap standings, difficulty scores and quiet days.

Run: python -X utf8 test_wrap.py   (exits 1 on failure)
All database cases use explicit rows in a temporary schema-aware SQLite file.
"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

import config
import db
import discord
import embeds


def fresh_db():
    fd, path = tempfile.mkstemp(prefix="wrap_test_", suffix=".db")
    os.close(fd)
    old_path = config.DB_PATH
    old_prison = config.PRISON_ENABLED
    config.DB_PATH = path
    config.PRISON_ENABLED = False
    db.init_db()
    return old_path, old_prison, path


def cleanup(old_path, old_prison, path):
    config.DB_PATH = old_path
    config.PRISON_ENABLED = old_prison
    try:
        os.remove(path)
    except OSError:
        pass


def add_score(board_date, user_id, user_name, puzzle_id, rank_score):
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.execute(
            "INSERT INTO scores (board_date, user_id, user_name, game, puzzle_id,"
            " solved, rank_score, display_score) VALUES (?, ?, ?, 'Wordle', ?, 1, ?, ?)",
            (board_date, user_id, user_name, puzzle_id, rank_score, f"{rank_score}/6"),
        )
        conn.commit()


def field(embed, name):
    matches = [item.value for item in embed.fields if item.name == name]
    assert len(matches) == 1, (name, [item.name for item in embed.fields])
    value = matches[0]
    assert value is not None
    return value


def assert_practice_day(embed, expected_names):
    names = [item.name for item in embed.fields]
    assert "Practice day" in names, names
    assert "Final standings" not in names and "\u200b" not in names, names
    assert embed.fields[-1].name == "Practice day"
    value = field(embed, "Practice day")
    assert value.startswith("No points awarded."), value
    for name in expected_names:
        safe_name = discord.utils.escape_mentions(discord.utils.escape_markdown(name))
        assert safe_name in value, (name, value)


def test_ordinary_standings_preserve_order_and_unfiltered_comment():
    old_path, old_prison, path = fresh_db()
    original_comment = embeds._wrap_comment
    calls = []

    def recording_comment(board_date, names, standings):
        calls.append((board_date, dict(names), list(standings)))
        return original_comment(board_date, names, standings)

    day = "2025-03-03"
    try:
        add_score(day, 1, "Alice", "#1", 1)
        add_score(day, 2, "Bob", "#1", 2)
        add_score(day, 3, "Cara", "#1", 3)
        add_score(day, 4, "Dan", "#2", 1)
        add_score(day, 5, "Erin", "#2", 2)

        expected_names = {1: "Alice", 2: "Bob", 3: "Cara", 4: "Dan", 5: "Erin"}
        expected_standings = [(1, 3), (4, 3), (2, 2), (5, 2), (3, 1)]
        embeds._wrap_comment = recording_comment
        embed = embeds.build_wrap_embed(day)
        assert embed is not None
        assert calls == [(day, expected_names, expected_standings)], calls
        assert embed.title == "🏆 Yesterday's wrap · Mon 3 Mar"
        assert field(embed, "Final standings") == (
            "Alice `3` · Dan `3` · Bob `2` · Erin `2` · Cara `1`"
        )
        assert not {"Daily reels", "Full names", "Bonus reel"}.intersection(
            item.name for item in embed.fields
        )

        # One unchanged date-seeded comment, immediately after the standings.
        assert embed.fields[-1].name == "\u200b"
        expected_comment = original_comment(day, expected_names, expected_standings)
        assert embed.fields[-1].value == expected_comment
        assert sum(item.name == "\u200b" for item in embed.fields) == 1
    finally:
        embeds._wrap_comment = original_comment
        cleanup(old_path, old_prison, path)


def test_tied_totals_keep_existing_order_and_points():
    old_path, old_prison, path = fresh_db()
    tied_day = "2025-03-04"
    identical_day = "2025-03-05"
    try:
        # Alice and Bob tie at five while retaining the established name ordering.
        for puzzle_id, ranks in (
            ("#10", {1: 1, 2: 2, 3: 3}),
            ("#11", {1: 2, 2: 1, 3: 3}),
        ):
            for uid, rank_score in ranks.items():
                add_score(tied_day, uid, {1: "Alice", 2: "Bob", 3: "Cara"}[uid],
                          puzzle_id, rank_score)
        points, _names = embeds.compute_daily_points(tied_day)
        assert points == {1: 5, 2: 5, 3: 2}, points
        tied = embeds.build_wrap_embed(tied_day)
        assert tied is not None
        assert field(tied, "Final standings") == "Alice `5` · Bob `5` · Cara `2`"

        # Both games together give every player exactly three points.
        names = {1: "Alice", 2: "Bob", 3: "Cara", 4: "Dan"}
        for puzzle_id, ranks in (
            ("#20", {1: 1, 2: 2, 3: 3, 4: 4}),
            ("#21", {1: 4, 2: 3, 3: 2, 4: 1}),
        ):
            for uid, rank_score in ranks.items():
                add_score(identical_day, uid, names[uid], puzzle_id, rank_score)
        points, _names = embeds.compute_daily_points(identical_day)
        assert points == {1: 3, 2: 3, 3: 3, 4: 3}, points
        identical = embeds.build_wrap_embed(identical_day)
        assert identical is not None
        assert field(identical, "Final standings") == (
            "Alice `3` · Bob `3` · Cara `3` · Dan `3`"
        )
    finally:
        cleanup(old_path, old_prison, path)


def test_final_standings_keep_full_names_without_reel_fallbacks():
    old_path, old_prison, path = fresh_db()
    day = "2025-03-06"
    long_name = "Alexandria with a name too long for the old reel"
    tick_name = "Tick```Name"
    try:
        add_score(day, 1, long_name, "#30", 1)
        add_score(day, 2, tick_name, "#30", 2)
        add_score(day, 3, "Cara", "#30", 3)
        embed = embeds.build_wrap_embed(day)
        assert embed is not None
        standings = field(embed, "Final standings")
        assert f"{long_name} `3`" in standings
        assert f"{tick_name} `2`" in standings
        assert "Cara `1`" in standings
        assert "Full names" not in {item.name for item in embed.fields}
        assert embed.fields[-1].name == "\u200b"
    finally:
        cleanup(old_path, old_prison, path)


def test_solo_and_multiplayer_no_point_days_are_quiet():
    old_path, old_prison, path = fresh_db()
    solo_day = "2025-03-07"
    multiplayer_day = "2025-03-08"
    try:
        add_score(solo_day, 1, "Alice", "#40", 2)
        solo = embeds.build_wrap_embed(solo_day)
        assert solo is not None
        assert_practice_day(solo, ["Alice"])

        # Two real players can still have no contest when their games were solo.
        add_score(multiplayer_day, 1, "Alice", "#41", 2)
        add_score(multiplayer_day, 2, "Bob", "#42", 2)
        multiplayer = embeds.build_wrap_embed(multiplayer_day)
        assert multiplayer is not None
        assert_practice_day(multiplayer, ["Alice", "Bob"])
    finally:
        cleanup(old_path, old_prison, path)


def test_all_zero_board_has_no_standings_or_roast():
    old_path, old_prison, path = fresh_db()
    day = "2025-03-09"
    config.PRISON_ENABLED = True
    try:
        add_score(day, 1, "Alice", "#50", 1)
        add_score(day, 2, "Bob", "#50", 2)
        db.add_prisoner(day, 1, "Alice", "Wordle")
        db.add_prisoner(day, 2, "Bob", "Wordle")
        points, _names = embeds.compute_daily_points(day)
        assert points == {1: 0.0, 2: 0.0}, points
        embed = embeds.build_wrap_embed(day)
        assert embed is not None
        assert_practice_day(embed, ["Alice", "Bob"])
    finally:
        cleanup(old_path, old_prison, path)


def test_difficulty_comments_include_selected_daily_and_weekly_medians():
    old_path, old_prison, path = fresh_db()
    old_today = config.today_str
    day = "2025-03-10"
    config.today_str = lambda: "2025-03-11"
    try:
        # Wordle medians: (1 + 5/6) / 2 and (2/6 + 1/6) / 2.
        add_score(day, 1, "Alice", "#60", 1)
        add_score(day, 2, "Bob", "#60", 2)
        add_score(day, 1, "Alice", "#61", 5)
        add_score(day, 2, "Bob", "#61", 6)

        daily = embeds.build_wrap_embed(day)
        weekly = embeds.build_weekly_embed(days=7)
        assert daily is not None and weekly is not None
        for verdict in (field(daily, "Game difficulty"), field(weekly, "Game difficulty")):
            lines = verdict.splitlines()
            assert len(lines) == 4, lines
            assert lines[0].startswith("Easiest: **Wordle**"), lines
            assert lines[1] == "Median score: 91.7%", lines
            assert lines[2].startswith("Hardest: **Wordle**"), lines
            assert lines[3] == "Median score: 25.0%", lines
    finally:
        config.today_str = old_today
        cleanup(old_path, old_prison, path)


def test_regionle_named_modes_use_the_regionle_scale():
    expected = 1 - (4 - 1) / 7
    base = embeds._performance_fraction("Regionle", 1, 4, "4/7")
    named_mode = embeds._performance_fraction("Regionle (US States)", 1, 4, "4/7")
    assert base == expected
    assert named_mode == expected
    assert named_mode != (7 - 4) / 6  # Not the generic six-try fallback.


if __name__ == "__main__":
    test_ordinary_standings_preserve_order_and_unfiltered_comment()
    test_tied_totals_keep_existing_order_and_points()
    test_final_standings_keep_full_names_without_reel_fallbacks()
    test_solo_and_multiplayer_no_point_days_are_quiet()
    test_all_zero_board_has_no_standings_or_roast()
    test_difficulty_comments_include_selected_daily_and_weekly_medians()
    test_regionle_named_modes_use_the_regionle_scale()
    print("All wrap tests passed.")
