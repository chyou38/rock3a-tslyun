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


class _FakeEntry:
    def __init__(self, data):
        self.data = data
        self.size = len(data)


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


if __name__ == "__main__":
    unittest.main()
