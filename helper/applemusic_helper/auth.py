"""Apple Music sign-in: manual media-user-token capture.

SPDX-License-Identifier: GPL-3.0-only

The developer token we ship is the web player's, which Apple locks to the
apple.com origin - so MusicKit's popup sign-in can't run on the helper's own
origin. Instead the user copies their media-user-token from a signed-in
music.apple.com tab and pastes it here. Server-side API calls then work because
the helper sends `Origin: https://music.apple.com` itself.
"""

from __future__ import annotations

import logging
import time
from importlib import resources

from aiohttp import web

_LOGGER = logging.getLogger(__name__)


def _page(storefront: str) -> str:
    html = resources.files(__package__).joinpath("musickit.html").read_text("utf-8")
    return html.replace("%%STOREFRONT%%", storefront or "us")


def add_routes(app: web.Application) -> None:
    app.router.add_get("/auth", _handle_page)
    app.router.add_get("/auth/", _handle_page)
    for path in ("/auth/token", "/auth/callback", "/token"):
        app.router.add_post(path, _handle_token)


async def _handle_page(request: web.Request) -> web.Response:
    config = request.app["config"]
    storefront = (request.query.get("sf") or config.storefront or "us").lower()
    return web.Response(text=_page(storefront), content_type="text/html")


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
    config.update(
        media_user_token=user_token,
        media_user_token_ts=int(time.time()),
        storefront=storefront,
    )
    _LOGGER.info("Stored media-user-token (storefront hint=%s)", storefront or "?")

    # verify against Apple and pin the authoritative storefront
    try:
        catalog._storefront = None
        sf = await catalog.storefront()
        _LOGGER.info("Apple Music connected, storefront=%s", sf)
        return web.json_response({"status": "ok", "storefront": sf})
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Token stored but verification failed: %s", err)
        if storefront:
            return web.json_response(
                {
                    "status": "ok",
                    "storefront": storefront,
                    "warning": f"could not verify with Apple ({err}); "
                    f"using the country you entered ({storefront}).",
                }
            )
        return web.json_response(
            {"error": f"token rejected by Apple: {err}"}, status=502
        )
