# LeleGamesStats

A Discord bot that digests daily puzzle-game results posted in a channel into a single, auto-updating leaderboard embed.

## What it does

- Watches a designated channel for raw game result pastes.
- Parses results for: **Wordle, Worldle, Flagle, Globle, Travle, Metazooa, Redactle, Songless, Centumth, Roughly** (lower rank score always wins; points games like Centumth store negated scores).
- Deletes the raw paste and updates **one consolidated daily leaderboard embed** per day (per-day boards are tracked in SQLite and edited in place).
- Awards podium points per game (👑=3, 🥈=2, 🥉=1, games with ≥2 players) plus a daily standings summary.
- Slash commands:
  - `/h2h <opponent> [player1]` — head-to-head record across all shared puzzles.
  - `/stats [player]` — all-time games played, solve rate, crown count.
  - `/repost_board` — re-posts today's board at the bottom of the channel.

## Setup

1. Python 3.10+ (uses `X | None`-style annotations via `str | None` return types and built-in generics).

   ```bash
   pip install -r requirements.txt
   ```

2. Create a Discord application/bot at <https://discord.com/developers/applications>.
   - Enable the **Message Content** and **Server Members** privileged intents.
   - Invite it with `bot` + `applications.commands` scopes and permissions: Send Messages, Manage Messages (to delete raw pastes), Embed Links, Read Message History.

3. Set environment variables:

   | Variable            | Required | Description                                  |
   |---------------------|----------|----------------------------------------------|
   | `DISCORD_BOT_TOKEN` | yes      | Your bot token. Keep it secret.              |
   | `SCORE_CHANNEL_ID`  | no       | Channel to watch. If unset, watches all.     |

4. Run:

   ```bash
   python bot.py
   ```

   Scores are stored in a local `scores.db` SQLite file (created automatically).

## Security note

Never commit your bot token. This project reads it from `DISCORD_BOT_TOKEN`; there is no token in the source. If you previously shared or committed a real token anywhere, [regenerate it](https://discord.com/developers/applications) immediately.
