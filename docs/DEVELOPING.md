# Developing / internals

## Layout

```
helper/                 Python sidecar (GPL-3.0-only) - all Apple Music logic
plugin/Plugins/AppleMusic/   Perl LMS plugin (GPL-2.0-or-later) - menus, protocol
                             handler, manages the helper process
.github/workflows/release.yml   builds per-platform binaries + release
scripts/                repackage-ffmpeg.sh, gen-repo-xml.sh
deploy/                 optional custom-init.sh for the venv/dev path
```

## Distribution

- **CI (`release.yml`)** builds `applemusic-helper` with PyInstaller for
  `x86_64-linux`, `aarch64-linux`, `arm-linux`, `darwin-{arm64,x86_64}`, `win-x64`
  (entry point `helper/pyinstaller_entry.py` — freezing `__main__.py` directly breaks
  its relative imports). A separate job repackages verified upstream **static ffmpeg**
  per platform (`scripts/repackage-ffmpeg.sh`). **The git tag is the only source
  of truth for the version** — `.github/actions/setver` stamps `v<X.Y.Z>` into
  `install.xml`, `helper/__init__.py` and `pyproject.toml` at build time (the
  committed value is a placeholder `0.0.0`). On a `v*` tag, everything — the zip,
  all binaries, `sha256sums.txt` and `repo.xml` (SHA1 from
  `scripts/gen-repo-xml.sh`) — is attached to a GitHub Release. LMS points at
  `releases/latest/download/repo.xml`.

### Cutting a release

```bash
git tag -a v0.1.1 -m v0.1.1 && git push origin v0.1.1
```

That's it — no file edits. To build a versioned artifact locally:
`bash scripts/set-version.sh 0.1.1` then the usual build.
- **`Helper.pm`** (in LMS) downloads `applemusic-helper-<platform>` +
  `ffmpeg-<platform>.tar.gz` from that release into `<LMS cache>/applemusic-helper/bin/`,
  checked against the release's `sha256sums.txt`, then runs the helper under
  `Proc::Background` (heartbeat-restarts it in `_beat`, kills it in `shutdownPlugin`).
- `Helper.pm` writes `config.json` from prefs (CDM paths, ffmpeg source, port); the
  helper writes the tokens/storefront back into the same file (read-merge-write).

## Helper — local dev

```bash
cd helper
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
APPLEMUSIC_HELPER_CONFIG=./dev-config.json .venv/bin/python -m applemusic_helper --log-level DEBUG
.venv/bin/pytest
.venv/bin/python -m applemusic_helper --selftest    # the plugin's health probe
```

To make the plugin use this instead of the binary: set the **Helper binary override**
pref to `/abs/path/.venv/bin/python -m applemusic_helper`.

### Request flow for playback

1. LMS transcode rule `apm flc` → `curl <helperUrl>/stream/<id> $START$`
   (`$START$` = `-G --data-urlencode seek=<secs>` on a seek — server-side seek).
2. `stream.StreamResolver.resolve`:
   - `POST play.music.apple.com/.../webPlayback` `{"salableAdamId": <id>}` with
     dev-token + media-user-token + `Origin: https://music.apple.com` headers
     → `songList[0]` = `{ assets, "hls-key-server-url" }`
   - pick `assets[*].flavor == "28:ctrp256"` → HLS m3u8 → `_parse_m3u8` → the
     fragmented-MP4 URL (`EXT-X-MAP`) + Widevine key-id (`EXT-X-KEY` `data:` URI)
3. `widevine.WidevineClient.get_content_key` — PSSH → `pywidevine` challenge →
   `POST <hls-key-server-url>` (TLS verify **off**) → license → CONTENT key hex
4. helper downloads the encrypted MP4 itself (aiohttp), then
   `ffmpeg -ss <s> -decryption_key <hex> -i enc.mp4 -c:a flac -f flac pipe:1`
   → streamed to LMS as `audio/flac`.

**ffmpeg must be ≥ 6.1** — 5.1 (Debian) fails Apple's `cenc` / 8-byte-IV with
"subsample size exceeds the packet size left".

### Endpoints Apple can break

- `play.music.apple.com/.../webPlayback` — asset resolution
- the developer-token JWT in `music.apple.com`'s JS bundle
  (`developer_token._BUNDLE_RE` / `_JWT_RE`) — it's an `AMPWebPlay` token,
  origin-locked to `apple.com`, so all server calls send a spoofed `Origin`
- `amp-api.music.apple.com/v1` — catalog/library
- MusicKit JS v3 `js-cdn.music.apple.com/musickit/v3/musickit.js` (sign-in page only)

Manual token override: `developer_token` + `developer_token_manual: true` in config.

## Perl syntax check without LMS

```bash
perl -I <stub-dir> -c plugin/Plugins/AppleMusic/Plugin.pm
```
Stubs needed: `Slim::*`, `Proc::Background`, and `main::{DEBUGLOG,INFOLOG,WEBUI,
TRANSCODING,ISWINDOWS,ISMAC}` constants.

## Not done yet

- Online library importer (`Importer.pm`) so tracks land in the main LMS library.
- `DontStopTheMusic` integration.
- Playlist editing.
- macOS ffmpeg auto-download (no reliable GitHub-hosted static source yet).
