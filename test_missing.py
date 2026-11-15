# -*- coding: utf-8 -*-
"""Focused regressions for /missing checklist partitioning.

Run: python -X utf8 test_missing.py   (exits 1 on failure)
Every case uses a throwaway SQLite file and temporarily injected game metadata,
so the suite never touches scores.db and does not depend on the real registry
(including another lane's Maptap or parser changes).
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

DATE = "2025-06-10"  # fixed Tuesday, far from the real wall-clock "today"
VALUE_LIMIT = 1024
EMBED_LIMIT = 6000


def _game(icon, url):
    return {"icon": icon, "desc": "daily puzzle", "url": url}


# A small but realistic registry: the new Maptap entry plus two familiar games.
REAL_GAMES = {
    "Maptap": _game("🗺️", "https://www.maptap.gg/"),
    "Wordle": _game("🟩", "https://www.nytimes.com/games/wordle"),
    "Worldle": _game("🗺️", "https://worldle.teuteuf.fr"),
}


def make_games(count):
    """Realistic game metadata, padded to `count` distinct daily-puzzle entries."""
    games = dict(REAL_GAMES)
    index = 1
    while len(games) < count:
        games[f"Daily Puzzle {index:02d}"] = _game(
            "🧩", f"https://puzzles.example/daily/{index:02d}"
        )
        index += 1
    return games


def install_fixture(games):
    """Temporarily replace the checklist registry/scheduling; return prior values."""
    old_meta = embeds.ACTIVE_GAME_META
    old_available = embeds.game_available_on
    embeds.ACTIVE_GAME_META = dict(games)
    embeds.game_available_on = lambda _name, _weekday: True
    return old_meta, old_available


def restore_fixture(saved):
    embeds.ACTIVE_GAME_META, embeds.game_available_on = saved


def fresh_db():
    fd, path = tempfile.mkstemp(prefix="missing_test_", suffix=".db")
    os.close(fd)
    old_path = config.DB_PATH
    old_today = config.today_str
    config.DB_PATH = path
    config.today_str = lambda: DATE
    db.init_db()
    return old_path, old_today, path


def cleanup(old_path, old_today, path):
    config.DB_PATH = old_path
    config.today_str = old_today
    try:
        os.remove(path)
    except OSError:
        pass


def add_played(game, display_score, user_id=1):
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.execute(
            "INSERT INTO scores (board_date, user_id, user_name, game, puzzle_id,"
            " solved, rank_score, display_score) VALUES (?, ?, 'Tester', ?, '#1', 1, 1.0, ?)",
            (DATE, user_id, game, display_score),
        )
        conn.commit()


def to_play_lines(games, played):
    return [
        f"{meta['icon']} **{name}** · [play]({meta['url']})"
        for name, meta in games.items()
        if name not in played
    ]


def done_lines(games, played):
    return [
        f"{games[name]['icon']} **{name}** · {played[name]}"
        for name in games
        if name in played
    ]


def field_name(item):
    assert item.name is not None
    return item.name


def field_value(item):
    assert item.value is not None
    return item.value


def section_fields(embed, base_name):
    """Fields belonging to one checklist section, including its continuations."""
    pattern = re.compile(rf"^{re.escape(base_name)}(?: \((\d+)/(\d+)\))?$")
    return [item for item in embed.fields if pattern.match(field_name(item))]


def assert_discord_limits(embed):
    assert isinstance(embed, discord.Embed), type(embed)
    assert len(embed.fields) <= 25, len(embed.fields)
    for item in embed.fields:
        assert item.value is not None, item.name
        assert len(item.value) <= VALUE_LIMIT, (item.name, len(item.value))
    assert len(embed) <= EMBED_LIMIT, len(embed)


def assert_single_field(embed, name, expected_lines):
    matches = [item for item in embed.fields if item.name == name]
    assert len(matches) == 1, [item.name for item in embed.fields]
    assert matches[0].value == "\n".join(expected_lines)


def assert_partitioned(fields, base_name, expected_lines):
    """Continuation fields reconstruct the original lines exactly, in order."""
    assert len(fields) >= 2, [item.name for item in fields]
    total = len(fields)
    for index, item in enumerate(fields, 1):
        assert item.name == f"{base_name} ({index}/{total})", item.name
        assert len(item.value) <= VALUE_LIMIT, (item.name, len(item.value))
    reconstructed = "\n".join(item.value for item in fields)
    assert reconstructed.split("\n") == expected_lines


def test_short_checklist_keeps_original_single_fields():
    old_path, old_today, path = fresh_db()
    saved = install_fixture(make_games(3))
    played = {"Wordle": "3/6"}
    try:
        add_played("Wordle", "3/6")
        embed = embeds.build_missing_embed(1)
        assert_discord_limits(embed)
        assert [item.name for item in embed.fields] == ["To play · 2", "Done · 1"]
        assert_single_field(embed, "To play · 2", to_play_lines(REAL_GAMES, played))
        assert_single_field(embed, "Done · 1", done_lines(REAL_GAMES, played))
        assert embed.description is None
    finally:
        restore_fixture(saved)
        cleanup(old_path, old_today, path)


def test_empty_and_complete_states_stay_honest():
    old_path, old_today, path = fresh_db()
    games = make_games(3)
    saved = install_fixture(games)
    try:
        nothing = embeds.build_missing_embed(1)
        assert nothing.description == "Nothing logged yet. Post your results in this channel."
        assert [field_name(item) for item in nothing.fields] == ["To play · 3"]
        assert not any(field_name(item).startswith("Done") for item in nothing.fields)
        assert_discord_limits(nothing)

        for name in games:
            add_played(name, "1/6")
        complete = embeds.build_missing_embed(1)
        assert complete.description == "All 3 games played today. See you tomorrow."
        assert [field_name(item) for item in complete.fields] == ["Done · 3"]
        assert not any(field_name(item).startswith("To play") for item in complete.fields)
        assert_discord_limits(complete)
    finally:
        restore_fixture(saved)
        cleanup(old_path, old_today, path)


def test_long_to_play_list_partitions_and_keeps_maptap():
    """Maptap-scale overflow: a full registry no longer truncates the checklist."""
    old_path, old_today, path = fresh_db()
    games = make_games(23)
    saved = install_fixture(games)
    played = {"Wordle": "3/6"}
    try:
        add_played("Wordle", "3/6")
        expected = to_play_lines(games, played)
        assert len("\n".join(expected)) > VALUE_LIMIT, "fixture must overflow one field"

        embed = embeds.build_missing_embed(1)
        assert_discord_limits(embed)

        to_fields = section_fields(embed, "To play · 22")
        assert_partitioned(to_fields, "To play · 22", expected)
        assert [item.name for item in embed.fields] == [
            "To play · 22 (1/2)",
            "To play · 22 (2/2)",
            "Done · 1",
        ]

        joined = "\n".join(field_value(item) for item in to_fields)
        assert joined.count("**Maptap**") == 1
        assert joined.count("https://www.maptap.gg/") == 1
        assert "…" not in joined  # no clipping on lines that fit normally

        assert_single_field(embed, "Done · 1", done_lines(games, played))
        assert all("Done" not in field_name(item) for item in to_fields)
    finally:
        restore_fixture(saved)
        cleanup(old_path, old_today, path)


def test_long_done_list_partitions_and_keeps_scores():
    old_path, old_today, path = fresh_db()
    games = make_games(44)
    saved = install_fixture(games)
    scores = ["3/6", "DNF", "18/30", "199/500", "6/6", "1g12s", "4/7", "863", "12/12", "5/6"]
    played = {name: scores[index % len(scores)] for index, name in enumerate(games)}
    played["Maptap"] = "863"  # the reported Maptap final score
    try:
        for name, score in played.items():
            add_played(name, score)
        expected = done_lines(games, played)
        assert len("\n".join(expected)) > VALUE_LIMIT, "fixture must overflow one field"

        embed = embeds.build_missing_embed(1)
        assert_discord_limits(embed)
        assert embed.description == "All 44 games played today. See you tomorrow."

        done_fields = section_fields(embed, "Done · 44")
        assert_partitioned(done_fields, "Done · 44", expected)
        assert not any(field_name(item).startswith("To play") for item in embed.fields)

        joined = "\n".join(field_value(item) for item in done_fields)
        assert joined.count("**Maptap** · 863") == 1
        assert "…" not in joined
    finally:
        restore_fixture(saved)
        cleanup(old_path, old_today, path)


if __name__ == "__main__":
    test_short_checklist_keeps_original_single_fields()
    test_empty_and_complete_states_stay_honest()
    test_long_to_play_list_partitions_and_keeps_maptap()
    test_long_done_list_partitions_and_keeps_scores()
    print("All missing-checklist tests passed.")
