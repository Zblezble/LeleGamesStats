# LeleGamesStats

A Discord bot that digests daily puzzle-game results posted in a channel into a single, auto-updating leaderboard embed.

## What it does

- Watches a designated channel for raw game result pastes.
- Parses results for: **Wordle, Worldle, Flagle, Globle, Travle, Metazooa, Redactle, Songless, Centumth, Roughly, Magnitudle, Majority, Trivmount, Thursday Thirty** (T30 is weekly and only appears in `/missing` on Thursdays; pastes still count any day) (lower rank score always wins; points games like Centumth store negated scores).
- Deletes raw score pastes, confirms with a short self-destructing acknowledgement incl. current placement and daily standing, and updates **one consolidated daily leaderboard embed** per day. Any message without a recognized score is left untouched, including announcements and banter mentioning game names.
- When the first board of a new day appears, publishes yesterday's locked wrap above it: player turnout, easiest/hardest games by median normalized performance, final standings, and one playful placement comment (randomly a winner, silver, mid-pack, second-last or last). Skipped on days with no scores; posted once per date.
- Logs every successfully parsed message to the `ingest_log` table (raw text + user) – the audit trail and data source for `/undo`. Run with `--debug` (or `DEBUG_LOG=1`) to also dump them to the console.
- Easter egg: exact integer results of `42`, `67`, `69`, or `420` get a public, curated gif reaction (one per person per day per number, no puzzle ids or dates). Any broken/unformatted score text stays untouched.
- Awards daily points per game (🥇 = 3 pts · 🥈 = 2 pts · 🥉 = 1 pt, ties share placement; games with ≥2 players) plus a standings summary on the board.
- Slash commands:
  - `/h2h <opponent> [player1]` – head-to-head record across all shared puzzles.
  - `/stats [player]` – all-time games played, solve rate, golds 🥇 (competitive wins).
  - `/board` – re-posts today's board at the bottom of the channel.
  - `/layout_switch` – toggles the channel's board between compact (three games per row) and wide (one line per game).
  - `/games` – lists supported games with short descriptions and links (private reply).
  - `/missing` – private (ephemeral) checklist: your games still to play today, with links.
  - `/undo` – removes the scores from your most recent post today (self-serve, ephemeral reply).
  - `/forfeit game:…` – records a manual DNF for games with no "give up" share text (e.g. Globle). Puzzle id inferred from today's results; no points.
  - `/remove game:… puzzle_id:… [user] [date]` – precise entry removal, requires Manage Messages. Deletions are announced publicly (transparency) and logged as `admin_remove`.

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
   | `BOT_TZ`            | no       | Timezone for the daily cutoff, e.g. `Europe/Warsaw`. Defaults to server-local time. |
   | `DISABLED_GAMES`    | no       | Comma-separated games to turn off, e.g. `Wordle`. Hidden from the board, `/games` and `/missing`; on by default. |

4. Run:

   ```bash
   python main.py
   ```

   Scores are stored in a local `scores.db` SQLite file (created automatically).

## Project layout

```
main.py       → entry point: bot instance + wiring only
config.py     → env vars (token, channel, BOT_TZ, DISABLED_GAMES, DEBUG_LOG), date helpers
games.py      → game registry (icons/links/descriptions), GRADED_GAMES, result-hint regex
db.py         → SQLite schema + ingest log
parsers.py    → parse_all_games: one share-text -> result dicts (the file that grows per game)
embeds.py     → daily board + /missing checklist builders
handlers.py   → on_message ingest flow + daily board maintenance
commands.py   → slash commands, attached via register(bot)
test_parsers.py → fixture suite: python test_parsers.py (run it before/after parser changes)
```

## Security note

Never commit your bot token. This project reads it from `DISCORD_BOT_TOKEN`; there is no token in the source. If you previously shared or committed a real token anywhere, [regenerate it](https://discord.com/developers/applications) immediately.
