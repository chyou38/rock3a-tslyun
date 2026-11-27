#!/usr/bin/env python3
"""TeslaBox 车辆状态门禁仿真矩阵 (v3.2.36).

用临时镜像/临时 write-cat/settings 跑真实门禁函数, 不挂载真实 U 盘, 不改盒子状态。
每个场景:
  - 写入旧 write-cat 状态
  - 设置镜像 mtime 模拟车机写入年龄
  - 模拟网页连接前的即时 SEI 复检结果(写入新 write-cat, 或超时不写)
  - 分别检查 U 盘连接、后台任务、常规归档、哨兵自动归档
输出 Markdown 表格, 供测试报告引用。
"""
import importlib.util
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sync = load("live_sync_sim", "tesla-live-sync.py")
view = load("viewer_sim", "sentry-viewer.py")

TMP = tempfile.TemporaryDirectory()
ROOT_TMP = Path(TMP.name)
IMG = ROOT_TMP / "teslacam.img"
IMG.write_bytes(b"x")
SETTINGS = ROOT_TMP / "settings.json"
SETTINGS.write_text('{"drive_lock": true}')
WRITE_CAT = ROOT_TMP / "write-cat.json"
REQ = ROOT_TMP / "sei-probe.req"

sync.IMG = str(IMG)
sync.SETTINGS_FILE = str(SETTINGS)
sync.WRITE_CAT_FILE = str(WRITE_CAT)
sync.SEI_REQ_FILE = str(REQ)
view.IMG = str(IMG)
view.SETTINGS_FILE = str(SETTINGS)
view.WRITE_CAT_FILE = str(WRITE_CAT)
view.SEI_REQ_FILE = str(REQ)


def set_age(seconds):
    ts = time.time() - seconds
    ns = int(ts * 1_000_000_000)
    os.utime(IMG, ns=(ns, ns))
    sync._CAR_WRITE.update(mtime=None, changed=0.0)
    view._CAR_WRITE.update(mtime=None, changed=0.0, ts=0.0, v=False)


def write_cat(driving, recent, sentry=False, saved=False, age_ts=0.0):
    WRITE_CAT.write_text(json.dumps({
        "driving": driving, "recent": recent, "sentry": sentry,
        "saved": saved, "sei_ts": time.time(), "ts": time.time() - age_ts,
    }, ensure_ascii=False))


def fresh_result(result):
    # None 是合法的"未判定"结果, 必须落盘; 只有超时才返回 Python None(无新状态)。
    st = {"driving": result, "recent": False, "sentry": False,
          "saved": False, "sei_ts": time.time(), "ts": time.time()}
    WRITE_CAT.write_text(json.dumps(st, ensure_ascii=False))
    return st


def state_text(v):
    return {True: "真行车", False: "停车哨兵", None: "未判定"}.get(v, str(v))


SCENARIOS = [
    # name, old driving, recent, sentry, saved, image age, old ts age, fresh result, expect_usb, expect_regular, expect_sentry
    ("静止空闲", False, False, False, False, 300, 0, False, "允许", "允许", "允许"),
    ("停车哨兵录像", False, True, False, False, 5, 0, False, "允许", "暂停", "允许"),
    ("手动保存写入", False, True, False, True, 5, 0, False, "允许", "暂停", "允许"),
    ("真行车", True, True, False, False, 5, 0, True, "拒绝", "暂停", "拒绝"),
    ("未判定(无SEI/短片段)", None, True, False, False, 5, 0, None, "拒绝", "暂停", "拒绝"),
    ("旧状态过期", False, False, False, False, 5, 45, False, "允许", "暂停", "允许"),
    ("停车切换真行车(旧false/复检true)", False, True, False, False, 5, 0, True, "拒绝", "暂停", "拒绝"),
    ("复检超时", False, True, False, False, 5, 0, "__timeout__", "拒绝", "暂停", "允许"),
]

rows = []
for name, driving, recent, sentry, saved, age, ts_age, fresh, e_usb, e_regular, e_sentry in SCENARIOS:
    set_age(age)
    write_cat(driving, recent, sentry, saved, age_ts=ts_age)
    # 旧状态下的门禁值(未复检)
    old_usb = "拒绝" if view.car_active_for_usb() else "允许"
    old_regular = "允许" if sync.sync_allowed() else "暂停"
    old_sentry = "允许" if sync.sentry_sync_allowed() else "拒绝"

    if fresh == "__timeout__":
        setter = lambda: None
        timeout = True
    else:
        def setter(v=fresh):
            return fresh_result(v)
        timeout = False

    with patch.object(view, "request_sei_recheck", side_effect=setter):
        ok, msg = view.usb_connect_gate()
    new_usb = "允许" if ok else "拒绝"
    new_regular = "允许" if sync.sync_allowed() else "暂停"
    new_sentry = "允许" if sync.sentry_sync_allowed() else "拒绝"
    bg = "暂停" if view.car_active_for_background() else "允许"
    passed = (new_usb == e_usb and new_regular == e_regular and new_sentry == e_sentry)
    rows.append({
        "场景": name,
        "旧状态": state_text(driving),
        "镜像年龄": "%ss" % age,
        "旧状态U盘": old_usb,
        "复检后U盘": new_usb,
        "后台任务": bg,
        "常规归档": new_regular,
        "哨兵自动归档": new_sentry,
        "期望": "%s/%s/%s" % (e_usb, e_regular, e_sentry),
        "结果": "通过" if passed else "失败",
        "msg": msg,
        "old_sentry": old_sentry,
        "old_regular": old_regular,
    })

print("| 场景 | 旧状态 | 镜像年龄 | 旧状态U盘 | 复检后U盘 | 后台任务 | 常规归档 | 哨兵自动归档 | 结果 |")
print("|---|---|---|---|---|---|---|---|---|")
for r in rows:
    print("| {场景} | {旧状态} | {镜像年龄} | {旧状态U盘} | {复检后U盘} | {后台任务} | {常规归档} | {哨兵自动归档} | {结果} |".format(**r))
print()
print("JSON=" + json.dumps(rows, ensure_ascii=False))
if any(r["结果"] != "通过" for r in rows):
    raise SystemExit(2)
