# 系统基线 · ROCK 3A（TSL Sentry Box）

本文件记录本仓库**实测通过**的软硬件版本与配置方式，便于复现和排障。所有密码、SSID、密钥、MAC、真实 IP 均以占位符表示，实际配置不要提交到仓库。

## 1. 硬件

| 项目 | 实测值 |
|---|---|
| 主板型号 | `Radxa ROCK 3A`（设备树 `model`；`compatible` = `radxa,rock3a` / `rockchip,rk3568`） |
| 处理器 | RK3568，4× Cortex-A55（aarch64） |
| 内存 | 2GB（1.9GiB 可用） |
| 系统盘 | eMMC 58.3GB（`mmcblk0`，根分区约 57GB） |
| 数据盘 | USB 470GB（`sda1`，ext4，挂 `/mnt/tsf-storage`，存虚拟 U 盘镜像与归档） |
| 无线网卡 | Intel Wi-Fi 6 AX200（PCIe `8086:2723`，驱动 `iwlwifi`） |
| 蓝牙 | AX200 集成 USB（`8087:0029`；正常枚举时出现控制器，未枚举时 `tsf-bt-name` 等待后退出） |
| 有线网卡 | `end1` 千兆，NetworkManager DHCP（旧 Armbian 上为 `end0`） |
| 风扇 | BSP 内核 `pwm-fan` 驱动（hwmon 名 `pwmfan`，`pwm1`，25kHz）；旧 mainline 走 `pwm8 m0` + `rock3a-pwm8-fan` overlay |
| USB | USB3 OTG 口用于 Gadget（mass_storage）导出虚拟 U 盘 |

**已使用接口**：USB3 OTG（接车机）、`end1`（有线网络）、AX200（WiFi STA + 2.4G 热点）、蓝牙、PWM 风扇座、eMMC（系统盘）、USB 数据盘（镜像/归档/缓存）。
**未使用接口**：HDMI、USB Host、M.2、音频等本方案不依赖，保持空闲。

> MAC 地址等唯一标识不写入仓库。原 MT7922 已拆除；`/etc/modprobe.d/tsf-blacklist-mt7921e.conf` 会屏蔽 `mt7921e/mt7921s/mt7921u/mt7922/mt76/mt76_connac_lib`，避免旧驱动残留导致换卡后系统卡死。

## 2. 系统与内核

| 项目 | 实测值 |
|---|---|
| 发行版 | Radxa 官方 Debian 12 bookworm BSP（Debian GNU/Linux 12） |
| 内核 | `6.1.84-15-rk2410-nocsf`（aarch64，BSP） |
| 主机名 | `tsl-sentry` |
| Python | 3.11.2（查看器仅用标准库） |
| 硬件加速 | `/dev/mpp_service` + `/dev/rga`；RKMPP ffmpeg/ffprobe 在 `/opt/rkmpp/bin`（见 `dist/rkmpp/`） |

依赖包（实测版本，Debian 12 bookworm）：

| 包 | 版本 | 用途 |
|---|---|---|
| `hostapd` | `2:2.10-12+deb12u3` | 个人热点 |
| `dnsmasq` | `2.90-4~deb12u2` | 热点 DHCP / DNS |
| `wpasupplicant` | `2:2.10-12+deb12u3` | WiFi STA（独立实例 `wpa_supplicant@wlp1s0`） |
| `iw` | `5.19-1` | 扫描 / 建 AP 接口 / 信道能力检查 |
| `bluez` | `5.66-1+deb12u2` | 蓝牙设置面板 |
| `ffmpeg` | `7:5.1.9-0+deb12u1` | 系统 ffmpeg；硬解/硬编用 RKMPP 版本替换 |
| `exfatprogs` | `1.2.0-1+deb12u1` | 镜像格式化辅助 |
| `udhcpc` | `1:1.35.0-4+deb12u1+b1` | 无线 STA 的 DHCP 客户端 |
| `NetworkManager` | BSP 自带 | 只管理有线 `end1` |

## 3. 数据、归档与缓存位置（新 BSP 重点）

新 BSP 不再把归档放在独立 `/archive` 分区，而是统一放在 USB 数据盘的 `tsf-data` 目录；根分区（eMMC）只放系统和程序。

