"""Slash commands. register(bot) attaches them to the command tree."""
import re
import sqlite3

import discord
from discord import app_commands

import config
import db
import embeds
import handlers
from config import today_str
from games import ACTIVE_GAME_META, get_game_icon


async def h2h(interaction: discord.Interaction, opponent: discord.Member, player1: discord.Member = None):
    p1 = player1 or interaction.user
    p2 = opponent

    with sqlite3.connect(config.DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT a.game, a.rank_score, b.rank_score
            FROM scores a
            JOIN scores b ON a.game = b.game AND a.puzzle_id = b.puzzle_id AND a.board_date = b.board_date
            WHERE a.user_id = ? AND b.user_id = ?
        """, (p1.id, p2.id))
        matchups = c.fetchall()

    if not matchups:
        await interaction.response.send_message(
            f"No shared puzzles found between **{p1.display_name}** and **{p2.display_name}** yet.",
            ephemeral=True
        )
        return

    stats = {}
    tot_w1 = tot_w2 = tot_ties = 0
    for game, s1, s2 in matchups:
        rec = stats.setdefault(game, [0, 0, 0])  # [p1_wins, p2_wins, ties]
        if abs(s1 - s2) < 1e-9:
            rec[2] += 1
            tot_ties += 1
        elif s1 < s2:
            rec[0] += 1
            tot_w1 += 1
        else:
            rec[1] += 1
            tot_w2 += 1

    embed = discord.Embed(
        title=f"Head-to-head: {p1.display_name} vs {p2.display_name}",
        description=f"**{tot_w1}–{tot_w2}** overall · {tot_ties} tied",
        color=0x64748B
    )
    lines = []
    for game, (w1, w2, t) in sorted(stats.items()):
        icon = get_game_icon(game)
        lines.append(f"{icon} **{game}** · {w1}–{w2} · {t} tied")

    embed.add_field(name="By game", value="\n".join(lines), inline=False)
    await interaction.response.send_message(embed=embed)


async def stats(interaction: discord.Interaction, player: discord.Member = None):
    target = player or interaction.user

    with sqlite3.connect(config.DB_PATH) as conn:
        c = conn.cursor()
        # Fetch all puzzles to compute crowns
        c.execute("SELECT board_date, game, puzzle_id, user_id, solved, rank_score, display_score FROM scores")
        all_rows = c.fetchall()

    puzzles = {}
    for bdate, game, pid, uid, solved, rscore, dscore in all_rows:
        puzzles.setdefault((bdate, game, pid), []).append((uid, solved, rscore, dscore))

    game_totals = {}  # game -> [played, solved, crowns]
    for (bdate, game, pid), entries in puzzles.items():
        best_score = min((e[2] for e in entries if e[1] == 1), default=None)
        for uid, solved, rscore, dscore in entries:
            if uid == target.id:
                rec = game_totals.setdefault(game, [0, 0, 0])
                rec[0] += 1
                if solved:
                    rec[1] += 1
                # Award crown if solved, tied for best score, and at least 2 people played
                if solved and best_score is not None and abs(rscore - best_score) < 1e-9 and len(entries) >= 2:
                    rec[2] += 1

    if not game_totals:
        await interaction.response.send_message(f"No games logged for **{target.display_name}** yet.", ephemeral=True)
        return

    total_played = sum(v[0] for v in game_totals.values())
    total_crowns = sum(v[2] for v in game_totals.values())

    embed = discord.Embed(
        title=f"All-time stats: {target.display_name}",
        description=f"**{total_played}** games logged · **{total_crowns}** 🥇 golds",
        color=0x64748B
    )
    lines = []
    for game, (played, solved, crowns) in sorted(game_totals.items()):
        icon = get_game_icon(game)
        win_rate = int((solved / played) * 100) if played else 0
        lines.append(f"{icon} **{game}** · {played} played · {win_rate}% solved · {crowns} 🥇")

    embed.add_field(name="By game", value="\n".join(lines), inline=False)
    await interaction.response.send_message(embed=embed)


async def board(interaction: discord.Interaction):
    board_date = today_str()
    with sqlite3.connect(config.DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT message_id FROM daily_boards WHERE board_date = ?", (board_date,))
        row = c.fetchone()
        if row:
            try:
                old_msg = await interaction.channel.fetch_message(row[0])
                await old_msg.delete()
            except Exception:
                pass
        c.execute("DELETE FROM daily_boards WHERE board_date = ?", (board_date,))
        conn.commit()

    await handlers.update_or_post_daily_board(interaction.channel, board_date)
    await interaction.response.send_message("Board reposted at the bottom of the channel.", ephemeral=True)


async def missing(interaction: discord.Interaction):
    await interaction.response.send_message(embed=embeds.build_missing_embed(interaction.user.id), ephemeral=True)


async def _game_autocomplete(_interaction, current: str):
    with sqlite3.connect(config.DB_PATH) as conn:
        names = [r[0] for r in conn.execute("SELECT DISTINCT game FROM scores ORDER BY game").fetchall()]
    choices = [n for n in names if current.lower() in n.lower()][:25]
    return [app_commands.Choice(name=n, value=n) for n in choices]


@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.describe(
    game="Game name (from the board)",
    puzzle_id="Puzzle id, e.g. 142 or #142 or 2026-11-03",
    user="Limit removal to this player (omit to remove everyone for that game+id)",
    date="Board date YYYY-MM-DD (default: today)",
)
@app_commands.autocomplete(game=_game_autocomplete)
async def remove_entry(interaction: discord.Interaction,
                       game: str,
                       puzzle_id: str,
                       user: discord.Member | None = None,
                       date: str | None = None):
    if date is None:
        board_date = today_str()
    else:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            await interaction.response.send_message("Date must be YYYY-MM-DD.", ephemeral=True)
            return
        board_date = date

    result = db.remove_entries(board_date, game, puzzle_id, user.id if user else None)
    if result is None:
        await interaction.response.send_message(
            f"No matching entries · {game} · {puzzle_id} · {board_date}"
            + (f" · {user.display_name}" if user else ""),
            ephemeral=True
        )
        return

    db.log_ingest(
        board_date, interaction.user.id, interaction.user.display_name,
        f"/remove game={game} id={puzzle_id} user={user.display_name if user else '*'} date={board_date}",
        f"removed {result['count']}: {', '.join(result['users'])}", "admin_remove"
    )

    # Re-render the day's board only if one already exists (don't create boards for old dates)
    with sqlite3.connect(config.DB_PATH) as conn:
        has_board = conn.execute("SELECT 1 FROM daily_boards WHERE board_date = ?", (board_date,)).fetchone()
    if has_board:
        await handlers.update_or_post_daily_board(interaction.channel, board_date)

    await interaction.response.send_message(
        f"Removed {result['count']} entr{'y' if result['count'] == 1 else 'ies'}"
        f" · {', '.join(result['games'])} {', '.join(result['puzzle_ids'])} · {board_date}"
        f" · {', '.join(result['users'])}",
        ephemeral=True
    )


async def undo(interaction: discord.Interaction):
    """Remove the scores from the caller's most recent ingest of the day."""
    result = db.undo_latest_ingest(today_str(), interaction.user.id)
    if result is None:
        await interaction.response.send_message(
            "Nothing to undo — only today's posts can be undone.", ephemeral=True
        )
        return
    summary, deleted = result
    await handlers.update_or_post_daily_board(interaction.channel, today_str())
    await interaction.response.send_message(
        f"Undid your latest ingest · removed {deleted} entr{'y' if deleted == 1 else 'ies'}: {summary}",
        ephemeral=True
    )


async def games(interaction: discord.Interaction):
    lines = []
    for name, meta in ACTIVE_GAME_META.items():
        lines.append(f"{meta['icon']} **{name}** · {meta['desc']} · [play]({meta['url']})")

    embed = discord.Embed(
        title=f"Supported games · {len(ACTIVE_GAME_META)}",
        description="\n".join(lines),  # description allows 4096 chars; a single field would cap at 1024
        color=0x64748B
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


async def layout_switch(interaction: discord.Interaction):
    channel_id = interaction.channel.id
    with sqlite3.connect(config.DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT layout FROM channel_settings WHERE channel_id = ?", (channel_id,))
        row = c.fetchone()
        current = row[0] if row else "grid"
        new_layout = "rows" if current == "grid" else "grid"
        c.execute(
            "INSERT OR REPLACE INTO channel_settings (channel_id, layout) VALUES (?, ?)",
            (channel_id, new_layout)
        )
        conn.commit()

    board_date = today_str()
    await handlers.update_or_post_daily_board(interaction.channel, board_date)

    if new_layout == "rows":
        await interaction.response.send_message("Board layout: wide · one line per game.", ephemeral=True)
    else:
        await interaction.response.send_message("Board layout: compact · three games per row.", ephemeral=True)


def register(bot):
    bot.tree.command(name="h2h", description="Head-to-Head comparison between two players across all daily games")(h2h)
    bot.tree.command(name="stats", description="View all-time crowns, podiums, and win rates")(stats)
    bot.tree.command(name="board", description="Moves today's scoreboard to the bottom of the channel if chat buried it")(board)
    bot.tree.command(name="missing", description="Which of today's games you still have to play")(missing)
    bot.tree.command(name="undo", description="Remove the scores from your most recent post today")(undo)
    bot.tree.command(name="remove", description="Remove a score entry (requires Manage Messages)")(remove_entry)
    bot.tree.command(name="games", description="List supported games with descriptions and links")(games)
    bot.tree.command(name="layout_switch", description="Toggle today's board between compact (3 per row) and wide (one line per game)")(layout_switch)
