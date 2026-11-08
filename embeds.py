"""Embed builders: the consolidated daily board and the personal /missing checklist."""
import random
import re
import sqlite3
from datetime import datetime, timezone

import discord

import config
from games import ACTIVE_GAME_META, GRADED_GAMES, game_available_on, get_game_icon


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
    graded = game in GRADED_GAMES
    pool = {e[3] for e in entries if e[2] == 1 or (graded and e[3] < 10000)}
    unique_scores = sorted(list(pool))
    for uid, _uname, solved, rscore, _d, _u in entries:
        if uid == user_id:
            if solved or (graded and rscore < 10000):
                return f"{unique_scores.index(rscore) + 1}/{len(entries)}"
            return None
    return None


def compute_daily_points(board_date: str):
    """Daily podium points per user id (3/2/1 for top-3 placement in games with >=2 players)."""
    grouped = _entries_by_game(board_date)
    mvp_points = {}
    names = {}
    for (game, _pid), entries in grouped.items():
        graded = game in GRADED_GAMES
        pool = {e[3] for e in entries if e[2] == 1 or (graded and e[3] < 10000)}
        unique_scores = sorted(list(pool))
        for uid, uname, solved, rscore, _d, _u in entries:
            competes = solved or (graded and rscore < 10000)
            if competes:
                names[uid] = uname
                rank_idx = unique_scores.index(rscore)
                if len(entries) >= 2 and rank_idx < 3:
                    mvp_points[uid] = mvp_points.get(uid, 0) + (3 - rank_idx)
    return mvp_points, names


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

    # Daily MVP points (1st = 3pts, 2nd = 2pts, 3rd = 1pt in games with >=2 players)
    mvp_points, names = compute_daily_points(board_date)

    for (game, pid), entries in grouped.items():
        icon = get_game_icon(game)
        lines = []
        for uid, uname, solved, rscore, dscore, url in entries:
            duel_str = f" · [rematch]({url})" if url else ""
            lines.append(f"{uname} `{dscore}`{duel_str}")

        field_title = f"{icon} {game} {pid}"
        # Clamp to Discord's 1024-char field limit so a huge game can't kill the whole board
        clamp = lambda v: v if len(v) <= 1024 else v[:1021] + "…"
        if layout == "rows":
            embed.add_field(name=field_title, value=clamp(" · ".join(lines)), inline=False)
        else:
            embed.add_field(name=field_title, value=clamp("\n".join(lines)), inline=True)

    # Add Daily Standings Footer/Summary if competitive games exist
    if mvp_points:
        standings = sorted(mvp_points.items(), key=lambda x: x[1], reverse=True)
        standings_str = " · ".join([f"{names[u]} `{p}`" for u, p in standings])
        embed.add_field(name="Today's points (🥇 = 3 pts · 🥈 = 2 pts · 🥉 = 1 pt)", value=standings_str, inline=False)

    return embed


