# TSL Sentry Drive · TSL哨兵云盘

> ⚠️ **Legal and risk notice (read first)**
>
> This is a personal open-source hardware project under the MIT License. It is **not affiliated with, authorized, sponsored or endorsed by** Tesla, Inc. or its affiliates. “Tesla” and other marks belong to their owners and are used here only to describe compatible hardware.
>
> The project is intended solely for personal learning, research and backing up data from devices you own. It must **not** be used for commercial operations, regulatory evasion, privacy violations or any unlawful purpose. Vehicle data access, USB device emulation and Wi-Fi hotspot transmission may be regulated in your jurisdiction; you are responsible for compliance and for any vehicle, data or equipment damage or legal consequences.
>
> The software is provided “AS IS”, without any express or implied warranty.

[中文](README.md) | **English**

**V3 (3.0.0)** · A virtual Sentry USB drive · 6-camera synchronized playback · SEI driving telemetry · hardware decode/encode · library · watermarked export — for Radxa ROCK 3A (RK3568) only.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.7+](https://img.shields.io/badge/python-3.7%2B-3776AB.svg)](https://www.python.org/)
[![Zero third-party deps](https://img.shields.io/badge/deps-zero-brightgreen.svg)](#features)

Plug a Radxa ROCK 3A (RK3568, 2GB) into the glovebox USB port instead of the factory USB drive: the car keeps recording as usual, and you open a web page over the box's Wi-Fi to review 4 / 6 synchronized camera angles, read the SEI telemetry embedded in the video bitstream frame by frame (gear / speed / accelerator / brake / steering angle / turn signals / Autopilot / GPS), and export clips with a driving-info watermark burned in.

This repository is maintained for exactly one hardware/OS combination: **Radxa official Debian 12 bookworm BSP / kernel 6.1.84-15-rk2410-nocsf / Intel AX200 Wi-Fi card**. The legacy Armbian mainline build (Debian 13 / 6.18.x) remains supported in code, but new deployments and measurements use the BSP. Other boards, routers or NAS devices are not adapted; they will not install or will lack features, and are out of scope.

---

## Features

| Capability | Details |
|---|---|
| 🗂 Virtual USB drive | **The installer does not create an image by default.** After deployment, open the web UI → **Personalization → Car USB**, then "Device & Storage"; insert any USB disk (whole disk ≥8 GB) → select it → set the virtual-drive percentage → enter its serial number to format and create. It creates a sparse exFAT image pre-populated with `TeslaCam` and exports it through USB Gadget `mass_storage`, coexisting with the network interface and serial console. You can still pre-create during install with `--size`. |
| ⚡ Live view | `tesla-live-sync.py` parses exFAT **read-only** every 15 seconds (no mount, no USB disconnect), so the car writes while the web page reads; new clips usually show up within 15–30 seconds. The `*/10` cron job only writes Boombox audio. |
| 📦 Archive & rolling window | Video lands in a separate archive directory (USB data drive on BSP, standalone ext4 `/archive` on legacy Armbian), never fighting the car for the image. `RecentClips` follows the car's rolling buffer and keeps only the last 60 minutes; archive retention for the box-side copies of `SentryClips` / `SavedClips` is configured in **Personalization → Files → Archive** by capacity watermark, with `.pruned` tombstones preventing the "delete → re-copy" loop. |
| 🎬 Playback | **Single camera by default**: opening an event plays the camera that triggered it (a switcher bar below the player offers front / rear / left B-pillar / right B-pillar / grid — only the selected angle loads, and switching keeps your position). Grid view auto-fits 4 angles as 2×2 and 6 as 3×2, with 250ms sync correction, one shared progress bar and 0.5–4x speed. **Playback lands on the minute containing the trigger and starts 5 seconds before it** (marked with a red dot in the clip list). |
| 📊 Telemetry & metadata | Reads the SEI protobuf embedded in the bitstream: gear / speed / accelerator / brake / steering angle / turn signals / Autopilot state / GPS / 3-axis acceleration, updating frame by frame with playback. `event.json` supplies time / city / street / trigger reason / trigger frame. |
| 🔍 Filtering & preview | Trigger-reason and date chips combine as filters. Deep links via `?ev=` `?date=` `?cat=` `?cam=` `?exp=1`. 📡 The near-live preview sits on the same level as the other categories (one click, no back-navigation) with Original / 720p / 480p / 360p quality choice. Storage bars (the virtual drive counts actual written bytes inside the volume, not the sparse image's apparent size; the bar is colour-coded by usage: <30% green / 30–85% blue / >85% red) plus a live sync status. |
| 📶 Quality | Playback offers original / 720p / 480p / 360p (server-side transcode cache, 2GB cap). **480p is the default** — the same resolution used as the default for Feishu push and export; a single 480p stream starts in 0.08s over the public internet in testing. Manual choices are remembered and preferred next time. When a new Sentry / manually saved event lands, the background transcodes the triggering camera's trigger segment ± adjacent segments to 480p (3 files per event) so it plays instantly — only when nobody is watching. **Dashcam and near-live preview are never pre-transcoded**: those clips are added every minute and scroll away quickly, so the cache would be wasted, and constant transcoding would keep a fanless box pegged and hot. They are transcoded on demand when you actually open them. **A missing cache never makes you wait**: the player starts with any existing lower-quality variant (falling back to the original only if none exists) and switches to the target quality on the next segment or next open, while the transcode runs in the background. |
| 🎞 Export | Single-clip download, zip bundle, or multi-camera composite (2-up 2×1 / 3-up bottom row filled / 4-up 2×2 / **6-up 3×2**). Quality: original / 720p / 480p / 360p. **Composites take 4:3 cells from the source with no letterboxing** (single-clip original exports at 1280×960 with the source frame rate). Watermarked exports are always rendered on-device by ffmpeg to H.264 mp4 (+faststart, so WeChat and the photo library accept them directly). The overlay matches the web player (time / location on the left; speed / turn signal / gear / brake / accelerator on the right, plus an **Autopilot steering-wheel icon** that is blue when engaged and grey when not). Clips without driving telemetry (parked Sentry recordings) degrade to time + location only rather than silently dropping the watermark. **The whole path runs on ffmpeg-rockchip** (rkmpp decode + RGA scale + `h264_rkmpp` encode): a 50-second 4K-class source takes ~7 s; a 6-camera 50 s watermarked composite takes ~54 s. |
| 💾 My library | Composite / export outputs land in a persistent library (no longer wiped with the 1–2 h temp dir); the header folder button lets you download, push to Feishu or delete at any time. **Retention is selectable in the web UI from 1 to 180 days (default 7)**, shrinking it cleans expired items immediately, and a background job sweeps every 30 minutes; 20 GB hard cap with day-first, then size-based eviction. |
| 📂 File management | Browse, upload and download on the drive or archive; multi-select batch delete / move / copy / rename (realpath-guarded). One click clears every recording under `TeslaCam/` while keeping the directory structure and leaving Boombox / Wraps alone. Drive management mode reverts to export automatically after 5 minutes idle. |
| 🔔 Feishu push | Direct message (self only) or group bot webhook: a library push sends a **detail card first** (cover from the composite's first frame, time / location / camera (N-up) / duration·size, plus a **“View recording” button** that deep-links to the 6-up split player), followed by the video message with the cover. Live alerts send a trigger-frame cover card or a clip starting 5 s before the trigger, optionally with the driving watermark burned in. Deduplicated, 20-second delay, 3 retries. |
| 🔐 Login protection | `install.sh` generates a random 10-character password (user `admin`) by default. HMAC-signed cookie valid for 30 days plus HTTP Basic. 8 wrong attempts from one IP within 10 minutes returns 429. Settings → Account lets you change the password or sign out. |
| 🌐 Fixed LAN address | The installer tries to install and enable Avahi mDNS and advertises `http://tsl.local` on the LAN (default host name `tsl`; change with `--mdns NAME`), so IP changes do not change the address. LAN only; standard mDNS supports only the `.local` suffix. |
| 🔄 Online update | Multiple sources raced in parallel with a GitHub API fallback; after download it verifies → backs up → swaps atomically → restarts, with one-click rollback. Settings → Update has an **auto-update** toggle (on by default: upgrades when a new version appears and nobody is watching). |
| 🎨 Personalization | Custom title icon and name (defaults to 「TSL哨兵云盘」), dark / light / auto theme, 4 UI styles (Default / Apple / Claude / Pixel), 10 UI languages, background skins, lock chime (`LockChime.wav`), wraps `Wraps/`. |
| 🛡 Robustness | Journaled ext4 archive, boot-time self-check, service auto-restart, automatic LUN re-attach via `*/2` cron after eject, recovery from power loss. |

---

## V3 changes (3.0.0, 2026-11-25)

V3 is the first release on the **Radxa official Debian 12 BSP (kernel 6.1.84)** line: hardware acceleration end to end, plus a persistent library.

**Hardware decode / encode**

- The system ffmpeg is replaced by self-built **ffmpeg-rockchip 9.1** (`/opt/rkmpp/bin/ffmpeg|ffprobe`, GPL v3, statically linked libav*); `install.sh` installs it automatically from the bundled `dist/rkmpp` package
- Every transcode path now runs on hardware: thumbnails, three-quality prebuffer (360p/480p/720p), push clips, in-browser clips, 6-camera composite export; output via `h264_rkmpp`, scaling via `scale_rkrga`
- Same 29 s 4K-class source: software x264 36 s → GStreamer 11.8 s → **ffmpeg-rkmpp 7.4 s**
- 6 cameras, 50.6 s, watermarked composite: **54.4 s** (1668×720, peak ~45 °C, 1.5 GB RAM still free). Subtitle burn itself costs only 0.2 s — the bottleneck is decoding the 4K-class sources; **3-way parallel downsampling measured slower (single MPP instance queueing), so it stays sequential**

**Features**

- Library: outputs persist under `/mnt/tsf-storage/tsf-data/exports`; **My library** in the web UI downloads / pushes / deletes; retention 1–180 days (default 7), swept every 30 minutes in the background, 20 GB hard cap
- Feishu library push: detail card (time / location / camera (N-up) / duration·size) with cover and a **View recording** button that deep-links to the `?ev=` 6-up split player
- 6-camera composite enabled (3×2 cells, 1668×720): per-camera RGA downsample + xstack + a single watermark burn
- New-system cleanup: removed the dead `tesla-sync` cron and `_hw_preview/_rkvdec_nodes` code (BSP has no `/dev/media*`), stats only count ffmpeg, GStreamer wording dropped from the UI

**System**

- AX200 (`iwlwifi`): Wi-Fi STA + 2.4 GHz hotspot coexist (NetworkManager only owns `end1`; `wlp1s0/ap0` unmanaged, `wpa_supplicant@wlp1s0` + `udhcpc`)
- Hostname, Asia/Shanghai timezone, BSP `pwm-fan` cooling, USB Gadget writing `mass_storage.0/lun.0/file` directly

---

## Supported device (ROCK 3A only)

This repository is maintained and verified for the **Radxa ROCK 3A (RK3568)** only. Other boards, routers or NAS devices are not adapted; they will not install or will lack features, and are out of scope.

| Item | Measured on this unit |
|---|---|
| Board | Radxa ROCK 3A (RK3568, 4× Cortex-A55) |
| RAM | 2GB (1.9GiB usable) |
| System storage | 58.3GB eMMC (`mmcblk0`, ~57GB root partition) |
| Data storage | 470GB USB drive (`sda1`, ext4, mounted at `/mnt/tsf-storage`, holds image/archive/cache) |
| OS | Radxa official Debian 12 bookworm BSP |
| Kernel | `6.1.84-15-rk2410-nocsf` (aarch64, BSP) |
| Wi-Fi card | Intel Wi-Fi 6 AX200 (`8086:2723`, iwlwifi) |
| Bluetooth | AX200 integrated USB (`8087:0029`, normally hci0/hci1) |
| Ethernet | `end1` gigabit, NetworkManager DHCP (legacy Armbian uses `end0`) |
| Fan | BSP `pwm-fan` driver (hwmon `pwmfan` / `pwm1`, 25kHz); legacy mainline needs the `rock3a-pwm8-fan` overlay |
| USB | USB3 OTG port as Gadget, connected to the car |

**Used**: USB3 OTG (car), `end1` (Ethernet), AX200 (Wi-Fi STA + 2.4G hotspot), Bluetooth, PWM fan header, eMMC (system), USB data drive (image/archive/cache).
**Unused**: HDMI, USB host ports, M.2 and audio are not required and stay idle.

**Hard requirements**: non-empty `/sys/class/udc/`, configfs + `USB_F_MASS_STORAGE`, kernel exFAT, loop / losetup, root, and a car USB port that can supply power. Debian 12/13 (BSP or Armbian) systemd is required. Python 3.7+ (the viewer has zero third-party dependencies). ffmpeg only affects thumbnails and transcoding — missing it does not block installation.

Check before installing (read-only, changes nothing):

```sh
sh scripts/tsf-check.sh          # item-by-item UDC / configfs / exFAT / Python / init check, colour-coded verdict
sh scripts/tsf-check.sh --json   # machine-readable, for scripts
```

System versions, package versions, service states and network/hotspot configuration are documented in [docs/SYSTEM.md](docs/SYSTEM.md).

---

## Installation

**1. Deploy** (over SSH on the device; **no virtual-drive image is created during install**)

```sh
git clone https://github.com/chyou38/rock3a-tslyun.git
cd rock3a-tslyun
sudo ./install.sh                                             # no image; port 80, archive /archive, mDNS tsl.local
sudo ./install.sh --size 120 --port 80 --archive /archive    # optional: pre-create a 120G image
sudo ./install.sh --mdns mybox                                # optional: use http://mybox.local

# BSP single-disk layout (USB data drive at /mnt/tsf-storage): keep archive and cache on it
sudo ./install.sh --archive /mnt/tsf-storage/tsf-data/archive \
                  --cache   /mnt/tsf-storage/tsf-data/cache
```

The installer will: verify the board is a ROCK 3A (RK3568) → check kernel gadget / exFAT / Python → **install the bundled ffmpeg-rockchip (`dist/rkmpp`, hardware decode/encode; failures only warn)** → install into `/opt/tesla-sentry/` and write `/etc/tesla-sentry.conf` → try to install and enable Avahi mDNS → register the `tesla-gadget` / `sentry-viewer` / `tesla-live` / `pwm-fan-control` / `tsf-ap-policy.timer` systemd services plus one cron job (`*/2` LUN self-heal); when NetworkManager is present (BSP), also mark `wlp1s0/ap0` unmanaged and install `wpa_supplicant@wlp1s0`, `tsf-wifi-dhcp` and `tsf-bt-name` → generate a random login password → create the library directory → start everything and print status. Missing fonts or optional kernel features produce warnings, not aborts. **By default no drive is created; you choose the disk and capacity in the web UI.**

**2. Open the web UI and create the virtual drive**: browse to `http://<device-ip>` or `http://tsl.local` (join the box's hotspot, connect through a USB network interface, or add Tailscale / frp yourself). The first login is `admin` with the password printed by the installer or stored in `/opt/tesla-sentry/auth.conf`. Open **Personalization → Car USB**; the "Device & Storage" card inside shows "No virtual drive configured":

1. Plug in the USB disk you want to use (whole disk ≥8 GB; USB stick or portable HDD, any capacity).
2. Select the whole disk in the "Select disk" list and drag "Virtual drive percentage" (10%–90%); the virtual-drive and archive sizes are calculated live.
3. Click "Format and create virtual drive" and confirm twice (the second prompt asks for the disk serial number). This erases the whole disk and creates a sparse exFAT image + `TeslaCam`; back up any existing data first.
4. The page reloads when done; `tesla-gadget` exports the new image and the status becomes "mounted".

For a virtual drive larger than 128 GB, `mkfs.exfat` must be present (Debian: `apt install exfatprogs`); smaller sizes do not need it.

**Fixed address (mDNS)**: the installer tries to install and enable Avahi and advertises `http://tsl.local` on the LAN (default `tsl`, change with `sudo ./install.sh --mdns mybox` for `http://mybox.local`). It depends on mDNS rather than the device IP, so changing networks or DHCP leases does not change the address. Phones, Macs and Linux usually resolve it directly; on Windows install Bonjour or keep using `http://<device-ip>`. Standard mDNS supports only `.local`; custom suffixes such as `.cot` are not treated as mDNS by ordinary clients.

**3. Plug it into the car**: insert the USB3 OTG port into the glovebox head-unit USB port; the car recognizes the virtual drive and starts recording. The image already contains `TeslaCam/{RecentClips,SavedClips,SentryClips,EncryptedClips}`, so **there is no "Format USB device" step**. If the car still asks, confirming is harmless — it just rebuilds the same structure.

**Uninstall**

```sh
sudo ./uninstall.sh              # stop services, remove program and cache, keep image and archived footage
sudo ./uninstall.sh --purge      # also delete image and archive (irreversible)
```

---

## RKMPP hardware decode / encode (required on BSP)

The BSP kernel exposes `/dev/mpp_service` and `/dev/rga`; the repository ships a self-built ffmpeg-rockchip bundle:

- `dist/rkmpp/rkmpp-bin.tar.gz`: stripped `ffmpeg` / `ffprobe` binaries (~21MB)
- `dist/rkmpp/install-rkmpp.sh`: restore script; checks runtime deps, symlinks system `ffmpeg`/`ffprobe`, and writes `TSF_FFMPEG` / `TSF_FFPROBE`
- `dist/rkmpp/deps.txt`: runtime dependency list for Debian 12

```sh
cd dist/rkmpp
sudo bash install-rkmpp.sh -y      # auto-install missing deps
sudo systemctl restart sentry-viewer
```

After installation, `ffmpeg -encoders | grep rkmpp` should list `h264_rkmpp`/`hevc_rkmpp`, and `-filters | grep rkrga` should list `scale_rkrga`. Mainline kernels without `/dev/mpp_service` can only software-decode.

---

## Configuration

Main config: `/etc/tesla-sentry.conf` (restart services after editing):

| Variable | Default | Purpose |
|---|---|---|
| `TSF_IMG` / `TSF_ARCHIVE` | `/opt/tesla-sentry/teslacam.img` / `/archive` | Virtual drive image / archive root; BSP single-disk layout uses `/mnt/tsf-storage/tsf-data/teslacam.img` / `.../archive` |
| `TSF_PORT` | `80` | Web port |
| `TSF_LIVE_INTERVAL` | `15` | Live read-only sync poll interval, seconds |
| `TSF_IDLE` | `600` | Image idle seconds; only used by the cron job that mounts to write Boombox audio |
| `TSF_RECENT_ROLL_MIN` | `60` | `RecentClips` rolling window in minutes, 0 = no rolling |
| `TSF_BOX_KEEP_DAYS` / `TSF_BOX_MAX_GB` | `0` / `0` | Legacy Plan B box-side retention and per-category cap; disabled by default. Archive retention is configured in **Personalization → Files → Archive** |
| `TSF_FREE_MIN_MB` / `TSF_FREE_TARGET_MB` | `4096` / `10240` | Free-space fallback cleanup: trigger threshold and target |
| `TSF_CACHE` | `<install-dir>/cache` | Thumbnail / telemetry / stitch temp cache; BSP deployment uses `/mnt/tsf-storage/tsf-data/cache` |
| `TSF_LIB` | `/mnt/tsf-storage/tsf-data/exports` | Library directory (composite / export outputs); retention is set in the web UI under **My library** (1–180 days, stored as `lib_ttl_days` in `settings.json`), 20 GB hard cap |
| `TSF_VPU_TRANSCODE_ON` / `TSF_TR_CODES` | `1` / `3` | Hardware transcode switch / concurrency; RK3568 has a single hardware encoder instance, and 3 is the long-tested sweet spot |
| `TSF_PREVIEW_CACHE` | `/opt/tesla-sentry/preview-cache` | Three-quality prebuffer cache; defaults to eMMC, recommended to move to the data drive on BSP (`/mnt/tsf-storage/tsf-data/preview-cache`) |
| `TSF_MDNS_NAME` | `tsl` | mDNS host name, i.e. `http://tsl.local`; restart avahi-daemon after changing |

OTA, Feishu push and authentication settings are **not** written to this file — they use environment variables (such as `TSF_OTA_SOURCES`, `TSF_OTA_REPO`) or the web UI. The full variable table and system baseline are in `docs/SYSTEM.md`.

The web **⚙ Personalization** panel has 11 sub-tabs: Network, Files, Lock chime, Wraps, Push, Account, Language, Background, Fan, Brand, Update. Disk selection and virtual-drive creation live in **Personalization → Car USB**, not on the home page.

- **Brand**: Settings → Brand. Replace the title-bar icon (png/jpg/webp, ≤3MB) and the name (≤24 characters). Changes apply instantly and propagate to the login page; the built-in 「TSL哨兵云盘」 icon and name are the defaults and can be restored with one click.
- **Online update**: Settings → Update compares against the repository's `version.json` and offers one-click upgrade / rollback. Configuration and recordings are never part of an update.
- **Feishu push**: Settings → Push. Use a self-built app for direct messages (self only) or a group bot webhook; supports cover cards and short clips from the triggering camera. Hit "Send test" first.
- **Authentication**: credentials live in `/opt/tesla-sentry/auth.conf` (mode 600). Deleting that file and restarting disables auth (only advisable on a trusted LAN).
- **Drive management mode**: "Connect car USB drive" temporarily stops exporting and mounts the image; it reverts after 5 minutes idle. Avoid leaving it mounted while the car is driving or Sentry is active.
- **Lock chime**: WAV, 44.1kHz, 16-bit, <1MB, 1–5 seconds, named `LockChime.wav` in the root of the drive.
- **API**: dozens of endpoints for events, media, telemetry, uploads, file management, OTA and push — `do_GET` / `do_POST` / `do_DELETE` in `sentry-viewer.py` are the reference.

Restart services after changing configuration:

```sh
systemctl restart sentry-viewer
systemctl restart tesla-live
systemctl restart tesla-gadget
```

---

## FAQ

- **The car doesn't see the drive / asks to format it**: confirm `/sys/class/udc/` has a controller and `grep exfat /proc/filesystems` returns something, then run `/opt/tesla-sentry/tesla-gadget.sh status`. New deployments no longer pre-create an image: create it first via **Personalization → Car USB**; a successful creation pre-populates exFAT + `TeslaCam`, so this should not happen. All-zero images left by older installs are patched automatically during reinstall. If the virtual drive exceeds 128 GB (the addressing limit of the car-compatible layout), `mkfs.exfat` is required (`apt install exfatprogs`); otherwise it falls back to a blank image that the car must format once. To write the filesystem manually run `python3 /opt/tesla-sentry/mkexfat.py <image-path> <size-GB>` (it refuses to overwrite an image that already holds data).
- **Black video**: the clips are H.265 / HEVC. Use Edge / Chrome on Windows (with an HEVC decoder) or Safari on iPhone; some Android browsers cannot play them.
- **No events in the web UI**: check `tesla-live.log` and `tesla-sync.log` under `/opt/tesla-sentry/`. Confirm the sync-status chip at the top is online, then verify the archive and image paths.

### Update check fails (GitHub unreachable)

On mainland networks `raw.githubusercontent.com` and the jsDelivr endpoints are frequently reset or hit by TLS interference, and third-party mirrors come and go, so "Check for updates" may occasionally report **all download sources unavailable**. Since 2.8.13 the behaviour is:

- Seven built-in sources (`ghfast.top`, `gcore.jsdelivr.net`, `ghproxy.net`, `gh-proxy.org`, `gh-proxy.com`, raw, jsDelivr) are **raced in parallel** — any one of them working is enough, instead of waiting out each timeout in order;
- Errors list every failed source with its reason (timeout / connection blocked / certificate tampered / DNS failure), so you can tell a firewall problem from a dead mirror at a glance;
- Auto-update is on by default: after the network recovers it retries every 5 minutes and upgrades automatically, no manual clicking.

To add your own source, put a working mirror in the config (comma-separated, in the form `https://domain/<repo-path>/main`):

```bash
echo 'TSF_OTA_SOURCES=https://ghfast.top/https://raw.githubusercontent.com/chyou38/rock3a-tslyun/main,https://gcore.jsdelivr.net/gh/chyou38/rock3a-tslyun@main' >> /etc/tesla-sentry.conf
systemctl restart sentry-viewer
```

**On old versions (2.8.12 and earlier) where even the check fails and the update page is unreachable**, overwrite the program manually once on the device; automatic updates resume afterwards:

```bash
wget -O /tmp/sv.py https://ghfast.top/https://raw.githubusercontent.com/chyou38/rock3a-tslyun/main/sentry-viewer.py \
  || wget -O /tmp/sv.py https://gcore.jsdelivr.net/gh/chyou38/rock3a-tslyun@main/sentry-viewer.py
python3 -m py_compile /tmp/sv.py && cp /tmp/sv.py /opt/tesla-sentry/sentry-viewer.py \
  && chmod 755 /opt/tesla-sentry/sentry-viewer.py && systemctl restart sentry-viewer
```

### Watermark checked but missing from the exported video

Burning the overlay on-device (`ffmpeg` + libass) requires a **CJK font**. Versions 2.8.18 and earlier silently skipped the whole subtitle chain when the font was missing — the export succeeded, with no watermark at all. Since 2.8.19:

- The export panel shows a "watermark font" status; when missing it offers **Install font** (one click, downloads from the official `google/fonts` repository, ~17MB, retried across mirrors) and **Upload** (local ttf/otf);
- With no font available the export is blocked with an explicit message rather than handing you a watermark-free video;
- Font detection also falls back to system font directories outside `/opt/tesla-sentry/fonts`, so boxes that already had a font installed work immediately after upgrading.

Installing the font manually (copying it from elsewhere works fine offline):

```bash
mkdir -p /opt/tesla-sentry/fonts
wget -O /opt/tesla-sentry/fonts/NotoSansSC.ttf \
  "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf" \
  || wget -O /opt/tesla-sentry/fonts/NotoSansSC.ttf \
  "https://ghfast.top/https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf"
ls -l /opt/tesla-sentry/fonts/     # should be about 17MB
systemctl restart sentry-viewer
```


---

## Security notes

- `install.sh` enables site-wide login protection by default. **Running `python3 sentry-viewer.py` directly without an `auth.conf` leaves authentication off** — only do that on a trusted LAN. Deleting `auth.conf` is still the "disable auth" switch, but if the file exists and the password cannot be read, the service **refuses to start** instead of running unprotected.
- The login page and HTTP Basic share one rate limit: 8 failures from an IP within 10 minutes locks it for 5 minutes, and Basic cannot bypass it.
- Uploads are capped at 100MB, plain JSON endpoints at 1MB per request; per-connection read/write timeout is 30 seconds with up to 48 threads. Paths are confined to the archive / image mount points and cannot escape into system directories.
- Authentication and cookies travel over plain HTTP. Use HTTPS or a VPN for internet exposure; behind a reverse proxy send `X-Forwarded-Proto: https` (or set `TSF_COOKIE_SECURE=1`) and the login cookie gains `Secure` automatically.

## Disclaimer

This is a personal hobby project, not affiliated with Tesla. Changing how your car's storage behaves carries risk (data loss, interrupted recording). Evaluate it yourself and test with a small image first.

## Credits

- [teslausb](https://github.com/marcone/teslausb) — the pioneering Raspberry Pi USB-drive impersonator; the idea this project grew from
- [SentryBox](https://github.com/weitanism/sentrybox) — productized practice for an always-on in-car device
- [tesla-sentry-viewer](https://github.com/denysvitali/tesla-sentry-viewer) — reference for the web-viewer form factor

## License

[MIT](LICENSE)
