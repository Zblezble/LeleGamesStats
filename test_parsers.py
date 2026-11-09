# -*- coding: utf-8 -*-
"""Fixture-based regression tests for the game result parsers.
Run: python test_parsers.py   (exits 1 on failure)

Each fixture is a REAL-world paste format we've seen in the channel, paired
with the expected parse outcome. Add a fixture here when a format changes or
a new game lands — the sim boards render from the same parser.
"""
import os
import sys

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parsers import parse_all_games  # noqa: E402

# (case name, paste text, expected results as (game, puzzle_id, solved, display_score))
CASES = [
    # --- Metazooa ---
    ("metazooa solved",
     "Animal #1190\nI figured it out in 9 guesses!",
     [("Metazooa", "#1190", 1, "9 guesses")]),
    ("metazooa gave up",
     "Animal #1190\nI gave up after 30 guesses.",
     [("Metazooa", "#1190", 0, "DNF")]),

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

    # --- Negatives: must NOT match ---
    ("banter about wordle", "did you play wordle today?", []),
    ("banter about globle", "this globle is impossible", []),
    ("trivmount chat mention", "hey did you play Trivmount #40 guys", []),
]


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
    print(f"\n{len(CASES) - failures}/{len(CASES)} cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
