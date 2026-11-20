"""Embed builders: the consolidated daily board and the personal /missing checklist."""
import random
import re
import sqlite3
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

import discord

import config
import db
import difficulty
from games import ACTIVE_GAME_META, game_available_on, get_game_icon, is_ranked_result

_RATIO_MEDIAN_GAMES = {
    "Centumth", "History in Order", "Magnitudle", "Majority",
    "Songless", "Songspot", "Thursday Thirty", "Trivmount",
}
_ATTEMPT_MEDIAN_GAMES = {
    "Chessle", "Flagle", "Mathle", "Regionle", "Tradle", "Wordle", "Worldle",
}
_GUESS_COUNT_MEDIAN_GAMES = {"Globle", "Metazooa", "Redactle"}
_RATIO_DISPLAY = re.compile(r"^\s*(\d+|X)\s*/\s*([1-9]\d*)", re.IGNORECASE)
_GUESS_COUNT_DISPLAY = re.compile(r"(\d+)\s*(?:guesses|g)\b", re.IGNORECASE)
_POINTS_DISPLAY = re.compile(r"^([\d,]+)\s*pts$", re.IGNORECASE)


def _entries_by_game(board_date: str):
    """Score rows for a date, grouped (game, puzzle_id) -> list of tuples."""
    with sqlite3.connect(config.DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT game, puzzle_id, user_id, user_name, solved, rank_score, display_score, extra_url
            FROM scores
            WHERE board_date = ?
            ORDER BY game ASC, rank_score ASC, timestamp ASC
        """, (board_date,))
        rows = c.fetchall()
    grouped = {}
    for game, pid, uid, uname, solved, rscore, dscore, url in rows:
        grouped.setdefault((game, pid), []).append((uid, uname, solved, rscore, dscore, url))
    return grouped


def placement_of(board_date: str, game: str, puzzle_id: str, user_id: int) -> str | None:
    """User's placement in one game today, e.g. '1/3' (ties share the rank).
    None if the user is outside the competing pool (DNF in elimination games)."""
    grouped = _entries_by_game(board_date)
    entries = grouped.get((game, puzzle_id))
    if not entries:
        return None
    pool = {e[3] for e in entries if is_ranked_result(game, e[2], e[3])}
    unique_scores = sorted(list(pool))
    for uid, _uname, solved, rscore, _d, _u in entries:
        if uid == user_id:
            if is_ranked_result(game, solved, rscore):
                return f"{unique_scores.index(rscore) + 1}/{len(entries)}"
            return None
    return None


def compute_daily_points(board_date: str):
    """Daily podium points per user id (3/2/1 for top-3 placement in games with >=2 players)."""
    grouped = _entries_by_game(board_date)
    mvp_points = {}
    names = {}
    # Voluntary anti-luck rule: record the sentence, not erase the result.
    # Jailed players may still rank per game, but their daily total is exactly zero.
    jailed = db.jailed_users(board_date) if config.PRISON_ENABLED else {}
    for uid, uname in jailed.items():
        mvp_points[uid] = 0.0
        names[uid] = uname

    for (game, _pid), entries in grouped.items():
        pool = {e[3] for e in entries if is_ranked_result(game, e[2], e[3])}
        unique_scores = sorted(list(pool))
        for uid, uname, solved, rscore, _d, _u in entries:
            competes = is_ranked_result(game, solved, rscore)
            if competes:
                names[uid] = uname
                rank_idx = unique_scores.index(rscore)
                if uid not in jailed and len(entries) >= 2 and rank_idx < 3:
                    mvp_points[uid] = mvp_points.get(uid, 0) + (3 - rank_idx)
    return mvp_points, names


def _append_daily_fields(embed: discord.Embed, candidates: list[tuple[str, str, bool]]):
    """Fit the board within Discord's field count and total character limits.

    Keep the normal fields that fit, put overflow into one compact notice rather than
    silently letting Discord reject every future board update. Token-heavy callers are
    budgeted too, including the final points legend.
    """
    remaining = 6000 - len(embed.title or "") - len(embed.description or "")
    overflow = []
    for name, value, inline in candidates:
        # Per-field value cap too, not just the overall embed-size budget.
        if len(value) > 1024:
            value = value[:1021] + "…"
        field_size = len(name) + len(value)
        # Keep one field slot for the overflow notice.
        if len(embed.fields) >= 24 or field_size > remaining:
            overflow.append((name, value, inline))
            continue
        embed.add_field(name=name, value=value, inline=inline)
        remaining -= field_size

    if not overflow:
        return

    # Never throw an embed-size error when the board exceeds capacity. Truncation is
    # explicit to users, and scores remain intact in the database, not dropped there.
    if remaining < 80 and len(embed.fields) < 25:
        embed.add_field(
            name="Shown within Discord limits",
            value=f"{len(overflow)} more result groups didn't fit on today's board.",
            inline=False,
        )
        return

    text_blocks = []
    for name, value, _inline in overflow:
        text_blocks.append(f"{name}\n{value}")
    text = "\n\n".join(text_blocks)
    notice = f"\n\n(+ {len(overflow)} more result groups didn't fit on today's board.)"
    limit = max(0, min(1024, remaining) - len(notice) - 1)
    if text and limit > 20 and len(embed.fields) < 25:
        clipped = text[:limit]
        if len(clipped) < len(text):
            clipped = clipped.rsplit("\n", 1)[0] + "…"
        embed.add_field(name="More results", value=clipped + notice, inline=False)
    elif len(embed.fields) < 25:
        embed.add_field(name="Shown within Discord limits", value=f"{len(overflow)} more result groups.", inline=False)


def build_daily_embed(board_date: str, layout: str = "grid") -> discord.Embed:
    """Constructs the single consolidated Daily Leaderboard Embed for a given date."""
    with sqlite3.connect(config.DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT game, puzzle_id, user_id, user_name, solved, rank_score, display_score, extra_url
            FROM scores
            WHERE board_date = ?
            ORDER BY game ASC, rank_score ASC, timestamp ASC
        """, (board_date,))
        rows = c.fetchall()

    embed = discord.Embed(
        title=f"🌅 Daily digest · {config.date_label(board_date)}",
        description="Drop your raw game results in this channel. They get logged here and tidied away.",
        color=0xF59E0B,
        timestamp=datetime.now(timezone.utc)
    )

    if not rows:
        embed.add_field(name="No scores yet", value="Post a result to start the board.", inline=False)
        return embed

    # Group by (game, puzzle_id)
    grouped = {}
    for game, pid, uid, uname, solved, rscore, dscore, url in rows:
        key = (game, pid)
        grouped.setdefault(key, []).append((uid, uname, solved, rscore, dscore, url))

    candidates = []
    for (game, pid), entries in grouped.items():
        icon = get_game_icon(game)
        lines = []
        for uid, uname, solved, rscore, dscore, url in entries:
            # Roughly duel invitations aren't shown on the shared daily board.
            duel_str = f" · [rematch]({url})" if url and not game.startswith("Roughly") else ""
            lines.append(f"{uname} `{dscore}`{duel_str}")

        field_title = f"{icon} {game} {pid}"
        # Per-value cap, then total budget (plus footer), so one busy day can't kill the board.
        clamp = lambda v: v if len(v) <= 1024 else v[:1021] + "…"
        value = " · ".join(lines) if layout == "rows" else "\n".join(lines)
        candidates.append((field_title, clamp(value), layout != "rows"))

    # Daily MVP points are budgeted as one field like any other, not appended ad hoc.
    mvp_points, names = compute_daily_points(board_date)

    # Add Daily Standings Footer/Summary if competitive games exist
    if mvp_points:
        standings = sorted(mvp_points.items(), key=lambda x: x[1], reverse=True)
        standings_str = " · ".join([f"{names[u]} `{p}`" for u, p in standings])
        candidates.append(("Today's points (🥇 = 3 pts · 🥈 = 2 pts · 🥉 = 1 pt)", standings_str, False))

    _append_daily_fields(embed, candidates)
    return embed


