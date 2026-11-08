from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / ".devcontainer" / "ensure-python-environment.sh"


class DevContainerPythonBootstrapTests(unittest.TestCase):
    def make_fixture(self):
        td = tempfile.TemporaryDirectory()
        base = Path(td.name)
        workspace = base / "workspace"
        home = base / "home"
        (workspace / ".devcontainer").mkdir(parents=True)
        (workspace / ".venv" / "bin").mkdir(parents=True)
        home.mkdir()
        shutil.copy2(BOOTSTRAP, workspace / ".devcontainer" / BOOTSTRAP.name)
        subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)

        # Stub the declared Python 3.13 runtime so this lifecycle test also runs
        # in the repository's supported 3.11/3.12 compatibility matrix.
        python3 = base / "python3-3.13"
        python3.write_text(
            "#!/usr/bin/env bash\n"
            "if [[ \"${1:-}\" == --version ]]; then echo 'Python 3.13.5'; exit 0; fi\n"
            "echo 'unexpected python3 invocation' >&2; exit 2\n",
            encoding="utf-8",
        )
        python3.chmod(0o755)

        venv_python = workspace / ".venv" / "bin" / "python"
        venv_python.write_text(
            "#!/usr/bin/env bash\n"
            "VENV_ROOT=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")/..\" && pwd)\"\n"
            "if [[ \"${1:-}\" == --version ]]; then echo 'Python 3.13.5'; exit 0; fi\n"
            "if [[ \"${1:-}\" == -c ]]; then\n"
            "  case \"$*\" in *documentation-publisher*) [[ -f \"$VENV_ROOT/.deps-installed\" ]] && exit 0 || exit 1 ;; *) exit 0 ;; esac\n"
            "fi\n"
            "if [[ \"${1:-}\" == -m && \"${2:-}\" == pip ]]; then\n"
            "  if [[ \"${3:-}\" == install && \"${4:-}\" == -e && \"${5:-}\" == '.[dev]' ]]; then touch \"$VENV_ROOT/.deps-installed\"; fi\n"
            "  exit 0\n"
            "fi\n"
            "if [[ \"${1:-}\" == - || $# == 0 ]]; then cat >/dev/null; exit 0; fi\n"
            "printf 'unexpected venv python invocation: %s\\n' \"$*\" >&2; exit 2\n",
            encoding="utf-8",
        )
        venv_python.chmod(0o755)
        activate = workspace / ".venv" / "bin" / "activate"
        activate.write_text(
            'VIRTUAL_ENV="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"\n'
            'export VIRTUAL_ENV\n'
            'PATH="$VIRTUAL_ENV/bin:$PATH"\n'
            'export PATH\n'
            'unset PYTHONHOME\n',
            encoding="utf-8",
        )

        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PUBLISHER_PYTHON3_BIN"] = str(python3)
        return td, workspace, home, env

    def test_new_interactive_bash_terminal_activates_project_venv(self):
        td, workspace, home, env = self.make_fixture()
        with td:
            result = subprocess.run(
                ["bash", str(workspace / ".devcontainer" / "ensure-python-environment.sh")],
                cwd=workspace,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertTrue((workspace / ".venv" / "bin" / "python").is_file())

            shell = subprocess.run(
                ["bash", "--noprofile", "--rcfile", str(home / ".bashrc"), "-ic", 'printf "%s" "${VIRTUAL_ENV:-}"'],
                cwd=workspace,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=15,
            )
            self.assertEqual(shell.returncode, 0, shell.stdout)
            self.assertIn(str(workspace / ".venv"), shell.stdout)

    def test_activation_hook_is_idempotent_and_rechecks_project_bootstrap(self):
        td, workspace, home, env = self.make_fixture()
        with td:
            script = workspace / ".devcontainer" / "ensure-python-environment.sh"
            for _ in range(2):
                result = subprocess.run(
                    ["bash", str(script), "--quiet"],
                    cwd=workspace,
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=15,
                )
                self.assertEqual(result.returncode, 0, result.stdout)
            bashrc = (home / ".bashrc").read_text(encoding="utf-8")
            self.assertEqual(bashrc.count("documentation-publisher .venv auto-activation"), 2)
            self.assertIn('ensure-python-environment.sh" --quiet', bashrc)

    def test_source_arriving_after_initial_setup_is_installed_before_terminal_activation(self):
        td, workspace, home, env = self.make_fixture()
        with td:
            script = workspace / ".devcontainer" / "ensure-python-environment.sh"
            first = subprocess.run(
                ["bash", str(script), "--quiet"], cwd=workspace, env=env,
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15,
            )
            self.assertEqual(first.returncode, 0, first.stdout)
            self.assertFalse((workspace / ".venv" / ".deps-installed").exists())

            # The Publisher project files arrive after the initial container setup.
            (workspace / "pyproject.toml").write_text(
                "[project]\nname='documentation-publisher'\nversion='2.0.10.dev0'\n", encoding="utf-8"
            )
            shell = subprocess.run(
                ["bash", "--noprofile", "--rcfile", str(home / ".bashrc"), "-ic",
                 'printf "%s" "${VIRTUAL_ENV:-}"'],
                cwd=workspace, env=env, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15,
            )
            self.assertEqual(shell.returncode, 0, shell.stdout)
            self.assertIn(str(workspace / ".venv"), shell.stdout)
            self.assertTrue((workspace / ".venv" / ".deps-installed").is_file())
            self.assertTrue((workspace / ".venv" / ".documentation-publisher-dependency-fingerprint").is_file())


if __name__ == "__main__":
    unittest.main()
