"""SPDX-License-Identifier: GPL-3.0-only"""

import pytest

from applemusic_helper import ffmpeg_fetch
from applemusic_helper.config import Config


@pytest.mark.parametrize(
    ("system", "machine", "expected"),
    [
        ("Linux", "x86_64", "x86_64-linux"),
        ("Linux", "aarch64", "aarch64-linux"),
        ("Linux", "armv7l", "arm-linux"),
        ("Darwin", "arm64", "darwin-arm64"),
        ("Darwin", "x86_64", "darwin-x86_64"),
        ("Windows", "AMD64", "win-x64"),
    ],
)
def test_platform_key(monkeypatch, system, machine, expected):
    monkeypatch.setattr(ffmpeg_fetch.platform, "system", lambda: system)
    monkeypatch.setattr(ffmpeg_fetch.platform, "machine", lambda: machine)
    assert ffmpeg_fetch.platform_key() == expected


def test_version_parse(monkeypatch):
    monkeypatch.setattr(
        ffmpeg_fetch.subprocess,
        "run",
        lambda *a, **k: type("R", (), {"stdout": "ffmpeg version 7.0.2-static ..."})(),
    )
    assert ffmpeg_fetch.ffmpeg_version("x") == (7, 0)
    assert ffmpeg_fetch.is_recent_enough("x")

    monkeypatch.setattr(
        ffmpeg_fetch.subprocess,
        "run",
        lambda *a, **k: type("R", (), {"stdout": "ffmpeg version 5.1.6-0+deb12u1 ..."})(),
    )
    assert not ffmpeg_fetch.is_recent_enough("x")


def test_ffmpeg_source_selection(tmp_path):
    cfg = Config.load(tmp_path / "config.json")
    assert cfg.ffmpeg_source == "auto"
    cfg.ffmpeg_source = "system"
    assert cfg.ffmpeg == "ffmpeg"
    cfg.ffmpeg_source = "custom"
    cfg.ffmpeg_path = "/opt/ffmpeg"
    assert cfg.ffmpeg == "/opt/ffmpeg"
    cfg.ffmpeg_source = "auto"
    (cfg.bin_dir).mkdir()
    (cfg.bin_dir / "ffmpeg").write_text("#!/bin/sh\n")
    assert cfg.ffmpeg == str(cfg.bin_dir / "ffmpeg")
