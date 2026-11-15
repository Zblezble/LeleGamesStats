# -*- coding: utf-8 -*-
"""Focused regressions for History in Order ranking, podiums and DB migration.

Run: python -X utf8 test_history.py   (exits 1 on failure)
Every database test uses a temporary SQLite file and explicit dates, so the
suite never reads or writes scores.db or the downloaded production database.
"""
import os
import sqlite3
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402
import db  # noqa: E402
import embeds  # noqa: E402
import games  # noqa: E402
import parsers  # noqa: E402


def fresh_db():
    """Point config at a throwaway database; return the previous path for cleanup."""
    fd, path = tempfile.mkstemp(prefix="history_test_", suffix=".db")
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


def add_score(board_date, user_id, user_name, game, puzzle_id, solved,
              rank_score, display_score, timestamp=None, extra_url=None,
              ingest_id=None):
    with sqlite3.connect(config.DB_PATH) as conn:
        if timestamp is None:
            conn.execute(
                "INSERT INTO scores (board_date, user_id, user_name, game, puzzle_id,"
                " solved, rank_score, display_score, extra_url, ingest_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (board_date, user_id, user_name, game, puzzle_id, solved,
                 rank_score, display_score, extra_url, ingest_id),
            )
        else:
            conn.execute(
                "INSERT INTO scores (board_date, user_id, user_name, game, puzzle_id,"
                " solved, rank_score, display_score, extra_url, ingest_id, timestamp)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (board_date, user_id, user_name, game, puzzle_id, solved,
                 rank_score, display_score, extra_url, ingest_id, timestamp),
            )
        conn.commit()


def only_history_result(text):
    results = parsers.parse_all_games(text)
    assert len(results) == 1, results
    assert results[0]["game"] == "History in Order", results
    return results[0]


def test_parser_ranks_more_placements_better():
    full = only_history_result("History in Order №214 · 6/6")
    four = only_history_result("History in Order №214 · 4/6")
    two = only_history_result("History in Order №214 · 2/6")
    larger = only_history_result("History in Order №300 · 8/10")

    assert (full["puzzle_id"], full["solved"], full["rank_score"], full["display_score"]) \
        == ("#214", 1, -6.0, "6/6"), full
    assert (four["solved"], four["rank_score"], four["display_score"]) == (0, -4.0, "4/6"), four
    assert (two["solved"], two["rank_score"], two["display_score"]) == (0, -2.0, "2/6"), two
    assert (larger["solved"], larger["rank_score"], larger["display_score"]) == (0, -8.0, "8/10"), larger

    # Lower rank_score is better: full > 4/6 > 2/6, with the native total respected.
    assert full["rank_score"] < four["rank_score"] < two["rank_score"]
    assert full["solved"] == 1
    assert four["solved"] == two["solved"] == 0


def test_partial_results_order_and_earn_daily_podium_points():
    old_path, path = fresh_db()
    old_prison = config.PRISON_ENABLED
    config.PRISON_ENABLED = False
    try:
        board_date = "2025-03-04"
        # The original bug: the earlier 2/6 used to sit above the later 4/6.
        add_score(board_date, 2, "Bob", "History in Order", "#77", 0, -2.0, "2/6",
                  timestamp="2025-03-04 09:00:00")
        add_score(board_date, 1, "Alice", "History in Order", "#77", 0, -4.0, "4/6",
                  timestamp="2025-03-04 10:00:00")

        assert embeds.placement_of(board_date, "History in Order", "#77", 1) == "1/2"
        assert embeds.placement_of(board_date, "History in Order", "#77", 2) == "2/2"
        assert embeds.compute_daily_points(board_date) == ({1: 3, 2: 2},
                                                          {1: "Alice", 2: "Bob"})

        embed = embeds.build_daily_embed(board_date)
        field = next(f for f in embed.fields if "History in Order" in (f.name or ""))
        value = field.value or ""
        assert value.index("4/6") < value.index("2/6"), value

        # A solo partial is visible but cannot manufacture a contest or points.
        add_score("2025-03-05", 1, "Alice", "History in Order", "#78", 0, -4.0, "4/6")
        assert embeds.compute_daily_points("2025-03-05") == ({}, {1: "Alice"})
        assert embeds.placement_of("2025-03-05", "History in Order", "#78", 1) == "1/1"
    finally:
        config.PRISON_ENABLED = old_prison
        cleanup(old_path, path)


