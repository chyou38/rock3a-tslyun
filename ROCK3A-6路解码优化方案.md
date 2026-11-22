# ROCK 3A 六路视频解码优化方案

> 日期：2026-11-21
> 设备：ROCK 3A（RK3568，4×Cortex-A55 @1.992GHz，2GB RAM）
> 系统：Armbian Debian 13，内核 6.18.44-current-rockchip64（mainline）
> 项目：tesla-sentry-f50（/opt/tesla-sentry，SSH 别名 teslausb）
> 状态：仅方案，未对盒子做任何变更

---

## 一、现状诊断（已实测）

| 项目 | 实测结果 |
|---|---|
| 六路软解速度 | 6×960×540@60fps，纯 CPU 软解仅 **0.443× 实时** |
| 当前 ffmpeg | Debian 13 官方 ffmpeg 7.1.5，**无 rkmpp、无 v4l2-request**，只有 v4l2m2m（stateful 封装） |
| VPU 硬解节点 | `/dev/video0 = rkvdec`（H.264/HEVC/VP9，驱动已绑定 fdf80100.video-codec）✅ 存在但完全没用上 |
| 其它硬件节点 | video1 = hantro（rk3328-vpu-dec）、video2 = vepu 编码器、video3 = rockchip-rga（mainline V4L2 M2M 版） |
| BSP 节点 | `/dev/mpp_service`、`/dev/rga` **不存在**（mainline 内核没有 Rockchip MPP/RGA 私有驱动） |
| CPU | 已跑满 1.992GHz，温度仅 21.9°C，**无降频**；governor = ondemand |
| 内存 | 2GB，可用约 1.6GB |
| GStreamer | 未安装，Debian 13 源里有（1.26.x） |
| 转码并发 | Q_SEM=2（注释按 8 核写的，实际 ROCK 3A 只有 4 核 A55） |

**瓶颈结论：不是频率、不是散热、不是 IO，是 A55 纯软解算力。**
RK3568 的 VPU 硬解能力为 4K60（约 4.98 亿像素/秒）：

- 6×540p60 ≈ 1.87 亿像素/秒 → 占 VPU 约 37%
- 6×特斯拉原片 1280×960@36fps ≈ 2.65 亿像素/秒 → 占约 53%

**硬解带 6 路绰绰有余，甚至 6 路 1080p30 也在能力范围内。**
当前 Debian 官方 ffmpeg 的 v4l2m2m 是 stateful 接口，驱动不了 mainline 的 stateless rkvdec，所以硬解节点在睡觉。

---

## 二、方案 A：启用 VPU 硬解（收益最大）

### A1. 保留当前 mainline 内核 + GStreamer stateless 硬解（低风险，先做）

不动内核、不动 OTG 配置，只装用户态软件：

```bash
apt install -y gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good
# Debian 13 的 GStreamer 1.26 自带 v4l2slh264dec（stateless H.264 硬解）

# 单路硬解基准测试（fpsdisplaysink 直接报 fps）：
gst-launch-1.0 filesrc location=/mnt/tsf-storage/tsf-data/archive/RecentClips/2026-11-21_15-20-00/front.mp4 \
  ! qtdemux ! h264parse ! v4l2slh264dec \
  ! fpsdisplaysink video-sink=fakesink sync=false text-overlay=false
```

- 验证通过后再起 6 个并行管道测总 fps。
- 备选：给 ffmpeg 打 Kwiboo/LibreELEC 的 v4l2-request 补丁自编译（h264_v4l2request），可继续用现有 ffmpeg 命令行体系，但要自己维护编译产物。
- **局限**：mainline 下 RGA 是 V4L2 M2M 设备，ffmpeg 没有对应滤镜，缩放/合成仍走 CPU；vepu 编码器 mainline 只支持 JPEG，H.264 编码仍走 libx264。
- **预期收益**：解码环节约 5–10×，CPU 从解码中解放出来专职缩放/编码，0.443× → 数倍实时。

### A2. 换 BSP vendor 内核 + ffmpeg-rockchip（最完整，风险较高）

要"6 路 1080p 合成导出全硬件"，这是最成熟路线：

1. 先整卡备份（dd 镜像），确认能回滚。
2. 切 Armbian vendor 内核（6.1 系）或 Radxa OS，获得 `/dev/mpp_service` + `/dev/rga`。
3. 装 rockchip-mpp + librga，用 nyanmisaka/ffmpeg-rockchip 或 jellyfin-ffmpeg（arm64 带 rkmpp/rga 构建）。
4. 全硬件管线示例（单路）：

