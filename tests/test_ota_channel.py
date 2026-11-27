import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "sentry-viewer.py"
SPEC = importlib.util.spec_from_file_location("sentry_viewer", MODULE_PATH)
viewer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(viewer)


class ChannelSettingsTests(unittest.TestCase):
    def setUp(self):
        self.orig = viewer.SETTINGS_FILE
        self.dir = Path(__file__).resolve().parent / "_tmp_settings"
        self.dir.mkdir(exist_ok=True)
        viewer.SETTINGS_FILE = str(self.dir / "settings.json")

    def tearDown(self):
        viewer.SETTINGS_FILE = self.orig
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def test_default_channel_is_stable(self):
        self.assertEqual(viewer._ota_channel(), "stable")
        self.assertEqual(viewer._ota_branch(), "main")

    def test_beta_channel_maps_to_beta_branch(self):
        viewer.save_settings({"update_channel": "beta"})
        self.assertEqual(viewer._ota_channel(), "beta")
        self.assertEqual(viewer._ota_branch(), "beta")

    def test_invalid_channel_falls_back_to_stable(self):
        viewer.save_settings({"update_channel": "nightly"})
        self.assertEqual(viewer._ota_channel(), "stable")
        self.assertEqual(viewer._ota_branch(), "main")

    def test_sources_follow_branch(self):
        main_src = viewer._ota_sources_for("main")
        beta_src = viewer._ota_sources_for("beta")
        self.assertTrue(main_src and beta_src)
        self.assertTrue(all("/main" in s or "@main" in s for s in main_src))
        self.assertTrue(all("/beta" in s or "@beta" in s for s in beta_src))
        self.assertEqual(len(main_src), len(beta_src))


class ManifestMergeTests(unittest.TestCase):
    def setUp(self):
        self.orig = viewer.SETTINGS_FILE
        self.dir = Path(__file__).resolve().parent / "_tmp_merge"
        self.dir.mkdir(exist_ok=True)
        viewer.SETTINGS_FILE = str(self.dir / "settings.json")
        viewer._OTA_CACHE.clear()

    def tearDown(self):
        viewer.SETTINGS_FILE = self.orig
        viewer._OTA_CACHE.clear()
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def _run(self, raced, api, branch="beta"):
        viewer.save_settings({"update_channel": branch})
        raw = json.dumps(raced).encode()

        def fake_race(path, timeout, limit, validate=None, collect=False, grace=1.0, sources=None):
            return [("https://mirror.example", raw)]

        with patch.object(viewer, "_race_get", fake_race), \
                patch.object(viewer, "_api_manifest", lambda timeout=5, branch=None: api):
            return viewer.ota_latest(True)

    def test_api_manifest_wins_on_equal_version(self):
        # 镜像 CDN 已缓存新版本号但仍是旧 notes, API 同版本应覆盖
        old = {"version": "3.2.19", "notes": ["旧说明"]}
        new = {"version": "3.2.19", "notes": ["新说明"]}
        j = self._run(old, new)
        self.assertEqual(j.get("notes"), ["新说明"])
        self.assertEqual(j.get("_channel"), "beta")
        self.assertEqual(j.get("_branch"), "beta")

    def test_api_manifest_wins_on_newer_version(self):
        j = self._run({"version": "3.2.18"}, {"version": "3.2.19", "notes": ["新"]})
        self.assertEqual(j.get("version"), "3.2.19")

    def test_mirror_kept_when_newer_than_api(self):
        j = self._run({"version": "3.2.20", "notes": ["镜像新"]}, {"version": "3.2.19"})
        self.assertEqual(j.get("version"), "3.2.20")
        self.assertEqual(j.get("_base"), "https://mirror.example")

    def test_cache_is_per_channel(self):
        self._run({"version": "3.2.19", "notes": ["beta"]}, None, branch="beta")
        self._run({"version": "3.2.17", "notes": ["main"]}, None, branch="stable")
        self.assertIn("beta", viewer._OTA_CACHE)
        self.assertIn("stable", viewer._OTA_CACHE)
        self.assertEqual(viewer._OTA_CACHE["beta"]["data"].get("notes"), ["beta"])
        self.assertEqual(viewer._OTA_CACHE["stable"]["data"].get("notes"), ["main"])

    def test_all_sources_fail_but_api_works(self):
        viewer.save_settings({"update_channel": "beta"})

        def boom(*a, **k):
            raise RuntimeError("all down")

        with patch.object(viewer, "_race_get", boom), \
                patch.object(viewer, "_api_manifest", lambda timeout=5, branch=None: {"version": "3.2.19"}):
            j = viewer.ota_latest(True)
        self.assertEqual(j.get("version"), "3.2.19")
        self.assertEqual(j.get("_base"), "https://api.github.com")


class VersionTupleTests(unittest.TestCase):
    def test_numeric_ordering(self):
        self.assertGreater(viewer._vtuple("3.2.10"), viewer._vtuple("3.2.9"))
        self.assertEqual(viewer._vtuple("3.2.19"), viewer._vtuple("3.2.19"))
        self.assertGreater(viewer._vtuple("4.0.0"), viewer._vtuple("3.99.99"))


if __name__ == "__main__":
    unittest.main()