def test_full_match_wins_but_partial_does_not_and_dnf_stays_out():
    old_path, path = fresh_db()
    old_prison = config.PRISON_ENABLED
    config.PRISON_ENABLED = False
    try:
        board_date = "2025-03-06"
        add_score(board_date, 1, "Alice", "History in Order", "#79", 1, -6.0, "6/6")
        add_score(board_date, 2, "Bob", "History in Order", "#79", 0, -4.0, "4/6")

        assert embeds.placement_of(board_date, "History in Order", "#79", 1) == "1/2"
        assert embeds.placement_of(board_date, "History in Order", "#79", 2) == "2/2"
        assert embeds.compute_daily_points(board_date) == ({1: 3, 2: 2},
                                                          {1: "Alice", 2: "Bob"})

        # New forfeits are stored above the graded competitive cutoff.
        assert db.forfeit_entry(board_date, 3, "Cara", "History in Order") == ("#79", False)
        with sqlite3.connect(config.DB_PATH) as conn:
            row = conn.execute(
                "SELECT solved, rank_score, display_score FROM scores"
                " WHERE board_date = ? AND user_id = 3",
                (board_date,),
            ).fetchone()
        assert row == (0, 10000.0, "DNF"), row
        assert embeds.placement_of(board_date, "History in Order", "#79", 3) is None
        points, names = embeds.compute_daily_points(board_date)
        assert points == {1: 3, 2: 2}, points
        assert 3 not in names
    finally:
        config.PRISON_ENABLED = old_prison
        cleanup(old_path, path)


def test_shared_eligibility_helper_excludes_legacy_sentinels_and_keeps_zero():
    old_path, path = fresh_db()
    old_prison = config.PRISON_ENABLED
    config.PRISON_ENABLED = False
    try:
        board_date = "2025-03-07"
        add_score(board_date, 1, "Alice", "History in Order", "#80", 0, -4.0, "4/6")
        add_score(board_date, 2, "Bob", "History in Order", "#80", 0, -2.0, "2/6")
        add_score(board_date, 3, "LegacyDNF", "History in Order", "#80", 0, 999.0, "DNF")
        add_score(board_date, 4, "Malformed", "History in Order", "#80", 0, 99.0, "4/6 ???")
        add_score(board_date, 5, "Zero", "History in Order", "#80", 0, 0.0, "0/6")

        # The shared eligibility helper is the single source of truth used by
        # placement_of and compute_daily_points.
        assert games.is_ranked_result("History in Order", 0, -4.0)
        assert games.is_ranked_result("History in Order", 0, 0.0)
        assert not games.is_ranked_result("History in Order", 0, 99.0)
        assert not games.is_ranked_result("History in Order", 0, 999.0)
        assert not games.is_ranked_result("History in Order", 0, 10000.0)
        assert not games.is_ranked_result("History in Order", 0, None)
        assert games.is_ranked_result("History in Order", 1, -6.0)
        # Ordinary behavior for other games is preserved.
        assert games.is_ranked_result("Wordle", 1, 1.0)
        assert not games.is_ranked_result("Wordle", 0, 1.0)
        assert not games.is_ranked_result("Wordle", 0, 999.0)
        assert games.is_ranked_result("Trivmount", 0, 5000.0)
        assert not games.is_ranked_result("Trivmount", 0, 10000.0)

        assert embeds.placement_of(board_date, "History in Order", "#80", 1) == "1/5"
        assert embeds.placement_of(board_date, "History in Order", "#80", 2) == "2/5"
        assert embeds.placement_of(board_date, "History in Order", "#80", 3) is None
        assert embeds.placement_of(board_date, "History in Order", "#80", 4) is None
        assert embeds.placement_of(board_date, "History in Order", "#80", 5) == "3/5"
        points, names = embeds.compute_daily_points(board_date)
        assert points == {1: 3, 2: 2, 5: 1}, points
        assert set(names) == {1, 2, 5}, names

        zero = only_history_result("History in Order №80 · 0/6")
        assert (zero["solved"], zero["rank_score"], zero["display_score"]) == (0, 0.0, "0/6"), zero
    finally:
        config.PRISON_ENABLED = old_prison
        cleanup(old_path, path)


def _snapshot():
    with sqlite3.connect(config.DB_PATH) as conn:
        return conn.execute(
            "SELECT id, board_date, user_id, user_name, game, puzzle_id, solved,"
            " rank_score, display_score, extra_url, ingest_id, timestamp"
            " FROM scores ORDER BY id"
        ).fetchall()


def _history_order():
    with sqlite3.connect(config.DB_PATH) as conn:
        return [row[0] for row in conn.execute(
            "SELECT display_score FROM scores"
            " WHERE game = 'History in Order' AND solved = 0"
            " AND display_score IN ('2/6', '4/6')"
            " ORDER BY rank_score ASC, timestamp ASC"
        ).fetchall()]