| 内容 | 路径 | 介质 |
|---|---|---|
| 虚拟 U 盘镜像 | `/mnt/tsf-storage/tsf-data/teslacam.img` | USB 数据盘 |
| 归档区 | `/mnt/tsf-storage/tsf-data/archive/{SentryClips,SavedClips,RecentClips,...}` | USB 数据盘 |
| 列表缩略图 / 遥测 / 合成临时 | `/mnt/tsf-storage/tsf-data/cache/{thumbs,tel-cache,res-cache,stitch-tmp}` | USB 数据盘 |
| 三档预缓冲 | `TSF_PREVIEW_CACHE` 未显式设置时默认 `/opt/tesla-sentry/preview-cache` | **eMMC（当前部署仍在系统盘）** |
| 中文字体 | `/opt/tesla-sentry/fonts` | eMMC |

当前实测机 `TSF_CACHE=/mnt/tsf-storage/tsf-data/cache`，缩略图和遥测缓存已在数据盘；但 `TSF_PREVIEW_CACHE` 没有写进 `/etc/tesla-sentry.conf`，代码回退到 `/opt/tesla-sentry/preview-cache`，所以 **360p/480p/720p 预缓冲仍写在 eMMC**（实测约 433MB，且随播放增长）。

要把它也迁到数据盘，在 `/etc/tesla-sentry.conf` 增加：

```sh
TSF_PREVIEW_CACHE=/mnt/tsf-storage/tsf-data/preview-cache
```

然后重启 `sentry-viewer`：

```sh
sudo mkdir -p /mnt/tsf-storage/tsf-data/preview-cache
sudo systemctl restart sentry-viewer
```

旧缓存可保留作兜底，确认新目录开始生成后可删除 `/opt/tesla-sentry/preview-cache`。安装脚本从本版起会默认写入 `TSF_PREVIEW_CACHE=$CACHE_DIR/preview-cache`，BSP 安装时用 `--cache /mnt/tsf-storage/tsf-data/cache` 即可让预缓冲也落在数据盘。

> 旧 Armbian 安装的默认路径是 `TSF_IMG=/opt/tesla-sentry/teslacam.img`、`TSF_ARCHIVE=/archive`；BSP 与新安装脚本请按上表/`install.sh --archive ... --cache ...` 显式指定。

## 4. 服务与开机行为

| 单元 | 开机 | 实测状态 | 说明 |
|---|---|---|---|
| `sentry-viewer.service` | enabled | active | 网页服务，监听 `0.0.0.0:80` |
| `tesla-gadget.service` | enabled | active | 虚拟 U 盘 Gadget（oneshot + RemainAfterExit） |
| `tesla-live.service` | enabled | active | 车机无感只读同步 |
| `pwm-fan-control.service` | enabled | active | 风扇温控常驻循环（BSP hwmon / mainline pwm8 自适应） |
| `tsf-hotspot.service` | enabled | 按策略 | 热点本体（hostapd + dnsmasq + NAT），按需 up/down |
| `tsf-ap-policy.timer` | enabled | active | 每 20 秒执行自动热点策略 |
| `tsf-wifi-dhcp.service` | enabled | active | `udhcpc -i wlp1s0`，BindsTo `wpa_supplicant@wlp1s0` |
| `tsf-bt-name.service` | enabled | oneshot | 有蓝牙控制器时设别名 `TeslaSentry`；无控制器等待后退出 |
| `wpa_supplicant@wlp1s0.service` | enabled | active | WiFi STA 独立实例 |
| `wpa_supplicant.service` | masked | inactive | 单实例会与 per-interface 实例抢 `wlp1s0`，必须屏蔽 |
| `bluetooth.service` | enabled | active | 蓝牙 |
| `hostapd.service` | disabled（安装脚本） | 按需 | 只在热点需要时由 `tsf-ap.sh` 拉起，禁止开机抢跑 |
| `dnsmasq.service` | disabled（发行版默认） | 按需 | 由 `tsf-ap.sh` 在热点 up 时 restart |
| `NetworkManager.service` | enabled | active | BSP 有线 `end1` DHCP；`wlp1s0/ap0` 标为 unmanaged |

## 5. 网络配置（BSP）

BSP 使用 NetworkManager 管理有线，WiFi STA 和 AP 都不交给 NM：