def _performance_fraction(game: str, solved: int, rank_score: float, display_score: str) -> float:
    """Map one result to a roughly comparable 0..1 outcome strength, for daily difficulty.

    Correct ratios ("18/30", "199/500") are used verbatim. Score-based percent
    games follow their percentage. Other games rank by puzzle constraints:
    first tries approach 1, guess counts reduce it. This is a heuristic for the
    day's recap, not a universal measure of player skill.
    """
    dscore = (display_score or "").strip()
    # Only genuine scoring games treat x/y as a score ratio. Wordle's 1/6 is a first try.
    if game in {"Trivmount", "Thursday Thirty", "Songless", "Centumth", "Majority"} or game.startswith("Magnitudle"):
        ratio = re.match(r"(\d+)/([1-9]\d*)", dscore)
        if ratio:
            correct, total = int(ratio.group(1)), int(ratio.group(2))
            return max(0.0, min(1.0, correct / total))
    if not solved:
        return 0.0
    if game.startswith("Roughly"):
        return max(0.0, min(1.0, -rank_score / 100))
    if game == "Travle":
        return 1 / max(1.0, 1 + rank_score)
    if game in {"Metazooa", "Globle", "Redactle"}:
        return 1 / max(1.0, abs(rank_score))
    # Guess-type games: tries (and hint penalties) translate through a 6-point scale.
    return max(0.0, min(1.0, (7 - rank_score) / 6))


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2


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
        ),
        "second": (
            f"{name} lands second with `{pts}` pts. Excellent hostilities resume tomorrow.",
            f"{name}, silver today. Close enough to taste the victory snacks.",
        ),
        "second_last": (
            f"{name} narrowly escapes last. That's a victory with slightly worse marketing.",
            f"{name} finishes just above bottom. Staying out of the basement lighting the way.",
        ),
        "middle": (
            f"{name} finishes at `{pts}` pts. A middle-of-the-pack diplomat.",
            f"Not first, not last. {name} brings respectable balance to the group.",
        ),
        "last": (
            f"{name} brings up the rear and keeps the group together. Teamwork matters.",
            f"{name} finishes with `{pts}` pts. Already plotting the triumphant comeback.",
        ),
    }
    return random.Random(f"{board_date}:line").choice(lines[kind])


def build_wrap_embed(board_date: str) -> discord.Embed | None:
    """Locked-day wrap: turnout, game difficulty, final standings and winner's trophy."""
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

    # Relative daily difficulty: median normalized result quality per game.
    # Solve flags alone cannot distinguish an easy 5/6 day from a perfect first try.
    rates = []
    for (game, _pid), entries in grouped.items():
        # A one-person game says nothing about relative daily difficulty.
        if len(entries) < 2:
            continue
        outcomes = sorted(
            _performance_fraction(game, solved, rscore, dscore)
            for _uid, _uname, solved, rscore, dscore, _url in entries
        )
        rates.append((game, _median(outcomes), len(entries)))
    hits = [(name, pct, n) for name, pct, n in rates if pct > 0]
    if hits:
        highest, lowest = max(r[1] for r in hits), min(r[1] for r in hits)
        render = lambda pct: f"`{pct:.0%}`"
        easiest = " / ".join(f"**{r[0]}** {render(r[1])}" for r in hits if r[1] == highest)
        hardest = " / ".join(f"**{r[0]}** {render(r[1])}" for r in hits if r[1] == lowest)
        if highest != lowest:
            embed.add_field(name="Game difficulty · median performance",
                            value=f"Easiest: {easiest}\nHardest: {hardest}", inline=False)

    standings = sorted(mvp_points.items(), key=lambda x: (-x[1], names.get(x[0], '')) if mvp_points else [])
    if standings:
        standings_str = " · ".join([f"{names[u]} `{p}`" for u, p in standings])
        embed.add_field(name="Final standings", value=standings_str, inline=False)

        # One random placement commenter for the wrap, replacing separate
        # winner-callout and last-place fields.
        embed.add_field(name="\u200b", value=_wrap_comment(board_date, names, standings), inline=False)
    else:
        solo_players = sorted({uname for entries in grouped.values()
                               for _uid, uname, _s, _r, _d, _u in entries})
        embed.add_field(name="\u200b", value="No points on the board. " + ", ".join(solo_players) + " played.", inline=False)
    return embed


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

    if missing:
        lines = [f"{meta['icon']} **{name}** · [play]({meta['url']})" for name, meta in ACTIVE_GAME_META.items() if name in missing]
        embed.add_field(name=f"To play · {len(missing)}", value="\n".join(lines), inline=False)
    if played:
        lines = [f"{ACTIVE_GAME_META[name]['icon']} **{name}** · {played[name]}" for name in ACTIVE_GAME_META if name in played]
        embed.add_field(name=f"Done · {len(played)}", value="\n".join(lines), inline=False)

    return embed
