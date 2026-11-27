# tsf-doctor

TeslaBox 的只读体检工具。它是独立二进制，不写业务文件、不重启服务、不改配置，主服务异常时也能单独运行。

## 检查项

- `systemctl is-active sentry-viewer` / `tesla-live`
- `/proc/meminfo` 可用内存、`/proc/loadavg` 负载
- `sentry-viewer.py` / `tesla-live-sync.py` 进程与 RSS
- 系统盘、存储盘剩余空间
- `health.log` 最近异常
- 归档区事件数、`.part`、`.pruned`
- `/api/ver`、`/api/live`、`/api/storage/status`、`/api/events`、`/api/events_meta`、`/api/settings`
- 媒体 `HEAD` 的 `Content-Length` 数量、`Range` 206、缩略图 200

## 交叉编译（Windows → ROCK 3A arm64）

```powershell
$env:GOOS = "linux"
$env:GOARCH = "arm64"
$env:CGO_ENABLED = "0"
go build -trimpath -ldflags "-s -w" -o tsf-doctor-linux-arm64 .
```

## 安装

```sh
install -d /opt/tesla-sentry/bin
install -m 755 tsf-doctor-linux-arm64 /opt/tesla-sentry/bin/tsf-doctor
```

网页入口：个性化 → 系统体检。后端接口：`/api/doctor`，手动刷新使用 `/api/doctor?refresh=1`。
每次真实体检会写入 `/opt/tesla-sentry/doctor-history.jsonl`（内部 JSONL，含全部检查项）。`GET /api/doctor/history/download` 会把内部 JSONL 转成中文可读的 **TXT**，包含 OTG/USB 事件、gadget/同步/健康日志、内核 USB/解码事件、MPP NULL 次数与原因；`POST /api/doctor/history/clear` 清空日志。
