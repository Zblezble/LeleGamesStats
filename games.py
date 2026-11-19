"""Game registry: icons, descriptions, links — and what's currently enabled."""
import config

# Base names are matched by prefix, so modes like "Roughly (Where from)"
# and "Magnitudle (Size It Up)" resolve to their base game too.
GAME_META = {
    "Wordle": {"icon": "🟩", "desc": "daily 5-letter word, 6 tries", "url": "https://www.nytimes.com/games/wordle"},
    "Worldle": {"icon": "🗺️", "desc": "guess the country from its outline", "url": "https://worldle.teuteuf.fr"},
    "Flagle": {"icon": "🚩", "desc": "guess the country's flag in 6 tries", "url": "https://www.flagle.io/"},
    "Globle": {"icon": "🌎", "desc": "hot/cold country guessing", "url": "https://globle-game.com"},
    "Travle": {"icon": "✈️", "desc": "connect two countries across borders", "url": "https://travle.earth/"},
    "Metazooa": {"icon": "🐾", "desc": "guess the animal from its taxonomy", "url": "https://metazooa.com"},
    "Redactle": {"icon": "████", "desc": "unredact the hidden Wikipedia article", "url": "https://redactle.net"},
    "Songless": {"icon": "🎵", "desc": "guess songs from short clips, per genre", "url": "https://lessgames.com/songless"},
    "Centumth": {"icon": "💯", "desc": "100-question daily knowledge quiz", "url": "https://centumth.com"},
    "Roughly": {"icon": "📏", "desc": "daily estimation duels", "url": "https://roughly.is"},
    "Magnitudle": {"icon": "📐", "desc": "size-it-up estimation rounds", "url": "https://magnitudle.com"},
    "Majority": {"icon": "🗳️", "desc": "guess what the crowd picked", "url": "https://www.majoritygame.com/"},
    "Trivmount": {"icon": "🏔️", "desc": "12 trivia questions to the summit", "url": "https://trivmount.com/"},
    "Thursday Thirty": {"icon": "🧠", "desc": "30-question weekly quiz, Thursdays", "url": "https://t30.teuteuf.fr/",
                        "days": {3}},  # Thursday (Monday=0) — shows in /missing on this day only
    "Songspot": {"icon": "🎧", "desc": "guess 5 songs for daily points", "url": "https://songspot.co/daily"},
    "Regionle": {"icon": "🧭", "desc": "find the mystery region in 7 guesses", "url": "https://regionle.io/"},
    "Mathle": {"icon": "➗", "desc": "find the hidden equation in 6 tries", "url": "https://wordle.global/en/mathle"},
    "History in Order": {"icon": "🕰️", "desc": "put seven events in order with 3 chances", "url": "https://wordle.global/en/history-order"},
    "Tradle": {"icon": "🚢", "desc": "guess which country exports the goods", "url": "https://tradle.net/"},
    "Chessle": {"icon": "♞", "desc": "solve a chess position in six attempts", "url": "https://wordle.global/en/chessle"},
    "Maptap": {"icon": "📍", "desc": "daily geography puzzle", "url": "https://maptap.gg/"},
}


def game_available_on(name: str, weekday: int) -> bool:
    """Scheduled games only appear on their play days in /missing (def: always available)."""
    days = GAME_META.get(name, {}).get("days")
    return True if days is None else weekday in days


def is_game_enabled(game_name: str) -> bool:
    """Whether ingest currently accepts this game (same prefix rule as parsing)."""
    folded = (game_name or "").strip().casefold()
    return not any(folded.startswith(disabled) for disabled in config.DISABLED_GAMES)


def get_game_meta(game_name: str) -> dict:
    for key, meta in GAME_META.items():
        if game_name.startswith(key):
            return meta
    return {"icon": "🧩", "desc": "", "url": ""}


# Registry minus any games turned off via DISABLED_GAMES — drives /games and /missing.
ACTIVE_GAME_META = {k: v for k, v in GAME_META.items() if k.lower() not in config.DISABLED_GAMES}

# Games with a reliable parsed attempt count and a fixed attempt maximum. These
# power the personal fixed-attempt history chart. Songless is deliberately
# absent: its displayed fraction counts solved songs, not attempts used.
FIXED_ATTEMPT_GAMES = {
    "Wordle": {"max_attempts": 6},
    "Worldle": {"max_attempts": 6},
    "Flagle": {"max_attempts": 6},
    "Tradle": {"max_attempts": 6},
    "Mathle": {"max_attempts": 6},
    "Regionle": {"max_attempts": 7},
    "Chessle": {"max_attempts": 6},
    # Travle's native score is extra guesses, where +0 is a perfect run.
    "Travle": {"max_attempts": 14, "zero_is_best": True, "dnf_column": True},
}


def fixed_attempt_family(game_name: str) -> str | None:
    """Return the chart family for an exact game or its meaningful submode."""
    folded = (game_name or "").strip().casefold()
    for family in FIXED_ATTEMPT_GAMES:
        family_folded = family.casefold()
        if folded == family_folded or folded.startswith(family_folded + " ("):
            return family
    return None


