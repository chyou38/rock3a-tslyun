# tslbox 车辆状态模拟测试报告

版本：v3.2.37 beta  
日期：2026-11-27  
设备：Radxa ROCK3 Model A（RK3568，Debian 12，盒子 `tsl-sentry`）  
测试方式：临时镜像 + 临时 `write-cat.json` + 模拟状态；不挂载真实车机 U 盘、不改真实归档区。

## 结论

- 33 个自动化测试全部通过：`Ran 33 tests ... OK`。
- 8 个车辆状态场景矩阵全部符合预期。
- 即时 SEI 复检在真实盒子上完成：请求文件写入后，同步服务下一轮回写新的 `sei_ts` 和 `driving`。
- v3.2.37 已部署，`/api/ver` 返回 `3.2.37`；`tesla-live`、`sentry-viewer` 均 active。
- 实时日志发现并修复主循环 `state` 被 `write-cat` 覆盖的严重 bug：19:26:57–19:38:28 的 658 秒内几乎每秒重扫 67 个哨兵文件、一直“待确认”；修复后同一 67 个片段、1.8GB 在 3 轮内完成自动归档。
- 实时日志窗口内没有新的 `dwc3 ... device reset`；已有 USB reset 记录仍为 17:38–17:47 的历史故障。

## 一、自动化测试

```text
python3 -m unittest -q tests.test_tesla_live_sync tests.test_sentry_viewer_gate
Ran 33 tests in 6.149s
OK
```

覆盖内容：

- SEI 判定：真行车、停车哨兵、短片段/无 SEI 未判定。
- `probe_driving(force=True)` 跳过目录缓存和文件名缓存。
- 真实 `probe_loop` + `sei-probe.req` 握手：同一文件名从无 SEI 改为有 SEI，请求后状态从 `false` 变 `true`。
- U 盘连接门禁：真行车拒绝、停车放行、未判定拒绝、复检超时拒绝、行车锁关闭不请求。
- 常规归档 3 分钟静默门禁；哨兵自动归档只认 `driving=false`。
- `SentryClips` 与 `SavedClips/RecentClips` 通道隔离。

## 二、车辆状态矩阵

运行：

```bash
python3 tests/vehicle_state_matrix.py
```

| 场景 | 旧状态 | 镜像年龄 | 旧状态U盘 | 复检后U盘 | 后台任务 | 常规归档 | 哨兵自动归档 | 结果 |
|---|---|---|---|---|---|---|---|---|
| 静止空闲 | 停车哨兵 | 300s | 允许 | 允许 | 允许 | 允许 | 允许 | 通过 |
| 停车哨兵录像 | 停车哨兵 | 5s | 允许 | 允许 | 暂停 | 暂停 | 允许 | 通过 |
| 手动保存写入 | 停车哨兵 | 5s | 允许 | 允许 | 暂停 | 暂停 | 允许 | 通过 |
| 真行车 | 真行车 | 5s | 拒绝 | 拒绝 | 暂停 | 暂停 | 拒绝 | 通过 |
| 未判定（无SEI/短片段） | 未判定 | 5s | 拒绝 | 拒绝 | 暂停 | 暂停 | 拒绝 | 通过 |
| 旧状态过期 | 停车哨兵 | 5s | 拒绝 | 允许 | 暂停 | 暂停 | 允许 | 通过 |
| 停车切换真行车（旧false/复检true） | 停车哨兵 | 5s | 允许 | 拒绝 | 暂停 | 暂停 | 拒绝 | 通过 |
| 复检超时 | 停车哨兵 | 5s | 允许 | 拒绝 | 暂停 | 暂停 | 允许 | 通过 |

关键验证点：

