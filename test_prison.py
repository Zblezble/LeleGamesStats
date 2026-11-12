# -*- coding: utf-8 -*-
"""Prison mode regression: keeps placements, zeroes daily points, idempotence and off switch."""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

import config
import db
import embeds
import games
import handlers
import main


class MessageStub:
    def __init__(self, mid):
        self.id = mid
    async def pin(self): pass
    async def unpin(self): pass
    async def edit(self, **kwargs): pass


class Channel:
    def __init__(self):
        self.id, self.sent = 42, []
    async def send(self, content=None, embed=None):
        self.sent.append(embed or content)
        return MessageStub(len(self.sent))
    async def fetch_message(self, mid):
        return MessageStub(mid)


class Author:
    def __init__(self, uid, name):
        self.id, self.display_name, self.bot = uid, name, False


class Message:
    def __init__(self, uid, name, text, channel):
        self.author = Author(uid, name)
        self.content, self.channel = text, channel
        self.guild = object()
    async def delete(self): pass


def ingest(channel, uid, name, text):
    event = main.bot.extra_events["on_message"][0]
    asyncio.run(event(Message(uid, name, text, channel)))


def fresh_db():
    with tempfile.NamedTemporaryFile(prefix="prison_test_", suffix=".db", delete=False) as f:
        config.DB_PATH = f.name
    db.init_db()


def test_prison_confiscates_only_prisoners_points():
    fresh_db()
    config.PRISON_ENABLED = True
    ch = Channel()
    ingest(ch, 1, "Lucky", "Animal #1190\nI figured it out in 1 guesses!")
    assert db.jailed_users(config.today_str()) == {1: "Lucky"}
    ingest(ch, 2, "RivalA", "Wordle 1958 4/6")
    ingest(ch, 3, "RivalB", "Wordle 1958 3/6")

    points, _ = embeds.compute_daily_points(config.today_str())
    assert points[1] == 0.0, "prison loses that date's points"
    assert points[2] == 2 and points[3] == 3, "non-prisoners keep their podium points unchanged"
    assert embeds.placement_of(config.today_str(), "Metazooa", "#1190", 1) == "1/1", "score records are not erased"
    assert any("prison" in m or "jail" in m for m in ch.sent if isinstance(m, str))


def test_prison_dedupes_daily_sentence():
    fresh_db()
    config.PRISON_ENABLED = True
    ch = Channel()
    original_comment = handlers._prison_comment
    calls = []
    def counted_comment(*args, **kwargs):
        result = original_comment(*args, **kwargs)
        calls.append((args, result))
        return result
    handlers._prison_comment = counted_comment
    text = "Animal #1190\nI figured it out in 1 guesses!"
    try:
        ingest(ch, 1, "Lucky", text)
        ingest(ch, 1, "Lucky", text)
    finally:
        handlers._prison_comment = original_comment
    print('prison comment calls:', calls)
    assert len(calls) == 1, "only one courthouse announcement per player per day"
    assert db.is_jailed(config.today_str(), 1)


def test_prison_no_actual_first_try():
    fresh_db()
    config.PRISON_ENABLED = True
    ch = Channel()
    ingest(ch, 1, "Safe", "Animal #1190\nI figured it out in 2 guesses!")
    assert db.jailed_users(config.today_str()) == {}


def test_prison_disabled_is_noop():
    fresh_db()
    config.PRISON_ENABLED = False
    ch = Channel()
    ingest(ch, 1, "Lucky", "Animal #1190\nI figured it out in 1 guesses!")
    assert db.jailed_users(config.today_str()) == {}
    assert not any("jail" in m for m in ch.sent if isinstance(m, str))


def test_prison_first_try_rules():
    "First-try eligible games trigger; out-of-scope games cannot trigger."
    for game in ("Globle", "Regionle", "Metazooa", "Redactle"):
        assert games.is_first_try({"game": game, "solved": 1, "rank_score": 1.0}), game
    for game in ("Wordle", "Trivmount"):
        assert not games.is_first_try({"game": game, "solved": 1, "rank_score": 1.0}), game
    # Redactle's extra timer digits do not change solvability of a first attempt.
    assert not games.is_first_try({"game": "Flagle", "solved": 1, "rank_score": 1.0})  # removed from prison
    assert games.is_first_try({"game": "Redactle", "solved": 1, "rank_score": 1.000138})


if __name__ == "__main__":
    test_prison_confiscates_only_prisoners_points()
    test_prison_dedupes_daily_sentence()
    test_prison_no_actual_first_try()
    test_prison_disabled_is_noop()
    test_prison_first_try_rules()
    print("All prison tests passed.")
