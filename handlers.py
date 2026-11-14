"""Discord event wiring: message ingestion flow and daily board maintenance."""
import asyncio
import random
import sqlite3
from datetime import datetime, timedelta

import discord

import config
import db
import embeds
import games
import parsers


def _meme_numbers(parsed_games: list[dict]) -> list[int]:
    """Exact integral scores with curated gifs, in stable order, no repeats.

    Uses the result itself (points, guesses), never a puzzle id/date or rounded scores.
    """
    hits = set()
    for result in parsed_games:
        score = result.get("rank_score", 0.0)
        if isinstance(score, (int, float)) and score.is_integer():
            special = abs(int(score))
            if special in games.MEME_SCORES:
                hits.add(special)
    return sorted(hits)


def _prison_comment(board_date: str, user_name: str, game: str) -> str:
    options = (
        f"🚔 {user_name} hit a first-try win on **{game}**. How incredibly convenient. Your daily points will be held for questioning.",
        f"{user_name}, our random-number compliance officer has detected **{game}** on the first attempt. Today’s points are gone. To jail. No get-out-jail-free cards.",
        f"A first guess, a perfect hit, zero total points for the day. {user_name}, prison really makes you think about what you have done. Do some more puzzles while you're there.",
        f"Congratulations to {user_name} for the least suspicious first-try **{game}** result in recorded human history. Your judgment: 0 points for today. Go directly to jail.",
        f"The bot, an entity that definitely cheats too, accuses {user_name} of cheating. **{game}** first try. Jail for you, 0 daily points for me.",
    )
    return random.Random(f"prison:{board_date}:{user_name}").choice(options)


async def _self_destruct(msg: discord.Message, delay: int):
    """Delete a bot acknowledgement after a delay so the channel stays clean."""
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except discord.NotFound:
        pass


async def _pin_new_daily_board(channel: discord.TextChannel, board_date: str, message: discord.Message):
    """Pin a fresh daily digest and unpin older digests in the same channel only."""
    try:
        await message.pin()
    except discord.HTTPException as e:
        print(f"Warning: could not pin board {board_date}: {e}")

    with sqlite3.connect(config.DB_PATH) as conn:
        old_boards = conn.execute(
            "SELECT board_date, message_id FROM daily_boards WHERE channel_id = ? AND board_date != ?",
            (channel.id, board_date)
        ).fetchall()
    for old_date, message_id in old_boards:
        try:
            older = await channel.fetch_message(message_id)
            await older.unpin()
        except discord.NotFound:
            pass  # Board was already deleted.
        except discord.HTTPException as e:
            print(f"Warning: could not unpin older board {old_date}: {e}")


_BOARD_LOCKS: dict[str, asyncio.Lock] = {}


async def post_or_backfill_wrap(channel: discord.TextChannel, target_date: str | None = None) -> tuple[str, str | None]:
    """Post the oldest unwrapped day in the trailing week, or report why not.

    Returns (status, day) with status posted / exists / none.
    Idempotent: a day has one wrap marked as posted and never gets sent again.
    """
    if target_date:
        start = datetime.strptime(target_date, "%Y-%m-%d")
        day = start - timedelta(days=1)
    else:
        day = datetime.strptime(config.today_str(), "%Y-%m-%d") - timedelta(days=1)

    for offset in range(7):
        candidate = (day - timedelta(days=offset)).strftime("%Y-%m-%d")
        if db.wrap_already_posted(candidate):
            return "exists", candidate
        if not db.day_has_scores(candidate):
            continue
        embed = embeds.build_wrap_embed(candidate)
        if embed is not None:
            try:
                msg = await channel.send(embed=embed)
                db.mark_wrap_posted(candidate, msg.id)
                return "posted", candidate
            except discord.HTTPException as e:
                print(f"Warning: failed to post day wrap: {e}")
                return "error", candidate
    return "none", None


async def update_or_post_daily_board(channel: discord.TextChannel, board_date: str):
    """Serialize check-then-create for a date, so simultaneous ingests can't duplicate it."""
    lock = _BOARD_LOCKS.setdefault(board_date, asyncio.Lock())
    async with lock:
        await _update_or_post_daily_board_impl(channel, board_date)


