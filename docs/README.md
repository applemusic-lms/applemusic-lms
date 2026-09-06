# Setup guide

Install the plugin, then supply a Widevine CDM. The plugin fetches the helper binary
and a modern ffmpeg itself.

---

## 1. Widevine CDM

Apple Music's web streams are Widevine‑encrypted. You must supply your own **L3 CDM** —
nothing is bundled.

You need either:

- a single **`device.wvd`** file, or
- a **`client_id.bin`** + **`private_key.pem`** pair.

These come from a Widevine L3 device. Put the file(s) somewhere the LMS server can read
(e.g. next to your LMS config).

---

## 2. Install the plugin

**Settings → Manage Plugins → Additional Repositories**, add:

```
https://github.com/applemusic-lms/applemusic-lms/releases/latest/download/repo.xml
```

Install **Apple Music**, restart LMS.

On first start the plugin downloads, for your platform, from the GitHub release:
`applemusic-helper` (~18 MB) and a static `ffmpeg` ≥ 7 (~30 MB), into
`<LMS cache>/applemusic-helper/bin/`. Watch **Settings → Advanced → Apple Music** — the
Helper panel shows `downloading binary…` then `running`.

### No outbound internet / airgapped

Put the two binaries in `<LMS cache>/applemusic-helper/bin/` yourself
(`applemusic-helper` and `ffmpeg`, both `chmod +x`) — the plugin skips the downloads.
Get them from the [releases page](https://github.com/applemusic-lms/applemusic-lms/releases).

---

## 3. Configure

**Settings → Advanced → Apple Music**:

- **CDM** — the `selectFile` fields: point at your `.wvd`, or the
  `client_id.bin` + `private_key.pem` pair.
- **ffmpeg** — *Download automatically* (default). Or *System ffmpeg* if you have
  ≥ 6.1 on `PATH`, or *Custom path*.
- **Audio delivery** — FLAC (helper decodes) or AAC (passthrough, LMS transcodes).
- Buttons: **Start / Stop / Restart** the helper, **Reload config & CDM** (re‑reads
  the CDM without a restart).

Saving a CDM/ffmpeg change restarts the helper automatically.

---

## 4. Sign in

The helper serves a sign‑in page. From a browser **on your LAN**:

```
http://<LMS-HOST>:9863/auth
```

The helper binds `127.0.0.1` only. From a machine that isn't the LMS host, tunnel:

```bash
ssh -L 9863:127.0.0.1:9863 <you>@<LMS-HOST>
# then open http://localhost:9863/auth
```

The page tells you to paste your **media‑user‑token** from a signed‑in
`music.apple.com` tab (`copy(MusicKit.getInstance().musicUserToken)` in its console) and
your country code. It's written into the helper's `config.json`. Re‑do this every ~6
months.

---

## Troubleshooting

| Symptom | Check |
|---|---|
| Helper panel stuck on "downloading" | LMS host can reach `github.com`? See airgapped note above. `<cache>/applemusic-helper/helper.log` |
| "needs ≥ 6.1" next to ffmpeg | Auto‑download failed, or System ffmpeg too old — switch to Auto, Restart |
| "No Widevine CDM configured" | CDM paths correct & readable by the LMS user; **Reload config & CDM** |
| Tracks 401 / "sign in again" | media‑user‑token expired — redo step 4 |
| Playback "license" errors | CDM revoked — new CDM |
| Everything 502 after months | Apple changed the web player — check for a plugin update |

Debug: **Settings → Advanced → Logging** → `plugin.applemusic` = DEBUG; helper log is at
`<LMS cache>/applemusic-helper/helper.log`.
