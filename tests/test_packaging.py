from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv
import zipfile
from importlib.util import find_spec
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PythonPackagingTests(unittest.TestCase):
    def test_wheel_contains_schema_template_capabilities_and_console_entrypoint(self):
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            wheel_dir = temp / "wheel"
            wheel_dir.mkdir()
            built = subprocess.run(
                [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
                 "--wheel-dir", str(wheel_dir), str(ROOT)],
                text=True, capture_output=True, timeout=90,
            )
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            wheels = list(wheel_dir.glob("documentation_publisher-*.whl"))
            self.assertEqual(len(wheels), 1)
            with zipfile.ZipFile(wheels[0]) as archive:
                names = set(archive.namelist())
                self.assertIn("publisher_engine/data/publisher.schema.json", names)
                self.assertIn("publisher_engine/data/publisher.example.yml", names)
                self.assertIn("publisher_engine/data/provider-capabilities.json", names)
                entry_points = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
                content = archive.read(entry_points).decode("utf-8")
                self.assertIn("documentation-publisher = publisher_engine.cli:main", content)
                metadata_path = next(name for name in names if name.endswith(".dist-info/METADATA"))
                metadata = archive.read(metadata_path).decode("utf-8")
                self.assertIn("Requires-Python: >=3.11", metadata)
                self.assertIn("Requires-Dist: PyYAML", metadata)
                self.assertIn("Requires-Dist: jsonschema", metadata)

            environment = temp / "venv"
            venv.EnvBuilder(with_pip=True).create(environment)
            scripts_dir = environment / ("Scripts" if os.name == "nt" else "bin")
            python = scripts_dir / ("python.exe" if os.name == "nt" else "python")
            console = scripts_dir / ("documentation-publisher.exe" if os.name == "nt" else "documentation-publisher")
            installed = subprocess.run(
                [str(python), "-m", "pip", "install", "--no-deps", str(wheels[0])],
                text=True, capture_output=True, timeout=60,
            )
            self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
            self.assertTrue(console.is_file(), f"console script missing: {console}")
            # Stage only runtime dependency packages from the active test interpreter.
            # This keeps the wheel installation isolated from any editable
            # documentation-publisher install or .pth import hook in the test runner.
            dependency_root = temp / "runtime-dependencies"
            dependency_root.mkdir()
            for module_name in ("yaml", "jsonschema", "jsonschema_specifications", "referencing", "rpds", "attrs", "attr"):
                spec = find_spec(module_name)
                self.assertIsNotNone(spec, f"test environment is missing runtime dependency {module_name}")
                if spec.submodule_search_locations:
                    shutil.copytree(Path(next(iter(spec.submodule_search_locations))), dependency_root / module_name)
                elif spec.origin and spec.origin not in {"built-in", "frozen"}:
                    shutil.copy2(spec.origin, dependency_root / Path(spec.origin).name)
            env = os.environ.copy()
            env["PYTHONPATH"] = str(dependency_root)
            executed = subprocess.run([str(console), "--version"], text=True, capture_output=True,
                                      cwd=temp, env=env, timeout=15)
            self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)
            self.assertIn("2.0.15-dev", executed.stdout)
            created = temp / "installed-wheel-config.yml"
            init_result = subprocess.run(
                [str(console), "init-config", "--output", str(created)],
                text=True, capture_output=True, cwd=temp, env=env, timeout=15,
            )
            self.assertEqual(init_result.returncode, 0, init_result.stdout + init_result.stderr)
            self.assertIn("<PUBLISHER_GIT_CLONE_URL>", created.read_text(encoding="utf-8"))
            capability_result = subprocess.run(
                [str(console), "capabilities"], text=True, capture_output=True, cwd=temp, env=env, timeout=15,
            )
            self.assertEqual(capability_result.returncode, 0, capability_result.stdout + capability_result.stderr)
            self.assertIn('"github_actions"', capability_result.stdout)
            smoke_config = temp / "publisher.keycloak.smoke.yml"
            smoke_config.write_bytes((ROOT / "publisher.keycloak.smoke.yml").read_bytes())
            validated = subprocess.run(
                [str(console), "validate-config", "--config", str(smoke_config)],
                text=True, capture_output=True, cwd=temp, env=env, timeout=20,
            )
            self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)
            self.assertIn("Configuration valid:", validated.stdout)

            unpacked = temp / "unpacked"
            unpacked.mkdir()
            with zipfile.ZipFile(wheels[0]) as archive:
                archive.extractall(unpacked)
            env = os.environ.copy()
            env["PYTHONPATH"] = str(unpacked)
            version = subprocess.run(
                [sys.executable, "-m", "publisher_engine.cli", "--version"],
                cwd=temp, env=env, text=True, capture_output=True, timeout=15,
            )
            self.assertEqual(version.returncode, 0, version.stdout + version.stderr)
            self.assertIn("2.0.15-dev", version.stdout)
            output = temp / "installed-template.yml"
            initialized = subprocess.run(
                [sys.executable, "-m", "publisher_engine.cli", "init-config", "--output", str(output)],
                cwd=temp, env=env, text=True, capture_output=True, timeout=15,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stdout + initialized.stderr)
            self.assertTrue(output.is_file())
            self.assertIn("<PUBLISHER_GIT_CLONE_URL>", output.read_text(encoding="utf-8"))
            capabilities = subprocess.run(
                [sys.executable, "-m", "publisher_engine.cli", "capabilities"],
                cwd=temp, env=env, text=True, capture_output=True, timeout=15,
            )
            self.assertEqual(capabilities.returncode, 0, capabilities.stdout + capabilities.stderr)
            self.assertIn('"github_actions"', capabilities.stdout)

    def test_repository_schema_and_packaged_schema_are_identical(self):
        source = (ROOT / "schemas" / "publisher.schema.json").read_bytes()
        packaged = (ROOT / "publisher_engine" / "data" / "publisher.schema.json").read_bytes()
        self.assertEqual(source, packaged)

    def test_repository_template_and_packaged_template_are_identical(self):
        source = (ROOT / "publisher.example.yml").read_bytes()
        packaged = (ROOT / "publisher_engine" / "data" / "publisher.example.yml").read_bytes()
        self.assertEqual(source, packaged)


if __name__ == "__main__":
    unittest.main()
