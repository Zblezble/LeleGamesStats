"""Game history model, retrieval and Unicode chart rendering.

This module is independent of Discord command handling. It reads only existing
canonical score rows and never changes rank_score, points, or difficulty data.
"""
from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

import config
import games

AttemptStatus = Literal["solved", "dnf", "missing"]
ScoreStatus = Literal["score", "dnf", "missing"]
# Calendar-day windows for the personal game history chart. The compact
# 20-day layout uses left-half blocks: ``▌▌▌`` has built-in gaps, so no
# explicit spaces are needed and it occupies the same width as ten spaced cells.
CHART_PERIOD_DAYS = 10
CHART_PERIOD_CHOICES = (10, 20)
# Half-height blocks stay aligned in Discord's monospace font while leaving a
# visible seam between vertically stacked attempts.
ATTEMPT_SYMBOL = "▄"
ATTEMPT_COMPACT_SYMBOL = "■"
SCORE_SYMBOL = "▉"
SCORE_COMPACT_SYMBOL = "▌"
_ATTEMPT_DISPLAY = re.compile(r"^([1-9]\d*)\s*/\s*([1-9]\d*)")
_DNF_DISPLAY = re.compile(r"^(?:dnf|x\s*/\s*([1-9]\d*))$", re.IGNORECASE)
_NUMBER_TEXT = r"\d[\d,]*"
_SCORE_RATIO = re.compile(rf"^({_NUMBER_TEXT})\s*/\s*({_NUMBER_TEXT})")
_SCORE_POINTS = re.compile(rf"^({_NUMBER_TEXT})\s*pts$", re.IGNORECASE)
_GUESS_COUNT = re.compile(r"^(\d+)\s+guesses$", re.IGNORECASE)


@dataclass(frozen=True)
class DailyAttempt:
    """One canonical day state for a fixed-attempt game."""

    date: date
    status: AttemptStatus
    attempts: int | None = None

    def __post_init__(self):
        if self.status not in ("solved", "dnf", "missing"):
            raise ValueError(f"Unsupported attempt status: {self.status!r}")
        if self.status == "solved":
            if isinstance(self.attempts, bool) or not isinstance(self.attempts, int):
                raise ValueError("A solved day requires an integer attempt count.")
            if self.attempts < 1:
                raise ValueError("A solved day requires at least one attempt.")
        elif self.attempts is not None:
            raise ValueError("Only solved days may carry an attempt count.")


@dataclass(frozen=True)
class DailyScore:
    """One canonical day state for a score-based game."""

    date: date
    status: ScoreStatus
    score: float | None = None
    maximum: float | None = None

    def __post_init__(self):
        if self.status not in ("score", "dnf", "missing"):
            raise ValueError(f"Unsupported score status: {self.status!r}")
        if self.status == "score":
            if (isinstance(self.score, bool) or not isinstance(self.score, (int, float))
                    or not math.isfinite(self.score) or self.score < 0):
                raise ValueError("A scored day requires a finite nonnegative score.")
            if self.maximum is not None:
                if (isinstance(self.maximum, bool) or not isinstance(self.maximum, (int, float))
                        or not math.isfinite(self.maximum) or self.maximum <= 0):
                    raise ValueError("A score maximum must be a positive number.")
                if self.score > self.maximum:
                    raise ValueError("A score cannot exceed its displayed maximum.")
        elif self.score is not None or self.maximum is not None:
            raise ValueError("Only scored days may carry score values.")


def _as_date(value: date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"Expected a date, got {type(value).__name__}")


def max_attempts_for(game_name: str) -> int:
    """Return the fixed attempt maximum for a supported game or variant."""
    family = games.fixed_attempt_family(game_name)
    if family is None:
        raise ValueError(f"Unsupported fixed-attempt game: {game_name!r}")
    return int(games.FIXED_ATTEMPT_GAMES[family]["max_attempts"])


def chart_layout(period: int, *, spaced_symbol: str,
                 compact_symbol: str) -> tuple[str, int]:
    """Return the symbol and cell width for a supported chart period."""
    if period == CHART_PERIOD_DAYS:
        return spaced_symbol, 2
    if period == CHART_PERIOD_CHOICES[-1]:
        return compact_symbol, 1
    raise ValueError("Chart period must be 10 or 20 days.")


def date_label_interval(cell_width: int) -> int:
    """Keep compact and spaced charts at the same visual label spacing."""
    if cell_width == 1:
        return 8
    if cell_width == 2:
        return 4
    raise ValueError("Chart cells must be one or two characters wide.")


