from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / ".devcontainer" / "verify-environment.sh"


class DevContainerRuntimeVerifierTests(unittest.TestCase):
    def make_fixture(self, *, java_major: int = 25, install_jdk21: bool = True,
                     lfs_version: str = "3.8.1", maven_version: str = "3.10.0",
                     python_wrapper: str | None = None):
        td = tempfile.TemporaryDirectory()
        base = Path(td.name)
        repo = base / "repo"
        bin_dir = base / "bin"
        sdkman = base / "sdkman"
        repo.mkdir()
        bin_dir.mkdir()
        candidates = sdkman / "candidates" / "java"
        candidates.mkdir(parents=True)
        git_exec = base / "active-git-exec"
        git_exec.mkdir()
        helper_dir = base / "usr" / "lib" / "git-core"
        helper_dir.mkdir(parents=True)
        helper = helper_dir / "git-subtree"
        helper.write_text("#!/bin/sh\necho 'fixture subtree helper'\n", encoding="utf-8")
        helper.chmod(0o755)
        (git_exec / "git-subtree").symlink_to(helper)

        git = bin_dir / "git"
        git.write_text(
            "#!/usr/bin/env bash\n"
            "case \"${1:-}\" in\n"
            "  rev-parse) pwd ;;\n"
            f"  --exec-path) echo {str(git_exec)!r} ;;\n"
            "  --version) echo 'git version 2.39.5' ;;\n"
            f"  subtree) if [[ -x {str(git_exec / 'git-subtree')!r} ]]; then echo 'usage: git subtree add'; else echo 'git subtree missing' >&2; exit 1; fi ;;\n"
            f"  lfs) echo 'git-lfs/{lfs_version} (test fixture)' ;;\n"
            "  *) echo \"unexpected git arguments: $*\" >&2; exit 2 ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        git.chmod(0o755)

        java = bin_dir / "java"
        java.write_text(
            "#!/usr/bin/env bash\n"
            f"echo 'openjdk version \"{java_major}.0.2\" 2026-10-01' >&2\n",
            encoding="utf-8",
        )
        java.chmod(0o755)

        maven = bin_dir / "mvn"
        maven.write_text(f"#!/usr/bin/env bash\necho 'Apache Maven {maven_version}'\n", encoding="utf-8")
        maven.chmod(0o755)

        if install_jdk21:
            jdk21 = candidates / "21.0.8-tem"
            (jdk21 / "bin").mkdir(parents=True)
            jdk21_java = jdk21 / "bin" / "java"
            jdk21_java.write_text(
                "#!/usr/bin/env bash\necho 'openjdk version \"21.0.8\" 2026-08-01' >&2\n",
                encoding="utf-8",
            )
            jdk21_java.chmod(0o755)

        env = os.environ.copy()
        env.pop("GIT_EXEC_PATH", None)
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
        env["SDKMAN_DIR"] = str(sdkman)
        # The APT lock verifier is exercised against isolated, deterministic fixtures;
        # no host package database or /etc/apt source file is read by these tests.
        apt_sources = base / "debian-snapshot.sources"
        apt_sources.write_text(
            "Types: deb\n"
            "URIs: https://snapshot.debian.org/archive/debian/20261107T000000Z/\n"
            "Suites: bookworm bookworm-updates\n"
            "Components: main\n"
            "Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg\n"
            "Check-Valid-Until: no\n\n"
            "Types: deb\n"
            "URIs: https://snapshot.debian.org/archive/debian-security/20261107T000000Z/\n"
            "Suites: bookworm-security\n"
            "Components: main\n"
            "Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg\n"
            "Check-Valid-Until: no\n",
            encoding="utf-8",
        )
        import hashlib
        source_sha = hashlib.sha256(apt_sources.read_bytes()).hexdigest()
        apt_state = base / "apt-state"
        apt_state.mkdir()
        helper_sha = hashlib.sha256(helper.read_bytes()).hexdigest()
        (apt_state / "toolchain-lock.tsv").write_text(
            "# format=devcontainer-apt-lock-v3\n"
            "# snapshot=20261107T000000Z\n"
            f"# source-sha256={source_sha}\n"
            "# architecture=amd64\n"
            "# apt-version=apt 2.6.1 (amd64)\n"
            "# dpkg-version=1.21.22\n"
            "# base-image-ref=mcr.microsoft.com/devcontainers/python:3.13-bookworm@sha256:ac334d90ca71f23b58820c90a440b400d175b77d642d312cf67ff0cc9cb2056d\n"
            "# build-platform=linux/amd64\n"
            "# git-version=git version 2.39.5\n"
            "# subtree-package=git\n"
            "# subtree-package-version=1:2.39.5-0+deb12u3\n"
            f"# subtree-source={helper}\n"
            f"# subtree-source-sha256={helper_sha}\n"
            f"# git-exec-path={git_exec}\n"
            f"# subtree-target={git_exec / 'git-subtree'}\n"
            f"# subtree-target-realpath={helper}\n"
            "# package\tversion\n"
            "git\t1:2.39.5-0+deb12u3\n",
            encoding="utf-8",
        )
        dpkg_query = bin_dir / "dpkg-query"
        dpkg_query.write_text(
            "#!/usr/bin/env bash\n"
            "if [[ \"${1:-}\" == \"-S\" ]]; then printf 'git: %s\\n' \"$2\"; exit 0; fi\n"
            "if [[ \"${1:-}\" == \"-W\" && \"${2:-}\" == *Version* ]]; then\n"
            "  case \"${3:-}\" in dpkg) echo 1.21.22 ;; git) echo \"${FAKE_GIT_PACKAGE_VERSION:-1:2.39.5-0+deb12u3}\" ;; *) exit 1 ;; esac\n"
            "else exit 2; fi\n",
            encoding="utf-8",
        )
        dpkg_query.chmod(0o755)
        dpkg = bin_dir / "dpkg"
        dpkg.write_text("#!/usr/bin/env bash\necho \"${FAKE_DPKG_ARCH:-amd64}\"\n", encoding="utf-8")
        dpkg.chmod(0o755)
        apt_get = bin_dir / "apt-get"
        apt_get.write_text("#!/usr/bin/env bash\necho \"${FAKE_APT_VERSION:-apt 2.6.1 (amd64)}\"\n", encoding="utf-8")
        apt_get.chmod(0o755)
        env["DEBIAN_SNAPSHOT"] = "20261107T000000Z"
        env["PUBLISHER_BASE_IMAGE_REF"] = "mcr.microsoft.com/devcontainers/python:3.13-bookworm@sha256:ac334d90ca71f23b58820c90a440b400d175b77d642d312cf67ff0cc9cb2056d"
        env["PUBLISHER_BUILD_PLATFORM"] = "linux/amd64"
        env["APT_SOURCES_FILE"] = str(apt_sources)
        env["APT_SOURCES_DIR"] = str(base)
        env["APT_ROOT_SOURCES"] = str(base / "sources.list")
        env["APT_LOCK_FILE"] = str(apt_state / "toolchain-lock.tsv")
        env["DPKG_QUERY_BIN"] = str(dpkg_query)
        env["DPKG_BIN"] = str(dpkg)
        env["APT_GET_BIN"] = str(apt_get)
        if python_wrapper is None:
            python_wrapper = (
                "#!/usr/bin/env bash\n"
                'if [[ "${1:-}" == "--version" ]]; then echo \"Python 3.13.5\"; exit 0; fi\n'
                f"exec {sys.executable!r} \"$@\"\n"
            )
        py = bin_dir / "python3"
        py.write_text(python_wrapper, encoding="utf-8")
        py.chmod(0o755)
        return td, repo, env

    def run_verifier(self, repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(VERIFY)], cwd=repo, env=env,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15,
        )

    def test_declared_runtime_contract_passes_when_all_tools_match(self):
        td, repo, env = self.make_fixture()
        with td:
            result = self.run_verifier(repo, env)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Python: Python 3.13", result.stdout)
        self.assertIn("Debian snapshot and Git Subtree base-image lock: verified", result.stdout)
        self.assertIn("Java 21 additional JDK: installed", result.stdout)
        self.assertIn("Maven: Apache Maven 3.10.0", result.stdout)
        self.assertIn("Git LFS: git-lfs/3.8.1", result.stdout)

    def test_verifier_rejects_java_21_as_the_active_default(self):
        td, repo, env = self.make_fixture(java_major=21)
        with td:
            result = self.run_verifier(repo, env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Java 25 must be the active default JDK", result.stdout)

    def test_verifier_rejects_missing_additional_jdk_21(self):
        td, repo, env = self.make_fixture(install_jdk21=False)
        with td:
            result = self.run_verifier(repo, env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("JDK 21 must be installed as an additional", result.stdout)

    def test_verifier_rejects_wrong_git_lfs_and_maven_versions(self):
        td, repo, env = self.make_fixture(lfs_version="3.7.1", maven_version="3.9.16")
        with td:
            result = self.run_verifier(repo, env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Expected Git LFS 3.8.1", result.stdout)

        td, repo, env = self.make_fixture(lfs_version="3.8.1", maven_version="3.9.16")
        with td:
            result = self.run_verifier(repo, env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Expected Maven 3.10.0", result.stdout)

    def test_verifier_rejects_drift_in_git_package_owning_subtree_helper(self):
        td, repo, env = self.make_fixture()
        env["FAKE_GIT_PACKAGE_VERSION"] = "1:2.39.5-0+deb12u4"
        with td:
            result = self.run_verifier(repo, env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Git package version drift", result.stdout)

    def test_verifier_rejects_apt_toolchain_or_architecture_drift(self):
        td, repo, env = self.make_fixture()
        env["FAKE_APT_VERSION"] = "apt 2.6.2 (amd64)"
        with td:
            result = self.run_verifier(repo, env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("APT version drift", result.stdout)

        td, repo, env = self.make_fixture()
        env["FAKE_DPKG_ARCH"] = "arm64"
        with td:
            result = self.run_verifier(repo, env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("APT architecture drift", result.stdout)

    def test_verifier_rejects_non_313_python(self):
        real_python = subprocess.check_output(["bash", "-lc", "command -v python3"], text=True).strip()
        wrapper = f"#!/usr/bin/env bash\nif [[ \"${{1:-}}\" == \"--version\" ]]; then echo 'Python 3.12.8'; exit 0; fi\nexec {real_python!r} \"$@\"\n"
        td, repo, env = self.make_fixture(python_wrapper=wrapper)
        with td:
            result = self.run_verifier(repo, env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Codespaces image must provide Python 3.13 exactly", result.stdout)


if __name__ == "__main__":
    unittest.main()
