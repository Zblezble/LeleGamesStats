"""Game result parsers. parse_all_games scans a message and returns one dict per result:
{game, puzzle_id, solved (1/0), rank_score (LOWER IS ALWAYS BETTER), display_score, extra_url}
"""
import re

import config


def parse_all_games(text: str) -> list[dict]:
    results = []

    # 1. METAZOOA (Animal #1190)
    for m in re.finditer(
        r"Animal #(\d+).*?\n(?:I figured it out in (\d+) guesses!|I gave up[^\n]*)",
        text, re.IGNORECASE
    ):
        pid, guesses = m.group(1), m.group(2)
        solved = 1 if guesses else 0
        g_val = int(guesses) if guesses else 999
        results.append({
            "game": "Metazooa",
            "puzzle_id": f"#{pid}",
            "solved": solved,
            "rank_score": float(g_val),
            "display_score": f"{g_val} guesses" if solved else "DNF",
            "extra_url": None
        })

    # 2. CENTUMTH (Centumth Nov 2, 2026 - Topic ... Total: 217/490)
    for m in re.finditer(
        r"Centumth ([A-Za-z]+ \d+, \d{4}) - ([^\n]+)\n(?:[^\n]+\n)?Total:\s*(\d+)/490",
        text
    ):
        date_str, topic, pts = m.group(1), m.group(2).strip(), int(m.group(3))
        results.append({
            "game": "Centumth",
            "puzzle_id": f"{date_str} ({topic[:22]}..)" if len(topic) > 22 else f"{date_str} ({topic})",
            "solved": 1 if pts > 0 else 0,
            "rank_score": float(-pts),  # Higher points = lower rank_score
            "display_score": f"{pts}/490",
            "extra_url": None
        })

    # 3. REDACTLE (Redactle #1670 — stats may be on the same line or the next one)
    for m in re.finditer(
        r"I (cracked|gave up on) Redactle #(\d+) (?:in|after) (\d+) guesses[.!]([^\n]*)(?:\n([^\n]+))?",
        text
    ):
        status, pid, guesses = m.group(1), m.group(2), int(m.group(3))
        stats_line = m.group(4) or m.group(5) or ""
        solved = 1 if status == "cracked" else 0
        # Parse hints: "Hints👆1, 💬0", "Hints: 2" or "Hints: none"
        h_match = re.search(r"Hints👆(\d+),\s*💬(\d+)", stats_line)
        h2_match = re.search(r"Hints:\s*(\d+)", stats_line)
        if h_match:
            hints = int(h_match.group(1)) + int(h_match.group(2))
        elif h2_match:
            hints = int(h2_match.group(1))
        else:
            hints = 0
        # Parse time: "⏱️ 6m16s" (emoji with or without variation selector)
        t_match = re.search(r"⏱️?\s*(?:(\d+)h)?(?:(\d+)m)?(\d+)s", stats_line)
        secs = 0
        if t_match:
            secs = (int(t_match.group(1) or 0) * 3600 +
                    int(t_match.group(2) or 0) * 60 +
                    int(t_match.group(3) or 0))
        time_str = re.search(r"⏱️?\s*([0-9hms]+)", stats_line)
        t_disp = f" ({time_str.group(1)})" if time_str else ""
        h_disp = f", {hints}h" if hints > 0 else ""

        # Solved beats unsolved; then fewer guesses, fewer hints, faster time
        base = guesses if solved else (10000 + guesses)
        rank_score = base + (hints * 0.01) + (secs * 0.000001)

        results.append({
            "game": "Redactle",
            "puzzle_id": f"#{pid}",
            "solved": solved,
            "rank_score": rank_score,
            "display_score": f"{guesses}g{h_disp}{t_disp}" if solved else f"DNF ({guesses}g)",
            "extra_url": None
        })

    # 4. FLAGLE (#Flagle #1715 (02.11.2026) 3/6)
    for m in re.finditer(
        r"#Flagle #(\d+)\s*\([^)]+\)\s*([1-6X])/6\s*\n((?:[🟥🟩⬛⬜]+\n?)+)([^\n]*)",
        text
    ):
        pid, score_ch, _grid, bonus_line = m.group(1), m.group(2), m.group(3), m.group(4).strip()
        solved = 0 if score_ch == "X" else 1
        tries = int(score_ch) if solved else 99
        # Count bonus emojis if present (e.g., 🗺️🛡️⛳️🧭🪙)
        bonus_emojis = "".join(c for c in bonus_line if c in "🗺️🛡️⛳🧭🪙")
        bonus_count = len([c for c in bonus_line if c in "🗺🛡⛳🧭🪙"])
        rank_score = float(tries) - (bonus_count * 0.05)
        disp = f"{score_ch}/6" + (f" {bonus_emojis}" if bonus_emojis else "")
        results.append({
            "game": "Flagle",
            "puzzle_id": f"#{pid}",
            "solved": solved,
            "rank_score": rank_score,
            "display_score": disp,
            "extra_url": None
        })

    # 5. WORLDLE (#Worldle #1746 (02.11.2026) 4/6 (100%))
    for m in re.finditer(
        r"#Worldle #(\d+)\s*\([^)]+\)\s*([1-6X])/6\s*\((\d+)%\)",
        text
    ):
        pid, score_ch, pct = m.group(1), m.group(2), int(m.group(3))
        solved = 0 if score_ch == "X" else 1
        tries = int(score_ch) if solved else 99
        rank_score = float(tries) - (pct * 0.001)
        results.append({
            "game": "Worldle",
            "puzzle_id": f"#{pid}",
            "solved": solved,
            "rank_score": rank_score,
            "display_score": f"{score_ch}/6 ({pct}%)",
            "extra_url": None
        })

    # 6. TRAVLE (#travle #1419 +4 (3 rady))
    # Scored/failed-with-X form. The score must be separated from the puzzle id,
    # otherwise "#1421 (3 pryč)" would misparse as id #142 with score 1.
    for m in re.finditer(
        r"#travle #(\d+)\s+([+\-]?\d+|X)(?:\s*\(([^)]+)\))?",
        text, re.IGNORECASE
    ):
        pid, score_str, note = m.group(1), m.group(2), m.group(3)
        solved = 0 if score_str.upper() == "X" else 1
        extra_guesses = int(score_str) if solved else 999
        hints = 0
        if note:
            h_m = re.search(r"(\d+)\s*(?:rad|hint)", note, re.IGNORECASE)
            if h_m:
                hints = int(h_m.group(1))
        # Hints cost like guesses, increasingly: 1st +1, 2nd +2, 3rd +3 (triangular)
        rank_score = float(extra_guesses) + (hints * (hints + 1) / 2)
        note_disp = f" ({note})" if note else ""
        results.append({
            "game": "Travle",
            "puzzle_id": f"#{pid}",
            "solved": solved,
            "rank_score": rank_score,
            "display_score": f"{score_str}{note_disp}",
            "extra_url": None
        })

    # 6b. TRAVLE unfinished run: "#travle #1421 (3 pryč)" / "(3 away)" — no score,
    # just a note saying how far from connecting (any locale). DNF, ranked by distance.
    for m in re.finditer(
        r"#travle #(\d+)\s*\(([^)]+)\)",
        text, re.IGNORECASE
    ):
        pid, note = m.group(1), m.group(2)
        away_m = re.match(r"\s*(\d+)", note)
        away = int(away_m.group(1)) if away_m else 499
        results.append({
            "game": "Travle",
            "puzzle_id": f"#{pid}",
            "solved": 0,
            "rank_score": float(500 + away),  # after all successes; closer finish = better
            "display_score": f"DNF ({note})",
            "extra_url": None
        })

    # 7. GLOBLE (🌎 Nov 1, 2026 🌍 ... N grid rows ... 🟩 = 3)
    for m in re.finditer(
        r"[🌎🌍🌏]\s*([A-Za-z]+ \d+, \d{4})\s*[🌎🌍🌏].*?\n(?:[^\n]*\n)*?[🟧🟥🟨🟩⬜⬛]+\s*=\s*(\d+)",
        text
    ):
        date_str, guesses = m.group(1), int(m.group(2))
        results.append({
            "game": "Globle",
            "puzzle_id": date_str,
            "solved": 1,
            "rank_score": float(guesses),
            "display_score": f"{guesses} guesses",
            "extra_url": None
        })

    # 8. ROUGHLY (roughly · Where from? #306 ... Me: better than 97% of players ... https://roughly.is/d/xxxx)
    for m in re.finditer(
        r"roughly\s*·\s*([^\n#]+)#(\d+)\s*\n([^\n]+)\nMe:\s*better than (\d+)% of players(?:.*?(https://roughly\.is/d/[a-zA-Z0-9]+))?",
        text, re.DOTALL
    ):
        submode = m.group(1).strip().rstrip("?")
        pid = m.group(2)
        pct = int(m.group(4))
        duel_url = m.group(5)
        results.append({
            "game": f"Roughly ({submode})",
            "puzzle_id": f"#{pid}",
            "solved": 1,
            "rank_score": float(-pct),  # Higher % = better
            "display_score": f"Top {100 - pct}% ({pct}%)",
            "extra_url": duel_url
        })

    # 9. SONGLESS (Songless #431 + multi-row blocks)
    for m in re.finditer(
        r"Songless #(\d+)\s*\n+((?:[⬜🟨🟩🟥⬛]+\s*\[[^\]]+\]\s*\n?)+)",
        text
    ):
        pid, block = m.group(1), m.group(2).strip()
        rows = [r.strip() for r in block.split("\n") if r.strip()]
        total_songs = len(rows)
        solved_songs = 0
        total_tries = 0
        cat_details = []

        for r in rows:
            cat_m = re.search(r"([⬜🟨🟩🟥⬛]+)\s*\[([^\]]+)\]", r)
            if not cat_m:
                continue
            grid, cat_name = cat_m.group(1), cat_m.group(2)
            short_cat = cat_name[:3]
            if "🟩" in grid:
                solved_songs += 1
                try_pos = grid.index("🟩") + 1
                total_tries += try_pos
                cat_details.append(f"{short_cat}:{try_pos}")
            else:
                total_tries += 6
                cat_details.append(f"{short_cat}:X")

        # More solved songs wins; fewer total tries breaks ties
        rank_score = float(-solved_songs * 100 + total_tries)
        detail_str = " ".join(cat_details)
        results.append({
            "game": "Songless",
            "puzzle_id": f"#{pid}",
            "solved": 1 if solved_songs > 0 else 0,
            "rank_score": rank_score,
            "display_score": f"{solved_songs}/{total_songs} ({detail_str})",
            "extra_url": None
        })

    # 10. WORDLE (Pasted text: Wordle 1958 5/6)
    for m in re.finditer(r"Wordle\s+(\d[\d,]*)\s+([1-6X])/6", text):
        pid = m.group(1).replace(",", "")
        score_ch = m.group(2)
        solved = 0 if score_ch == "X" else 1
        tries = int(score_ch) if solved else 99
        results.append({
            "game": "Wordle",
            "puzzle_id": f"#{pid}",
            "solved": solved,
            "rank_score": float(tries),
            "display_score": f"{score_ch}/6",
            "extra_url": None
        })

    # 11. MAGNITUDLE (Magnitudle — Size It Up \n 2026-11-03 \n Score: 199/500 + grid rows)
    for m in re.finditer(
        r"Magnitudle\s*[—–-]\s*([^\n]+)\n(\d{4}-\d{2}-\d{2})\s*\n+\s*Score:\s*(\d+)/500",
        text
    ):
        submode = m.group(1).strip()
        date_str, pts = m.group(2), int(m.group(3))
        results.append({
            "game": f"Magnitudle ({submode})",
            "puzzle_id": date_str,
            "solved": 1 if pts > 0 else 0,
            "rank_score": float(-pts),  # Higher points = lower rank_score
            "display_score": f"{pts}/500",
            "extra_url": None
        })

    # 12. MAJORITY (Majority #64 \n ☆⭐☆☆⭐ \n 2/5 majorities · 52% crowd sync)
    # The percentage may be mangled ("64kkk%") — tolerate a few junk chars before "%".
    for m in re.finditer(
        r"Majority #(\d+)\s*\n(?:[☆⭐]+\s*\n)?(\d+)/(\d+) majorities · (\d+)[^\d%]{0,5}% crowd sync",
        text
    ):
        pid, maj, total, sync = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
        results.append({
            "game": "Majority",
            "puzzle_id": f"#{pid}",
            "solved": 1 if maj > 0 else 0,
            "rank_score": float(-maj * 100 - sync),  # More majorities + higher sync = better
            "display_score": f"{maj}/{total} ({sync}%)",
            "extra_url": None
        })

    # 13. TRIVMOUNT (Trivmount #40 11/12 | #40 ⛰️ 12/12 | #40 ⛰️ SUMMIT + grid row)
    # A win is a perfect climb (total/total), which the share text renders as "SUMMIT".
    # The ⛰️ marker and other decoration between id and score are tolerated.
    for m in re.finditer(
        r"Trivmount #(\d+)[^\d/\n]*(?:(\d+)/(\d+)|(SUMMIT))(?:\s*\n([⬜🟨🟩🟥🟧⬛]+))?",
        text
    ):
        pid = m.group(1)
        if m.group(4):  # SUMMIT = perfect run; take the length from the grid row
            grid = m.group(5) or ""
            total = len(grid) if grid else 12
            correct = total
        else:
            correct, total = int(m.group(2)), int(m.group(3))
        frac = correct / total if total else 0.0
        solved = 1 if total > 0 and correct == total else 0
        results.append({
            "game": "Trivmount",
            "puzzle_id": f"#{pid}",
            "solved": solved,
            "rank_score": (-frac * 100) if solved else (10000 - frac * 100),
            "display_score": f"{correct}/{total}",
            "extra_url": None
        })

    # 14. THURSDAY THIRTY (I just completed Thursday Thirty Week 33!🧠 22/30 (73%))
    # teuteuf weekly quiz; ratio scored, replayable any day (scheduled on Thursdays in /missing).
    # The 🧠 marker may be absent, and whitespace/newlines are allowed between
    # the week number, the marker, and the score (real share format varies by client).
    for m in re.finditer(
        r"Thursday Thirty Week (\d+)(?:!|\.)?\s*🧠?\s*(\d+)/(\d+)(?:\s*\((\d+)%\))?",
        text, re.IGNORECASE
    ):
        week, correct, total = int(m.group(1)), int(m.group(2)), int(m.group(3))
        solved = 1 if correct > 0 else 0
        ratio = correct / total if total else 0.0
        results.append({
            "game": "Thursday Thirty",
            "puzzle_id": f"Week {week}",
            "solved": solved,
            "rank_score": (-ratio * 100) if solved else 10000.0,
            "display_score": f"{correct}/{total} ({int(ratio * 100)}%)",
            "extra_url": None
        })

    # 15. SONGSPOT (songspot · Daily Challenge · Nov 9, 2026)
    for m in re.finditer(
        r"songspot\s*[·•\-]\s*Daily Challenge\s*[·•\-]\s*([A-Za-z]+ \d{1,2}, \d{4})"
        r"\s*\n\s*(\d+)/(\d+)\s*[·•]\s*([\d,]+)\s*/\s*([\d,]+)\s*pts",
        text, re.IGNORECASE
    ):
        date_str, known, total = m.group(1), int(m.group(2)), int(m.group(3))
        pts_text, max_pts = m.group(4), m.group(5)
        pts = int(pts_text.replace(",", ""))
        max_pts_num = int(max_pts.replace(",", ""))
        solved = 1 if known > 0 else 0
        # Songs known drives placement; points are only the tiebreaker.
        rank_score = -(known / total) * 100 if solved else 10000.0
        if max_pts_num:
            rank_score -= (pts / max_pts_num) * 0.001
        results.append({
            "game": "Songspot",
            "puzzle_id": date_str,
            "solved": solved,
            "rank_score": rank_score,
            "display_score": f"{known}/{total} · {pts_text} pts",
            "extra_url": None
        })

    # 16. REGIONLE (Regionle #143 4/7, seven colored grid rows)
    for m in re.finditer(r"Regionle #(\d+)\s+([1-7X])/7", text, re.IGNORECASE):
        pid, score_ch = m.group(1), m.group(2).upper()
        solved = 0 if score_ch == "X" else 1
        tries = int(score_ch) if solved else 99
        results.append({
            "game": "Regionle",
            "puzzle_id": f"#{pid}",
            "solved": solved,
            "rank_score": float(tries),
            "display_score": f"{score_ch}/7",
            "extra_url": None
        })

    if config.DISABLED_GAMES:
        results = [r for r in results
                   if not any(r["game"].lower().startswith(d) for d in config.DISABLED_GAMES)]
    return results