def _date_labels(results: list, cell_width: int) -> str:
    """Build date labels aligned to compact or spaced chart cells."""
    interval = date_label_interval(cell_width)
    labels = [" " * cell_width for _ in results]
    for index, result in enumerate(results):
        if index % interval:
            continue
        label = f"{result.date.day:02d}"
        if cell_width == 1:
            # A two-digit date spans two compact cells; start it at the tick.
            if index + 1 < len(labels):
                labels[index], labels[index + 1] = label
            else:
                labels[index - 1], labels[index] = label
        else:
            labels[index] = label
    return "".join(labels)


def score_chart_meta(game_name: str) -> dict:
    """Return renderer/unit metadata for a supported score-history game."""
    family = games.score_chart_family(game_name)
    if family is None:
        raise ValueError(f"Unsupported score-history game: {game_name!r}")
    return games.SCORE_CHART_GAMES[family]


def guess_chart_meta(game_name: str) -> dict:
    """Return renderer/unit metadata for a supported open-ended guess game."""
    family = games.guess_chart_family(game_name)
    if family is None:
        raise ValueError(f"Unsupported guess-history game: {game_name!r}")
    return games.GUESS_CHART_GAMES[family]


def resolve_chart_game(user_id: int, selected_game: str,
                       start_date: date, end_date: date) -> tuple[str | None, list[str]]:
    """Resolve a chart game for one user and period.

    Returns ``(game, [])`` when one exact game can be used. For a base-name
    request with several variants, returns ``(None, variants)`` so the caller
    can ask for an exact variant instead of silently mixing them.
    """
    family = (games.fixed_attempt_family(selected_game)
              or games.score_chart_family(selected_game)
              or games.guess_chart_family(selected_game))
    if family is None:
        return None, []

    selected = selected_game.strip().casefold()
    with sqlite3.connect(config.DB_PATH) as conn:
        rows = conn.execute(
            "SELECT DISTINCT game FROM scores"
            " WHERE user_id = ? AND board_date BETWEEN ? AND ?",
            (user_id, start_date.isoformat(), end_date.isoformat()),
        ).fetchall()
    candidates = sorted({
        row[0] for row in rows
        if row[0] and (games.fixed_attempt_family(row[0]) == family
                       or games.score_chart_family(row[0]) == family
                       or games.guess_chart_family(row[0]) == family)
    })
    exact = [name for name in candidates if name.casefold() == selected]
    if exact:
        return exact[0], []
    # A base-name request may use its sole played variant, or the registry's
    # designated active variant. An explicit variant request must not silently
    # substitute a different variant.
    if "(" in selected:
        return None, []
    preferred = games.chart_preferred_variant(family)
    if preferred and any(name.casefold() == preferred.casefold()
                         for name in candidates):
        return preferred, []
    if len(candidates) == 1:
        return candidates[0], []
    if len(candidates) > 1:
        return None, candidates
    return None, []


def _attempt_from_row(day: date, solved: object, display_score: str | None,
                      max_attempts: int) -> DailyAttempt | None:
    """Convert one stored row into a chart state, or None if it is unusable."""
    if solved not in (0, 1) or isinstance(solved, bool):
        return None
    display = (display_score or "").strip()
    dnf = _DNF_DISPLAY.match(display)
    if dnf:
        if solved != 0:
            return None
        denominator = dnf.group(1)
        if denominator and int(denominator) != max_attempts:
            return None
        return DailyAttempt(day, "dnf", None)

    match = _ATTEMPT_DISPLAY.match(display)
    if match and solved == 1:
        attempts, total = int(match.group(1)), int(match.group(2))
        if total == max_attempts and 1 <= attempts <= max_attempts:
            return DailyAttempt(day, "solved", attempts)
    return None


