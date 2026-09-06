"""Thin async client for the public Apple Music API.

SPDX-License-Identifier: GPL-3.0-only

Adapted from Music Assistant's apple_music/api_client.py (Apache-2.0).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp

from .developer_token import (
    DeveloperTokenError,
    scrape_developer_token,
    token_is_fresh,
    verify_developer_token,
)

_LOGGER = logging.getLogger(__name__)

# The web player uses amp-api; a real developer-account token would use
# api.music.apple.com. We ship the scraped web-player token, so default to amp-api.
DEFAULT_API_BASE = "https://amp-api.music.apple.com/v1"
LIBRARY_PAGE_SIZE = 100

# The scraped developer token is a web-player ("AMPWebPlay") token, origin-locked
# to apple.com. Present as the web player so Apple honours it.
_WEB_PLAYER_HEADERS = {
    "Origin": "https://music.apple.com",
    "Referer": "https://music.apple.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
}


class AppleApiError(RuntimeError):
    """Generic Apple Music API failure."""


class NotAuthenticated(AppleApiError):
    """Apple rejected our credentials - the user must sign in again."""


class NotFound(AppleApiError):
    """Requested resource does not exist."""


class AppleMusicApi:
    """HTTP wrapper around api.music.apple.com with token management + retries."""

    def __init__(self, config, session: aiohttp.ClientSession) -> None:
        self._config = config
        self._session = session
        self._api_base = (getattr(config, "api_base", "") or DEFAULT_API_BASE).rstrip("/")
        self._token_lock = asyncio.Lock()
        # simple global rate limit: >= 0.25s between requests (~4 req/s)
        self._min_interval = 0.25
        self._last_request = 0.0
        self._rl_lock = asyncio.Lock()

    # ------------------------------------------------------------------ tokens
    async def developer_token(self, *, force_refresh: bool = False) -> str:
        cfg = self._config
        if cfg.developer_token_manual and cfg.developer_token:
            return cfg.developer_token
        async with self._token_lock:
            if (
                not force_refresh
                and cfg.developer_token
                and token_is_fresh(cfg.developer_token)
            ):
                return cfg.developer_token
            _LOGGER.info("Refreshing Apple Music developer token")
            try:
                token = await scrape_developer_token(self._session)
            except (aiohttp.ClientError, DeveloperTokenError) as err:
                if cfg.developer_token:
                    _LOGGER.warning(
                        "Developer token refresh failed (%s); keeping current token", err
                    )
                    return cfg.developer_token
                raise NotAuthenticated(f"Cannot obtain developer token: {err}") from err
            cfg.update(
                developer_token=token,
                developer_token_fetched_at=int(time.time()),
            )
            return token

    @property
    def _user_token(self) -> str:
        return self._config.media_user_token

    async def _headers(self, *, force_refresh: bool = False) -> dict[str, str]:
        headers = dict(_WEB_PLAYER_HEADERS)
        headers["Authorization"] = (
            f"Bearer {await self.developer_token(force_refresh=force_refresh)}"
        )
        if self._user_token:
            headers["Music-User-Token"] = self._user_token
        return headers

    # ------------------------------------------------------------------ requests
    async def _throttle(self) -> None:
        async with self._rl_lock:
            wait = self._min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()

    async def _request(
        self, method: str, endpoint: str, *, params: dict | None = None, json_body: Any = None
    ) -> dict[str, Any]:
        url = (
            endpoint
            if endpoint.startswith("http")
            else f"{self._api_base}/{endpoint.lstrip('/')}"
        )
        params = {k: v for k, v in (params or {}).items() if v is not None}
        backoff = 1.0
        for attempt in range(8):
            await self._throttle()
            force_refresh = attempt == 1  # one retry with a fresh developer token
            try:
                async with self._session.request(
                    method,
                    url,
                    headers=await self._headers(force_refresh=force_refresh),
                    params=params,
                    json=json_body,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    if resp.status in (401, 403):
                        # could be a stale developer token; verify before giving up
                        if attempt == 0:
                            _LOGGER.debug("%s %s -> %s, will retry", method, endpoint, resp.status)
                            continue
                        body = await resp.text()
                        if not await verify_developer_token(
                            self._session, self._config.developer_token
                        ):
                            raise NotAuthenticated(
                                "Apple rejected the developer token"
                            )
                        raise NotAuthenticated(
                            f"Apple denied access to {endpoint} - sign in to Apple Music again "
                            f"({resp.status}: {body[:200]})"
                        )
                    if resp.status == 404:
                        if params.get("limit") is not None and params.get("offset"):
                            return {}
                        raise NotFound(f"{endpoint} not found")
                    if resp.status == 429 or resp.status >= 500:
                        _LOGGER.debug(
                            "%s %s -> %s, backoff %.0fs", method, endpoint, resp.status, backoff
                        )
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, 64)
                        continue
                    resp.raise_for_status()
                    if resp.content_length == 0 or resp.status == 204:
                        return {}
                    return await resp.json()
            except (aiohttp.ClientConnectionError, aiohttp.ClientPayloadError, TimeoutError) as err:
                _LOGGER.debug("transient error %s on %s: %s", type(err).__name__, endpoint, err)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 64)
        raise AppleApiError(f"Apple Music API kept failing for {endpoint}")

    async def get(self, endpoint: str, **params: Any) -> dict[str, Any]:
        return await self._request("GET", endpoint, params=params)

    async def post(self, endpoint: str, data: Any = None, **params: Any) -> dict[str, Any]:
        return await self._request("POST", endpoint, params=params, json_body=data)

    async def put(self, endpoint: str, data: Any = None, **params: Any) -> dict[str, Any]:
        return await self._request("PUT", endpoint, params=params, json_body=data)

    async def delete(self, endpoint: str, data: Any = None, **params: Any) -> dict[str, Any]:
        return await self._request("DELETE", endpoint, params=params, json_body=data)

    # ------------------------------------------------------------------ paging
    async def iter_all(
        self, endpoint: str, key: str = "data", page_size: int = LIBRARY_PAGE_SIZE, **params: Any
    ):
        offset = 0
        while True:
            params.update(limit=page_size, offset=offset)
            result = await self.get(endpoint, **params)
            if key not in result:
                break
            for item in result[key]:
                yield item
            if not result.get("next"):
                break
            offset += page_size

    async def get_all(self, endpoint: str, key: str = "data", **params: Any) -> list[dict]:
        return [item async for item in self.iter_all(endpoint, key, **params)]

    # ------------------------------------------------------------------ misc
    async def resolve_storefront(self) -> str:
        result = await self.get("me/storefront")
        return result["data"][0]["id"]
