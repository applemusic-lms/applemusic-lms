"""Obtain an Apple Music *developer token* (JWT).

SPDX-License-Identifier: GPL-3.0-only

Apple's web player configures MusicKit with a short-lived developer token
(~6 month expiry) that is embedded in its JS bundle. There is no documented
endpoint for it, so we scrape it - the same approach the community Apple Music
downloaders use. A manually supplied token (config.developer_token_manual)
always wins.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time

import aiohttp

_LOGGER = logging.getLogger(__name__)

_HOME_URL = "https://music.apple.com/us/browse"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

# <script ... src="/assets/index-LEGACY-xxxx.js"> and friends
_BUNDLE_RE = re.compile(r'src="(/assets/[^"]*index[^"]*\.js)"')
# a bare JWT literal inside the JS: "eyJhbGciOiJFUzI1Ni...."
_JWT_RE = re.compile(r'"(eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)"')


class DeveloperTokenError(RuntimeError):
    """Raised when a usable developer token cannot be obtained."""


def _jwt_exp(token: str) -> int | None:
    """Return the `exp` claim (unix seconds) of a JWT, or None."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        exp = payload.get("exp")
        return int(exp) if exp is not None else None
    except (ValueError, KeyError, IndexError, json.JSONDecodeError):
        return None


def token_is_fresh(token: str, *, skew: int = 24 * 3600) -> bool:
    """True if *token* looks like a JWT that is not (nearly) expired."""
    if not token or token.count(".") != 2:
        return False
    exp = _jwt_exp(token)
    if exp is None:
        # unparseable exp - assume usable, the API call will tell us otherwise
        return True
    return exp - skew > time.time()


async def scrape_developer_token(session: aiohttp.ClientSession) -> str:
    """Fetch music.apple.com and extract the developer token from its JS bundle."""
    async with session.get(
        _HOME_URL, headers={"User-Agent": _UA}, allow_redirects=True
    ) as resp:
        resp.raise_for_status()
        html = await resp.text()

    bundles = _BUNDLE_RE.findall(html)
    if not bundles:
        raise DeveloperTokenError(
            "Could not locate the Apple Music JS bundle - the web player markup changed"
        )

    for rel in dict.fromkeys(bundles):  # preserve order, dedupe
        url = f"https://music.apple.com{rel}"
        try:
            async with session.get(url, headers={"User-Agent": _UA}) as resp:
                resp.raise_for_status()
                js = await resp.text()
        except aiohttp.ClientError as err:  # pragma: no cover - network
            _LOGGER.debug("bundle fetch failed %s: %s", url, err)
            continue
        for candidate in _JWT_RE.findall(js):
            if token_is_fresh(candidate):
                _LOGGER.info("Scraped developer token from %s", rel)
                return candidate

    raise DeveloperTokenError(
        "No valid developer token found in the Apple Music JS bundle"
    )


async def verify_developer_token(session: aiohttp.ClientSession, token: str) -> bool:
    """Return True if the API accepts *token* (401/403 -> False, other -> unknown/True)."""
    try:
        async with session.get(
            "https://api.music.apple.com/v1/test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status in (401, 403):
                return False
            return True
    except (aiohttp.ClientError, TimeoutError):
        return True  # inconclusive; don't discard a token over a network blip
