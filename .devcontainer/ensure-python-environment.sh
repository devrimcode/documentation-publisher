#!/usr/bin/env bash
set -Eeuo pipefail

QUIET=0
if [[ "${1:-}" == "--quiet" ]]; then QUIET=1; fi
log() { [[ "$QUIET" == "1" ]] || printf '[devcontainer] %s\n' "$*"; }
fail() { printf '[devcontainer] ERROR: %s\n' "$*" >&2; exit 1; }

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || fail 'Workspace is not a Git checkout.'
cd "$ROOT"
PYTHON3_BIN="${PUBLISHER_PYTHON3_BIN:-python3}"
command -v "$PYTHON3_BIN" >/dev/null 2>&1 || fail 'Python 3 is missing from the Dev Container.'
PYTHON_LINE="$("$PYTHON3_BIN" --version 2>&1)" || fail 'Python 3 is unavailable.'
[[ "$PYTHON_LINE" == "Python 3.13."* ]] || fail "Codespaces requires Python 3.13 exactly; found: $PYTHON_LINE"

# Recreate a stale or wrong-version local environment rather than layering packages
# into an interpreter that violates this repository's declared runtime contract.
if [[ -x .venv/bin/python ]]; then
  if ! .venv/bin/python -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) else 1)' >/dev/null 2>&1; then
    log 'Existing .venv uses a different Python version; replacing the complete local virtual environment.'
    rm -rf .venv
  fi
fi

if [[ ! -x .venv/bin/python ]]; then
  log 'Creating the project virtual environment at .venv.'
  "$PYTHON3_BIN" -m venv .venv
fi

.venv/bin/python - <<'PY'
import sys
if sys.version_info[:2] != (3, 13):
    raise SystemExit(
        f".venv must use Python 3.13.x; found {sys.version.split()[0]}"
    )
PY

# Hash the dependency declarations so a later source/config addition or dependency
# change is picked up on the next Codespaces start, not only on first post-create.
DEPENDENCY_FILES=()
if [[ -f pyproject.toml ]]; then
  DEPENDENCY_FILES=(pyproject.toml)
elif [[ -f requirements-dev.txt ]]; then
  DEPENDENCY_FILES=(requirements-dev.txt)
elif [[ -f requirements.txt ]]; then
  DEPENDENCY_FILES=(requirements.txt)
fi

if ((${#DEPENDENCY_FILES[@]})); then
  DEPENDENCY_FINGERPRINT="$(sha256sum "${DEPENDENCY_FILES[@]}" | sha256sum | awk '{print $1}')"
  FINGERPRINT_FILE=".venv/.documentation-publisher-dependency-fingerprint"
  INSTALLED_FINGERPRINT=''
  [[ -r "$FINGERPRINT_FILE" ]] && INSTALLED_FINGERPRINT="$(cat "$FINGERPRINT_FILE")"

  IMPORT_CHECK='import yaml, jsonschema, pytest'
  if [[ -f pyproject.toml ]]; then
    IMPORT_CHECK+='; import importlib.metadata as m; m.version("documentation-publisher")'
  elif [[ ! -f requirements-dev.txt ]]; then
    IMPORT_CHECK='import yaml, jsonschema'
  fi

  NEEDS_INSTALL=0
  [[ "$DEPENDENCY_FINGERPRINT" == "$INSTALLED_FINGERPRINT" ]] || NEEDS_INSTALL=1
  .venv/bin/python -c "$IMPORT_CHECK" >/dev/null 2>&1 || NEEDS_INSTALL=1

  if [[ "$NEEDS_INSTALL" == "1" ]]; then
    log 'Installing the complete dependency set declared by the project.'
    .venv/bin/python -m pip install --upgrade pip
    if [[ -f pyproject.toml ]]; then
      .venv/bin/python -m pip install -e '.[dev]'
    elif [[ -f requirements-dev.txt ]]; then
      .venv/bin/python -m pip install -r requirements-dev.txt
    elif [[ -f requirements.txt ]]; then
      .venv/bin/python -m pip install -r requirements.txt
    fi
    .venv/bin/python -c "$IMPORT_CHECK" >/dev/null \
      || fail 'The declared Python dependencies or editable package are still unavailable after installation.'
    printf '%s\n' "$DEPENDENCY_FINGERPRINT" > "$FINGERPRINT_FILE"
  else
    log 'Project dependency fingerprint and imports are current.'
  fi
else
  log 'No Python dependency declaration exists yet; .venv is ready and dependencies will be installed when project files arrive.'
fi

# VS Code's interpreter preference does not activate a pre-existing interactive
# Bash process. Install an idempotent shell-start hook so every new workspace Bash
# terminal finds and activates the nearest repository .venv automatically.
[[ -n "${HOME:-}" ]] || fail 'HOME is not set; cannot configure automatic Bash virtual-environment activation.'
BASH_RC="${HOME}/.bashrc"
mkdir -p "$(dirname "$BASH_RC")"
touch "$BASH_RC"
ACTIVATION_MARKER='# >>> documentation-publisher .venv auto-activation >>>'
if ! grep -Fq "$ACTIVATION_MARKER" "$BASH_RC"; then
  cat >> "$BASH_RC" <<'BASHRC_EOF'

# >>> documentation-publisher .venv auto-activation >>>
# Resolve the repository from the terminal's working directory. The bootstrap is
# rechecked for every new interactive Bash terminal, so source files added after
# the first container creation trigger dependency installation on the next terminal.
if [[ $- == *i* ]]; then
  _publisher_activate_workspace_venv() {
    local candidate="${PWD:-}"
    while [[ -n "$candidate" && "$candidate" != "/" ]]; do
      if [[ -f "$candidate/.devcontainer/ensure-python-environment.sh" ]]; then
        bash "$candidate/.devcontainer/ensure-python-environment.sh" --quiet || return 1
        if [[ -f "$candidate/.venv/bin/activate" ]]; then
          # shellcheck disable=SC1090
          source "$candidate/.venv/bin/activate"
          return 0
        fi
        return 1
      fi
      candidate="$(dirname "$candidate")"
    done
    return 0
  }
  _publisher_activate_workspace_venv || printf '[devcontainer] ERROR: project .venv bootstrap failed; see the diagnostic above.\n' >&2
  unset -f _publisher_activate_workspace_venv
fi
# <<< documentation-publisher .venv auto-activation <<<
BASHRC_EOF
fi

log "Active project interpreter: $(.venv/bin/python --version 2>&1)"
log 'Automatic activation configured for newly opened interactive Bash terminals.'
