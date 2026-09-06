"""Entry point: `python -m applemusic_helper`.

SPDX-License-Identifier: GPL-3.0-only
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__
from .config import DEFAULT_CONFIG_PATH, Config
from .server import run


def _selftest() -> int:
    """Prove the (possibly frozen) binary is functional. Used by the LMS plugin
    as its health probe, like `spotty --check`."""
    try:
        import aiohttp  # noqa: F401
        from pywidevine import Cdm, Device  # noqa: F401

        print(f"ok applemusic-helper v{__version__} (pywidevine ok)")
        return 0
    except Exception as err:  # noqa: BLE001
        print(f"fail applemusic-helper v{__version__}: {type(err).__name__}: {err}")
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="applemusic-helper", description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG_PATH, help="path to config.json"
    )
    parser.add_argument("--host", help="override bind_host")
    parser.add_argument("--port", type=int, help="override bind_port")
    parser.add_argument("--log-level", help="override log_level (DEBUG/INFO/WARNING)")
    parser.add_argument(
        "--dist-url",
        help="base URL for downloading the bundled ffmpeg (a GitHub release)",
    )
    parser.add_argument(
        "--selftest", action="store_true", help="check the runtime and exit"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()

    config = Config.load(args.config)
    if args.host:
        config.bind_host = args.host
    if args.port:
        config.bind_port = args.port
    if args.log_level:
        config.log_level = args.log_level
    if args.dist_url:
        config.dist_url = args.dist_url

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if config.log_file:
        try:
            handlers.append(logging.FileHandler(config.log_file, encoding="utf-8"))
        except OSError as err:
            print(f"cannot open log file {config.log_file}: {err}", file=sys.stderr)
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
    )
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

    log = logging.getLogger("applemusic_helper")
    log.info("applemusic-helper %s", __version__)
    log.info("config: %s", config.path)
    log.info("listening on http://%s:%s", config.bind_host, config.bind_port)
    if not config.cdm_configured():
        log.warning("no Widevine CDM configured - catalog playback will not work yet")
    if not config.media_user_token:
        log.warning("not signed in - open %s/auth", config.effective_public_url)

    try:
        run(config)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
