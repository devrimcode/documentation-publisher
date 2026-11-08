from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from publisher_engine.gitops import integrate_subtree


class GitLfsPathFilterTests(unittest.TestCase):
    def _exercise(self, source_root: str):
        with tempfile.TemporaryDirectory() as td:
            publisher = Path(td) / "publisher"
            publisher.mkdir()
            source = {
                "id": "docs",
                "root": source_root,
                "vcs": {"provider": "git", "clone_url": str(Path(td) / "source.git"),
                        "default_ref": "main", "ref_type": "branch", "depth": 1,
                        "lfs": True, "clone_timeout_seconds": 60},
                "integration": {"mode": "git_subtree", "prefix": "vendor/generated-docs",
                                "squash": True, "history": "shallow"},
            }
            sha = "a" * 40
            seen = []

            def fake_run_git(args, cwd=None, env=None, timeout=600):
                seen.append(list(args))
                if args[:2] == ["rev-parse", "FETCH_HEAD"]:
                    return sha
                if args[:2] == ["rev-parse", "HEAD"]:
                    return sha
                if args[:2] == ["subtree", "add"]:
                    (publisher / "vendor/generated-docs").mkdir(parents=True, exist_ok=True)
                return ""

            fake_completed = subprocess.CompletedProcess(["git", "lfs", "version"], 0, "git-lfs/3.x", "")
            with patch("publisher_engine.gitops.ensure_git_subtree"), \
                 patch("publisher_engine.gitops.run_git", side_effect=fake_run_git), \
                 patch("publisher_engine.gitops.make_askpass_env", side_effect=lambda auth, env, run_root: (env, None)), \
                 patch("publisher_engine.gitops.run_process", return_value=fake_completed):
                integrate_subtree(publisher, source, Path(td), Path(td) / "run", {})
            return [args for args in seen if args[:2] == ["lfs", "fetch"]]

    def test_lfs_include_uses_source_root_not_publisher_destination_prefix(self):
        calls = self._exercise("manuals/en")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2], "--include=manuals/en/**")
        self.assertNotIn("vendor/generated-docs/**", calls[0])

    def test_lfs_include_for_repository_root_covers_source_tree(self):
        calls = self._exercise(".")
        self.assertEqual(calls[0][2], "--include=**")

    @unittest.skipUnless(shutil.which("git-lfs"), "real git-lfs client is not installed in this environment")
    def test_real_git_lfs_transfer_requires_local_lfs_server_fixture(self):
        # This is the environment-gated acceptance hook for a real client transfer.
        # The deterministic command-argument tests above still run without git-lfs.
        self.skipTest("real transfer harness requires an installed git-lfs client and an HTTP LFS batch/object fixture")


if __name__ == "__main__":
    unittest.main(verbosity=2)
