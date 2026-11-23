# Scoring and difficulty

This document describes how the bot turns shared puzzle results into a daily scoreboard, daily points, and easiest/hardest labels. It is meant to explain the system without assuming knowledge of the source code.

## The scores in play

There are two different numbers:

- **`rank_score`** – used to order results. **Lower is better.** It is a normalized leaderboard key, not a judgement of how good a puzzle actually was.
- **Historical difficulty percentile** – used only by the daily and weekly difficulty summaries. It compares the group's performance on a puzzle with that same game's own recent history. It is a 0–100 percentile where **higher means easier than usual**, and it **never affects rank_score or points**.

Every score is stored against `(board_date, user_id, game, puzzle_id)`. Reposting the same score on the same day overwrites the earlier entry.

## Daily rankings and points

Each `(game, puzzle_id)` is a leaderboard on its own. Results are ordered by `rank_score`, with ties sharing a dense rank (1, 1, 2 rather than 1, 2, 2).

For a result to earn **daily points** it must be in a **competitive game**, meaning at least two players posted a result for that puzzle today.

- Place 1: **3 points**
- Place 2: **2 points**
- Place 3: **1 point**
- Place 4+: **0 points**

Ties share both the placement and the points. Other players’ scores are not penalized. Daily points are aggregated into a standings footer named **“Today's points”**.

Yesterday's wrap also shows each standings player's played puzzle results and **points per game**: total daily points ÷ distinct `(game, puzzle_id)` records. Failed, DNF, and forfeit attempts count as played; this informational average never changes points or standings order.

### Elimination vs. graded results

For most games, only solved results compete. Unfinished/DNF players stay visible with their displayed score, but do not earn ranking points.

The graded games are **Trivmount** and **History in Order**: every scored result competes for points, even if it is not a perfect run. A Trivmount zero earns nothing. For History in Order, a numeric partial (e.g. 4/6, or 0/6) can therefore reach the daily podium, but only a full match (placed == total) counts as solved, a win, or a crown.

---

## Game-specific score calculation

In the table below, **lower rank_score wins**. The table describes the stored leaderboard key only; the difficulty summary uses the same canonical stored attempt with the status-aware ordering rules described further down.