```bash
ffmpeg -c:v h264_rkmpp -hwaccel_output_format drm_prime -i front.mp4 \
  -vf scale_rkrga=w=640:h=360:format=yuv420p \
  -c:v h264_rkmpp -b:v 2M out.mp4
```

- 6 路九宫格：每路 `h264_rkmpp` 解码 + `scale_rkrga` 缩放，再用 `overlay_rkrga` 链式拼屏，最后 `h264_rkmpp` 硬编，CPU 几乎零占用。
- **风险**：换内核会影响已调好的 OTG gadget（dwc3 peripheral overlay 是按当前内核 dtb 做的），需重新验证 UDC/gadget；USB 盘启动、fstab 也要复核。历史上多路 1080p 软解触发过内核 lockup 重启，硬解后这类问题从根上消失。
- **预期收益**：解码+缩放+合成+编码全硬件，6 路 1080p 合成导出可达实时甚至更快。

---

## 三、方案 B：播放走"零解码"（立即见效，不依赖硬解）

网页六路预览的最快路径是**盒子根本不解码**：

- 直接 HTTP 原片 mp4（支持 Range），浏览器/电脑 GPU 解 6 路——特斯拉原片就是 H.264，浏览器原生可播。
- 项目里已有"浏览器本机合成"路径（当初为避开设备端多路 1080p 内核重启而做），把它扩展为**所有多路预览的默认路径**。
- 水印（ASS/libass，CPU 大户）只在导出/推飞书时加，预览路径一律不加。
- 盒子端转码只保留给"推送导出"场景，且走缓存（现有 push-*.mp4 机制已具备）。
- **预期收益**：预览即点即播，"解码速度"变成网速/盘速问题；盒子负载≈0。

---

## 四、方案 C：软解参数调优（保留 CPU 解码时，约 1.5–2.5×）

1. **跳帧 + 跳过环路滤波**（预览画质损失很小，收益大）：

```bash
ffmpeg -skip_frame noref -skip_loop_filter all -i front.mp4 -f null -
```

2. **6 个独立进程各 `-threads 1`**，优于单个 6 输入 filtergraph：A55 上多进程并行更均匀，避免 xstack 强制同步等待和单进程内存压力。
3. **降预览规格**：监控预览 360p15 足够，540p60→360p15 像素量降约 8×；原片 36fps 没必要按 60fps 解。
4. **一次转码、永久缓存**：解码成本只付一次，回放走 stream copy（现有缓存目录机制保留，容量上限可从 2GB 适当上调）。
5. 预览编码用 `-preset ultrafast`（推送保留 superfast）；`-tune fastdecode` 可再降播放端压力。
6. Q_SEM=2 是按 8 核写的注释，4 核 A55 软解时 2×4 线程已打满，**软解阶段不要调高并发**；硬解落地后可提到 4–6。

---

## 五、方案 D：系统层

- **governor ondemand → performance**（或 schedutil）：突发解码升频更快；当前 22°C，无过热风险。持久化用 cpufrequtils 或 systemd unit。
- **内存**：2GB 偏紧，6 路 ffmpeg + filtergraph 注意 OOM；保留 oom_score_adj 策略，可加 zram。
- **IO**：视频在 USB 盘上，6 路并发读注意带宽（USB2 实际约 35MB/s）；确认盘插在 USB3 口，必要时用 iostat 验证是否 IO 瓶颈。
- **散热**：目前温度很低，无需动；长期满载硬解+硬编时再观察。

---

## 六、推荐实施顺序

| 步骤 | 内容 | 预期收益 | 风险 |
|---|---|---|---|
| 1 | 方案 B：预览改浏览器直解 + 方案 D governor | 预览即点即播 | 极低 |
| 2 | 方案 C：导出软解加 skip_frame/skip_loop_filter、降预览规格 | 软解 1.5–2.5× | 低（画质微损） |
| 3 | 方案 A1：装 GStreamer 验证 v4l2slh264dec 硬解 | 解码 5–10× | 低（不动内核） |
| 4 | 方案 A2：BSP 内核 + ffmpeg-rockchip 全硬件管线 | 6 路 1080p 合成实时 | 中高（先整卡备份，OTG 需重验） |

**基准测试方法**（每步前后各跑一次留档）：

```bash
# 软解基准
ffmpeg -benchmark -i front.mp4 -f null -
# 硬解基准（A1 落地后）
gst-launch-1.0 filesrc location=front.mp4 ! qtdemux ! h264parse ! v4l2slh264dec ! fpsdisplaysink video-sink=fakesink sync=false text-overlay=false
# 六路并行：起 6 个上述进程，看合计 fps 与 CPU 占用（top）
```