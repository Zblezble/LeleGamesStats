"""Slash commands. register(bot) attaches them to the command tree."""
import io
import re
import sqlite3

import discord
from discord import app_commands

import config
import db
import embeds
import handlers
from datetime import datetime

import csv

from config import today_str
from games import ACTIVE_GAME_META, get_game_icon


@app_commands.describe(
    opponent="Player to compare against",
    player1="Defaults to you if omitted",
)
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
            f"No shared puzzles found between {p1.display_name} and {p2.display_name} yet.",
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
        description=f"{tot_w1}–{tot_w2} overall · {tot_ties} tied",
        color=0x64748B
    )
    lines = []
    for game, (w1, w2, t) in sorted(stats.items()):
        icon = get_game_icon(game)
        lines.append(f"{icon} **{game}** · {w1}–{w2} · {t} tied")

    embeds._append_daily_fields(embed, [("By game", "\n".join(lines), False)])
    await interaction.response.send_message(embed=embed)


def _personal_best_scores(all_rows, user_id: int) -> dict[str, dict]:
    """Return the native display score with the user's lowest rank_score, per game."""
    best = {}
    for _bdate, game, _pid, uid, solved, rank_score, display_score in all_rows:
        if uid == user_id and solved:
            if game not in best or rank_score < best[game].get("rank_score", 0):
                best[game] = {"rank_score": rank_score, "display_score": display_score}
    return best


def _play_streaks(date_strings, today=None):
    """Return (current ongoing run, longest run), distinct dates per day."""
    dates = sorted({datetime.strptime(x, "%Y-%m-%d") for x in date_strings})
    best_run = run = 1 if dates else 0
    for prev, curr in zip(dates, dates[1:]):
        run = run + 1 if (curr - prev).days == 1 else 1
        best_run = max(best_run, run)
    latest_run = 1 if dates else 0
    for prev, curr in zip(dates, dates[1:]):
        latest_run = latest_run + 1 if (curr - prev).days == 1 else 1
    current = latest_run if dates and dates[-1].strftime("%Y-%m-%d") == (today or today_str()) else 0
    return current, best_run


@app_commands.describe(player="Defaults to you if omitted")
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
        await interaction.response.send_message(f"No games logged for {target.display_name} yet.", ephemeral=True)
        return

    total_played = sum(v[0] for v in game_totals.values())
    total_crowns = sum(v[2] for v in game_totals.values())

    personal_bests = _personal_best_scores(all_rows, target.id)
    current_streak, best_streak = _play_streaks(
        [bdate for bdate, _game, _pid, uid, _s, _r, _d in all_rows if uid == target.id]
    )

    embed = discord.Embed(
        title=f"All-time stats: {target.display_name}",
        description=f"{total_played} games logged · {total_crowns} 🥇 golds",
        color=0x64748B
    )
    embed.add_field(name="Prison days", value=f"Lifetime total: {db.prison_count(target.id)}", inline=False)
    streak_line = f"Longest streak: {best_streak} days"
    if current_streak:
        streak_line += f" · current: {current_streak} days"
    embed.add_field(name="Prison days", value=f"Lifetime total: {db.prison_count(target.id)}", inline=False)

    lines = []
    for game, (played, solved, crowns) in sorted(game_totals.items()):
        icon = get_game_icon(game)
        win_rate = int((solved / played) * 100) if played else 0
        pb = personal_bests.get(game, {}).get("display_score", "—")
        lines.append(f"{icon} **{game}** · {played} played · {win_rate}% solved · {crowns} 🥇 · PB `{pb}`")

    embeds._append_daily_fields(embed, [("By game", "\n".join(lines), False)])
    await interaction.response.send_message(embed=embed)


async def board(interaction: discord.Interaction):
    # Acknowledge immediately: reposting can take longer than Discord's 3s initial timeout.
    await interaction.response.defer(ephemeral=True)
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
    try:
        await interaction.followup.send("Board reposted at the bottom of the channel.", ephemeral=True)
    except discord.NotFound:
        # The interaction webhook expired, but the board was already updated.
        # Do not leave a traceback for a confirmation that arrived too late to matter.
        print("Board reposted; interaction webhook unavailable for the confirmation.")


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

    # Acknowledge before maintenance (moderation remains public for transparency).
    await interaction.response.defer(ephemeral=False)

    # Re-render the day's board only if one already exists (don't create boards for old dates)
    with sqlite3.connect(config.DB_PATH) as conn:
        has_board = conn.execute("SELECT 1 FROM daily_boards WHERE board_date = ?", (board_date,)).fetchone()
    if has_board:
        await handlers.update_or_post_daily_board(interaction.channel, board_date)

    # Deletions by mods are announced publicly for transparency; self-/undo stays quiet.
    await interaction.response.send_message(
        f"🧹 Removed {result['count']} entr{'y' if result['count'] == 1 else 'ies'}"
        f" · {', '.join(result['games'])} {', '.join(result['puzzle_ids'])} · {board_date}"
        f" · {', '.join(result['users'])} · by {interaction.user.display_name}"
    )


