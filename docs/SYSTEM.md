# 系统基线 · ROCK 3A（TSL Sentry Box）

本文件记录本仓库**实测通过**的软硬件版本与配置方式，便于复现和排障。所有密码、SSID、密钥均以占位符表示，实际配置不要提交到仓库。

## 1. 硬件

| 项目 | 实测值 |
|---|---|
| 主板型号 | `Radxa ROCK 3A`（设备树 `model`；`compatible` = `radxa,rock3a` / `rockchip,rk3568`） |
| 处理器 | RK3568，4× Cortex-A55（aarch64） |
| 内存 | 2GB（1.9GiB 可用） |
| 系统盘 | eMMC 58.3GB（`mmcblk0`，根分区 57.6GB，已用约 2.5GB） |
| 数据盘 | USB 478GB（`sda1`，挂 `/mnt/tsf-storage`，存虚拟 U 盘镜像与归档） |
| 无线网卡 | Intel Wi-Fi 6 AX200（PCIe `8086:2723`，驱动 `iwlwifi`，固件 `iwlwifi-cc-a0-77.ucode`） |
| 蓝牙 | AX200 集成，USB `8087:0029`，控制器 `hci0` |
| 有线网卡 | `end0` 千兆，DHCP |
| 风扇 | ROCK 3A 3-pin PWM 风扇座（`pwm8 m0`，需 `rock3a-pwm8-fan` overlay） |
| USB | USB3 OTG 口用于 Gadget（mass_storage）导出虚拟 U 盘 |

**已使用接口**：USB3 OTG（接车机）、`end0`（有线网络）、AX200（WiFi STA + 2.4G 热点）、蓝牙、PWM 风扇座、eMMC（系统盘）、USB 数据盘（镜像/归档）。
**未使用接口**：HDMI、USB Host、M.2、音频等本方案不依赖，保持空闲。

> MAC 地址等唯一标识不写入仓库。换卡说明：原 MT7922 已拆除。`/etc/modprobe.d/tsf-blacklist-mt7921e.conf` 会屏蔽 `mt7921e/mt7921s/mt7921u/mt7922/mt76/mt76_connac_lib`，并已 `apt purge firmware-mediatek`，避免旧驱动残留导致换卡后系统卡死。

## 2. 系统与内核

| 项目 | 实测值 |
|---|---|
| 发行版 | Armbian 26.8.1 trixie（Debian GNU/Linux 13） |
| 内核 | `6.18.44-current-rockchip64`（aarch64，SMP PREEMPT） |
| 主机名 | `rock-3a` |
| Python | 3.13.5（查看器仅用标准库） |

依赖包（实测版本，Debian 13）：

| 包 | 版本 | 用途 |
|---|---|---|
| `hostapd` | `2:2.10-24` | 个人热点 |
| `dnsmasq` / `dnsmasq-base` | `2.91-1+deb13u2` | 热点 DHCP / DNS |
| `wpasupplicant` | `2:2.10-24` | WiFi STA（独立实例 `wpa_supplicant@wlp1s0`） |
| `iw` | `6.9-1+b1` | 扫描 / 建 AP 接口 / 信道能力检查 |
| `bluez` | `5.82-1.1+rpt2` | 蓝牙设置面板 |
| `ffmpeg` | `7:7.1.5-0+deb13u1` | 转码 / 缩略图 / 水印导出 |
| `exfatprogs` | `1.2.9-1+deb13u1` | 镜像格式化辅助 |
| `firmware-iwlwifi` | `20250410-2` | AX200 固件 |

## 3. 服务与开机行为

| 单元 | 开机 | 实测状态 | 说明 |
|---|---|---|---|
| `sentry-viewer.service` | enabled | active | 网页服务，监听 `0.0.0.0:80` |
| `tesla-gadget.service` | enabled | active | 虚拟 U 盘 Gadget（oneshot + RemainAfterExit） |
| `tesla-live.service` | enabled | active | 车机无感只读同步 |
| `pwm-fan-control.service` | enabled | active | 风扇温控常驻循环 |
| `tsf-hotspot.service` | enabled | inactive | 热点本体（hostapd + dnsmasq + NAT），按需拉起 |
| `tsf-ap-policy.timer` | enabled | active | 每 20 秒执行自动热点策略 |
| `wpa_supplicant@wlp1s0.service` | enabled | active | WiFi STA 独立实例 |
| `bluetooth.service` | enabled | active | 蓝牙 |
| `hostapd.service` | **disabled** | inactive | 只在热点需要时由 `tsf-ap.sh` 拉起，禁止开机抢跑 |

