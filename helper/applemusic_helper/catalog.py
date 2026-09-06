"""Catalog + library operations for Apple Music.

SPDX-License-Identifier: GPL-3.0-only

Adapted from Music Assistant's apple_music/media.py and library.py (Apache-2.0).
Everything returns the flat dicts from parsers.py.
"""

from __future__ import annotations

import logging
from typing import Any

from . import parsers
from .apple_api import AppleMusicApi, NotFound

_LOGGER = logging.getLogger(__name__)

_SEARCH_TYPES = {
    "artists": "artists",
    "albums": "albums",
    "songs": "songs",
    "playlists": "playlists",
}


class Catalog:
    def __init__(self, api: AppleMusicApi) -> None:
        self._api = api
        self._storefront: str | None = None

    async def storefront(self) -> str:
        if not self._storefront:
            self._storefront = self._api._config.storefront or await self._api.resolve_storefront()
            if self._storefront != self._api._config.storefront:
                self._api._config.update(storefront=self._storefront)
        return self._storefront

    def _cat(self, path: str) -> str:
        return f"catalog/{self._storefront}/{path}"

    # ------------------------------------------------------------------ search
    async def search(self, term: str, types: list[str], limit: int = 25) -> dict[str, list]:
        sf = await self.storefront()
        wanted = [_SEARCH_TYPES[t] for t in types if t in _SEARCH_TYPES] or list(_SEARCH_TYPES)
        resp = await self._api.get(
            f"catalog/{sf}/search",
            term=term.replace("'", ""),
            types=",".join(wanted),
            limit=min(limit, 25),
        )
        results = resp.get("results", {})
        out: dict[str, list] = {}
        for key in ("artists", "albums", "songs", "playlists"):
            items = results.get(key, {}).get("data", [])
            parsed = [p for p in (parsers.parse_any(i) for i in items) if p]
            if parsed:
                out[key] = parsed
        return out

    # ------------------------------------------------------------------ items
    async def get_track(self, track_id: str) -> dict[str, Any]:
        sf = await self.storefront()
        endpoint = (
            f"me/library/songs/{track_id}"
            if parsers.is_library_id(track_id)
            else f"catalog/{sf}/songs/{track_id}"
        )
        resp = await self._api.get(endpoint, include="artists,albums,catalog")
        data = resp.get("data") or []
        if not data:
            raise NotFound(f"track {track_id}")
        parsed = parsers.parse_track(data[0])
        if not parsed:
            raise NotFound(f"track {track_id}")
        return parsed

    async def get_tracks(self, ids: list[str]) -> list[dict[str, Any]]:
        """Batch catalog track lookup (<=300 ids)."""
        if not ids:
            return []
        sf = await self.storefront()
        catalog_ids = [i for i in ids if not parsers.is_library_id(i)]
        out: list[dict[str, Any]] = []
        for chunk_start in range(0, len(catalog_ids), 300):
            chunk = catalog_ids[chunk_start : chunk_start + 300]
            resp = await self._api.get(
                f"catalog/{sf}/songs", ids=",".join(chunk), include="artists,albums"
            )
            out.extend(p for p in (parsers.parse_track(i) for i in resp.get("data", [])) if p)
        return out

    async def get_album(self, album_id: str) -> dict[str, Any]:
        sf = await self.storefront()
        endpoint = (
            f"me/library/albums/{album_id}"
            if parsers.is_library_id(album_id)
            else f"catalog/{sf}/albums/{album_id}"
        )
        resp = await self._api.get(endpoint, include="artists,catalog")
        data = resp.get("data") or []
        if not data:
            raise NotFound(f"album {album_id}")
        return parsers.parse_album(data[0]) or {}

    async def get_album_tracks(self, album_id: str) -> list[dict[str, Any]]:
        sf = await self.storefront()
        if parsers.is_library_id(album_id):
            endpoint = f"me/library/albums/{album_id}/tracks"
        else:
            endpoint = f"catalog/{sf}/albums/{album_id}/tracks"
        items = await self._api.get_all(endpoint, include="artists,catalog")
        return [p for p in (parsers.parse_track(i) for i in items) if p]

    async def get_artist(self, artist_id: str) -> dict[str, Any]:
        sf = await self.storefront()
        resp = await self._api.get(f"catalog/{sf}/artists/{artist_id}")
        data = resp.get("data") or []
        if not data:
            raise NotFound(f"artist {artist_id}")
        return parsers.parse_artist(data[0]) or {}

    async def get_artist_albums(self, artist_id: str) -> list[dict[str, Any]]:
        sf = await self.storefront()
        items = await self._api.get_all(f"catalog/{sf}/artists/{artist_id}/albums")
        return [p for p in (parsers.parse_album(i) for i in items) if p]

    async def get_artist_top_tracks(self, artist_id: str) -> list[dict[str, Any]]:
        sf = await self.storefront()
        resp = await self._api.get(f"catalog/{sf}/artists/{artist_id}/view/top-songs")
        return [p for p in (parsers.parse_track(i) for i in resp.get("data", [])) if p]

    async def get_playlist(self, playlist_id: str) -> dict[str, Any]:
        sf = await self.storefront()
        if playlist_id.startswith("pl."):
            endpoint = f"catalog/{sf}/playlists/{playlist_id}"
        else:
            endpoint = f"me/library/playlists/{playlist_id}"
        resp = await self._api.get(endpoint)
        data = resp.get("data") or []
        if not data:
            raise NotFound(f"playlist {playlist_id}")
        return parsers.parse_playlist(data[0]) or {}

    async def get_playlist_tracks(self, playlist_id: str) -> list[dict[str, Any]]:
        sf = await self.storefront()
        if playlist_id.startswith("pl."):
            endpoint = f"catalog/{sf}/playlists/{playlist_id}/tracks"
        else:
            endpoint = f"me/library/playlists/{playlist_id}/tracks"
        items = await self._api.get_all(endpoint, include="artists,catalog")
        tracks = []
        for i in items:
            p = parsers.parse_track(i)
            if p and p["available"]:
                tracks.append(p)
        return tracks

    # ------------------------------------------------------------------ library
    async def library(self, kind: str) -> list[dict[str, Any]]:
        """kind in {playlists, albums, artists, songs}."""
        endpoint = f"me/library/{kind}"
        params: dict[str, Any] = {}
        if kind in ("albums", "songs", "artists"):
            params["include"] = "catalog"
        items = await self._api.get_all(endpoint, **params)
        return [p for p in (parsers.parse_any(i) for i in items) if p]

    # ------------------------------------------------------------------ discovery
    async def recommendations(self) -> list[dict[str, Any]]:
        resp = await self._api.get("me/recommendations")
        rows: list[dict[str, Any]] = []
        for row in resp.get("data", []):
            attrs = row.get("attributes", {})
            title = (attrs.get("title") or {}).get("stringForDisplay") or "Recommended"
            contents = row.get("relationships", {}).get("contents", {}).get("data", [])
            items = [p for p in (parsers.parse_any(i) for i in contents) if p]
            if items:
                rows.append({"title": title, "items": items})
        return rows

    async def stations(self) -> list[dict[str, Any]]:
        sf = await self.storefront()
        # Apple Music 1 / Hits / Country live radio, plus the user's personal station.
        out: list[dict[str, Any]] = []
        resp = await self._api.get(
            f"catalog/{sf}/stations", **{"filter[featured]": "apple-music-live-radio"}
        )
        out.extend(p for p in (parsers.parse_station(i) for i in resp.get("data", [])) if p)
        try:
            personal = await self._api.get(f"catalog/{sf}/stations", **{"filter[identity]": "personal"})
            out.extend(
                p for p in (parsers.parse_station(i) for i in personal.get("data", [])) if p
            )
        except (NotFound, KeyError):
            pass
        return out