- **旧状态过期**：旧 `write-cat` 超过 30 秒，旧逻辑下 U 盘被拒绝；即时复检拿到新 `driving=false` 后放行。
- **停车切换真行车**：旧状态为 `false` 时 U 盘本来会放行；复检返回 `true` 后立即拒绝，证明“及时复检”确实挡住了这个窗口。
- **未判定**：复检拿到 `driving=null` 时拒绝，不把“读不到 SEI”当成停车。
- **复检超时**：同步服务 5 秒内没有回写新 `sei_ts` 时拒绝，不拿旧状态放行。

## 三、真实盒子即时复检验证

部署 v3.2.36 时直接调用查看器的 `request_sei_recheck()`：

```text
{'recent': True, 'sentry': False, 'saved': False,
 'driving': False, 'sei_ts': 1795778771.990209,
 'ts': 1795778771.9902375}
```

说明：

- 请求前 `sei_ts` 为约 19:25:56。
- 请求后 `sei_ts` 更新到 19:26:11，`driving=false`，即停车哨兵。
- 同步服务确实响应了 `sei-probe.req`，不是只改了查看器本地变量。

实时日志窗口：

```text
[2026-11-27 19:25:55] 在线同步服务启动: 车机连续静止 3 分钟前不打开镜像
[2026-11-27 19:25:56] SEI探针: 停车哨兵
[2026-11-27 19:25:57] 车机未静止 (停车哨兵), 归档顺延 (给 OTG 让路)
[2026-11-27 19:26:11] SEI即时复检: 停车哨兵
```

`dmesg` 中最后一条 USB 相关 reset 仍为：

```text
[Fri Nov 27 17:47:59 2026] dwc3 fcc00000.usb: device reset
```

19:25–19:41 的部署/复检/归档窗口内没有新增 `dwc3 ... device reset`。

### v3.2.37 实测：即时复检与哨兵自动归档恢复

v3.2.37 部署后再次调用 `request_sei_recheck()`：

```text
{'recent': False, 'sentry': False, 'saved': False,
 'driving': False, 'sei_ts': 1795779711.5897179,
 'ts': 1795779711.5897503}
```

对应时间约 19:41:51，`sei_ts` 更新，`driving=false`（停车哨兵）。

同一时间窗口内，19:26 创建的哨兵事件 `SentryClips/2026-11-27_19-26-02` 完成自动归档：

```text
[2026-11-27 19:38:35] 在线同步服务启动: 车机连续静止 3 分钟前不打开镜像
[2026-11-27 19:38:36] SEI即时复检: 停车哨兵
[2026-11-27 19:38:36] 已同步 SentryClips/2026-11-27_19-26-02/event.json (0 KB)
[2026-11-27 19:38:38] 已同步 ... 19-15-28-front.mp4 (51046 KB)
[2026-11-27 19:39:14] 哨兵优先同步: 7 个片段, 300.8 MB
[2026-11-27 19:40:38] 哨兵优先同步: 27 个片段, 772.2 MB
[2026-11-27 19:41:28] 哨兵优先同步: 33 个片段, 751.6 MB
```

共 67 个片段、约 1824.6 MB；归档目录 `SentryClips/2026-11-27_19-26-02` 实测 1.8G，`find -type f` 计数 67，`__pending__` 已清零。  
19:40:38 有 3 个片段因 `driving` 短暂未判定触发“停车哨兵状态未确认，暂停搬运”，属于保护性中断；下一轮自动续传，最终 67/67 全部落地。复制期间常规归档保持“给 OTG 让路”。

## 四、本轮发现并修复的问题

### 1. 前端用旧 `locked` 快照直接拦住连接

原 `usbAttach()` 里：

```js
if (DRIVE_LOCK_STATE.locked) { ... return; }
```

页面状态可能比真实 SEI 慢；用户刚停车时会被旧锁定状态挡住，根本到不了后端的即时复检。  
已改为：页面只提示，不再提前 return，由 `usb_connect_gate()` 以后端复检结果裁决。

### 2. 即时复检缺少请求/回写协议

新增：

