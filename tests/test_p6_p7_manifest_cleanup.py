from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_engine import base_config, init_remote
from publisher_engine.engine import build, BuildError


class ManifestAndCleanupAcceptanceTests(unittest.TestCase):
    def _fixture(self, root: Path):
        publisher_remote = init_remote(root / "publisher", {"README.md": "publisher fixture\n"})
        source_remote = init_remote(root / "source", {"docs/page.adoc": "= Source page\n"})
        config = base_config(root, publisher_remote, source_remote)
        path = root / "publisher.yml"
        return config, path

    def _write_config(self, cfg, path):
        path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

    def test_p6_final_manifest_counts_itself_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg, path = self._fixture(root)
            self._write_config(cfg, path)
            result = build(path, selected_ids=["guide"])
            site = root / "_site"
            manifest_path = site / "build-manifest.json"
            manifest = __import__("json").loads(manifest_path.read_text(encoding="utf-8"))
            actual_files = [item for item in site.rglob("*") if item.is_file()]
            self.assertEqual(manifest["site_files"], len(actual_files))
            self.assertEqual(manifest["site_bytes"], sum(item.stat().st_size for item in actual_files))
            self.assertEqual(result["site_files"], manifest["site_files"])
            self.assertEqual(result["site_bytes"], manifest["site_bytes"])

    def test_p6_final_manifest_is_included_in_max_files_limit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg, path = self._fixture(root)
            cfg["validation"]["require_build_manifest"] = False
            cfg["validation"]["required_files"] = []
            self._write_config(cfg, path)
            build(path, selected_ids=["guide"])
            manifest = __import__("json").loads((root / "_site" / "build-manifest.json").read_text())
            self.assertGreater(manifest["site_files"], 1)
            import shutil
            shutil.rmtree(root / "_site")
            cfg["validation"]["max_files"] = manifest["site_files"] - 1
            self._write_config(cfg, path)
            with self.assertRaisesRegex(BuildError, "maximum"):
                build(path, selected_ids=["guide"])
            self.assertFalse((root / "_site").exists())

    def test_p6_explicit_required_manifest_is_created_when_manifest_validation_is_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg, path = self._fixture(root)
            cfg["validation"]["require_build_manifest"] = False
            cfg["validation"]["required_files"] = ["build-manifest.json"]
            self._write_config(cfg, path)
            result = build(path, selected_ids=["guide"])
            manifest_path = root / "_site" / "build-manifest.json"
            self.assertTrue(manifest_path.is_file())
            self.assertEqual(result["status"], "success")

    def test_p7_nonfatal_success_cleanup_error_keeps_site_and_is_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg, path = self._fixture(root)
            cfg["workspace"]["fail_on_cleanup_error"] = False
            self._write_config(cfg, path)
            with patch("publisher_engine.engine._remove_tree_strict", side_effect=OSError("injected cleanup fault")) as cleanup:
                result = build(path, selected_ids=["guide"])
            self.assertEqual(cleanup.call_count, 1)
            self.assertEqual(result["status"], "success")
            self.assertIn("injected cleanup fault", result["cleanup_warning"])
            manifest = __import__("json").loads((root / "_site" / "build-manifest.json").read_text())
            self.assertIn("injected cleanup fault", manifest["cleanup_warning"])

    def test_p7_fatal_success_cleanup_error_does_not_install_site(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg, path = self._fixture(root)
            cfg["workspace"]["fail_on_cleanup_error"] = True
            self._write_config(cfg, path)
            with patch("publisher_engine.engine._remove_tree_strict", side_effect=OSError("injected cleanup fault")):
                with self.assertRaisesRegex(BuildError, "cleanup"):
                    build(path, selected_ids=["guide"])
            self.assertFalse((root / "_site").exists())

    def test_p7_cleanup_on_success_false_is_independent_of_cleanup_error_policy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg, path = self._fixture(root)
            cfg["workspace"]["cleanup_on_success"] = False
            cfg["workspace"]["fail_on_cleanup_error"] = True
            self._write_config(cfg, path)
            with patch("publisher_engine.engine._remove_tree_strict", side_effect=AssertionError("cleanup must not be attempted")) as cleanup:
                result = build(path, selected_ids=["guide"])
            cleanup.assert_not_called()
            self.assertEqual(result["status"], "success")
            self.assertTrue(list((root / "runs").iterdir()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
