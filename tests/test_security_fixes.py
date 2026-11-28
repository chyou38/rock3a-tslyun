import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "sentry-viewer.py"
SPEC = importlib.util.spec_from_file_location("sentry_viewer_security", MODULE_PATH)
viewer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(viewer)


class OtaManifestTrustTests(unittest.TestCase):
    def test_newer_manifest_requires_signature(self):
        raw = json.dumps({"version": "9.9.9", "notes": ["evil"]}).encode()
        ok, why = viewer._ota_manifest_trust(raw)
        self.assertFalse(ok)
        self.assertIn("签名", why)

    def test_old_unsigned_manifest_allowed_for_display(self):
        raw = json.dumps({"version": "0.0.1", "notes": []}).encode()
        ok, why = viewer._ota_manifest_trust(raw)
        self.assertTrue(ok, why)

    def test_repo_manifest_signature_verifies(self):
        # 发布前脚本会签名 version.json; 这个断言防止忘了签名/签名规则不一致
        raw = (Path(__file__).resolve().parents[1] / "version.json").read_bytes()
        ok, why = viewer._ota_manifest_trust(raw)
        self.assertTrue(ok, why)

    def test_tampered_signed_manifest_rejected(self):
        raw = (Path(__file__).resolve().parents[1] / "version.json").read_bytes()
        j = json.loads(raw)
        j["notes"] = ["tampered"]
        raw2 = json.dumps(j, ensure_ascii=False).encode()
        ok, _why = viewer._ota_manifest_trust(raw2)
        self.assertFalse(ok)


class CustomDirPathTests(unittest.TestCase):
    def test_settings_and_auth_share_runtime_dir(self):
        # 默认安装/自定义安装都必须让 auth.conf 与 settings.json 同目录;
        # 否则 --dir 安装会静默关掉认证或读不到设置。
        self.assertEqual(os.path.dirname(viewer.SETTINGS_FILE), os.path.dirname(viewer.AUTH_FILE))
        self.assertEqual(os.path.dirname(viewer.NOTIFY_CONF), os.path.dirname(viewer.AUTH_FILE))
        self.assertEqual(os.path.dirname(viewer.OTA_BACKUP), os.path.dirname(viewer.AUTH_FILE))

    def test_custom_dir_import_uses_tsf_dir(self):
        # 真实 --dir 场景: 用子进程设 TSF_DIR 后导入, 所有状态路径必须落在该目录
        with tempfile.TemporaryDirectory() as td:
            env = os.environ.copy()
            env["TSF_DIR"] = td
            for k in ("TSF_SETTINGS", "TSF_AUTH_FILE", "TSF_NOTIFY_CONF", "TSF_OTA_BACKUP"):
                env.pop(k, None)
            code = ("import importlib.util,json,sys;"
                    "s=importlib.util.spec_from_file_location('v', %r);"
                    "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
                    "print(json.dumps({'settings':m.SETTINGS_FILE,'auth':m.AUTH_FILE,"
                    "'notify':m.NOTIFY_CONF,'ota':m.OTA_BACKUP}))"
                    % str(MODULE_PATH))
            r = subprocess.run([sys.executable, "-c", code], env=env,
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr[-300:])
            d = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertEqual(os.path.dirname(d["settings"]), td)
            self.assertEqual(os.path.dirname(d["auth"]), td)
            self.assertEqual(os.path.dirname(d["notify"]), td)
            self.assertEqual(os.path.dirname(d["ota"]), td)


class SidecarRollbackTests(unittest.TestCase):
    def test_rollback_restores_script_and_removes_state(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / "tesla-gadget.sh").write_text("NEW")
            bk = td / "backup-sidecar-3.2.44"
            bk.mkdir()
            (bk / "tesla-gadget.sh").write_text("OLD")
            state = td / "ota-sidecar-state.json"
            state.write_text(json.dumps({"version": "3.2.44", "dir": str(bk),
                                         "files": ["tesla-gadget.sh"]}))
            with patch.object(viewer, "RUNTIME_DIR", str(td)), \
                    patch.object(viewer, "OTA_SIDECAR_STATE", str(state)):
                restored = viewer._ota_sidecar_rollback()
            self.assertEqual(restored, ["tesla-gadget.sh"])
            self.assertEqual((td / "tesla-gadget.sh").read_text(), "OLD")
            self.assertFalse(state.exists())