```text
end1 (NetworkManager DHCP, 例 192.168.1.50)
  └─ 有线 IPv4 可用 → 热点关闭
wlp1s0 (STA, 独立 wpa_supplicant@wlp1s0, 2.4G only)
  └─ 连上 WiFi → 热点关闭；udhcpc 负责拿地址
ap0 (192.168.50.1/24, hostapd + dnsmasq, NAT 到当前默认出口)
  └─ DHCP 池 192.168.50.100-200 / 12h
```

相关文件（模板见 [`config/`](../config)）：

- `/etc/NetworkManager/conf.d/99-tsf-unmanaged.conf` — `wlp1s0` / `ap0` / `p2p-dev-ap0` 标 unmanaged
- `/etc/wpa_supplicant/wpa_supplicant-wlp1s0.conf` — 权限 600，`country=CN`，`freq_list` 锁 2.4G；SSID/PSK 由网页写入 `wifi-networks.json`
- `/etc/tsf-ap.conf` — 热点三态、SSID/PSK、频段/信道（权限 600）
- `/etc/hostapd/tsf-ap.conf` — 由 `tsf-ap.sh` 按 `/etc/tsf-ap.conf` 生成，`hostapd.conf` 软链到它
- `/etc/dnsmasq.d/tsf-ap.conf` — 热点 DHCP / DNS
- `/etc/default/pwm-fan` — 风扇曲线 / 手动占空比
- `/etc/tesla-sentry.conf` — `TSF_ARCHIVE`、`TSF_CACHE`、`TSF_PREVIEW_CACHE` 等路径

### 热点自动策略（三态）

`/etc/tsf-ap.conf` 的 `AP_ENABLE`：

- `0` = 关闭
- `1` = 常开
- `auto` = **没连上 WiFi 且没有有线 IPv4** 时开热点；任一网络可用时关热点

`tsf-ap-policy.timer` 每 20 秒检查一次，调用 `ap-policy.sh` 启停 `tsf-hotspot.service`；有线接口按默认路由识别（旧 `end0` / BSP `end1` 都可），网页「个人热点」下拉对应这三档。

### AX200 的能力边界（重要）

`iw phy` 能力：`#{managed}<=1 + #{AP,P2P-client,P2P-GO}<=1, total<=3, #channels<=1`，即 **STA + AP 可以并发，但必须同信道**。AX200 是 self-managed 监管域（`iw reg set CN` 不生效），5 GHz 信道 36–165 恒为 `no IR`，hostapd 会报 `Primary frequency not allowed ... NO-IR`。因此：

- 热点只能 **2.4 GHz**；`AP_HW_MODE=a` 在 AX200 上不可用
- 已连 WiFi 时热点自动跟随同一信道（如 ch6）
- 未连 WiFi 时默认 2.4G ch6；网页可切「自动 / 手动信道」

## 6. 网页与登录

- 端口：`TSF_PORT=80`，直接访问 `http://<设备IP>/`，无需加端口
- mDNS：安装时启用 Avahi，默认广播 `http://tsl.local`（`TSF_MDNS_NAME=tsl`，用 `--mdns NAME` 可改）；换 IP 不影响地址，仅同一局域网有效，标准后缀只有 `.local`
- 账号：`admin`，密码由 `install.sh` 随机生成写入 `/opt/tesla-sentry/auth.conf`（权限 600，不入库）
- 认证：HMAC 签名 Cookie 30 天 + HTTP Basic；连错 8 次/10 分钟限流

## 7. OTA 更新源

`OTA_REPO` 默认 `chyou38/rock3a-tslyun`（公开仓库），可用环境变量 `TSF_OTA_REPO` 覆盖。

> 仓库已公开：盒子和其他安装者可直接匿名拉取 `version.json` 与 `sentry-viewer.py`，不需要令牌或部署密钥。

## 8. 快速自检

```sh
uname -a
cat /etc/os-release
systemctl is-active sentry-viewer tesla-gadget tesla-live pwm-fan-control \
  tsf-ap-policy.timer wpa_supplicant@wlp1s0 tsf-wifi-dhcp bluetooth
ip -brief addr
iw dev
curl -I http://127.0.0.1/
```

原始采集输出（已去掉 IP/MAC/SSID/PSK）见 [`system-info.txt`](system-info.txt)。
