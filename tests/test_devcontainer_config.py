from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
DEVCONTAINER = ROOT / ".devcontainer"


class ActiveDevContainerConfigTests(unittest.TestCase):
    def test_active_codespaces_configuration_exists_at_discovery_path(self) -> None:
        config_path = DEVCONTAINER / "devcontainer.json"
        self.assertTrue(config_path.is_file(), "Codespaces requires .devcontainer/devcontainer.json")
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["build"]["dockerfile"], "Dockerfile")
        self.assertEqual(config["build"]["context"], "..")
        self.assertEqual(config["build"]["options"], ["--platform=linux/amd64"])
        self.assertTrue((DEVCONTAINER / "Dockerfile").is_file())

    def test_environment_features_cover_publisher_and_keycloak_build(self) -> None:
        config = json.loads((DEVCONTAINER / "devcontainer.json").read_text(encoding="utf-8"))
        features = config["features"]
        self.assertIn("ghcr.io/devcontainers/features/git-lfs:1.2.5", features)
        self.assertIn("ghcr.io/devcontainers/features/java:1.8.3", features)
        java = features["ghcr.io/devcontainers/features/java:1.8.3"]
        lfs = features["ghcr.io/devcontainers/features/git-lfs:1.2.5"]
        self.assertEqual(java["version"], "25")
        self.assertEqual(java["additionalVersions"], "21")
        self.assertEqual(java["jdkDistro"], "tem")
        self.assertTrue(java["installMaven"])
        self.assertEqual(java["mavenVersion"], "3.10.0")
        self.assertEqual(lfs["version"], "3.8.1")
        self.assertFalse(lfs["autoPull"])
        self.assertEqual(config["containerEnv"]["MAVEN_ARGS"], "-B -nsu -Daether.connector.http.connectionMaxTtl=25 -Daether.connector.http.retryHandler.count=5 -Daether.connector.http.retryHandler.serviceUnavailable=429,502,503,504")

    def test_installer_reuses_debian_git_package_helper_without_fake_apt_package(self) -> None:
        installer = (DEVCONTAINER / "install-apt-snapshot.sh").read_text(encoding="utf-8")
        dockerfile = (DEVCONTAINER / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("/usr/lib/git-core/git-subtree", installer)
        self.assertIn("dpkg-query", installer)
        self.assertIn("OWNER_PACKAGE=\"${OWNER_LABEL%%:*}\"", installer)
        self.assertIn("[[ \"$OWNER_PACKAGE\" == \"git\" ]]", installer)
        self.assertIn('GIT_EXEC_PATH=\"$(\"$GIT_BIN\" --exec-path)\"', installer)
        self.assertIn('ln -s \"$SUBTREE_SOURCE\" \"$SUBTREE_TARGET\"', installer)
        self.assertIn('\"$GIT_BIN\" subtree -h', installer)
        self.assertNotIn("apt-get install", installer)
        self.assertNotIn("apt-get install git-subtree", dockerfile)

    def test_dockerfile_uses_the_expected_digest_pinned_base_and_cleans_apt_metadata(self) -> None:
        dockerfile = (DEVCONTAINER / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn(
            "FROM mcr.microsoft.com/devcontainers/python:3.13-bookworm@sha256:"
            "ac334d90ca71f23b58820c90a440b400d175b77d642d312cf67ff0cc9cb2056d",
            dockerfile,
        )
        self.assertIn("bash /usr/local/sbin/install-apt-snapshot.sh", dockerfile)
        installer = (DEVCONTAINER / "install-apt-snapshot.sh").read_text(encoding="utf-8")
        self.assertIn('"$APT_GET_BIN" -o Acquire::Retries=5 -o Acquire::https::Timeout=30 update', installer)
        self.assertIn("rm -rf /var/lib/apt/lists/*", dockerfile)
        self.assertIn("ARG DEBIAN_SNAPSHOT=20261107T000000Z", dockerfile)

    def test_ci_workflow_declares_the_supported_python_compatibility_matrix(self) -> None:
        import yaml

        workflow_path = ROOT / ".github" / "workflows" / "python-compatibility.yml"
        self.assertTrue(workflow_path.is_file())
        workflow = yaml.load(workflow_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertEqual(
            workflow["jobs"]["test"]["strategy"]["matrix"]["python-version"],
            ["3.11", "3.12", "3.13"],
        )
        steps = workflow["jobs"]["test"]["steps"]
        actions = [step.get("uses", "") for step in steps]
        self.assertIn("actions/checkout@v7", actions)
        self.assertIn("actions/setup-python@v7", actions)
        run_text = "\n".join(step.get("run", "") for step in steps)
        self.assertIn("tests/test_p6_p7_manifest_cleanup.py", run_text)
        self.assertIn("tests/test_packaging.py", run_text)
        self.assertIn("tests/test_process.py", run_text)
        self.assertIn("--ignore=tests/test_process.py", run_text)

    def test_repository_upload_does_not_depend_on_a_local_feature_installer(self) -> None:
        self.assertFalse((DEVCONTAINER / "features").exists())
        config = json.loads((DEVCONTAINER / "devcontainer.json").read_text(encoding="utf-8"))
        self.assertEqual(set(config["features"]), {
            "ghcr.io/devcontainers/features/java:1.8.3",
            "ghcr.io/devcontainers/features/git-lfs:1.2.5",
        })

    def test_environment_verifier_requires_exact_declared_python_java_maven_and_lfs_versions(self) -> None:
        verifier = (DEVCONTAINER / "verify-environment.sh").read_text(encoding="utf-8")
        self.assertIn('PYTHON_LINE="$(python3 --version 2>&1)"', verifier)
        self.assertIn("Java 25 must be the active default JDK", verifier)
        self.assertIn('candidates/java/21*', verifier)
        self.assertIn('CANDIDATE_LINE', verifier)
        self.assertIn('git-lfs/3.8.1*', verifier)
        self.assertIn('Apache Maven 3.10.0', verifier)
        self.assertNotIn("Python 3.11+ required", verifier)

    def test_lifecycle_commands_and_setup_scripts_exist(self) -> None:
        config = json.loads((DEVCONTAINER / "devcontainer.json").read_text(encoding="utf-8"))
        self.assertEqual(config["postCreateCommand"], "bash .devcontainer/post-create.sh")
        self.assertEqual(
            config["postStartCommand"],
            "bash .devcontainer/ensure-python-environment.sh --quiet && bash .devcontainer/verify-environment.sh --quiet",
        )
        self.assertEqual(config["customizations"]["vscode"]["settings"]["terminal.integrated.cwd"], "${workspaceFolder}")
        self.assertEqual(config["waitFor"], "postCreateCommand")
        for name in ("post-create.sh", "ensure-python-environment.sh", "verify-environment.sh", "install-apt-snapshot.sh", "verify-apt-state.sh"):
            script = DEVCONTAINER / name
            self.assertTrue(script.is_file())
            self.assertTrue(script.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash"))

    def test_bootstrap_installs_dependencies_and_post_start_rechecks_new_source_files(self) -> None:
        bootstrap = (DEVCONTAINER / "ensure-python-environment.sh").read_text(encoding="utf-8")
        post_create = (DEVCONTAINER / "post-create.sh").read_text(encoding="utf-8")
        config = json.loads((DEVCONTAINER / "devcontainer.json").read_text(encoding="utf-8"))
        self.assertIn("pip install -e '.[dev]'", bootstrap)
        self.assertIn('requirements-dev.txt', bootstrap)
        self.assertIn('DEPENDENCY_FINGERPRINT', bootstrap)
        self.assertIn('bash .devcontainer/ensure-python-environment.sh', post_create)
        self.assertIn('bash .devcontainer/verify-environment.sh', post_create)
        self.assertIn('ensure-python-environment.sh --quiet', config['postStartCommand'])
        self.assertIn('documentation-publisher .venv auto-activation', bootstrap)

    def test_codespaces_test_script_runs_regression_groups_separately(self) -> None:
        script = (ROOT / "scripts" / "test-in-codespaces.sh").read_text(encoding="utf-8")
        self.assertIn('"$PYTHON" scripts/codespaces_acceptance.py', script)
        self.assertIn(
            '"$PYTHON" -m pytest -q --ignore=tests/test_process.py '
            '--ignore=tests/test_packaging.py --ignore=tests/test_p6_p7_manifest_cleanup.py',
            script,
        )
        self.assertIn('"$PYTHON" -m pytest -q tests/test_p6_p7_manifest_cleanup.py', script)
        self.assertIn('"$PYTHON" -m pytest -q tests/test_packaging.py', script)
        self.assertIn('"$PYTHON" -Werror::ResourceWarning -m pytest -q tests/test_process.py', script)
        self.assertIn('>"$MAIN_LOG" 2>&1', script)
        self.assertIn('>"$MANIFEST_LOG" 2>&1', script)
        self.assertIn('>"$PACKAGING_LOG" 2>&1', script)
        self.assertIn('>"$PROCESS_LOG" 2>&1', script)
        self.assertEqual(script.count("-m pytest"), 4)

    def test_codespaces_acceptance_checks_exact_pinned_versions_and_example_semantics(self) -> None:
        script = (ROOT / "scripts" / "codespaces_acceptance.py").read_text(encoding="utf-8")
        self.assertIn("sys.version_info[:2] != (3, 13)", script)
        self.assertIn('expected_venv = (ROOT / ".venv").resolve()', script)
        self.assertIn('active_prefix == expected_venv', script)
        self.assertIn("git-lfs/3.8.1", script)
        self.assertIn("Apache Maven 3.10.0", script)
        self.assertIn('version\\s+"25', script)
        self.assertIn('version\\s+"21', script)
        self.assertIn("publisher.example.yml", script)
        self.assertIn("publisher.keycloak.smoke.yml", script)

    def test_codespaces_acceptance_checks_the_apt_snapshot_and_package_lock(self) -> None:
        script = (ROOT / "scripts" / "codespaces_acceptance.py").read_text(encoding="utf-8")
        self.assertIn('"APT snapshot and Git Subtree base-image lock"', script)
        self.assertIn('".devcontainer/verify-apt-state.sh"', script)
        post_create = (DEVCONTAINER / "post-create.sh").read_text(encoding="utf-8")
        self.assertIn("devcontainer-toolchain-lock.tsv", post_create)
        self.assertIn("devcontainer-toolchain-lock.tsv.SHA256", post_create)

    def test_root_gitignore_covers_generated_runtime_and_test_files(self) -> None:
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in ("__pycache__/", "*.py[cod]", ".pytest_cache/", ".venv/", "test-results/", "_site/", ".publisher-tmp/", ".publisher-sources/"):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, ignore)

    def test_active_configuration_is_not_left_as_example_only(self) -> None:
        self.assertFalse((DEVCONTAINER / "devcontainer.json.example").exists())


if __name__ == "__main__":
    unittest.main()
