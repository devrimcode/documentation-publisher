#!/usr/bin/env python3
"""Run a non-mutating acceptance pass in the active Codespaces container."""
from __future__ import annotations

import datetime as dt
import importlib.metadata
import os
import platform
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_dir = ROOT / "test-results"
    report_dir.mkdir(exist_ok=True)
    report_path = report_dir / f"codespaces-acceptance-{timestamp}.log"
    lines: list[str] = []
    failures = 0

    def emit(value: str = "") -> None:
        print(value, flush=True)
        lines.append(value)

    def run_step(label: str, command: list[str], timeout: int = 30,
                 accepted_returncodes: tuple[int, ...] = (0,)) -> tuple[bool, str]:
        nonlocal failures
        emit(f"\n=== {label} ===")
        emit("$ " + " ".join(command))
        try:
            # Use a regular temporary file rather than a PIPE. Some process
            # tests deliberately spawn descendants; an inherited output pipe
            # can keep an outer harness waiting even after pytest has exited.
            with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as output_file:
                proc = subprocess.run(command, cwd=ROOT, text=True,
                                      stdout=output_file, stderr=subprocess.STDOUT,
                                      timeout=timeout, check=False)
                output_file.seek(0)
                output = output_file.read().rstrip()
            if output:
                for line in output.splitlines():
                    emit(line)
            ok = proc.returncode in accepted_returncodes
            emit(f"RESULT: {'PASS' if ok else 'FAIL'} (exit {proc.returncode})")
            if not ok:
                failures += 1
            return ok, output
        except subprocess.TimeoutExpired:
            emit(f"RESULT: FAIL (timeout after {timeout}s; see runner diagnostics above)")
            failures += 1
            return False, ""
        except OSError as exc:
            emit(f"RESULT: FAIL ({type(exc).__name__}: {exc})")
            failures += 1
            return False, str(exc)

    emit("DOCUMENTATION PUBLISHER — CODESPACES ACCEPTANCE")
    emit(f"UTC: {timestamp}")
    emit(f"Project: {ROOT}")
    emit(f"Platform: {platform.platform()}")
    emit(f"Python: {sys.version.replace(os.linesep, ' ')}")
    emit(f"GIT_EXEC_PATH: {os.environ.get('GIT_EXEC_PATH', '<unset>')}")

    if sys.version_info[:2] != (3, 13):
        emit(f"RESULT: FAIL (Codespaces image contract requires Python 3.13 exactly; found {sys.version.split()[0]})")
        failures += 1
    else:
        emit("Python version contract: PASS (3.13)")

    expected_venv = (ROOT / ".venv").resolve()
    active_prefix = Path(sys.prefix).resolve()
    if active_prefix == expected_venv:
        emit(f"Project virtual environment: PASS ({active_prefix})")
    else:
        emit(f"RESULT: FAIL (the active interpreter is not the project .venv; sys.prefix={active_prefix})")
        emit("HINT: open a new interactive Bash terminal; the repository bootstrap should activate .venv automatically.")
        failures += 1

    ok, _ = run_step("Test dependencies", [sys.executable, "-c",
        "import yaml, pytest, importlib.metadata as m; "
        "print('PyYAML', m.version('PyYAML')); "
        "print('jsonschema', m.version('jsonschema')); print('pytest', pytest.__version__)"])
    if not ok:
        emit("HINT: install the project and test dependencies with: python -m pip install -e '.[dev]'")

    run_step("APT snapshot and Git Subtree base-image lock", ["bash", ".devcontainer/verify-apt-state.sh"])
    run_step("Git version", ["git", "--version"])
    exec_ok, exec_path = run_step("Git exec path", ["git", "--exec-path"])
    subtree_ok, subtree_output = run_step("Git subtree discovery in this exact environment",
        ["git", "subtree", "-h"], timeout=15, accepted_returncodes=(0, 129))
    if subtree_ok and "usage: git subtree" not in subtree_output.lower():
        emit("RESULT DETAIL: FAIL (command returned without the expected git subtree help)")
        failures += 1
    lfs_ok, lfs_output = run_step("Git LFS command availability", ["git", "lfs", "version"])
    if lfs_ok and not lfs_output.startswith("git-lfs/3.8.1"):
        emit(f"RESULT DETAIL: FAIL (expected Git LFS 3.8.1; found {lfs_output.splitlines()[0] if lfs_output else '<empty>'})")
        failures += 1

    java_ok, java_output = run_step("Java executable availability", ["java", "-version"])
    if java_ok and not re.search(r'\bversion\s+"25(?:\.|\")', java_output):
        emit("RESULT DETAIL: FAIL (Java 25 must be active; Java 21 is additional only)")
        failures += 1

    sdkman_dir = Path(os.environ.get("SDKMAN_DIR", "/usr/local/sdkman"))
    jdk21_candidates = sorted((sdkman_dir / "candidates" / "java").glob("21*"))
    jdk21_ok = False
    jdk21_detail = "No SDKMAN Java 21 candidate directory found"
    for candidate in jdk21_candidates:
        java_binary = candidate / "bin" / "java"
        if not java_binary.is_file():
            continue
        try:
            result = subprocess.run([str(java_binary), "-version"], stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            jdk21_detail = f"{candidate.name}: {exc}"
            continue
        if result.returncode == 0 and re.search(r'\bversion\s+"21(?:\.|\")', result.stdout):
            jdk21_ok = True
            jdk21_detail = f"{candidate.name}: Java 21 verified"
            break
        jdk21_detail = f"{candidate.name}: candidate does not report Java 21"
    emit(f"\n=== Additional JDK 21 ===")
    emit(jdk21_detail)
    emit(f"RESULT: {'PASS' if jdk21_ok else 'FAIL'}")
    if not jdk21_ok:
        failures += 1

    maven_ok, maven_output = run_step("Maven command availability", ["mvn", "--version"])
    if maven_ok and not maven_output.splitlines()[0].startswith("Apache Maven 3.10.0"):
        emit(f"RESULT DETAIL: FAIL (expected Apache Maven 3.10.0; found {maven_output.splitlines()[0] if maven_output else '<empty>'})")
        failures += 1

    # Pytest is intentionally run by scripts/test-in-codespaces.sh after this
    # environment/CLI check exits. Keeping process-tree tests out of a nested
    # subprocess runner prevents descendants from interacting with the outer
    # acceptance process's captured descriptors.

    run_step("Python compilation", [sys.executable, "-m", "compileall", "-q",
             "publisher_engine", "tests", "scripts"])
    run_step("CLI module version", [sys.executable, "-m", "publisher_engine.cli", "--version"])
    console_ok, console_output = run_step("Installed console entry point", ["documentation-publisher", "--version"])
    if console_ok and "2.0.15-dev" not in console_output:
        emit("RESULT DETAIL: FAIL (console script did not report the current package version)")
        failures += 1
    caps_ok, caps_output = run_step("Installed provider capability registry", ["documentation-publisher", "capabilities"])
    if caps_ok and '"github_actions"' not in caps_output:
        emit("RESULT DETAIL: FAIL (capability registry did not expose the supported workflow provider)")
        failures += 1
    generic_ok, generic_output = run_step("Generic config template must fail closed", [sys.executable, "-m",
        "publisher_engine.cli", "validate-config", "--config", "publisher.example.yml"],
        accepted_returncodes=(1,))
    if generic_ok and "Unresolved configuration placeholders" not in generic_output:
        emit("RESULT DETAIL: FAIL (generic template did not report unresolved placeholders)")
        failures += 1

    run_step("Keycloak smoke config validation", [sys.executable, "-m",
             "publisher_engine.cli", "validate-config", "--config", "publisher.keycloak.smoke.yml"])
    run_step("Keycloak smoke component plan", [sys.executable, "-m", "publisher_engine.cli", "plan",
             "--config", "publisher.keycloak.smoke.yml", "--components", "keycloak-docs"])

    emit("\n=== Summary ===")
    emit(f"Failed/blocked checks: {failures}")
    emit("Git exec path observed: " + (exec_path.strip() if exec_ok else "unavailable"))
    emit("Git subtree discovery: " + ("PASS" if subtree_ok else "FAIL"))
    emit("Interpretation: this report tests the extracted candidate against the current container; "
         "it does not deploy, push, modify the remote, or alter the existing checkout.")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nReport written to: {report_path}", flush=True)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
