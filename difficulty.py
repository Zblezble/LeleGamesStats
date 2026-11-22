"""Historical difficulty percentiles, separate from leaderboard points and ranks."""
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

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


TrendStatus = Literal["improving", "declining", "stable", "insufficient"]


@dataclass(frozen=True)
class TrendResult:
    """A player's recent performance change in historical percentile points."""

    status: TrendStatus
    previous_average: float | None
    recent_average: float | None
    change_pp: float | None
    previous_count: int
    recent_count: int
    period_days: int


def _trend_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return _day(value).date()


def _classify_trend(change_pp: float) -> TrendStatus:
    """Classify a raw percentage-point change using the documented thresholds."""
    if change_pp >= 15:
        return "improving"
    if change_pp <= -15:
        return "declining"
    return "stable"


def calculate_game_trend(user_id: int, game_key: str,
                         end_date: date | datetime | str) -> TrendResult:
    """Calculate one player's recent percentile trend without shrinkage.

    Each submitted result is compared with the same game's historical baseline
    strictly before that result's date. Results without usable history are
    excluded. At least ``GAME_TREND_MIN_RESULTS`` usable results are required in
    each half of the configured trend period.
    """
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        raise ValueError("Trend user_id must be an integer.")
    if not isinstance(game_key, str) or not game_key.strip():
        raise ValueError("Trend game_key must be a non-empty string.")
    end = _trend_date(end_date)
    family = games.score_chart_family(game_key)
    chart_meta = games.SCORE_CHART_GAMES.get(family, {}) if family else {}
    period_days = int(chart_meta.get("trend_period_days",
                                     config.GAME_TREND_DAILY_DAYS))
    if period_days < 2:
        raise ValueError("Trend period must span at least two days.")

    window_days = period_days // 2
    start = end - timedelta(days=period_days - 1)
    recent_start = end - timedelta(days=window_days - 1)
    previous_end = recent_start - timedelta(days=1)

    with sqlite3.connect(config.DB_PATH) as conn:
        rows = conn.execute(
            "SELECT board_date, puzzle_id, solved, rank_score, display_score"
            " FROM scores WHERE user_id = ? AND game = ? COLLATE NOCASE"
            " AND board_date BETWEEN ? AND ?"
            " ORDER BY board_date ASC, puzzle_id ASC, timestamp ASC, id ASC",
            (user_id, game_key, start.isoformat(), end.isoformat()),
        ).fetchall()

    previous_percentiles: list[float] = []
    recent_percentiles: list[float] = []
    for board_date, _puzzle_id, solved, stored_rank, display in rows:
        try:
            day = date.fromisoformat(board_date)
        except (TypeError, ValueError):
            continue
        if day < start or day > end:
            continue
        rank = _rank(game_key, solved, stored_rank, display)
        if rank is None:
            continue
        _base, _variant, measurement = _variant_of(game_key, display)
        baseline = _history_for(day.isoformat(), game_key, measurement)
        if baseline is None:
            continue
        percentile = empirical_percentile(rank, baseline)
        if percentile is None:
            continue
        if start <= day <= previous_end:
            previous_percentiles.append(percentile)
        elif recent_start <= day <= end:
            recent_percentiles.append(percentile)

    minimum = config.GAME_TREND_MIN_RESULTS
    if len(previous_percentiles) < minimum or len(recent_percentiles) < minimum:
        return TrendResult(
            status="insufficient", previous_average=None, recent_average=None,
            change_pp=None, previous_count=len(previous_percentiles),
            recent_count=len(recent_percentiles), period_days=period_days,
        )

    previous_average = sum(previous_percentiles) / len(previous_percentiles)
    recent_average = sum(recent_percentiles) / len(recent_percentiles)
    change_pp = recent_average - previous_average
    return TrendResult(
        status=_classify_trend(change_pp),
        previous_average=previous_average,
        recent_average=recent_average,
        change_pp=change_pp,
        previous_count=len(previous_percentiles),
        recent_count=len(recent_percentiles),
        period_days=period_days,
    )
