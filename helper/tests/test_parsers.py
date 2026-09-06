"""SPDX-License-Identifier: GPL-3.0-only"""

from applemusic_helper import parsers

TRACK_OBJ = {
    "id": "1440841363",
    "type": "songs",
    "attributes": {
        "name": "Paranoid Android",
        "artistName": "Radiohead",
        "albumName": "OK Computer",
        "durationInMillis": 383000,
        "trackNumber": 2,
        "discNumber": 1,
        "contentRating": "clean",
        "genreNames": ["Alternative"],
        "playParams": {"id": "1440841363", "kind": "song"},
        "artwork": {"url": "https://ex/{w}x{h}{f}.jpg", "width": 3000, "height": 3000},
        "url": "https://music.apple.com/us/album/x/1440841242?i=1440841363",
    },
}

LIBRARY_TRACK_OBJ = {
    "id": "i.abc123",
    "type": "library-songs",
    "attributes": {"name": "Local Only", "playParams": {"id": "i.abc123"}},
    "relationships": {
        "catalog": {
            "data": [
                {
                    "id": "999",
                    "type": "songs",
                    "attributes": {
                        "name": "Catalog Name",
                        "artistName": "Band",
                        "durationInMillis": 1000,
                        "playParams": {"id": "999"},
                    },
                }
            ]
        }
    },
}


def test_parse_catalog_track():
    p = parsers.parse_track(TRACK_OBJ)
    assert p["id"] == "1440841363"
    assert p["uri"] == "applemusic://track/1440841363"
    assert p["title"] == "Paranoid Android"
    assert p["artist"] == "Radiohead"
    assert p["duration"] == 383
    assert p["cover"].startswith("https://ex/600x600")
    assert p["available"] is True


def test_library_track_prefers_catalog_id():
    p = parsers.parse_track(LIBRARY_TRACK_OBJ)
    assert p["id"] == "999"
    assert p["title"] == "Catalog Name"


def test_is_library_id():
    assert parsers.is_library_id("i.abc123")
    assert parsers.is_library_id("p.XXX")
    assert not parsers.is_library_id("1440841363")
    assert not parsers.is_library_id("pl.u-abc")
