"""Turn raw Apple Music API objects into flat dicts the LMS plugin consumes.

SPDX-License-Identifier: GPL-3.0-only

Adapted from Music Assistant's apple_music/parsers.py (Apache-2.0). The output
shape is deliberately small - just what an OPML menu / TrackInfo needs.
"""

from __future__ import annotations

import re
from typing import Any

MAX_ARTWORK = 600  # px; LMS thumbnails are small, keep payloads light

_LIBRARY_ID_RE = re.compile(r"[ailp]\.[a-zA-Z0-9]+")


def is_library_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_LIBRARY_ID_RE.fullmatch(value))


def artwork_url(attributes: dict[str, Any], size: int = MAX_ARTWORK) -> str | None:
    artwork = attributes.get("artwork") or {}
    url = artwork.get("url")
    if not url:
        return None
    w = min(artwork.get("width") or size, size)
    h = min(artwork.get("height") or size, size)
    return url.replace("{w}", str(w)).replace("{h}", str(h)).replace("{f}", "jpg")


def _catalog_id_and_attrs(obj: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Prefer the catalog counterpart of a library object (has a streamable id)."""
    rel = obj.get("relationships", {})
    catalog = rel.get("catalog", {}).get("data") or []
    if obj.get("type", "").startswith("library-") and catalog and "attributes" in catalog[0]:
        return catalog[0]["id"], catalog[0]["attributes"]
    return obj["id"], obj.get("attributes", {})


def _is_available(attributes: dict[str, Any]) -> bool:
    play = attributes.get("playParams") or {}
    if play.get("id") is None:
        return False
    return not (play.get("purchasedId") is not None and play.get("catalogId") is None)


def parse_track(obj: dict[str, Any]) -> dict[str, Any] | None:
    track_id, attrs = _catalog_id_and_attrs(obj)
    if not attrs:
        return None
    rel = obj.get("relationships", {})
    artists = [a["attributes"]["name"] for a in rel.get("artists", {}).get("data", [])
               if a.get("attributes", {}).get("name")]
    artist = ", ".join(artists) or attrs.get("artistName") or ""
    return {
        "type": "track",
        "id": track_id,
        "uri": f"applemusic://track/{track_id}",
        "title": attrs.get("name", ""),
        "artist": artist,
        "album": attrs.get("albumName", ""),
        "duration": int(attrs.get("durationInMillis", 0) / 1000),
        "track_number": attrs.get("trackNumber"),
        "disc_number": attrs.get("discNumber"),
        "cover": artwork_url(attrs),
        "explicit": attrs.get("contentRating") == "explicit",
        "genres": attrs.get("genreNames", []),
        "available": _is_available(attrs),
        "url": attrs.get("url"),
    }


def parse_album(obj: dict[str, Any]) -> dict[str, Any] | None:
    album_id, attrs = _catalog_id_and_attrs(obj)
    if not attrs:
        return None
    year = None
    if rd := attrs.get("releaseDate"):
        try:
            year = int(rd.split("-")[0])
        except ValueError:
            pass
    return {
        "type": "album",
        "id": album_id,
        "uri": f"applemusic://album/{album_id}",
        "title": attrs.get("name", ""),
        "artist": attrs.get("artistName", ""),
        "cover": artwork_url(attrs),
        "year": year,
        "track_count": attrs.get("trackCount"),
        "explicit": attrs.get("contentRating") == "explicit",
        "genres": attrs.get("genreNames", []),
        "url": attrs.get("url"),
    }


def parse_artist(obj: dict[str, Any]) -> dict[str, Any] | None:
    artist_id, attrs = _catalog_id_and_attrs(obj)
    name = attrs.get("name")
    if not name:
        return None
    return {
        "type": "artist",
        "id": artist_id,
        "uri": f"applemusic://artist/{artist_id}",
        "name": name,
        "cover": artwork_url(attrs),
        "genres": attrs.get("genreNames", []),
        "url": attrs.get("url"),
    }


def parse_playlist(obj: dict[str, Any]) -> dict[str, Any] | None:
    attrs = obj.get("attributes", {})
    if not attrs:
        return None
    raw_id = obj["id"]
    play = attrs.get("playParams", {})
    # library playlists: keep the "p." id for reads; catalog "pl." for sharing
    playlist_id = raw_id if is_library_id(raw_id) else (play.get("globalId") or raw_id)
    descr = attrs.get("description") or {}
    return {
        "type": "playlist",
        "id": playlist_id,
        "uri": f"applemusic://playlist/{playlist_id}",
        "name": attrs.get("name", "Unknown Playlist"),
        "curator": attrs.get("curatorName", ""),
        "cover": artwork_url(attrs),
        "description": descr.get("standard") or descr.get("short") or "",
        "editable": bool(attrs.get("canEdit")),
        "url": attrs.get("url"),
    }


def parse_station(obj: dict[str, Any]) -> dict[str, Any] | None:
    attrs = obj.get("attributes", {})
    if not attrs.get("name"):
        return None
    return {
        "type": "station",
        "id": obj["id"],
        "uri": f"applemusic://station/{obj['id']}",
        "name": attrs["name"],
        "cover": artwork_url(attrs),
        "url": attrs.get("url"),
    }


_PARSERS = {
    "songs": parse_track,
    "library-songs": parse_track,
    "albums": parse_album,
    "library-albums": parse_album,
    "artists": parse_artist,
    "library-artists": parse_artist,
    "playlists": parse_playlist,
    "library-playlists": parse_playlist,
    "stations": parse_station,
}


def parse_any(obj: dict[str, Any]) -> dict[str, Any] | None:
    fn = _PARSERS.get(obj.get("type", ""))
    return fn(obj) if fn else None
