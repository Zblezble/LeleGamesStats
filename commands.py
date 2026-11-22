"""Slash commands. register(bot) attaches them to the command tree."""
import io
import re
import sqlite3

import discord
from discord import app_commands

import config
import db
import difficulty
import embeds
import handlers
import stats_charts
from datetime import date, datetime, timedelta

import csv

from config import today_str
from games import (ACTIVE_GAME_META, FIXED_ATTEMPT_GAMES, GUESS_CHART_GAMES,
                   SCORE_CHART_GAMES, fixed_attempt_family, get_game_icon,
                   guess_chart_family, is_game_enabled, score_chart_family)


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


def _format_game_trend(result: difficulty.TrendResult) -> str:
    """Format a reusable TrendResult as a compact, mobile-friendly section."""
    if (result.status == "insufficient" or result.previous_average is None
            or result.recent_average is None or result.change_pp is None):
        return "❔ Trend: Not enough data"
    labels = {
        "improving": ("📈", "Improving"),
        "declining": ("📉", "Declining"),
        "stable": ("➡️", "Stable"),
    }
    icon, label = labels[result.status]
    change = f"{result.change_pp:+.0f} pp"
    return (
        f"{icon} Trend ({result.period_days} days): {label}\n"
        f"Previous: {round(result.previous_average)} → "
        f"Recent: {round(result.recent_average)} ({change})"
    )


def build_all_time_stats_embed(target_id: int, target_name: str) -> discord.Embed | None:
    """Build the existing all-time stats embed; None when no games are logged."""
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
            if uid == target_id:
                rec = game_totals.setdefault(game, [0, 0, 0])
                rec[0] += 1
                if solved:
                    rec[1] += 1
                # Award crown if solved, tied for best score, and at least 2 people played
                if solved and best_score is not None and abs(rscore - best_score) < 1e-9 and len(entries) >= 2:
                    rec[2] += 1

    if not game_totals:
        return None

    total_played = sum(v[0] for v in game_totals.values())
    total_crowns = sum(v[2] for v in game_totals.values())

    personal_bests = _personal_best_scores(all_rows, target_id)
    current_streak, best_streak = _play_streaks(
        [bdate for bdate, _game, _pid, uid, _s, _r, _d in all_rows if uid == target_id]
    )

    embed = discord.Embed(
        title=f"All-time stats: {target_name}",
        description=f"{total_played} games logged · {total_crowns} 🥇 golds",
        color=0x64748B
    )
    embed.add_field(name="Prison days", value=f"Lifetime total: {db.prison_count(target_id)}", inline=False)
    streak_line = f"Longest streak: {best_streak} days"
    if current_streak:
        streak_line += f" · current: {current_streak} days"
    embed.add_field(name="Streak", value=streak_line, inline=False)

    lines = []
    for game, (played, solved, crowns) in sorted(game_totals.items()):
        icon = get_game_icon(game)
        win_rate = int((solved / played) * 100) if played else 0
        pb = personal_bests.get(game, {}).get("display_score", "—")
        lines.append(f"{icon} **{game}** · {played} played · {win_rate}% solved · {crowns} 🥇 · PB `{pb}`")

    # Discord caps each field at 1024 characters. Split at complete game rows,
    # so a long all-time history stays readable instead of ending in an ellipsis.
    embeds._append_daily_fields(embed, embeds._checklist_fields("By game", lines))
    return embed


async def _chart_game_autocomplete(_interaction, current: str):
    """Offer supported chart families; variants are resolved from history."""
    names = {name for name in FIXED_ATTEMPT_GAMES if is_game_enabled(name)}
    names.update(name for name in SCORE_CHART_GAMES if is_game_enabled(name))
    names.update(name for name in GUESS_CHART_GAMES if is_game_enabled(name))
    matches = [name for name in sorted(names, key=str.casefold)
               if current.casefold() in name.casefold()]
    return [app_commands.Choice(name=name, value=name) for name in matches[:25]]


