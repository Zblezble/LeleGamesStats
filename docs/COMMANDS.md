# Command reference

This page documents the bot’s slash commands in more detail than the README.

All commands are guild-only. If `SCORE_CHANNEL_ID` is configured, slash commands are accepted only in that results channel. “Private” below means Discord-ephemeral: only the invoking member sees the response. It does not mean that scores are hidden from other members when a command later renders them publicly.

## Command summary

| Command | Purpose | Access / response |
|---|---|---|
| `/h2h` | Compare two players across shared puzzle results. | Public embed. |
| `/stats` | Show all-time stats or a recent game-history chart. | Public all-time embed; game charts private unless `public` is true. |
| `/missing` | Show your remaining games for today. | Private embed. |
| `/games` | List enabled games alphabetically. | Private embed. |
| `/week` | Show the last seven days’ recap. | Public embed. |
| `/wrap` | Post an available daily wrap. | Public wrap; private confirmation. |
| `/board` | Repost today’s board at the bottom of the channel. | Public board; private confirmation. |
| `/layout_switch` | Toggle the board layout. | Public board; private confirmation. |
| `/undo` | Remove your latest parsed ingest today. | Private confirmation; public board update. |
| `/forfeit` | Record a manual DNF for today. | Private confirmation; public board update. |
| `/remove` | Remove matching score entries. | Requires **Manage Messages**; public removal notice. |
| `/export` | Export recent score rows as CSV. | Requires **Manage Messages**; private attachment. |

Useful examples:

```text
/stats game:Wordle period:20 user:@Friend public:true
/h2h opponent:@Friend player1:@Me
/missing
/remove game:Wordle puzzle_id:142 date:2026-11-23 user:@Friend
```

---

## `/h2h opponent:<member> [player1:<member>]`

Compares two players across every stored `(date, game, puzzle_id)` result they share.

- Lower `rank_score` wins.
- Exact score ties are counted separately as ties.
- `player1` defaults to the invoking member.
- The summary shows the overall record and tied puzzles, followed by a per-game breakdown.
- If the two players have no shared puzzle result, the bot replies privately.

## `/stats [game:<name>] [period:<10|20>] [user:<member>] [public:<true|false>]`

`/stats` has two modes.

### All-time stats

When `game` is omitted, the bot shows a public all-time summary for the selected member:

- total games logged and lifetime golds;
- lifetime prison days;
- current and longest play streaks;
- per-game played count, solve rate, gold count, and native personal best.

`period` and `public` do not affect this mode.

### Game history chart

When `game` is provided, the bot renders a compact Unicode history chart for that member.

- `period` selects **10 calendar days** by default or **20 calendar days** in the denser layout.
- For **Thursday Thirty**, `period` means the last 10 or 20 Thursdays rather than calendar days.
- Game charts are private by default. Set `public` to `true` to post the embed in the channel.
- `user` defaults to the invoking member and may target another server member.
- Missing days are blank. DNF days are visible as their own column marker where supported.
- The chart is followed by a native-unit summary and a performance-trend section.

Game autocomplete offers supported chart families. Variant-specific stored names are resolved from the selected member’s recent history; if multiple incompatible variants appear in the period, the bot asks which one to chart.

### Performance trend

Game history charts include a trend calculated independently of the displayed chart period:

- Daily games use the last **30 days**, split into previous days 1–15 and recent days 16–30.
- Thursday Thirty uses the last **180 days**, split into two 90-day windows.
- Each valid result is converted to a historical percentile using only results from strictly earlier dates.
- Difficulty shrinkage is not applied.
- Both windows need at least five usable percentile results.
- The output classifies the change as improving, declining, stable, or “Not enough data.”

A higher percentile means better-than-usual performance for that game and variant, regardless of whether its raw score is “lower is better” or “higher is better.”

## `/missing`

Shows an ephemeral personal checklist for today’s configured results channel date.

- **To play** lists enabled games the player has not logged today.
- **Done** lists games they have logged today, using their latest native display score.
- Meaningful submodes collapse to their base game for checklist purposes.
- Scheduled games such as Thursday Thirty appear only on their scheduled weekday.
- Links come from the game registry.

## `/games`

Lists enabled games alphabetically with icons, short descriptions, and play links. Disabled games are omitted.

The footer notes that most games reset at midnight in the viewer’s local time and that Redactle resets at 17:00.

## `/week`

Builds a recap for the inclusive seven-day window ending today in `BOT_TZ`.

- Shows active players, distinct games, and active days.
- Weekly points are the sum of each day’s normal daily podium points, not a re-ranking of the whole week as one competition.
- Includes historical weekly difficulty where enough eligible history exists.
- The command is public and does not write a wrap record to the database.

## `/wrap`

Posts a daily wrap for a day that has scores but has not already been wrapped.

- Starting from yesterday, it scans backward through the trailing seven days.
- Empty days are skipped.
- The first available unwrapped day is posted publicly and marked as wrapped.
- Wraps are idempotent; a date is not posted twice.
- A new daily board also triggers wrap backfill when the board is first created for that date.
- If the most recent scanned date already has a wrap, the bot reports that instead of searching for older missing days.

## `/board`

Deletes the existing daily board record and message for today, then posts a fresh board at the bottom of the current channel and pins it.

- Older daily board pins in the same channel are unpinned.
- Other pins are untouched.
- The confirmation is private, while the resulting board is public.
- The command does not change the saved channel layout.

## `/layout_switch`

Toggles the current channel’s board layout and immediately updates today’s board.

- `grid` is the compact layout with multiple game groups per row.
- `rows` is the wide layout with one line per game.
- The setting is stored per channel.
- The confirmation is private; the updated board is public.

## `/undo`

Removes the score rows created by the invoking member’s most recent successful parsed ingest today.

- It applies to the latest raw-message ingest, including a message that parsed multiple games.
- It updates today’s public board.
- It does not remove the corresponding `ingest_log` row; that row is marked `undone`.
- It does not undo `/forfeit` or `/remove` actions.
- Only today’s ingests are eligible.

## `/forfeit game:<name>`

Records a manual DNF for the invoking member.

- The game must already have at least one stored result today, so the bot can infer a real `puzzle_id`; it does not invent a phantom puzzle.
- The base game name is used for lookup, and the stored variant is inferred from the latest matching result.
- If the member already has an entry for that game and puzzle today, it is replaced with the DNF.
- The confirmation is private, and the public board is updated.
- This action is not reversible with `/undo`.

## `/remove game:<name> puzzle_id:<id> [user:<member>] [date:<YYYY-MM-DD>]`

Removes matching stored score entries.

- `date` defaults to today and must use `YYYY-MM-DD`.
- `puzzle_id` accepts either `142` or `#142`.
- `game` matches the exact game name or a variant prefix; `Regionle` also matches `Regionle (US States)`.
- **If `user` is omitted, every matching player’s entry for that game, puzzle, and date is removed.** Always include `user` for a single-player correction.
- The action posts a public removal notice for transparency.
- The corresponding `ingest_log` row is not deleted.
- If an existing daily board exists for that date, it is refreshed; no board is created for an old date.

## `/export [days:<1-31>]`

Exports current score rows as a CSV attachment.

- `days` defaults to 7 and is clamped to 1–31.
- The inclusive range ends on today’s `BOT_TZ` date.
- Spreadsheet-looking cells are prefixed with an apostrophe to keep the CSV inert.
- The response and attachment are private.
- This is a score report, not a complete database backup; it does not include `ingest_log` or bot bookkeeping tables.

## Related documentation

- [README](../README.md)
- [Scoring and difficulty](../SCORING.md)
- [Game registry source](../games.py)