- `sei-probe.req`：查看器在连接前写入请求。
- `sei_ts`：`write-cat.json` 增加最近一次 SEI 判定时间。
- `probe_loop` 检测到请求后强制 `probe_driving(force=True)`，跳过目录缓存和文件名缓存。
- `request_sei_recheck()` 等待 `sei_ts` 更新；超时返回 `None`，连接门禁拒绝。

### 3. 已连接 U 盘期间，车机从停车哨兵切真行车时仍可能最长 60 秒不卸载

`drive_watch_loop()` 新增：

- U 盘已连接期间监测镜像 mtime。
- 车机一有新写入，立即请求一次 SEI 复检。
- 复检为 `true` 或 `null`（未判定/超时）立即 `usb_detach_safe()`，不等 60 秒周期。
- 复检为 `false`（停车哨兵/手动保存）继续保留连接。

### 4. 实时日志发现：主循环 `state` 被 `write-cat` 覆盖（v3.2.37 修复）

现象：19:26:57–19:38:28 的 **658 秒** 内，日志几乎每秒打印 67 条同一批 `发现新片段(待确认)`（67 个片段），累计约 4.4 万条；状态文件里 67 个片段签名已稳定且与扫描结果完全相等，但永远不进入复制，归档目录为空。扫描从“两轮确认”退化成了每秒一轮全量重扫。

根因：主循环写：

```python
state = _write_cat_state()
```

把持久同步状态 `state`（含 `__pending__`、`__cmp__`）覆盖成 `write-cat.json` 的分类标志。随后 `do_sync()` 每轮拿到的 `pending` 都是空字典，上一轮签名永远读不到；`save_state()` 还把 `driving/recent/sentry` 等 write-cat 字段写进了同步状态文件。常规归档同样受影响。

修复：改用独立变量：

```python
cat_state = _write_cat_state()
if cat_state is not None and cat_state.get("driving") is False:
    ...
```

并新增回归测试 `MainLoopStateRegressionTests`，用 AST 检查 `main()` 中不能把 `_write_cat_state()` 的返回值赋给 `state`。

验证：33 个测试全部通过；v3.2.37 启动后 19:38:36 第一轮即识别已有 pending，19:38:38 开始复制，19:41:28 完成 67 个片段、约 1.8GB 的哨兵自动归档；最终归档文件数 67、pending 0。

## 五、仍需观察的点

1. **未连接 U 盘时的哨兵自动通道**：仍依赖 `write-cat` 的 `driving=false`；如果车辆从停车哨兵切换真行车，而 U 盘没有连接，哨兵自动通道理论上仍有最多一个探针周期的旧状态窗口。当前已通过 `probe_loop` 的写入触发和 60 秒探针降低，但未做到“每次车机写入都强制复检”。
2. **手动保存与哨兵自动通道同时写盘**：哨兵自动通道只复制 `SentryClips`，不会复制 `SavedClips`；但两者可能共享镜像 I/O。当前保留原设计，后续可按实际日志再决定是否给 `SavedClips` 增加互斥。
3. **即时复检超时会拒绝 U 盘管理**：这是保护优先策略；如果同步服务异常，网页不能强行读取镜像。

## 六、复现命令

```bash
cd /var/lib/openbot/tslusb/wt-update-channel
python3 -m unittest -q tests.test_tesla_live_sync tests.test_sentry_viewer_gate
python3 tests/vehicle_state_matrix.py
```

真实盒子请求验证：

```bash
ssh teslabox 'echo radxa | sudo -S -p "" -u radxa env TSF_DIR=/opt/tesla-sentry python3 -c \
  "import importlib.util; p=\"/opt/tesla-sentry/sentry-viewer.py\"; \
   s=importlib.util.spec_from_file_location(\"sv\",p); m=importlib.util.module_from_spec(s); \
   s.loader.exec_module(m); print(m.request_sei_recheck(timeout=5.0))"'
```
