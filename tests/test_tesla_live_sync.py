import importlib.util
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "tesla-live-sync.py"
SPEC = importlib.util.spec_from_file_location("tesla_live_sync", MODULE_PATH)
live_sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(live_sync)


class CarBusyTests(unittest.TestCase):
    """car_busy() 用镜像真实 mtime 判断车机是否在写, 所以测试用真实时间戳, 不 mock 时钟。"""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.image = Path(self.tempdir.name) / "teslacam.img"
        self.image.write_bytes(b"image")
        self.hold = live_sync.CAR_WRITE_HOLD
        live_sync.CAR_WRITE_HOLD = 30
        live_sync._CAR_WRITE.update(mtime=None, changed=0.0)

    def tearDown(self):
        live_sync.CAR_WRITE_HOLD = self.hold
        live_sync._CAR_WRITE.update(mtime=None, changed=0.0)
        self.tempdir.cleanup()

    def set_image_age(self, seconds):
        ts = time.time() - seconds
        ns = int(ts * 1_000_000_000)
        os.utime(self.image, ns=(ns, ns))

    def test_first_observation_of_stale_image_is_not_busy(self):
        # 首次观测就以文件真实 mtime 为基线: 两分钟前写过 = 车机空闲。
        self.set_image_age(120)
        with patch.object(live_sync, "IMG", str(self.image)):
            self.assertFalse(live_sync.car_busy())

    def test_first_observation_of_recent_image_is_busy(self):
        self.set_image_age(5)
        with patch.object(live_sync, "IMG", str(self.image)):
            self.assertTrue(live_sync.car_busy())

    def test_mtime_change_after_baseline_is_busy(self):
        self.set_image_age(120)
        with patch.object(live_sync, "IMG", str(self.image)):
            self.assertFalse(live_sync.car_busy())   # 基线: 空闲
            self.set_image_age(1)                    # 车机刚写过
            self.assertTrue(live_sync.car_busy())


