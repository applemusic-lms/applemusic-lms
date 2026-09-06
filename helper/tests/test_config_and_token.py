"""SPDX-License-Identifier: GPL-3.0-only"""

import base64
import json
import time

from applemusic_helper.config import Config
from applemusic_helper.developer_token import token_is_fresh


def _fake_jwt(exp: int) -> str:
    def part(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{part({'alg': 'ES256'})}.{part({'exp': exp})}.sig"


def test_config_roundtrip(tmp_path):
    p = tmp_path / "config.json"
    cfg = Config.load(p)
    assert p.exists()
    cfg.update(media_user_token="abc", storefront="gb")
    again = Config.load(p)
    assert again.media_user_token == "abc"
    assert again.storefront == "gb"
    assert again.bind_port == 9863


def test_config_ignores_unknown_keys(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"bind_port": 5000, "bogus": 1}))
    cfg = Config.load(p)
    assert cfg.bind_port == 5000


def test_cdm_detection(tmp_path):
    p = tmp_path / "config.json"
    cfg = Config.load(p)
    assert not cfg.cdm_configured()
    wvd = tmp_path / "device.wvd"
    wvd.write_bytes(b"x")
    cfg.update(cdm_wvd_path="device.wvd")
    assert cfg.cdm_configured()
    assert cfg.wvd_path == wvd


def test_token_freshness():
    assert token_is_fresh(_fake_jwt(int(time.time()) + 90 * 86400))
    assert not token_is_fresh(_fake_jwt(int(time.time()) - 10))
    assert not token_is_fresh("not-a-jwt")