| Game | rank_score assignment | Notes |
|---|---|---|
| **Metazooa** | `guesses` | The number of guesses is the main score. DNF is 999. |
| **Centumth** | `-points` | More points is better. Displayed as points / 490. |
| **Redactle** | `guesses + (10 × arrow hints) + (100 × chat hints) + 0.000001 × seconds` | Up-arrow hints 👆 cost 10 guesses each. Chat hints 💬 cost 100 each. Time is only a tiny tiebreak. DNF uses `10000 + guesses`. |
| **Flagle** | `tries − 0.05 × bonus emoji count` | Fewer tries wins; bonus emojis reward small rank improvements. DNF is 99, with the same bonus applied. |
| **Worldle** | `tries − (percentage × 0.001)` | Higher percentage gives a small improvement. DNF is 99. |
| **Travle** | `extra guesses + hints(n)` | With `n` hints, cost is `n(n+1)/2`, i.e. 1st hint +1, 2nd +2, 3rd +3. Unfinished localized results like “(3 pryč)” or “(3 away)” use `500 + distance`. X or unfinished is otherwise 999. |
| **Globle** | `guesses` | Lower guesses wins. Forfeit gives 999. |
| **Roughly** | `-percentile` on ordinary shares; `−(grid-average × 100 + best percentile / 10000)` on grid shares | The headline percentage is the **best round only**. When the grid is present, tiers stay `□=15%`, `▧=45%`, `▣=72.5%`, `■=92.5%`, and their mean is the **primary** result. That mean is a bucket estimate, not the game's exact internal total, so it is shown with `~`. The exact best-round percentile is a deliberately small **secondary** tiebreak: equal grid averages prefer the higher native best. Example: mean 65% with best 95% scores `−65.0095` but displays `~65% · best 95%`. Headline-only and grid-derived shares are kept in separate difficulty versions when their measurement scales are not comparable. |
| **Songless** | `−(solved songs × 100) + total tries` | More solved songs dominates. Fewer green-position tries breaks ties. Rows without a green mark cost 6 tries each. |
| **Magnitudle** | `-points` | More points (out of 500) wins. Forfeit gives 999. |
| **Majority** | `−(majorities won × 100 + crowd sync %)` | Majorities dominate; crowd-sync % breaks ties. Correct count and sync rate are separate values. |
| **Trivmount** | Perfect: `-100 × correct/total`. Imperfect: `10000 − 100 × correct/total` | **Only perfect climbs are solved.** Imperfect climbs still compete for points through the graded exception. For difficulty, a valid numeric partial is a measurable performance, not an automatic failure. |
| **Thursday Thirty** | `−(correct / 30 × 100)` | Ratio-based ranking; replayable any day, but only nudged in `/missing` on Thursdays. Unfinished is 10000. |
| **Songspot** | `−(known songs / total songs × 100) − (points / max points × 0.001)` | Known songs determine the primary placement; points are a small tiebreak. Performance uses known/total. |
| **Regionle** | `tries` | Simple fewer-tries wins over seven attempts. DNF is 99. |
| **Mathle** | `tries` | Lower attempts wins. DNF is 99. |
| **History in Order** | `−placements` | More correctly placed events wins, so a 4/6 ranks above a 2/6. Any numeric partial competes through the graded exception, but only a full match (placed == total, e.g. 6/6) counts as solved/won. DNF and forfeits do not compete. |
| **Tradle** | `tries` | Fewer tries wins. DNF is 99. |
| **Chessle** | `attempts + 0.000001 × seconds` | Attempts dominate, elapsed time is a small tiebreak. The level (e.g. Medium) is preserved in the game name. |
| **Maptap** | `-final score` | The published **final score** is the only authoritative result; higher is better. The preceding emoji-annotated values are not summed. A completed share with a final score of 0 is still a finished result, not a DNF, and participates in difficulty when it has enough history. |
| **Farflung** | `−(distance km + best valid rarity index / 10000)` | Distance is the primary score and higher kilometers are better. The best valid rarity is a tiny same-distance tiebreak; rarity order is `Common`, `Uncommon`, `Rare`, `Elusive`, `Farflung`. `Miss` is a valid zero-distance pin and is never treated as the best tip. A completed `0/500` is a finished result, not a DNF. |

A compact summary of the typical guess-style games is: **fewer guesses / attempts wins**; the exact failure fallback varies by game (99, 999, or 10000).

## How easiest and hardest are chosen

Difficulty is a **historical comparison**, not a cross-game absolute rating. For each game and meaningful variant the bot builds a baseline from earlier submitted results, then asks how well the group did today or this week relative to that game's own usual outcomes. It never compares a Worldle guess count with a Trivmount score.

### Historical baselines

- **Baseline key:** `(canonical game name, meaningful variant)`. Chessle Medium and Hard, named Regionle modes, and Roughly submodes each keep their own baseline. Different scoring formats or modes never share one.
- **Rolling window:** 90 calendar days, configured in `config.py`.
- **Strict cutoff:** only attempts with `board_date` **strictly before** the puzzle being evaluated. Same-day results and later dates never enter a baseline, including elsewhere in the same reporting week.
- **Minimum history:** at least **30 eligible attempts** and **10 distinct eligible puzzle IDs**. Short windows are allowed; the bot simply uses everything earlier within the 90-day range. If either minimum is missed, the game is excluded as **insufficient history**.
- **No heuristic fallback:** insufficient or incompatible history is omitted, never replaced by the old cross-game normalization.
- Only real submitted attempts are used. Corrupt, unparseable, missing, non-numeric, boolean, or non-finite ranking values are skipped rather than counted as failures. Arbitrary fallback sentinels such as `99`, `999`, or `10000` are not interpreted as genuine performance measurements.

### Performance ordering and valid attempts

Ordering follows each game's existing performance rules, with result status applied first:

