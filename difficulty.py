"""Historical difficulty percentiles, separate from leaderboard points and ranks."""
import math
import re
import sqlite3
from datetime import datetime, timedelta

import config
import games

_RATIO_GAMES = {
    "Trivmount", "Thursday Thirty", "Songless", "Centumth",
    "Majority", "Songspot", "History in Order",
}


def empirical_percentile(current, history):
    """Return the empirical midrank: strictly worse plus half of ties / N."""
    if not history:
        return None
    worse = sum(1 for rank in history if rank > current)
    ties = sum(1 for rank in history if rank == current)
    return 100.0 * (worse + 0.5 * ties) / len(history)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _rank(game, solved, rank_score, display_score):
    """Return a comparable key, or None for invalid/unmeasurable records.

    ``(0, native rank)`` is a scored/in-progress result. ``(1, 0)`` is a
    genuine failed attempt with no documented additional progression. Lower
    keys are better. Sentinel values are never treated as real guess counts.
    """
    if not isinstance(game, str):
        return None
    base = game.split(" (", 1)[0]
    if not any(name.casefold() == base.casefold() for name in games.GAME_META):
        return None
    if solved not in (0, 1):
        return None
    score = _number(rank_score)
    display = display_score.strip() if isinstance(display_score, str) else ""
    if score is None or not display:
        return None
    lower = display.casefold()
    if re.match(r"^dnf\b", lower) or re.match(r"^x/\d+(?:\s|$)", lower):
        return 1, 0.0
    if solved == 1:
        return 0, score
    match = re.match(r"(\d+)\s*/\s*([1-9]\d*)", display)
    if match:
        placed, total = int(match.group(1)), int(match.group(2))
        if placed >= total:
            return None  # Incomplete-but-equal must not contradict solved=0.
        if game.startswith("Trivmount"):
            return (0, score) if score < 10000 else None
        if game in _RATIO_GAMES or game.startswith("Magnitudle"):
            return 0, score
    # Travle's documented localized distance/hint progress is comparable.
    if game == "Travle" and score >= 500 and re.search(r"(?:away|pryč)", display, re.IGNORECASE):
        return 1, score
    return None


def _day(date_text):
    return datetime.strptime(date_text, "%Y-%m-%d")


def _variant_of(game, display):
    """Return meaningful subtype and, for Roughly, an incompatible-style marker."""
    base, separator, rest = game.partition(" (")
    variant = rest[:-1].strip() if separator and rest.endswith(")") else None
    type_marker = "grid" if base == "Roughly" and display.startswith("~") else "headline"
    return base, variant, type_marker


def _rows_for_day(board_date):
    with sqlite3.connect(config.DB_PATH) as conn:
        return conn.execute(
            "SELECT game, puzzle_id, user_id, solved, rank_score, display_score"
            " FROM scores WHERE board_date = ?",
            (board_date,),
        ).fetchall()


def _history_for(board_date, target_game, target_type):
    start = _day(board_date) - timedelta(days=config.DIFFICULTY_HISTORY_DAYS)
    with sqlite3.connect(config.DB_PATH) as conn:
        rows = conn.execute(
            "SELECT puzzle_id, board_date, solved, rank_score, display_score FROM scores"
            " WHERE game = ?",
            (target_game,),
        ).fetchall()
    ranks = []
    puzzles = set()
    target_day = _day(board_date)
    for puzzle_id, day_string, solved, stored_rank, display in rows:
        try:
            attempt_day = _day(day_string)
        except (TypeError, ValueError):
            continue
        if not (start.date() <= attempt_day.date() < target_day.date()):
            continue
        _base, _variant, measurement = _variant_of(target_game, display)
        if measurement != target_type:
            continue
        key = _rank(target_game, solved, stored_rank, display)
        if key is None:
            continue
        puzzles.add(puzzle_id)
        ranks.append(key)
    if len(ranks) < config.DIFFICULTY_MIN_HISTORY_ATTEMPTS or len(puzzles) < config.DIFFICULTY_MIN_HISTORY_PUZZLES:
        return None
    return ranks


def analyze_day(board_date):
    """Return qualified puzzle percentiles, highest first, with no heuristic fallback."""
    grouped = {}
    for game, puzzle_id, user_id, solved, stored_rank, display in _rows_for_day(board_date):
        if not isinstance(user_id, int) or isinstance(user_id, bool):
            continue
        key = _rank(game, solved, stored_rank, display)
        if key is None:
            continue
        entry = (user_id, key, display)
        grouped.setdefault((game, puzzle_id), []).append(entry)

    candidates = []
    for (game, puzzle_id), participants in grouped.items():
        user_percentiles = {}
        for uid, rank, _display in participants:
            user_percentiles.setdefault(uid, []).append(rank)
        if len(user_percentiles) < config.DIFFICULTY_MIN_DAILY_PLAYERS:
            continue

        styles = {_variant_of(game, display) for _uid, _rank, display in participants}
        if len(styles) != 1:
            continue  # Do not combine incompatible measurement semantics today.
        _base, variant, type_marker = styles.pop()
        baseline = _history_for(board_date, game, type_marker)
        if baseline is None:
            continue
        percentiles = [empirical_percentile(rank, baseline)
                       for ranks in user_percentiles.values() for rank in ranks]
        if any(value is None for value in percentiles):
            continue
        raw_mean = sum(value for value in percentiles if value is not None) / len(percentiles)
        n = len(user_percentiles)
        adjusted = ((n * raw_mean + config.DIFFICULTY_SHRINKAGE_STRENGTH * 50)
                    / (n + config.DIFFICULTY_SHRINKAGE_STRENGTH))
        candidates.append({
            "game": game,
            "variant": variant,
            "puzzle_id": puzzle_id,
            "percentile": adjusted,
            "players": n,
        })
    return sorted(candidates, key=lambda item: (
        -item["percentile"], item["game"].casefold(),
        (item["variant"] or "").casefold(), item["puzzle_id"],
    ))


def analyze_week(end_date: str, days: int = 7):
    """Average eligible daily puzzle scores by variant, never future baseline data."""
    end = _day(end_date)
    start = end - timedelta(days=days - 1)
    variants = {}
    for offset in range(days):
        date = (start + timedelta(days=offset)).strftime("%Y-%m-%d")
        for result in analyze_day(date):
            key = (result["game"], result["variant"])
            bucket = variants.setdefault(key, {"scores": [], "instances": set()})
            bucket["scores"].append(result["percentile"])
            bucket["instances"].add((date, result["puzzle_id"]))
    results = []
    for (game, variant), item in variants.items():
        if len(item["instances"]) < config.DIFFICULTY_MIN_WEEKLY_PUZZLES:
            continue
        results.append({
            "game": game,
            "variant": variant,
            "percentile": sum(item["scores"]) / len(item["scores"]),
            "instances": len(item["instances"]),
        })
    return sorted(results, key=lambda item: (
        -item["percentile"], item["game"].casefold(), (item["variant"] or "").casefold()
    ))
