import importlib.util
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


VIEWER_PATH = Path(__file__).resolve().parents[1] / "sentry-viewer.py"
SPEC = importlib.util.spec_from_file_location("sentry_viewer", VIEWER_PATH)
viewer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(viewer)


class RequestSeiRecheckTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.write_cat = root / "write-cat.json"
        self.req = root / "sei-probe.req"
        self.patches = [
            patch.object(viewer, "WRITE_CAT_FILE", str(self.write_cat)),
            patch.object(viewer, "SEI_REQ_FILE", str(self.req)),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tempdir.cleanup()

    def test_returns_state_written_after_request(self):
        def responder():
            deadline = time.time() + 2
            while time.time() < deadline and not self.req.exists():
                time.sleep(0.01)
            if not self.req.exists():
                return
            state = {"driving": False, "recent": True, "sentry": False,
                     "saved": False, "sei_ts": time.time(), "ts": time.time()}
            self.write_cat.write_text(json.dumps(state))

        th = threading.Thread(target=responder, daemon=True)
        th.start()
        state = viewer.request_sei_recheck(timeout=2.0)
        self.assertIsNotNone(state)
        self.assertIs(state.get("driving"), False)
        self.assertTrue(self.req.exists())

    def test_timeout_returns_none(self):
        self.assertIsNone(viewer.request_sei_recheck(timeout=0.3))

    def test_stale_write_cat_is_not_used(self):
        state = {"driving": False, "sei_ts": time.time() - 10, "ts": time.time() - 100}
        self.write_cat.write_text(json.dumps(state))
        self.assertIsNone(viewer.request_sei_recheck(timeout=0.3))


class UsbConnectGateTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.settings = Path(self.tempdir.name) / "settings.json"
        self.settings.write_text('{"drive_lock": true}')
        self.patch_settings = patch.object(viewer, "SETTINGS_FILE", str(self.settings))
        self.patch_settings.start()

    def tearDown(self):
        self.patch_settings.stop()
        self.tempdir.cleanup()

    def gate(self, recheck, car_active=False, lock=True):
        with patch.object(viewer, "drive_lock_on", return_value=lock), \
             patch.object(viewer, "request_sei_recheck", return_value=recheck), \
             patch.object(viewer, "car_active_for_usb", return_value=car_active):
            return viewer.usb_connect_gate()

    def test_driving_blocks(self):
        ok, msg = self.gate({"driving": True})
        self.assertFalse(ok)
        self.assertIn("即时 SEI 复检确认正在行车", msg)

    def test_parked_allows(self):
        ok, msg = self.gate({"driving": False}, car_active=False)
        self.assertTrue(ok)

    def test_parked_but_recent_driving_blocks(self):
        ok, msg = self.gate({"driving": False}, car_active=True)
        self.assertFalse(ok)
        self.assertIn("近 3 分钟", msg)

    def test_unknown_blocks(self):
        ok, msg = self.gate({"driving": None})
        self.assertFalse(ok)
        self.assertIn("无法判定", msg)

    def test_recheck_timeout_blocks(self):
        ok, msg = self.gate(None)
        self.assertFalse(ok)
        self.assertIn("复检未完成", msg)

    def test_lock_off_does_not_request_recheck(self):
        with patch.object(viewer, "drive_lock_on", return_value=False), \
             patch.object(viewer, "request_sei_recheck") as req:
            ok, _ = viewer.usb_connect_gate()
            self.assertTrue(ok)
            req.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class AttachedWriteWatchTests(unittest.TestCase):
    """已连接 U 盘时车机新写入 -> 即时复检 -> 真行车立即卸载。"""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.image = Path(self.tempdir.name) / "teslacam.img"
        self.image.write_bytes(b"x")
        self.stop = threading.Event()
        self.detach_patch = patch.object(viewer, "usb_detach_safe")
        self.detach = self.detach_patch.start()
        self.patches = [
            patch.object(viewer, "IMG", str(self.image)),
            patch.object(viewer, "usb_attached", True),
            patch.object(viewer, "drive_lock_on", return_value=True),
            patch.object(viewer, "car_active_for_usb", return_value=False),
            patch.object(viewer, "sentry_writing_only", return_value=False),
            patch.object(viewer, "request_sei_recheck", return_value={"driving": True}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        self.stop.set()
        for p in self.patches:
            p.stop()
        self.detach_patch.stop()
        self.tempdir.cleanup()

    def test_new_write_while_driving_detaches(self):
        th = threading.Thread(target=viewer.drive_watch_loop, args=(self.stop,), daemon=True)
        th.start()
        time.sleep(0.3)
        ts = time.time() + 1
        os.utime(self.image, ns=(int(ts * 1e9), int(ts * 1e9)))
        time.sleep(1.4)
        self.detach.assert_called_once()
        self.stop.set()
        th.join(timeout=2)


class NotifyRetryTests(unittest.TestCase):
    """飞书网络短时失败不能把事件永久记成 seen; 必须保留 pending 并退避重试。"""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.archive = root / "archive"
        self.event = self.archive / "SentryClips" / "2026-11-27_12-00-00"
        self.event.mkdir(parents=True)
        clip = self.event / "clip.mp4"
        clip.write_bytes(b"x" * 64)
        old = time.time() - 60
        os.utime(clip, (old, old))
        self.conf = root / "notify.json"
        self.conf.write_text(json.dumps({
            "enabled": True, "mode": "dm", "app_id": "cli_test", "app_secret": "secret",
            "receive_id": "ou_test", "receive_id_type": "open_id", "delay": 20,
        }))
        self.state = root / "notify-state.json"
        self.state.write_text(json.dumps({"init": 1, "seen": {}}))
        self.live_state = root / "live-state.json"
        self.live_state.write_text("{}")
        self.patches = [
            patch.object(viewer, "ARCHIVE", str(self.archive)),
            patch.object(viewer, "NOTIFY_CONF", str(self.conf)),
            patch.object(viewer, "NOTIFY_STATE", str(self.state)),
            # 用例目录名固定为 2026-11-27; 超过 24h 后会被“历史回灌”规则记账不推。
            # 这里把事件时间固定为 1 分钟前, 只测试 pending/退避逻辑, 不依赖跑测试的日期。
            patch.object(viewer, "_ev_ts", return_value=time.time() - 60),
            patch.object(viewer, "LIVE_STATE", str(root / "live-state.json")),
            patch.object(viewer, "LIVE_STATE", str(self.live_state)),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tempdir.cleanup()

    def read_state(self):
        return json.loads(self.state.read_text())

    def test_retry_delay_backoff(self):
        self.assertEqual(viewer.notify_retry_delay(1), 30)
        self.assertEqual(viewer.notify_retry_delay(6), 900)
        self.assertEqual(viewer.notify_retry_delay(20), 900)

    def test_archive_pending_blocks_until_complete(self):
        key = "SentryClips/2026-11-27_12-00-00"
        self.live_state.write_text(json.dumps({
            "__pending__": {key + "/clip.mp4": [64, 64, int(time.time())]}
        }))
        with patch.object(viewer, "notify_push", return_value=(True, "ok")) as push:
            self.assertEqual(viewer.notify_scan(), 0)
        push.assert_not_called()
        st = self.read_state()
        self.assertNotIn(key, st["seen"])

        self.live_state.write_text("{}")
        with patch.object(viewer, "notify_push", return_value=(True, "ok")) as push:
            self.assertEqual(viewer.notify_scan(), 1)
        push.assert_called_once()
        self.assertIn(key, self.read_state()["seen"])

    def test_sentry_push_forces_trigger_thumb(self):
        with patch.object(viewer, "notify_conf", return_value={
                "enabled": True, "mode": "dm", "app_id": "cli_test", "app_secret": "secret",
                "receive_id": "ou_test", "receive_id_type": "open_id"}), \
             patch.object(viewer, "_trigger_frame", return_value=("/tmp/cover.jpg", {})) as frame, \
             patch.object(viewer, "_feishu_upload", return_value="img_key"), \
             patch.object(viewer, "_feishu_card", return_value={"card": "x"}), \
             patch.object(viewer, "_feishu_send_dm", return_value=True):
            ok, _msg = viewer.notify_push("SentryClips", "2026-11-27_12-00-00")
        self.assertTrue(ok)
        self.assertIs(frame.call_args.kwargs.get("force"), True)

    def test_archive_pending_blocks_push(self):
        key = "SentryClips/2026-11-27_12-00-00"
        (Path(self.tempdir.name) / "live-state.json").write_text(json.dumps({
            "__pending__": {key + "/clip.mp4": [64, 64, 1]},
        }))
        with patch.object(viewer, "notify_push") as push:
            self.assertEqual(viewer.notify_scan(), 0)
            push.assert_not_called()
        self.assertNotIn(key, self.read_state()["seen"])

    def test_network_failure_keeps_pending_then_succeeds(self):
        key = "SentryClips/2026-11-27_12-00-00"
        with patch.object(viewer, "notify_push", return_value=(False, "No route to host")):
            self.assertEqual(viewer.notify_scan(), 0)
        st = self.read_state()
        self.assertNotIn(key, st["seen"])
        self.assertGreater(st["retry"][key], int(time.time()))
        self.assertEqual(st["try"][key], 1)

        st["retry"][key] = 0
        self.state.write_text(json.dumps(st))
        with patch.object(viewer, "notify_push", return_value=(True, "已推送")):
            self.assertEqual(viewer.notify_scan(), 1)
        st = self.read_state()
        self.assertIn(key, st["seen"])
        self.assertNotIn(key, st["try"])
        self.assertNotIn(key, st["retry"])


class SentryThumbPolicyTests(unittest.TestCase):
    def test_sentry_clip_path_detection(self):
        self.assertTrue(viewer._is_sentry_clip("/archive/SentryClips/2026-11-27_12-00-00/front.mp4"))
        self.assertFalse(viewer._is_sentry_clip("/archive/RecentClips/2026-11-27_12-00-00/front.mp4"))
        self.assertFalse(viewer._is_sentry_clip("/archive/SavedClips/2026-11-27_12-00-00/front.mp4"))

    def test_sentry_push_forces_cover_decode(self):
        conf = {"enabled": True, "mode": "dm", "app_id": "cli_test", "app_secret": "secret",
                "receive_id": "ou_test", "receive_id_type": "open_id", "media": "thumb"}
        with patch.object(viewer, "notify_conf", return_value=conf), \
             patch.object(viewer, "_trigger_frame", return_value=("/tmp/x.jpg", {})) as frame, \
             patch.object(viewer, "_feishu_upload", return_value="img_key"), \
             patch.object(viewer, "_feishu_send_dm", return_value=True), \
             patch.object(viewer, "_feishu_card", return_value={}):
            ok, msg = viewer.notify_push("SentryClips", "2026-11-27_12-00-00")
        self.assertTrue(ok)
        self.assertIn("已推送", msg)
        self.assertIs(frame.call_args.kwargs.get("force"), True)

    def test_sentry_never_transcodes_video(self):
        conf = {"enabled": True, "mode": "dm", "app_id": "cli_test", "app_secret": "secret",
                "receive_id": "ou_test", "receive_id_type": "open_id",
                "media": "video", "vdur": 30, "quality": "480p"}
        with patch.object(viewer, "notify_conf", return_value=conf), \
             patch.object(viewer, "_trigger_frame", return_value=("/tmp/x.jpg", {})), \
             patch.object(viewer, "_feishu_upload", return_value="img_key"), \
             patch.object(viewer, "_feishu_send_dm", return_value=True), \
             patch.object(viewer, "_feishu_card", return_value={}), \
             patch.object(viewer, "_make_push_video") as video:
            ok, msg = viewer.notify_push("SentryClips", "2026-11-27_12-00-00")
        self.assertTrue(ok)
        self.assertFalse(video.called)
        self.assertNotIn("秒视频", msg)


class DriveStateTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.write_cat = Path(self.tempdir.name) / "write-cat.json"
        self.write_cat.write_text(json.dumps({
            "recent": False, "sentry": False, "saved": False, "driving": False,
            "ts": time.time(),
        }))
        self.patches = [patch.object(viewer, "WRITE_CAT_FILE", str(self.write_cat))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tempdir.cleanup()

    def test_stale_write_cat_is_not_sentry_writing_after_usb_disconnect(self):
        with patch.object(viewer, "car_host_connected", return_value=False), \
             patch.object(viewer, "car_active_for_background", return_value=True):
            self.assertFalse(viewer.sentry_writing_only())
            self.assertFalse(viewer.parked_recording())

    def test_fresh_write_cat_with_active_car_is_sentry_recording(self):
        with patch.object(viewer, "car_host_connected", return_value=True), \
             patch.object(viewer, "car_active_for_background", return_value=True):
            self.assertTrue(viewer.sentry_writing_only())
            self.assertTrue(viewer.parked_recording())


class NotifyVideoGateTests(unittest.TestCase):
    def test_saved_clips_video_falls_back_to_card_while_car_writes(self):
        conf = {"enabled": True, "mode": "dm", "app_id": "cli_test", "app_secret": "secret",
                "receive_id": "ou_test", "receive_id_type": "open_id",
                "media": "video", "vdur": 30, "quality": "480p"}
        with patch.object(viewer, "notify_conf", return_value=conf), \
             patch.object(viewer, "car_active_for_background", return_value=True), \
             patch.object(viewer, "_trigger_frame", return_value=("/tmp/x.jpg", {})), \
             patch.object(viewer, "_feishu_upload", return_value="img_key"), \
             patch.object(viewer, "_feishu_send_dm", return_value=True), \
             patch.object(viewer, "_feishu_card", return_value={}), \
             patch.object(viewer, "_make_push_video") as video:
            ok, msg = viewer.notify_push("SavedClips", "2026-11-27_12-00-00")
        self.assertTrue(ok)
        self.assertFalse(video.called)
        self.assertNotIn("秒视频", msg)


class GetVariantGateTests(unittest.TestCase):
    def test_no_new_transcode_while_car_writes(self):
        with tempfile.TemporaryDirectory() as d, \
             patch.object(viewer, "_variant_path", return_value=str(Path(d) / "none.mp4")), \
             patch.object(viewer, "car_active_for_background", return_value=True):
            self.assertEqual(viewer.get_variant("/tmp/src.mp4", "360p"), "/tmp/src.mp4")

    def test_cached_variant_still_returned_while_car_writes(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "cached.mp4"
            out.write_bytes(b"x")
            with patch.object(viewer, "_variant_path", return_value=str(out)), \
                 patch.object(viewer, "car_active_for_background", return_value=True):
                self.assertEqual(viewer.get_variant("/tmp/src.mp4", "360p"), str(out))
