"""aiohttp application wiring the helper together.

SPDX-License-Identifier: GPL-3.0-only
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any

import aiohttp
from aiohttp import web

from . import __version__, auth
from .apple_api import AppleApiError, AppleMusicApi, NotAuthenticated, NotFound
from .catalog import Catalog
from .config import Config
from .developer_token import token_is_fresh
from .stream import StreamError, StreamResolver
from .widevine import CdmError, WidevineClient

_LOGGER = logging.getLogger(__name__)

routes = web.RouteTableDef()


# ---------------------------------------------------------------------- health
@routes.get("/health")
async def health(request: web.Request) -> web.Response:
    config: Config = request.app["config"]
    api: AppleMusicApi = request.app["api"]
    widevine: WidevineClient = request.app["widevine"]

    dev_ok = bool(config.developer_token) and token_is_fresh(config.developer_token)
    if not dev_ok:
        try:
            await api.developer_token()
            dev_ok = True
        except AppleApiError:
            dev_ok = False

    user_ok = False
    storefront = config.storefront
    if config.media_user_token:
        try:
            storefront = await request.app["catalog"].storefront()
            user_ok = True
        except NotAuthenticated:
            user_ok = False
        except AppleApiError as err:
            _LOGGER.debug("health storefront check failed: %s", err)

    ff_path = config.ffmpeg
    ff_ver = _ffmpeg_version(ff_path)
    ff_downloading = bool(request.app.get("ffmpeg_downloading"))
    ff_ok = _ffmpeg_recent(ff_ver)

    return web.json_response(
        {
            "status": "ok"
            if (dev_ok and user_ok and widevine.available and ff_ok)
            else "degraded",
            "version": __version__,
            "developer_token_ok": dev_ok,
            "user_token_ok": user_ok,
            "cdm_ok": widevine.available,
            "cdm_status": widevine.status,
            "storefront": storefront,
            "audio_format": config.audio_format,
            "auth_url": f"{config.effective_public_url}/auth",
            "config_path": str(config.path),
            "ffmpeg_source": config.ffmpeg_source,
            "ffmpeg_path": ff_path,
            "ffmpeg_version": "downloading…" if ff_downloading else ff_ver,
            "ffmpeg_ok": ff_ok,
            "ffmpeg_downloading": ff_downloading,
            "pid": os.getpid(),
        }
    )


def _ffmpeg_recent(version_str: str) -> bool:
    m = re.search(r"(\d+)\.(\d+)", version_str or "")
    return bool(m) and (int(m.group(1)), int(m.group(2))) >= (6, 1)


_FFMPEG_VERSION_CACHE: dict[str, str] = {}


def _ffmpeg_version(path: str) -> str:
    if path in _FFMPEG_VERSION_CACHE:
        return _FFMPEG_VERSION_CACHE[path]
    try:
        out = subprocess.run(
            [path, "-version"], capture_output=True, text=True, timeout=5
        ).stdout
        first = out.splitlines()[0] if out else ""
        # "ffmpeg version 7.0.2-static ..." -> "7.0.2-static"
        parts = first.split()
        ver = parts[2] if len(parts) >= 3 and parts[0] == "ffmpeg" else (first or "unknown")
    except (OSError, subprocess.SubprocessError, IndexError):
        ver = "not found"
    _FFMPEG_VERSION_CACHE[path] = ver
    return ver


@routes.post("/cdm/reload")
async def cdm_reload(request: web.Request) -> web.Response:
    request.app["config"] = Config.load(request.app["config"].path)
    request.app["widevine"].reload()
    return web.json_response({"cdm_ok": request.app["widevine"].available,
                              "cdm_status": request.app["widevine"].status})


# ---------------------------------------------------------------------- browse
def _require_auth(request: web.Request) -> None:
    if not request.app["config"].media_user_token:
        raise web.HTTPUnauthorized(text="not signed in to Apple Music - open /auth")


@routes.get("/search")
async def search(request: web.Request) -> web.Response:
    _require_auth(request)
    term = request.query.get("q", "").strip()
    if not term:
        raise web.HTTPBadRequest(text="missing q")
    types = [t for t in request.query.get("types", "").split(",") if t]
    limit = int(request.query.get("limit", "25"))
    return web.json_response(await request.app["catalog"].search(term, types, limit))


@routes.get("/meta/tracks")
async def meta_tracks(request: web.Request) -> web.Response:
    _require_auth(request)
    ids = [i for i in request.query.get("ids", "").split(",") if i]
    return web.json_response({"tracks": await request.app["catalog"].get_tracks(ids)})


@routes.get("/meta/track/{item_id}")
async def meta_track(request: web.Request) -> web.Response:
    _require_auth(request)
    ids = request.query.get("ids")
    catalog: Catalog = request.app["catalog"]
    if ids:
        return web.json_response({"tracks": await catalog.get_tracks(ids.split(","))})
    return web.json_response(await catalog.get_track(request.match_info["item_id"]))


@routes.get("/meta/{kind}/{item_id}")
async def meta_item(request: web.Request) -> web.Response:
    _require_auth(request)
    kind = request.match_info["kind"]
    item_id = request.match_info["item_id"]
    catalog: Catalog = request.app["catalog"]
    fn = {
        "album": catalog.get_album,
        "artist": catalog.get_artist,
        "playlist": catalog.get_playlist,
    }.get(kind)
    if not fn:
        raise web.HTTPNotFound(text=f"unknown kind {kind}")
    return web.json_response(await fn(item_id))


@routes.get("/album/{item_id}/tracks")
async def album_tracks(request: web.Request) -> web.Response:
    _require_auth(request)
    return web.json_response(
        {"tracks": await request.app["catalog"].get_album_tracks(request.match_info["item_id"])}
    )


@routes.get("/playlist/{item_id}/tracks")
async def playlist_tracks(request: web.Request) -> web.Response:
    _require_auth(request)
    return web.json_response(
        {"tracks": await request.app["catalog"].get_playlist_tracks(request.match_info["item_id"])}
    )


@routes.get("/artist/{item_id}/tracks")
async def artist_tracks(request: web.Request) -> web.Response:
    _require_auth(request)
    return web.json_response(
        {"tracks": await request.app["catalog"].get_artist_top_tracks(request.match_info["item_id"])}
    )


@routes.get("/artist/{item_id}/albums")
async def artist_albums(request: web.Request) -> web.Response:
    _require_auth(request)
    return web.json_response(
        {"albums": await request.app["catalog"].get_artist_albums(request.match_info["item_id"])}
    )


@routes.get("/library/{kind}")
async def library(request: web.Request) -> web.Response:
    _require_auth(request)
    kind = request.match_info["kind"]
    if kind not in ("playlists", "albums", "artists", "songs"):
        raise web.HTTPNotFound(text=f"unknown library kind {kind}")
    return web.json_response({"items": await request.app["catalog"].library(kind)})


@routes.get("/recommendations")
async def recommendations(request: web.Request) -> web.Response:
    _require_auth(request)
    return web.json_response({"rows": await request.app["catalog"].recommendations()})


@routes.get("/stations")
async def stations(request: web.Request) -> web.Response:
    _require_auth(request)
    return web.json_response({"items": await request.app["catalog"].stations()})


# ---------------------------------------------------------------------- stream
@routes.get("/stream/{item_id}")
async def stream(request: web.Request) -> web.StreamResponse:
    _require_auth(request)
    item_id = request.match_info["item_id"]
    seek = 0.0
    try:
        seek = max(0.0, float(request.query.get("seek", "0")))
    except ValueError:
        pass

    resolver: StreamResolver = request.app["stream"]
    tmpdir = tempfile.mkdtemp(prefix="am-")
    mp4_path = os.path.join(tmpdir, "enc.mp4")
    try:
        try:
            resolved = await resolver.resolve(item_id)
            size = await resolver.fetch_mp4(resolved, mp4_path)
            _LOGGER.info("stream %s: fetched %d bytes, decrypting", item_id, size)
        except CdmError as err:
            raise web.HTTPServiceUnavailable(text=f"Widevine error: {err}")
        except (StreamError, AppleApiError) as err:
            raise web.HTTPBadGateway(text=f"could not resolve track {item_id}: {err}")

        proc = await resolver.open_ffmpeg(mp4_path, resolved.content_key_hex, seek=seek)
        response = web.StreamResponse()
        response.content_type = resolver.content_type
        response.headers["Cache-Control"] = "no-store"
        await response.prepare(request)

        stderr_task = asyncio.create_task(_drain(proc.stderr))
        try:
            assert proc.stdout is not None
            while True:
                chunk = await proc.stdout.read(64 * 1024)
                if not chunk:
                    break
                await response.write(chunk)
        except (asyncio.CancelledError, ConnectionResetError):
            _LOGGER.debug("client disconnected from stream %s", item_id)
            raise
        finally:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
            stderr = await stderr_task
            if proc.returncode not in (0, None) and stderr:
                _LOGGER.warning(
                    "ffmpeg for %s exited %s: %s", item_id, proc.returncode, stderr[-800:]
                )
        await response.write_eof()
        return response
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


async def _drain(stream: asyncio.StreamReader | None) -> str:
    if stream is None:
        return ""
    data = await stream.read()
    return data.decode("utf-8", "replace")


# ---------------------------------------------------------------------- app
async def _on_startup(app: web.Application) -> None:
    config: Config = app["config"]
    session = aiohttp.ClientSession(raise_for_status=False)
    app["session"] = session
    api = AppleMusicApi(config, session)
    app["api"] = api
    app["catalog"] = Catalog(api)
    app["widevine"] = WidevineClient(config, session)
    app["stream"] = StreamResolver(config, session, app["widevine"])
    app["ffmpeg_downloading"] = False
    app["ffmpeg_task"] = asyncio.create_task(_ensure_ffmpeg(app))
    # warm the developer token but don't fail startup if offline
    try:
        await api.developer_token()
    except AppleApiError as err:
        _LOGGER.warning("Could not obtain developer token at startup: %s", err)


async def _ensure_ffmpeg(app: web.Application) -> None:
    config: Config = app["config"]
    if (config.ffmpeg_source or "auto").lower() != "auto":
        return
    if _ffmpeg_recent(_ffmpeg_version(config.ffmpeg)):
        return
    from . import ffmpeg_fetch

    app["ffmpeg_downloading"] = True
    try:
        path = await asyncio.to_thread(
            ffmpeg_fetch.ensure_ffmpeg, config.dist_url, config.bin_dir
        )
        _FFMPEG_VERSION_CACHE.clear()
        _LOGGER.info("bundled ffmpeg ready at %s", path)
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("could not obtain a static ffmpeg: %s", err)
    finally:
        app["ffmpeg_downloading"] = False


async def _on_cleanup(app: web.Application) -> None:
    task = app.get("ffmpeg_task")
    if task and not task.done():
        task.cancel()
    await app["session"].close()


@web.middleware
async def _error_mw(request: web.Request, handler: Any) -> web.StreamResponse:
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except NotFound as err:
        return web.json_response({"error": str(err)}, status=404)
    except NotAuthenticated as err:
        return web.json_response({"error": str(err)}, status=401)
    except AppleApiError as err:
        _LOGGER.exception("API error on %s", request.path)
        return web.json_response({"error": str(err)}, status=502)


def build_app(config: Config) -> web.Application:
    app = web.Application(middlewares=[_error_mw], client_max_size=1 << 20)
    app["config"] = config
    app.add_routes(routes)
    auth.add_routes(app)
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    return app


def run(config: Config) -> None:
    app = build_app(config)
    web.run_app(app, host=config.bind_host, port=config.bind_port, print=None)
