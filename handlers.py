"""Discord event wiring: message ingestion flow and daily board maintenance."""
import asyncio
import sqlite3
from datetime import datetime, timedelta

import discord

import config
import db
import embeds
import games
import parsers


async def _self_destruct(msg: discord.Message, delay: int):
    """Delete a bot acknowledgement after a delay so the channel stays clean."""
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except discord.NotFound:
        pass


async def update_or_post_daily_board(channel: discord.TextChannel, board_date: str):
    """Edits today's existing summary Embed, or posts a new one if none exists yet."""
    with sqlite3.connect(config.DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT layout FROM channel_settings WHERE channel_id = ?", (channel.id,))
        layout_row = c.fetchone()
        layout = layout_row[0] if layout_row else "grid"

    embed = embeds.build_daily_embed(board_date, layout)

    with sqlite3.connect(config.DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT message_id FROM daily_boards WHERE board_date = ?", (board_date,))
        row = c.fetchone()

        if row:
            msg_id = row[0]
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.edit(embed=embed)
                return
            except discord.NotFound:
                pass  # Message was manually deleted, fall through to create a new one
            except discord.HTTPException as e:
                print(f"Warning: failed to edit board message: {e}")
                return

        # First board of a new day: publish yesterday's locked wrap once, above the fresh board.
        try:
            yesterday = (datetime.strptime(board_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        except ValueError:
            yesterday = None
        if yesterday and not db.wrap_already_posted(yesterday) and db.day_has_scores(yesterday):
            wrap = embeds.build_wrap_embed(yesterday)
            if wrap is not None:
                try:
                    wrap_msg = await channel.send(embed=wrap)
                    db.mark_wrap_posted(yesterday, wrap_msg.id)
                except discord.HTTPException as e:
                    print(f"Warning: failed to post day wrap: {e}")

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


def register(bot):
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

        # 2. Update the single Daily Digest Embed
        await update_or_post_daily_board(message.channel, board_date)

        # 3. Confirm with a short acknowledgement (self-destructs) incl. current placement
        placements = []
        for g in parsed_games:
            p = embeds.placement_of(board_date, g["game"], g["puzzle_id"], user_id)
            placements.append(f"{games.get_game_icon(g['game'])} **{g['game']}** `{p}`" if p else
                              f"{games.get_game_icon(g['game'])} **{g['game']}** DNF")
        lines = [f"{user_name} · logged: " + " · ".join(placements)]

        mvp_points, names = embeds.compute_daily_points(board_date)
        if names and user_id in mvp_points:
            standing = sorted(mvp_points.items(), key=lambda x: x[1], reverse=True)
            pos = [i + 1 for i, (u, _) in enumerate(standing) if u == user_id][0]
            lines.append(f"Daily: {pos}. · `{mvp_points[user_id]} pts`")

        ack = await message.channel.send("\n".join(lines))
        asyncio.create_task(_self_destruct(ack, 12))

    bot.add_listener(on_ready, "on_ready")
    bot.add_listener(on_message, "on_message")