def load_attempts(user_id: int, game_name: str,
                  start_date: date, end_date: date) -> list[DailyAttempt]:
    """Load one user's latest valid result per day for an exact game name."""
    start = _as_date(start_date)
    end = _as_date(end_date)
    if end < start:
        raise ValueError("The chart end date must not precede its start date.")
    max_attempts = max_attempts_for(game_name)

    with sqlite3.connect(config.DB_PATH) as conn:
        rows = conn.execute(
            "SELECT board_date, solved, display_score"
            " FROM scores WHERE user_id = ? AND game = ? COLLATE NOCASE"
            " AND board_date BETWEEN ? AND ?"
            " ORDER BY board_date ASC, timestamp DESC, id DESC",
            (user_id, game_name, start.isoformat(), end.isoformat()),
        ).fetchall()

    by_day: dict[date, DailyAttempt] = {}
    for board_date, solved, display_score in rows:
        try:
            day = date.fromisoformat(board_date)
        except (TypeError, ValueError):
            continue
        if not start <= day <= end:
            continue
        attempt = _attempt_from_row(day, solved, display_score, max_attempts)
        if attempt is not None:
            # Rows are newest-first, so the first valid row wins deterministically.
            by_day.setdefault(day, attempt)

    return [
        by_day.get(start + timedelta(days=offset),
                   DailyAttempt(start + timedelta(days=offset), "missing", None))
        for offset in range((end - start).days + 1)
    ]


def _score_from_row(day: date, solved: object, display_score: str | None,
                    game_name: str) -> DailyScore | None:
    """Convert one stored score row into a chart state, or None if unusable."""
    if solved not in (0, 1) or isinstance(solved, bool):
        return None
    meta = score_chart_meta(game_name)
    display = (display_score or "").strip()
    if display.casefold() == "dnf":
        return DailyScore(day, "dnf", None, None)

    def number(text: str) -> int:
        return int(text.replace(",", ""))

    ratio = _SCORE_RATIO.match(display)
    if meta["renderer"] == "fixed_score":
        if not ratio:
            return None
        score, maximum = number(ratio.group(1)), number(ratio.group(2))
        if maximum > 0 and 0 <= score <= maximum:
            return DailyScore(day, "score", score, maximum)
        return None

    if games.score_chart_family(game_name) == "Maptap":
        points = _SCORE_POINTS.match(display)
        if not points:
            return None
        return DailyScore(day, "score", number(points.group(1)), None)

    if not ratio:
        return None
    score, maximum = number(ratio.group(1)), number(ratio.group(2))
    if maximum > 0 and 0 <= score <= maximum:
        return DailyScore(day, "score", score, maximum)
    return None


def load_scores(user_id: int, game_name: str,
                start_date: date, end_date: date) -> list[DailyScore]:
    """Load one user's latest valid score per day for an exact game name."""
    start = _as_date(start_date)
    end = _as_date(end_date)
    if end < start:
        raise ValueError("The chart end date must not precede its start date.")
    score_chart_meta(game_name)

    with sqlite3.connect(config.DB_PATH) as conn:
        rows = conn.execute(
            "SELECT board_date, solved, display_score"
            " FROM scores WHERE user_id = ? AND game = ? COLLATE NOCASE"
            " AND board_date BETWEEN ? AND ?"
            " ORDER BY board_date ASC, timestamp DESC, id DESC",
            (user_id, game_name, start.isoformat(), end.isoformat()),
        ).fetchall()

    by_day: dict[date, DailyScore] = {}
    for board_date, solved, display_score in rows:
        try:
            day = date.fromisoformat(board_date)
        except (TypeError, ValueError):
            continue
        if not start <= day <= end:
            continue
        result = _score_from_row(day, solved, display_score, game_name)
        if result is not None:
            # Rows are newest-first, so the first valid row wins deterministically.
            by_day.setdefault(day, result)

    return [
        by_day.get(start + timedelta(days=offset),
                   DailyScore(start + timedelta(days=offset), "missing", None, None))
        for offset in range((end - start).days + 1)
    ]


def _guess_from_row(day: date, solved: object, display_score: str | None,
                    game_name: str) -> DailyAttempt | None:
    """Convert one stored Globle-style result into an open-ended attempt state."""
    if solved not in (0, 1) or isinstance(solved, bool):
        return None
    guess_chart_meta(game_name)
    display = (display_score or "").strip()
    if _DNF_DISPLAY.match(display):
        return DailyAttempt(day, "dnf", None) if solved == 0 else None
    match = _GUESS_COUNT.match(display)
    if match and solved == 1 and int(match.group(1)) >= 1:
        return DailyAttempt(day, "solved", int(match.group(1)))
    return None