# The historical percentile engine owns difficulty computation. This module only
# renders its results and never re-derives a local normalized difficulty scale.
_DIFFICULTY_NOTE = "Higher percentile = easier than usual for the group."
_CLOSING_FIELD_NAME = "Closing remark"


def _median(values: Sequence[float]) -> float:
    """Arithmetic median; the caller supplies at least one finite value."""
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _format_native_number(value: float) -> str:
    """Keep native medians compact, allowing fractional values without trailing .0."""
    rounded = round(value, 1)
    return str(int(rounded)) if rounded.is_integer() else f"{rounded:.1f}"


def _native_median(game: str, entries: list[tuple]) -> str | None:
    """Return the day's median native score from readable display results.

    This is presentation only: it does not feed the historical percentile,
    leaderboard ordering, or points.
    """
    base_game = game.split(" (", 1)[0]
    displays = [(entry[4] or "").strip() for entry in entries]
    if base_game in _RATIO_MEDIAN_GAMES:
        denominators = set()
        numerators = []
        for display in displays:
            match = _RATIO_DISPLAY.match(display)
            if not match or match.group(1).upper() == "X":
                continue
            numerators.append(int(match.group(1)))
            denominators.add(int(match.group(2)))
        if len(denominators) != 1 or not numerators:
            return None
        denominator = denominators.pop()
        return f"{_format_native_number(_median(numerators))}/{denominator}"

    if base_game in _ATTEMPT_MEDIAN_GAMES:
        denominators = set()
        attempts = []
        for display in displays:
            match = _RATIO_DISPLAY.match(display)
            if not match:
                continue
            denominator = int(match.group(2))
            if match.group(1).upper() == "X":
                attempts.append(denominator + 1)
            else:
                attempts.append(int(match.group(1)))
            denominators.add(denominator)
        if len(denominators) != 1 or not attempts:
            return None
        denominator = denominators.pop()
        median = _median(attempts)
        if median > denominator:
            return f"X/{denominator}"
        return f"{_format_native_number(median)}/{denominator}"

    if base_game in _GUESS_COUNT_MEDIAN_GAMES:
        guesses = [int(match.group(1)) for display in displays
                   if (match := _GUESS_COUNT_DISPLAY.search(display))]
        if not guesses:
            return None
        return f"{_format_native_number(_median(guesses))} guesses"

    if base_game == "Maptap":
        points = []
        for display in displays:
            match = _POINTS_DISPLAY.match(display)
            if match:
                points.append(int(match.group(1).replace(",", "")))
        if not points:
            return None
        return f"{int(_median(points)):,} pts"

    return None


