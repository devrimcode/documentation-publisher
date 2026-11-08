from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys

import yaml

from publisher_engine.config import ConfigError, load_config, semantic_validate, validate_schema
from publisher_engine.gitops import GitError, integrate_subtree
from publisher_engine.workflow import WorkflowError, generate_github_actions_workflow, generate_gitlab_ci_workflow
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_engine import NoDuplicateKeyLoader, base_config, init_remote, git


class RepositoryDispatchConfigTests(unittest.TestCase):
    def _config(self, tmp: Path):
        cfg = base_config(tmp, tmp / "publisher.git", tmp / "source.git")
        cfg["sources"][0]["vcs"].update({
            "clone_url": "https://github.com/devrimcode/keycloak.git",
            "web_url": "https://github.com/keycloak/keycloak",
            "default_ref": "main",
            "ref_type": "branch",
            "dispatch_sha_env": "PUBLISHER_KEYCLOAK_SOURCE_SHA",
        })
        cfg["triggers"] = {
            "manual": True,
            "push_branches": ["main"],
            "pull_request": True,
            "deploy_branch": "main",
            "repository_dispatch": {
                "event_type": "keycloak-documentation-updated",
                "source_id": "content",
                "source_repository": "devrimcode/keycloak",
                "source_branch": "main",
            },
        }
        return cfg

    def test_production_config_keeps_build_source_and_three_link_destinations_independent(self):
        project_root = Path(__file__).resolve().parents[1]
        cfg = load_config(project_root / "publisher.yml")
        source = next(item for item in cfg["sources"] if item["id"] == "keycloak")
        self.assertEqual(source["vcs"]["clone_url"], "https://github.com/devrimcode/keycloak.git")
        self.assertEqual(source["vcs"]["web_url"], "https://github.com/keycloak/keycloak")
        edit_target = next(item for item in cfg["authoring_targets"] if item["id"] == cfg["links"]["edit"]["target_id"])
        self.assertEqual(edit_target["repository"], "devrimcode/keycloak")
        self.assertEqual(cfg["links"]["issues"]["target_url"], "https://github.com/keycloak/keycloak")
        self.assertEqual(cfg["links"]["navigation"]["target_url"], "https://github.com/devrimcode/keycloak")
        self.assertEqual(cfg["triggers"]["repository_dispatch"]["source_repository"], "devrimcode/keycloak")
        self.assertEqual(cfg["workflow"]["java_version"], "25")
        self.assertEqual(cfg["workflow"]["actions"]["setup_java"], "actions/setup-java@de7274f081f381c8f8158605e0321c36c376e2e6")
        self.assertIn("-Daether.connector.http.retryHandler.count=5", cfg["workflow"]["environment"]["MAVEN_ARGS"])
        self.assertTrue(cfg["triggers"]["concurrency_group_per_ref"])
        self.assertFalse(cfg["triggers"]["cancel_in_progress"])

    def test_dispatch_config_validates_and_matches_clone_repo_branch(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = self._config(Path(td))
            validate_schema(cfg)
            semantic_validate(cfg)

    def test_dispatch_rejects_repository_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = self._config(Path(td))
            cfg["triggers"]["repository_dispatch"]["source_repository"] = "keycloak/keycloak"
            with self.assertRaisesRegex(ConfigError, "must match the GitHub owner/repository"):
                semantic_validate(cfg)

    def test_dispatch_rejects_branch_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = self._config(Path(td))
            cfg["triggers"]["repository_dispatch"]["source_branch"] = "stable"
            with self.assertRaisesRegex(ConfigError, "must match the selected source"):
                semantic_validate(cfg)

    def test_dispatch_requires_non_reserved_sha_environment(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = self._config(Path(td))
            cfg["sources"][0]["vcs"]["dispatch_sha_env"] = "GITHUB_SHA"
            with self.assertRaisesRegex(ConfigError, "non-reserved uppercase environment"):
                semantic_validate(cfg)


class RepositoryDispatchWorkflowTests(unittest.TestCase):
    def _config(self):
        sha = "a" * 40
        return {
            "workflow": {
                "provider": "github_actions",
                "java_version": "25",
                "environment": {
                    "MAVEN_ARGS": "-B -nsu -Daether.connector.http.retryHandler.count=5",
                },
                "actions": {
                    "checkout": f"actions/checkout@{sha}",
                    "setup_python": f"actions/setup-python@{sha}",
                    "setup_java": f"actions/setup-java@{sha}",
                    "upload_pages_artifact": f"actions/upload-pages-artifact@{sha}",
                    "deploy_pages": f"actions/deploy-pages@{sha}",
                },
            },
            "publisher": {"ref": "main"},
            "sources": [{
                "id": "keycloak",
                "vcs": {
                    "clone_url": "https://github.com/devrimcode/keycloak.git",
                    "default_ref": "main",
                    "dispatch_sha_env": "PUBLISHER_KEYCLOAK_SOURCE_SHA",
                },
            }],
            "triggers": {
                "manual": True,
                "push_branches": ["main"],
                "deploy_branch": "main",
                "concurrency_group": "documentation-publisher",
                "concurrency_group_per_ref": True,
                "cancel_in_progress": False,
                "repository_dispatch": {
                    "event_type": "keycloak-documentation-updated",
                    "source_id": "keycloak",
                    "source_repository": "devrimcode/keycloak",
                    "source_branch": "main",
                },
            },
            "site": {"output_directory": "_site"},
            "publishing": {"artifact_name": "site", "retention_days": 1, "dry_run": False},
        }

    def test_generated_workflow_receives_and_validates_exact_source_dispatch(self):
        rendered = generate_github_actions_workflow(self._config())
        parsed = yaml.load(rendered, Loader=NoDuplicateKeyLoader)
        events = parsed.get("on", parsed.get(True))
        self.assertEqual(events["repository_dispatch"]["types"], ["keycloak-documentation-updated"])
        steps = parsed["jobs"]["build"]["steps"]
        guard = next(step for step in steps if step.get("name") == "Validate source repository dispatch payload")
        self.assertEqual(guard["if"], "github.event_name == 'repository_dispatch'")
        self.assertEqual(guard["env"]["EXPECTED_SOURCE_REPOSITORY"], "devrimcode/keycloak")
        self.assertEqual(guard["env"]["EXPECTED_SOURCE_REF"], "refs/heads/main")
        self.assertIn("github.event.client_payload.sha", guard["env"]["EVENT_SOURCE_SHA"])
        java = next(step for step in steps if step.get("name") == "Set up Java")
        self.assertEqual(java["uses"], f"actions/setup-java@{'a' * 40}")
        self.assertEqual(java["with"]["java-version"], "25")
        build = next(step for step in steps if step.get("name") == "Build and validate site")
        self.assertEqual(build["env"]["PUBLISHER_KEYCLOAK_SOURCE_SHA"], "${{ github.event.client_payload.sha }}")
        self.assertEqual(build["env"]["MAVEN_ARGS"], "-B -nsu -Daether.connector.http.retryHandler.count=5")
        self.assertIn("--components", build["run"])
        freshness = next(step for step in steps if step.get("name") == "Check source revision is current before artifact upload")
        self.assertEqual(freshness["if"], "github.event_name == 'repository_dispatch'")
        self.assertIn("git ls-remote", freshness["run"])
        self.assertIn("current=false", freshness["run"])
        concurrency = parsed["concurrency"]
        self.assertEqual(concurrency["group"], "documentation-publisher-${{ github.ref }}")
        self.assertFalse(concurrency["cancel-in-progress"])
        deploy_steps = parsed["jobs"]["deploy"]["steps"]
        deploy_freshness = next(step for step in deploy_steps if step.get("name") == "Recheck source revision immediately before deployment")
        self.assertIn("git ls-remote", deploy_freshness["run"])
        deploy_action = next(step for step in deploy_steps if step.get("name") == "Deploy validated artifact")
        self.assertEqual(deploy_action["if"], "github.event_name != 'repository_dispatch' || steps.source-freshness.outputs.current == 'true'")
        self.assertIn("if: needs.build.outputs.deploy == 'true'", rendered)


    def test_java_action_and_version_must_be_configured_together(self):
        cfg = self._config()
        del cfg["workflow"]["actions"]["setup_java"]
        with self.assertRaisesRegex(WorkflowError, "requires a pinned.*setup_java"):
            generate_github_actions_workflow(cfg)
        cfg = self._config()
        del cfg["workflow"]["java_version"]
        with self.assertRaisesRegex(WorkflowError, "setup_java requires workflow.java_version"):
            generate_github_actions_workflow(cfg)

    def test_stale_source_check_suppresses_deploy_when_branch_head_has_moved(self):
        rendered = generate_github_actions_workflow(self._config())
        parsed = yaml.load(rendered, Loader=NoDuplicateKeyLoader)
        steps = parsed["jobs"]["build"]["steps"]
        freshness = next(step for step in steps if step.get("name") == "Check source revision is current before artifact upload")
        import tempfile
        from pathlib import Path
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            fake_git = bin_dir / "git"
            new_head = "b" * 40
            fake_git.write_text(f"#!/bin/sh\nprintf '%s\\trefs/heads/main\\n' '{new_head}'\n", encoding="utf-8")
            fake_git.chmod(0o755)
            output = root / "github-output"
            env = {
                **os.environ,
                "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
                "SOURCE_CLONE_URL": "https://github.com/devrimcode/keycloak.git",
                "SOURCE_REF": "refs/heads/main",
                "EVENT_SOURCE_SHA": "a" * 40,
                "GITHUB_OUTPUT": str(output),
            }
            proc = subprocess.run(["bash", "-c", freshness["run"]], env=env, text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=5)
            self.assertEqual(proc.returncode, 0, proc.stdout)
            self.assertEqual(output.read_text(encoding="utf-8").strip(), "current=false")
            self.assertIn("Skipping stale source revision", proc.stdout)

    def test_source_freshness_check_allows_current_head(self):
        rendered = generate_github_actions_workflow(self._config())
        parsed = yaml.load(rendered, Loader=NoDuplicateKeyLoader)
        steps = parsed["jobs"]["build"]["steps"]
        freshness = next(step for step in steps if step.get("name") == "Check source revision is current before artifact upload")
        import tempfile
        from pathlib import Path
        import subprocess
        current_sha = "c" * 40
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            fake_git = bin_dir / "git"
            fake_git.write_text(f"#!/bin/sh\nprintf '%s\\trefs/heads/main\\n' '{current_sha}'\n", encoding="utf-8")
            fake_git.chmod(0o755)
            output = root / "github-output"
            env = {
                **os.environ,
                "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
                "SOURCE_CLONE_URL": "https://github.com/devrimcode/keycloak.git",
                "SOURCE_REF": "refs/heads/main",
                "EVENT_SOURCE_SHA": current_sha,
                "GITHUB_OUTPUT": str(output),
            }
            proc = subprocess.run(["bash", "-c", freshness["run"]], env=env, text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=5)
            self.assertEqual(proc.returncode, 0, proc.stdout)
            self.assertEqual(output.read_text(encoding="utf-8").strip(), "current=true")
            self.assertNotIn("Skipping stale source revision", proc.stdout)

    def test_source_side_workflow_template_has_minimal_permissions_and_dispatch_payload(self):
        template = (Path(__file__).resolve().parents[1] / "integration/source-repository/.github/workflows/notify-documentation-publisher.yml").read_text(encoding="utf-8")
        self.assertIn("branches:\n      - main", template)
        self.assertIn("contents: read", template)
        self.assertIn("secrets.PUBLISHER_DISPATCH_TOKEN", template)
        self.assertIn("keycloak-documentation-updated", template)
        self.assertIn("github.repository", template)
        self.assertIn("github.ref", template)
        self.assertIn("github.sha", template)
        self.assertIn("devrimcode/documentation-publisher/dispatches", template)
        self.assertNotIn("contents: write", template)

    def test_generator_rejects_dispatch_clone_repository_mismatch(self):
        cfg = self._config()
        cfg["triggers"]["repository_dispatch"]["source_repository"] = "keycloak/keycloak"
        with self.assertRaisesRegex(WorkflowError, "must match the selected source clone_url"):
            generate_github_actions_workflow(cfg)

    def test_gitlab_generator_rejects_github_repository_dispatch(self):
        cfg = self._config()
        cfg["workflow"]["provider"] = "gitlab_ci"
        cfg["workflow"]["container_image"] = "registry.example.invalid/docs/python@sha256:" + "a" * 64
        with self.assertRaisesRegex(WorkflowError, "does not support the GitHub repository_dispatch"):
            generate_gitlab_ci_workflow(cfg)


class GitSubtreeDispatchCommitTests(unittest.TestCase):
    def test_subtree_fetches_exact_dispatch_commit_not_newer_branch_head(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            publisher_remote = init_remote(root / "publisher", {"README.md": "publisher\n"})
            source_remote = init_remote(root / "source", {"docs/guide.adoc": "version one\n"})
            source_work = root / "source-work"
            first_sha = git(["rev-parse", "HEAD"], source_work)
            (source_work / "docs/guide.adoc").write_text("version two\n", encoding="utf-8")
            git(["add", "docs/guide.adoc"], source_work)
            git(["commit", "-m", "second source update"], source_work)
            git(["push", "origin", "main"], source_work)
            latest_sha = git(["rev-parse", "HEAD"], source_work)
            self.assertNotEqual(first_sha, latest_sha)

            publisher_clone = root / "publisher-clone"
            subprocess.run(["git", "clone", str(publisher_remote), str(publisher_clone)], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            git(["checkout", "-B", "main", "origin/main"], publisher_clone)
            git(["config", "user.name", "Test Publisher"], publisher_clone)
            git(["config", "user.email", "publisher@example.invalid"], publisher_clone)
            source = {
                "id": "keycloak",
                "vcs": {
                    "clone_url": str(source_remote),
                    "default_ref": "main",
                    "ref_type": "branch",
                    "depth": 1,
                    "lfs": False,
                    "dispatch_sha_env": "PUBLISHER_KEYCLOAK_SOURCE_SHA",
                },
                "integration": {
                    "mode": "git_subtree",
                    "prefix": ".publisher-sources/keycloak",
                    "squash": True,
                    "history": "shallow",
                },
            }
            result = integrate_subtree(
                publisher_clone, source, root, root / "run",
                {**os.environ, "PUBLISHER_KEYCLOAK_SOURCE_SHA": first_sha},
            )
            self.assertEqual(result["source_commit"], first_sha)
            self.assertEqual(
                (publisher_clone / ".publisher-sources/keycloak/docs/guide.adoc").read_text(encoding="utf-8"),
                "version one\n",
            )

    def test_invalid_dispatch_sha_fails_before_fetch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            clone = root / "publisher-clone"
            clone.mkdir()
            source = {
                "id": "keycloak",
                "vcs": {
                    "clone_url": "https://github.com/devrimcode/keycloak.git",
                    "default_ref": "main",
                    "ref_type": "branch",
                    "depth": 1,
                    "dispatch_sha_env": "PUBLISHER_KEYCLOAK_SOURCE_SHA",
                },
                "integration": {"prefix": "subtrees/keycloak", "squash": True, "history": "shallow"},
            }
            with self.assertRaisesRegex(GitError, "Unsafe or empty Git ref"):
                integrate_subtree(
                    clone, source, root, root / "run",
                    {**os.environ, "PUBLISHER_KEYCLOAK_SOURCE_SHA": "main;rm -rf /"},
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
