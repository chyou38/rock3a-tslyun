# TeslaBox v3.2.38 飞书告警漏发修复

## 本次漏发结论

`SentryClips/2026-11-27_19-26-02` 没有自动告警，是两层原因叠加：

1. 盒子默认路由在 `wlp1s0`，该 WiFi 当时没有外网，飞书 API 返回 `[Errno 113] No route to host`。
2. `notify_scan()` 连续失败 3 次后，把事件写入 `seen` 永久放弃；等网络恢复也不会再补发。

## 修复内容

### 1. 飞书专用 4G 路由

新增 `scripts/feishu-route.sh` 与 `systemd/tesla-feishu-route.service`：

- 开机等 `end1` 拿到 `192.168.70.x` 后，把飞书 CDN 的 `112.28.0.0/16`、`112.29.0.0/16` 固定走 4G 网关 `192.168.70.1`。
- 只影响飞书 API 网段，不影响局域网、Tailscale 和默认 WiFi 路由。
- 服务已 `systemctl enable`，重启后仍生效。

### 2. 失败不再永久记账

`notify_scan()` 新增 `retry` 状态：

- 推送失败只累加 `try`，不再写入 `seen`。
- 按 `30s → 60s → 120s → ... → 15min` 退避重试。
- 事件超过 6 小时才停止补发；短时断网、4G 切网、飞书 API 抖动都能自动补上。

## 验证

- `/api/ver` 返回 `3.2.38`；`tesla-live`、`sentry-viewer`、`tesla-feishu-route` 均 active。
- `ip route get 112.29.213.208` 返回 `via 192.168.70.1 dev end1 src 192.168.70.138`。
- 飞书 tenant token 获取成功（42 字符）。
- 本次事件已手动补发到飞书私聊；`notify-state.last.ok=true`。
- 自动化测试 35 项通过，新增“网络失败保留 pending、恢复后成功”回归用例。

## 边界

- 4G 与 WiFi 同时断网时，任何推送都无法送达；恢复后会在 6 小时内继续补发。
- 封面抽帧在车机正在写入时仍会让路，告警卡片可能没有封面，但文字和事件信息不受影响。
