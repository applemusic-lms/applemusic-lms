# applemusic-helper

Local sidecar that does everything the Apple Music LMS plugin can't do in Perl:
the Apple Music API, MusicKit browser sign-in, Widevine license exchange
(`pywidevine`), and `ffmpeg` decrypt → FLAC/AAC.

**Licence: GPL-3.0-only** (it links `pywidevine`). Portions adapted from
[Music Assistant](https://github.com/music-assistant/server) (Apache-2.0) — see
[`NOTICE`](NOTICE).

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
APPLEMUSIC_HELPER_CONFIG=./dev-config.json .venv/bin/python -m applemusic_helper --log-level DEBUG
```

Then `curl -s localhost:9863/health | jq`. See [`../docs/README.md`](../docs/README.md)
for the CDM, sign-in, and deployment steps, and
[`../docs/DEVELOPING.md`](../docs/DEVELOPING.md) for internals.

## Config

JSON file (path from `--config` or `$APPLEMUSIC_HELPER_CONFIG`, default
`~/.config/applemusic-helper/config.json`). Created with defaults on first run.
Key fields:

| key | meaning |
|---|---|
| `bind_host` / `bind_port` | listen address (default `127.0.0.1:9863`) |
| `public_url` | external origin for the sign-in redirect, if not `http://host:port` |
| `cdm_wvd_path` | path to a `.wvd` device file (relative → next to the config) |
| `cdm_client_id_path` / `cdm_private_key_path` | alternative to `.wvd` |
| `audio_format` | `flac` (decode) or `aac` (passthrough) |
| `developer_token` + `developer_token_manual` | pin a developer JWT instead of scraping |
| `media_user_token` / `storefront` | written by the sign-in flow |

## HTTP API (all JSON unless noted)

| route | notes |
|---|---|
| `GET /health` | token/CDM/storefront status |
| `GET /auth` · `POST /auth/callback` | MusicKit sign-in page + capture |
| `POST /cdm/reload` | re-read config + CDM files |
| `GET /search?q=&types=&limit=` | catalog search |
| `GET /meta/track/<id>` · `GET /meta/tracks?ids=` | track metadata |
| `GET /meta/{album,artist,playlist}/<id>` | item detail |
| `GET /album/<id>/tracks` · `/playlist/<id>/tracks` · `/artist/<id>/tracks` · `/artist/<id>/albums` | listings |
| `GET /library/{playlists,albums,artists,songs}` | the user's library |
| `GET /recommendations` · `GET /stations` | discovery rows / radio |
| `GET /stream/<catalogId>?seek=<sec>` | decrypted audio (`audio/flac` or `audio/aac`) |
