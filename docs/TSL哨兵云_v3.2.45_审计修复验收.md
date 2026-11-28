# TSL哨兵云 v3.2.45 审计修复验收

- 仓库：`/var/lib/openbot/tslusb/wt-update-channel`
- 分支：`beta`
- 代码提交：`7b109e0`（v3.2.45 收口）
- 基线提交：`43d1aa1`（v3.2.44 12 项审计修复）
- 盒子版本：`3.2.45`（`/api/ver` 已确认）
- 自动化测试：`76 tests OK`
- 部署状态：`sentry-viewer`、`tesla-live` 均为 active
- 回滚备份：`/opt/tesla-sentry/sentry-viewer.bak.py` 为 v3.2.44

## 12 项审计修复

| # | 问题 | 修复 | 验证 |
|---|---|---|---|
| 1 | OTA 可被镜像/CDN 换包后自动执行 | `version.json` 增加 Ed25519 签名与发布文件 SHA-256；设备端先验签/校验哈希，再 `py_compile` + `--ota-check` | `test_repo_manifest_signature_verifies`、`test_tampered_signed_manifest_rejected`；盒子 `openssl` 可用 |
| 2 | `--dir` 自定义安装时认证/设置路径分裂 | `RUNTIME_DIR` 统一由 `TSF_DIR` 决定；settings/auth/notify/OTA/日志/缓存全部跟随安装目录；`install.sh` 写入对应环境变量 | `CustomDirPathTests`，子进程 `TSF_DIR` 导入验证 |
| 3 | 自动升级不看车机写入 | 升级前检查车机写入；收口后同时检查 live-sync 搬录像、网络回滚未确认、播放/合成任务；下载校验后再复查一次才替换 | `UpdateWindowGateTests`；`ota_apply()` 在门禁占用时直接返回“升级已推迟” |
| 4 | 归档盘与镜像分离时水位清理不生效 | `_archive_capacity()` 在额度为 0 时回退到归档盘 `statvfs`；`roll_archive_capacity()` 按物理盘剩余清理 | `ArchiveWatermarkFallbackTests` |
| 5 | 飞书 token 缓存不随凭据更新 | token 缓存绑定 `app_id/app_secret`；`notify_save()` 检测凭据变化立即清空缓存 | `FeishuTokenResetTests` |
| 6 | OTA 回滚不恢复 sidecar | 升级前备份 sidecar；`ota_sidecar_state.json` 记录备份目录/文件名；回滚主程序时一并恢复 | `SidecarRollbackTests`；收口后 sidecar 下载走多源竞速，不再把 `api.github.com` 当 raw 文件源 |
| 7 | 登录 `next` 可注入 CRLF | `_safe_next()` 拒绝控制字符、`//` 与跨站地址，只允许本站绝对路径 | `LoginNextTests` |
| 8 | 导出任务 id 路径穿越 | `_job_component()` 清洗 `/`、`\`、`..` 等字符，限制长度；合成/导出/分享统一使用 | `ExportJobIdTests` |
| 9 | 网络回滚计时器不落盘 | 回滚快照与截止时间写入 `net-rollback.json`；启动时恢复/续期计时器，确认后清除 | `NetRollStateTests` |
| 10 | 幽灵簇回收无恢复日志 | 回收默认关闭；启用时先把位图/FAT 原始字节写入 journal 并 fsync，再改镜像；启动时按 journal 回放 | `ReclaimJournalTests`（含截断日志拒绝回放） |
| 11 | 小上传接口先收 100MB 再拒绝 | `_read_upload(max_bytes=...)` 按接口上限，超限在读 body 前返回 `TOOBIG`；皮肤/音频/图标 3MB，通用上传 100MB | `UploadCapTests`；各上传路由均处理 `TOOBIG` |
| 12 | 登录失败 IP 表无上限 | 只读检查不插入新键；过期条目清理；新增 4096 条硬上限，满表淘汰最早失败项 | `test_many_ips_do_not_grow_table_past_cap` |

## v3.2.45 收口补充

- 自动/手动升级统一走 `_update_window_ok()`：车机写入、live-sync 搬录像、网络回滚未确认、播放中、合成任务运行都会推迟升级。
- 升级下载并校验完成后，替换程序前再检查一次，避免下载期间车机开始写盘导致重启打断。
- OTA sidecar 下载改为多源竞速；即使清单来自 GitHub API，也不会把 `api.github.com` 当作脚本文件源。
- 登录失败表增加 4096 条硬上限，避免轮换 IP 撑大内存。

## 验收结果

- `python3 -m unittest discover -s tests -v`：**Ran 76 tests / OK**
- `python3 sentry-viewer.py --ota-check`：`ok 3.2.45`
- 盒子 `/api/ver`：`{"v":"3.2.45"}`
- 盒子 `version.json`：`3.2.45`，签名与文件哈希核对通过
- 盒子服务：`sentry-viewer active`、`tesla-live active`
- 当前车机写入状态：`recent/sentry/saved/driving` 均为 false，部署未在车机写入期间执行

## 备注

- 本次未打包，未合并 `main`；`beta` 为当前测试分支。
- beta 的 jsDelivr/gcore 镜像仍可能返回旧缓存 `3.2.43`；盒子已手动部署 `3.2.45`，待镜像缓存刷新后 OTA 页面会自动看到新版本。该缓存不影响已部署实例。