class ArchiveWatermarkFallbackTests(unittest.TestCase):
    def test_separate_disk_uses_physical_capacity_and_deletes(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            base = td / "SentryClips" / "2026-11-20_10-00-00"
            base.mkdir(parents=True)
            (base / "clip.mp4").write_bytes(b"x")
            old = time.time() - 7200
            os.utime(base / "clip.mp4", (old, old))
            os.utime(base, (old, old))
            with patch.object(viewer, "ARCHIVE", str(td)), \
                    patch.object(viewer, "_archive_capacity", return_value=(1000, 950, True)), \
                    patch.object(viewer, "archive_low_water_pct", return_value=10), \
                    patch.object(viewer, "_archive_quota", return_value=0), \
                    patch.object(viewer, "_invalidate_storage_caches"), \
                    patch.object(viewer, "preview_cleanup"), \
                    patch.object(viewer, "thumb_cleanup"):
                n = viewer.roll_archive_capacity()
            self.assertGreaterEqual(n, 1)
            self.assertFalse(base.exists())


class FeishuTokenResetTests(unittest.TestCase):
    def test_saving_new_app_credentials_drops_cached_token(self):
        with tempfile.TemporaryDirectory() as td:
            conf = Path(td) / "notify.json"
            conf.write_text(json.dumps({"app_id": "old", "app_secret": "oldsecret"}))
            with patch.object(viewer, "NOTIFY_CONF", str(conf)):
                viewer._TOK.update({"v": "cached", "exp": time.time() + 9999, "app": "old\0oldsecret"})
                viewer.notify_save({"app_id": "new", "app_secret": "newsecret"})
                self.assertEqual(viewer._TOK["v"], "")
                self.assertEqual(viewer._TOK["exp"], 0)


class LoginNextTests(unittest.TestCase):
    def test_crlf_and_protocol_relative_rejected(self):
        self.assertEqual(viewer.Handler._safe_next(None, "/ok\r\nSet-Cookie: x"), "/")
        self.assertEqual(viewer.Handler._safe_next(None, "//evil"), "/")
        self.assertEqual(viewer.Handler._safe_next(None, "https://evil"), "/")
        self.assertEqual(viewer.Handler._safe_next(None, "/a?b=1"), "/a?b=1")


class ExportJobIdTests(unittest.TestCase):
    def test_traversal_chars_removed(self):
        jid = viewer._job_component("../../etc/passwd")
        self.assertNotIn("/", jid)
        self.assertNotIn("\\", jid)
        self.assertNotIn("..", jid)
        self.assertEqual(viewer._job_component("a/b"), "a_b")


class LoginFailureMapTests(unittest.TestCase):
    def setUp(self):
        viewer.FAILS.clear()

    def tearDown(self):
        viewer.FAILS.clear()

    def test_read_check_does_not_insert(self):
        self.assertFalse(viewer.fail_check("1.2.3.4", False))
        self.assertNotIn("1.2.3.4", viewer.FAILS)

    def test_eight_failures_lock_without_unbounded_entries(self):
        ip = "5.6.7.8"
        for i in range(7):
            self.assertFalse(viewer.fail_check(ip, True), i)
        self.assertTrue(viewer.fail_check(ip, True))
        self.assertTrue(viewer.fail_check(ip, False))
        self.assertEqual(len(viewer.FAILS), 1)

    def test_many_ips_do_not_grow_table_past_cap(self):
        with patch.object(viewer, "FAIL_MAX", 8):
            for i in range(40):
                viewer.fail_check("10.0.0.%d" % i, True)
        self.assertLessEqual(len(viewer.FAILS), 8)


class ReclaimJournalTests(unittest.TestCase):
    def test_recover_restores_original_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            img = td / "teslacam.img"
            img.write_bytes(b"NEW0" + b"unchanged")
            journal = td / "teslacam.img.reclaim-journal"
            writes = [(0, b"ORIG", b"NEW0")]
            with patch.object(viewer, "IMG", str(img)), \
                    patch.object(viewer, "RECLAIM_JOURNAL", str(journal)):
                viewer._reclaim_journal_write(writes)
                self.assertTrue(journal.exists())
                self.assertTrue(viewer._reclaim_recover())
            self.assertEqual(img.read_bytes()[:4], b"ORIG")
            self.assertFalse(journal.exists())

    def test_truncated_journal_is_not_applied(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            img = td / "teslacam.img"
            img.write_bytes(b"NEW0")
            journal = td / "teslacam.img.reclaim-journal"
            journal.write_bytes(b"TSRJ" + struct.pack("<I", 100))  # 头不完整
            with patch.object(viewer, "IMG", str(img)), \
                    patch.object(viewer, "RECLAIM_JOURNAL", str(journal)):
                self.assertFalse(viewer._reclaim_recover())
            self.assertEqual(img.read_bytes(), b"NEW0")


class UpdateWindowGateTests(unittest.TestCase):
    def test_usb_sync_blocks_auto_update(self):
        with patch.object(viewer, "MEDIA_ACTIVE", [0]), \
                patch.object(viewer, "car_active_for_background", return_value=False), \
                patch.object(viewer, "usb_sync_busy", return_value=True), \
                patch.object(viewer, "STITCH_JOBS", {}):
            self.assertFalse(viewer._update_window_ok())

    def test_pending_network_rollback_blocks_auto_update(self):
        with patch.object(viewer, "MEDIA_ACTIVE", [0]), \
                patch.object(viewer, "car_active_for_background", return_value=False), \
                patch.object(viewer, "usb_sync_busy", return_value=False), \
                patch.object(viewer, "_net_roll_read", return_value={"config": "network: {}\n"}), \
                patch.object(viewer, "STITCH_JOBS", {}):
            self.assertFalse(viewer._update_window_ok())


class NetRollStateTests(unittest.TestCase):
    def test_state_roundtrip_and_clear(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "net-rollback.json"
            with patch.object(viewer, "NET_ROLL_STATE", str(state)):
                viewer._net_roll_save("network: {}\n", time.time() + 90)
                st = viewer._net_roll_read()
                self.assertEqual(st["config"], "network: {}\n")
                viewer._net_roll_clear()
                self.assertIsNone(viewer._net_roll_read())


class UploadCapTests(unittest.TestCase):
    def test_small_route_rejects_big_body_before_read(self):
        h = object.__new__(viewer.Handler)
        h.headers = {"Content-Type": "multipart/form-data; boundary=x",
                     "Content-Length": str(4 * 1024 * 1024)}
        h.rfile = None                       # 超限时不应读 body
        self.assertEqual(h._read_upload(3 * 1024 * 1024)[0], "TOOBIG")


if __name__ == "__main__":
    unittest.main()
