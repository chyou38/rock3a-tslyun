# TeslaBox v3.2.37 实时验证日志摘录

抓取时间：2026-11-27 19:43（CST）  
设备：Radxa ROCK3 Model A（RK3568，Debian 12，`tsl-sentry`）

## 运行状态

```text
/api/ver       {"v": "3.2.37"}
tesla-live     active
sentry-viewer  active

write-cat.json
{"recent": true, "sentry": false, "saved": false,
 "driving": false, "sei_ts": 1795779772.7424324,
 "ts": 1795779806.868724}
```

## 修复前：哨兵 pending 被反复清空

同一事件 `SentryClips/2026-11-27_19-26-02` 在 **658 秒**内几乎每秒打印 67 条 `发现新片段(待确认)`：

```text
首条：2026-11-27 19:26:57
末条：2026-11-27 19:38:28
每秒条数：约 67（对应 67 个片段）
累计日志：约 4.4 万条
归档目录：空
```

日志样例：

```text
[2026-11-27 19:27:07] 发现新片段(待确认): SentryClips/2026-11-27_19-26-02/2026-11-27_19-21-29-back.mp4 (25738470 bytes)
[2026-11-27 19:27:07] 发现新片段(待确认): SentryClips/2026-11-27_19-26-02/2026-11-27_19-21-29-left_pillar.mp4 (26820032 bytes)
```

状态文件里 67 个签名与扫描结果逐项相等，但每轮 `do_sync()` 都把 pending 当空；根因是主循环：

```python
state = _write_cat_state()
```

覆盖了持久同步状态 `state`。v3.2.37 改为 `cat_state`，并加 AST 回归测试。

## 修复后：两轮签名确认恢复，67 个片段自动归档

```text
[2026-11-27 19:38:35] 在线同步服务启动: 车机连续静止 3 分钟前不打开镜像
[2026-11-27 19:38:36] SEI即时复检: 停车哨兵
[2026-11-27 19:38:36] 已同步 SentryClips/2026-11-27_19-26-02/event.json (0 KB)
[2026-11-27 19:38:38] 已同步 SentryClips/2026-11-27_19-26-02/2026-11-27_19-15-28-front.mp4 (51046 KB)
[2026-11-27 19:39:14] 哨兵优先同步: 7 个片段, 300.8 MB
[2026-11-27 19:40:38] 哨兵优先同步: 27 个片段, 772.2 MB
[2026-11-27 19:41:28] 哨兵优先同步: 33 个片段, 751.6 MB
```

保护性中断：

```text
[2026-11-27 19:40:38] 同步失败 ... 19-25-30-left_repeater.mp4: 停车哨兵状态未确认, 暂停搬运
[2026-11-27 19:40:38] 同步失败 ... 19-25-30-right_pillar.mp4: 停车哨兵状态未确认, 暂停搬运
[2026-11-27 19:40:38] 同步失败 ... 19-25-30-right_repeater.mp4: 停车哨兵状态未确认, 暂停搬运
```

3 个片段在 `driving` 短暂未判定时按保护优先暂停，下一轮自动续传；没有跳过、没有半截文件。

最终核对：

```text
归档文件数       67
归档体积         1.8G
__pending__      0
```

## 即时 SEI 复检

v3.2.37 部署后调用 `request_sei_recheck()`：

```text
{"recent": false, "sentry": false, "saved": false,
 "driving": false, "sei_ts": 1795779711.5897179,
 "ts": 1795779711.5897503}
```

`sei_ts` 更新，`driving=false`（停车哨兵）。

## USB 稳定性

```text
[Fri Nov 27 17:47:59 2026] dwc3 fcc00000.usb: device reset
[Fri Nov 27 17:47:59 2026] dwc3 fcc00000.usb: device reset
```

19:25–19:43 的部署、复检、归档窗口内没有新增 `dwc3 ... device reset`。

## 自动化测试

```text
python3 -m unittest -q tests.test_tesla_live_sync tests.test_sentry_viewer_gate
Ran 33 tests in 6.149s
OK
```

8 个车辆状态矩阵场景全部通过。

## 版本与提交

- 版本：v3.2.37
- 代码提交：`28264e9`（beta）
- 部署备份：`/opt/tesla-sentry/backup-20261127-1940`
- 未打包（按约定，等待明确“打包”指令）