## 4. 网络配置

有线 `end0` 走 netplan + systemd-networkd 的 DHCP；无线 `wlp1s0` 不写进 netplan（netplan 的 `wifis:` 不支持 `band` 键，且去掉 `access-points` 会报错），改由独立 `wpa_supplicant` 实例连接，`systemd-networkd` 只负责 DHCP。

```text
end0 (DHCP, 例 192.168.1.50)
  └─ 有线网络可用 → 热点关闭
wlp1s0 (STA, 2.4G only, freq_list 2412-2472)
  └─ 连上 WiFi → 热点关闭；未连 → 热点可开
ap0 (192.168.50.1/24, hostapd + dnsmasq, NAT 到 end0)
  └─ DHCP 池 192.168.50.100-200 / 12h
```

相关文件（模板见 [`config/`](../config)）：

- `/etc/netplan/10-dhcp-all-interfaces.yaml` — 只保留 `ethernets`，含 `lan[0-9]*` / `wan[0-9]*` 匹配块与 `end0`
- `/etc/wpa_supplicant/wpa_supplicant-wlp1s0.conf` — 权限 600，`country=CN`，`freq_list` 锁 2.4G
- `/etc/systemd/network/20-wlp1s0.network` — `DHCP=yes`
- `/etc/tsf-ap.conf` — 热点三态、SSID/PSK、频段/信道（权限 600）
- `/etc/hostapd/tsf-ap.conf` — 由 `tsf-ap.sh` 按 `/etc/tsf-ap.conf` 生成，`hostapd.conf` 软链到它
- `/etc/dnsmasq.d/tsf-ap.conf` — 热点 DHCP
- `/etc/default/pwm-fan` — 风扇曲线 / 手动占空比

### 热点自动策略（三态）

`/etc/tsf-ap.conf` 的 `AP_ENABLE`：

- `0` = 关闭
- `1` = 常开
- `auto` = **没连上 WiFi 且没有有线 IPv4** 时开热点；任一网络可用时关热点

`tsf-ap-policy.timer` 每 20 秒检查一次，调用 `ap-policy.sh` 启停 `tsf-hotspot.service`；网页「个人热点」下拉对应这三档。

### AX200 的能力边界（重要）

`iw phy` 能力：`#{managed}<=1 + #{AP,P2P-client,P2P-GO}<=1, total<=3, #channels<=1`，即 **STA + AP 可以并发，但必须同信道**。AX200 是 self-managed 监管域（`iw reg set CN` 不生效），5 GHz 信道 36–165 恒为 `no IR`，hostapd 会报 `Primary frequency not allowed ... NO-IR`。因此：

- 热点只能 **2.4 GHz**；`AP_HW_MODE=a` 在 AX200 上不可用
- 已连 WiFi 时热点自动跟随同一信道（如 ch6）
- 未连 WiFi 时默认 2.4G ch6；网页可切「自动 / 手动信道」

## 5. 网页与登录

- 端口：`TSF_PORT=80`，直接访问 `http://<设备IP>/`，无需加端口
- mDNS：安装时启用 Avahi，默认广播 `http://tsl.local`（`TSF_MDNS_NAME=tsl`，用 `--mdns NAME` 可改）；换 IP 不影响地址，仅同一局域网有效，标准后缀只有 `.local`
- 账号：`admin`，密码由 `install.sh` 随机生成写入 `/opt/tesla-sentry/auth.conf`（权限 600，不入库）
- 认证：HMAC 签名 Cookie 30 天 + HTTP Basic；连错 8 次/10 分钟限流

## 6. OTA 更新源

`OTA_REPO` 默认 `chyou38/rock3a-tslyun`（公开仓库），可用环境变量 `TSF_OTA_REPO` 覆盖。

> 仓库已公开：盒子和其他安装者可直接匿名拉取 `version.json` 与 `sentry-viewer.py`，不需要令牌或部署密钥。

## 7. 快速自检

```sh
uname -a
cat /etc/os-release
systemctl is-active sentry-viewer tesla-gadget tesla-live pwm-fan-control tsf-ap-policy.timer wpa_supplicant@wlp1s0 bluetooth hostapd
iw dev
iw phy | grep -A6 "valid interface combinations"
curl -I http://127.0.0.1/
```

原始采集输出见 [`system-info.txt`](system-info.txt)。
