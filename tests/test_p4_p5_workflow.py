from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_engine import NoDuplicateKeyLoader
from publisher_engine.workflow import WorkflowError, generate_github_actions_workflow


class WorkflowEnvironmentAndPathFiltersTests(unittest.TestCase):
    def _config(self, *, triggers=None, environment=None):
        sha = "c" * 40
        return {
            "workflow": {
                "provider": "github_actions",
                "actions": {
                    "checkout": f"actions/checkout@{sha}",
                    "setup_python": f"actions/setup-python@{sha}",
                    "upload_pages_artifact": f"actions/upload-pages-artifact@{sha}",
                    "deploy_pages": f"actions/deploy-pages@{sha}",
                },
                "environment": environment or {},
            },
            "triggers": triggers if triggers is not None else {"manual": True},
            "publisher": {"ref": "main"},
            "site": {"output_directory": "_site"},
            "publishing": {"artifact_name": "site", "retention_days": 1, "dry_run": False},
        }

    def _parse(self, **kwargs):
        rendered = generate_github_actions_workflow(self._config(**kwargs))
        return rendered, yaml.load(rendered, Loader=NoDuplicateKeyLoader)

    def test_p4_environment_is_available_to_validate_and_build_steps(self):
        _, workflow = self._parse(environment={"DOCS_CHANNEL": "preview", "FEATURE_FLAG": "enabled"})
        steps = workflow["jobs"]["build"]["steps"]
        validate = next(step for step in steps if step.get("name") == "Validate configuration")
        build = next(step for step in steps if step.get("name") == "Build and validate site")
        self.assertEqual(validate["env"]["DOCS_CHANNEL"], "preview")
        self.assertEqual(validate["env"]["FEATURE_FLAG"], "enabled")
        self.assertEqual(build["env"]["DOCS_CHANNEL"], "preview")
        self.assertEqual(build["env"]["FEATURE_FLAG"], "enabled")

    def test_p4_repository_secret_is_exported_after_validation_not_into_validate_env(self):
        config = self._config(environment={"DOCS_CHANNEL": "preview"})
        config["publisher"]["auth"] = {"mode": "https_token", "secret_env": "DOCS_TOKEN"}
        config["workflow"]["secrets"] = {"DOCS_TOKEN": "GH_DOCS_TOKEN"}
        rendered = generate_github_actions_workflow(config)
        workflow = yaml.load(rendered, Loader=NoDuplicateKeyLoader)
        steps = workflow["jobs"]["build"]["steps"]
        validate = next(step for step in steps if step.get("name") == "Validate configuration")
        build = next(step for step in steps if step.get("name") == "Build and validate site")
        export = next(step for step in steps if step.get("name") == "Export configured credential DOCS_TOKEN")
        self.assertNotIn("DOCS_TOKEN", validate["env"])
        self.assertNotIn("PUBLISHER_SECRET_VALUE", validate["env"])
        self.assertNotIn("GH_DOCS_TOKEN", rendered.split("- name: Validate configuration", 1)[1].split("- name: Export configured credential", 1)[0])
        self.assertIn("secrets.GH_DOCS_TOKEN", export["env"]["PUBLISHER_SECRET_VALUE"])
        self.assertIn("DOCS_CHANNEL", build["env"])

    def test_p4_reserved_environment_variable_is_rejected(self):
        with self.assertRaisesRegex(WorkflowError, "reserved runner variable"):
            self._parse(environment={"GITHUB_TOKEN": "not-allowed"})

    def test_p5_paths_apply_to_both_push_and_pull_request(self):
        _, workflow = self._parse(triggers={
            "push_branches": ["main"], "pull_request": True,
            "paths": ["docs/**", "!docs/private/**", "publisher.yml"],
        })
        events = workflow.get("on", workflow.get(True))
        self.assertEqual(events["push"]["branches"], ["main"])
        self.assertEqual(events["push"]["paths"], ["docs/**", "!docs/private/**", "publisher.yml"])
        self.assertEqual(events["pull_request"]["paths"], ["docs/**", "!docs/private/**", "publisher.yml"])

    def test_p5_push_path_filter_is_preserved_when_no_pull_request(self):
        _, workflow = self._parse(triggers={"push_branches": ["main"], "paths": ["docs/**"]})
        events = workflow.get("on", workflow.get(True))
        self.assertEqual(events["push"]["paths"], ["docs/**"])
        self.assertNotIn("pull_request", events)

    def test_p5_pull_request_path_filter_works_without_push(self):
        _, workflow = self._parse(triggers={"pull_request": True, "paths": ["docs/**"]})
        events = workflow.get("on", workflow.get(True))
        self.assertEqual(events["pull_request"]["paths"], ["docs/**"])
        self.assertNotIn("push", events)

    def test_p5_empty_paths_are_omitted(self):
        _, workflow = self._parse(triggers={"push_branches": ["main"], "pull_request": True, "paths": []})
        events = workflow.get("on", workflow.get(True))
        self.assertNotIn("paths", events["push"])
        self.assertNotIn("paths-ignore", events["push"])
        self.assertNotIn("paths", (events["pull_request"] or {}))
        self.assertNotIn("paths-ignore", (events["pull_request"] or {}))

    def test_p5_only_negative_patterns_become_paths_ignore(self):
        _, workflow = self._parse(triggers={"push_branches": ["main"], "pull_request": True,
                                            "paths": ["!docs/private/**", "!build/**"]})
        events = workflow.get("on", workflow.get(True))
        expected = ["docs/private/**", "build/**"]
        self.assertEqual(events["push"]["paths-ignore"], expected)
        self.assertEqual(events["pull_request"]["paths-ignore"], expected)
        self.assertNotIn("paths", events["push"])

    def test_p5_paths_without_path_aware_trigger_are_rejected(self):
        with self.assertRaisesRegex(WorkflowError, "requires at least one"):
            self._parse(triggers={"manual": True, "paths": ["docs/**"]})


if __name__ == "__main__":
    unittest.main(verbosity=2)