class DrivingGateTests(unittest.TestCase):
    """行车中 / 刚写盘 / RecentClips 还在写, 无论如何都不能搬运归档。"""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.image = root / "teslacam.img"
        self.image.write_bytes(b"image")
        self.settings = root / "settings.json"
        self.settings.write_text('{"drive_lock": true}')
        self.write_cat = root / "write-cat.json"
        self.idle = live_sync.SENTRY_IDLE_MIN
        live_sync.SENTRY_IDLE_MIN = 3
        live_sync._CAR_WRITE.update(mtime=None, changed=0.0)
        self.patches = [
            patch.object(live_sync, "IMG", str(self.image)),
            patch.object(live_sync, "SETTINGS_FILE", str(self.settings)),
            patch.object(live_sync, "WRITE_CAT_FILE", str(self.write_cat)),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        live_sync.SENTRY_IDLE_MIN = self.idle
        live_sync._CAR_WRITE.update(mtime=None, changed=0.0)
        self.tempdir.cleanup()

    def set_image_age(self, seconds):
        ts = time.time() - seconds
        ns = int(ts * 1_000_000_000)
        os.utime(self.image, ns=(ns, ns))

    def set_state(self, driving=None, recent=False, sentry=False, saved=False):
        self.write_cat.write_text(__import__("json").dumps({
            "driving": driving, "recent": recent, "sentry": sentry,
            "saved": saved, "ts": time.time(),
        }))

    def test_recent_write_blocks_even_when_not_marked_driving(self):
        self.set_image_age(1)
        self.set_state(driving=False, recent=False)
        self.assertFalse(live_sync.sync_allowed())

    def test_driving_flag_blocks(self):
        self.set_image_age(700)
        self.set_state(driving=True, recent=True)
        self.assertFalse(live_sync.sync_allowed())

    def test_recentclips_still_writing_blocks(self):
        self.set_image_age(700)
        self.set_state(driving=False, recent=True)
        self.assertFalse(live_sync.sync_allowed())

    def test_drive_lock_off_does_not_bypass_archive_gate(self):
        self.settings.write_text('{"drive_lock": false}')
        self.set_image_age(10)
        self.set_state(driving=False, recent=False)
        self.assertFalse(live_sync.sync_allowed())

    def test_sentry_sync_only_when_parked_is_confirmed(self):
        self.set_state(driving=None, recent=True)
        self.assertFalse(live_sync.sentry_sync_allowed())
        self.set_state(driving=True, recent=True, sentry=True)
        self.assertFalse(live_sync.sentry_sync_allowed())
        self.set_state(driving=False, recent=True)
        self.assertTrue(live_sync.sentry_sync_allowed())
        self.set_state(driving=None, recent=False, sentry=True)
        self.assertFalse(live_sync.sentry_sync_allowed())

    def test_sentry_sync_rejects_stale_state(self):
        self.set_state(driving=False, recent=False)
        j = __import__("json").loads(self.write_cat.read_text())
        j["ts"] = time.time() - 60
        self.write_cat.write_text(__import__("json").dumps(j))
        self.assertFalse(live_sync.sentry_sync_allowed())

    def test_only_after_three_minutes_idle_allows(self):
        self.set_image_age(700)
        self.set_state(driving=False, recent=False)
        self.assertTrue(live_sync.sync_allowed())
        self.set_image_age(170)
        self.assertFalse(live_sync.sync_allowed())
        self.set_image_age(190)
        live_sync._CAR_WRITE.update(mtime=None, changed=0.0)
        self.assertTrue(live_sync.sync_allowed())
        self.set_image_age(60)
        self.assertFalse(live_sync.sync_allowed())


class ActiveSentrySyncTests(unittest.TestCase):
    """停车哨兵自动通道只能动 SentryClips; 不能把 SavedClips/RecentClips 混进来。"""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.state_path = self.root / "state.json"
        self.dest = self.root / "clip.mp4"
        self.entry = _FakeEntry(b"x" * 128)
        self.key = ("SentryClips", "2026-11-27_19-00-00", "clip.mp4")
        self.state = {"__pending__": {"/".join(self.key):
                                      [self.entry.size, self.entry.vdl, self.entry.mtime]}}

    def tearDown(self):
        self.tempdir.cleanup()

    def run_sync(self, cats, copy):
        with patch.object(live_sync, "STATE", str(self.state_path)), \
                patch.object(live_sync, "scan", return_value={self.key: self.entry}), \
                patch.object(live_sync, "safe_dest", return_value=str(self.dest)), \
                patch.object(live_sync, "load_pruned", return_value=set()), \
                patch.object(live_sync, "copy_entry", side_effect=copy):
            return live_sync.do_sync(object(), self.state, quiet=True, cats=cats,
                                     hold=False, newest_events=1, allow_active=True)

    def test_active_sentry_rejects_recentclips(self):
        with self.assertRaises(ValueError):
            self.run_sync(("RecentClips",), lambda *a, **kw: 0)

    def test_active_sentry_uses_active_gate_only(self):
        calls = []
        def copy(*a, **kw):
            calls.append(kw)
            return self.entry.size
        copied, _ = self.run_sync(("SentryClips",), copy)
        self.assertEqual(copied, 1)
        self.assertTrue(calls[0].get("allow_active"))
        self.assertFalse(calls[0].get("hold"))


class _FakeEntry:
    def __init__(self, data, name="clip.mp4", mtime=12345):
        self.data = data
        self.size = len(data)
        self.vdl = self.size
        self.mtime = mtime
        self.name = name


class _FakeExFat:
    """只实现 read_file, 按 128KB 分块吐出条目内容。"""

    def __init__(self, data):
        self.data = data

    def read_file(self, entry, limit=None):
        chunk = 128 * 1024
        for off in range(0, len(self.data), chunk):
            yield self.data[off:off + chunk]


class SameFileTests(unittest.TestCase):
    """same_file() 只比大小, 同尺寸改写会漏同步; same_content() 负责兜底内容比对。"""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.dest = Path(self.tempdir.name) / "clip.mp4"
        self.old = b"\x00A" * 64
        self.new = b"\x00B" * 64
        self.dest.write_bytes(self.old)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_same_file_only_checks_size(self):
        # 同尺寸改写: 旧实现只看大小, 会误判为已同步
        self.assertTrue(live_sync.same_file(str(self.dest), len(self.new)))

    def test_same_content_detects_in_place_rewrite(self):
        entry = _FakeEntry(self.new)
        exfat = _FakeExFat(self.new)
        self.assertFalse(live_sync.same_content(str(self.dest), entry, exfat))

    def test_same_content_accepts_identical_bytes(self):
        entry = _FakeEntry(self.old)
        exfat = _FakeExFat(self.old)
        self.assertTrue(live_sync.same_content(str(self.dest), entry, exfat))

    def test_same_content_detects_truncated_archive(self):
        self.dest.write_bytes(self.old[:32])
        entry = _FakeEntry(self.old)
        exfat = _FakeExFat(self.old)
        self.assertFalse(live_sync.same_content(str(self.dest), entry, exfat))

    def test_same_content_missing_archive(self):
        entry = _FakeEntry(self.old)
        exfat = _FakeExFat(self.old)
        self.assertFalse(live_sync.same_content(str(self.dest) + ".absent", entry, exfat))


class FirstRunSyncTests(unittest.TestCase):
    """旧归档首轮不能被逐字节全扫; 首次只建签名基线, 长循环要分段落盘。"""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.dest = Path(self.tempdir.name) / "clip.mp4"
        self.old = b"\x00A" * 64
        self.new = b"\x00B" * 64
        self.dest.write_bytes(self.old)
        self.state_path = Path(self.tempdir.name) / "live-state.json"
        self.key = ("SentryClips", "2026-11-27_15-00-00", "clip.mp4")
        self.entry = _FakeEntry(self.new)
        self.scan_result = {self.key: self.entry}

    def tearDown(self):
        self.tempdir.cleanup()

    def run_sync(self):
        with patch.object(live_sync, "STATE", str(self.state_path)), \
                patch.object(live_sync, "scan", return_value=self.scan_result), \
                patch.object(live_sync, "safe_dest", return_value=str(self.dest)), \
                patch.object(live_sync, "load_pruned", return_value=set()):
            return live_sync.do_sync(object(), {}, quiet=True)

    def test_first_run_seeds_signature_without_content_compare(self):
        # 旧实现会在 __cmp__ 为空时调用 same_content; 这里一旦调用就让测试失败。
        with patch.object(live_sync, "same_content",
                          side_effect=AssertionError("首轮不应读取旧归档内容")):
            copied, _ = self.run_sync()
        self.assertEqual(copied, 0)
        state = __import__("json").loads(self.state_path.read_text())
        self.assertEqual(state["__cmp__"]["/".join(self.key)],
                         [self.entry.size, self.entry.vdl, self.entry.mtime])

    def test_long_sync_saves_checkpoints(self):
        # 每处理 1 个条目就保存, 至少应有“检查点 + 结束”两次写入。
        with patch.object(live_sync, "CHECKPOINT_EVERY", 1), \
                patch.object(live_sync, "same_content", return_value=True), \
                patch.object(live_sync, "save_state", wraps=live_sync.save_state) as save_mock:
            self.run_sync()
        self.assertGreaterEqual(save_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()


class _SeiFakeEntry:
    def __init__(self, name, cluster, size, is_dir=False, data=b""):
        self.name = name
        self.cluster = cluster
        self.size = size
        self.is_dir = is_dir
        self.data = data


class _SeiFakeExFat:
    """只实现 probe_driving 需要的目录树/读取接口。"""
    root_cluster = 0

    def __init__(self, front):
        self.cam = _SeiFakeEntry("TeslaCam", 1, 0, True)
        self.rec = _SeiFakeEntry("RecentClips", 2, 0, True)
        self.front = front

    def list_dir(self, cluster, size=0):
        if cluster == 0:
            return [self.cam]
        if cluster == self.cam.cluster:
            return [self.rec]
        if cluster == self.rec.cluster:
            return [self.front]
        return []

    @staticmethod
    def find(entries, name):
        for e in entries:
            if e.name == name:
                return e
        return None

    @staticmethod
    def read_file(entry):
        yield entry.data


class ForceSeiProbeTests(unittest.TestCase):
    """即时复检必须跳过文件名缓存, 否则刚出现的新行车片段会被旧结论挡住。"""

    def setUp(self):
        live_sync._REC_CACHE = {"ts": 0.0, "entry": None}
        live_sync._DRIVE_HINT = {"key": None, "val": None}
        self.size = live_sync.SEI_MIN_BYTES + 1024
        self.front = _SeiFakeEntry(
            "2026-11-27_19-00-00-front.mp4", 3, self.size, False,
            b"no-telemetry" * (self.size // 12 + 1),
        )
        self.exfat = _SeiFakeExFat(self.front)

    def test_force_bypasses_same_filename_cache(self):
        self.assertFalse(live_sync.probe_driving(self.exfat, limit=live_sync.SEI_PROBE_BYTES))
        self.front.data = b"\x42\x42\x42\x69" * 3 + b"x" * self.size
        self.assertFalse(live_sync.probe_driving(self.exfat, limit=live_sync.SEI_PROBE_BYTES))
        self.assertTrue(live_sync.probe_driving(self.exfat, limit=live_sync.SEI_PROBE_BYTES, force=True))

    def test_short_front_file_is_unknown_even_with_force(self):
        self.front.size = live_sync.SEI_MIN_BYTES - 1
        self.front.data = b"\x42\x42\x42\x69" * 3
        self.assertIsNone(live_sync.probe_driving(self.exfat, force=True))



class ProbeLoopRequestTests(unittest.TestCase):
    """真实 probe_loop + 请求文件: 验证网页即时复检能拿到新的 sei_ts/driving。"""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.image = root / "teslacam.img"
        self.image.write_bytes(b"image")
        self.write_cat = root / "write-cat.json"
        self.req = root / "sei-probe.req"
        self.size = live_sync.SEI_MIN_BYTES + 1024
        self.front = _SeiFakeEntry(
            "2026-11-27_19-00-00-front.mp4", 3, self.size, False,
            b"no-telemetry" * (self.size // 12 + 1),
        )
        self.exfat = _SeiFakeExFat(self.front)
        live_sync._REC_CACHE = {"ts": 0.0, "entry": None}
        live_sync._DRIVE_HINT = {"key": None, "val": None}
        self.patches = [
            patch.object(live_sync, "IMG", str(self.image)),
            patch.object(live_sync, "WRITE_CAT_FILE", str(self.write_cat)),
            patch.object(live_sync, "SEI_REQ_FILE", str(self.req)),
            patch.object(live_sync, "SENTRY_IDLE_MIN", 3.0),
            patch.object(live_sync, "ExFat", lambda _p: self.exfat),
        ]
        for p in self.patches:
            p.start()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=live_sync.probe_loop, args=(self.stop,), daemon=True)
        self.thread.start()

    def tearDown(self):
        self.stop.set()
        self.thread.join(timeout=3)
        for p in self.patches:
            p.stop()
        self.tempdir.cleanup()

    def state(self):
        try:
            return json.loads(self.write_cat.read_text())
        except Exception:
            return {}

    def request_and_wait(self, expected, deadline=3.0):
        req_ts = time.time()
        self.req.write_text("%.6f\n" % req_ts)
        end = time.time() + deadline
        while time.time() < end:
            st = self.state()
            try:
                if st.get("driving") is expected and float(st.get("sei_ts") or 0) >= req_ts:
                    return st
            except (TypeError, ValueError):
                pass
            time.sleep(0.1)
        return self.state()

    def test_request_forces_new_sei_after_same_filename(self):
        # 等第一轮基线/自动探针落盘
        end = time.time() + 2.0
        while time.time() < end and not self.state():
            time.sleep(0.1)
        st = self.request_and_wait(False)
        self.assertIs(st.get("driving"), False)

        # 同一个文件名内容变成有 SEI: 请求必须绕过旧缓存
        self.front.data = b"\x42\x42\x42\x69" * 3 + b"x" * self.size
        st = self.request_and_wait(True)
        self.assertIs(st.get("driving"), True)
