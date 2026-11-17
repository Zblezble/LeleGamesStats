# -*- coding: utf-8 -*-
"""Curated gif delivery: validated attachment, direct-link fallback, reusable cache."""
import asyncio
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

import games
import handlers
import parsers

GIF_PAYLOAD = b"GIF89a" + bytes(range(64))


class Response:
    def __init__(self, payload, content_type="image/gif", status=200):
        self.payload = payload
        self.status = status
        self.headers = {"Content-Type": content_type}
        self.read_size = None

    def read(self, size=-1):
        self.read_size = size
        return self.payload[:size] if size >= 0 else self.payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Channel:
    """Records sends and materialises any attachment while its stream is fresh."""
    def __init__(self):
        self.sent = []

    async def send(self, content=None, file=None):
        payload = file.fp.read() if file is not None else None
        self.sent.append({
            "content": content,
            "file": file,
            "filename": file.filename if file is not None else None,
            "payload": payload,
        })
        return object()


def _install_response(response):
    handlers.urlopen = lambda request, timeout: response


def test_download_validates_content_and_bounds_read():
    response = Response(GIF_PAYLOAD)
    original = handlers.urlopen
    _install_response(response)
    try:
        payload = handlers._download_gif("https://example.test/curated.gif")
    finally:
        handlers.urlopen = original
    assert payload == GIF_PAYLOAD
    assert response.read_size == handlers._GIF_MAX_BYTES + 1, "read must be bounded"


def test_post_sends_gif_attachment_with_original_caption():
    handlers._MEME_GIF_CACHE.clear()
    original = handlers.urlopen
    _install_response(Response(GIF_PAYLOAD))
    channel = Channel()
    try:
        asyncio.run(handlers._post_meme(channel, 69, "Pan Proktor", games.MEME_SCORES[69]))
    finally:
        handlers.urlopen = original
    assert len(channel.sent) == 1
    sent = channel.sent[0]
    assert sent["content"] == "Pan Proktor · 69 · Nice."
    assert sent["file"] is not None
    assert sent["filename"].endswith(".gif")
    assert sent["payload"] == GIF_PAYLOAD


def test_fallback_to_direct_link_on_download_or_validation_failure():
    expected = "Pan Proktor · 69 · Nice.\n" + games.MEME_SCORES[69]["url"]
    original = handlers.urlopen

    def network_failure(request, timeout):
        raise OSError("network down")

    scenarios = (
        ("network", network_failure),
        ("mime", lambda request, timeout: Response(GIF_PAYLOAD, content_type="text/html")),
        ("magic", lambda request, timeout: Response(b"<html>not a gif</html>")),
    )
    try:
        for name, urlopen_impl in scenarios:
            handlers._MEME_GIF_CACHE.clear()
            handlers.urlopen = urlopen_impl
            channel = Channel()
            with contextlib.redirect_stdout(io.StringIO()):
                asyncio.run(handlers._post_meme(channel, 69, "Pan Proktor", games.MEME_SCORES[69]))
            assert len(channel.sent) == 1, name
            assert channel.sent[0]["file"] is None, name
            assert channel.sent[0]["content"] == expected, name
            assert handlers._MEME_GIF_CACHE == {}, f"{name} failure must not be cached"
    finally:
        handlers.urlopen = original


def test_cached_bytes_use_a_fresh_stream_on_each_send():
    handlers._MEME_GIF_CACHE.clear()
    handlers._MEME_GIF_CACHE[games.MEME_SCORES[69]["url"]] = GIF_PAYLOAD
    original = handlers._download_gif

    def unexpected_download(url):
        raise AssertionError(f"cache should avoid a download: {url}")

    handlers._download_gif = unexpected_download
    channel = Channel()
    try:
        asyncio.run(handlers._post_meme(channel, 69, "Pan Proktor", games.MEME_SCORES[69]))
        asyncio.run(handlers._post_meme(channel, 69, "Pan Proktor", games.MEME_SCORES[69]))
    finally:
        handlers._download_gif = original
        handlers._MEME_GIF_CACHE.clear()
    assert [s["payload"] for s in channel.sent] == [GIF_PAYLOAD, GIF_PAYLOAD]
    assert [s["filename"] for s in channel.sent] == ["meme-69.gif", "meme-69.gif"]


def test_roughly_finer_rank_still_triggers_integral_base_score():
    # Grid mean = 69%, native best = 37%: rank_score becomes -69.0037, but the
    # coarse base key stays integral so the curated 69 gif still triggers.
    share = (
        "roughly · Where? #322\n"
        "Where would you find a quokka?\n"
        "Me: better than 37% of players\n"
        "▣▣□■■\n"
        "https://roughly.is/d/grid69"
    )
    result = parsers.parse_all_games(share)[0]
    assert result["base_rank_score"] == -69.0
    assert not result["rank_score"].is_integer()
    assert handlers._meme_numbers([result]) == [69]
    # Without the base key the finer rank alone would miss the curated score.
    assert handlers._meme_numbers([{"rank_score": result["rank_score"]}]) == []
    # Non-Roughly integral scores keep their existing trigger behavior.
    assert handlers._meme_numbers([{"rank_score": -69.0}]) == [69]


if __name__ == "__main__":
    test_download_validates_content_and_bounds_read()
    test_post_sends_gif_attachment_with_original_caption()
    test_fallback_to_direct_link_on_download_or_validation_failure()
    test_cached_bytes_use_a_fresh_stream_on_each_send()
    test_roughly_finer_rank_still_triggers_integral_base_score()
    print("All meme gif tests passed.")
