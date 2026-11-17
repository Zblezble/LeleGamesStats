# -*- coding: utf-8 -*-
"""Focused regressions for daily wrap standings, difficulty scores and quiet days.

Run: python -X utf8 test_wrap.py   (exits 1 on failure)
All database cases use explicit rows in a temporary schema-aware SQLite file.
"""
import os
import random
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
            "Alice `3` pts · `1` game · `3.0` pts/game\n"
            "Dan `3` pts · `1` game · `3.0` pts/game\n"
            "Bob `2` pts · `1` game · `2.0` pts/game\n"
            "Erin `2` pts · `1` game · `2.0` pts/game\n"
            "Cara `1` pts · `1` game · `1.0` pts/game"
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


def test_standings_lines_count_distinct_results_and_handle_zero_games():
    pan = (1, "Pan Security Evangelist", 1, 1.0, "3/6", None)
    grouped = {}
    for index in range(15):
        # Distinct native puzzles count separately; a repeated row in one group does not.
        grouped[("Redactle", f"#{index + 1}")] = [pan, pan] if index == 0 else [pan]
    grouped[("Wordle", "#dnf")] = [(2, "Attempted", 0, 999.0, "DNF", None)]

    lines = embeds._wrap_standings_lines(
        [(1, 42), (2, 3), (3, 0.0)],
        {1: "Pan Security Evangelist", 2: "Attempted", 3: "Missing"},
        grouped,
    )
    assert lines == [
        "Pan Security Evangelist `42` pts · `15` games · `2.8` pts/game",
        "Attempted `3` pts · `1` game · `3.0` pts/game",
        "Missing `0.0` pts · `0` games · `0.0` pts/game",
    ]


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
        assert field(tied, "Final standings") == (
            "Alice `5` pts · `2` games · `2.5` pts/game\n"
            "Bob `5` pts · `2` games · `2.5` pts/game\n"
            "Cara `2` pts · `2` games · `1.0` pts/game"
        )

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
            "Alice `3` pts · `2` games · `1.5` pts/game\n"
            "Bob `3` pts · `2` games · `1.5` pts/game\n"
            "Cara `3` pts · `2` games · `1.5` pts/game\n"
            "Dan `3` pts · `2` games · `1.5` pts/game"
        )
    finally:
        cleanup(old_path, old_prison, path)


