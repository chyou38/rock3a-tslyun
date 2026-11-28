# TSL Sentry Drive · TSL哨兵云盘

> ⚠️ **Legal and risk notice (read first)**
>
> This is a personal open-source hardware project under the MIT License. It is **not affiliated with, authorized, sponsored or endorsed by** Tesla, Inc. or its affiliates. “Tesla” and other marks belong to their owners and are used here only to describe compatible hardware.
>
> The project is intended solely for personal learning, research and backing up data from devices you own. It must **not** be used for commercial operations, regulatory evasion, privacy violations or any unlawful purpose. Vehicle data access, USB device emulation and Wi-Fi hotspot transmission may be regulated in your jurisdiction; you are responsible for compliance and for any vehicle, data or equipment damage or legal consequences.
>
> The software is provided “AS IS”, without any express or implied warranty.

[中文](README.md) | **English**

**V3.2.55** · A virtual Sentry USB drive · 6-camera synchronized playback · SEI driving telemetry · hardware decode/encode · remote single-stream composite · library · watermarked export — for Radxa ROCK 3A (RK3568) only.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.7+](https://img.shields.io/badge/python-3.7%2B-3776AB.svg)](https://www.python.org/)
[![Zero third-party deps](https://img.shields.io/badge/deps-zero-brightgreen.svg)](#features)

Plug a Radxa ROCK 3A (RK3568, 2GB) into the glovebox USB port instead of the factory USB drive: the car keeps recording as usual, and you open a web page over the box's Wi-Fi or a remote connection to review 4 / 6 synchronized camera angles, read the SEI telemetry embedded in the video bitstream frame by frame (gear / speed / accelerator / brake / steering angle / turn signals / Autopilot / GPS), and export clips with a driving-info watermark burned in.

This repository is maintained for exactly one hardware/OS combination: **Radxa official Debian 12 bookworm BSP / kernel 6.1.84-15-rk2410-nocsf / Intel AX200 Wi-Fi card**. The legacy Armbian mainline build (Debian 13 / 6.18.x) remains supported in code, but new deployments and measurements use the BSP. Other boards, routers or NAS devices are not adapted; they will not install or will lack features, and are out of scope.

---

## Current playback strategy (3.0.2)

This release puts “can a remote phone see a stable picture” first: every waiting state is explicit, the player never goes black or shows a giant play button, and the previous clip's frame is never left on the new clip.

### Three playback modes

| Mode | Current behavior |
|---|---|
| **Auto (default)** | LAN / private direct connections use **six native streams**; public internet / Tailscale uses the **server-side composite**. The page decides from `/api/net_kind` and the access address, and you can lock a mode in Settings |
| **Six native streams** | Six independent HEVC streams with per-stream quality, seeking and cross-minute continuation; the most control, but the highest uplink demand |
| **Server-side composite** | The box joins the cameras into one live fMP4, so the phone pulls a single stream — ideal for weak remote links. The first version only supports continuous playback (the seek bar is disabled); if the **first frame does not appear within 20 seconds**, it falls back to six native streams with a toast. Opening another event retries the composite instead of staying on native forever |

Composite quality follows the current setting; original / 1080p are composited at 720p to keep the single stream manageable.

### Quality and waiting behavior

- Qualities: **Original / 1080p / 720p / 480p / 360p**. The main player defaults to Original on a LAN and 360p over the internet / Tailscale; the Sentry overview defaults to 360p. Manual choices are remembered separately for LAN and remote.
- The background pre-warms the first **30 seconds at 360p** for archived cameras; 480p / 720p are filled only while nobody is watching and 360p is idle. Dashcam and near-live clips are not pre-warmed; they transcode on demand.
- If the cache is not ready, the player starts with any lower variant that exists (Original only if none) and switches to the target quality on the next segment or next open; transcoding continues in the background.
- While switching clips / quality, the player keeps the last frame or a blurred thumbnail and shows “buffering / transcoding” in the top-right corner. It never clears the whole grid to black and never shows the white play button.
- If metadata does not arrive within 6 seconds, the request is re-issued (up to two attempts). After about 12 seconds without playback progress, quality steps down: `Original → 1080p → 720p → 480p → 360p`.
- If the lowest 360p still has no picture, the top-right badge becomes a **clickable retry**; the no-progress path also reloads once more after 10 seconds. The last frame / thumbnail stays visible throughout.
- Six native streams switch quality with a 250 ms stagger, so six requests do not hit the uplink at the same instant.

### Live multi-camera panorama

The single “front” view is normal. When you tap “6-camera / 4-camera panorama”, every cell starts at **480p** (single-camera still follows your quality), staggered by 500 ms. Any cell without metadata after 8 seconds is re-mounted once; if the user did not press pause, playback resumes automatically when data arrives. The goal is to get all 4 / 6 cells showing a picture, not just one or two.

---

## Features

| Capability | Details |
|---|---|
| 🗂 Virtual USB drive | **The installer does not create an image by default.** After deployment, open the web UI → **Personalization → Car USB**, then "Device & Storage"; insert any USB disk (whole disk ≥8 GB) → select it → set the virtual-drive percentage → enter its serial number to format and create. It creates a sparse exFAT image pre-populated with `TeslaCam` and exports it through USB Gadget `mass_storage`, coexisting with the network interface and serial console. You can still pre-create during install with `--size`. |
| ⚡ Live view | `tesla-live-sync.py` parses exFAT **read-only** every 15 seconds (no mount, no USB disconnect), so the car writes while the web page reads; new clips usually show up within 15–30 seconds. On BSP no cron sync is needed; only the `*/2` LUN self-heal remains. |
| 📦 Archive & rolling window | Video lands in a separate archive directory (USB data drive on BSP, standalone ext4 `/archive` on legacy Armbian), never fighting the car for the image. `RecentClips` follows the car's rolling buffer and keeps only the last 60 minutes; archive retention for the box-side copies of `SentryClips` / `SavedClips` is configured in **Personalization → Files → Archive** by capacity watermark, with `.pruned` tombstones preventing the "delete → re-copy" loop. |
| 🎬 Playback | By default the grid follows the saved view: 4 angles as 2×2, 6 as 3×2; the camera bar below switches to front / rear / left B-pillar / right B-pillar / single angle and keeps the position. The grid is aligned every second, shares one progress bar, and supports **0.5x / 1x / 2x** speed; playback continues across minute segments and supports cross-segment seeking. **It lands on the minute containing the trigger and starts 5 seconds before it** (red dot in the clip list). The screenshot button saves the current view as PNG and shows where it went. |
| 📊 Telemetry & metadata | Reads the SEI protobuf embedded in the bitstream: gear / speed / accelerator / brake / steering angle / turn signals / Autopilot state / GPS / 3-axis acceleration, updating frame by frame with playback. `event.json` supplies time / city / street / trigger reason / trigger frame. **Parked Sentry clips without SEI hide the telemetry block entirely rather than showing an empty shell.** |
| 🔍 Filtering & preview | Trigger-reason and date chips combine as filters. Deep links via `?ev=` `?date=` `?cat=` `?cam=` `?exp=1`. 📡 The near-live preview sits on the same level as the other categories (one click, no back-navigation) with Original / 1080p / 720p / 480p / 360p quality choice. Storage bars (the virtual drive counts actual written bytes inside the volume, not the sparse image's apparent size; the bar is colour-coded by usage: <30% green / 30–85% blue / >85% red) plus a live sync status. |
| 📶 Quality | See “Quality and waiting behavior” above. Playback offers Original / 1080p / 720p / 480p / 360p (server-side transcode cache, 2 GB cap). **The default is not a fixed 480p**: it is Original on a LAN and 360p over the internet / remote, with manual choices remembered per network. If the cache is not ready, the player starts from an existing lower variant / Original while transcoding continues, and uses the target quality on the next segment or next open. |
| 🎬 Playback mode | Settings → UI & playback offers **Auto / Six native / Server composite**. See “Three playback modes”. Single-camera playback and export are unaffected. |
| 🎞 Export | Single-clip download, zip bundle, or multi-camera composite (2-up 2×1 / 3-up bottom row filled / 4-up 2×2 / **6-up 3×2**). Quality: Original / 720p / 480p / 360p. **Composites take 4:3 cells from the source with no letterboxing** (single-clip Original exports at 1280×960 with the source frame rate). Watermarked exports are always rendered on-device by ffmpeg to H.264 mp4 (+faststart, so WeChat and the photo library accept them directly). The overlay matches the web player (time / location on the left; speed / turn signal / gear / brake / accelerator on the right, plus an **Autopilot steering-wheel icon** that is blue when engaged and grey when not). Clips without driving telemetry (parked Sentry recordings) degrade to time + location only rather than silently dropping the watermark. **The whole path runs on ffmpeg-rockchip** (rkmpp decode + RGA scale + `h264_rkmpp` encode): a 50-second 4K-class source takes ~7 s; a 6-camera 50 s watermarked composite takes ~54 s. |
| 💾 My library | Composite / export outputs land in a persistent library (no longer wiped with the 1–2 h temp dir); the header folder button lets you download, push to Feishu or delete at any time. **Retention is selectable in the web UI from 1 to 180 days (default 7)**, shrinking it cleans expired items immediately, and a background job sweeps every 30 minutes; 20 GB hard cap with day-first, then size-based eviction. |
| 📂 File management | Browse, upload and download on the drive or archive; multi-select batch delete / move / copy / rename (realpath-guarded). One click clears every recording under `TeslaCam/` while keeping the directory structure and leaving Boombox / Wraps alone. Drive management mode reverts to export automatically after 5 minutes idle. |
| 🔔 Feishu push | Direct message (self only) or group bot webhook: a library push sends a **detail card first** (cover from the composite's first frame, time / location / camera (N-up) / duration·size, plus a **“View recording” button** that deep-links to the 6-up split player), followed by the video message with the cover. Live alerts send a trigger-frame cover card or a clip starting 5 s before the trigger, optionally with the driving watermark burned in. Deduplicated, 20-second delay, 3 retries. |
| 🔐 Login protection | `install.sh` generates a random 10-character password (user `admin`) by default. HMAC-signed cookie valid for 30 days plus HTTP Basic. 8 wrong attempts from one IP within 10 minutes returns 429. Settings → Account lets you change the password or sign out. |
| 🌐 Fixed LAN address | The installer tries to install and enable Avahi mDNS and advertises `http://tsl.local` on the LAN (default host name `tsl`; change with `--mdns NAME`), so IP changes do not change the address. LAN only; standard mDNS supports only the `.local` suffix. |
| 🔄 Online update | Multiple sources raced in parallel with a GitHub API fallback; `version.json` uses an Ed25519 signature plus per-file SHA-256 checks, then verifies → backs up → swaps atomically → restarts, with one-click rollback. Settings → Update can switch between **stable `main` / beta `beta`**. Auto-update is on by default, but is deferred while the car is writing the USB drive, live-sync is moving recordings, a network rollback is unconfirmed, or playback / composition is running. |
| 🎨 Personalization | Custom title icon and name (defaults to 「TSL哨兵云盘」), dark / light / auto theme, 4 UI styles (Default / Apple / Claude / Pixel), 10 UI languages, background skins, lock chime (`LockChime.wav`), wraps `Wraps/`. |
| 🛡 Robustness | Journaled ext4 archive, boot-time self-check, service auto-restart, automatic LUN re-attach via `*/2` cron after eject, recovery from power loss. The repo also ships an optional `scripts/tsf-watch.sh`: a 10-second heartbeat with local `/opt/tesla-sentry/watch.log`. It **does not push the CmaFree low-watermark alert to Feishu by default** (0–1 MB is normal on RK3568); set `TSF_WATCH_ALERT_CMA=1` in the service environment to restore it. |

---

## What's new in v3.2.55 (2026-11-28)

- Added `[APP-WS]` diagnostics for WebSocket handshakes: source, auth mode, token presence, reject code, connect/disconnect; tokens are never logged.
- APP settings now show whether WebSocket is connected, plus an opt-in "tokenless on LAN" switch (default off, private/Tailscale sources only; public direct connections still rejected).
- `/api/notify` exposes `app_ws_open` / `app_ws_active` for troubleshooting.
- All 89 tests pass.

## What's new in v3.2.54 (2026-11-28)

- Added a real-time WebSocket channel for the WebToApp APK: `GET /api/app/ws` pushes `title` / `body` / `url` as soon as a Sentry event arrives, instead of waiting for the client's 5-minute polling floor.
- WebSocket uses the independent APP token (`?token=` or `Authorization: Bearer`), replays queued events on connect, and removes delivered events to avoid duplicate notifications.
- The APP settings page now exposes a WebSocket URL with one-click copy. Select WebSocket push in WebToApp and paste that URL; polling remains available as a fallback.
- Added WebSocket frame/handshake/delivery tests; all 89 tests pass.

## What's new in v3.2.53 (2026-11-28)

- Added a WebToApp polling endpoint `GET /api/app/poll`: returns a bare JSON array with `title` / `body` / `url`, and removes delivered items from the queue.
- The App settings polling URL now points to this endpoint; in WebToApp choose **Polling notification** and set the interval to **5 minutes** (the client minimum).
- The original `GET /api/app/notifications` incremental API and `POST /api/app/notifications/ack` remain unchanged for custom clients.
- Fixed WebToApp parsing an object response as an empty notification.

## What's new in v3.2.52 (2026-11-28)

- The web UI now ships a complete PWA setup: `manifest.webmanifest`, 192/512 icons, `theme-color`, `apple-touch-icon` and a minimal service worker, so WebToApp can detect it as a PWA.
- PWA name/short name are “TSL哨兵云” / “哨兵云”; icons reuse the current brand logo without adding or overwriting any user image.
- Both the login page and the main page carry PWA metadata; `manifest.webmanifest`, icons and `sw.js` are reachable without login, so the app can be installed before signing in.
- The service worker caches no HTML, API, `version.json` or media, avoiding stale PWA builds or broken notifications.

## What's new in v3.2.51 (2026-11-28)

- Personalization now has an **App settings** tab: independent App notification toggle, random access token, polling URL and test notification. Feishu can stay enabled at the same time.
- App pending notifications: `GET /api/app/notifications?token=...&after=...` for incremental polling and `POST /api/app/notifications/ack`; WebToApp uses `GET /api/app/poll?token=...` for a bare array (delivered items are dequeued). Both work over Tailscale.
- Sentry / manual-save / watchdog events can be queued for the App, with deep links opening the matching event; WebToApp can consume it with URL polling.
- 82 automated tests pass.

---

## What's new in v3.2.50 (2026-11-28)

- Completed 12 security / runtime audit fixes: signed OTA manifest plus SHA-256 for every published file, unified `--dir` state paths, export/share job-id traversal protection, login `next` injection guard, persisted network rollback, ghost-cluster reclaim journal, pre-body upload caps, Feishu token binding and a bounded login-failure table.
- Auto-update now waits for the car to stop writing the USB drive, live-sync to stop moving recordings, no unconfirmed network rollback and no active playback / composition job; the viewer and live service are not restarted during those windows.
- OTA supports stable `main` / beta `beta` channels. Both are currently v3.2.50; the update page shows the installed manifest notes and no longer presents a stale mirror version as “latest”.
- The box is deployed at v3.2.50 with 78 automated tests passing; the previous build is kept for one-click rollback.

---

## What's new in 3.0.2 (2026-11-26)

- Fixed the stale frozen frame when switching clips: opening a new event / minute segment now clears the reused cells' `hold` state and freeze image, so only the new clip's blurred thumbnail is shown.
- Quality switching no longer leaves only one of six cells playing: every cell gets an explicit `load()`, streams start 250 ms apart, a cell without metadata is re-mounted after 6 seconds (up to two attempts), and after 12 seconds without progress quality steps down — even a manually locked quality.
- The lowest 360p no longer waits forever: the badge becomes a **clickable retry**, and the no-progress path reloads once more after 10 seconds.
- Server composite first-frame timeout relaxed from 8 to **20 seconds**; opening another event retries the composite instead of falling back for the whole session.
- Live 6 / 4-camera panorama: starts at 480p, 500 ms stagger, re-mounts a cell after 8 seconds without metadata, and resumes automatically unless the user paused — all six cells can now show a picture.
- Screenshot now shows “saved to the download folder”; the live status bar only reports “temporarily unreachable” after two consecutive failures, so a single uplink timeout no longer raises a false alarm.
- Removed the inapplicable landscape / portrait button from the player bar.
- The CmaFree low-watermark alert is muted by default; the local log is kept.

---

## V3 baseline (3.0.0, 2026-11-25)

V3 is the first release on the **Radxa official Debian 12 BSP (kernel 6.1.84)** line: hardware acceleration end to end, plus a persistent library.

**Hardware decode / encode**

- The system ffmpeg is replaced by self-built **ffmpeg-rockchip 9.1** (`/opt/rkmpp/bin/ffmpeg|ffprobe`, GPL v3, statically linked libav*); `install.sh` installs it automatically from the bundled `dist/rkmpp` package.
- Every transcode path now runs on hardware: thumbnails, prebuffer (360p first), push clips, in-browser clips, 6-camera composite export; output via `h264_rkmpp`, scaling via `scale_rkrga`.
- Same 29 s 4K-class source: software x264 36 s → GStreamer 11.8 s → **ffmpeg-rkmpp 7.4 s**.
- 6 cameras, 50.6 s, watermarked composite: **54.4 s** (1668×720, peak ~45 °C, 1.5 GB RAM still free). Subtitle burn itself costs only 0.2 s — the bottleneck is decoding the 4K-class sources; **3-way parallel downsampling measured slower (single MPP instance queueing), so it stays sequential**.

**Features**

- Library: outputs persist under `/mnt/tsf-storage/tsf-data/exports`; **My library** in the web UI downloads / pushes / deletes; retention 1–180 days (default 7), swept every 30 minutes in the background, 20 GB hard cap.
- Feishu library push: detail card (time / location / camera (N-up) / duration·size) with cover and a **View recording** button that deep-links to the `?ev=` 6-up split player.
- 6-camera composite enabled (3×2 cells, 1668×720): per-camera RGA downsample + xstack + a single watermark burn.
- New-system cleanup: removed the dead `tesla-sync` cron and `_hw_preview/_rkvdec_nodes` code (BSP has no `/dev/media*`), stats only count ffmpeg, GStreamer wording dropped from the UI.

**System**

- AX200 (`iwlwifi`): Wi-Fi STA + 2.4 GHz hotspot coexist (NetworkManager only owns `end1`; `wlp1s0/ap0` unmanaged, `wpa_supplicant@wlp1s0` + `udhcpc`).
- Hostname, Asia/Shanghai timezone, BSP `pwm-fan` cooling, USB Gadget writing `mass_storage.0/lun.0/file` directly.

---

## Supported device (ROCK 3A only)

This repository is maintained and verified for the **Radxa ROCK 3A (RK3568)** only. Other boards, routers or NAS devices are not adapted; they will not install or will lack features, and are out of scope.

| Item | Measured on this unit |
|---|---|
| Board | Radxa ROCK 3A (RK3568, 4× Cortex-A55) |
| RAM | 2GB (1.9GiB usable) |
| System storage | eMMC 58.3GB (`mmcblk0`, rootfs ~57GB) |
| Data drive | USB 470GB (`sda1`, ext4, mounted at `/mnt/tsf-storage`, holds image / archive / cache) |
| OS | Radxa official Debian 12 bookworm BSP |
| Kernel | `6.1.84-15-rk2410-nocsf` (aarch64, BSP) |
| Wi-Fi | Intel Wi-Fi 6 AX200 (`8086:2723`, iwlwifi) |
| Bluetooth | AX200 integrated USB (`8087:0029`, hci0/hci1 when enumerated) |
| Ethernet | `end1` gigabit, NetworkManager DHCP (legacy Armbian: `end0`) |
| Fan | BSP `pwm-fan` driver (hwmon `pwmfan` / `pwm1`, 25 kHz); old mainline needs the `rock3a-pwm8-fan` overlay |
| USB | USB3 OTG port as Gadget, connected to the car |

**Used**: USB3 OTG (car), `end1` (Ethernet), AX200 (Wi-Fi STA + 2.4 GHz hotspot), Bluetooth, PWM fan header, eMMC (system), USB data drive (image / archive / cache).
**Unused**: HDMI, USB Host, M.2, audio and other ports are not required by this design and stay idle.

**Hard requirements**: non-empty `/sys/class/udc/`, configfs + `USB_F_MASS_STORAGE`, kernel exFAT, loop / losetup, root, and a car USB port that can supply power. The OS must be Debian 12/13 (BSP or Armbian) with systemd; Python 3.7+ (the viewer has zero third-party dependencies); ffmpeg only affects thumbnails and transcoding and does not block installation.

Run the read-only self-check before installing:

```sh
sh scripts/tsf-check.sh          # UDC / configfs / exFAT / Python / init, with a three-colour verdict
sh scripts/tsf-check.sh --json   # machine-readable
```

See [docs/SYSTEM.md](docs/SYSTEM.md) for the full system baseline, dependency versions, service table and network/hotspot configuration.

---

## Installation

**1. Deploy** (run over SSH on the device; the installer **does not create a virtual-drive image**)

```sh
git clone https://github.com/chyou38/rock3a-tslyun.git
cd rock3a-tslyun
sudo ./install.sh                                             # no image; port 80, archive /archive, mDNS tsl.local
sudo ./install.sh --size 120 --port 80 --archive /archive    # optional: pre-create a 120G image
sudo ./install.sh --mdns mybox                                # optional: use http://mybox.local

# BSP single-disk setup (USB data drive at /mnt/tsf-storage): keep archive and cache on it
sudo ./install.sh --archive /mnt/tsf-storage/tsf-data/archive \
                  --cache   /mnt/tsf-storage/tsf-data/cache
```

The installer verifies the board is a ROCK 3A (RK3568) → checks kernel gadget / exFAT / Python → **installs the bundled ffmpeg-rockchip (`dist/rkmpp`, hardware decode/encode; failure is a warning only)** → installs into `/opt/tesla-sentry/`, writes `/etc/tesla-sentry.conf` → tries to install and enable Avahi mDNS → registers `tesla-gadget` / `sentry-viewer` / `tesla-live` / `pwm-fan-control` / `tsf-ap-policy.timer` systemd services and a `*/2` cron for USB LUN self-heal; on NetworkManager (BSP) it also configures `wlp1s0/ap0` as unmanaged, `wpa_supplicant@wlp1s0`, `tsf-wifi-dhcp`, `tsf-bt-name` → generates a random login password → creates the library directory → starts services and prints status. Missing fonts or kernel options are warnings, not fatal. **No image is created by default; choose the disk and capacity in the web UI after installation.**

**2. Open the page and create the virtual drive yourself**: visit `http://<device-ip>` or `http://tsl.local` (phone on the box hotspot, USB Ethernet, or your own Tailscale / frp). First login is `admin`; the password is in the install output or `/opt/tesla-sentry/auth.conf`. Open **Personalization → Car USB**; "Device & Storage" will say "virtual USB drive not configured":

1. Insert the USB disk to use (whole disk ≥8 GB; a USB stick or portable SSD both work, capacity is not fixed).
2. Select the whole disk in the "Select disk" dropdown and drag the "Virtual drive share" slider (10%–90%); the page shows the resulting virtual-drive / archive capacity.
3. Click "Format and create virtual USB drive" and confirm twice (the second confirmation asks for the disk serial number). This erases the whole disk and creates a sparse exFAT image with a `TeslaCam` directory; back up any data first.
4. When done the page refreshes and `tesla-gadget` exports the drive; the status becomes "mounted".

For a virtual drive larger than 128 GB, the system needs `mkfs.exfat` (Debian: `apt install exfatprogs`); smaller drives do not.

**Fixed address (mDNS)**: the installer tries to install and enable Avahi and advertises `http://tsl.local` on the LAN (default host `tsl`; `sudo ./install.sh --mdns mybox` changes it to `http://mybox.local`). This address depends only on mDNS, not on the device IP, so a new network or lease does not change it. Phones, Macs and Linux usually resolve it; on Windows install Bonjour or keep using `http://<device-ip>`. Standard mDNS only supports the `.local` suffix; custom suffixes such as `.cot` are not treated as mDNS by normal clients.

**3. Plug it into the car**: connect the USB3 OTG port to the glovebox USB port. The car recognises the virtual drive and starts recording. The image is pre-populated with `TeslaCam/{RecentClips,SavedClips,SentryClips,EncryptedClips}`; normally you do not need to tap "Format USB device" again. If the car still asks, confirming is harmless.

**Uninstall**

```sh
sudo ./uninstall.sh              # stop services, remove program and cache; keep image and archive
sudo ./uninstall.sh --purge      # also delete image and archive (irreversible)
```

---

## RKMPP hardware decode / encode (required on BSP)

The BSP kernel exposes `/dev/mpp_service` and `/dev/rga`; the repo ships a self-built ffmpeg-rockchip bundle (GPL v3, statically linked libav*):

- `dist/rkmpp/rkmpp-bin.tar.gz`: `ffmpeg` / `ffprobe` binaries (~21 MB, stripped)
- `dist/rkmpp/install-rkmpp.sh`: restore script; checks runtime dependencies, symlinks system `ffmpeg`/`ffprobe`, writes `TSF_FFMPEG` / `TSF_FFPROBE`
- `dist/rkmpp/deps.txt`: runtime dependency list (Debian 12)

`install.sh` automatically calls `install-rkmpp.sh -y` when `/opt/rkmpp/bin/ffmpeg` is missing. Manually:

```sh
cd dist/rkmpp
sudo bash install-rkmpp.sh -y      # installs missing dependencies via apt
sudo systemctl restart sentry-viewer
```

After installation, `ffmpeg -encoders | grep rkmpp` should list `h264_rkmpp`/`hevc_rkmpp`, and `-filters | grep rkrga` should list `scale_rkrga`. A mainline kernel without `/dev/mpp_service` can only use software decoding; hardware acceleration is unavailable.

---

## Configuration and common settings

Main configuration: `/etc/tesla-sentry.conf` (restart services after changes).

| Variable | Default | Purpose |
|---|---|---|
| `TSF_IMG` / `TSF_ARCHIVE` | `/opt/tesla-sentry/teslacam.img` / `/archive` | Virtual USB image / archive; the BSP single-disk setup uses `/mnt/tsf-storage/tsf-data/teslacam.img` / `.../archive` |
| `TSF_PORT` | `80` | Web port |
| `TSF_LIVE_INTERVAL` | `15` | Read-only live sync interval (seconds) |
| `TSF_IDLE` | `600` | Image idle seconds, only used by the cron job that mounts it to write Boombox audio |
| `TSF_RECENT_ROLL_MIN` | `60` | RecentClips rolling window (minutes); 0 = no rolling |
| `TSF_BOX_KEEP_DAYS` / `TSF_BOX_MAX_GB` | `0` / `0` | Legacy plan-B box-side retention days / per-category cap; off by default. Archive retention is configured in Personalization → Files → Archive |
| `TSF_FREE_MIN_MB` / `TSF_FREE_TARGET_MB` | `4096` / `10240` | Free-space cleanup trigger and target |
| `TSF_CACHE` | `<install dir>/cache` | Thumbnail / telemetry / composite temp cache; BSP uses `/mnt/tsf-storage/tsf-data/cache` |
| `TSF_LIB` | `/mnt/tsf-storage/tsf-data/exports` | Library directory (composites / exports); retention is changed in My Library (1–180 days, stored as `lib_ttl_days` in `settings.json`), 20 GB hard cap |
| `TSF_VPU_TRANSCODE_ON` / `TSF_TR_CODES` | `1` / `3` | Hardware transcode switch / concurrency; RK3568 has one hardware encoder instance, 3 is the long-term measured balance |
| `TSF_PREVIEW_CACHE` | `/opt/tesla-sentry/preview-cache` | Prebuffer cache; defaults to eMMC, recommended on the data drive (`/mnt/tsf-storage/tsf-data/preview-cache`) |
| `TSF_PREWARM` | `1` | Background prewarm switch; `0` disables it and transcodes on demand |
| `TSF_MDNS_NAME` | `tsl` | mDNS host name for `http://tsl.local`; restart avahi-daemon after changing |

OTA, Feishu push and authentication parameters are **not** in this conf; they come from environment variables (such as `TSF_OTA_SOURCES`, `TSF_OTA_REPO`) or the web UI. See `docs/SYSTEM.md` for the full variable list and system baseline.

**⚙ Personalization** includes network, files, Car USB, lock chime, wraps, push, account, language, background, fan, branding and update pages. Disk selection and virtual-drive creation live in **Personalization → Car USB**, not on the home page.

- **Branding**: Settings → Branding; the header icon (png/jpg/webp, ≤3 MB) and name (≤24 characters) can be replaced, effective immediately and on the login page; the built-in 「TSL哨兵云盘」 icon and name can be restored with one click.
- **Online update**: Settings → Update compares the repo's `version.json`; one-click upgrade / rollback. Configuration and recordings are not part of the update.
- **Feishu push**: Settings → Push; use a self-built app for a direct message (self only) or a group bot webhook. Covers and trigger-camera clips are supported; send a test first.
- **Authentication**: credentials live in `/opt/tesla-sentry/auth.conf` (mode 600); deleting the file and restarting disables authentication (trusted LAN only).
- **Drive management mode**: "Connect car USB" temporarily stops export and mounts the image; it reverts after 5 minutes idle. Do not leave it mounted while Sentry / driving recording is active.
- **Lock chime**: WAV, 44.1 kHz, 16-bit, <1 MB, 1–5 seconds, named `LockChime.wav` in the drive root.
- **API**: dozens of endpoints for events, media, telemetry, upload, file management, OTA and push; `do_GET` / `do_POST` / `do_DELETE` in `sentry-viewer.py` are authoritative.

Restart services after changing configuration:

```sh
systemctl restart sentry-viewer
systemctl restart tesla-live
systemctl restart tesla-gadget
```

---

## Troubleshooting

- **Car does not recognise the drive / asks to format**: confirm `/sys/class/udc/` has a controller and `grep exfat /proc/filesystems` returns a line, then run `/opt/tesla-sentry/tesla-gadget.sh status`. New deployments do not pre-create an image: create it in **Personalization → Car USB** first. A successful creation pre-populates exFAT + `TeslaCam`, so the car should not ask again. An all-zero blank image left by an old install is repaired automatically on reinstall. A virtual drive over 128 GB (the addressing limit of the car's layout) needs `mkfs.exfat` (`apt install exfatprogs`); otherwise it falls back to a blank drive the car formats once. To repair manually: `python3 /opt/tesla-sentry/mkexfat.py <image> <capacityGB>` (it refuses to overwrite an image that contains data).
- **Black playback**: the video is H.265 / HEVC. Edge / Chrome on Windows need a HEVC decoder; iPhone Safari supports it natively; some Android browsers do not. On a weak remote link prefer “Server-side composite” (Settings → UI & playback), which pulls a single stream.
- **No events in the page**: check `/opt/tesla-sentry/tesla-live.log` and `journalctl -u sentry-viewer -n 50 --no-pager`; confirm the sync status capsule is online, then check the archive path and image path.
- **Quality switch takes a long time**: the first switch to an uncached 480p / 720p requires on-box transcoding, and six native streams appear one by one. The waiting state keeps the last frame / blurred thumbnail and shows a status. For a quick view stay on 360p or use the single-stream composite.
- **360p still has no picture**: the top-right badge is a retry button; tap it to reload the current segment. If it keeps failing, check box load and storage (`uptime`, `df -h`, `systemctl status sentry-viewer`).

### Update check fails (cannot reach GitHub)

On some networks `raw.githubusercontent.com` and some mirrors are reset or TLS-interfered, and third-party mirrors come and go, so "Check for updates" occasionally reports **all sources unavailable**. Since 2.8.13:

- Multiple sources (`ghfast.top`, `fastly.jsdelivr.net`, `testingcf.jsdelivr.net`, `gcore.jsdelivr.net`, `ghproxy.net`, `gh-proxy.org`, `gh-proxy.com`, raw, jsDelivr) are **raced in parallel**; any one working is enough, instead of waiting for each in order.
- The error lists every failed source and its reason (timeout / connection blocked / certificate hijack / DNS failure), so you can tell whether it is the firewall or a dead mirror.
- Auto-update is on by default and retries every 5 minutes after the network recovers; it will not upgrade while the car is writing the USB drive, live-sync is moving recordings, a network rollback is unconfirmed, or playback / composition is running.

To add your own source, write the usable mirrors into the config (comma-separated, `https://domain/<repo-path>/main`):

```bash
echo 'TSF_OTA_SOURCES=https://ghfast.top/https://raw.githubusercontent.com/chyou38/rock3a-tslyun/main,https://gcore.jsdelivr.net/gh/chyou38/rock3a-tslyun@main' >> /etc/tesla-sentry.conf
systemctl restart sentry-viewer
```

**Old versions (2.8.12 and earlier) cannot even check and cannot enter the update page**: overwrite once manually on the device; automatic updates work afterwards.

```bash
wget -O /tmp/sv.py https://ghfast.top/https://raw.githubusercontent.com/chyou38/rock3a-tslyun/main/sentry-viewer.py \
  || wget -O /tmp/sv.py https://gcore.jsdelivr.net/gh/chyou38/rock3a-tslyun@main/sentry-viewer.py
python3 -m py_compile /tmp/sv.py && cp /tmp/sv.py /opt/tesla-sentry/sentry-viewer.py \
  && chmod 755 /opt/tesla-sentry/sentry-viewer.py && systemctl restart sentry-viewer
```

### Watermark selected but missing from the export

On-device watermarking (`ffmpeg` + libass) needs a **Chinese font**. In 2.8.18 and earlier, a missing font silently skipped the whole subtitle chain — the export succeeded but had no text. Since 2.8.19:

- The export panel shows the “watermark font” status; when missing it offers **Install font** (one click from the official `google/fonts` repo, ~17 MB, multiple mirrors) and **Upload** (local ttf/otf).
- Export is blocked with a clear message when the font is missing, instead of producing an unwatermarked video.
- Font detection also scans system font directories outside `/opt/tesla-sentry/fonts`, so a box with fonts already installed works immediately after upgrading.

Manual font installation (copy from another machine if there is no internet):

```bash
mkdir -p /opt/tesla-sentry/fonts
wget -O /opt/tesla-sentry/fonts/NotoSansSC.ttf \
  "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf" \
  || wget -O /opt/tesla-sentry/fonts/NotoSansSC.ttf \
  "https://ghfast.top/https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf"
ls -l /opt/tesla-sentry/fonts/     # should be ~17 MB
systemctl restart sentry-viewer
```

### Watchdog script (optional)

The repo ships `scripts/tsf-watch.sh`: it samples USB / memory / temperature / service state every 10 seconds and writes anomalies to `/opt/tesla-sentry/watch.log`; optional Feishu alerts go through the viewer loopback endpoint and reuse the push configuration. **CmaFree low-watermark alerts are off by default** (0–1 MB is normal on RK3568); set `TSF_WATCH_ALERT_CMA=1` in the systemd environment to restore them.

---

## Security notes

- `install.sh` enables site-wide login protection by default. **Running `python3 sentry-viewer.py` directly without `auth.conf` disables authentication**; use it only on a trusted LAN. Deleting `auth.conf` is still the "disable auth" switch, but if the file exists and no password can be read, the service **refuses to start** instead of running unprotected.
- The login page and HTTP Basic share the rate limit: 8 wrong attempts from one IP within 10 minutes locks it for 5 minutes; Basic cannot bypass it.
- Uploads are limited to 100 MB, ordinary JSON bodies to 1 MB, per-connection read/write timeout 30 seconds, and 48 concurrent threads; paths are confined to the archive / image mount and cannot escape to system directories.
- Authentication and cookies use plain HTTP; use HTTPS or a VPN for public access. A reverse proxy should send `X-Forwarded-Proto: https` (or set `TSF_COOKIE_SECURE=1`), and the login cookie will carry `Secure`.

## Disclaimer

This is a personal hobby project, unrelated to Tesla, Inc. Modifying the car's storage behaviour carries risk (data loss, interrupted recording); evaluate it yourself and validate with a small image first.

## References and acknowledgements

- [teslausb](https://github.com/marcone/teslausb) — the pioneer of Raspberry Pi USB-drive emulation and archiving; the original inspiration
- [SentryBox](https://github.com/weitanism/sentrybox) — a productised always-on car device
- [tesla-sentry-viewer](https://github.com/denysvitali/tesla-sentry-viewer) — reference for the web viewer form factor

## License

[MIT](LICENSE)