# Score-based history charts. ``max_score`` is the nominal maximum where one
# exists; None means the native displayed denominator/score range can vary.
SCORE_CHART_GAMES = {
    "Trivmount": {"renderer": "fixed_score", "max_score": 12, "unit": "correct"},
    "History in Order": {"renderer": "fixed_score", "max_score": None, "unit": "correct"},
    "Majority": {"renderer": "fixed_score", "max_score": 5, "unit": "majorities"},
    "Songspot": {"renderer": "fixed_score", "max_score": 5, "unit": "songs"},
    "Centumth": {"renderer": "scaled_score", "max_score": 490, "unit": "pts"},
    "Magnitudle": {"renderer": "scaled_score", "max_score": 500, "unit": "pts"},
    "Maptap": {"renderer": "scaled_score", "max_score": None, "unit": "pts"},
}


def score_chart_family(game_name: str) -> str | None:
    """Return the score-chart family for an exact game or meaningful submode."""
    folded = (game_name or "").strip().casefold()
    for family in SCORE_CHART_GAMES:
        family_folded = family.casefold()
        if folded == family_folded or folded.startswith(family_folded + " ("):
            return family
    return None


# Open-ended guess-count charts. ``default_max`` is the minimum Y-axis height;
# the chart scales up to the largest valid guess count in the period.
GUESS_CHART_GAMES = {
    "Globle": {"renderer": "scaled_guess", "default_max": 10, "unit": "guesses"},
}


def guess_chart_family(game_name: str) -> str | None:
    """Return the guess-chart family for an exact game or meaningful submode."""
    folded = (game_name or "").strip().casefold()
    for family in GUESS_CHART_GAMES:
        family_folded = family.casefold()
        if folded == family_folded or folded.startswith(family_folded + " ("):
            return family
    return None


# Selection stays at the family level, while these chart families read their
# one actively played native variant.
CHART_PREFERRED_VARIANTS = {
    "Chessle": "Chessle (Medium)",
    "Magnitudle": "Magnitudle (Size It Up)",
}


def chart_preferred_variant(family: str) -> str | None:
    """Return the actively played variant used for a chart family, if any."""
    return CHART_PREFERRED_VARIANTS.get(family)


def get_game_icon(game_name: str) -> str:
    return get_game_meta(game_name)["icon"]


# Games where every posted score competes for daily podium points, ranked by
# closeness (no elimination). All other games stay elimination-style: only
# solved runs score points. Stats/'win' semantics are per-parser and unchanged.
# History in Order partials compete, but only a full match is solved (a win/crown).
GRADED_GAMES = {"Trivmount", "History in Order"}


def is_ranked_result(game: str, solved: int, rank_score) -> bool:
    """Whether a stored result competes for daily placement and podium points.

    Solved results compete through the ordinary elimination path. Unsolved
    results compete only in graded games. History in Order uses negative
    placements for genuine numeric partials, so only rank_score <= 0 is
    eligible; legacy DNF/forfeit sentinels and malformed scores stay out.
    Nonnumeric rank keys never compete.
    """
    if not isinstance(rank_score, (int, float)) or isinstance(rank_score, bool):
        return False
    if solved:
        return True
    if game == "History in Order":
        return rank_score <= 0
    return game in GRADED_GAMES and rank_score < 10000

# Playful public acknowledgements for exact integer results. Curated static links,
# no external image API requested. URLs were validated to serve actual GIFs.
# Curated set of comparable games for cross-game daily difficulty.
# Open-ended guessing games (Redactle, Metazooa, Globle, Travle, Roughly) are
# excluded because their native scores are not comparable to a 6-try puzzle:
# 40 guesses is a perfectly normal Redactle, not the hardest game ever.
DIFFICULTY_GAMES = {
    "Wordle", "Worldle", "Flagle", "Regionle", "Mathle", "Trivmount", "Tradle", "Chessle", "History in Order",
    "Thursday Thirty", "Songless", "Songspot", "Centumth", "Majority", "Magnitudle",
}

# First-guess games where hitting on attempt #1 triggers the optional prison mechanic.
# Only native parsed scores from genuine posts are considered; /forfeit cannot enter.
PRISON_GAMES = {"Globle", "Regionle", "Metazooa", "Redactle"}


def is_first_try(result: dict) -> bool:
    """Detect a first-attempt win in an eligible base game, including its modes."""
    base_game = (result.get("game") or "").split(" (", 1)[0]
    if not result.get("solved") or base_game not in PRISON_GAMES:
        return False
    rank = result.get("rank_score")
    if not isinstance(rank, (int, float)):
        return False
    if base_game == "Flagle":
        return rank <= 1.0
    if base_game == "Redactle":
        # Timer seconds are a fractional tiebreak, not extra guesses: 1g12s is FIRST TRY.
        return rank < 2.0
    return abs(rank - 1.0) < 1e-6

MEME_SCORES = {
    42: {"caption": "The answer to everything.", "url": "https://media1.tenor.com/m/T-weCEHq2BgAAAAC/life-the-universe-and-everything-hitchhikers-guide-to-the-galaxy.gif"},
    67: {"caption": "Six seven.", "url": "https://media1.tenor.com/m/gJR-HQLJ2isAAAAd/petr-pavel-67-petr-pavel.gif"},
    69: {"caption": "Nice.", "url": "https://media1.tenor.com/m/6vjzHxepwDkAAAAC/pout-kiss.gif"},
    420: {"caption": "Blaze it.", "url": "https://media.tenor.com/ev8UUqNOIm0AAAAi/snoop-dogg-dance.gif"},
}
