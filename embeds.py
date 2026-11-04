"""Embed builders: the consolidated daily board and the personal /missing checklist."""
import sqlite3
from datetime import datetime, timezone

import discord

import config
from games import ACTIVE_GAME_META, GRADED_GAMES, get_game_icon


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

    # Calculate Overall Daily MVP Points (1st = 3pts, 2nd = 2pts, 3rd = 1pt in games with >=2 players)
    mvp_points = {}
    names = {}  # uid -> display_name (points keyed by uid so same-named players don't merge)

    for (game, pid), entries in grouped.items():
        icon = get_game_icon(game)
        lines = []
        # Podium points pool: solved entries, plus every real score in graded games
        # (rank_score >= 10000 marks a zero/no-show result in graded games)
        graded = game in GRADED_GAMES
        pool = {e[3] for e in entries if e[2] == 1 or (graded and e[3] < 10000)}
        unique_scores = sorted(list(pool))

        for uid, uname, solved, rscore, dscore, url in entries:
            competes = solved or (graded and rscore < 10000)
            if competes:
                names[uid] = uname
                rank_idx = unique_scores.index(rscore)
                if len(entries) >= 2 and rank_idx < 3:
                    pts = 3 - rank_idx
                    mvp_points[uid] = mvp_points.get(uid, 0) + pts

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

    missing = [k for k in ACTIVE_GAME_META if k not in played]

    embed = discord.Embed(
        title=f"Today's checklist · {config.date_label(board_date)}",
        color=0x64748B
    )
    if not played:
        embed.description = "Nothing logged yet. Post your results in this channel."
    elif not missing:
        embed.description = f"All {len(ACTIVE_GAME_META)} games played today. See you tomorrow."

    if missing:
        lines = [f"{meta['icon']} **{name}** · [play]({meta['url']})" for name, meta in ACTIVE_GAME_META.items() if name in missing]
        embed.add_field(name=f"To play · {len(missing)}", value="\n".join(lines), inline=False)
    if played:
        lines = [f"{ACTIVE_GAME_META[name]['icon']} **{name}** · {played[name]}" for name in ACTIVE_GAME_META if name in played]
        embed.add_field(name=f"Done · {len(played)}", value="\n".join(lines), inline=False)

    return embed
