"""Fixed-attempt history model, retrieval and Unicode chart rendering.

This module is independent of Discord command handling. It reads only existing
canonical score rows and never changes rank_score, points, or difficulty data.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

import config
import games

AttemptStatus = Literal["solved", "dnf", "missing"]
# Fixed calendar-day window for the personal game history chart.
CHART_PERIOD_DAYS = 10
# Half-height blocks stay aligned in code blocks while leaving a visible seam
# between vertically stacked attempts, so 3/6 reads as three blocks.
ATTEMPT_SYMBOL = "▄"
_ATTEMPT_DISPLAY = re.compile(r"^([1-9]\d*)\s*/\s*([1-9]\d*)")
_DNF_DISPLAY = re.compile(r"^(?:dnf|x\s*/\s*([1-9]\d*))$", re.IGNORECASE)


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


def resolve_chart_game(user_id: int, selected_game: str,
                       start_date: date, end_date: date) -> tuple[str | None, list[str]]:
    """Resolve a chart game for one user and period.

    Returns ``(game, [])`` when one exact game can be used. For a base-name
    request with several variants, returns ``(None, variants)`` so the caller
    can ask for an exact variant instead of silently mixing them.
    """
    family = games.fixed_attempt_family(selected_game)
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
        if row[0] and games.fixed_attempt_family(row[0]) == family
    })
    exact = [name for name in candidates if name.casefold() == selected]
    if exact:
        return exact[0], []
    # A base-name request may use its sole played variant. An explicit variant
    # request must not silently substitute a different variant.
    if "(" in selected:
        return None, []
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
                         title: str = "Attempt history") -> str:
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
    cell_width = 2
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
                symbol = ATTEMPT_SYMBOL
            elif result.status == "dnf" and attempt == max_attempts:
                symbol = "X"
            else:
                symbol = " "
            cells.append(" " + symbol)
        lines.append((f"{attempt:>{axis_width}} │" + "".join(cells)).rstrip())

    lines.append(" " * (axis_width + 1) + "└" + "─" * (cell_width * len(normalized)))
    labels = [
        f"{result.date.day:02d}" if index % 4 == 0 else "  "
        for index, result in enumerate(normalized)
    ]
    lines.append((" " * (axis_width + 2) + "".join(labels)).rstrip())
    lines.append("")
    lines.append(f"{ATTEMPT_SYMBOL} = attempt · X = DNF · blank = no result")
    return "\n".join(lines)
