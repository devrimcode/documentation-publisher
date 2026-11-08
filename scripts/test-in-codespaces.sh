#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"
PYTHON="${PYTHON:-python3}"

# Environment, Git extension and CLI/configuration checks run first. In a
# freshly created Codespace, the Dev Container setup must already have installed
# Maven and Git LFS before this script starts.
"$PYTHON" scripts/codespaces_acceptance.py

# Keep the process-group suite in its own direct shell invocation. Write test
# output to regular files rather than a pipe: descendant-process tests must not
# inherit an outer terminal pipe that can keep the runner open after pytest exits.
mkdir -p test-results
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
MAIN_LOG="test-results/pytest-main-${TIMESTAMP}.log"
MANIFEST_LOG="test-results/pytest-manifest-cleanup-${TIMESTAMP}.log"
PACKAGING_LOG="test-results/pytest-packaging-${TIMESTAMP}.log"
PROCESS_LOG="test-results/pytest-process-${TIMESTAMP}.log"

printf '\n=== Main regression suite (manifest, packaging and process groups excluded) ===\n'
if "$PYTHON" -m pytest -q --ignore=tests/test_process.py --ignore=tests/test_packaging.py --ignore=tests/test_p6_p7_manifest_cleanup.py >"$MAIN_LOG" 2>&1; then
  cat "$MAIN_LOG"
else
  status=$?
  cat "$MAIN_LOG"
  printf 'Main regression suite failed with exit code %s. Log: %s\n' "$status" "$MAIN_LOG" >&2
  exit "$status"
fi

printf '\n=== Manifest and cleanup integration regression suite ===\n'
if "$PYTHON" -m pytest -q tests/test_p6_p7_manifest_cleanup.py >"$MANIFEST_LOG" 2>&1; then
  cat "$MANIFEST_LOG"
else
  status=$?
  cat "$MANIFEST_LOG"
  printf 'Manifest/cleanup regression suite failed with exit code %s. Log: %s\n' "$status" "$MANIFEST_LOG" >&2
  exit "$status"
fi

printf '\n=== Wheel installation regression suite ===\n'
if "$PYTHON" -m pytest -q tests/test_packaging.py >"$PACKAGING_LOG" 2>&1; then
  cat "$PACKAGING_LOG"
else
  status=$?
  cat "$PACKAGING_LOG"
  printf 'Packaging regression suite failed with exit code %s. Log: %s\n' "$status" "$PACKAGING_LOG" >&2
  exit "$status"
fi

printf '\n=== Subprocess/process-group regression suite ===\n'
if "$PYTHON" -Werror::ResourceWarning -m pytest -q tests/test_process.py >"$PROCESS_LOG" 2>&1; then
  cat "$PROCESS_LOG"
else
  status=$?
  cat "$PROCESS_LOG"
  printf 'Subprocess/process-group suite failed with exit code %s. Log: %s\n' "$status" "$PROCESS_LOG" >&2
  exit "$status"
fi

printf '\nTest logs written to:\n  %s\n  %s\n  %s\n  %s\n' \
  "$MAIN_LOG" "$MANIFEST_LOG" "$PACKAGING_LOG" "$PROCESS_LOG"