def _round_percentile(value: float) -> int:
    """Display-only whole-number percentile, clamped to the historical 0-100 range."""
    return max(0, min(100, int(float(value) + 0.5)))


def _ordinal(number: int) -> str:
    """English ordinal suffix, including the 11th/12th/13th exceptions."""
    if 10 <= number % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def _difficulty_label(game: str, variant: str | None, puzzle_id: str | None = None) -> str:
    """Concise game label; variant and puzzle id only when they add identity."""
    label = f"{game} ({variant})" if variant else game
    return f"{label} {puzzle_id}" if puzzle_id else label


def _difficulty_line(label: str, percentile: float, count: int, noun: str,
                     median: str | None = None) -> str:
    parts = [
        f"**{label}**",
        f"`{_ordinal(_round_percentile(percentile))}` percentile",
    ]
    if median:
        parts.append(f"median `{median}`")
    noun_form = noun if count == 1 else f"{noun}s"
    parts.append(f"`{count}` {noun_form}")
    return " · ".join(parts)


def _daily_difficulty_text(results: list[dict], board_date: str) -> str | None:
    """One factual easiest/hardest pair from the engine's ordered daily results."""
    if len(results) < 2:
        return None
    easiest, hardest = results[0], results[-1]
    if easiest["percentile"] == hardest["percentile"]:
        # No contrast to report: one percentile value is not an easiest/hardest pair.
        return None

    grouped = _entries_by_game(board_date)
    instances = {}
    for item in results:
        key = (item["game"], item.get("variant"))
        instances[key] = instances.get(key, 0) + 1

    def label(item: dict) -> str:
        game, variant = item["game"], item.get("variant")
        # A repeated game+variant needs its puzzle id to disambiguate the entry.
        puzzle_id = item.get("puzzle_id") if instances[(game, variant)] > 1 else None
        return _difficulty_label(game, variant, puzzle_id)

    def native_median(item: dict) -> str | None:
        entries = grouped.get((item["game"], item.get("puzzle_id")), [])
        return _native_median(item["game"], entries)

    return "\n".join([
        "Easiest: " + _difficulty_line(
            label(easiest), easiest["percentile"], int(easiest.get("players", 0)),
            "player", native_median(easiest),
        ),
        "Hardest: " + _difficulty_line(
            label(hardest), hardest["percentile"], int(hardest.get("players", 0)),
            "player", native_median(hardest),
        ),
        _DIFFICULTY_NOTE,
    ])


