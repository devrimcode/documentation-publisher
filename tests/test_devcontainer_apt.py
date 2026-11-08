from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEVCONTAINER = ROOT / ".devcontainer"
INSTALL = DEVCONTAINER / "install-apt-snapshot.sh"
VERIFY = DEVCONTAINER / "verify-apt-state.sh"
SNAPSHOT = "20261107T000000Z"
BASE_IMAGE = (
    "mcr.microsoft.com/devcontainers/python:3.13-bookworm@sha256:"
    "ac334d90ca71f23b58820c90a440b400d175b77d642d312cf67ff0cc9cb2056d"
)
GIT_VERSION = "1:2.39.5-0+deb12u3"


class DevContainerAptSnapshotTests(unittest.TestCase):
    def _fixture(self, root: Path):
        bin_dir = root / "bin"
        bin_dir.mkdir()
        state_dir = root / "state"
        state_dir.mkdir()
        sources_dir = root / "sources.d"
        sources_dir.mkdir()
        sources = sources_dir / "debian-snapshot.sources"
        sources.write_text(
            f"Types: deb\nURIs: https://snapshot.debian.org/archive/debian/{SNAPSHOT}/\n"
            "Suites: bookworm bookworm-updates\nComponents: main\n"
            "Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg\nCheck-Valid-Until: no\n\n"
            f"Types: deb\nURIs: https://snapshot.debian.org/archive/debian-security/{SNAPSHOT}/\n"
            "Suites: bookworm-security\nComponents: main\n"
            "Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg\nCheck-Valid-Until: no\n",
            encoding="utf-8",
        )
        active_exec = root / "active-git-exec"
        active_exec.mkdir()
        helper = bin_dir / "git-subtree"
        helper.write_text("#!/bin/sh\necho 'fixture git-subtree helper'\n", encoding="utf-8")
        helper.chmod(0o755)
        apt_log = root / "apt.log"
        apt = bin_dir / "apt-get"
        apt.write_text(
            "#!/usr/bin/env bash\n"
            f"printf '%s\\n' \"$*\" >> {str(apt_log)!r}\n"
            "case \" $* \" in\n"
            "  *'--version'*) echo 'apt 2.6.1 (amd64)'; exit 0 ;;\n"
            "  *' update '*) exit 0 ;;\n"
            "  *) echo \"unexpected apt-get arguments: $*\" >&2; exit 9 ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        apt.chmod(0o755)
        git = bin_dir / "git"
        git.write_text(
            "#!/usr/bin/env bash\n"
            "case \"${1:-}\" in\n"
            f"  --exec-path) printf '%s\\n' {str(active_exec)!r} ;;\n"
            "  --version) echo 'git version 2.39.5' ;;\n"
            f"  subtree) if [[ -x {str(active_exec / 'git-subtree')!r} ]]; then echo 'usage: git subtree add'; exit 129; else echo 'git: subtree unavailable' >&2; exit 1; fi ;;\n"
            "  *) echo \"unexpected git arguments: $*\" >&2; exit 2 ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        git.chmod(0o755)
        dpkg_query = bin_dir / "dpkg-query"
        dpkg_query.write_text(
            "#!/usr/bin/env bash\n"
            "if [[ \"${1:-}\" == '-S' ]]; then printf '%s: %s\\n' \"${FAKE_DPKG_OWNER:-git}\" \"$2\"; exit 0; fi\n"
            "[[ \"${1:-}\" == '-W' ]] || exit 2\n"
            "case \"${3:-}\" in\n"
            "  dpkg) printf '1.21.22\\n' ;;\n"
            f"  git) printf '%s\\n' \"${{FAKE_GIT_PACKAGE_VERSION:-{GIT_VERSION}}}\" ;;\n"
            "  *) exit 1 ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        dpkg_query.chmod(0o755)
        dpkg = bin_dir / "dpkg"
        dpkg.write_text("#!/usr/bin/env bash\necho \"${FAKE_DPKG_ARCH:-amd64}\"\n", encoding="utf-8")
        dpkg.chmod(0o755)

        env = os.environ.copy()
        env.pop("GIT_EXEC_PATH", None)
        env.update({
            "PATH": str(bin_dir) + os.pathsep + env.get("PATH", ""),
            "DEBIAN_SNAPSHOT": SNAPSHOT,
            "PUBLISHER_BASE_IMAGE_REF": BASE_IMAGE,
            "PUBLISHER_BUILD_PLATFORM": "linux/amd64",
            "APT_GET_BIN": str(apt),
            "DPKG_QUERY_BIN": str(dpkg_query),
            "DPKG_BIN": str(dpkg),
            "GIT_BIN": str(git),
            "APT_SOURCES_FILE": str(sources),
            "APT_SOURCES_DIR": str(sources.parent),
            "APT_ROOT_SOURCES": str(root / "sources.list"),
            "APT_STATE_DIR": str(state_dir),
            "APT_LOCK_FILE": str(state_dir / "toolchain-lock.tsv"),
            # Keep test fixtures independent of helpers installed in the real
            # Codespaces image (notably /usr/local/libexec/git-core/git-subtree).
            "GIT_SUBTREE_FALLBACK_PATHS": "",
        })
        return {
            "root": root, "bin": bin_dir, "state": state_dir, "sources": sources,
            "helper": helper, "active_exec": active_exec, "apt": apt,
            "apt_log": apt_log, "git": git, "dpkg_query": dpkg_query,
            "dpkg": dpkg, "env": env,
        }

    def _run(self, script: Path, env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(script)], cwd=cwd, env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15,
        )

    def test_snapshot_template_freezes_bookworm_updates_and_security(self):
        template = (DEVCONTAINER / "debian-snapshot.sources.in").read_text(encoding="utf-8")
        self.assertEqual(template.count("@DEBIAN_SNAPSHOT@"), 2)
        self.assertIn("archive/debian/@DEBIAN_SNAPSHOT@/", template)
        self.assertIn("archive/debian-security/@DEBIAN_SNAPSHOT@/", template)
        self.assertIn("Suites: bookworm bookworm-updates", template)
        self.assertIn("Suites: bookworm-security", template)
        self.assertEqual(template.count("Check-Valid-Until: no"), 2)
        self.assertEqual(template.count("Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg"), 2)

    def test_dockerfile_pins_image_platform_and_does_not_install_nonexistent_package(self):
        dockerfile = (DEVCONTAINER / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn(f"FROM {BASE_IMAGE}", dockerfile)
        self.assertIn(f'ENV PUBLISHER_BASE_IMAGE_REF="{BASE_IMAGE}"', dockerfile)
        self.assertIn('ENV PUBLISHER_BUILD_PLATFORM="linux/amd64"', dockerfile)
        self.assertIn("ARG DEBIAN_SNAPSHOT=20261107T000000Z", dockerfile)
        self.assertIn("bash /usr/local/sbin/install-apt-snapshot.sh", dockerfile)
        self.assertIn("bash /usr/local/sbin/verify-apt-state.sh", dockerfile)
        self.assertNotIn("apt-get install", dockerfile)
        self.assertNotIn("apt-get install", dockerfile)
        self.assertIn("--platform=linux/amd64", (DEVCONTAINER / "devcontainer.json").read_text(encoding="utf-8"))

    def test_installer_reuses_git_package_helper_links_into_active_exec_path_and_locks_it(self):
        with tempfile.TemporaryDirectory() as temp:
            fx = self._fixture(Path(temp))
            result = self._run(INSTALL, fx["env"], fx["root"])
            self.assertEqual(result.returncode, 0, result.stdout)

            target = fx["active_exec"] / "git-subtree"
            self.assertTrue(target.is_symlink())
            self.assertEqual(target.resolve(), fx["helper"].resolve())
            self.assertIn("git subtree verified", result.stdout)

            lock_path = fx["state"] / "toolchain-lock.tsv"
            lock = lock_path.read_text(encoding="utf-8")
            self.assertIn("# format=devcontainer-apt-lock-v3", lock)
            self.assertIn(f"# snapshot={SNAPSHOT}", lock)
            self.assertIn(hashlib.sha256(fx["sources"].read_bytes()).hexdigest(), lock)
            self.assertIn("# architecture=amd64", lock)
            self.assertIn("# apt-version=apt 2.6.1 (amd64)", lock)
            self.assertIn("# dpkg-version=1.21.22", lock)
            self.assertIn(f"# base-image-ref={BASE_IMAGE}", lock)
            self.assertIn("# build-platform=linux/amd64", lock)
            self.assertIn("# subtree-package=git", lock)
            self.assertIn(f"# subtree-package-version={GIT_VERSION}", lock)
            self.assertIn(f"# subtree-source-sha256={hashlib.sha256(fx['helper'].read_bytes()).hexdigest()}", lock)
            self.assertIn("# git-exec-path=", lock)
            self.assertIn(f"# subtree-target={target}", lock)
            self.assertIn(f"git\t{GIT_VERSION}", lock)

            apt_commands = fx["apt_log"].read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(apt_commands), 2)
            self.assertTrue(any(command.endswith("update") for command in apt_commands))
            self.assertTrue(any("--version" in command for command in apt_commands))
            self.assertFalse(any("install" in command for command in apt_commands))
            self.assertFalse(any("git-subtree" in command for command in apt_commands))
            self.assertFalse(any("install" in command for command in apt_commands))

    def test_runtime_verifier_accepts_locked_helper_and_detects_package_helper_and_source_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            fx = self._fixture(Path(temp))
            installed = self._run(INSTALL, fx["env"], fx["root"])
            self.assertEqual(installed.returncode, 0, installed.stdout)

            passed = self._run(VERIFY, fx["env"], fx["root"])
            self.assertEqual(passed.returncode, 0, passed.stdout)
            self.assertIn("Base-image package versions verified: 1", passed.stdout)

            changed_version_env = fx["env"].copy()
            changed_version_env["FAKE_GIT_PACKAGE_VERSION"] = "1:2.39.5-0+deb12u4"
            drift = self._run(VERIFY, changed_version_env, fx["root"])
            self.assertNotEqual(drift.returncode, 0)
            self.assertIn("Git package version drift", drift.stdout)

            changed_helper = fx["helper"].read_text(encoding="utf-8") + "# changed\n"
            fx["helper"].write_text(changed_helper, encoding="utf-8")
            tampered = self._run(VERIFY, fx["env"], fx["root"])
            self.assertNotEqual(tampered.returncode, 0)
            self.assertIn("packaged git-subtree helper changed", tampered.stdout)

    def test_installer_is_idempotent_when_helper_is_already_linked(self):
        with tempfile.TemporaryDirectory() as temp:
            fx = self._fixture(Path(temp))
            first = self._run(INSTALL, fx["env"], fx["root"])
            self.assertEqual(first.returncode, 0, first.stdout)
            target = fx["active_exec"] / "git-subtree"
            first_target = target.resolve()

            second = self._run(INSTALL, fx["env"], fx["root"])
            self.assertEqual(second.returncode, 0, second.stdout)
            self.assertTrue(target.is_symlink())
            self.assertEqual(target.resolve(), first_target)
            self.assertIn("git subtree verified", second.stdout)

    def test_installer_rejects_helper_not_owned_by_debian_git_package(self):
        with tempfile.TemporaryDirectory() as temp:
            fx = self._fixture(Path(temp))
            env = fx["env"].copy()
            env["FAKE_DPKG_OWNER"] = "git-extra"
            result = self._run(INSTALL, env, fx["root"])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("owned by Debian package 'git'", result.stdout)

    def test_installer_rejects_global_git_exec_path_override(self):
        with tempfile.TemporaryDirectory() as temp:
            fx = self._fixture(Path(temp))
            env = fx["env"].copy()
            env["GIT_EXEC_PATH"] = str(fx["root"] / "manual-override")
            result = self._run(INSTALL, env, fx["root"])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("GIT_EXEC_PATH must remain unset", result.stdout)

    def test_installer_fails_closed_if_debian_git_helper_is_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            fx = self._fixture(Path(temp))
            fx["helper"].unlink()
            result = self._run(INSTALL, fx["env"], fx["root"])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("helper is absent", result.stdout)
            commands = fx["apt_log"].read_text(encoding="utf-8").splitlines()
            self.assertFalse(any("install" in command for command in commands))

    def test_installer_uses_isolated_fallback_path_when_explicitly_configured(self):
        with tempfile.TemporaryDirectory() as temp:
            fx = self._fixture(Path(temp))
            package_helper = fx["root"] / "debian-git-package" / "git-subtree"
            package_helper.parent.mkdir()
            fx["helper"].rename(package_helper)
            env = fx["env"].copy()
            env["GIT_SUBTREE_FALLBACK_PATHS"] = str(package_helper)

            result = self._run(INSTALL, env, fx["root"])
            self.assertEqual(result.returncode, 0, result.stdout)
            target = fx["active_exec"] / "git-subtree"
            self.assertTrue(target.is_symlink())
            self.assertEqual(target.resolve(), package_helper.resolve())

    def test_verifier_rejects_unexpected_additional_apt_source_file(self):
        with tempfile.TemporaryDirectory() as temp:
            fx = self._fixture(Path(temp))
            installed = self._run(INSTALL, fx["env"], fx["root"])
            self.assertEqual(installed.returncode, 0, installed.stdout)
            (fx["sources"].parent / "live-debian.sources").write_text(
                "Types: deb\nURIs: https://deb.debian.org/debian\nSuites: bookworm\nComponents: main\n",
                encoding="utf-8",
            )
            live = self._run(VERIFY, fx["env"], fx["root"])
            self.assertNotEqual(live.returncode, 0)
            self.assertIn("Unexpected APT source file exists outside the locked snapshot", live.stdout)

    def test_verifier_rejects_mutable_debian_mirror_even_if_lock_hash_is_updated(self):
        with tempfile.TemporaryDirectory() as temp:
            fx = self._fixture(Path(temp))
            installed = self._run(INSTALL, fx["env"], fx["root"])
            self.assertEqual(installed.returncode, 0, installed.stdout)

            sources = fx["sources"].read_text(encoding="utf-8")
            frozen_uri = f"https://snapshot.debian.org/archive/debian/{SNAPSHOT}/"
            self.assertIn(frozen_uri, sources)
            sources = sources.replace(frozen_uri, "https://deb.debian.org/debian/", 1)
            fx["sources"].write_text(sources, encoding="utf-8")

            # Recompute the lock checksum to prove the verifier also enforces
            # the immutable snapshot URI, not just byte-for-byte lock integrity.
            lock_path = fx["state"] / "toolchain-lock.tsv"
            lock = lock_path.read_text(encoding="utf-8")
            new_digest = hashlib.sha256(fx["sources"].read_bytes()).hexdigest()
            lock, replacements = re.subn(
                r"(?m)^# source-sha256=.*$",
                f"# source-sha256={new_digest}",
                lock,
                count=1,
            )
            self.assertEqual(replacements, 1)
            lock_path.write_text(lock, encoding="utf-8")

            live = self._run(VERIFY, fx["env"], fx["root"])
            self.assertNotEqual(live.returncode, 0)
            self.assertIn("Bookworm APT source no longer points to the locked snapshot", live.stdout)


if __name__ == "__main__":
    unittest.main()
