# TeslaBox 车机U盘 / 归档区 / 哨兵联动逻辑

版本：v3.2.37 beta  
范围：`tesla-live-sync.py`、`sentry-viewer.py`、`write-cat.json`  
目标：车机写入永远第一优先；只有明确停车哨兵时才自动归档 `SentryClips`；手动保存和行车记录走常规归档。

---

## 1. 总体数据流

```
车机写入 teslacam.img
        │
        ├─ mtime 变化 ──────────────► 车机活跃计时（10s / 180s 窗口）
        │
        └─ tesla-live 每 60s
             只读最新 RecentClips 前视片段头部 512KB
             ├─ 有 SEI 遥测 ──► driving = true   （真行车）
             ├─ 无 SEI 遥测 ──► driving = false  （停车哨兵）
             └─ 读不到/文件太小 ─► driving = null （未判定）

write-cat.json
  ├─ sentry-viewer：车机U盘门禁、后台缩略图/预缓冲门禁、页面状态
  └─ tesla-live：常规归档门禁、停车哨兵自动归档门禁
```

`write-cat.json` 关键字段：

| 字段 | 含义 |
|---|---|
| `driving` | `true` 真行车；`false` 停车哨兵；`null` 未判定 |
| `recent` | 镜像 mtime 在 12 秒内，近期有写入 |
| `sentry` | 空闲签名扫描发现 `SentryClips` 变化 |
| `saved` | 空闲签名扫描发现 `SavedClips` 变化 |
| `sei_ts` | 最近一次 SEI 判定时间，网页连接U盘前据此确认即时复检已完成 |
| `ts` | 状态时间戳；超过 30 秒视为过期/未知 |

---

## 2. 即时 SEI 复检（v3.2.36）

### 连接 U 盘前

1. 网页 `usb_connect_gate()` 先写 `/opt/tesla-sentry/sei-probe.req`；
2. `tesla-live-sync.py` 的 `probe_loop()` 下一轮发现请求，执行 `probe_driving(force=True)`：跳过 20 秒目录缓存和文件名缓存，重新列 `RecentClips` 并只读最新前视片段头部 512KB；
3. 结果连同 `sei_ts` 回写 `write-cat.json`；
4. 网页最多等 5 秒：
   - `driving=true` → 拒绝连接；
   - `driving=null`（片段不足/无 SEI）→ 拒绝；
   - 超时/服务没回写新的 `sei_ts` → 拒绝；
   - `driving=false` → 继续走原有 `car_active_for_usb()` 检查。

页面上的 `locked` 是旧快照，不再直接拦住用户；真正裁决以后端复检为准。

### 已连接 U 盘期间

`drive_watch_loop()` 监测镜像 mtime。车机一有新写入：

- 立即请求一次即时 SEI 复检；
- 复检为 `true` 或 `null`/超时 → `usb_detach_safe()` 立刻归还车机导出；
- 复检为 `false`（停车哨兵/手动保存）→ 保持连接。

这样停车哨兵切换真行车时，不再等最多 60 秒的周期探针。

---

## 3. 车机U盘读取（虚拟U盘）

判定函数：`car_active_for_usb()`

| 条件 | 结果 |
|---|---|
| 行车锁开关关闭 | 允许连接/读取 |
| 最近 180 秒没有任何车机写入 | 允许连接/读取 |
| `driving = true` | 锁定，禁止读取 |
| `driving = null` 且没有明确哨兵/手动保存标志 | 锁定，保护优先 |
| `driving = false`（停车哨兵） | 不锁，允许临时连接管理 |

补充：

- 页面状态：`driving=true` → “行车中 · 已锁定”；`driving=false` → “哨兵录像中 · 未锁定”；`null` → “车机写入中 · 保护中（未判定行车/哨兵）”。
- U 盘连接后 180 秒无操作自动恢复车机导出；用户浏览/下载/上传会续期。
- 行车锁只控制虚拟U盘读取，不控制归档区回放；但归档/缩略图/预缓冲另有独立门禁。

---

## 4. 后台缩略图 / 预缓冲 / 转码

判定函数：`car_active_for_background()`

- 最近 **180 秒**内只要车机写过镜像，就返回 `true`。
- 不受行车锁开关影响。
- 覆盖：缩略图、预缓冲、后台硬解补档等。
- 服务重启后的首分钟不再误判空闲：`car_writing()` 首次观测使用镜像自身 mtime 初始化，而不是从 `changed=-100` 开始。

---

## 5. 归档通道分类

| 类别 | 归档通道 | 触发条件 |
|---|---|---|
| `SentryClips` | **哨兵独立自动通道** | `driving=false`，每 60 秒检查最新 1 个事件 |
| `SavedClips` | **常规归档通道** | 与 `RecentClips` 一起，等连续 3 分钟无写入 |
| `RecentClips` | **常规归档通道** | 与 `SavedClips` 一起，等连续 3 分钟无写入 |

物理目录仍按类别分开（`archive/SentryClips`、`archive/SavedClips`、`archive/RecentClips`），但调度上：

- 手动保存 + 行车记录 = 同一轮常规归档；
- 哨兵 = 单独轮次，不混入手动保存/行车记录。

---

## 6. 常规归档门禁

判定函数：`sync_allowed()`

必须同时满足：

1. `driving != true`
2. `recent = false`（不是刚写过盘）
3. 当前没有车机写入忙碌
4. 连续无写入时间 ≥ **3 分钟**