@app_commands.describe(game="Game to forfeit today (global: base game names)")
@app_commands.autocomplete(game=_game_autocomplete)
async def forfeit(interaction: discord.Interaction, game: str):
    key = next((k for k in ACTIVE_GAME_META if k.lower() == game.lower() or game.lower().startswith(k.lower())), None)
    if key is None:
        await interaction.response.send_message(
            f"Unknown game: **{game}**. Pick one from the board.", ephemeral=True)
        return

    board_date = today_str()
    puzzle_id, overwritten = db.forfeit_entry(board_date, interaction.user.id,
                                              interaction.user.display_name, key)
    db.log_ingest(board_date, interaction.user.id, interaction.user.display_name,
                  f"/forfeit {game}", f"DNF {key} {puzzle_id}", "forfeit")
    await interaction.response.defer(ephemeral=True)
    await handlers.update_or_post_daily_board(interaction.channel, board_date)
    await interaction.followup.send(
        f"Forfeited **{key}** today · logged as DNF ({puzzle_id})."
        + (" Your earlier entry was replaced." if overwritten else ""),
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
    await interaction.response.defer(ephemeral=True)
    await handlers.update_or_post_daily_board(interaction.channel, today_str())
    await interaction.followup.send(
        f"Undid your latest ingest · removed {deleted} entr{'y' if deleted == 1 else 'ies'}: {summary}",
        ephemeral=True
    )


async def games(interaction: discord.Interaction):
    lines = []
    for name, meta in ACTIVE_GAME_META.items():
        lines.append(f"{meta['icon']} **{name}** · {meta['desc']} · [play]({meta['url']})")

    embed = discord.Embed(
        title=f"Supported games · {len(ACTIVE_GAME_META)}",
        # description allows 4096 chars; a single field would cap at 1024
        description="\n".join(lines) + "\n\nAll games reset at midnight, your local time.",
        color=0x64748B
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


async def wrap(interaction: discord.Interaction):
    """Post the oldest currently unwrapped recent day, without spamming repeats."""
    status, day = await handlers.post_or_backfill_wrap(interaction.channel)
    if status == "posted":
        await interaction.response.send_message(f"🏆 Wrapped up **{day}**.", ephemeral=True)
    elif status == "exists":
        await interaction.response.send_message(f"**{day}** already has a wrap in this channel.", ephemeral=True)
    elif status == "invalid":
        await interaction.response.send_message(f"Invalid date format: {day}.", ephemeral=True)
    else:
        await interaction.response.send_message("No results available to wrap for yesterday.", ephemeral=True)


async def weekly(interaction: discord.Interaction):
    embed = embeds.build_weekly_embed()
    if embed is None:
        await interaction.response.send_message("No scores logged in the last seven days.", ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed)


@app_commands.checks.has_permissions(manage_messages=True)
async def export(interaction: discord.Interaction, days: int | None = None):
    """Export the last N days as a formula-safe CSV, privately to this admin."""
    days = max(1, min(days if days is not None else 7, 31))
    text, start, end = db.export_scores_csv(days)
    rows = list(csv.reader(io.StringIO(text)))
    await interaction.response.defer(ephemeral=True)
    if(len(rows) <= 1):
        await interaction.followup.send(
            f"No scores available between {start} and {end}.", ephemeral=True)
        return
    filename = f"scores_{start}_to_{end}.csv"
    await interaction.followup.send(
        f"Export of {len(rows) - 1} results · {start} to {end}",
        file=discord.File(io.BytesIO(text.encode("utf-8-sig")), filename=filename),
        ephemeral=True,
    )


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

    await interaction.response.defer(ephemeral=True)
    board_date = today_str()
    await handlers.update_or_post_daily_board(interaction.channel, board_date)

    if new_layout == "rows":
        await interaction.followup.send("Board layout: wide · one line per game.", ephemeral=True)
    else:
        await interaction.followup.send("Board layout: compact · three games per row.", ephemeral=True)


def register(bot):
    bot.tree.command(name="h2h", description="Head-to-Head comparison between two players across all daily games")(h2h)
    bot.tree.command(name="stats", description="View all-time crowns, podiums, and win rates")(stats)
    bot.tree.command(name="board", description="Moves today's scoreboard to the bottom of the channel if chat buried it")(board)
    bot.tree.command(name="missing", description="Which of today's games you still have to play")(missing)
    bot.tree.command(name="undo", description="Remove the scores from your most recent post today")(undo)
    bot.tree.command(name="forfeit", description="Record a DNF for a game you can't finish today")(forfeit)
    bot.tree.command(name="remove", description="Remove a score entry (requires Manage Messages)")(remove_entry)
    bot.tree.command(name="games", description="List supported games with descriptions and links")(games)
    bot.tree.command(name="layout_switch", description="Toggle today's board between compact (3 per row) and wide (one line per game)")(layout_switch)
    bot.tree.command(name="wrap", description="Post yesterday's wrap if it hasn't already been posted")(wrap)
    bot.tree.command(name="week", description="Weekly recap: standings, activity and game difficulty")(weekly)
    bot.tree.command(name="export", description="Export last N days as CSV (admins only, max 31)")(export)
