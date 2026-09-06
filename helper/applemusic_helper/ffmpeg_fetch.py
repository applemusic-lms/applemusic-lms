"""Obtain a modern static ffmpeg for the current platform.

SPDX-License-Identifier: GPL-3.0-only

Debian/LMS-image ffmpeg (5.1) cannot decrypt Apple's cenc / 8-byte-IV streams
("subsample size exceeds the packet size left"). When config.ffmpeg_source is
"auto" we download a verified static build (repackaged by our GitHub Actions as
`ffmpeg-<platform>.tar.gz`) into <data dir>/bin/ and use that.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import urllib.request
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

MIN_MAJOR, MIN_MINOR = 6, 1  # ffmpeg >= 6.1 handles Apple's cenc audio correctly


class FfmpegError(RuntimeError):
    pass


def platform_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "linux":
        if machine in ("x86_64", "amd64"):
            return "x86_64-linux"
        if machine in ("aarch64", "arm64"):
            return "aarch64-linux"
        if machine.startswith("arm") or machine.startswith("armv"):
            return "arm-linux"
    elif system == "darwin":
        return "darwin-arm64" if machine in ("arm64", "aarch64") else "darwin-x86_64"
    elif system == "windows":
        return "win-x64"
    raise FfmpegError(f"no bundled ffmpeg for {system}/{machine}")


def ffmpeg_version(path: str) -> tuple[int, int] | None:
    """Return (major, minor) of an ffmpeg binary, or None if it won't run."""
    try:
        out = subprocess.run(
            [path, "-version"], capture_output=True, text=True, timeout=10
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"ffmpeg version n?(\d+)\.(\d+)", out)
    if not m:
        # some builds print "ffmpeg version 7.0.2-static ..."
        m = re.search(r"ffmpeg version (\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else None


def is_recent_enough(path: str) -> bool:
    ver = ffmpeg_version(path)
    if ver is None:
        return False
    return ver >= (MIN_MAJOR, MIN_MINOR)


def _download(url: str) -> bytes:
    _LOGGER.info("downloading %s", url)
    req = urllib.request.Request(url, headers={"User-Agent": "applemusic-helper"})
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 - our own release URL
        return resp.read()


def _expected_sha(dist_url: str, name: str) -> str | None:
    try:
        sums = _download(f"{dist_url.rstrip('/')}/sha256sums.txt").decode()
    except OSError:
        return None
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name:
            return parts[0]
    return None


def ensure_ffmpeg(dist_url: str, bin_dir: Path) -> str:
    """Ensure a usable static ffmpeg exists in *bin_dir*; return its path."""
    if not dist_url:
        raise FfmpegError("ffmpeg_source is 'auto' but no dist_url is configured")

    target = bin_dir / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if target.exists() and is_recent_enough(str(target)):
        return str(target)

    plat = platform_key()
    name = f"ffmpeg-{plat}.tar.gz"
    url = f"{dist_url.rstrip('/')}/{name}"
    blob = _download(url)

    expected = _expected_sha(dist_url, name)
    if expected:
        actual = hashlib.sha256(blob).hexdigest()
        if actual != expected:
            raise FfmpegError(f"{name} sha256 mismatch: {actual} != {expected}")
    else:
        _LOGGER.warning("no sha256sums.txt entry for %s - skipping checksum", name)

    bin_dir.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        member = next(
            (m for m in tf.getmembers() if m.isfile() and Path(m.name).name.startswith("ffmpeg")),
            None,
        )
        if member is None:
            raise FfmpegError(f"{name} contains no ffmpeg binary")
        src = tf.extractfile(member)
        if src is None:
            raise FfmpegError(f"could not read ffmpeg from {name}")
        with open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst)

    tmp.chmod(tmp.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.replace(tmp, target)
    if platform.system() == "Darwin":
        subprocess.run(
            ["xattr", "-dr", "com.apple.quarantine", str(target)],
            capture_output=True,
            check=False,
        )

    if not is_recent_enough(str(target)):
        raise FfmpegError(f"downloaded ffmpeg at {target} is unusable or too old")
    _LOGGER.info("ffmpeg ready: %s (%s)", target, ".".join(map(str, ffmpeg_version(str(target)))))
    return str(target)
