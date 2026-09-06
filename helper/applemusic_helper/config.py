"""Persistent configuration for applemusic-helper.

SPDX-License-Identifier: GPL-3.0-only

The config file is the single source of truth for every credential. LMS never
stores Apple tokens; it only knows the helper's URL.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(
    os.environ.get(
        "APPLEMUSIC_HELPER_CONFIG",
        Path.home() / ".config" / "applemusic-helper" / "config.json",
    )
)


@dataclass
class Config:
    """Helper configuration, round-tripped to a JSON file."""

    # --- network ---
    bind_host: str = "127.0.0.1"
    bind_port: int = 9863
    # Public origin the sign-in page is reached on (needed for the MusicKit
    # redirect). Defaults to http://<bind_host>:<bind_port>; override if the
    # helper sits behind another hostname/port.
    public_url: str = ""

    # --- apple credentials ---
    # Apple Music API host. Blank -> amp-api.music.apple.com (matches the scraped
    # web-player token). Set to https://api.music.apple.com/v1 only with a real
    # developer-account token.
    api_base: str = ""
    developer_token: str = ""          # JWT, auto-scraped unless set manually
    developer_token_fetched_at: int = 0
    developer_token_manual: bool = False
    media_user_token: str = ""         # per-account, from MusicKit sign-in
    media_user_token_ts: int = 0
    storefront: str = ""               # e.g. "us", "gb" - resolved after sign-in

    # --- widevine cdm ---
    # Either a single .wvd file, or a client_id/private_key pair. Relative paths
    # resolve against the config file's directory.
    cdm_wvd_path: str = ""
    cdm_client_id_path: str = ""
    cdm_private_key_path: str = ""

    # --- audio ---
    # "flac"  -> ffmpeg decodes + re-encodes to FLAC (default, most compatible)
    # "aac"   -> ffmpeg copies the AAC stream into ADTS (lowest CPU, LMS transcodes)
    audio_format: str = "flac"

    # ffmpeg_source:
    #   "auto"   -> download a verified static build into <data dir>/bin/ffmpeg
    #   "system" -> use "ffmpeg" from PATH
    #   "custom" -> use ffmpeg_path verbatim
    ffmpeg_source: str = "auto"
    ffmpeg_path: str = ""

    # base URL to download the bundled ffmpeg from (a GitHub release). The plugin
    # passes this so the frozen binary and the plugin agree on the origin.
    dist_url: str = ""

    # --- misc ---
    log_level: str = "INFO"
    log_file: str = ""          # blank -> stderr only

    def __post_init__(self) -> None:
        # non-serialisable runtime state - deliberately not dataclass fields
        self._path: Path = DEFAULT_CONFIG_PATH
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ load/save
    @classmethod
    def load(cls, path: Path | str | None = None) -> "Config":
        """Load config from *path*, creating it with defaults if absent."""
        p = Path(path) if path else DEFAULT_CONFIG_PATH
        cfg = cls()
        cfg._path = p
        if p.exists():
            try:
                raw = json.loads(p.read_text("utf-8"))
            except (json.JSONDecodeError, OSError) as err:
                _LOGGER.error("Could not read config %s: %s - using defaults", p, err)
                raw = {}
            known = {f.name for f in fields(cls) if not f.name.startswith("_")}
            for key, value in raw.items():
                if key in known:
                    setattr(cfg, key, value)
                else:
                    _LOGGER.warning("Ignoring unknown config key %r", key)
        else:
            _LOGGER.info("No config at %s - creating with defaults", p)
            cfg.save()
        return cfg

    def save(self) -> None:
        """Atomically write the config back to disk."""
        with self._lock:
            data: dict[str, Any] = {
                f.name: getattr(self, f.name) for f in fields(self)
            }
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=self._path.parent, prefix=".config-", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2, sort_keys=True)
                    fh.write("\n")
                os.replace(tmp, self._path)
                try:
                    os.chmod(self._path, 0o600)
                except OSError:
                    pass
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
                raise

    # ------------------------------------------------------------------ helpers
    @property
    def path(self) -> Path:
        return self._path

    @property
    def effective_public_url(self) -> str:
        if self.public_url:
            return self.public_url.rstrip("/")
        host = "127.0.0.1" if self.bind_host in ("0.0.0.0", "::") else self.bind_host
        return f"http://{host}:{self.bind_port}"

    def _resolve(self, value: str) -> Path | None:
        if not value:
            return None
        p = Path(value)
        if not p.is_absolute():
            p = self._path.parent / p
        return p

    @property
    def data_dir(self) -> Path:
        return self._path.parent

    @property
    def bin_dir(self) -> Path:
        return self._path.parent / "bin"

    @property
    def bundled_ffmpeg(self) -> Path:
        name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        return self.bin_dir / name

    @property
    def ffmpeg(self) -> str:
        """Path to the ffmpeg binary to use, per ffmpeg_source.

        "custom" -> ffmpeg_path; "system" -> "ffmpeg"; "auto" -> the bundled
        build under <data dir>/bin (download is handled by ffmpeg_fetch, not
        here). Falls back sensibly if a source is misconfigured.
        """
        source = (self.ffmpeg_source or "auto").lower()
        if source == "custom" and self.ffmpeg_path:
            return self.ffmpeg_path
        if source == "system":
            return "ffmpeg"
        if self.bundled_ffmpeg.exists():
            return str(self.bundled_ffmpeg)
        # auto but not downloaded yet, or custom with no path set
        return self.ffmpeg_path or "ffmpeg"

    @property
    def wvd_path(self) -> Path | None:
        return self._resolve(self.cdm_wvd_path)

    @property
    def client_id_path(self) -> Path | None:
        return self._resolve(self.cdm_client_id_path)

    @property
    def private_key_path(self) -> Path | None:
        return self._resolve(self.cdm_private_key_path)

    def cdm_configured(self) -> bool:
        if self.wvd_path and self.wvd_path.exists():
            return True
        return bool(
            self.client_id_path
            and self.client_id_path.exists()
            and self.private_key_path
            and self.private_key_path.exists()
        )

    def update(self, **changes: Any) -> None:
        """Set fields and persist."""
        known = {f.name for f in fields(type(self)) if not f.name.startswith("_")}
        for key, value in changes.items():
            if key not in known:
                raise KeyError(key)
            setattr(self, key, value)
        self.save()
