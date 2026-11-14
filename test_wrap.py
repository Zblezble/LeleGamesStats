# -*- coding: utf-8 -*-
"""Focused regressions for the static daily wrap and its locked-result reels.

Run: python -X utf8 test_wrap.py   (exits 1 on failure)
All database cases use explicit rows in a temporary schema-aware SQLite file.
"""
import os
import re
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


def reel_lines(value):
    lines = value.splitlines()
    assert lines[0] == "```text" and lines[-1] == "```", value
    body = lines[1:-1]
    assert body and "RESULTS LOCKED" in body[1], body
    assert all("`" not in line for line in body), body
    # Rough width algebra on generated text, including every actual result row.
    assert all(len(line) <= 42 for line in body), [len(line) for line in body]
    assert len({len(line) for line in body}) == 1, [len(line) for line in body]
    return body


def reel_results(value):
    results = []
    for line in reel_lines(value):
        match = re.fullmatch(r"\[#\s*(\d+)\] \[(.*)\] \[([^]]+) pts\]", line)
        if match:
            results.append((int(match.group(1)), match.group(2).strip(), match.group(3)))
    assert results, value
    return results


def assert_practice_day(embed, expected_names):
    names = [item.name for item in embed.fields]
    assert "Practice day" in names, names
    assert "Daily reels" not in names and "Bonus reel" not in names, names
    value = field(embed, "Practice day")
    assert value.startswith("No points awarded."), value
    for name in expected_names:
        safe_name = discord.utils.escape_mentions(discord.utils.escape_markdown(name))
        assert safe_name in value, (name, value)
    combined = "\n".join(item.value or "" for item in embed.fields)
    assert "RESULTS LOCKED" not in combined and "```" not in combined, combined


def test_ordinary_reels_preserve_standings_and_unfiltered_comment():
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
        assert reel_results(field(embed, "Daily reels")) == [
            (1, "Alice", "3"),
            (1, "Dan", "3"),
            (3, "Bob", "2"),
            (3, "Erin", "2"),
            (5, "Cara", "1"),
        ]

        # One unchanged date-seeded comment, after all standings and fallbacks.
        assert embed.fields[-1].name == "Bonus reel"
        expected_comment = original_comment(day, expected_names, expected_standings)
        assert field(embed, "Bonus reel") == expected_comment
        assert sum(item.name == "Bonus reel" for item in embed.fields) == 1
    finally:
        embeds._wrap_comment = original_comment
        cleanup(old_path, old_prison, path)


def test_tied_placements_include_fully_identical_totals():
    old_path, old_prison, path = fresh_db()
    tied_day = "2025-03-04"
    identical_day = "2025-03-05"
    try:
        # Alice and Bob tie at five; Cara follows at two with competition rank 3.
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
        assert reel_results(field(tied, "Daily reels")) == [
            (1, "Alice", "5"), (1, "Bob", "5"), (3, "Cara", "2")
        ]

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
        assert reel_results(field(identical, "Daily reels")) == [
            (1, "Alice", "3"), (1, "Bob", "3"), (1, "Cara", "3"), (1, "Dan", "3")
        ]
    finally:
        cleanup(old_path, old_prison, path)


def test_long_and_backtick_names_are_safe_with_full_name_fallback():
    old_path, old_prison, path = fresh_db()
    day = "2025-03-06"
    long_name = "Alexandria with a name far too long for the reel"
    tick_name = "Tick```Name"
    try:
        add_score(day, 1, long_name, "#30", 1)
        add_score(day, 2, tick_name, "#30", 2)
        add_score(day, 3, "Cara", "#30", 3)
        embed = embeds.build_wrap_embed(day)
        assert embed is not None
        body = reel_lines(field(embed, "Daily reels"))
        visual = "\n".join(body)
        assert long_name not in visual and tick_name not in visual
        assert "Tick'''Name" in visual and "Cara" in visual

        fallback = field(embed, "Full names").splitlines()
        assert len(fallback) == 2, fallback
        safe_long = discord.utils.escape_markdown(long_name)
        safe_tick = discord.utils.escape_markdown(tick_name)
        assert fallback[0].startswith("#1 ") and safe_long in fallback[0]
        assert "3 pts" in fallback[0]
        assert fallback[1].startswith("#2 ") and safe_tick in fallback[1]
        assert "2 pts" in fallback[1]
        assert embed.fields[-1].name == "Bonus reel"
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


def test_all_zero_board_has_no_reel_or_roast():
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


if __name__ == "__main__":
    test_ordinary_reels_preserve_standings_and_unfiltered_comment()
    test_tied_placements_include_fully_identical_totals()
    test_long_and_backtick_names_are_safe_with_full_name_fallback()
    test_solo_and_multiplayer_no_point_days_are_quiet()
    test_all_zero_board_has_no_reel_or_roast()
    print("All wrap tests passed.")
