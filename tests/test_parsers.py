# -*- coding: utf-8 -*-
"""Fixture-based regression tests for the game result parsers.
Run: python -X utf8 tests/test_parsers.py   (exits 1 on failure)

Each fixture is a REAL-world paste format we've seen in the channel, paired
with the expected parse outcome. Add a fixture here when a format changes or
a new game lands — the sim boards render from the same parser.
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parsers import parse_all_games  # noqa: E402

# Maptap shares reused by both the compact cases and the explicit rank_score checks.
MAPTAP_SHARE = (
    "www.maptap.gg November 15\n\n"
    "86🎓 88🎉 100🎯 83🌟 80👏\n"
    "Final score: 863"
)
MAPTAP_ZERO_SHARE = (
    "www.maptap.gg December 3\r\n\r\n"
    "100🎓 92🎉 100🎯 88🌟 95👏\r\n"
    "Final score: 0"
)

# The user-supplied share that motivated the grid-first / best-round tiebreak.
# Grid mean = (0.725 x 3 + 0.15 + 0.925) / 5 = 0.65, native best round = 95%.
ROUGHLY_FULL_SHARE = (
    "roughly · Where? #321\n"
    "Where is the pygmy hippo located?\n"
    "Me: better than 95% of players\n"
    "▣▣▣□■\n\n"
    "Can you beat me?\n"
    "https://roughly.is/d/er6zn2erwp"
)
# Same grid (same 65% midpoint mean), deliberately weaker best round.
ROUGHLY_SAME_GRID_LOW_BEST = ROUGHLY_FULL_SHARE.replace("95%", "60%")
ROUGHLY_LEGACY_SHARE = (
    "roughly · Where from? #306\nCan you guess the country?\n"
    "Me: better than 97% of players\nhttps://roughly.is/d/abC123"
)
ROUGHLY_ALL_ROUND_GRID = (
    "roughly · How big? #77\nHow wide is a giant Pacific octopus, arm tip to arm tip?\n"
    "Me: better than 99% of players\n▧■▣■■\n\nCan you beat me?\n"
    "https://roughly.is/d/cqsdamg898"
)
ROUGHLY_MULTI_SHARE = (
    "roughly · Where from? #306\nWhich country?\n"
    "Me: better than 97% of players\n"
    "roughly · Where from? #307\nWhich country?\n"
    "Me: better than 24% of players\n■■\n"
    "https://roughly.is/d/second123"
)

# (case name, paste text, expected results as (game, puzzle_id, solved, display_score))
CASES = [
    # --- Metazooa ---
    ("metazooa solved",
     "Animal #1190\nI figured it out in 9 guesses!",
     [("Metazooa", "#1190", 1, "9 guesses")]),
    ("metazooa gave up",
     "Animal #1190\nI gave up after 30 guesses.",
     [("Metazooa", "#1190", 0, "DNF")]),
    ("metazooa stumped at 20-guess limit",
     "🦫 Animal #1202 🦝\nI was stumped by today's game!\n"
     "🟧🟧🟥🟧🟧🟧🟨🟥🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟥🟥\n"
     "🔥 0 | Avg. Guesses: 5.8\n\nhttps://metazooa.com/\n#metazooa",
     [("Metazooa", "#1202", 0, "DNF")]),

    # --- Centumth ---
    ("centumth",
     "Centumth Nov 3, 2026 - Topic Capital Cities\nRound 1 recap\nTotal: 217/490",
     [("Centumth", "Nov 3, 2026 (Topic Capital Cities)", 1, "217/490")]),

    # --- Redactle ---
    ("redactle same-line stats",
     "I cracked Redactle #1672 in 18 guesses!🎲 18 | 🔥 2 | Avg 67.50 | Hints: none | ⏱️ 1m10s\n\nhttps://redactle.net/",
     [("Redactle", "#1672", 1, "18g (1m10s)")]),
    ("redactle next-line stats",
     "I cracked Redactle #1670 in 43 guesses!\nHints👆1, 💬0 ⏱️ 6m16s",
     [("Redactle", "#1670", 1, "43g, 1h (6m16s)")]),
    ("redactle gave up",
     "I gave up on Redactle #1670 after 55 guesses.\n⏱️ 12m03s",
     [("Redactle", "#1670", 0, "DNF (55g)")]),
    ("redactle shared-player solved",
     "We cracked Redactle #1696 in 166 guesses with 1 other player!"
     "🎲 166 | 🔥 0 | Avg 69.88 | Hints👆1, 💬0 | ⏱️ 29m35s\n\n"
     "https://redactle.net/en/g/wQn4cPJ",
     [("Redactle", "#1696", 1, "166g, 1h (29m35s)")]),
    ("redactle shared-player gave up",
     "We gave up on Redactle #1697 after 72 guesses with 2 other players."
     "🎲 72 | 🔥 0 | Avg 88.12 | Hints👆0, 💬0 | ⏱️ 41m02s",
     [("Redactle", "#1697", 0, "DNF (72g)")]),

    # --- Flagle ---
    ("flagle solved",
     "#Flagle #1715 (02.11.2026) 2/6\n🟥🟩\n🟩🟩\n",
     [("Flagle", "#1715", 1, "2/6")]),
    ("flagle failed",
     "#Flagle #1715 (02.11.2026) X/6\n🟥🟥\n🟥🟥\n",
     [("Flagle", "#1715", 0, "X/6")]),

    # --- Worldle ---
    ("worldle",
     "#Worldle #1746 (02.11.2026) 4/6 (100%)",
     [("Worldle", "#1746", 1, "4/6 (100%)")]),

    # --- Travle ---
    ("travle +2 with hint",
     "#travle #1419 +2 (1 rada)",
     [("Travle", "#1419", 1, "+2 (1 rada)")]),
    ("travle +0",
     "#travle #1419 +0",
     [("Travle", "#1419", 1, "+0")]),
    ("travle X",
     "#travle #1419 X",
     [("Travle", "#1419", 0, "X")]),
    ("travle czech DNF — no digit stealing",
     "#travle #1421 (3 pryč)\n🟥🟧🟧🟥🟧🟧🟧🟧🟩\nhttps://travle.earth",
     [("Travle", "#1421", 0, "DNF (3 pryč)")]),
    ("travle english away DNF",
     "#travle #1421 (3 away)",
     [("Travle", "#1421", 0, "DNF (3 away)")]),
    ("travle note without number",
     "#travle #1421 (pryč)",
     [("Travle", "#1421", 0, "DNF (pryč)")]),

    # --- Globle ---
    ("globle single row",
     "🌎 Nov 3, 2026 🌍🔥 1 | Avg. Guesses: 9\n🟧🟧🟥🟧🟨🟥🟧🟥\n🟩 = 9\n\nhttps://globle-game.com/\n#globle",
     [("Globle", "Nov 3, 2026", 1, "9 guesses")]),
    ("globle multi row (many guesses)",
     "🌎 Nov 4, 2026 🌍🔥 2 | Avg. Guesses: 7.33\n🟥🟥🟥🟥🟥🟥🟥🟥\n🟥🟥🟥🟧🟥🟥🟥🟥\n🟧🟨🟧🟥🟥🟥🟥🟥\n🟩 = 15",
     [("Globle", "Nov 4, 2026", 1, "15 guesses")]),

    # --- Roughly ---
    ("roughly with duel link",
     "roughly · Where from? #306\nCan you guess the country?\nMe: better than 97% of players\nhttps://roughly.is/d/abC123",
     [("Roughly (Where from)", "#306", 1, "Top 3% (97%)")]),

    # --- Songless ---
    ("songless two categories",
     "Songless #431\n🟩⬜⬜⬜⬜⬜ [Rock]\n⬜🟩⬜⬜⬜⬜ [Pop]",
     [("Songless", "#431", 1, "2/2 (Roc:1 Pop:2)")]),

    # --- Wordle ---
    ("wordle",
     "Wordle 1958 3/6",
     [("Wordle", "#1958", 1, "3/6")]),
    ("wordle failed",
     "Wordle 1958 X/6",
     [("Wordle", "#1958", 0, "X/6")]),

    # --- Magnitudle ---
    ("magnitudle",
     "Magnitudle — Size It Up\n2026-11-03\n\nScore: 199/500\n\n🟥🟥🟥🟥⬜ 75\n⬜⬜⬜⬜⬜ 0\n\nhttps://magnitudle.com/size-it-up",
     [("Magnitudle (Size It Up)", "2026-11-03", 1, "199/500")]),
    ("magnitudle current Size It Up serial header",
     "Size It Up\r#98\r\rScore: 230/500\r\n"
     "🟥⬜⬜⬜⬜ 28\n🟥🟥⬜⬜⬜ 47\n🟥🟥🟥🟥🟥 100\n"
     "⬜⬜⬜⬜⬜ 5\n🟥🟥🟥⬜⬜ 50\n\nhttps://magnitudle.com/size-it-up",
     [("Magnitudle (Size It Up)", "#98", 1, "230/500")]),

    # --- Majority ---
    ("majority",
     "Majority #64\n☆⭐☆☆⭐\n2/5 majorities · 52% crowd sync\nhttps://www.majoritygame.com/",
     [("Majority", "#64", 1, "2/5 (52%)")]),
    ("majority mangled percent",
     "Majority #65\n☆☆⭐⭐☆\n2/5 majorities · 64kkk% crowd sync\nhttps://www.majoritygame.com/",
     [("Majority", "#65", 1, "2/5 (64%)")]),

    # --- Trivmount ---
    ("trivmount partial",
     "Trivmount #40 11/12\n🟧🟧🟧🟧🟧🟧🟧🟧🟧🟧🟧🟥\nhttps://trivmount.com/",
     [("Trivmount", "#40", 0, "11/12")]),
    ("trivmount perfect with emoji",
     "Trivmount #40 ⛰️ 12/12\n🟧🟧🟧🟧🟧🟧🟧🟧🟧🟧🟧🟧\nhttps://trivmount.com/",
     [("Trivmount", "#40", 1, "12/12")]),
    ("trivmount SUMMIT with grid",
     "Trivmount #40 ⛰️ SUMMIT\n🟧🟧🟧🟧🟧🟧🟧🟧🟧🟧🟧🟧\nhttps://trivmount.com/",
     [("Trivmount", "#40", 1, "12/12")]),
    ("trivmount SUMMIT without grid",
     "Trivmount #41 ⛰️ SUMMIT\nhttps://trivmount.com/",
     [("Trivmount", "#41", 1, "12/12")]),

    # --- Thursday Thirty ---
    ("thursday thirty",
     "I just completed Thursday Thirty Week 33!🧠 22/30 (73%)\n\n🟩🟩🟩🟥🟩🟩🟩🟩🟩🟩\n🟩🟩🟩🟩🟩🟩🟩🟥🟩🟩\n🟥🟥🟥🟩🟥🟥🟩🟥🟩🟩\n\nTake the quiz: https://t30.teuteuf.fr/",
     [("Thursday Thirty", "Week 33", 1, "22/30 (73%)")]),

    ("thursday thirty newline before brain",
     "I just completed Thursday Thirty Week 43!\n🧠 18/30 (60%)\n\n🟩🟩🟩🟥🟩🟩🟥🟩🟥🟥\n🟩🟥🟩🟩🟩🟩🟩🟩🟥🟥\n🟩🟩🟩🟥🟩🟥🟥🟩🟥🟥\n\nTake the quiz: https://t30.teuteuf.fr",
     [("Thursday Thirty", "Week 43", 1, "18/30 (60%)")]),
    ("thursday thirty without brain",
     "Thursday Thirty Week 43! 18/30",
     [("Thursday Thirty", "Week 43", 1, "18/30 (60%)")]),

    # --- Songspot ---
    ("songspot",
     "songspot · Daily Challenge · Nov 9, 2026\n4/5 · 3,450 / 6,000 pts\n✓ ✓ × ✓ ✓\nI knew 4 of 5. How many do you know?\nhttps://songspot.co/daily\n#songspot",
     [("Songspot", "Nov 9, 2026", 1, "4/5 · 3,450 pts")]),

    # --- Regionle ---
    ("regionle solved",
     "Regionle #143 4/7\n⬛⬛⬛⬛⬛⬛⬛\n🟨⬛🟨🟨⬛🟩⬛\n⬛⬛⬛⬛⬛🟩⬛\n🟩🟩🟩🟩🟩🟩🟩\nhttps://regionle.io/",
     [("Regionle", "#143", 1, "4/7")]),
    ("regionle failed",
     "Regionle #143 X/7\n⬛⬛⬛⬛⬛⬛⬛\nhttps://regionle.io/",
     [("Regionle", "#143", 0, "X/7")]),
    ("regionle named special exhausts seven guesses",
     "Regionle US States #148 X/7\n"
     "⬛🟨🟨⬛⬛⬛🟩\n⬛🟨⬛⬛⬛⬛🟩\n⬛⬛🟨⬛🟩⬛🟩\n"
     "🟨🟨🟨⬛⬛⬛⬛\n🟨🟨⬛⬛🟨⬛🟩\n⬛⬛⬛⬛🟩⬛🟩\n"
     "⬛🟨🟨🟨🟨⬛🟩",
     [("Regionle (US States)", "#148", 0, "X/7")]),

    ("roughly all-round symbol grid, not just best",
     "roughly · How big? #77\nHow wide is a giant Pacific octopus, arm tip to arm tip?\nMe: better than 99% of players\n▧■▣■■\n\nCan you beat me?\nhttps://roughly.is/d/cqsdamg898",
     [("Roughly (How big)", "#77", 1, "~79% · best 99%")]),

    # --- Mathle ---
    ("mathle",
     "Mathle №214 4/6\n\n🟩🟨⬜⬜⬜🟨⬜\n🟨🟨⬜⬜🟨🟨🟩⬜\n🟩🟩🟩🟨🟩⬜🟩⬜\n🟩🟩🟩🟩🟩🟩🟩🟩\n\nhttps://wordle.global/p/J_-BeRmOFP8",
     [("Mathle", "#214", 1, "4/6")]),
    ("mathle failed",
     "Mathle №214 X/6\nhttps://wordle.global/en/mathle",
     [("Mathle", "#214", 0, "X/6")]),

    # --- History in Order ---
    ("history in order",
     "History in Order №214 · 6/6\n🟩🟩🟩🟩🟩🟩\n\nhttps://wordle.global/p/1jMZbRM0Db0",
     [("History in Order", "#214", 1, "6/6")]),
    ("history in order incomplete",
     "History in Order №214 · 4/6",
     [("History in Order", "#214", 0, "4/6")]),

    # --- Tradle ---
    ("tradle solved",
     "#Tradle #1710 3/6\n🟩🟩🟩🟩⬜\n🟩🟩🟩🟩🟨\n🟩🟩🟩🟩🟩\nhttps://tradle.net/",
     [("Tradle", "#1710", 1, "3/6")]),
    ("tradle failed",
     "#Tradle #1710 X/6\n⬜🟨🟩🟨🟪🟪\nhttps://tradle.net/",
     [("Tradle", "#1710", 0, "X/6")]),

    ("redactle singular guess with priced hints",
     "I cracked Redactle #1680 in 1 guess!\n🎲 1 | 🔥 2 | Avg 68.39 | Hints👆3, 💬1 | ⏱️ 2m18s\n\nhttps://redactle.net/",
     [("Redactle", "#1680", 1, "1g, 4h (2m18s)")]),

    # --- Chessle ---
    ("chessle medium",
     "Chessle №216 · Medium · ✓ 1/6 · 1m 14s\n🟩🟩🟩\n\nhttps://wordle.global/p/qi4iCGg2_go",
     [("Chessle (Medium)", "#216", 1, "1/6 · 1m 14s")]),
    ("chessle unsolved",
     "Chessle №216 · Medium · X/6 · 1m 54s\nhttps://wordle.global/en/chessle",
     [("Chessle (Medium)", "#216", 0, "X/6 · 1m 54s")]),

    # --- Maptap ---
    ("maptap",
     MAPTAP_SHARE,
     [("Maptap", "November 15", 1, "863 pts")]),
    ("maptap zero is completed, non-hardcoded date (CRLF)",
     MAPTAP_ZERO_SHARE,
     [("Maptap", "December 3", 1, "0 pts")]),

    ("roughly multiple results with independent paths",
     "roughly · Where from? #306\nWhich country?\nMe: better than 97% of players\nroughly · Where from? #307\nWhich country?\nMe: better than 24% of players\n■■\nhttps://roughly.is/d/second123",
     [("Roughly (Where from)", "#306", 1, "Top 3% (97%)"),
      ("Roughly (Where from)", "#307", 1, "~92% · best 24%")]),

    ("farflung with rarity tips",
     "Farflung #49 · 230/500 kmCommon · Common · Common · Common · Rare\n"
     "https://farflung.game/s/fpfcf2?e=49",
     [("Farflung", "#49", 1, "230/500 (Rare)")]),
    ("farflung best rarity is Farflung",
     "Farflung Expedition #50 · 500/500 km · Common · Uncommon · Rare · Elusive · Farflung",
     [("Farflung", "#50", 1, "500/500 (Farflung)")]),
    ("farflung without rarity labels",
     "Farflung #51 · 120/500 km",
     [("Farflung", "#51", 1, "120/500")]),
    ("farflung miss is not the best tip",
     "Farflung #52 · 230/500 kmCommon · Miss · Common · Rare · Elusive",
     [("Farflung", "#52", 1, "230/500 (Elusive)")]),
    ("farflung all misses still complete at zero km",
     "Farflung #53 · 0/500 kmMiss · Miss · Miss · Miss · Miss",
     [("Farflung", "#53", 1, "0/500")]),

    # --- Negatives: must NOT match ---
    ("banter about wordle", "did you play wordle today?", []),
    ("banter about globle", "this globle is impossible", []),
    ("trivmount chat mention", "hey did you play Trivmount #40 guys", []),
]


# The compact CASES tuples don't expose rank_score, so verify the ranking key
# explicitly for games where "higher result is better" could be inverted.
# (case name, paste text, expected (game, puzzle_id, solved, rank_score, display_score))
RANK_CASES = [
    ("maptap ranks final score higher-is-better",
     MAPTAP_SHARE,
     [("Maptap", "November 15", 1, -863.0, "863 pts")]),
    ("maptap zero is completed, not DNF",
     MAPTAP_ZERO_SHARE,
     [("Maptap", "December 3", 1, 0.0, "0 pts")]),
    ("history full ranks by negative placements",
     "History in Order №214 · 6/6",
     [("History in Order", "#214", 1, -6.0, "6/6")]),
    ("history partial ranks by negative placements",
     "History in Order №214 · 4/6",
     [("History in Order", "#214", 0, -4.0, "4/6")]),
    ("history uses the native total, not a hardcoded one",
     "History in Order №300 · 8/10",
     [("History in Order", "#300", 0, -8.0, "8/10")]),
    ("magnitudle current serial header ranks higher points better",
     "Size It Up\n#98\nScore: 230/500",
     [("Magnitudle (Size It Up)", "#98", 1, -230.0, "230/500")]),
    ("farflung ranks distance higher-is-better with rarity tiebreak",
     "Farflung #49 · 230/500 kmCommon · Common · Common · Common · Rare\n"
     "https://farflung.game/s/fpfcf2?e=49",
     [("Farflung", "#49", 1, -230.0002, "230/500 (Rare)")]),
    ("farflung same distance ranks best rarity better",
     "Farflung #52 · 140/500 km · Common · Uncommon · Rare · Elusive · Farflung\n"
     "https://farflung.game/s/example?e=52",
     [("Farflung", "#52", 1, -140.0004, "140/500 (Farflung)")]),
]


def roughly_grid_tiebreak_checks() -> tuple[int, list[str]]:
    """Verify the midpoint average stays primary and the native best only breaks ties."""
    failures: list[str] = []
    checks = 0

    def check(name, actual, expected):
        nonlocal checks
        checks += 1
        if actual != expected:
            failures.append(f"{name}\n  expected: {expected!r}\n  got:      {actual!r}")

    def check_close(name, actual, expected, tolerance=1e-9):
        nonlocal checks
        checks += 1
        if not isinstance(actual, (int, float)) or abs(actual - expected) > tolerance:
            failures.append(f"{name}\n  expected: {expected!r} (+-{tolerance})\n  got:      {actual!r}")

    # Full user example: grid midpoint ~65% is primary, best 95% is the tiny tiebreak.
    full = parse_all_games(ROUGHLY_FULL_SHARE)
    check("full share count", len(full), 1)
    result = full[0]
    check("full game/mode", result["game"], "Roughly (Where)")
    check("full puzzle id", result["puzzle_id"], "#321")
    check("full solved", result["solved"], 1)
    check_close("full base rank keeps midpoint average", result["base_rank_score"], -65.0)
    check_close("full rank adds best/10000 tiebreak", result["rank_score"], -65.0095)
    check("full display keeps coarse midpoint estimate", result["display_score"],
          "~65% · best 95%")
    check("full duel url", result["extra_url"], "https://roughly.is/d/er6zn2erwp")

    # Same grid mean, different native best: primary tie, higher exact percentile wins.
    low = parse_all_games(ROUGHLY_SAME_GRID_LOW_BEST)[0]
    check("same-grid low display", low["display_score"], "~65% · best 60%")
    check_close("same-grid midpoint tie", low["base_rank_score"], result["base_rank_score"], 0.0)
    check("same-grid higher best strictly outranks", low["rank_score"] > result["rank_score"], True)
    check_close("same-grid rank gap is only the percentile delta",
                result["rank_score"] - low["rank_score"], -(95 - 60) / 10000.0)

    # Legacy no-grid share: ordinary percentile ranking, no second tiebreak.
    legacy = parse_all_games(ROUGHLY_LEGACY_SHARE)[0]
    check("legacy game/mode", legacy["game"], "Roughly (Where from)")
    check("legacy rank", legacy["rank_score"], -97.0)
    check("legacy base rank", legacy["base_rank_score"], -97.0)
    check("legacy display", legacy["display_score"], "Top 3% (97%)")
    check("legacy duel url", legacy["extra_url"], "https://roughly.is/d/abC123")

    # Existing all-round grid fixture keeps its midpoint value and gains the best label.
    all_round = parse_all_games(ROUGHLY_ALL_ROUND_GRID)[0]
    check_close("all-round grid base rank", all_round["base_rank_score"], -79.0)
    check_close("all-round grid rank", all_round["rank_score"], -79.0099)
    check("all-round grid display", all_round["display_score"], "~79% · best 99%")
    check("all-round grid duel url", all_round["extra_url"], "https://roughly.is/d/cqsdamg898")

    # Multi-share scoping: each tail keeps its own mode, grid, and duel link.
    multi = parse_all_games(ROUGHLY_MULTI_SHARE)
    check("multi-share count", len(multi), 2)
    check("multi-share urls", [m["extra_url"] for m in multi],
          [None, "https://roughly.is/d/second123"])
    check("multi-share displays", [m["display_score"] for m in multi],
          ["Top 3% (97%)", "~92% · best 24%"])
    check_close("multi-share no-grid rank", multi[0]["rank_score"], -97.0)
    check_close("multi-share grid base rank", multi[1]["base_rank_score"], -92.5)
    check_close("multi-share grid rank", multi[1]["rank_score"], -92.5024)

    return checks, failures


def main() -> int:
    failures = 0
    for name, text, expected in CASES:
        got = parse_all_games(text)
        got_tuples = [(g["game"], g["puzzle_id"], g["solved"], g["display_score"]) for g in got]
        if got_tuples != expected:
            failures += 1
            print(f"FAIL {name}")
            print(f"  text:     {text!r}")
            print(f"  expected: {expected}")
            print(f"  got:      {got_tuples}")
        else:
            printable = [f"{g} {d}" for g, _, _, d in expected] or ["(no match)"]
            print(f"ok   {name}: {', '.join(printable)}")
    for name, text, expected in RANK_CASES:
        got = parse_all_games(text)
        got_tuples = [(g["game"], g["puzzle_id"], g["solved"], g["rank_score"], g["display_score"]) for g in got]
        if got_tuples != expected:
            failures += 1
            print(f"FAIL {name} (rank_score)")
            print(f"  text:     {text!r}")
            print(f"  expected: {expected}")
            print(f"  got:      {got_tuples}")
        else:
            printable = [f"{g} rank={r} {d}" for g, _, _, r, d in expected] or ["(no match)"]
            print(f"ok   {name}: {', '.join(printable)}")
    total = len(CASES) + len(RANK_CASES)
    extra_total, extra_failures = roughly_grid_tiebreak_checks()
    total += extra_total
    failures += len(extra_failures)
    for failure in extra_failures:
        print(f"FAIL {failure}")
    if not extra_failures:
        print(f"ok   roughly grid midpoint primary / best-round tiebreak ({extra_total} checks)")
    print(f"\n{total - failures}/{total} cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