def load_guesses(user_id: int, game_name: str,
                 start_date: date, end_date: date) -> list[DailyAttempt]:
    """Load one user's latest valid guess count per day for an exact game name."""
    start = _as_date(start_date)
    end = _as_date(end_date)
    if end < start:
        raise ValueError("The chart end date must not precede its start date.")
    guess_chart_meta(game_name)

    with sqlite3.connect(config.DB_PATH) as conn:
        rows = conn.execute(
            "SELECT board_date, solved, display_score"
            " FROM scores WHERE user_id = ? AND game = ? COLLATE NOCASE"
            " AND board_date BETWEEN ? AND ?"
            " ORDER BY board_date ASC, timestamp DESC, id DESC",
            (user_id, game_name, start.isoformat(), end.isoformat()),
        ).fetchall()

    by_day: dict[date, DailyAttempt] = {}
    for board_date, solved, display_score in rows:
        try:
            day = date.fromisoformat(board_date)
        except (TypeError, ValueError):
            continue
        if not start <= day <= end:
            continue
        attempt = _guess_from_row(day, solved, display_score, game_name)
        if attempt is not None:
            # Rows are newest-first, so the first valid row wins deterministically.
            by_day.setdefault(day, attempt)

    return [
        by_day.get(start + timedelta(days=offset),
                   DailyAttempt(start + timedelta(days=offset), "missing", None))
        for offset in range((end - start).days + 1)
    ]


def summarize_attempts(daily_results: list[DailyAttempt], *,
                       unit: str = "guesses", singular: str = "guess") -> str:
    """Return compact played/solved/average/best lines for the chart period."""
    played = [result for result in daily_results if result.status != "missing"]
    solved = [result for result in played if result.status == "solved"]
    attempts = [result.attempts for result in solved if result.attempts is not None]

    if played:
        rate = len(solved) / len(played)
        solved_line = f"Solved: {len(solved)}/{len(played)} ({rate:.0%})"
    else:
        solved_line = "Solved: 0/0 (—)"
    average = f"{sum(attempts) / len(attempts):.1f} {unit}" if attempts else "—"
    best = f"{min(attempts)} {singular if min(attempts) == 1 else unit}" if attempts else "—"
    return "\n".join([
        f"Played: {len(played)}/{len(daily_results)} days",
        solved_line,
        f"Avg: {average}",
        f"Best: {best}",
    ])


def render_attempt_chart(daily_results: list[DailyAttempt], max_attempts: int,
                         start_date: date, end_date: date, *,
                         title: str = "Attempt history",
                         period: int = CHART_PERIOD_DAYS) -> str:
    """Render an aligned vertical Unicode bar chart in a code block."""
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
        raise ValueError("max_attempts must be a positive integer.")

    start = _as_date(start_date)
    end = _as_date(end_date)
    expected_days = (end - start).days + 1
    if end < start or len(daily_results) != expected_days:
        raise ValueError("daily_results must cover the inclusive date range exactly.")

    normalized: list[DailyAttempt] = []
    for offset, result in enumerate(daily_results):
        if not isinstance(result, DailyAttempt):
            raise TypeError(f"Expected DailyAttempt, got {type(result).__name__}")
        expected_day = start + timedelta(days=offset)
        if _as_date(result.date) != expected_day:
            raise ValueError("daily_results must be in chronological day order.")
        if result.status == "solved" and (
            result.attempts is None or result.attempts > max_attempts
        ):
            raise ValueError("A solved attempt exceeds the game's fixed maximum.")
        normalized.append(result)

    axis_width = len(str(max_attempts))
    bar_symbol, cell_width = chart_layout(
        period, spaced_symbol=ATTEMPT_SYMBOL,
        compact_symbol=ATTEMPT_COMPACT_SYMBOL,
    )
    lines = [
        f"{title.upper()} · {start.isoformat()} to {end.isoformat()}",
        "Guesses (lower = better)",
        "",
    ]

    for attempt in range(max_attempts, 0, -1):
        cells = []
        for result in normalized:
            if (result.status == "solved" and result.attempts is not None
                    and result.attempts >= attempt):
                symbol = bar_symbol
            elif result.status == "dnf" and attempt == max_attempts:
                symbol = "X"
            else:
                symbol = " "
            cells.append(symbol.rjust(cell_width))
        lines.append((f"{attempt:>{axis_width}} │" + "".join(cells)).rstrip())

    lines.append(" " * (axis_width + 1) + "└" + "─" * (cell_width * len(normalized)))
    lines.append(" " * (axis_width + 2) + _date_labels(normalized, cell_width))
    return "\n".join(lines)


