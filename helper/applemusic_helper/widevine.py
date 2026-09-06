"""Widevine license exchange for Apple Music catalog tracks.

SPDX-License-Identifier: GPL-3.0-only

Adapted from Music Assistant's apple_music/streaming.py (Apache-2.0).

Given a track's key-id and Apple's per-track HLS key-server URL, run an L3 CDM
(supplied by the user) to obtain the AES-CTR content key that ffmpeg needs to
decrypt the fragmented MP4.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from typing import TYPE_CHECKING

import aiohttp
from pywidevine import PSSH, Cdm, Device, DeviceTypes
from pywidevine.license_protocol_pb2 import WidevinePsshData

if TYPE_CHECKING:
    from .config import Config

_LOGGER = logging.getLogger(__name__)

_KEY_CACHE_TTL = 3600


class CdmError(RuntimeError):
    """Raised when the CDM is missing/invalid or a license request fails."""


class WidevineClient:
    """Loads the user's CDM once and resolves per-track content keys."""

    def __init__(self, config: "Config", session: aiohttp.ClientSession) -> None:
        self._config = config
        self._session = session
        self._device: Device | None = None
        self._device_error: str | None = None
        self._keys: dict[str, tuple[float, str]] = {}
        self._load_device()

    # ------------------------------------------------------------------ device
    def _load_device(self) -> None:
        cfg = self._config
        try:
            if cfg.wvd_path and cfg.wvd_path.exists():
                self._device = Device.load(str(cfg.wvd_path))
                _LOGGER.info("Loaded Widevine device from %s", cfg.wvd_path.name)
                return
            if (
                cfg.client_id_path
                and cfg.client_id_path.exists()
                and cfg.private_key_path
                and cfg.private_key_path.exists()
            ):
                self._device = Device(
                    type_=DeviceTypes.ANDROID,
                    security_level=3,
                    flags=None,
                    private_key=cfg.private_key_path.read_bytes(),
                    client_id=cfg.client_id_path.read_bytes(),
                )
                _LOGGER.info("Loaded Widevine device from client_id + private_key")
                return
        except Exception as err:  # noqa: BLE001 - pywidevine raises bare Exception subclasses
            self._device_error = f"{type(err).__name__}: {err}"
            _LOGGER.error("Failed to load Widevine CDM: %s", self._device_error)
            return
        self._device_error = "no CDM configured"
        _LOGGER.warning(
            "No Widevine CDM configured - encrypted catalog tracks will not play"
        )

    @property
    def available(self) -> bool:
        return self._device is not None

    @property
    def status(self) -> str:
        return "ok" if self._device else (self._device_error or "unavailable")

    def reload(self) -> None:
        self._device = None
        self._device_error = None
        self._keys.clear()
        self._load_device()

    # ------------------------------------------------------------------ keys
    @staticmethod
    def _build_pssh(key_id: bytes) -> PSSH:
        pssh_data = WidevinePsshData()
        pssh_data.algorithm = WidevinePsshData.AESCTR
        pssh_data.key_ids.append(key_id)
        init_data = base64.b64encode(pssh_data.SerializeToString()).decode()
        return PSSH.new(system_id=PSSH.SystemId.Widevine, init_data=init_data)

    async def get_content_key(
        self, *, track_id: str, key_id: bytes, key_uri: str, license_url: str
    ) -> str:
        """Return the AES content key (hex) for a track, using a short-lived cache."""
        cached = self._keys.get(track_id)
        if cached and cached[0] > time.time():
            return cached[1]
        if not self._device:
            raise CdmError(f"Widevine CDM unavailable: {self.status}")

        cdm = Cdm.from_device(self._device)
        session_id = cdm.open()
        try:
            challenge = cdm.get_license_challenge(session_id, self._build_pssh(key_id))
            license_b64 = await self._request_license(
                challenge=challenge,
                license_url=license_url,
                key_uri=key_uri,
                track_id=track_id,
            )
            cdm.parse_license(session_id, license_b64)
            content_key = next(
                (k for k in cdm.get_keys(session_id) if k.type == "CONTENT"), None
            )
            if content_key is None:
                raise CdmError(f"No content key returned for track {track_id}")
            key_hex = content_key.key.hex()
        finally:
            cdm.close(session_id)

        self._keys[track_id] = (time.time() + _KEY_CACHE_TTL, key_hex)
        return key_hex

    async def _request_license(
        self, *, challenge: bytes, license_url: str, key_uri: str, track_id: str
    ) -> str:
        payload = {
            "challenge": base64.b64encode(challenge).decode(),
            "key-system": "com.widevine.alpha",
            "uri": key_uri,
            "adamId": track_id,
            "isLibrary": False,
            "user-initiated": True,
        }
        headers = _decryption_headers(self._config)
        # Apple's key server presents a cert chain aiohttp dislikes; MA disables
        # verification here too. The request body carries no secrets beyond the
        # (single-use) challenge.
        async with self._session.post(
            license_url, data=json.dumps(payload), headers=headers, ssl=False
        ) as resp:
            resp.raise_for_status()
            content = await resp.json()
            license_b64 = content.get("license")
            if not license_b64:
                raise CdmError(f"Apple returned no license for track {track_id}: {content}")
            return license_b64


def _decryption_headers(config: "Config") -> dict[str, str]:
    return {
        "authorization": f"Bearer {config.developer_token}",
        "media-user-token": config.media_user_token,
        "accept": "application/json",
        "origin": "https://music.apple.com",
        "referer": "https://music.apple.com/",
        "content-type": "application/json;charset=utf-8",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
    }
