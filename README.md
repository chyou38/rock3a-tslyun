# TSL哨兵云盘 · TSL Sentry Drive

> ⚠️ **法律与风险提示（必读）**
>
> 本项目是个人开源硬件改造项目，采用 MIT License，与 Tesla, Inc.（特斯拉）及其关联公司**无任何隶属、授权、赞助或背书关系**；“Tesla”“特斯拉”等商标归其权利人所有，本项目仅在描述兼容设备时作指代。
>
> 本项目仅供个人学习、研究与自有设备数据备份，**不得**用于商业运营、规避监管、侵犯他人隐私或其他违法用途。使用涉及车辆数据访问、USB 设备模拟、Wi-Fi 热点发射等行为，请自行确认符合所在地区法律法规与无线电管理规定；由此产生的车辆、数据、设备损坏或法律责任由使用者自行承担。
>
> 软件按“现状（AS IS）”提供，不附带任何明示或暗示担保。

**中文** | [English](README.en.md)

**V3.2.65** · 虚拟哨兵 U 盘 · 6 路同步回放 · SEI 行车遥测 · 硬解硬编 · 远程单流合成 · 作品库 · 水印导出 —— 仅适配 Radxa ROCK 3A（RK3568）。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.7+](https://img.shields.io/badge/python-3.7%2B-3776AB.svg)](https://www.python.org/)
[![零第三方依赖](https://img.shields.io/badge/deps-%E9%9B%B6%E7%AC%AC%E4%B8%89%E6%96%B9%E5%BA%93-brightgreen.svg)](#功能)

把 Radxa ROCK 3A（RK3568，2GB）顶替原车 U 盘插进手套箱：车机照常录制，手机连盒子 WiFi 或远程接入后打开网页，就能回看 4 / 6 路同步画面、逐帧读视频码流里的 SEI 遥测（挡位 / 车速 / 油门 / 刹车 / 方向盘 / 转向灯 / AP / 坐标），并导出带行车信息水印的视频。

本仓库只维护这一套硬件与系统：**Radxa 官方 Debian 12 bookworm BSP / 内核 6.1.84-15-rk2410-nocsf / Intel AX200 无线网卡**。旧 Armbian mainline（Debian 13 / 6.18.x）仍保留兼容代码，但新部署与实测以 BSP 为准。其他型号的开发板、路由器或 NAS 未适配，装不上或功能不可用，不在支持范围。

---

## 当前播放策略

这一版把“远程能不能稳定看到画面”放在第一位：所有等待期都有明确状态，不黑屏、不露大播放键，也不会把上一条记录的画面留在新片段上。

### 三种播放模式

| 模式 | 现在的行为 |
|---|---|
| **自动（默认）** | 局域网 / 私网直连走**六路原生**；公网 / Tailscale 走**服务端合成**。页面按 `/api/net_kind` 与访问地址自动判断，可在设置里手动锁定 |
| **六路原生** | 每路一条独立 HEVC 流，可切档、拖动、跨分钟段续播；画质和拖动的控制最完整，但对上行带宽要求最高 |
| **服务端合成** | 盒子把多路拼成一条实时 fMP4，手机只拉 1 条流，远程弱网优先用这个。第一版只支持连续播放，进度条不可拖动；**首帧 20 秒仍没有画面**才自动退回六路原生并提示。换一条记录会重新尝试合成，不会一次超时后永远退回六路 |

合成流的清晰度按当前档位封装；选择原画 / 1080p 时按 720p 合成，避免单条流过大。

### 画质与等待期

- 可选 **原画 / 1080p / 720p / 480p / 360p**；局域网主播放器默认原画，公网 / 远程默认 360p，哨兵总览默认 360p。手动选过会按网络类型分别记住。
- 后台优先给归档摄像头预热 **360p 前 30 秒**；480p / 720p 只在没人看视频、360p 空闲时补。行车记录与准实时预览不预热，点开时按需转码。
- 缓存没赶上时，播放器先用已有的低档（都没有才用原画）起播，不等转码；转码在后台跑，切段或下次打开自动用上目标档。
- 换片段 / 换画质时保留上一帧或模糊缩略图，右上角显示“缓冲中 / 转码中”；不会清空整组变黑，也不会出现白色大播放键。
- 换源后 6 秒没拿到 metadata 自动重挂一次（最多两次）；约 12 秒没有播放进度按 `原画 → 1080p → 720p → 480p → 360p` 逐级降档。
- 最低档 360p 仍无画面时，右上角提示可点重试；无进度路径还会在 10 秒后自动再重载一次，用户始终有上一帧 / 缩略图可看。
- 六路原生切换画质时每路错开 250ms 起流，避免同一毫秒六个请求一起抢占上行。

### 实时预览多路全景

单路“前视”正常；点“六路全景 / 四路全景”时，多路统一按 **480p** 起播（单路仍按用户档位），每路错开 500ms，8 秒没 metadata 自动重挂一次；只要不是用户自己按了暂停，数据到了会自动续播。这样保证 4 / 6 格先全部出画，而不是只剩一两格。

---

## 功能

| 能力 | 说明 |
|---|---|
| 🗂 虚拟 U 盘 | **安装时不预建镜像**；部署后打开网页「个性化 → 车机U盘」里的「设备与存储」，插入任意容量 USB 硬盘（整盘 ≥8G）→ 选择整块盘 → 拖动虚拟U盘占比 → 输入序列号格式化创建。创建的是稀疏 exFAT 镜像并预置 `TeslaCam` 目录，通过 USB Gadget `mass_storage` 导出；网卡 / 串口共存。也可在安装时用 `--size` 显式预建。 |
| ⚡ 定时归档 | `tesla-live-sync.py` **只读解析 exFAT**（不挂载、不断 USB），默认**每 10 分钟归档一次**，间隔在网页「个性化 → 虚拟硬盘 → 归档区」自定义（1–1440 分钟），另有**「立即归档」**按钮；**检测到车机正在写 U 盘一律顺延**，停止写入后再搬，搬运途中车机开始写盘也会暂停让路，不与车机抢读写。BSP 版不需要 cron 同步，另有 1 秒级 USB 自愈狗。 |
| 📦 归档与滚动窗口 | 视频落到独立归档目录（BSP 在 USB 数据盘，旧 Armbian 为独立 ext4 `/archive`），不与车机同时读写镜像；`RecentClips` 跟随车机滚动缓冲只留最近 60 分钟，`SentryClips` / `SavedClips` 的**盒子副本**归档保留统一走网页「个性化 → 文件 → 归档区」按容量水位清理，`.pruned` 墓碑避免「删除→重抄」死循环。 |
| 🎬 回放 | 默认按设置显示全览：4 路 2×2、6 路 3×2；下方机位条可切前视 / 后视 / 左B柱 / 右B柱 / 单路，切换保留进度。全览每秒对齐、统一进度条，速度 **0.5x / 1x / 2x**；跨分钟段自动续播，支持跨段拖动。**自动落在触发时刻所在的那一分钟、从触发前 5 秒起播**（片段栏红点标记）。截屏按钮把当前画面存成 PNG，并提示保存位置。 |
| 📊 遥测与元数据 | 直读码流内嵌 SEI protobuf：挡位 / 车速 / 油门 / 刹车 / 方向盘角度 / 转向灯 / AP 状态 / 坐标 / 三轴加速度，随进度逐帧跳动；`event.json` 提供时间 / 城市 / 街道 / 触发原因 / 触发画面。**没有 SEI 的停车哨兵片段整块隐藏，不留空壳。** |
| 🔍 筛选与预览 | 触发原因 + 日期胶囊叠加筛选；`?ev=` `?date=` `?cat=` `?cam=` `?exp=1` 深链；📡 实时预览与其它分类同级（点页签即切换，不用返回），带 原画 / 1080p / 720p / 480p / 360p 画质选择；存储条（虚拟U盘按卷内实际写入量计，不是镜像预分配占用；进度条按占用比例配色：<30% 绿 / 30–85% 蓝 / >85% 红）与在线同步状态。 |
| 📶 清晰度 | 见上文「画质与等待期」。播放可选原画 / 1080p / 720p / 480p / 360p（服务端转码缓存，上限 2GB）。**不是固定 480p 默认**，而是局域网原画、公网 / 远程 360p，并按网络分别记住手动选择。缓存没赶上时先用已有低档 / 原画起播，后台转码，切段或下次打开再用目标档。 |
| 🎬 播放模式 | 设置 → 界面与播放可选 **自动 / 六路原生 / 服务端合成**。行为见上文「三种播放模式」。单路播放和导出链路不受影响。 |
| 🎞 导出 | 单路下载、zip 打包、多路合成（2 路 2×1 / 3 路下排铺满 / 4 路 2×2 / **6 路 3×2**）；清晰度 原画 / 720p / 480p / 360p，**多画面按原片 4:3 取格子，不留黑边**（原画单路直接出 1280×960 + 源帧率）；带水印时一律由设备端 ffmpeg 直出 H.264 mp4（+faststart，微信 / 相册可直接发）；水印与网页播放器同款（左侧时间 / 地点，右侧车速 / 转向灯 / 挡位 / 刹车 / 油门，外加 **AP 方向盘图标**：辅助驾驶启动时蓝色、未启动时灰色）；片段没有行车遥测（停车哨兵录制）时水印退化成只显示时间 + 地点，不会悄悄不出水印。**全程 ffmpeg-rockchip 硬解 + RGA 缩放 + h264_rkmpp 硬编**：单路 50 秒 4K 级源片约 7 秒，6 路 50 秒素材带水印合成约 54 秒。 |
| 💾 我的作品库 | 合成 / 导出成品统一落作品库（不再随临时目录 1~2 小时被清），网页 header 文件夹按钮随时下载、补推飞书、删除；**保留天数网页可选 1~180 天（默认 7 天）**，改小立即清超期，另有后台每 30 分钟兜底清理；容量硬顶 20GB，先按天数再按容量淘汰。 |
| 📂 文件管理 | U 盘 / 归档区浏览上传下载，多选批量删除 / 移动 / 复制 / 重命名（realpath 防逃逸）；一键清空 `TeslaCam/` 全部录像（保留目录结构、不动 Boombox / Wraps）；U 盘管理模式 5 分钟无操作自动恢复导出。车机U盘页带**行车锁**开关（默认开）：车机正在写 U 盘（行车中）时禁止连接/读取虚拟U盘镜像，看门狗每 3s 自动上锁/解锁、异常挂载主动归还车机；**归档区是独立副本，回放/实时预览不受影响**。 |
| 🔔 飞书推送 | 私聊（仅本人）/ 群机器人：作品推送先发**说明卡**（封面取合成首帧 + 时间 / 位置 / 镜头（N 路）/ 时长·大小 + **「查看录像」按钮**，直达 6 路分格播放页），再发带封面的视频消息；触发那一帧封面卡片或触发点前 5 秒短视频，可烧行车信息水印；去重、延迟 20 秒、失败重试 3 次。 |
| 🔐 登录保护 | `install.sh` 默认生成随机 10 位密码（admin），HMAC 签名 cookie 保留 30 天 + HTTP Basic；10 分钟内连错 8 次返回 429；设置 → 账号可改密码 / 退出。 |
| 🌐 内网固定地址 | 安装时尝试启用 Avahi mDNS，在局域网广播 `http://tsl.local`（默认主机名 `tsl`，`--mdns NAME` 可改）；换 IP 不用重新记地址。仅同一局域网有效，标准 mDNS 只支持 `.local` 后缀。 |
| 🔄 在线升级 | 多源并发竞速 + GitHub API 实时兜底；`version.json` 使用 Ed25519 签名 + 发布文件 SHA-256 校验，下载后校验 → 备份 → 原子替换 → 自动重启，出问题一键回滚。设置 → 更新里可切换**稳定版 `main` / 测试版 `beta`**；自动更新默认开启，但车机正在写 U 盘、live-sync 正在搬录像、网络回滚未确认或播放/合成任务运行时一律推迟。 |
| 🎨 个性化 | 标题图标与名称可自定义（默认「TSL哨兵云盘」）、深 / 浅 / 自动主题，4 套界面风格（默认 / Apple / Claude / 像素），10 种界面语言、网页背景换肤、锁车音（`LockChime.wav`）、涂装 `Wraps/`。 |
| 🛡 稳定性 | 归档区 ext4 日志式、开机自检、服务自动拉起、**USB 自愈狗 1 秒级监控，车机 U 盘被弹出或异常断开时立即热挂回，失败再完整恢复；你主动点「连接」管理时自动暂停让路，并显示本次开机累计触发次数**、断电自愈。仓库另带可选的 `scripts/tsf-watch.sh`：每 10 秒心跳、异常写本地 `/opt/tesla-sentry/watch.log`；默认**不推 CmaFree 低水位飞书告警**（该值在 RK3568 上长期 0–1MB 属正常波动），需要恢复时在服务里设 `TSF_WATCH_ALERT_CMA=1`。 |

---

## v3.2.65 更新（2026-11-28）

- 修复通知设置未接收 `app_ws_open` 的问题：内网免令牌 WebSocket 开关现在能真正保存。
- 新增本机设置上传代理：品牌图标、锁车音频、Wraps 图片可经本机网关直接上传。
- 设置中心补齐上传、删除、存储初始化、清空 `TeslaCam` 入口。
- 全量自动化测试通过，OTA 清单已重新签名。

## v3.2.56 更新（2026-11-28）

- 内网免令牌 WebSocket 放行 Tailscale `100.64.0.0/10` 网段；手机直连 tailnet IP 时不再需要令牌。
- 新增 CGNAT 来源测试；全量 90 项测试通过。
- 可用直连地址 `ws://192.168.1.100/api/app/ws` 绕开 Tailscale Serve 的 TLS/DNS 路径。

## v3.2.55 更新（2026-11-28）

- 新增 `[APP-WS]` 诊断日志：记录 WebSocket 握手来源、鉴权方式、是否带 token、拒绝码、连接/断开，不打印令牌。
- 通知设置页显示 WebSocket 是否已连接；新增「内网免令牌 WebSocket」开关，默认关闭，仅内网/Tailscale 来源生效，公网直连仍拒绝。
- `/api/notify` 增加 `app_ws_open` / `app_ws_active`，可直接确认手机端有没有连上来。
- 全量 89 项测试通过。

## v3.2.54 更新（2026-11-28）

- 新增外部通知客户端「WebSocket 推送」实时通道：`GET /api/app/ws`，连接建立后服务端主动推送 `title` / `body` / `url`，哨兵事件触发即弹通知，不再受客户端 5 分钟轮询限制。
- WebSocket 使用独立通知令牌鉴权，支持 `?token=` 或 `Authorization: Bearer`；连接时自动补发离线积压通知，送达后出队，避免重连重复弹。
- 通知设置页新增 WebSocket 地址与一键复制；外部通知客户端通知类型选「WebSocket 推送」并填入该地址即可，轮询仍作为备用。
- 补充 WebSocket 帧、握手和实时送达出队测试；全量 89 项测试通过。

## v3.2.53 更新（2026-11-28）

- 新增外部通知客户端「轮询通知」专用接口 `GET /api/app/poll`：返回裸 JSON 数组，字段 `title` / `body` / `url`，取走即出队。
- 通知设置里的轮询地址改为该接口；外部通知客户端通知类型选「轮询通知」，间隔填 5 分钟（客户端最小 5 分钟）。
- 保留原有 `GET /api/app/notifications` 增量接口与 `POST /api/app/notifications/ack`，自定义客户端不受影响。
- 修复外部通知客户端把对象响应误解析成空通知的问题。

## v3.2.52 更新（2026-11-28）

- 网页补齐 PWA 配置：`manifest.webmanifest`、192/512 图标、`theme-color`、`apple-touch-icon`、`service worker`，外部通知客户端可识别为 PWA。
- PWA 名称/短名为「TSL哨兵云」/「哨兵云」，图标直接复用当前品牌 LOGO，不新增或覆盖用户图片。
- 登录页与主页面都注入 PWA 元信息；`manifest.webmanifest`、图标、`sw.js` 免登录可访问，未登录也能安装。
- Service Worker 不缓存页面、API、`version.json` 与媒体，避免 PWA 缓存旧版本或让通知失效。

## v3.2.51 更新（2026-11-28）

- 个性化新增「通知设置」：独立通知开关、随机访问令牌、轮询地址、测试通知；不替代飞书，可同时开启。
- 待取通知：`GET /api/app/notifications?token=...&after=...` 增量拉取，`POST /api/app/notifications/ack` 已读回执；外部通知客户端用 `GET /api/app/poll?token=...` 取裸数组（取走即出队）。均支持 Tailscale 内网访问。
- 哨兵 / 手动保存 / 巡检事件可写入通知队列，通知深链直接打开对应事件；外部通知客户端用 URL 轮询即可。
- 82 项自动化测试通过。

---

## v3.2.50 更新（2026-11-28）

- 完成 12 项安全 / 运行审计修复：OTA 清单 Ed25519 签名 + 文件 SHA-256、`--dir` 状态路径统一、导出/分享任务 id 路径穿越、登录 `next` 注入、网络回滚落盘、幽灵簇回收 journal、上传前置上限、飞书 token 凭据绑定、登录失败表上限等。
- 自动升级增加车机门禁：车机正在写 U 盘、live-sync 正在搬录像、网络回滚未确认或播放/合成任务运行时一律推迟，不重启 viewer/live-sync。
- OTA 支持稳定版 `main` / 测试版 `beta` 切换；当前两者均为 v3.2.50，更新页显示本机版本说明，旧镜像缓存不会再被当作“最新版本”。
- 盒子端已部署 v3.2.50，78 项自动化测试通过；升级前保留上一版备份，可在更新页一键回滚。

---

## 3.0.2 更新（2026-11-26）

- 修掉“切片段后下半三格还留在上一条记录”的冻结帧：换记录 / 换分钟段立即清空复用格子的 `hold` 与冻结图，新片段只显示自己的模糊缩略图。
- 换档不再“六路只活一路”：每路强制 `load()`、错开 250ms 起流，6 秒没 metadata 自动重挂（最多两次）；12 秒没进度按阶梯降档，手动锁定档也会降。
- 最低档 360p 仍无画面不再干等：右上角给出**可点重试**，无进度路径 10 秒后自动再重载一次。
- 服务端合成首帧等待从 8 秒放宽到 **20 秒**；换记录会重新尝试合成，避免一次超时后整个会话都退回六路。
- 实时预览六路 / 四路全景：统一 480p 起播、每路错开 500ms、8 秒没 metadata 自动重挂；非用户暂停时自动续播，六格能全部出画。
- 截屏增加“截图已保存到下载目录”提示；实时状态栏只有连续两次检查失败才显示“检查暂时不可达”，不再被偶发上行占满误报。
- 播放条移除不适用的“横屏 / 竖屏”按钮。
- 巡检 CmaFree 低水位告警默认关闭，本地日志仍保留。

---

## V3 基线（3.0.0，2026-11-25）

V3 是切到 **Radxa 官方 Debian 12 BSP（内核 6.1.84）** 后的第一个发布版本，主线是「全链路硬件化 + 作品库」：

**硬解 / 硬编**

- 系统 ffmpeg 换成自编译 **ffmpeg-rockchip 9.1**（`/opt/rkmpp/bin/ffmpeg|ffprobe`，GPL v3，静态链 libav*），`install.sh` 自动安装，`dist/rkmpp` 带离线包。
- 所有转码路径切硬解：缩略图、预缓冲（360p 优先）、推送短视频、浏览器片段、6 路合成导出；输出用 `h264_rkmpp`，缩放用 `scale_rkrga`。
- 同一 29s 4K 级源片实测：软编 36s → GStreamer 11.8s → **ffmpeg-rkmpp 7.4s**。
- 6 路 50.6s 素材带水印合成 **54.4s**（1668×720，峰值温度约 45°C，可用内存剩 1.5G）；水印字幕本身只占 0.2s，瓶颈是 4K 级源片解码；**3 路并行降采样实测反而更慢（MPP 实例排队），保持顺序执行**。

**功能**

- 作品库：成品落 `/mnt/tsf-storage/tsf-data/exports`，网页「我的作品」下载 / 推飞书 / 删除；保留天数 1~180 天可选（默认 7 天），后台每 30 分钟定时清理，20GB 容量硬顶。
- 飞书作品推送：说明卡（时间 / 位置 / 镜头（N 路）/ 时长·大小）+ 封面 + **「查看录像」** 按钮（直达 `?ev=` 6 路分格播放页）。
- 6 路合成放开（3×2 格子 1668×720），逐路 RGA 降采样 + xstack + 统一烧一次水印。
- 清理新系统遗留：删掉失效的 `tesla-sync` cron 与 `_hw_preview/_rkvdec_nodes` 死代码（BSP 无 `/dev/media*`），统计只认 ffmpeg，前端去掉 GStreamer 文案。

**系统**

- 网卡 AX200（`iwlwifi`）：WiFi STA + 2.4G 热点共存（NM 只接管 `end1`，`wlp1s0/ap0` unmanaged，`wpa_supplicant@wlp1s0` + `udhcpc`）。
- 主机名、时区（Asia/Shanghai）、风扇（BSP `pwm-fan`）、USB Gadget 直写 `mass_storage.0/lun.0/file`。

---

## 适配设备（仅 ROCK 3A）

本仓库只针对 **Radxa ROCK 3A（RK3568）** 维护和验证；其他型号的开发板、路由器或 NAS 未适配，装不上或功能不可用，不在支持范围。

| 项目 | 本机实测 |
|---|---|
| 主板 | Radxa ROCK 3A（RK3568，4× Cortex-A55） |
| 内存 | 2GB（可用 1.9GiB） |
| 系统盘 | eMMC 58.3GB（`mmcblk0`，根分区约 57GB） |
| 数据盘 | USB 470GB（`sda1`，ext4，挂 `/mnt/tsf-storage`，存镜像/归档/缓存） |
| 系统 | Radxa 官方 Debian 12 bookworm BSP |
| 内核 | `6.1.84-15-rk2410-nocsf`（aarch64，BSP） |
| 无线网卡 | Intel Wi-Fi 6 AX200（`8086:2723`，iwlwifi） |
| 蓝牙 | AX200 集成 USB（`8087:0029`，正常枚举时 hci0/hci1） |
| 有线网卡 | `end1` 千兆，NetworkManager DHCP（旧 Armbian 为 `end0`） |
| 风扇 | BSP `pwm-fan` 驱动（hwmon `pwmfan` / `pwm1`，25kHz）；旧 mainline 需 `rock3a-pwm8-fan` overlay |
| USB | USB3 OTG 口做 Gadget，接车机 |

**已使用**：USB3 OTG（车机）、`end1`（有线）、AX200（WiFi STA + 2.4G 热点）、蓝牙、PWM 风扇座、eMMC（系统）、USB 数据盘（镜像/归档/缓存）。
**未使用**：HDMI、USB Host、M.2、音频等接口本方案不依赖，保持空闲。

**硬门槛**：`/sys/class/udc/` 非空、configfs + `USB_F_MASS_STORAGE`、内核 exFAT、loop / losetup、root，且车机 USB 口能供电。系统必须是 Debian 12/13（BSP 或 Armbian）systemd；Python 3.7+（查看器零第三方依赖）；ffmpeg 只影响缩略图与转码，缺失不阻塞安装。

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

# BSP 单盘（USB 数据盘挂 /mnt/tsf-storage）推荐把归档和缓存都放数据盘：
sudo ./install.sh --archive /mnt/tsf-storage/tsf-data/archive \
                  --cache   /mnt/tsf-storage/tsf-data/cache
```

安装会：先校验主板是否为 ROCK 3A（RK3568）→ 检查内核 gadget / exFAT / Python → **自动安装仓库自带的 ffmpeg-rockchip（`dist/rkmpp`，硬解硬编，失败只警告）** → 装到 `/opt/tesla-sentry/`、写 `/etc/tesla-sentry.conf` → 尝试安装并启用 Avahi mDNS → 注册 `tesla-gadget` / `sentry-viewer` / `tesla-live` / `pwm-fan-control` / `tsf-ap-policy.timer` 等 systemd 服务与一条 cron（`*/2` 的 U 盘 LUN 自愈）；检测到 NetworkManager（BSP）时额外配置 `wlp1s0/ap0` unmanaged、`wpa_supplicant@wlp1s0`、`tsf-wifi-dhcp`、`tsf-bt-name` → 生成随机登录密码 → 创建作品库目录 → 启动并打印状态。字体、部分内核项缺失只警告不中止。**默认不建盘，安装完成后由你在网页里选择硬盘和容量。**

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

## RKMPP 硬解 / 硬编（BSP 必装）

BSP 内核带 `/dev/mpp_service` 与 `/dev/rga`，仓库提供自编译的 ffmpeg-rockchip 产物（GPL v3，静态链 libav*）：

- `dist/rkmpp/rkmpp-bin.tar.gz`：`ffmpeg` / `ffprobe` 二进制（约 21MB，已 strip）
- `dist/rkmpp/install-rkmpp.sh`：恢复脚本，自动检查运行时依赖、软链系统 `ffmpeg`/`ffprobe`，并写入 `TSF_FFMPEG` / `TSF_FFPROBE`
- `dist/rkmpp/deps.txt`：运行时依赖清单（Debian 12）

`install.sh` 检测到 `/opt/rkmpp/bin/ffmpeg` 不存在时会**自动调用** `install-rkmpp.sh -y`；也可手动：

```sh
cd dist/rkmpp
sudo bash install-rkmpp.sh -y      # 缺依赖时自动 apt 安装
sudo systemctl restart sentry-viewer
```

装好后 `ffmpeg -encoders | grep rkmpp` 应能看到 `h264_rkmpp`/`hevc_rkmpp`，`-filters | grep rkrga` 应能看到 `scale_rkrga`。没有 `/dev/mpp_service` 的 mainline 内核只能软解，硬解不可用。

---

## 配置与常用设置

主配置 `/etc/tesla-sentry.conf`（改完重启服务生效）：

| 变量 | 默认 | 作用 |
|---|---|---|
| `TSF_IMG` / `TSF_ARCHIVE` | `/opt/tesla-sentry/teslacam.img` / `/archive` | 虚拟 U 盘镜像 / 归档区；BSP 单盘部署为 `/mnt/tsf-storage/tsf-data/teslacam.img` / `.../archive` |
| `TSF_PORT` | `80` | 网页端口 |
| `TSF_LIVE_INTERVAL` | `15` | 在线只读同步轮询秒数 |
| `TSF_IDLE` | `600` | 镜像空闲秒数，仅用于 cron 挂载写 Boombox 音频 |
| `TSF_RECENT_ROLL_MIN` | `60` | RecentClips 滚动窗口（分钟），0 = 不滚动 |
| `TSF_BOX_KEEP_DAYS` / `TSF_BOX_MAX_GB` | `0` / `0` | 旧方案 B 的盒子侧保留天数与单分类上限，默认关闭；归档保留统一走网页「个性化 → 文件 → 归档区」 |
| `TSF_FREE_MIN_MB` / `TSF_FREE_TARGET_MB` | `4096` / `10240` | 空间兜底清理的触发阈值与目标 |
| `TSF_CACHE` | `<安装目录>/cache` | 缩略图 / 遥测 / 合成临时缓存；BSP 部署为 `/mnt/tsf-storage/tsf-data/cache` |
| `TSF_LIB` | `/mnt/tsf-storage/tsf-data/exports` | 作品库目录（合成 / 导出成品）；保留天数在网页「我的作品」里改（1~180 天，存 `settings.json` 的 `lib_ttl_days`），容量硬顶 20GB |
| `TSF_VPU_TRANSCODE_ON` / `TSF_TR_CODES` | `1` / `3` | 硬转开关 / 并发路数；RK3568 只有一个硬编实例，3 是长期实测的平衡点 |
| `TSF_PREVIEW_CACHE` | `/opt/tesla-sentry/preview-cache` | 预缓冲缓存；默认在 eMMC，建议 BSP 改到数据盘（`/mnt/tsf-storage/tsf-data/preview-cache`） |
| `TSF_PREWARM` | `1` | 后台预缓冲开关；设 `0` 关闭，播放时按需转码 |
| `TSF_MDNS_NAME` | `tsl` | mDNS 主机名，对应 `http://tsl.local`；改完重启 avahi-daemon |

OTA、飞书推送、认证的参数**不写入这个 conf**，走环境变量（如 `TSF_OTA_SOURCES`、`TSF_OTA_REPO`）或网页配置。完整变量表与系统基线见 `docs/SYSTEM.md`。

网页 **⚙ 个性化** 包含网络设置、文件、车机U盘、锁车语音、涂装、推送、账号、语言、网页背景、风扇、品牌、系统体检、更新等页面。存储盘选择和虚拟U盘创建在 **「个性化 → 车机U盘」** 里，不在首页。

- **系统体检**：个性化 → 系统体检，调用独立 Go 只读工具 `tsf-doctor`，检查服务、内存/负载/磁盘、进程 RSS、health.log、归档 `.part/.pruned`、关键 API、媒体 HEAD/Range 与缩略图；不写业务文件、不重启服务、不改配置。进入页面只加载已有记录，不会自动检查或拉日志；只有点「立即检查」才执行 `/api/doctor?refresh=1`、写一条内部 JSONL 记录并生成本次开机全量日志。记录在 `/opt/tesla-sentry/doctor-history.jsonl`（保留最近 120 条）；页面可展开全部检查项、每条记录下方单独下载 **TXT 可读日志**或清空。每条记录的日志在生成时落独立快照（硬链接共享压缩缓存，后续重建不会串记录），下载从快照流式解压，不整段读入内存。单条 TXT 包含该次接口/检查问题、OTG/USB 连接/断开与 LUN、USB reset 次数、gadget/同步/健康日志、内核 dwc3 USB 事件、MPP 视频解码 NULL/等待中断，以及本次开机至今的 watch/health/gadget/sync、**全部 systemd 服务 journal** 与 dmesg（缓存在 `/opt/tesla-sentry/doctor-history-logs/`）。页面 MPP 摘要取 journal 最近 8000 行，下载为本次开机全量口径。另可选装常驻 Go 缓存服务 `tsf-sysd`（`tools/tsf-sysd/README.md`），体检优先读它的内存快照；服务未起/未 ready/数据过期超过 60 秒时自动回退 Python 采集。

- **品牌**：设置 → 品牌，标题栏左侧的图标（png/jpg/webp，≤3MB）与名称（≤24 字）都能换成自己的，改完立即生效、登录页同步；默认是内置的「TSL哨兵云盘」图标与名称，一键可恢复。
- **在线升级**：设置 → 更新，自动比对仓库 `version.json`，一键升级 / 回滚；配置与录像归档不在升级范围内。
- **飞书推送**：设置 → 推送，用自建应用私聊（仅本人）或群机器人 webhook，支持封面卡片与触发摄像头短视频，配好先点「发送测试」。
- **认证**：凭据在 `/opt/tesla-sentry/auth.conf`（权限 600）；删除该文件并重启即关闭认证（仅建议纯内网）。
- **U 盘管理模式**：点「连接车机U盘」会临时停止导出并挂载镜像，5 分钟无操作自动恢复；行车 / 哨兵活跃时不要长时间挂着。
- **锁车音**：WAV、44.1kHz、16-bit、<1MB、1–5 秒，文件名 `LockChime.wav` 写入 U 盘根目录。
- **API**：事件、媒体、遥测、上传、文件管理、OTA、推送等数十个接口，以 `sentry-viewer.py` 的 `do_GET` / `do_POST` / `do_DELETE` 为准。

改完配置重启服务：

```sh
systemctl restart sentry-viewer
systemctl restart tesla-live
systemctl restart tesla-gadget
```

---

## 常见问题

- **车机不认盘 / 提示格式化**：确认 `/sys/class/udc/` 有控制器、`grep exfat /proc/filesystems` 有输出，再跑 `/opt/tesla-sentry/tesla-gadget.sh status`。首次部署不再预建镜像，先在网页「个性化 → 车机U盘」完成选盘创建；创建成功会预置 exFAT + `TeslaCam`，正常不会再提示格式化。旧版安装留下的全零空盘重装时会自动补写。若虚拟盘超过 128G（车机同款布局的寻址上限），需要 `mkfs.exfat`（`apt install exfatprogs`），否则会退回空白盘由车机格式化一次；想手动补写可执行 `python3 /opt/tesla-sentry/mkexfat.py <镜像路径> <容量GB>`（镜像里有数据时它会拒绝覆盖）。
- **播放黑屏**：视频是 H.265 / HEVC，Windows 用 Edge / Chrome（需 HEVC 解码器）、iPhone Safari 原生支持，部分安卓浏览器不支持。远程弱网优先用“服务端合成”模式（设置 → 界面与播放），只拉一条流。
- **网页没有事件**：看 `/opt/tesla-sentry/tesla-live.log`，以及 `journalctl -u sentry-viewer -n 50 --no-pager`；先确认顶部同步状态胶囊在线，再核对归档目录与镜像路径。
- **切档后要等很久**：首次切到未缓存的 480p / 720p 需要盒子现场转码，六路原生会一条条出画；等待期保留上一帧 / 模糊缩略图，右上角有状态。着急可先停在 360p，或用服务端合成单流。
- **360p 仍无画面**：右上角提示可点重试；点一下会重新拉当前段。若一直失败，检查盒子负载与存储（`uptime`、`df -h`、`systemctl status sentry-viewer`）。

### 检查更新失败（连不上 GitHub）

国内网络下 `raw.githubusercontent.com` 及部分镜像可能被 RST 或 TLS 干扰，第三方反代也会时通时断，所以「检查更新」偶尔会报**所有下载源均不可用**。2.8.13 起的处理方式：

- 内置多个源（`ghfast.top`、`fastly.jsdelivr.net`、`testingcf.jsdelivr.net`、`gcore.jsdelivr.net`、`ghproxy.net`、`gh-proxy.org`、`gh-proxy.com`、raw、jsDelivr）**并发竞速**，任一可用即可，不再按顺序一个个等超时；
- 报错会逐个列出失败的源及其原因（超时 / 连接被阻断 / 证书被劫持 / DNS 解析失败），一眼能看出是墙还是镜像挂了；
- 自动更新默认开启，网络恢复后每 5 分钟重试；车机正在写 U 盘、live-sync 正在搬录像、网络回滚未确认或播放/合成任务运行时不会升级，会等空闲后再试。

想自己加源，把可用的镜像写进配置即可（逗号分隔，`https://域名/<仓库路径>/main` 形式）：

```bash
echo 'TSF_OTA_SOURCES=https://ghfast.top/https://raw.githubusercontent.com/chyou38/rock3a-tslyun/main,https://gcore.jsdelivr.net/gh/chyou38/rock3a-tslyun@main' >> /etc/tesla-sentry.conf
systemctl restart sentry-viewer
```

**老版本（2.8.12 及更早）连检查都失败、进不了升级入口**时，直接在设备上手动覆盖一次，之后就回到自动更新：

```bash
wget -O /tmp/sv.py https://ghfast.top/https://raw.githubusercontent.com/chyou38/rock3a-tslyun/main/sentry-viewer.py \
  || wget -O /tmp/sv.py https://gcore.jsdelivr.net/gh/chyou38/rock3a-tslyun@main/sentry-viewer.py
python3 -m py_compile /tmp/sv.py && cp /tmp/sv.py /opt/tesla-sentry/sentry-viewer.py \
  && chmod 755 /opt/tesla-sentry/sentry-viewer.py && systemctl restart sentry-viewer
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
systemctl restart sentry-viewer
```

### 巡检脚本（可选）

仓库带 `scripts/tsf-watch.sh`，每 10 秒采一轮 USB / 内存 / 温度 / 服务状态，异常写 `/opt/tesla-sentry/watch.log`；需要飞书告警时经 viewer 回环接口复用推送配置。**CmaFree 低水位默认不推飞书**（RK3568 上 0–1MB 属正常波动），要恢复把 `TSF_WATCH_ALERT_CMA=1` 写进 systemd 环境。

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
