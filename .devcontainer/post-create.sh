#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  printf '[devcontainer] ERROR: The workspace is not a Git checkout.\n' >&2
  exit 1
}
cd "$ROOT"

bash .devcontainer/ensure-python-environment.sh
bash .devcontainer/verify-environment.sh

# Preserve the base-image Git/Subtree toolchain lock as ignored Codespaces evidence.
APT_LOCK_SOURCE="/usr/local/share/devcontainer/toolchain-lock.tsv"
if [[ -r "$APT_LOCK_SOURCE" ]]; then
  mkdir -p test-results
  install -m 0644 "$APT_LOCK_SOURCE" test-results/devcontainer-toolchain-lock.tsv
  sha256sum test-results/devcontainer-toolchain-lock.tsv \
    > test-results/devcontainer-toolchain-lock.tsv.SHA256
fi
