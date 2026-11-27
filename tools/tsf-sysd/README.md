# tsf-sysd

只读系统状态缓存服务，给系统体检提供热数据，避免每次体检冷启动 `journalctl` / `dmesg`。

## 边界

- 只读：不写业务文件、不改 configfs、不碰车机写入路径。
- 只监听 `127.0.0.1:8099`，不对外网暴露。
- `sentry-viewer` 连不上、未 ready 或数据超过 60 秒未更新时，自动回退原有 Python 采集。
- `Nice=5`、`MemoryMax=64M`、`CPUQuota=20%`，不抢车机写盘。

## 采集内容

- UDC 状态、当前/最高 USB 速率、mass_storage LUN。
- `watch.log` 的 OTG 状态变化、LUN、USB reset、ALERT 与心跳。
- `journalctl -b -u sentry-viewer.service` 的解码 MPP NULL 计数、原因和最近事件。
- `dmesg` 的 `wait task break by signal` 计数、dwc3 USB 事件。
- `tesla-gadget.log`、`tesla-sync.log`、`health.log` 最近片段。

## 接口

- `GET /status`：JSON，字段与 `sentry-viewer` 的 `system_logs` 对齐。
- `GET /healthz`：`ok`。

## 构建 / 安装

```powershell
$env:GOOS = "linux"
$env:GOARCH = "arm64"
$env:CGO_ENABLED = "0"
go build -trimpath -ldflags "-s -w" -o tsf-sysd-linux-arm64 .
```

```sh
install -m 755 tsf-sysd-linux-arm64 /opt/tesla-sentry/bin/tsf-sysd
install -m 644 scripts/tsf-sysd.service /etc/systemd/system/tsf-sysd.service
systemctl daemon-reload
systemctl enable --now tsf-sysd.service
```
