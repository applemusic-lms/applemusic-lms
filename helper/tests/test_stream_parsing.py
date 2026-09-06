"""SPDX-License-Identifier: GPL-3.0-only"""

from applemusic_helper.stream import _parse_m3u8

MEDIA_PLAYLIST = """#EXTM3U
#EXT-X-VERSION:6
#EXT-X-TARGETDURATION:6
#EXT-X-KEY:METHOD=SAMPLE-AES,URI="data:text/plain;base64,AAAAKGtleWlk",KEYFORMAT="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"
#EXT-X-MAP:URI="track-abc.mp4"
#EXT-X-BYTERANGE:1000@0
#EXTINF:5.9,
track-abc.mp4
#EXT-X-BYTERANGE:2000@1000
#EXTINF:5.9,
track-abc.mp4
#EXT-X-ENDLIST
"""

MASTER_PLAYLIST = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=256000,CODECS="mp4a.40.2"
media/prog_index.m3u8
"""


def test_media_playlist_extracts_map_and_key():
    seg, key_uri, variant = _parse_m3u8(MEDIA_PLAYLIST, "https://h/a/b/index.m3u8")
    assert seg == "track-abc.mp4"
    assert key_uri == "data:text/plain;base64,AAAAKGtleWlk"
    assert variant is None


def test_master_playlist_returns_variant():
    seg, key_uri, variant = _parse_m3u8(MASTER_PLAYLIST, "https://h/a/master.m3u8")
    assert variant == "https://h/a/media/prog_index.m3u8"
