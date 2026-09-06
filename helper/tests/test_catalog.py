"""SPDX-License-Identifier: GPL-3.0-only

Endpoint-routing tests for Catalog: library ids (i./l./p.) must go to the
me/library/* endpoints, catalog ids to catalog/{sf}/*.
"""

import pytest

from applemusic_helper.apple_api import NotFound
from applemusic_helper.catalog import Catalog


def _song(sid, name="S"):
    return {
        "id": sid,
        "type": "library-songs" if sid[:2] in ("i.", "l.") else "songs",
        "attributes": {"name": name, "playParams": {"id": sid}},
    }


class _FakeApi:
    """Records every request; returns canned payloads keyed by endpoint prefix."""

    def __init__(self, storefront="gb"):
        self._config = type("C", (), {"storefront": storefront})()
        self.calls = []           # list of (endpoint, params)
        self.not_found = set()    # endpoints that should raise NotFound
        self.payloads = {}        # endpoint -> {"data": [...]}

    async def resolve_storefront(self):
        return "gb"

    async def get(self, endpoint, **params):
        self.calls.append((endpoint, params))
        if endpoint in self.not_found:
            raise NotFound(endpoint)
        return self.payloads.get(endpoint, {"data": []})

    async def get_all(self, endpoint, key="data", **params):
        self.calls.append((endpoint, params))
        if endpoint in self.not_found:
            raise NotFound(endpoint)
        return self.payloads.get(endpoint, {}).get(key, [])

    def endpoints(self):
        return [c[0] for c in self.calls]


@pytest.fixture
def cat():
    api = _FakeApi()
    return Catalog(api), api


async def test_get_track_routes_library_id(cat):
    c, api = cat
    api.payloads["me/library/songs/i.abc"] = {"data": [_song("i.abc")]}
    api.payloads["catalog/gb/songs/12345"] = {"data": [_song("12345")]}

    await c.get_track("i.abc")
    await c.get_track("12345")

    assert "me/library/songs/i.abc" in api.endpoints()
    assert "catalog/gb/songs/12345" in api.endpoints()


async def test_get_album_and_tracks_route_library_id(cat):
    c, api = cat
    api.payloads["me/library/albums/l.XYZ"] = {"data": [{"id": "l.XYZ", "type": "library-albums", "attributes": {"name": "A"}}]}
    api.payloads["me/library/albums/l.XYZ/tracks"] = {"data": [_song("i.1"), _song("i.2")]}

    await c.get_album("l.XYZ")
    tracks = await c.get_album_tracks("l.XYZ")

    assert "me/library/albums/l.XYZ" in api.endpoints()
    assert "me/library/albums/l.XYZ/tracks" in api.endpoints()
    assert {t["id"] for t in tracks} == {"i.1", "i.2"}


async def test_get_album_tracks_catalog_id(cat):
    c, api = cat
    api.payloads["catalog/gb/albums/999/tracks"] = {"data": [_song("999001")]}
    await c.get_album_tracks("999")
    assert "catalog/gb/albums/999/tracks" in api.endpoints()


async def test_library_album_tracks_missing_returns_empty(cat):
    c, api = cat
    api.not_found.add("me/library/albums/l.GONE/tracks")
    assert await c.get_album_tracks("l.GONE") == []


async def test_catalog_album_tracks_missing_raises(cat):
    c, api = cat
    api.not_found.add("catalog/gb/albums/404/tracks")
    with pytest.raises(NotFound):
        await c.get_album_tracks("404")


async def test_playlist_tracks_routing(cat):
    c, api = cat
    api.payloads["catalog/gb/playlists/pl.cat/tracks"] = {"data": [_song("1")]}
    api.payloads["me/library/playlists/p.lib/tracks"] = {"data": [_song("i.1")]}

    await c.get_playlist_tracks("pl.cat")
    await c.get_playlist_tracks("p.lib")

    eps = api.endpoints()
    assert "catalog/gb/playlists/pl.cat/tracks" in eps
    assert "me/library/playlists/p.lib/tracks" in eps


async def test_library_playlist_tracks_missing_returns_empty(cat):
    c, api = cat
    api.not_found.add("me/library/playlists/p.gone/tracks")
    assert await c.get_playlist_tracks("p.gone") == []


async def test_get_tracks_splits_catalog_and_library_ids(cat):
    c, api = cat
    api.payloads["catalog/gb/songs"] = {"data": [_song("111"), _song("222")]}
    api.payloads["me/library/songs"] = {"data": [_song("i.aaa")]}

    out = await c.get_tracks(["111", "i.aaa", "222"])

    eps = api.endpoints()
    assert "catalog/gb/songs" in eps
    assert "me/library/songs" in eps
    assert {t["id"] for t in out} == {"111", "222", "i.aaa"}


async def test_get_tracks_library_only(cat):
    c, api = cat
    api.payloads["me/library/songs"] = {"data": [_song("i.aaa"), _song("i.bbb")]}
    out = await c.get_tracks(["i.aaa", "i.bbb"])
    assert [e for e in api.endpoints()] == ["me/library/songs"]
    assert {t["id"] for t in out} == {"i.aaa", "i.bbb"}


async def test_artist_views_swallow_not_found(cat):
    c, api = cat
    api.not_found.add("catalog/gb/artists/x/albums")
    api.not_found.add("catalog/gb/artists/x/view/top-songs")
    assert await c.get_artist_albums("x") == []
    assert await c.get_artist_top_tracks("x") == []
