import os
import re
import sqlite3
from datetime import datetime, timezone
import discord
from discord import app_commands
from discord.ext import commands

# ================= CONFIGURATION =================
# Set these as environment variables before running:
#   DISCORD_BOT_TOKEN - your Discord bot token (required)
#   SCORE_CHANNEL_ID  - the channel to watch (optional; if unset, watches all channels)
#   BOT_TZ            - timezone for daily board cutoff, e.g. "Europe/Warsaw"
#                     (optional; defaults to the server's local time)
BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
SCORE_CHANNEL_ID = int(os.getenv("SCORE_CHANNEL_ID", "0")) or None
DB_PATH = "scores.db"

try:
    from zoneinfo import ZoneInfo
    BOT_TZ = ZoneInfo(os.environ["BOT_TZ"]) if os.getenv("BOT_TZ") else None
except Exception:
    BOT_TZ = None  # unknown/missing tz database: fall back to server-local time


def today_str() -> str:
    now = datetime.now(BOT_TZ) if BOT_TZ else datetime.now()
    return now.strftime("%Y-%m-%d")

# Emoji icons & Display ordering for games
GAME_META = {
    "Metazooa": {"icon": "🐾", "unit": "guesses"},
    "Flagle": {"icon": "🚩", "unit": "tries"},
    "Worldle": {"icon": "🗺️", "unit": "tries"},
    "Globle": {"icon": "🌎", "unit": "guesses"},
    "Travle": {"icon": "✈️", "unit": "extra"},
    "Centumth": {"icon": "💯", "unit": "pts"},
    "Redactle": {"icon": "████", "unit": "guesses"},
    "Songless": {"icon": "🎵", "unit": "solved"},
    "Wordle": {"icon": "🟩", "unit": "tries"},
}

def get_game_icon(game_name: str) -> str:
    if game_name.startswith("Roughly"):
        return "📏"
    if game_name.startswith("Magnitudle"):
        return "📐"
    return GAME_META.get(game_name, {}).get("icon", "🧩")


# ================= DATABASE SETUP =================
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_date TEXT,
                user_id INTEGER,
                user_name TEXT,
                game TEXT,
                puzzle_id TEXT,
                solved INTEGER,
                rank_score REAL,
                display_score TEXT,
                extra_url TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(board_date, user_id, game, puzzle_id)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS daily_boards (
                board_date TEXT PRIMARY KEY,
                channel_id INTEGER,
                message_id INTEGER
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS channel_settings (
                channel_id INTEGER PRIMARY KEY,
                layout TEXT NOT NULL DEFAULT 'grid'
            )
        """)
        conn.commit()


# ================= REGEX PARSERS =================
# Each parser returns a list of dicts:
# {game, puzzle_id, solved (1/0), rank_score (LOWER IS ALWAYS BETTER), display_score, extra_url}

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
    for m in re.finditer(
        r"#travle #(\d+)\s*([+\-]?\d+|X)(?:\s*\(([^)]+)\))?",
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
        rank_score = float(extra_guesses) + (hints * 0.1)
        note_disp = f" ({note})" if note else ""
        results.append({
            "game": "Travle",
            "puzzle_id": f"#{pid}",
            "solved": solved,
            "rank_score": rank_score,
            "display_score": f"{score_str}{note_disp}",
            "extra_url": None
        })

    # 7. GLOBLE (🌎 Nov 1, 2026 🌍 ... 🟥🟥🟩 = 3)
    for m in re.finditer(
        r"[🌎🌍🌏]\s*([A-Za-z]+ \d+, \d{4})\s*[🌎🌍🌏].*?\n(?:[^\n]*\n)?[🟧🟥🟨🟩⬜⬛]+\s*=\s*(\d+)",
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

    return results


# ================= DISCORD BOT CLASS =================
class DailyScoreBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        init_db()
        await self.tree.sync()
        print("Database initialized & Slash commands synced.")


bot = DailyScoreBot()


def build_daily_embed(board_date: str, layout: str = "grid") -> discord.Embed:
    """Constructs the single consolidated Daily Leaderboard Embed for a given date."""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT game, puzzle_id, user_id, user_name, solved, rank_score, display_score, extra_url
            FROM scores
            WHERE board_date = ?
            ORDER BY game ASC, rank_score ASC, timestamp ASC
        """, (board_date,))
        rows = c.fetchall()

    try:
        dt = datetime.strptime(board_date, "%Y-%m-%d")
        date_label = f"{dt.strftime('%a')} {dt.day} {dt.strftime('%b')}"
    except ValueError:
        date_label = board_date

    embed = discord.Embed(
        title=f"🌅 Daily digest — {date_label}",
        description="Drop your raw game results in this channel — they get logged here and tidied away.",
        color=0xF59E0B,
        timestamp=datetime.now(timezone.utc)
    )

    if not rows:
        embed.add_field(name="No scores yet", value="Post a result to start the board.", inline=False)
        return embed

    # Group by (game, puzzle_id)
    grouped = {}
    for game, pid, uid, uname, solved, rscore, dscore, url in rows:
        key = (game, pid)
        grouped.setdefault(key, []).append((uid, uname, solved, rscore, dscore, url))

    # Calculate Overall Daily MVP Points (1st = 3pts, 2nd = 2pts, 3rd = 1pt in games with >=2 players)
    mvp_points = {}
    names = {}  # uid -> display_name (points keyed by uid so same-named players don't merge)

    for (game, pid), entries in grouped.items():
        icon = get_game_icon(game)
        lines = []
        # Calculate dense ranks so ties share the same medal
        unique_scores = sorted(list({e[3] for e in entries if e[2] == 1}))

        for uid, uname, solved, rscore, dscore, url in entries:
            if solved:
                names[uid] = uname
                rank_idx = unique_scores.index(rscore)
                if len(entries) >= 2 and rank_idx < 3:
                    pts = 3 - rank_idx
                    mvp_points[uid] = mvp_points.get(uid, 0) + pts

            duel_str = f" · [rematch]({url})" if url else ""
            lines.append(f"**{uname}** `{dscore}`{duel_str}")

        field_title = f"{icon} {game} {pid}"
        # Clamp to Discord's 1024-char field limit so a huge game can't kill the whole board
        clamp = lambda v: v if len(v) <= 1024 else v[:1021] + "…"
        if layout == "rows":
            embed.add_field(name=field_title, value=clamp(" · ".join(lines)), inline=False)
        else:
            embed.add_field(name=field_title, value=clamp("\n".join(lines)), inline=True)

    # Add Daily Standings Footer/Summary if competitive games exist
    if mvp_points:
        standings = sorted(mvp_points.items(), key=lambda x: x[1], reverse=True)
        standings_str = " · ".join([f"**{names[u]}** {p}" for u, p in standings])
        embed.add_field(name="Today's points (🥇 = 3 pts · 🥈 = 2 pts · 🥉 = 1 pt)", value=standings_str, inline=False)

    return embed