- For elimination games, a valid solved result beats a valid failure regardless of the numeric sentinel used for the failure.
- Valid DNFs and failures are included and normally tie at the bottom. Failure progress is compared only where the parser defines a meaningful progression.
- Graded games keep measurable partials: Trivmount uses `correct / total`, and History in Order uses its negative placement count. A numeric partial is not an automatic DNF.
- Maptap's published final score is authoritative, including a completed `0`; it is a valid result, not a DNF.
- Roughly compares the five-round grid estimate first and the reported best-round percentile as the tiebreak. Headline-only and grid-derived shares are not blended when their measurement semantics are incompatible; they use separate difficulty versions/baselines instead.

Missing or corrupt records are not DNFs.

### Empirical midrank percentile

For a current attempt against `N` eligible historical attempts:

```
percentile = 100 × (W + 0.5 × T) / N
```

`W` is the number of historical attempts **strictly worse** than the current attempt and `T` is the number **equivalent** to it. The result is bounded 0–100; tied outcomes receive half credit. With no eligible history there is no percentile, and the puzzle cannot be rated.

Interpretation:

- **Low percentile:** worse than the game's usual performance (harder than usual).
- **Around 50:** typical.
- **High percentile:** better than usual (easier than usual).

Small differences near 50 are just that: a numeric historical position, not a confident claim of objective difficulty.

### Daily group score

Every `(game, puzzle_id)` is evaluated separately. Multiple puzzles from the same game on one date are not pooled. Duplicate rows for the same player are resolved by `user_id`, not display name, and only the canonical stored attempt is used.

A puzzle needs at least **two distinct valid players**. Then:

```
raw_group_percentile = mean(player_percentiles)
adjusted_percentile = (n × raw_group_percentile + 3 × 50) / (n + 3)
```

Every valid participant contributes, including failures. `n` is the number of distinct valid players and the configured shrinkage strength is 3; 50 is the neutral percentile. Example: player percentiles `10, 20, 30` give a raw mean of `20` and an adjusted score of `(3 × 20 + 3 × 50) / 6 = 35`.

The **easiest** puzzle of the day has the highest adjusted percentile and the **hardest** the lowest. Comparisons use unrounded values, exact ties use a deterministic canonical order, and the easiest/hardest comparison is omitted when fewer than two puzzles qualify.

### Weekly difficulty

1. Calculate every eligible puzzle's adjusted daily percentile, each using a baseline strictly before **that puzzle's own date**.
2. Group those puzzle scores by game and variant within the reporting week.
3. Average the puzzle scores for each group, giving every puzzle equal weight regardless of how many players it had.
4. Require at least **two distinct eligible puzzle instances**. A single instance, or a group made only of reposts/rows for one puzzle, does not compete.
5. The highest weekly average is **easiest** and the lowest is **hardest**; omit the comparison if too few games qualify.

Results from later in the week never influence earlier puzzles, and an active parent game's history never rescues a new or under-populated variant.

### Stored data and recalculation

Difficulty is calculated on demand from the canonical stored attempt for each `(board_date, user_id, game, puzzle_id)`. It does not rewrite stored results in SQLite, reconstruct invented totals, or require a schema migration. Score corrections are picked up by recalculating from the corrected canonical attempt, unchanged reruns produce identical output, and no future data leaks into a past evaluation.

**Key distinction:** the historical difficulty percentile names the day's or week's easiest and hardest puzzles. **`rank_score`**, actual leaderboard points, podium points, crowns, placements, player IDs, solve percentages, and the private-guild gate are unchanged.

## Optional prison mode

Set `PRISON_ENABLED=1` to enable it. Currently, eligible games are **Globle, Regionle, Metazooa, and Redactle** (not Flagle or Travle). A first-attempt win on those games confiscates the player’s daily points, but preserves the actual game result and placement. The sentence is announced once per player per day, and resets with the next day.

For visibility and transparency, `/stats` includes **lifetime prison days**. Daily and weekly wraps also show jailed players for that period when there are offenders.
