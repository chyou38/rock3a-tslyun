# TSL哨兵云盘 · TSL Sentry Drive

> ⚠️ **法律与风险提示（必读）**
>
> 本项目是个人开源硬件改造项目，采用 MIT License，与 Tesla, Inc.（特斯拉）及其关联公司**无任何隶属、授权、赞助或背书关系**；“Tesla”“特斯拉”等商标归其权利人所有，本项目仅在描述兼容设备时作指代。
>
> 本项目仅供个人学习、研究与自有设备数据备份，**不得**用于商业运营、规避监管、侵犯他人隐私或其他违法用途。使用涉及车辆数据访问、USB 设备模拟、Wi-Fi 热点发射等行为，请自行确认符合所在地区法律法规与无线电管理规定；由此产生的车辆、数据、设备损坏或法律责任由使用者自行承担。
>
> 软件按“现状（AS IS）”提供，不附带任何明示或暗示担保。

**中文** | [English](README.en.md)

**虚拟哨兵 U 盘 · 多路同步回放 · SEI 行车遥测 · 水印导出 —— 仅适配 Radxa ROCK 3A（RK3568）。**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.7+](https://img.shields.io/badge/python-3.7%2B-3776AB.svg)](https://www.python.org/)
[![零第三方依赖](https://img.shields.io/badge/deps-%E9%9B%B6%E7%AC%AC%E4%B8%89%E6%96%B9%E5%BA%93-brightgreen.svg)](#功能)

把 Radxa ROCK 3A（RK3568，2GB）顶替原车 U 盘插进手套箱：车机照常录制，手机连盒子 WiFi 打开网页就能回看 4 / 6 路同步画面、逐帧读视频码流里的 SEI 遥测（挡位 / 车速 / 油门 / 刹车 / 方向盘 / 转向灯 / AP / 坐标），并导出带行车信息水印的视频。

本仓库只维护这一套硬件与系统：**Armbian 26.8.1 trixie（Debian 13）/ 内核 6.18.44-current-rockchip64 / Intel AX200 无线网卡**。其他型号的开发板、路由器或 NAS 未适配，装不上或功能不可用，不在支持范围。

---

## 功能

| 能力 | 说明 |
|---|---|
| 🗂 虚拟 U 盘 | **安装时不预建镜像**；部署后打开网页「个性化 → 车机U盘」里的「设备与存储」，插入任意容量 USB 硬盘（整盘 ≥8G）→ 选择整块盘 → 拖动虚拟U盘占比 → 输入序列号格式化创建。创建的是稀疏 exFAT 镜像并预置 `TeslaCam` 目录，通过 USB Gadget `mass_storage` 导出；网卡 / 串口共存。也可在安装时用 `--size` 显式预建。 |
| ⚡ 实时查看 | `tesla-live-sync.py` 每 15 秒**只读解析 exFAT**（不挂载、不断 USB），车机边写网页边看，新片段通常 15–30 秒出现；cron `*/10` 只负责写 Boombox 音频 |
| 📦 归档与滚动窗口 | 视频落到独立 ext4 归档区，不与车机同时读写镜像；`RecentClips` 跟随车机滚动缓冲只留最近 60 分钟，`SentryClips` / `SavedClips` 的**盒子副本**默认按 14 天 / 12GB 清理（车机 U 盘那份只读不动），`.pruned` 墓碑避免「删除→重抄」死循环 |
| 🎬 播放 | **默认单路**: 点开事件直接播触发摄像头那一路 (画面下方切换条可选 前视/后视/左B柱/右B柱/全览, 点哪个才加载哪个, 切换保留播放进度)；全览 4 路 2×2 / 6 路 3×2 自适应，250ms 同步校正、统一进度条、0.5–4x；**自动落在触发时刻所在的那一分钟、从触发前 5 秒起播**（片段栏红点标记） |
| 📊 遥测与元数据 | 直读码流内嵌 SEI protobuf：挡位 / 车速 / 油门 / 刹车 / 方向盘角度 / 转向灯 / AP 状态 / 坐标 / 三轴加速度，随进度逐帧跳动；`event.json` 提供时间 / 城市 / 街道 / 触发原因 / 触发画面 |
| 🔍 筛选与预览 | 触发原因 + 日期胶囊叠加筛选；`?ev=` `?date=` `?cat=` `?cam=` `?exp=1` 深链；📡 实时预览与其它分类同级（点页签即切换，不用返回），带 原画 / 720p / 480p / 360p 画质选择；存储条（虚拟U盘按卷内实际写入量计，不是镜像预分配占用；进度条按占用比例配色：<30% 绿 / 30–85% 蓝 / >85% 红）与在线同步状态 |
| 📶 清晰度 | 播放可选 原画 / 720p / 480p / 360p（服务端转码缓存，上限 2GB）。**默认 480p**：与飞书推送 / 导出的默认档位同一分辨率，单路 480p 公网起播实测 0.08s；手动改过就记住你的选择，下次优先用记忆值。哨兵 / 手动保存的新事件落盘后，后台会先把「触发摄像头那一路」的触发段±相邻段预转成 480p（点开即播；每事件 3 个文件），只在没人看视频时跑。**行车记录 / 准实时预览不预转**：这类片段每分钟新增、很快滚动淘汰，预转的缓存立刻作废，还会让无风扇设备持续满载转码、核心温度长期偏高；真点开时由服务端按需后台转码。**缓存没赶上的文件不会让人干等**：播放器先用已有的压缩档（都没有才用原画）开播，不必等转码；转码放后台，切段或下次打开自动用上目标档位 |
| 🎞 导出 | 单路下载、zip 打包、多路合成（2×2 / 3 路时第三路铺满下排）；清晰度 原画 / 720p / 480p / 360p，**多画面按原片 4:3 取格子，不留黑边**（原画单路直接出 1280×960 + 源帧率）；带水印时一律由设备端 ffmpeg 直出 H.264 mp4（+faststart，微信 / 相册可直接发）；水印与网页播放器同款（左侧时间 / 地点，右侧车速 / 转向灯 / 挡位 / 刹车 / 油门，外加 **AP 方向盘图标**：辅助驾驶启动时蓝色、未启动时灰色）；片段没有行车遥测（停车哨兵录制）时水印退化成只显示时间 + 地点，不会悄悄不出水印 |
| 📂 文件管理 | U 盘 / 归档区浏览上传下载，多选批量删除 / 移动 / 复制 / 重命名（realpath 防逃逸）；一键清空 `TeslaCam/` 全部录像（保留目录结构、不动 Boombox / Wraps）；U 盘管理模式 5 分钟无操作自动恢复导出 |
| 🔔 飞书推送 | 私聊（仅本人）/ 群机器人，触发那一帧封面卡片或触发点前 5 秒短视频，可烧行车信息水印；去重、延迟 20 秒、失败重试 3 次，导出浮层也能直接推送 |
| 🔐 登录保护 | `install.sh` 默认生成随机 10 位密码（admin），HMAC 签名 cookie 保留 30 天 + HTTP Basic；10 分钟内连错 8 次返回 429；设置 → 账号可改密码 / 退出 |
| 🌐 内网固定地址 | 安装时尝试启用 Avahi mDNS，在局域网广播 `http://tsl.local`（默认主机名 `tsl`，`--mdns NAME` 可改）；换 IP 不用重新记地址。仅同一局域网有效，标准 mDNS 只支持 `.local` 后缀 |
| 🔄 在线升级 | 多源并发竞速 + GitHub API 实时兜底，下载后校验 → 备份 → 原子替换 → 自动重启，出问题一键回滚；设置 → 更新里可勾选**自动更新**（默认开启，检测到新版且没人看视频时自动升） |
| 🎨 个性化 | 标题图标与名称可自定义（默认「TSL哨兵云盘」）、深 / 浅 / 自动主题，4 套界面风格（默认 / Apple / Claude / 像素），10 种界面语言、网页背景换肤、锁车音（`LockChime.wav`）、涂装 `Wraps/` |
| 🛡 稳定性 | 归档区 ext4 日志式、开机自检、服务自动拉起、LUN 被弹出后 cron `*/2` 自动重挂、断电自愈 |

---

## 适配设备（仅 ROCK 3A）

本仓库只针对 **Radxa ROCK 3A（RK3568）** 维护和验证；其他型号的开发板、路由器或 NAS 未适配，装不上或功能不可用，不在支持范围。

| 项目 | 本机实测 |
|---|---|
| 主板 | Radxa ROCK 3A（RK3568，4× Cortex-A55） |
| 内存 | 2GB（可用 1.9GiB） |
| 系统盘 | eMMC 58.3GB（`mmcblk0`，根分区 57.6GB） |
| 数据盘 | USB 478GB（`sda1`，挂 `/mnt/tsf-storage`，存镜像与归档） |
| 系统 | Armbian 26.8.1 trixie（Debian 13） |
| 内核 | 6.18.44-current-rockchip64（aarch64） |
| 无线网卡 | Intel Wi-Fi 6 AX200（`8086:2723`，iwlwifi，固件 `iwlwifi-cc-a0-77`） |
| 蓝牙 | AX200 集成（`8087:0029`，hci0） |
| 有线网卡 | `end0` 千兆，DHCP |
| 风扇 | 板载 3-pin PWM（`pwm8 m0`，需 `rock3a-pwm8-fan` overlay） |
| USB | USB3 OTG 口做 Gadget，接车机 |

**已使用**：USB3 OTG（车机）、`end0`（有线）、AX200（WiFi STA + 2.4G 热点）、蓝牙、PWM 风扇座、eMMC（系统）、USB 数据盘（镜像/归档）。
**未使用**：HDMI、USB Host、M.2、音频等接口本方案不依赖，保持空闲。

**硬门槛**：`/sys/class/udc/` 非空、configfs + `USB_F_MASS_STORAGE`、内核 exFAT、loop / losetup、root，且车机 USB 口能供电。系统必须是 Debian 13 / Armbian systemd；Python 3.7+（查看器零第三方依赖）；ffmpeg 只影响缩略图与转码，缺失不阻塞安装。

装之前先自检（只读、不改系统）：

```sh
sh scripts/tsf-check.sh          # 逐项检查 UDC / configfs / exFAT / Python / init，三色结论
sh scripts/tsf-check.sh --json   # 供脚本判定
```

系统版本、依赖版本、服务启停表与网络/热点配置详见 [docs/SYSTEM.md](docs/SYSTEM.md)。

---

## 安装

**1. 部署**（在设备 SSH 里执行；安装阶段**不创建任何虚拟U盘镜像**）

```sh
git clone https://github.com/chyou38/rock3a-tslyun.git
cd rock3a-tslyun
sudo ./install.sh                                             # 不预建镜像；端口 80、归档 /archive、mDNS tsl.local
sudo ./install.sh --size 120 --port 80 --archive /archive    # 可选：安装时预建 120G 镜像
sudo ./install.sh --mdns mybox                                # 可选：改用 http://mybox.local
```

安装会：先校验主板是否为 ROCK 3A（RK3568）→ 检查内核 gadget / exFAT / Python → 装到 `/opt/tesla-sentry/`、写 `/etc/tesla-sentry.conf` → 尝试安装并启用 Avahi mDNS → 注册 `tesla-gadget` / `sentry-viewer` / `tesla-live` / `pwm-fan-control` / `tsf-ap-policy.timer` 等 systemd 服务与两条 cron → 生成随机登录密码 → 启动并打印状态。ffmpeg、字体、部分内核项缺失只警告不中止。**默认不建盘，安装完成后由你在网页里选择硬盘和容量。**

**2. 打开网页，自己创建虚拟U盘**：浏览器访问 `http://<设备IP>` 或 `http://tsl.local`（手机连设备热点、USB 网卡直连，或自行加 Tailscale / frp）。首次登录账号 `admin`，密码见安装输出或 `/opt/tesla-sentry/auth.conf`。打开 **「个性化 → 车机U盘」**，里面的「设备与存储」会提示「未配置虚拟U盘」：

1. 插入要用的 USB 硬盘（整块盘容量 ≥8G，U 盘 / 移动硬盘均可，容量不固定）。
2. 在「选择硬盘」下拉里选中整块盘，拖动「虚拟U盘占比」（10%–90%），下方会实时算出虚拟盘 / 归档区容量。
3. 点「格式化并创建虚拟U盘」，连续两次确认（第二次输入该盘序列号）。会清空整块盘并创建稀疏 exFAT + `TeslaCam` 目录；盘上有数据请先备份。
4. 创建完成后页面自动刷新，`tesla-gadget` 会导出这块虚拟盘，状态变为「已挂载」。

虚拟盘超过 128G 时，需要系统里有 `mkfs.exfat`（Debian: `apt install exfatprogs`）；小容量不需要。

**固定访问地址（mDNS）**：安装阶段会尝试安装并启用 Avahi，在局域网广播 `http://tsl.local`（默认主机名 `tsl`，可用 `sudo ./install.sh --mdns mybox` 改成 `http://mybox.local`）。这个地址只依赖 mDNS，不依赖设备 IP，换了网络/租约也不用改地址；手机、Mac、Linux 通常直接可访问，Windows 若解析不了可安装 Bonjour 或继续用 `http://<设备IP>`。标准 mDNS 只支持 `.local` 后缀，`.cot` 等自定义后缀不会被普通客户端当作 mDNS。

**3. 插到车上**：把设备 USB3 OTG 口插进手套箱车机 USB 口，车机识别虚拟盘后开始录制。镜像里已预建 `TeslaCam/{RecentClips,SavedClips,SentryClips,EncryptedClips}`，正常不需要再点「格式化 USB 设备」；若车机仍弹出该提示，点确认也无害。

**卸载**

```sh
sudo ./uninstall.sh              # 停服务、删程序与缓存，保留镜像和归档录像
sudo ./uninstall.sh --purge      # 连镜像和归档一起删（不可恢复）
```

---

## 配置与常用设置

主配置 `/etc/tesla-sentry.conf`（改完重启服务生效）：

| 变量 | 默认 | 作用 |
|---|---|---|
| `TSF_IMG` / `TSF_ARCHIVE` | `/opt/tesla-sentry/teslacam.img` / `/archive` | 虚拟 U 盘镜像 / 归档区 |
| `TSF_PORT` | `80` | 网页端口 |
| `TSF_LIVE_INTERVAL` | `15` | 在线只读同步轮询秒数 |
| `TSF_IDLE` | `600` | 镜像空闲秒数，仅用于 cron 挂载写 Boombox 音频 |
| `TSF_RECENT_ROLL_MIN` | `60` | RecentClips 滚动窗口（分钟），0 = 不滚动 |
| `TSF_BOX_KEEP_DAYS` / `TSF_BOX_MAX_GB` | `14` / `12` | 盒子侧哨兵 / 手动保存归档的保留天数与单分类上限，0 = 不限 |
| `TSF_FREE_MIN_MB` / `TSF_FREE_TARGET_MB` | `4096` / `10240` | 空间兜底清理的触发阈值与目标 |
| `TSF_CACHE` | 自动 | 缩略图 / 遥测 / 转码缓存目录 |
| `TSF_MDNS_NAME` | `tsl` | mDNS 主机名，对应 `http://tsl.local`；改完重启 avahi-daemon |

OTA、飞书推送、认证的参数**不写入这个 conf**，走环境变量（如 `TSF_OTA_SOURCES`、`TSF_OTA_REPO`）或网页配置。完整变量表与系统基线见 `docs/SYSTEM.md`。

网页 **⚙ 个性化** 有 11 个子页签：网络设置、文件、锁车语音、涂装、推送、账号、语言、网页背景、风扇、品牌、更新。存储盘选择和虚拟U盘创建在 **「个性化 → 车机U盘」** 里，不在首页。

- **品牌**：设置 → 品牌，标题栏左侧的图标（png/jpg/webp，≤3MB）与名称（≤24 字）都能换成自己的，改完立即生效、登录页同步；默认是内置的「TSL哨兵云盘」图标与名称，一键可恢复。

- **在线升级**：设置 → 更新，自动比对仓库 `version.json`，一键升级 / 回滚；配置与录像归档不在升级范围内。
- **飞书推送**：设置 → 推送，用自建应用私聊（仅本人）或群机器人 webhook，支持封面卡片与触发摄像头短视频，配好先点「发送测试」。
- **认证**：凭据在 `/opt/tesla-sentry/auth.conf`（权限 600）；删除该文件并重启即关闭认证（仅建议纯内网）。
- **U 盘管理模式**：点「连接车机U盘」会临时停止导出并挂载镜像，5 分钟无操作自动恢复；行车 / 哨兵活跃时不要长时间挂着。
- **锁车音**：WAV、44.1kHz、16-bit、<1MB、1–5 秒，文件名 `LockChime.wav` 写入 U 盘根目录。
- **API**：事件、媒体、遥测、上传、文件管理、OTA、推送等数十个接口，以 `sentry-viewer.py` 的 `do_GET` / `do_POST` / `do_DELETE` 为准。

改完配置重启服务：

```sh
/etc/init.d/tesla-viewer restart
/etc/init.d/tesla-live restart
/etc/init.d/tesla-gadget restart
```

---

## 常见问题

- **车机不认盘 / 提示格式化**：确认 `/sys/class/udc/` 有控制器、`grep exfat /proc/filesystems` 有输出，再跑 `/opt/tesla-sentry/tesla-gadget.sh status`。首次部署不再预建镜像，先在网页「个性化 → 车机U盘」完成选盘创建；创建成功会预置 exFAT + `TeslaCam`，正常不会再提示格式化。旧版安装留下的全零空盘重装时会自动补写。若虚拟盘超过 128G（车机同款布局的寻址上限），需要 `mkfs.exfat`（`apt install exfatprogs`），否则会退回空白盘由车机格式化一次；想手动补写可执行 `python3 /opt/tesla-sentry/mkexfat.py <镜像路径> <容量GB>`（镜像里有数据时它会拒绝覆盖）。
- **播放黑屏**：视频是 H.265 / HEVC，Windows 用 Edge / Chrome（需 HEVC 解码器）、iPhone Safari 原生支持，部分安卓浏览器不支持。
- **网页没有事件**：看 `/opt/tesla-sentry/` 下的 `tesla-live.log`、`tesla-sync.log`；先确认顶部同步状态胶囊在线，再核对归档目录与镜像路径。

### 检查更新失败（连不上 GitHub）

国内网络下 `raw.githubusercontent.com`、`fastly/testingcf.jsdelivr.net` 基本会被 RST 或 TLS 干扰，第三方反代也会时通时断，所以「检查更新」偶尔会报**所有下载源均不可用**。2.8.13 起的处理方式：

- 内置 7 个源（`ghfast.top`、`gcore.jsdelivr.net`、`ghproxy.net`、`gh-proxy.org`、`gh-proxy.com`、raw、jsDelivr）**并发竞速**，任一可用即可，不再按顺序一个个等超时；
- 报错会逐个列出失败的源及其原因（超时 / 连接被阻断 / 证书被劫持 / DNS 解析失败），一眼能看出是墙还是镜像挂了；
- 自动更新默认开启，网络恢复后每 5 分钟重试一次并自动升级，不用一直手点。

想自己加源，把可用的镜像写进配置即可（逗号分隔，`https://域名/<仓库路径>/main` 形式）：

```bash
echo 'TSF_OTA_SOURCES=https://ghfast.top/https://raw.githubusercontent.com/chyou38/rock3a-tslyun/main,https://gcore.jsdelivr.net/gh/chyou38/rock3a-tslyun@main' >> /etc/tesla-sentry.conf
/etc/init.d/tesla-viewer restart
```

**老版本（2.8.12 及更早）连检查都失败、进不了升级入口**时，直接在设备上手动覆盖一次，之后就回到自动更新：

```bash
wget -O /tmp/sv.py https://ghfast.top/https://raw.githubusercontent.com/chyou38/rock3a-tslyun/main/sentry-viewer.py \
  || wget -O /tmp/sv.py https://gcore.jsdelivr.net/gh/chyou38/rock3a-tslyun@main/sentry-viewer.py
python3 -m py_compile /tmp/sv.py && cp /tmp/sv.py /opt/tesla-sentry/sentry-viewer.py \
  && chmod 755 /opt/tesla-sentry/sentry-viewer.py && /etc/init.d/tesla-viewer restart
```

### 导出勾了水印，视频里却没有水印

设备端烧水印（`ffmpeg` + libass）需要**中文字体**。2.8.18 及更早版本在字体缺失时会静默跳过整条字幕链 —— 视频照样导出成功，但一个字都没有。2.8.19 起：

- 打开导出面板会显示「水印字体」状态；缺失时给出 **安装字体**（一键从官方 `google/fonts` 仓下载，约 17MB，多镜像重试）和 **上传**（本地 ttf/otf）两个按钮；
- 缺字体时导出会被明确拦下并提示，不会再给你一段没水印的视频；
- 字体探测会在 `/opt/tesla-sentry/fonts` 之外兜底扫描系统字体目录，已经装过字体的盒子升级后立刻可用。

命令行手动补字体（无外网时从别处拷贝也行）：

```bash
mkdir -p /opt/tesla-sentry/fonts
wget -O /opt/tesla-sentry/fonts/NotoSansSC.ttf \
  "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf" \
  || wget -O /opt/tesla-sentry/fonts/NotoSansSC.ttf \
  "https://ghfast.top/https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf"
ls -l /opt/tesla-sentry/fonts/     # 应约 17MB
/etc/init.d/tesla-viewer restart
```


---

## 安全提示

- `install.sh` 默认开启全站登录保护；**直接裸跑 `python3 sentry-viewer.py` 且没有 `auth.conf` 时认证是关闭的**，只可在可信内网使用。删除 `auth.conf` 仍是「关闭认证」的开关，但文件存在却读不出密码时服务会**拒绝启动**，不会静默裸奔。
- 登录页与 HTTP Basic 共用限速：同一 IP 10 分钟内错 8 次锁 5 分钟，Basic 方式也绕不过去。
- 上传限制 100MB，普通 JSON 接口请求体限制 1MB，单连接读写超时 30 秒、并发线程上限 48；路径被约束在归档区 / 镜像挂载点内，不可逃逸到系统目录。
- 认证与 Cookie 走 HTTP 明文，公网访问务必套 HTTPS 或 VPN；反向代理请传 `X-Forwarded-Proto: https`（或设置 `TSF_COOKIE_SECURE=1`），登录 Cookie 会自动带 `Secure`。

## 免责声明

本项目为个人爱好项目，与特斯拉公司无关。修改车机存储行为存在风险（数据丢失、录制中断等），请自行评估，建议先用小容量镜像验证。

## 参考与致谢

- [teslausb](https://github.com/marcone/teslausb) —— 树莓派伪装 U 盘归档的开山之作，本项目思路来源
- [SentryBox](https://github.com/weitanism/sentrybox) —— 车机常驻设备的产品化实践
- [tesla-sentry-viewer](https://github.com/denysvitali/tesla-sentry-viewer) —— 网页查看器形态参考

## License

[MIT](LICENSE)