def test_init_db_normalizes_legacy_history_ranks_idempotently():
    old_path, path = fresh_db()
    try:
        board_date = "2025-04-01"
        # Legacy partial rows: both rank 99, so the older 2/6 leads before migration.
        add_score(board_date, 2, "Two", "History in Order", "#50", 0, 99.0, "2/6",
                  timestamp="2025-04-01 08:00:00", extra_url="https://example/2",
                  ingest_id=20)
        add_score(board_date, 1, "Four", "History in Order", "#50", 0, 99.0, "4/6",
                  timestamp="2025-04-01 09:00:00", extra_url="https://example/4",
                  ingest_id=10)
        # Rows that must not be rewritten.
        add_score(board_date, 4, "Correct", "History in Order", "#50", 0, -5.0, "5/6")
        add_score(board_date, 5, "DNF", "History in Order", "#50", 0, 999.0, "DNF")
        add_score(board_date, 6, "Malformed", "History in Order", "#50", 0, 99.0, "4/6 ???")
        add_score(board_date, 7, "FullLooking", "History in Order", "#50", 0, 99.0, "6/6")
        add_score(board_date, 8, "Completed", "History in Order", "#50", 1, 6.0, "6/6")
        add_score(board_date, 9, "UnknownMode", "History in Order (Hard)", "#50", 0, 99.0, "4/6")
        add_score(board_date, 10, "OtherGame", "Wordle", "#50", 0, 99.0, "4/6")
        add_score(board_date, 11, "NoRank", "History in Order", "#50", 0, None, "3/6")
        add_score(board_date, 12, "BadFlagPartial", "History in Order", "#50", 1, 99.0, "4/6")

        assert _history_order() == ["2/6", "4/6"]
        before = _snapshot()
        assert len(before) == 11
        full_before = next(row for row in before if row[3] == "Completed")

        db.init_db()  # Runs the existing initialization path, including migration.

        after = _snapshot()
        changed = []
        untouched = []
        for old_row, new_row in zip(before, after):
            assert old_row[0] == new_row[0]
            if old_row[7] != new_row[7]:
                changed.append(new_row[0])
                # Only rank_score may change; raw result and metadata stay intact.
                assert old_row[:7] == new_row[:7], (old_row, new_row)
                assert old_row[8:] == new_row[8:], (old_row, new_row)
            else:
                untouched.append(new_row[0])
                assert old_row == new_row, (old_row, new_row)

        assert len(changed) == 3, changed
        assert len(untouched) == 8, untouched
        assert _history_order() == ["4/6", "2/6"]

        # The unchanged legacy DNF and malformed rows also stay ineligible.
        assert embeds.placement_of(board_date, "History in Order", "#50", 5) is None
        assert embeds.placement_of(board_date, "History in Order", "#50", 6) is None

        with sqlite3.connect(config.DB_PATH) as conn:
            migrated = dict(conn.execute(
                "SELECT id, rank_score FROM scores WHERE id IN (?, ?, ?)", tuple(changed)
            ).fetchall())
            full_after = conn.execute(
                "SELECT solved, rank_score, display_score FROM scores"
                " WHERE user_name = 'Completed'"
            ).fetchone()
        assert set(migrated.values()) == {-2.0, -4.0, -6.0}, migrated
        assert full_before[7] == 6.0
        assert full_after == (1, -6.0, "6/6"), full_after
        assert full_before[:7] == next(row for row in after if row[3] == "Completed")[:7]
        assert full_before[8:] == next(row for row in after if row[3] == "Completed")[8:]

        stable = _snapshot()
        db.init_db()  # Repeat must make no further changes.
        assert _snapshot() == stable
        assert _history_order() == ["4/6", "2/6"]
        print("     migrated 3 legacy native rows (2 partial, 1 full);"
              " repeat initialization changed 0 rows")
    finally:
        cleanup(old_path, path)


def main() -> int:
    tests = [
        test_parser_ranks_more_placements_better,
        test_partial_results_order_and_earn_daily_podium_points,
        test_full_match_wins_but_partial_does_not_and_dnf_stays_out,
        test_shared_eligibility_helper_excludes_legacy_sentinels_and_keeps_zero,
        test_init_db_normalizes_legacy_history_ranks_idempotently,
    ]
    for test in tests:
        test()
        print(f"ok   {test.__name__}")
    print(f"\n{len(tests)}/{len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
