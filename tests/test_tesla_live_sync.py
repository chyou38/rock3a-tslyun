import importlib.util
import os
import tempfile
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

    def set_state(self, driving=None, recent=False):
        self.write_cat.write_text(__import__("json").dumps({
            "driving": driving, "recent": recent, "sentry": False,
            "saved": False, "ts": time.time(),
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
