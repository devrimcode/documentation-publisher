from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_engine import NoDuplicateKeyLoader
from publisher_engine.workflow import generate_github_actions_workflow


class WorkflowDeployJobOutputTests(unittest.TestCase):
    def _generated(self, *, dry_run: bool = False):
        sha = "b" * 40
        config = {
            "workflow": {
                "provider": "github_actions",
                "actions": {
                    "checkout": f"actions/checkout@{sha}",
                    "setup_python": f"actions/setup-python@{sha}",
                    "upload_pages_artifact": f"actions/upload-pages-artifact@{sha}",
                    "deploy_pages": f"actions/deploy-pages@{sha}",
                },
            },
            "triggers": {"manual": True},
            "publisher": {"ref": "main"},
            "site": {"output_directory": "_site"},
            "publishing": {"artifact_name": "site", "retention_days": 1, "dry_run": dry_run},
        }
        rendered = generate_github_actions_workflow(config)
        parsed = yaml.load(rendered, Loader=NoDuplicateKeyLoader)
        return rendered, parsed

    def test_build_job_exports_decision_step_output(self):
        _, workflow = self._generated()
        build = workflow["jobs"]["build"]
        self.assertEqual(
            build.get("outputs", {}).get("deploy"),
            "${{ steps.decision.outputs.deploy }}",
        )

    def test_deploy_job_consumes_exported_build_job_output(self):
        _, workflow = self._generated()
        build = workflow["jobs"]["build"]
        deploy = workflow["jobs"]["deploy"]
        self.assertIn("decision", {step.get("id") for step in build["steps"]})
        self.assertEqual(
            deploy.get("if"),
            "needs.build.outputs.deploy == 'true'",
        )
        self.assertIn("deploy", build.get("outputs", {}))

    def test_dry_run_has_no_deploy_job_or_job_output(self):
        _, workflow = self._generated(dry_run=True)
        build = workflow["jobs"]["build"]
        self.assertNotIn("deploy", workflow["jobs"])
        self.assertNotIn("deploy", build.get("outputs", {}))
        self.assertFalse(any(step.get("id") == "decision" for step in build["steps"]))

    def test_export_references_the_unique_decision_step(self):
        rendered, workflow = self._generated()
        build = workflow["jobs"]["build"]
        decisions = [step for step in build["steps"] if step.get("id") == "decision"]
        self.assertEqual(len(decisions), 1)
        self.assertEqual(
            build["outputs"]["deploy"],
            "${{ steps.decision.outputs.deploy }}",
        )
        self.assertIn("echo 'deploy=true'", decisions[0]["run"])
        self.assertIn("echo 'deploy=false'", decisions[0]["run"])
        self.assertIn("if: steps.decision.outputs.deploy == 'true'", rendered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