async def _update_or_post_daily_board_impl(channel: discord.TextChannel, board_date: str):
    """Edits today's existing summary Embed, or posts a new one if none exists yet."""
    with sqlite3.connect(config.DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT layout FROM channel_settings WHERE channel_id = ?", (channel.id,))
        layout_row = c.fetchone()
        layout = layout_row[0] if layout_row else "grid"

    embed = embeds.build_daily_embed(board_date, layout)

    with sqlite3.connect(config.DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT channel_id, message_id FROM daily_boards WHERE board_date = ?", (board_date,))
        row = c.fetchone()
        if config.DEBUG_LOG:
            print(f"Board update: channel={channel.id}, row={row}")

        # Operate on the record for this channel only; a bot must not edit another
        # channel's pinned digest and flip its DB record to a wrong-body board.
        if row and row[0] == channel.id:
            msg_id = row[1]
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.edit(embed=embed)
                return
            except discord.NotFound:
                pass  # Message was manually deleted, fall through to create a new one
            except discord.HTTPException as e:
                print(f"Warning: failed to edit board message: {e}")
                return

        await post_or_backfill_wrap(channel, board_date)

        try:
            new_msg = await channel.send(embed=embed)
        except discord.HTTPException as e:
            print(f"Warning: failed to post board message: {e}")
            return
        c.execute(
            "INSERT OR REPLACE INTO daily_boards (board_date, channel_id, message_id) VALUES (?, ?, ?)",
            (board_date, channel.id, new_msg.id)
        )
        conn.commit()
        await _pin_new_daily_board(channel, board_date, new_msg)


def register(bot):
    # Slash commands are guild-only by design, and if a designated scores
    # channel is configured do not let other channels or DMs move its board.
    async def restrict_scores_channel(interaction):
        if interaction.guild is None or (config.SCORE_CHANNEL_ID and interaction.channel.id != config.SCORE_CHANNEL_ID):
            try:
                await interaction.response.send_message("Use this command in the results channel.", ephemeral=True)
            except discord.NotFound:
                pass
            return False
        return True

    bot.tree.interaction_check = restrict_scores_channel

    """Attach event listeners. The bot instance is captured so on_message can
    fall through to prefix-command processing without a circular import."""

    async def on_ready():
        print(f"Logged in as {bot.user} (ID: {bot.user.id})")

    async def on_message(message: discord.Message):
        # Ignore our own messages, other bots (like the official Wordle Activity app), DMs, or other channels
        if message.author.bot:
            return
        if message.guild is None:
            return
        if config.SCORE_CHANNEL_ID and message.channel.id != config.SCORE_CHANNEL_ID:
            return

        board_date = config.today_str()
        user_id = message.author.id
        user_name = message.author.display_name
        parsed_games = parsers.parse_all_games(message.content)

        if not parsed_games:
            # Anything without a recognizable score is ordinary chat: leave it alone,
            # including game examples in announcements and messages mentioning game names.
            if config.DEBUG_LOG:
                # Diagnostic only, never changes behavior: exposes the exact input string
                # searched by the parsers, including hidden Unicode differences.
                print(f"[ingest:unparsed] {user_name}: {message.content!r}")
            await bot.process_commands(message)
            return

        summary = ", ".join(f"{games.get_game_icon(g['game'])} **{g['game']}**" for g in parsed_games)
        if len(parsed_games) > 3:
            summary = ", ".join(f"{games.get_game_icon(g['game'])} **{g['game']}**" for g in parsed_games[:3]) \
                      + f" +{len(parsed_games) - 3} more"
        ingest_id = db.log_ingest(board_date, user_id, user_name, message.content, summary, "ok")

        with sqlite3.connect(config.DB_PATH) as conn:
            c = conn.cursor()
            for g in parsed_games:
                c.execute("""
                    INSERT INTO scores (board_date, user_id, user_name, game, puzzle_id, solved, rank_score, display_score, extra_url, ingest_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(board_date, user_id, game, puzzle_id) DO UPDATE SET
                        solved=excluded.solved,
                        rank_score=excluded.rank_score,
                        display_score=excluded.display_score,
                        extra_url=COALESCE(excluded.extra_url, scores.extra_url),
                        ingest_id=excluded.ingest_id
                """, (
                    board_date, user_id, user_name,
                    g["game"], g["puzzle_id"], g["solved"],
                    g["rank_score"], g["display_score"], g["extra_url"], ingest_id
                ))
            conn.commit()

        # 1. Auto-delete the user's raw score dump to keep the channel clean
        try:
            await message.delete()
        except discord.Forbidden:
            print("Warning: Bot lacks 'Manage Messages' permission to delete raw score posts.")
        except discord.NotFound:
            pass

        # Sentence first-attempt win games, but never strip the underlying result.
        jail_game = None
        if config.PRISON_ENABLED:
            for result in parsed_games:
                if games.is_first_try(result) and db.add_prisoner(board_date, user_id, user_name, result["game"]):
                    jail_game = result["game"]
                    break  # One public sentence per player per day, not per replay

        # 2. Update the single Daily Digest Embed
        await update_or_post_daily_board(message.channel, board_date)

        # 3. Confirm with a short acknowledgement (self-destructs) incl. current placement
        placements = []
        for g in parsed_games:
            p = embeds.placement_of(board_date, g["game"], g["puzzle_id"], user_id)
            placements.append(f"{games.get_game_icon(g['game'])} **{g['game']}** `{p}`" if p else
                              f"{games.get_game_icon(g['game'])} **{g['game']}** DNF")
        lines = [f"{user_name} · logged: " + " · ".join(placements)]

        if config.PRISON_ENABLED and db.is_jailed(board_date, user_id):
            lines.append("Daily: in prison · 0 pts")
        else:
            mvp_points, names = embeds.compute_daily_points(board_date)
            if names and user_id in mvp_points:
                standing = sorted(mvp_points.items(), key=lambda x: x[1], reverse=True)
                pos = [i + 1 for i, (u, _) in enumerate(standing) if u == user_id][0]
                lines.append(f"Daily: {pos}. · `{mvp_points[user_id]} pts`")

        ack = await message.channel.send("\n".join(lines))
        asyncio.create_task(_self_destruct(ack, 12))

        if jail_game:
            # Public and persistent, like Monopoly. Lucky first try unlike ranking exonerations.
            await message.channel.send(_prison_comment(board_date, user_name, jail_game))

        # Easter egg for exact virtual scores. Public, doesn't replace the acknowledgement.
        for special in _meme_numbers(parsed_games):
            effect = games.MEME_SCORES[special]
            try:
                # Direct URL lets Discord own the preview, rather than relying on a
                # custom embed's externally-fetched image being rendered.
                await message.channel.send(f"{user_name} · {special} · {effect['caption']}\n{effect['url']}")
            except discord.HTTPException as e:
                print(f"Warning: failed to post gif for {special}: {e}")

    bot.add_listener(on_ready, "on_ready")
    bot.add_listener(on_message, "on_message")
