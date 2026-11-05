"""Embed builders: the consolidated daily board and the personal /missing checklist."""
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


def _wrap_last_line(board_date: str, player_name: str) -> str:
    """Gentle closing quip for the last-placed player, deterministic for a given day."""
    quips = (
        "{name}, you kept the others in line today. Teamwork matters.",
        "A brave bottom-place finish by {name}. Every group needs a hero who finished.",
        "{name} made sure silver looked especially shiny today.",
        "Not everyone can be first. {name} found a different way to contribute.",
        "Tomorrow has 'comeback' written all over it, {name}.",
    )
    return quips[sum(ord(c) for c in board_date) % len(quips)].format(name=player_name)


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

    # Relative daily difficulty: solve rate per game (solved / players who posted it).
    # This is intentionally not rank_score, since units vary across games.
    rates = []
    for (game, _pid), entries in grouped.items():
        total = len(entries)
        solved = sum(1 for e in entries if e[2] == 1)
        rates.append((game, solved, total, solved / total))
    rates.sort(key=lambda r: (r[3], r[0]))
    highest, lowest = max(r[3] for r in rates), min(r[3] for r in rates)
    if highest != lowest:
        easiest = " / ".join(f"**{r[0]}** `{r[3]:.0%}`" for r in rates if r[3] == highest)
        hardest = " / ".join(f"**{r[0]}** `{r[3]:.0%}`" for r in rates if r[3] == lowest)
        embed.add_field(name="Difficulty by solve rate", value=f"Easiest: {easiest}\nHardest: {hardest}", inline=False)

    standings = sorted(mvp_points.items(), key=lambda x: (-x[1], names.get(x[0], '')) if mvp_points else [])
    if standings:
        standings_str = " · ".join([f"{names[u]} `{p}`" for u, p in standings])
        embed.add_field(name="Final standings (🥇 3 · 🥈 2 · 🥉 1)", value=standings_str, inline=False)

        best = standings[0][1]
        winners = [names[u] for u, p in standings if p == best]
        label = " and ".join(winners)
        verb = "split" if len(winners) > 1 else "takes"
        embed.add_field(name="\u200b", value=f"🏆 {label} {verb} the day with `{best}` pts.", inline=False)

        last_id, last_pts = standings[-1]
        embed.add_field(name="\u200b", value=_wrap_last_line(board_date, names[last_id]), inline=False)
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
