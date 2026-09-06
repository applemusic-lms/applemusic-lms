"""SPDX-License-Identifier: GPL-3.0-only

Route-level tests with Apple + Widevine + ffmpeg stubbed out.
"""

import asyncio
import os

import pytest
from aiohttp.test_utils import TestClient, TestServer

from applemusic_helper import server as server_mod
from applemusic_helper.config import Config
from applemusic_helper.server import build_app
from applemusic_helper.stream import ResolvedStream


@pytest.fixture
async def client(tmp_path, monkeypatch):
    cfg = Config.load(tmp_path / "config.json")
    cfg.media_user_token = "fake-user-token"
    cfg.developer_token = "fake.dev.token"

    app = build_app(cfg)

    async def fake_startup(app):
        app["session"] = None
        app["api"] = _FakeApi(cfg)
        app["catalog"] = _FakeCatalog(cfg)
        app["widevine"] = _FakeWidevine()
        app["stream"] = _FakeResolver(cfg)

    app.on_startup.clear()
    app.on_cleanup.clear()
    app.on_startup.append(fake_startup)

    async with TestClient(TestServer(app)) as c:
        yield c


class _FakeApi:
    def __init__(self, cfg):
        self._config = cfg

    async def developer_token(self, **_):
        return "fake.dev.token"


class _FakeCatalog:
    _storefront = "us"

    def __init__(self, config=None):
        self._config = config

    async def storefront(self):
        return (self._config.storefront if self._config else None) or "us"

    async def search(self, term, types, limit=25):
        return {"songs": [{"type": "track", "id": "1", "uri": "applemusic://track/1",
                           "title": term, "artist": "A", "album": "B", "duration": 10,
                           "cover": None, "available": True}]}

    async def get_track(self, tid):
        return {"type": "track", "id": tid, "title": "T", "duration": 200, "available": True}

    async def library(self, kind):
        return [{"type": "playlist", "id": "p.1", "name": "Mine"}]


class _FakeWidevine:
    available = True
    status = "ok"


class _FakeResolver:
    def __init__(self, cfg):
        self._config = cfg

    content_type = "audio/flac"

    async def resolve(self, item_id):
        return ResolvedStream(item_id, "http://x/a.mp4", "deadbeef", 200)

    async def fetch_mp4(self, stream, dest):
        with open(dest, "wb") as fh:
            fh.write(b"\x00" * 2048)
        return 2048

    async def open_ffmpeg(self, mp4_path, key_hex, seek=0.0):
        assert os.path.exists(mp4_path)
        proc = await asyncio.create_subprocess_exec(
            "printf", "FLACDATA",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        return proc


async def test_health(client):
    r = await client.get("/health")
    assert r.status == 200
    body = await r.json()
    assert body["cdm_ok"] is True
    assert body["user_token_ok"] is True


async def test_auth_gate(client):
    client.app["config"].media_user_token = ""
    r = await client.get("/search?q=x")
    assert r.status == 401


async def test_search(client):
    r = await client.get("/search?q=hello")
    assert r.status == 200
    assert (await r.json())["songs"][0]["title"] == "hello"


async def test_library(client):
    r = await client.get("/library/playlists")
    assert (await r.json())["items"][0]["name"] == "Mine"
    r = await client.get("/library/bogus")
    assert r.status == 404


async def test_stream_pipes_ffmpeg_output(client):
    r = await client.get("/stream/12345")
    assert r.status == 200
    assert r.headers["Content-Type"] == "audio/flac"
    assert await r.read() == b"FLACDATA"


async def test_auth_page_served(client):
    r = await client.get("/auth")
    assert r.status == 200
    text = await r.text()
    assert "media-user-token" in text


async def test_token_capture(client):
    r = await client.post("/auth/token", json={"media_user_token": "A" * 40, "storefront": "gb"})
    assert r.status == 200
    body = await r.json()
    assert body["storefront"] == "gb"
    assert client.app["config"].media_user_token == "A" * 40


async def test_token_rejected_rolls_back(client):
    from applemusic_helper.apple_api import NotAuthenticated

    client.app["config"].media_user_token = "GOOD" * 10
    client.app["config"].storefront = "gb"

    async def boom():
        raise NotAuthenticated("Apple says no")

    client.app["catalog"].storefront = boom

    r = await client.post("/auth/token", json={"media_user_token": "B" * 40})
    assert r.status == 200                       # 2xx so the plugin can read the body
    body = await r.json()
    assert body["status"] == "error"
    assert client.app["config"].media_user_token == "GOOD" * 10   # rolled back


async def test_token_kept_when_apple_unreachable(client):
    client.app["config"].media_user_token = ""
    client.app["config"].storefront = ""

    async def offline():
        raise OSError("Temporary failure in name resolution")

    client.app["catalog"].storefront = offline

    r = await client.post("/auth/token", json={"media_user_token": "C" * 40})
    assert r.status == 200
    body = await r.json()
    assert body["status"] == "ok"
    assert body.get("warning")
    assert client.app["config"].media_user_token == "C" * 40      # kept, not rolled back


async def test_logout_clears_token(client):
    assert client.app["config"].media_user_token
    r = await client.post("/auth/logout")
    assert r.status == 200
    assert client.app["config"].media_user_token == ""
    assert client.app["config"].storefront == ""
