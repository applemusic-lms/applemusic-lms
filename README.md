# Apple Music for Lyrion Music Server (unofficial)

Stream your personal **Apple Music** subscription to Squeezebox / Joggler / Squeezelite
players through [Lyrion Music Server](https://lyrion.org) (LMS).

> **Unofficial.** Not affiliated with or endorsed by Apple. It drives the Apple Music
> *web player* interface, which Apple can change or break at any time.

## Install

1. In LMS: **Settings → Manage Plugins → Additional Repositories**, add
   `https://github.com/applemusic-lms/applemusic-lms/releases/latest/download/repo.xml`
2. Install **Apple Music**, restart LMS.
3. **Settings → Advanced → Apple Music**:
   - **CDM** — point at your own Widevine L3 CDM (`device.wvd`, or a
     `client_id.bin` + `private_key.pem` pair). Nothing DRM‑related is bundled.
   - **ffmpeg** — leave on *Download automatically*.
   - Click **sign in** and complete Apple's login (see
     [`docs/README.md`](docs/README.md#3-sign-in) for headless boxes).

The plugin downloads the helper binary and a modern static ffmpeg for your platform on
first run (~50 MB, once).

## How it works

| Part | Language | Job |
|------|----------|-----|
| **`plugin/`** — `Plugins::AppleMusic` | Perl (in LMS) | menus, search, protocol handler, settings, manages the helper process |
| **`helper/`** — `applemusic-helper` | Python (localhost sidecar) | Apple Music API, MusicKit sign‑in, Widevine license, ffmpeg decrypt → FLAC |

```
LMS  ──HTTP──>  applemusic-helper (127.0.0.1)  ──HTTPS──>  Apple Music
```

## Requirements

- An **Apple Music subscription** (not just an Apple ID).
- **LMS 8.0+** with transcoding enabled.
- A **Widevine L3 CDM** you provide yourself — see
  [`docs/README.md`](docs/README.md#1-widevine-cdm).
- Outbound HTTPS from the LMS host to `github.com` for the one‑time download (or place
  the binaries manually — see docs).

## Limitations

- **256 kbps AAC only.** Lossless / hi‑res / Atmos need Apple's FairPlay DRM (Apple
  hardware only). This path is Widevine, same ceiling as the web player.
- One Apple Music stream at a time per account.
- Breaks when Apple changes the web player. Token refresh roughly every ~6 months.

## Licence

- `plugin/` and everything else — **GPL‑2.0‑or‑later** (see [`LICENSE`](LICENSE)).
  GPL‑2‑or‑later so it can combine with GPL‑2‑only Lyrion Music Server *and* the
  GPL‑3 helper.
- `helper/` — **GPL‑3.0‑only** (it links `pywidevine`; see [`helper/LICENSE`](helper/LICENSE)).

Portions of the helper are adapted from
[Music Assistant](https://github.com/music-assistant/server) (Apache‑2.0) — see
[`helper/NOTICE`](helper/NOTICE).
