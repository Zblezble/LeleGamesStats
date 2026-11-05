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