通过后，`do_sync(cats=("RecentClips","SavedClips"))` 执行常规归档。

复制每个文件时，`copy_entry(allow_active=false)`：

- 开始复制前检查一次 `sync_allowed()`；
- 每复制 1MB 再检查一次；
- 车机一旦开始写盘，立即抛出暂停，清理未完成 `.part`，等下一轮。

归档调度间隔仍由页面设置控制，默认 10 分钟；“立即归档”只是写触发文件，仍需等门禁通过。

---

## 7. 停车哨兵自动归档

判定函数：`sentry_sync_allowed()`

- 只认 `driving=false`。
- `driving=true`、`null`、状态过期 → 一律拒绝。
- 只允许 `SentryClips`，不允许 `SavedClips`/`RecentClips`。

执行流程：

1. `tesla-live` 主循环每 60 秒检查一次；
2. 若 `driving=false`，设置哨兵优先触发；
3. `do_sync(cats=("SentryClips",), newest_events=1, allow_active=True)`；
4. 只处理最新 1 个哨兵事件；
5. 复制过程中每 1MB 复检 `sentry_sync_allowed()`；
6. 车机在写时 `hold=False`，每 1MB 只让 0.15 秒；一旦变成行车/未判定，立即停止并保留 `.part` 待续；
7. 如果第一轮只是记录待确认签名，下一轮立即重试；重试只看 `SentryClips` 的 pending，不会被 `SavedClips` 拖入空转。

---

## 8. 状态时序

### 真行车

```
driving=true
  ├─ 车机U盘锁定
  ├─ 常规归档禁止
  ├─ 哨兵自动归档禁止
  └─ 后台缩略图/预缓冲/转码禁止
```

### 停车哨兵

```
driving=false
  ├─ 车机U盘不锁，可临时连接
  ├─ 哨兵 SentryClips 可每60秒自动归档最新1个事件
  ├─ 常规归档（Recent+Saved）仍禁止，等3分钟静默
  └─ 后台缩略图/预缓冲/转码禁止（近180秒有写入）
```

### 车机完全空闲

```
连续3分钟无写入
  ├─ 常规归档恢复：RecentClips + SavedClips 同一轮
  ├─ 哨兵自动通道仍按最新 SentryClips 检查
  └─ 180秒后后台任务恢复
```

---

## 9. 当前实测状态（v3.2.37）

- `write-cat.json`：`driving=false`，识别为停车哨兵。
- `/api/drive_lock`：`on=true`、`locked=false`、`parked_recording=true`、`sentry_writing=true`、`driving=false`。
- 页面应显示：**哨兵录像中 · 未锁定**；车机U盘可连接。
- `/api/archive_sched`：`car_writing=true`，常规归档暂停，消息“车机未静止（停车哨兵），归档暂停”。
- `tesla-live`、`sentry-viewer` 均 active。
- `/api/ver` 已返回 `3.2.37`；`write-cat.json` 的 `sei_ts` 随即时复检更新。
- 19:26 的 `SentryClips/2026-11-27_19-26-02` 事件已由哨兵自动通道归档：67 个片段、约 1.8GB，分 3 轮完成（19:38–19:41）；最终 `__pending__=0`。
- v3.2.37 修复了主循环 `state` 被 `write-cat` 覆盖导致 pending 永远无法确认的 bug；实测该 bug 在 19:26:57–19:38:28 的 658 秒内几乎每秒重扫 67 个文件。`do_sync()` 的持久状态必须使用独立变量名。

---

## 10. 已知边界 / 风险

1. **未连接 U 盘时仍有 60 秒窗口**：哨兵自动通道依赖 `write-cat` 的 `driving=false`；车辆从停车哨兵切换真行车、且 U 盘没有连接时，哨兵自动通道理论上仍可能保留一个探针周期的旧状态。U 盘连接前和连接期间已由即时复检覆盖；哨兵自动通道后续可按实际日志决定是否也加写入触发复检。
2. **只读最新前视片段头部 512KB**：极少数片段头部没有足够 SEI 标记时会判为 `null`，按保护优先处理，不会误放行。
3. **哨兵自动只处理最新 1 个事件**：如果最新事件还在写入，需等签名连续两轮一致；更早的未归档事件不会在这个通道里自动补。
4. **常规归档仍要等 3 分钟静默**：停车哨兵持续每分钟写盘时，`SavedClips/RecentClips` 不会自动进入常规归档；这是“车机写入第一优先”的直接结果。
5. **物理目录仍分开**：`SavedClips` 与 `RecentClips` 在同一常规调度轮次，但归档目录和页面分类仍各自保留；哨兵目录单独。

---

## 11. 关键代码位置

- `tesla-live-sync.py`
  - `probe_driving()`：512KB SEI 判定
  - `publish_recent_only()`：活动期写 `write-cat`
  - `sync_allowed()`：常规归档门禁
  - `sentry_sync_allowed()`：停车哨兵门禁
  - `copy_entry()`：1MB 复检与让路
  - `do_sync()`：分类归档与 pending 确认
  - `probe_loop()`：SEI 探针与状态发布
- `sentry-viewer.py`
  - `car_writing()`：mtime 活跃检测
  - `car_active_for_usb()`：虚拟U盘门禁
  - `car_active_for_background()`：后台任务门禁
  - `sentry_writing_only()` / `parked_recording()`：页面与U盘分类
  - `drive_watch_loop()`：行车锁看门狗