def _weekly_difficulty_text(results: list[dict]) -> str | None:
    """One factual easiest/hardest pair from the engine's qualifying weekly variants."""
    minimum = getattr(config, "DIFFICULTY_MIN_WEEKLY_PUZZLES", 2)
    qualified = [item for item in results if int(item.get("instances", 0)) >= minimum]
    if len(qualified) < 2:
        return None
    easiest, hardest = qualified[0], qualified[-1]
    if easiest["percentile"] == hardest["percentile"]:
        return None

    def label(item: dict) -> str:
        return _difficulty_label(item["game"], item.get("variant"))

    return "\n".join([
        "Easiest: " + _difficulty_line(
            label(easiest), easiest["percentile"], int(easiest["instances"]), "puzzle"
        ),
        "Hardest: " + _difficulty_line(
            label(hardest), hardest["percentile"], int(hardest["instances"]), "puzzle"
        ),
        _DIFFICULTY_NOTE,
    ])


def _prison_group(start_date: str, end_date: str):
    """Optional field listing who went to prison over a day or week, or None."""
    rows = db.prison_breakdown(start_date, end_date)
    if not rows:
        return None
    label = "Prisoners" if start_date == end_date else "Prisoners (days)"
    lines = []
    for _name, _uid, days in rows:
        noun = "day" if days == 1 else "days"
        lines.append(f"{_name} · {days} {noun}")
    return label, "\n".join(lines)


