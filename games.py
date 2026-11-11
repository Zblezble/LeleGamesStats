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
}


def game_available_on(name: str, weekday: int) -> bool:
    """Scheduled games only appear on their play days in /missing (def: always available)."""
    days = GAME_META.get(name, {}).get("days")
    return True if days is None else weekday in days


def get_game_meta(game_name: str) -> dict:
    for key, meta in GAME_META.items():
        if game_name.startswith(key):
            return meta
    return {"icon": "🧩", "desc": "", "url": ""}


# Registry minus any games turned off via DISABLED_GAMES — drives /games and /missing.
ACTIVE_GAME_META = {k: v for k, v in GAME_META.items() if k.lower() not in config.DISABLED_GAMES}


def get_game_icon(game_name: str) -> str:
    return get_game_meta(game_name)["icon"]


# Games where every posted score competes for daily podium points, ranked by
# closeness (no elimination). All other games stay elimination-style: only
# solved runs score points. Stats/'win' semantics are per-parser and unchanged.
GRADED_GAMES = {"Trivmount"}

# Playful public acknowledgements for exact integer results. Curated static links,
# no external image API requested. URLs were validated to serve actual GIFs.
# Curated set of comparable games for cross-game daily difficulty.
# Open-ended guessing games (Redactle, Metazooa, Globle, Travle, Roughly) are
# excluded because their native scores are not comparable to a 6-try puzzle:
# 40 guesses is a perfectly normal Redactle, not the hardest game ever.
DIFFICULTY_GAMES = {
    "Wordle", "Worldle", "Flagle", "Regionle", "Mathle", "Trivmount", "Tradle", "History in Order",
    "Thursday Thirty", "Songless", "Songspot", "Centumth", "Majority", "Magnitudle",
}

# First-guess games where hitting on attempt #1 triggers the optional prison mechanic.
# Only native parsed scores from genuine posts are considered; /forfeit cannot enter.
PRISON_GAMES = {"Globle", "Regionle", "Metazooa", "Redactle"}


def is_first_try(result: dict) -> bool:
    """Detect a first-attempt win in an eligible game, tolerating Flagle bonuses."""
    if not result.get("solved") or result.get("game") not in PRISON_GAMES:
        return False
    rank = result.get("rank_score")
    if not isinstance(rank, (int, float)):
        return False
    if result["game"] == "Flagle":
        return rank <= 1.0  # First try = 1.0; bonus tiles may subtract more
    return abs(rank - 1.0) < 1e-6

MEME_SCORES = {
    42: {"caption": "The answer to everything.", "url": "https://media1.tenor.com/m/T-weCEHq2BgAAAAC/life-the-universe-and-everything-hitchhikers-guide-to-the-galaxy.gif"},
    67: {"caption": "Six seven.", "url": "https://media1.tenor.com/m/gJR-HQLJ2isAAAAd/petr-pavel-67-petr-pavel.gif"},
    69: {"caption": "Nice.", "url": "https://media1.tenor.com/m/6vjzHxepwDkAAAAC/pout-kiss.gif"},
    420: {"caption": "Blaze it.", "url": "https://media.tenor.com/ev8UUqNOIm0AAAAi/snoop-dogg-dance.gif"},
}
