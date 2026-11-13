# Scoring and difficulty

This document describes how the bot turns shared puzzle results into a daily scoreboard, daily points, and easiest/hardest labels. It is meant to explain the system without assuming knowledge of the source code.

## The two scores in play

There are two different numbers:

- **`rank_score`** – used to order results. **Lower is better.** It is a normalized leaderboard key, not a judgement of how good a puzzle actually was.
- **Normalized performance** – used only by the daily and weekly difficulty summary. It is a rough 0–100% estimate of how well the group did on a game, and **never affects rank_score or points**.

Every score is stored against `(board_date, user_id, game, puzzle_id)`. Reposting the same score on the same day overwrites the earlier entry.

## Daily rankings and points

Each `(game, puzzle_id)` is a leaderboard on its own. Results are ordered by `rank_score`, with ties sharing a dense rank (1, 1, 2 rather than 1, 2, 2).

For a result to earn **daily points** it must be in a **competitive game**, meaning at least two players posted a result for that puzzle today.

- Place 1: **3 points**
- Place 2: **2 points**
- Place 3: **1 point**
- Place 4+: **0 points**

Ties share both the placement and the points. Other players’ scores are not penalized. Daily points are aggregated into a standings footer named **“Today's points”**.

### Elimination vs. graded results

For most games, only solved results compete. Unfinished/DNF players stay visible with their displayed score, but do not earn ranking points.

The exception is **Trivmount**, a graded game: any nonzero score competes for points, even if it is not a perfect summit. A zero score earns nothing.

---

## Game-specific score calculation

In the table below, **lower rank_score wins**. Where a value contributes to the normalized performance used in the daily wrap, it is shown as `native result -> performance`.

| Game | rank_score assignment | Notes |
|---|---|---|
| **Metazooa** | `guesses` | The number of guesses is the main score. DNF is 999. |
| **Centumth** | `-points` | More points is better. Displayed as points / 490. |
| **Redactle** | `guesses + (10 × arrow hints) + (100 × chat hints) + 0.000001 × seconds` | Up-arrow hints 👆 cost 10 guesses each. Chat hints 💬 cost 100 each. Time is only a tiny tiebreak. DNF uses `10000 + guesses`. |
| **Flagle** | `tries − 0.05 × bonus emoji count` | Fewer tries wins; bonus emojis reward small rank improvements. DNF is 99, with the same bonus applied. |
| **Worldle** | `tries − (percentage × 0.001)` | Higher percentage gives a small improvement. DNF is 99. |
| **Travle** | `extra guesses + hints(n)` | With `n` hints, cost is `n(n+1)/2`, i.e. 1st hint +1, 2nd +2, 3rd +3. Unfinished localized results like “(3 pryč)” or “(3 away)” use `500 + distance`. X or unfinished is otherwise 999. |
| **Globle** | `guesses` | Lower guesses wins. Forfeit gives 999. |
| **Roughly** | `-percentile` on ordinary shares; `−average-tier × 100` on grid shares | The headline percentage is the **best round only**. When the grid is present, tiers become `□=15%`, `▧=45%`, `▣=72.5%`, `■=92.5%`, averaged for an **approximate** overall result, marked with `~`. This is a bucket estimate, not the game's exact internal score. |
| **Songless** | `−(solved songs × 100) + total tries` | More solved songs dominates. Fewer green-position tries breaks ties. Rows without a green mark cost 6 tries each. |
| **Magnitudle** | `-points` | More points (out of 500) wins. Forfeit gives 999. |
| **Majority** | `−(majorities won × 100 + crowd sync %)` | Majorities dominate; crowd-sync % breaks ties. Correct count and sync rate are separate values. |
| **Trivmount** | Perfect: `-100 × correct/total`. Imperfect: `10000 − 100 × correct/total` | **Only perfect climbs are solved.** Imperfect climbs still compete through the graded exception. Their normalized performance is `correct/total`. |
| **Thursday Thirty** | `−(correct / 30 × 100)` | Ratio-based ranking; replayable any day, but only nudged in `/missing` on Thursdays. Unfinished is 10000. |
| **Songspot** | `−(known songs / total songs × 100) − (points / max points × 0.001)` | Known songs determine the primary placement; points are a small tiebreak. Performance uses known/total. |
| **Regionle** | `tries` | Simple fewer-tries wins over seven attempts. DNF is 99. |
| **Mathle** | `tries` | Lower attempts wins. DNF is 99. |
| **History in Order** | `placements` | Fewer placements wins. Complete means placed == total recognized events (e.g. 6/6); incomplete is 99. |
| **Tradle** | `tries` | Fewer tries wins. DNF is 99. |
| **Chessle** | `attempts + 0.000001 × seconds` | Attempts dominate, elapsed time is a small tiebreak. The level (e.g. Medium) is preserved in the game name. |

A compact summary of the typical guess-style games is: **fewer guesses / attempts wins**; the exact failure fallback varies by game (99, 999, or 10000).

## How easiest and hardest are chosen

The wrap uses the distribution of everyone’s results, not the stand-out individual score. It:

1. Converts each result into a comparable **performance fraction** from 0 to 1.
2. Uses the **median** fraction per game, so a single lucky or unlucky player does not define difficulty.
3. Picks the highest median score as **easiest** and the lowest as **hardest**, then renders a playful description.

### Normalization used by games

- **Score-ratio games** (Trivmount, Thursday Thirty, Songless, Centumth, Majority, Songspot, History in Order, Magnitudle): use the direct score ratio `correct / total`.
- **Percentile games** (Roughly): transform the rank into a bounded fraction.
- **Travle**: performance = `1 / (1 + extra_guesses + hint_cost)`.
- **Metazooa, Globle, Redactle**: performance = `1 / guesses` (fewer guesses produces a larger fraction).
- **Regionle**: performance = `1 − (tries − 1) / 7`, clamped to 0–1.
- **Other guess-type games**: performance = `(7 − tries) / 6`, clamped to 0–1.

This normalization is intentionally a **heuristic for our own summary**, not a claim about the games’ official scoring scales. Open-ended guessing games may not compare cleanly to a 6-try puzzle; those games are excluded rather than given a false hard rating.

### Eligibility and safeguards

- **At least two players must compete on the game.** Solo results are not used to decide hardest/easiest.
- Games with **comparable score schemes only** participate. Redactle, Metazooa, Globle, Travle and Roughly are left out of cross-game difficulty unless specifically evaluated by a parser that makes sense.
- Only **positive performance fractions** are used. A zero result cannot win a difficulty slot.
- All difficulty fields respect Discord’s limits: fields are each capped and merged where needed rather than rejected by the API.

**Key distinction:** normalized performance is used to name the day’s easiest and hardest games; **rank_score**, podium points, crowns, and solve percentages remain separate numbers.

## Optional prison mode

Set `PRISON_ENABLED=1` to enable it. Currently, eligible games are **Globle, Metazooa, and Regionle** (not Flagle or Travle). A first-attempt win on those games confiscates the player’s daily points, but preserves the actual game result and placement. The sentence is announced once per player per day, and resets with the next day.

For visibility and transparency, `/stats` includes **lifetime prison days**. Daily and weekly wraps also show jailed players for that period when there are offenders.
