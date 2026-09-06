"""Apple Music sign-in: manual media-user-token capture.

SPDX-License-Identifier: GPL-3.0-only

The developer token we ship is the web player's, which Apple locks to the
apple.com origin - so MusicKit's popup sign-in can't run on the helper's own
origin. Instead the user copies their media-user-token from a signed-in
music.apple.com tab and pastes it here. Server-side API calls then work because
the helper sends `Origin: https://music.apple.com` itself.
"""

from __future__ import annotations

import asyncio
import logging
import time
from importlib import resources

from aiohttp import web

from .apple_api import AppleApiError, NotAuthenticated

_LOGGER = logging.getLogger(__name__)

_VERIFY_TIMEOUT = 12  # seconds to wait for Apple before accepting the token unverified


def _page() -> str:
    return resources.files(__package__).joinpath("musickit.html").read_text("utf-8")


def add_routes(app: web.Application) -> None:
    app.router.add_get("/auth", _handle_page)
    app.router.add_get("/auth/", _handle_page)
    for path in ("/auth/token", "/auth/callback", "/token"):
        app.router.add_post(path, _handle_token)
    app.router.add_post("/auth/logout", _handle_logout)


async def _handle_page(request: web.Request) -> web.Response:
    return web.Response(text=_page(), content_type="text/html")


async def _handle_token(request: web.Request) -> web.Response:
    config = request.app["config"]
    catalog = request.app["catalog"]
    try:
        body = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text="expected JSON body")

    user_token = (body.get("music_user_token") or body.get("media_user_token") or "").strip()
    if len(user_token) < 20:
        raise web.HTTPBadRequest(text="missing / implausible media-user-token")

    storefront = (body.get("storefront") or config.storefront or "").lower()
    prev = (config.media_user_token, config.media_user_token_ts, config.storefront)
    config.update(
        media_user_token=user_token,
        media_user_token_ts=int(time.time()),
        storefront=storefront,
    )
    _LOGGER.info("Stored media-user-token (storefront hint=%s)", storefront or "?")

    # verify against Apple and pin the authoritative storefront
    try:
        catalog._storefront = None
        sf = await asyncio.wait_for(catalog.storefront(), _VERIFY_TIMEOUT)
        _LOGGER.info("Apple Music connected, storefront=%s", sf)
        return web.json_response({"status": "ok", "storefront": sf})
    except NotAuthenticated as err:
        # Apple actively rejected the credentials - this token is no good, undo
        _LOGGER.warning("Sign-in rejected by Apple: %s", err)
        config.update(
            media_user_token=prev[0], media_user_token_ts=prev[1], storefront=prev[2]
        )
        catalog._storefront = None
        # 200 (not 5xx): LMS's async HTTP client discards error-response bodies,
        # so the plugin can only see this message on a 2xx.
        return web.json_response(
            {"status": "error", "error": f"Apple rejected this token: {err}"}
        )
    except (asyncio.TimeoutError, AppleApiError, OSError) as err:
        # stored, but we couldn't reach Apple to confirm right now - keep it;
        # /health verifies once connectivity is back
        _LOGGER.warning("Token saved, verification deferred: %s", err)
        return web.json_response(
            {
                "status": "ok",
                "storefront": storefront or config.storefront or "",
                "warning": "saved, but couldn't reach Apple to verify just now",
            }
        )


async def _handle_logout(request: web.Request) -> web.Response:
    config = request.app["config"]
    config.update(media_user_token="", media_user_token_ts=0, storefront="")
    request.app["catalog"]._storefront = None
    _LOGGER.info("Signed out of Apple Music")
    return web.json_response({"status": "ok"})
