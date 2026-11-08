from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from publisher_engine.engine import BuildError, resolve_build_plan
from publisher_engine.cli import main as cli_main


def sample_config():
    return {
        "project": {"id": "plan-fixture"},
        "sources": [
            {"id": "source-a", "integration": {"mode": "git_subtree", "prefix": "subtrees/a"}, "vcs": {"default_ref": "main"}},
            {"id": "source-b", "integration": {"mode": "git_subtree", "prefix": "subtrees/b"}, "vcs": {"default_ref": "main"}},
            {"id": "unused", "integration": {"mode": "git_subtree", "prefix": "subtrees/unused"}, "vcs": {"default_ref": "main"}},
        ],
        "components": [
            {"id": "guide-a", "source_id": "source-a", "route": "a", "tasks": ["build-a"]},
            {"id": "guide-b", "source_id": "source-b", "route": "b", "dependencies": ["guide-a"], "tasks": ["build-b"]},
        ],
        "build_tasks": [
            {"id": "prepare-a", "source_id": "source-a", "depends_on": []},
            {"id": "build-a", "source_id": "source-a", "depends_on": ["prepare-a"]},
            {"id": "prepare-b", "source_id": "source-b", "depends_on": []},
            {"id": "build-b", "source_id": "source-b", "depends_on": ["prepare-b", "build-a"]},
        ],
    }


class SharedBuildPlanTests(unittest.TestCase):
    def test_plan_resolves_component_dependencies_and_transitive_task_dependencies(self):
        plan = resolve_build_plan(sample_config(), ["guide-b"])
        self.assertEqual(plan["chosen_ids"], ["guide-a", "guide-b"])
        self.assertEqual([task["id"] for task in plan["tasks"]], ["prepare-a", "build-a", "prepare-b", "build-b"])
        self.assertEqual(plan["task_source_ids"], {
            "prepare-a": "source-a", "build-a": "source-a", "prepare-b": "source-b", "build-b": "source-b",
        })
        self.assertEqual([source["id"] for source in plan["sources"]], ["source-a", "source-b"])

    def test_plan_excludes_unselected_sources_and_tasks(self):
        plan = resolve_build_plan(sample_config(), ["guide-a"])
        self.assertEqual(plan["chosen_ids"], ["guide-a"])
        self.assertEqual([task["id"] for task in plan["tasks"]], ["prepare-a", "build-a"])
        self.assertEqual([source["id"] for source in plan["sources"]], ["source-a"])

    def test_plan_rejects_unknown_component_and_ambiguous_task_source(self):
        with self.assertRaisesRegex(BuildError, "Unknown component"):
            resolve_build_plan(sample_config(), ["missing"])
        cfg = sample_config()
        cfg["build_tasks"].append({"id": "ambiguous", "depends_on": []})
        cfg["components"][1]["tasks"].append("ambiguous")
        with self.assertRaisesRegex(BuildError, "ambiguous"):
            resolve_build_plan(cfg, ["guide-b"])

    def test_cli_plan_uses_same_resolver_and_reports_only_required_sources(self):
        cfg = sample_config()
        output = io.StringIO()
        with patch("publisher_engine.cli.load_config", return_value=cfg), contextlib.redirect_stdout(output):
            exit_code = cli_main(["plan", "--config", "publisher.yml", "--components", "guide-b"])
        self.assertEqual(exit_code, 0)
        document = json.loads(output.getvalue())
        self.assertEqual(document["selection"], ["guide-a", "guide-b"])
        self.assertEqual([source["id"] for source in document["sources"]], ["source-a", "source-b"])
        self.assertEqual([task["id"] for task in document["tasks"]], ["prepare-a", "build-a", "prepare-b", "build-b"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