def _wrap_comment(board_date: str, names: dict[int, str], standings: list[tuple[int, int]]) -> str:
    """One playful placement comment for the day, selected deterministically.

    Targets any placement, not only winner and last. Immutable for a given day's wrap.
    """
    if not standings:
        return ""
    pool = [idx for idx in range(len(standings))]
    idx = random.Random(f"{board_date}:placement").choice(pool)
    uid, pts = standings[idx]
    name = names.get(uid, "Someone")
    last = len(standings) - 1

    kinds = []
    if idx == 0:
        kinds.append("first")
    if idx == 1 and len(standings) > 2:
        kinds.append("second")
    if idx == len(standings) - 2:
        kinds.append("second_last")
    if idx == last and len(standings) > 1:
        kinds.append("last")
    if not kinds:
        kinds.append("middle")
    kind = random.Random(f"{board_date}:kind").choice(kinds)

    lines = {
        "first": (
            f"🏆 {name} takes the day with `{pts}` pts. Tiny victory dance time.",
            f"🏆 {name} wins the day with `{pts}` pts. Rematch pending, obviously.",
            f"🏆 {name} holds the crown with `{pts}` pts. What an entirely planned outcome.",
            f"🏆 {name}, today's champion. And they said casual gaming couldn't get serious.",
            f"{name} takes first. The victory speech has already exceeded the channel limit.",
            f"{name} wins with `{pts}` pts. Please return the borrowed brain cells before tomorrow.",
            f"First place for {name}. The rest of us were clearly collecting research data.",
            f"{name} tops the board. A suspicious amount of competence for a casual pastime.",
            f"{name}, enjoy the lead. Tomorrow's puzzles have not agreed to cooperate.",
        ),
        "second": (
            f"{name} lands second with `{pts}` pts. Excellent hostilities resume tomorrow.",
            f"{name}, silver today. Close enough to taste the victory snacks.",
            f"{name} finishes second with `{pts}` pts. One tiny rematch from a narrative correction.",
            f"{name}, one spot short of glory and one *rematch* from fixing it.",
            f"{name} takes second. Basically first, if you ignore one inconvenient person.",
            f"{name}, close enough to win in the version of events you tell tomorrow.",
            f"Second for {name}. The silver lining is unusually literal today.",
            f"{name} finishes on `{pts}` pts. One more good guess and this becomes a very different speech.",
            f"{name}, an excellent result with just enough disappointment to encourage a rematch.",
        ),
        "second_last": (
            f"{name} narrowly escapes last. That's a victory with slightly worse marketing.",
            f"{name} finishes just above bottom. Staying out of the basement lighting the way.",
            f"{name} avoided the basement by a whisker. Not quite last, oddly satisfying.",
            f"{name}, this close to last but separated by the luxurious distinction of one other person.",
            f"{name} avoids last. Technically a survival story, not a success story.",
            f"{name}, one place above disaster. Excellent use of the available buffer.",
            f"{name} escapes the wooden spoon. Please stop checking whether the scores are final.",
            f"Not last for {name}. The celebration is small, but legally valid.",
            f"{name}, the person below you would like a word about your victory dance.",
        ),
        "middle": (
            f"{name} finishes at `{pts}` pts. A middle-of-the-pack diplomat.",
            f"Not first, not last. {name} brings respectable balance to the group.",
            f"{name} gets no medal ceremony today, just the quiet promise of future escalation.",
            f"{name} finished mid-pack with `{pts}` pts. Close enough to the summit to hear the laughter.",
            f"{name} occupies the middle. A strategic position from which to blame both ends.",
            f"{name}, neither a victory lap nor a rescue mission. Efficient moderation.",
            f"`{pts}` pts for {name}. The statistical equivalent of a sensible cardigan.",
            f"{name} keeps the leaderboard structurally balanced. Somebody has to.",
            f"{name}, safely in the middle: close to the action, far from the paperwork.",
        ),
        "last": (
            f"Not everyone can be first. {name} found a different way to contribute.",
            f"A brave bottom-place finish by {name}. Every group needs a hero who finished.",
            f"{name} brings up the rear and keeps the group together. Teamwork matters.",
            f"{name} finishes with `{pts}` pts. Already plotting the triumphant comeback.",
            f"{name} accepted the wooden spoon with grace and an inconvenient rematch request.",
            f"{name} has truly mastered the art of giving everyone else a confidence boost.",
            f"{name} takes last. A generous donation to everyone else's confidence.",
            f"{name}, today's scores have been filed under character development.",
            f"Last place for {name}. The comeback now has a properly dramatic opening chapter.",
            f"{name} gets `{pts}` pts and unlimited material for a revenge arc.",
            f"{name}, even the bottom of the table is still on the table.",
        ),
    }
    neutral = (
        f"{name}, did you know octopuses have three hearts? None of them has to endure this leaderboard.",
        f"{name}, did you know sharks predate trees? Your rematch can probably wait until tomorrow.",
        f"{name}, did you know wombats produce cube-shaped droppings? That's today's unrelated fact. You're welcome.",
        f"{name}, die Punkte sind gezählt. Beschwerden bitte in dreifacher Ausfertigung.",
    )
    return random.Random(f"{board_date}:line").choice(lines[kind] + neutral)


def _wrap_standings_lines(standings: list[tuple[int, int | float]], names: dict[int, str], grouped) -> list[str]:
    """Format each standing with played puzzle results and informational points per game."""
    played_counts = {uid: 0 for uid, _points in standings}
    for entries in grouped.values():
        # One group is one native puzzle result, even if inconsistent data repeats a user.
        for uid in {entry[0] for entry in entries}:
            if uid in played_counts:
                played_counts[uid] += 1

    lines = []
    for uid, points in standings:
        played = played_counts[uid]
        average = points / played if played else 0.0
        game_noun = "game" if played == 1 else "games"
        display_name = re.sub(r"\s+", " ", names.get(uid, "Someone")).strip() or "Someone"
        safe_name = discord.utils.escape_mentions(discord.utils.escape_markdown(display_name))
        lines.append(
            f"{safe_name} `{points}` pts · `{played}` {game_noun} · `{average:.1f}` pts/game"
        )
    return lines


