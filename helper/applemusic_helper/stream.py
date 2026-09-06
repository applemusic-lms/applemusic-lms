"""Resolve a catalog track to a decrypted audio stream.

SPDX-License-Identifier: GPL-3.0-only

Adapted from Music Assistant's apple_music/streaming.py (Apache-2.0).

Flow:
  1. POST webPlayback  -> assets + hls-key-server-url
  2. pick the "28:ctrp256" (256 kbps AAC) asset, fetch its HLS media playlist
  3. from the playlist: the fragmented-MP4 URL + the Widevine key-id
  4. Widevine license exchange -> AES-CTR content key
  5. ffmpeg -decryption_key <hex> -i <mp4> ...  -> FLAC (or copied AAC) on stdout
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urljoin

import aiohttp

from .widevine import _decryption_headers

if TYPE_CHECKING:
    from .config import Config
    from .widevine import WidevineClient

_LOGGER = logging.getLogger(__name__)

_WEBPLAYBACK_URL = (
    "https://play.music.apple.com/WebObjects/MZPlay.woa/wa/webPlayback"
)
_CTRP256_FLAVOR = "28:ctrp256"


class StreamError(RuntimeError):
    """Raised when a track cannot be resolved to a playable stream."""


@dataclass
class ResolvedStream:
    track_id: str
    mp4_url: str
    content_key_hex: str
    duration: int  # seconds, 0 if unknown


class StreamResolver:
    def __init__(
        self, config: "Config", session: aiohttp.ClientSession, widevine: "WidevineClient"
    ) -> None:
        self._config = config
        self._session = session
        self._widevine = widevine
        # Apple allows one active stream per account; serialise resolution.
        self._lock = asyncio.Lock()

    async def resolve(self, track_id: str) -> ResolvedStream:
        async with self._lock:
            meta = await self._fetch_webplayback(track_id)
            assets = meta.get("assets") or []
            license_url = meta.get("hls-key-server-url")
            if not license_url:
                raise StreamError(f"No key-server URL for track {track_id}")
            mp4_url, key_uri = await self._parse_playlist(assets)
            key_id = base64.b64decode(key_uri.split(",", 1)[1])
            key_hex = await self._widevine.get_content_key(
                track_id=track_id,
                key_id=key_id,
                key_uri=key_uri,
                license_url=license_url,
            )
            duration = 0
            try:
                duration = int(int(meta.get("assets", [{}])[0].get("metadata", {})
                                   .get("durationInMillis", 0)) / 1000)
            except (ValueError, TypeError, AttributeError, IndexError):
                pass
            return ResolvedStream(track_id, mp4_url, key_hex, duration)

    # ------------------------------------------------------------------ apple
    async def _fetch_webplayback(self, track_id: str) -> dict:
        payload = {"salableAdamId": track_id}
        headers = _decryption_headers(self._config)
        last_err: Exception | None = None
        for attempt in range(2):
            try:
                async with self._session.post(
                    _WEBPLAYBACK_URL, json=payload, headers=headers, ssl=True
                ) as resp:
                    resp.raise_for_status()
                    content = await resp.json()
                if content.get("failureType"):
                    raise StreamError(
                        content.get("failureMessage")
                        or f"webPlayback failed for {track_id}"
                    )
                song_list = content.get("songList") or []
                if not song_list:
                    raise StreamError(f"webPlayback returned no song for {track_id}")
                return song_list[0]
            except (aiohttp.ClientError, StreamError) as err:
                last_err = err
                if attempt == 0:
                    _LOGGER.warning("webPlayback retry for %s: %s", track_id, err)
                    await asyncio.sleep(1)
        raise StreamError(f"webPlayback failed for {track_id}: {last_err}")

    async def _parse_playlist(self, assets: list[dict]) -> tuple[str, str]:
        urls = [a["URL"] for a in assets if a.get("flavor") == _CTRP256_FLAVOR and a.get("URL")]
        if not urls:
            raise StreamError("No 28:ctrp256 (256 kbps AAC) asset for this track")
        playlist_url = urls[0]
        text = await self._get_text(playlist_url)
        segment, key_uri, variant = _parse_m3u8(text, playlist_url)
        if variant:  # master playlist -> descend one level
            text = await self._get_text(variant)
            segment, key_uri, _ = _parse_m3u8(text, variant)
            playlist_url = variant
        if not segment or not key_uri:
            raise StreamError("HLS playlist missing segment or key URI")
        mp4_url = urljoin(playlist_url.rsplit("/", 1)[0] + "/", segment)
        return mp4_url, key_uri

    async def _get_text(self, url: str) -> str:
        async with self._session.get(url, ssl=True) as resp:
            resp.raise_for_status()
            return await resp.text()

    # ------------------------------------------------------------------ fetch + ffmpeg
    async def fetch_mp4(self, stream: ResolvedStream, dest: str) -> int:
        """Download the encrypted fragmented-MP4 to *dest*.

        We fetch it ourselves rather than letting ffmpeg pull the URL: a modern
        ffmpeg is needed to decrypt Apple's cenc/8-byte-IV streams, and static
        ffmpeg builds often can't resolve DNS inside a container. aiohttp has no
        such problem.
        """
        total = 0
        async with self._session.get(stream.mp4_url, ssl=True) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as fh:
                async for chunk in resp.content.iter_chunked(256 * 1024):
                    fh.write(chunk)
                    total += len(chunk)
        if total < 1024:
            raise StreamError(f"encrypted asset was empty ({total} bytes)")
        return total

    async def open_ffmpeg(self, mp4_path: str, key_hex: str, *, seek: float = 0.0):
        """Spawn ffmpeg on a local encrypted file; stdout = decoded audio."""
        fmt = self._config.audio_format
        args = [self._config.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin"]
        if seek and seek > 0:
            args += ["-ss", f"{seek:.3f}"]
        args += ["-decryption_key", key_hex, "-i", mp4_path, "-vn"]
        if fmt == "aac":
            args += ["-c:a", "copy", "-f", "adts"]
        else:  # flac
            args += ["-c:a", "flac", "-compression_level", "5", "-f", "flac"]
        args += ["pipe:1"]
        _LOGGER.debug("ffmpeg: %s", " ".join(args))
        return await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    @property
    def content_type(self) -> str:
        return "audio/aac" if self._config.audio_format == "aac" else "audio/flac"


_ATTR_RE = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')


def _attrs(line: str) -> dict[str, str]:
    """Parse an HLS tag's attribute list, honouring quoted values (which may
    contain commas, as in a base64 data: URI)."""
    body = line.split(":", 1)[1] if ":" in line else ""
    return {m.group(1): m.group(2).strip('"') for m in _ATTR_RE.finditer(body)}


def _parse_m3u8(text: str, base_url: str) -> tuple[str | None, str | None, str | None]:
    """Return (first_segment_path, key_uri, variant_url).

    variant_url is set only for a master playlist (EXT-X-STREAM-INF).
    """
    segment: str | None = None
    key_uri: str | None = None
    variant: str | None = None
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-KEY") or line.startswith("#EXT-X-SESSION-KEY"):
            key_uri = _attrs(line).get("URI") or key_uri
        elif line.startswith("#EXT-X-MAP"):
            # EXT-X-MAP URI is the init segment == the fragmented mp4 for Apple
            segment = _attrs(line).get("URI") or segment
        elif line.startswith("#EXT-X-STREAM-INF"):
            nxt = lines[i + 1] if i + 1 < len(lines) else None
            if nxt and not nxt.startswith("#"):
                variant = urljoin(base_url.rsplit("/", 1)[0] + "/", nxt)
        elif not line.startswith("#") and segment is None:
            segment = line
    return segment, key_uri, variant