def render_scaled_guess_chart(daily_results: list[DailyAttempt], default_max: int,
                              start_date: date, end_date: date, *,
                              title: str = "Guess history", unit: str = "guesses",
                              period: int = CHART_PERIOD_DAYS) -> str:
    """Render open-ended guess counts with a scalable lower-is-better axis."""
    if isinstance(default_max, bool) or not isinstance(default_max, int) or default_max < 1:
        raise ValueError("default_max must be a positive integer.")
    start = _as_date(start_date)
    end = _as_date(end_date)
    expected_days = (end - start).days + 1
    if end < start or len(daily_results) != expected_days:
        raise ValueError("daily_results must cover the inclusive date range exactly.")

    normalized: list[DailyAttempt] = []
    for offset, result in enumerate(daily_results):
        if not isinstance(result, DailyAttempt):
            raise TypeError(f"Expected DailyAttempt, got {type(result).__name__}")
        if _as_date(result.date) != start + timedelta(days=offset):
            raise ValueError("daily_results must be in chronological day order.")
        if result.status == "solved" and result.attempts is None:
            raise ValueError("A solved guess day requires an attempt count.")
        normalized.append(result)

    counts = [result.attempts for result in normalized
              if result.status == "solved" and result.attempts is not None]
    chart_max = max([default_max, *counts])
    axis_width = len(str(chart_max))
    bar_symbol, cell_width = chart_layout(
        period, spaced_symbol=ATTEMPT_SYMBOL,
        compact_symbol=ATTEMPT_COMPACT_SYMBOL,
    )
    lines = [
        f"{title.upper()} · {start.isoformat()} to {end.isoformat()}",
        f"{unit.capitalize()} (lower = better)",
        "",
    ]

    for level in range(chart_max, 0, -1):
        cells = []
        for result in normalized:
            if (result.status == "solved" and result.attempts is not None
                    and result.attempts >= level):
                symbol = bar_symbol
            elif result.status == "dnf" and level == chart_max:
                symbol = "X"
            else:
                symbol = " "
            cells.append(symbol.rjust(cell_width))
        lines.append((f"{level:>{axis_width}} │" + "".join(cells)).rstrip())

    lines.append(" " * (axis_width + 1) + "└" + "─" * (cell_width * len(normalized)))
    lines.append(" " * (axis_width + 2) + _date_labels(normalized, cell_width))
    return "\n".join(lines)


def _format_number(value: float) -> str:
    """Show integral scores without a decimal, otherwise with one decimal."""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"


def _nice_ceiling(value: float) -> float:
    """Round a chart maximum up to a compact 1/2/5-style scale."""
    if value <= 0:
        return 1.0
    magnitude = 10.0 ** math.floor(math.log10(value))
    for multiplier in (1.0, 2.0, 5.0, 10.0):
        candidate = multiplier * magnitude
        if candidate >= value:
            return candidate
    return value


def _validate_score_results(daily_results: list[DailyScore],
                            start_date: date, end_date: date) -> list[DailyScore]:
    start = _as_date(start_date)
    end = _as_date(end_date)
    expected_days = (end - start).days + 1
    if end < start or len(daily_results) != expected_days:
        raise ValueError("daily_results must cover the inclusive date range exactly.")
    normalized: list[DailyScore] = []
    for offset, result in enumerate(daily_results):
        if not isinstance(result, DailyScore):
            raise TypeError(f"Expected DailyScore, got {type(result).__name__}")
        if _as_date(result.date) != start + timedelta(days=offset):
            raise ValueError("daily_results must be in chronological day order.")
        normalized.append(result)
    return normalized


def summarize_fixed_scores(daily_results: list[DailyScore],
                           default_maximum: float | None = None) -> str:
    """Summarize raw correct-answer/points history for fixed-score games."""
    played = [result for result in daily_results if result.status != "missing"]
    scored = [result for result in played if result.status == "score"]
    maximums = [result.maximum for result in scored if result.maximum is not None]
    denominator = max(maximums, default=default_maximum)
    if scored:
        average = sum(result.score for result in scored if result.score is not None) / len(scored)
        best = max(result.score for result in scored if result.score is not None)
        average_text = f"{average:.1f}/{_format_number(denominator)}" if denominator else f"{average:.1f}"
        best_text = f"{_format_number(best)}/{_format_number(denominator)}" if denominator else _format_number(best)
        perfect = sum(
            result.maximum is not None and result.score == result.maximum
            for result in scored
        )
    else:
        average_text = "—"
        best_text = "—"
        perfect = 0
    return "\n".join([
        f"Played: {len(played)}/{len(daily_results)} days",
        f"Avg: {average_text}",
        f"Best: {best_text}",
        f"Perfect: {perfect}",
    ])