async def update_or_post_daily_board(channel: discord.TextChannel, board_date: str):
    """Edits today's existing summary Embed, or posts a new one if none exists yet."""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT layout FROM channel_settings WHERE channel_id = ?", (channel.id,))
        layout_row = c.fetchone()
        layout = layout_row[0] if layout_row else "grid"

    embed = build_daily_embed(board_date, layout)

    with sqlite3.connect(DB_PATH) as conn:
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


# ================= EVENT LISTENERS =================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")


@bot.event
async def on_message(message: discord.Message):
    # Ignore our own messages, other bots (like the official Wordle Activity app), DMs, or other channels
    if message.author.bot:
        return
    if message.guild is None:
        return
    if SCORE_CHANNEL_ID and message.channel.id != SCORE_CHANNEL_ID:
        return

    parsed_games = parse_all_games(message.content)
    if not parsed_games:
        # Regular chat/banter message — leave it alone!
        await bot.process_commands(message)
        return

    board_date = today_str()
    user_id = message.author.id
    user_name = message.author.display_name

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        for g in parsed_games:
            c.execute("""
                INSERT INTO scores (board_date, user_id, user_name, game, puzzle_id, solved, rank_score, display_score, extra_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(board_date, user_id, game, puzzle_id) DO UPDATE SET
                    solved=excluded.solved,
                    rank_score=excluded.rank_score,
                    display_score=excluded.display_score,
                    extra_url=COALESCE(excluded.extra_url, scores.extra_url)
            """, (
                board_date, user_id, user_name,
                g["game"], g["puzzle_id"], g["solved"],
                g["rank_score"], g["display_score"], g["extra_url"]
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


# ================= COMPARISON SLASH COMMANDS =================
@bot.tree.command(name="h2h", description="Head-to-Head comparison between two players across all daily games")
async def h2h(interaction: discord.Interaction, opponent: discord.Member, player1: discord.Member = None):
    p1 = player1 or interaction.user
    p2 = opponent

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT a.game, a.rank_score, b.rank_score
            FROM scores a
            JOIN scores b ON a.game = b.game AND a.puzzle_id = b.puzzle_id AND a.board_date = b.board_date
            WHERE a.user_id = ? AND b.user_id = ?
        """, (p1.id, p2.id))
        matchups = c.fetchall()

    if not matchups:
        await interaction.response.send_message(
            f"No shared puzzles found between **{p1.display_name}** and **{p2.display_name}** yet.",
            ephemeral=True
        )
        return

    stats = {}
    tot_w1 = tot_w2 = tot_ties = 0
    for game, s1, s2 in matchups:
        rec = stats.setdefault(game, [0, 0, 0])  # [p1_wins, p2_wins, ties]
        if abs(s1 - s2) < 1e-9:
            rec[2] += 1
            tot_ties += 1
        elif s1 < s2:
            rec[0] += 1
            tot_w1 += 1
        else:
            rec[1] += 1
            tot_w2 += 1

    embed = discord.Embed(
        title=f"Head-to-head: {p1.display_name} vs {p2.display_name}",
        description=f"**{tot_w1}–{tot_w2}** overall · {tot_ties} tied",
        color=0x64748B
    )
    lines = []
    for game, (w1, w2, t) in sorted(stats.items()):
        icon = get_game_icon(game)
        lines.append(f"{icon} **{game}** · {w1}–{w2} · {t} tied")

    embed.add_field(name="By game", value="\n".join(lines), inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="stats", description="View all-time crowns, podiums, and win rates")
async def stats(interaction: discord.Interaction, player: discord.Member = None):
    target = player or interaction.user

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        # Fetch all puzzles to compute crowns
        c.execute("SELECT board_date, game, puzzle_id, user_id, solved, rank_score, display_score FROM scores")
        all_rows = c.fetchall()

    puzzles = {}
    for bdate, game, pid, uid, solved, rscore, dscore in all_rows:
        puzzles.setdefault((bdate, game, pid), []).append((uid, solved, rscore, dscore))

    game_totals = {}  # game -> [played, solved, crowns]
    for (bdate, game, pid), entries in puzzles.items():
        best_score = min((e[2] for e in entries if e[1] == 1), default=None)
        for uid, solved, rscore, dscore in entries:
            if uid == target.id:
                rec = game_totals.setdefault(game, [0, 0, 0])
                rec[0] += 1
                if solved:
                    rec[1] += 1
                # Award crown if solved, tied for best score, and at least 2 people played
                if solved and best_score is not None and abs(rscore - best_score) < 1e-9 and len(entries) >= 2:
                    rec[2] += 1

    if not game_totals:
        await interaction.response.send_message(f"No games logged for **{target.display_name}** yet.", ephemeral=True)
        return

    total_played = sum(v[0] for v in game_totals.values())
    total_crowns = sum(v[2] for v in game_totals.values())

    embed = discord.Embed(
        title=f"All-time stats: {target.display_name}",
        description=f"**{total_played}** games logged · **{total_crowns}** 🥇 golds",
        color=0x64748B
    )
    lines = []
    for game, (played, solved, crowns) in sorted(game_totals.items()):
        icon = get_game_icon(game)
        win_rate = int((solved / played) * 100) if played else 0
        lines.append(f"{icon} **{game}** · {played} played · {win_rate}% solved · {crowns} 🥇")

    embed.add_field(name="By game", value="\n".join(lines), inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="repost_board", description="Moves today's scoreboard to the bottom of the channel if chat buried it")
async def repost_board(interaction: discord.Interaction):
    board_date = today_str()
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT message_id FROM daily_boards WHERE board_date = ?", (board_date,))
        row = c.fetchone()
        if row:
            try:
                old_msg = await interaction.channel.fetch_message(row[0])
                await old_msg.delete()
            except Exception:
                pass
        c.execute("DELETE FROM daily_boards WHERE board_date = ?", (board_date,))
        conn.commit()

    await update_or_post_daily_board(interaction.channel, board_date)
    await interaction.response.send_message("Board reposted at the bottom of the channel.", ephemeral=True)


@bot.tree.command(name="layout_switch", description="Toggle today's board between compact (3 per row) and wide (one line per game)")
async def layout_switch(interaction: discord.Interaction):
    channel_id = interaction.channel.id
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT layout FROM channel_settings WHERE channel_id = ?", (channel_id,))
        row = c.fetchone()
        current = row[0] if row else "grid"
        new_layout = "rows" if current == "grid" else "grid"
        c.execute(
            "INSERT OR REPLACE INTO channel_settings (channel_id, layout) VALUES (?, ?)",
            (channel_id, new_layout)
        )
        conn.commit()

    board_date = today_str()
    await update_or_post_daily_board(interaction.channel, board_date)

    if new_layout == "rows":
        await interaction.response.send_message("Board layout: wide — one line per game.", ephemeral=True)
    else:
        await interaction.response.send_message("Board layout: compact — three games per row.", ephemeral=True)


if __name__ == "__main__":
    bot.run(BOT_TOKEN)