def build_wrap_embed(board_date: str) -> discord.Embed | None:
    """Locked-day wrap: turnout, game difficulty, final standings and one placement comment."""
    grouped = _entries_by_game(board_date)
    if not grouped:
        return None
    mvp_points, names = compute_daily_points(board_date)

    embed = discord.Embed(
        title=f"🏆 Yesterday's wrap · {config.date_label(board_date)}",
        color=0xF59E0B,
    )

    players = {uid for entries in grouped.values() for uid, *_ in entries}
    game_names = {game for game, _pid in grouped}
    embed.add_field(name="Turnout", value=f"{len(players)} players · {len(game_names)} games", inline=False)

    police = _prison_group(board_date, board_date)
    if police is not None:
        embed.add_field(name=police[0], value=police[1], inline=False)

    # Historical difficulty compares each puzzle with the group's own pre-date results.
    # The analysis engine owns eligibility, ordering and percentile math.
    difficulty_text = _daily_difficulty_text(
        difficulty.analyze_day(board_date), board_date
    )
    if difficulty_text:
        _append_daily_fields(embed, [("Historical difficulty", difficulty_text, False)])

    standings = sorted(mvp_points.items(), key=lambda x: (-x[1], names.get(x[0], '')) if mvp_points else [])
    has_points_contest = len(players) > 1 and any(points > 0 for _uid, points in standings)
    if has_points_contest:
        standings_fields = _checklist_fields(
            "Final standings", _wrap_standings_lines(standings, names, grouped)
        )

        # Keep the existing date-seeded target and line variety as the sole punchline.
        candidates = [*standings_fields,
                      (_CLOSING_FIELD_NAME,
                       _wrap_comment(board_date, names, standings), False)]
        _append_daily_fields(embed, candidates)
    else:
        solo_players = sorted({uname for entries in grouped.values()
                               for _uid, uname, _s, _r, _d, _u in entries})
        safe_players = [
            discord.utils.escape_mentions(discord.utils.escape_markdown(name))
            for name in solo_players
        ]
        embed.add_field(
            name="Practice day",
            value="No points awarded. " + ", ".join(safe_players) + " played.",
            inline=False,
        )
    return embed


def build_weekly_embed(days: int = 7) -> discord.Embed | None:
    """Weekly recap, ranking only results from the inclusive window.
    Returns None if the period has no results; doesn't write to the DB.
    """
    end_text = config.today_str()
    end_dt = datetime.strptime(end_text, "%Y-%m-%d")
    start_date = (end_dt - timedelta(days=days - 1)).strftime("%Y-%m-%d")

    grouped = {}
    with sqlite3.connect(config.DB_PATH) as conn:
        rows = conn.execute(
            "SELECT board_date, game, puzzle_id, user_id, user_name, solved, rank_score, display_score, extra_url "
            "FROM scores WHERE board_date BETWEEN ? AND ?",
            (start_date, end_text)
        ).fetchall()
    if not rows:
        return None

    for _date, game, pid, uid, uname, solved, rscore, dscore, url in rows:
        grouped.setdefault((game, pid), []).append((uid, uname, solved, rscore, dscore, url))

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    # Sum the daily podiums rather than ranking every date as one "competitive"
    # puzzle: this exactly preserves native scoring and cannot create a two-player
    # competition from a single author's results across days.
    totals, names = {}, {}
    for offset in range((end_dt - start_dt).days + 1):
        date_text = (start_dt + timedelta(days=offset)).strftime("%Y-%m-%d")
        daily_points, daily_names = compute_daily_points(date_text)
        for uid, points in daily_points.items():
            if points:
                totals[uid] = totals.get(uid, 0.0) + points
                names[uid] = daily_names[uid]

    counters = {uid for entries in grouped.values() for uid, *_ in entries}
    game_names = {g for g, _ in grouped}
    days_count = len({row[0] for row in rows})
    embed = discord.Embed(
        title=f"🏆 Weekly recap · {config.date_label(end_text)}",
        description=f"{start_date} to {end_text} (inclusive)",
        color=0xF59E0B,
    )
    embed.add_field(
        name="Turnout",
        value=f"{len(counters)} players · {len(game_names)} games · {days_count} active days",
        inline=False
    )
    police = _prison_group(start_date, end_text)
    if police is not None:
        embed.add_field(name=police[0], value=police[1], inline=False)

    # Historical weekly difficulty: each puzzle scored against its own earlier-date
    # baseline, then averaged per game/variant. No local median or native guess scale.
    weekly_difficulty = _weekly_difficulty_text(difficulty.analyze_week(end_text, days))
    if weekly_difficulty:
        embed.add_field(name="Historical difficulty", value=weekly_difficulty, inline=False)

    ordered = sorted(totals.items(), key=lambda kv: (-kv[1], names[kv[0]]))
    standings = " · ".join(f"{names[u]} `{p}`" for u, p in ordered) if ordered else "No podium points yet. See you tomorrow."
    embed.add_field(name="Weekly points", value=standings, inline=False)
    return embed