def summarize_scaled_scores(daily_results: list[DailyScore], *, unit: str = "pts") -> str:
    """Summarize raw score history; chart scaling never alters these values."""
    played = [result for result in daily_results if result.status != "missing"]
    scored = [result for result in played if result.status == "score"]
    scores = [result.score for result in scored if result.score is not None]
    average = f"{_format_number(sum(scores) / len(scores))} {unit}" if scores else "—"
    best = f"{_format_number(max(scores))} {unit}" if scores else "—"
    return "\n".join([
        f"Played: {len(played)}/{len(daily_results)} days",
        f"Avg: {average}",
        f"Best: {best}",
    ])


def render_fixed_score_chart(daily_results: list[DailyScore], nominal_max: float | None,
                             start_date: date, end_date: date, *,
                             title: str = "Score history", unit: str = "score",
                             period: int = CHART_PERIOD_DAYS) -> str:
    """Render raw correct-answer scores with one row per positive score."""
    results = _validate_score_results(daily_results, start_date, end_date)
    values = [result.score for result in results if result.status == "score"
              and result.score is not None]
    maximums = [result.maximum for result in results if result.status == "score"
                and result.maximum is not None]
    chart_max = max(
        [int(nominal_max or 0), *[int(value) for value in values],
         *[int(value) for value in maximums]]
    )
    if chart_max < 1:
        chart_max = 1

    axis_width = len(str(chart_max))
    bar_symbol, cell_width = chart_layout(
        period, spaced_symbol=ATTEMPT_SYMBOL,
        compact_symbol=ATTEMPT_COMPACT_SYMBOL,
    )
    lines = [
        f"{title.upper()} · {start_date.isoformat()} to {end_date.isoformat()}",
        f"{unit.capitalize()} (higher = better)",
        "",
    ]

    for level in range(chart_max, 0, -1):
        cells = []
        for result in results:
            if (result.status == "score" and result.score is not None
                    and result.score >= level):
                symbol = bar_symbol
            elif result.status == "dnf" and level == chart_max:
                symbol = "X"
            else:
                symbol = " "
            cells.append(symbol.rjust(cell_width))
        lines.append((f"{level:>{axis_width}} │" + "".join(cells)).rstrip())

    lines.append(" " * (axis_width + 1) + "└" + "─" * (cell_width * len(results)))
    lines.append(" " * (axis_width + 2) + _date_labels(results, cell_width))
    return "\n".join(lines)


def render_scaled_score_chart(daily_results: list[DailyScore], nominal_max: float | None,
                              start_date: date, end_date: date, *,
                              title: str = "Score history", unit: str = "pts",
                              period: int = CHART_PERIOD_DAYS) -> str:
    """Render raw scores on a compact, dynamically scaled ten-row chart.

    Scores are rounded to the nearest visual bucket. A score in the lower half
    of the first bucket (for example 0–49 on a 0–1000 scale) has no bar, so a
    valid zero looks quiet rather than being mistaken for a positive score.
    """
    results = _validate_score_results(daily_results, start_date, end_date)
    chart_height = 10
    raw_max = max(
        [result.score for result in results if result.status == "score"
         and result.score is not None]
        + [nominal_max or 0]
    )
    scale_max = _nice_ceiling(max(raw_max, 1.0))
    bucket_width = scale_max / chart_height
    levels = {
        id(result): 0 if result.status != "score" or result.score is None else min(
            chart_height,
            math.floor(result.score / bucket_width + 0.5),
        )
        for result in results
    }

    axis_width = len(_format_number(scale_max))
    bar_symbol, cell_width = chart_layout(
        period, spaced_symbol=SCORE_SYMBOL,
        compact_symbol=SCORE_COMPACT_SYMBOL,
    )
    lines = [
        f"{title.upper()} · {start_date.isoformat()} to {end_date.isoformat()}",
        f"Raw {unit} (higher = better)",
        "",
    ]

    for level in range(chart_height, 0, -1):
        tick = scale_max * level / chart_height
        cells = []
        for result in results:
            if result.status == "score" and levels[id(result)] >= level:
                symbol = bar_symbol
            elif result.status == "dnf" and level == chart_height:
                symbol = "X"
            else:
                symbol = " "
            cells.append(symbol.rjust(cell_width))
        lines.append(
            f"{_format_number(tick):>{axis_width}} │" + "".join(cells).rstrip()
        )

    lines.append(" " * (axis_width + 1) + "└" + "─" * (cell_width * len(results)))
    lines.append(" " * (axis_width + 2) + _date_labels(results, cell_width))
    return "\n".join(lines)