def test_standings_order_stays_by_total_points_not_average():
    old_path, old_prison, path = fresh_db()
    day = "2025-03-11"
    try:
        add_score(day, 2, "Bob", "#31", 1)
        add_score(day, 1, "Alice", "#31", 2)
        add_score(day, 3, "Cara", "#31", 3)
        add_score(day, 3, "Cara", "#32", 1)
        add_score(day, 1, "Alice", "#32", 2)

        points, _names = embeds.compute_daily_points(day)
        assert points == {2: 3, 1: 4, 3: 4}, points
        embed = embeds.build_wrap_embed(day)
        assert embed is not None
        # Bob has the best average, but remains below both four-point players.
        assert field(embed, "Final standings") == (
            "Alice `4` pts · `2` games · `2.0` pts/game\n"
            "Cara `4` pts · `2` games · `2.0` pts/game\n"
            "Bob `3` pts · `1` game · `3.0` pts/game"
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
        safe_long = discord.utils.escape_markdown(long_name)
        safe_tick = discord.utils.escape_markdown(tick_name)
        assert f"{safe_long} `3` pts · `1` game · `3.0` pts/game" in standings
        assert f"{safe_tick} `2` pts · `1` game · `2.0` pts/game" in standings
        assert "Cara `1` pts · `1` game · `1.0` pts/game" in standings
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


def test_zero_point_player_in_a_real_contest_shows_zero_average():
    old_path, old_prison, path = fresh_db()
    day = "2025-03-12"
    config.PRISON_ENABLED = True
    try:
        add_score(day, 1, "Alice", "#51", 1)
        add_score(day, 2, "Bob", "#51", 2)
        db.add_prisoner(day, 1, "Alice", "Wordle")
        embed = embeds.build_wrap_embed(day)
        assert embed is not None
        assert field(embed, "Final standings") == (
            "Bob `2` pts · `1` game · `2.0` pts/game\n"
            "Alice `0.0` pts · `1` game · `0.0` pts/game"
        )
    finally:
        cleanup(old_path, old_prison, path)


def test_difficulty_fields_show_native_daily_and_weekly_medians():
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
        expected = (
            "Easiest: **Wordle** · median `1.5/6 guesses` · normalized `91.7%`\n"
            "Hardest: **Wordle** · median `5.5/6 guesses` · normalized `25.0%`"
        )
        for verdict in (field(daily, "Game difficulty"), field(weekly, "Game difficulty")):
            assert verdict == expected, verdict
            assert len(verdict) <= 1024
            for removed in (
                "free points", "figured this one out", "confidence booster", "warm welcome",
                "silence after the answers", "tiny derailment", "strengthen their stance", "lunch money",
            ):
                assert removed not in verdict
    finally:
        config.today_str = old_today
        cleanup(old_path, old_prison, path)


def test_native_difficulty_formats_score_ratios_placements_and_regionle():
    def result(rank_score, display_score, solved=1):
        return (1, "Player", solved, rank_score, display_score, None)

    wordle = [result(1, "1/6"), result(1, "1/6")]
    assert embeds._native_median("Wordle", wordle, 1.0) == "1/6 guesses"
    assert embeds._performance_fraction("Wordle", 1, 1, "1/6") > embeds._performance_fraction(
        "Wordle", 1, 5, "5/6"
    )  # Fewer guesses is better.

    centumth = [result(-250, "250/490"), result(-250, "250/490")]
    centumth_score = embeds._median([
        embeds._performance_fraction("Centumth", 1, rank, display)
        for _uid, _name, _solved, rank, display, _url in centumth
    ])
    assert embeds._performance_fraction("Centumth", 1, -250, "250/490") > embeds._performance_fraction(
        "Centumth", 1, -100, "100/490"
    )  # More correct answers is better, completely unlike guess-count ordering.
    assert embeds._difficulty_summary(
        "2025-03-14", "hardest", [("Centumth", centumth_score, centumth)]
    ) == "Hardest: **Centumth** · median `250/490` · normalized `51.0%`"

    history = [result(-4, "4/6", 0), result(-2, "2/6", 0)]
    assert embeds._native_median("History in Order", history, 0.5) == "3/6 placements"

    regionle = [result(3, "3/7"), result(5, "5/7")]
    assert embeds._native_median("Regionle (US States)", regionle, 4 / 7) == "4/7 guesses"
    assert embeds._difficulty_summary(
        "2025-03-14", "easiest", [("Regionle (US States)", 4 / 7, regionle)]
    ) == "Easiest: **Regionle (US States)** · median `4/7 guesses` · normalized `57.1%`"

    maptap = [result(-1234, "1234"), result(-1234, "1234")]
    assert embeds._native_median("Maptap", maptap, 0.75) is None
    assert embeds._difficulty_summary(
        "2025-03-14", "hardest", [("Maptap", 0.75, maptap)]
    ) == "Hardest: **Maptap** · normalized `75.0%`"
    assert embeds._native_median(
        "Wordle", [result(1, "1/6"), result(1, "1/8")], 1.0
    ) is None  # Mixed puzzle contexts are not safe to combine into a native fraction.


def test_regionle_named_modes_use_the_regionle_scale():
    expected = 1 - (4 - 1) / 7
    base = embeds._performance_fraction("Regionle", 1, 4, "4/7")
    named_mode = embeds._performance_fraction("Regionle (US States)", 1, 4, "4/7")
    assert base == expected
    assert named_mode == expected
    assert named_mode != (7 - 4) / 6  # Not the generic six-try fallback.


def test_long_standings_partition_complete_player_lines():
    old_path, old_prison, path = fresh_db()
    day = "2025-03-13"
    players = []
    try:
        for pair in range(12):
            for offset, (points, rank_score) in enumerate(((3, 1), (2, 2))):
                uid = pair * 2 + offset + 1
                name = f"Player {uid:02d} with a deliberately long display name for wrap fields"
                players.append((name, points))
                add_score(day, uid, name, f"#70-{pair}", rank_score)

        embed = embeds.build_wrap_embed(day)
        assert embed is not None
        standing_fields = [
            item for item in embed.fields
            if item.name == "Final standings" or (item.name or "").startswith("Final standings (")
        ]
        assert len(standing_fields) > 1
        assert [item.name for item in standing_fields] == [
            f"Final standings ({index}/{len(standing_fields)})"
            for index in range(1, len(standing_fields) + 1)
        ]
        assert all(len(item.value or "") <= 1024 for item in standing_fields)
        assert len(embed) <= 6000

        actual_lines = [
            line for item in standing_fields for line in (item.value or "").splitlines()
        ]
        expected_lines = [
            f"{name} `{points}` pts · `1` game · `{points:.1f}` pts/game"
            for name, points in sorted(players, key=lambda player: (-player[1], player[0]))
        ]
        assert actual_lines == expected_lines
        assert len(actual_lines) == len(set(actual_lines)) == 24
        assert embed.fields[-1].name == "\u200b"
    finally:
        cleanup(old_path, old_prison, path)


def _new_closing_lines(category, name, pts):
    """The five orchestrator-supplied closing lines for one placement category."""
    lines = {
        "first": (
            f"{name} takes first. The victory speech has already exceeded the channel limit.",
            f"{name} wins with `{pts}` pts. Please return the borrowed brain cells before tomorrow.",
            f"First place for {name}. The rest of us were clearly collecting research data.",
            f"{name} tops the board. A suspicious amount of competence for a casual pastime.",
            f"{name}, enjoy the lead. Tomorrow's puzzles have not agreed to cooperate.",
        ),
        "second": (
            f"{name} takes second. Basically first, if you ignore one inconvenient person.",
            f"{name}, close enough to win in the version of events you tell tomorrow.",
            f"Second for {name}. The silver lining is unusually literal today.",
            f"{name} finishes on `{pts}` pts. One more good guess and this becomes a very different speech.",
            f"{name}, an excellent result with just enough disappointment to encourage a rematch.",
        ),
        "middle": (
            f"{name} occupies the middle. A strategic position from which to blame both ends.",
            f"{name}, neither a victory lap nor a rescue mission. Efficient moderation.",
            f"`{pts}` pts for {name}. The statistical equivalent of a sensible cardigan.",
            f"{name} keeps the leaderboard structurally balanced. Somebody has to.",
            f"{name}, safely in the middle: close to the action, far from the paperwork.",
        ),
        "second_last": (
            f"{name} avoids last. Technically a survival story, not a success story.",
            f"{name}, one place above disaster. Excellent use of the available buffer.",
            f"{name} escapes the wooden spoon. Please stop checking whether the scores are final.",
            f"Not last for {name}. The celebration is small, but legally valid.",
            f"{name}, the person below you would like a word about your victory dance.",
        ),
        "last": (
            f"{name} takes last. A generous donation to everyone else's confidence.",
            f"{name}, today's scores have been filed under character development.",
            f"Last place for {name}. The comeback now has a properly dramatic opening chapter.",
            f"{name} gets `{pts}` pts and unlimited material for a revenge arc.",
            f"{name}, even the bottom of the table is still on the table.",
        ),
    }
    return lines[category]


def _neutral_lines(name):
    return (
        f"{name}, did you know octopuses have three hearts? None of them has to endure this leaderboard.",
        f"{name}, did you know sharks predate trees? Your rematch can probably wait until tomorrow.",
        f"{name}, did you know wombats produce cube-shaped droppings? That's today's unrelated fact. You're welcome.",
        f"{name}, die Punkte sind gezählt. Beschwerden bitte in dreifacher Ausfertigung.",
    )


def test_wrap_comment_is_deterministic_and_keeps_original_selection():
    day = "2025-04-01"
    standings = [(10, 9), (11, 7), (12, 5), (13, 3), (14, 1)]
    names = {10: "Anna", 11: "Ben", 12: "Cleo", 13: "Dev", 14: "Eli"}

    first = embeds._wrap_comment(day, names, standings)
    second = embeds._wrap_comment(day, names, standings)
    assert first == second, (first, second)

    calls = []
    original_random = random.Random

    class RecordingRandom:
        def __init__(self, seed):
            self.seed = seed

        def choice(self, seq):
            options = list(seq)
            calls.append((self.seed, options))
            return original_random(self.seed).choice(options)

    try:
        embeds.random.Random = RecordingRandom
        selected = embeds._wrap_comment(day, names, standings)
    finally:
        embeds.random.Random = original_random

    assert selected == first
    # Placement, category and line still use the original date-seeded order.
    assert [seed for seed, _options in calls] == [
        f"{day}:placement", f"{day}:kind", f"{day}:line"
    ], calls
    assert calls[0][1] == list(range(len(standings))), calls[0]

    idx = original_random(f"{day}:placement").choice(range(len(standings)))
    expected_kinds = []
    if idx == 0:
        expected_kinds.append("first")
    if idx == 1 and len(standings) > 2:
        expected_kinds.append("second")
    if idx == len(standings) - 2:
        expected_kinds.append("second_last")
    if idx == len(standings) - 1 and len(standings) > 1:
        expected_kinds.append("last")
    if not expected_kinds:
        expected_kinds.append("middle")
    assert calls[1][1] == expected_kinds, (calls[1], expected_kinds)
    assert first in calls[2][1], (first, calls[2][1])


def test_wrap_comment_categories_expose_new_lines_and_single_german_variant():
    day = "2025-04-02"
    standings = [(1, 10), (2, 8), (3, 6), (4, 4), (5, 2)]
    names = {1: "Anna", 2: "Ben", 3: "Cleo", 4: "Dev", 5: "Eli"}
    categories = ("first", "second", "middle", "second_last", "last")
    # Five-player board: each forced index maps cleanly to one category.
    expected_pool_sizes = {"first": 13, "second": 13, "middle": 13, "second_last": 13, "last": 15}
    original_random = random.Random
    captured = []

    class ForcedPlacementRandom:
        forced_index = 0

        def __init__(self, seed):
            self.seed = seed

        def choice(self, seq):
            options = list(seq)
            if self.seed == f"{day}:placement":
                return ForcedPlacementRandom.forced_index
            if self.seed == f"{day}:line":
                captured.append(options)
                return options[0]
            assert options == [categories[ForcedPlacementRandom.forced_index]], options
            return options[0]

    try:
        embeds.random.Random = ForcedPlacementRandom
        for index, category in enumerate(categories):
            ForcedPlacementRandom.forced_index = index
            captured.clear()
            result = embeds._wrap_comment(day, names, standings)
            assert len(captured) == 1, (category, captured)
            pool = captured[0]
            assert result == pool[0], (category, result, pool[0])
            assert len(pool) == expected_pool_sizes[category], (category, len(pool))

            name, pts = names[standings[index][0]], standings[index][1]
            for line in _new_closing_lines(category, name, pts):
                assert line in pool, (category, line)
            for line in _neutral_lines(name):
                assert line in pool, (category, line)
            # The German line joins the single rotation once; it is not a footer.
            german = (f"{name}, die Punkte sind gezählt. "
                      "Beschwerden bitte in dreifacher Ausfertigung.")
            assert pool.count(german) == 1, (category, pool)
    finally:
        embeds.random.Random = original_random


def test_wrap_embed_has_exactly_one_deterministic_closing_field():
    old_path, old_prison, path = fresh_db()
    day = "2025-04-03"
    try:
        add_score(day, 1, "Alice", "#90", 1)
        add_score(day, 2, "Bob", "#90", 2)
        add_score(day, 3, "Cara", "#90", 3)
        add_score(day, 1, "Alice", "#91", 2)
        add_score(day, 2, "Bob", "#91", 1)
        add_score(day, 3, "Cara", "#91", 3)

        first = embeds.build_wrap_embed(day)
        second = embeds.build_wrap_embed(day)
        assert first is not None and second is not None
        assert [(item.name, item.value) for item in first.fields] == [
            (item.name, item.value) for item in second.fields
        ]
        assert sum(item.name == "\u200b" for item in first.fields) == 1
        assert first.fields[-1].name == "\u200b"
    finally:
        cleanup(old_path, old_prison, path)


if __name__ == "__main__":
    test_ordinary_standings_preserve_order_and_unfiltered_comment()
    test_standings_lines_count_distinct_results_and_handle_zero_games()
    test_tied_totals_keep_existing_order_and_points()
    test_standings_order_stays_by_total_points_not_average()
    test_final_standings_keep_full_names_without_reel_fallbacks()
    test_solo_and_multiplayer_no_point_days_are_quiet()
    test_all_zero_board_has_no_standings_or_roast()
    test_zero_point_player_in_a_real_contest_shows_zero_average()
    test_difficulty_fields_show_native_daily_and_weekly_medians()
    test_native_difficulty_formats_score_ratios_placements_and_regionle()
    test_regionle_named_modes_use_the_regionle_scale()
    test_long_standings_partition_complete_player_lines()
    test_wrap_comment_is_deterministic_and_keeps_original_selection()
    test_wrap_comment_categories_expose_new_lines_and_single_german_variant()
    test_wrap_embed_has_exactly_one_deterministic_closing_field()
    print("All wrap tests passed.")