async def _send_game_chart(interaction: discord.Interaction, target: discord.abc.User,
                           selected_game: str,
                           period: int = stats_charts.CHART_PERIOD_DAYS,
                           *, public: bool = False):
    """Resolve, render and send one user's game history chart."""
    end = date.fromisoformat(today_str())
    selected_meta = None
    if score_chart_family(selected_game) is not None:
        selected_meta = stats_charts.score_chart_meta(selected_game)
    weekly = bool(selected_meta and selected_meta.get("weekly"))
    if weekly:
        thursdays = stats_charts.weekly_thursdays(end, period)
        start, end = thursdays[0], thursdays[-1]
    else:
        start = end - timedelta(days=period - 1)
    if (fixed_attempt_family(selected_game) is None
            and score_chart_family(selected_game) is None
            and guess_chart_family(selected_game) is None):
        await interaction.response.send_message(
            f"**{selected_game}** doesn't have a history chart yet.",
            ephemeral=True,
        )
        return

    game, variants = stats_charts.resolve_chart_game(target.id, selected_game, start, end)
    if game is None:
        if variants:
            family = (fixed_attempt_family(selected_game)
                      or score_chart_family(selected_game)
                      or guess_chart_family(selected_game))
            shown = ", ".join(f"`{name}`" for name in variants)
            await interaction.response.send_message(
                f"Multiple **{family}** variants were played "
                f"in this period. Pick one: {shown}.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"No **{selected_game}** results for {target.display_name} between "
                f"{start.isoformat()} and {end.isoformat()}.",
                ephemeral=True,
            )
        return

    if fixed_attempt_family(game) is not None:
        daily_attempts = stats_charts.load_attempts(target.id, game, start, end)
        if not any(result.status != "missing" for result in daily_attempts):
            await interaction.response.send_message(
                f"No **{game}** results for {target.display_name} between "
                f"{start.isoformat()} and {end.isoformat()}.",
                ephemeral=True,
            )
            return
        meta = stats_charts.fixed_attempt_meta(game)
        chart = stats_charts.render_attempt_chart(
            daily_attempts, meta["max_attempts"], start, end,
            title=game,
            axis_label="Extra guesses" if meta.get("zero_is_best") else "Guesses",
            zero_is_best=bool(meta.get("zero_is_best")),
            show_hints=bool(meta.get("zero_is_best")),
            period=period,
        )
        summary = stats_charts.summarize_attempts(
            daily_attempts,
            unit="extra guesses" if meta.get("zero_is_best") else "guesses",
        )
    elif guess_chart_family(game) is not None:
        daily_guesses = stats_charts.load_guesses(target.id, game, start, end)
        if not any(result.status != "missing" for result in daily_guesses):
            await interaction.response.send_message(
                f"No **{game}** results for {target.display_name} between "
                f"{start.isoformat()} and {end.isoformat()}.",
                ephemeral=True,
            )
            return
        meta = stats_charts.guess_chart_meta(game)
        chart = stats_charts.render_scaled_guess_chart(
            daily_guesses, meta["default_max"], start, end,
            title=game, unit=meta["unit"],
            max_attempts=meta.get("max_attempts"), period=period,
        )
        summary = stats_charts.summarize_attempts(
            daily_guesses, unit=meta["unit"],
            singular=meta["unit"].removesuffix("es"),
        )
    else:
        meta = stats_charts.score_chart_meta(game)
        if meta.get("weekly"):
            daily_scores = stats_charts.load_scores_on_dates(
                target.id, game, stats_charts.weekly_thursdays(end, period)
            )
        else:
            daily_scores = stats_charts.load_scores(target.id, game, start, end)
        if not any(result.status != "missing" for result in daily_scores):
            await interaction.response.send_message(
                f"No **{game}** results for {target.display_name} between "
                f"{start.isoformat()} and {end.isoformat()}.",
                ephemeral=True,
            )
            return
        meta = stats_charts.score_chart_meta(game)
        if meta["renderer"] == "fixed_score":
            chart = stats_charts.render_fixed_score_chart(
                daily_scores, meta["max_score"], start, end,
                title=game, unit=meta["unit"],
                zero_axis=bool(meta.get("zero_axis")), period=period,
            )
            summary = stats_charts.summarize_fixed_scores(
                daily_scores, meta["max_score"],
            )
        else:
            lower_is_better = bool(meta.get("lower_is_better"))
            chart = stats_charts.render_scaled_score_chart(
                daily_scores, meta["max_score"], start, end,
                title=game, unit=meta["unit"],
                lower_is_better=lower_is_better,
                cap_outliers=bool(meta.get("cap_outliers")),
                fixed_axis=bool(meta.get("fixed_axis")),
                estimated=bool(meta.get("estimated")),
                axis_suffix=meta.get("axis_suffix"),
                axis_label=meta.get("axis_label"),
                expected_dates=stats_charts.weekly_thursdays(end, period)
                if meta.get("weekly") else None,
                period=period,
            )
            summary = stats_charts.summarize_scaled_scores(
                daily_scores, unit=meta["unit"], lower_is_better=lower_is_better,
                include_hints=bool(meta.get("show_hints")),
                include_perfect=bool(meta.get("weekly")),
                estimated=bool(meta.get("estimated")),
            )

    trend = difficulty.calculate_game_trend(target.id, game, today_str())
    embed = discord.Embed(
        title=f"{get_game_icon(game)} {game} · {target.display_name}",
        color=0x64748B,
    )
    period_noun = "Thursdays" if weekly else "days"
    embed.add_field(
        name=f"Last {period} {period_noun}",
        value=f"```text\n{chart}\n```",
        inline=False,
    )
    embed.add_field(
        name="Summary",
        value=summary,
        inline=False,
    )
    embed.add_field(
        name="Performance trend",
        value=_format_game_trend(trend),
        inline=False,
    )
    await interaction.response.send_message(embed=embed, ephemeral=not public)


@app_commands.describe(
    game="Optional game history chart",
    period="Length of the game history (used only with game)",
    user="Defaults to you if omitted",
    public="Post the game chart publicly (default: private to you)",
)
@app_commands.choices(period=[
    app_commands.Choice(name="Last 10 days", value=10),
    app_commands.Choice(name="Last 20 days", value=20),
])
@app_commands.autocomplete(game=_chart_game_autocomplete)
async def stats(interaction: discord.Interaction,
                game: str | None = None,
                period: int = stats_charts.CHART_PERIOD_DAYS,
                user: discord.Member | None = None,
                public: bool = False):
    target = user or interaction.user

    if game:
        await _send_game_chart(interaction, target, game, period, public=public)
        return

    embed = build_all_time_stats_embed(target.id, target.display_name)
    if embed is None:
        await interaction.response.send_message(
            f"No games logged for {target.display_name} yet.", ephemeral=True)
        return
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

    # A deferred interaction must be completed through the follow-up webhook,
    # not the already-used initial response (which would raise 500).
    await interaction.followup.send(
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
    entry = db.forfeit_entry(board_date, interaction.user.id,
                             interaction.user.display_name, key)
    if entry is None:
        await interaction.response.send_message(
            f"No **{key}** result logged today yet — forfeits need an existing "
            "puzzle to join.",
            ephemeral=True
        )
        return
    puzzle_id, overwritten = entry
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
    bot.tree.command(name="stats", description="View all-time stats or a recent game history chart")(stats)
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