def _checklist_fields(base_name: str, lines: list[str]) -> list[tuple[str, str, bool]]:
    """Render one checklist section, partitioning at game-line boundaries when needed.

    Short sections keep their historical single-field name, so ordinary /missing
    output is unchanged. A section too long for one field's value limit becomes
    consecutive fields titled "<base_name> (1/N)", "<base_name> (2/N)", ... Each
    game line stays intact, including its Markdown and link, and keeps its original
    order. Only an individual impossible line is clamped with the same safe
    ellipsis rule used elsewhere, rather than dropping content unnoticed.
    """
    if not lines:
        return []

    def clamp(line: str) -> str:
        return line if len(line) <= 1024 else line[:1021] + "…"

    # Fast path: unchanged rendering for lists that fit in one field.
    value = "\n".join(lines)
    if len(value) <= 1024:
        return [(base_name, value, False)]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for raw_line in lines:
        line = clamp(raw_line)
        added = len(line) if not current else len(line) + 1  # newline separator
        if current and current_len + added > 1024:
            chunks.append("\n".join(current))
            current, current_len = [line], len(line)
        else:
            current.append(line)
            current_len += added
    if current:
        chunks.append("\n".join(current))

    total = len(chunks)
    return [
        (f"{base_name} ({index}/{total})", chunk, False)
        for index, chunk in enumerate(chunks, 1)
    ]


def build_missing_embed(user_id: int) -> discord.Embed:
    """Personal daily checklist: games played today vs. still to play (with links)."""
    board_date = config.today_str()
    with sqlite3.connect(config.DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT game, display_score FROM scores WHERE board_date = ? AND user_id = ?",
            (board_date, user_id)
        )
        played_rows = c.fetchall()

    played = {}  # base game key -> display_score (submodes collapse to their base game)
    for game, dscore in played_rows:
        for key in ACTIVE_GAME_META:
            if game.startswith(key):
                played.setdefault(key, dscore)

    # Scheduled games (e.g. Thursday Thirty) only count as "missing" on their play days
    weekday = datetime.strptime(board_date, "%Y-%m-%d").weekday()
    missing = [k for k in ACTIVE_GAME_META if k not in played and game_available_on(k, weekday)]
    available_today = sum(1 for k in ACTIVE_GAME_META if game_available_on(k, weekday))

    embed = discord.Embed(
        title=f"Today's checklist · {config.date_label(board_date)}",
        color=0x64748B
    )
    if not played:
        embed.description = "Nothing logged yet. Post your results in this channel."
    elif not missing:
        embed.description = f"All {available_today} games played today. See you tomorrow."

    candidates = []
    if missing:
        lines = [f"{meta['icon']} **{name}** · [play]({meta['url']})" for name, meta in ACTIVE_GAME_META.items() if name in missing]
        candidates.extend(_checklist_fields(f"To play · {len(missing)}", lines))
    if played:
        lines = [f"{ACTIVE_GAME_META[name]['icon']} **{name}** · {played[name]}" for name in ACTIVE_GAME_META if name in played]
        candidates.extend(_checklist_fields(f"Done · {len(played)}", lines))
    # One call keeps both sections inside the same field-count/total-size budget.
    _append_daily_fields(embed, candidates)

    return embed
