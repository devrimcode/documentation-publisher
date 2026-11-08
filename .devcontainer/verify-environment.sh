#!/usr/bin/env bash
set -Eeuo pipefail

QUIET=0
if [[ "${1:-}" == "--quiet" ]]; then QUIET=1; fi
log() { [[ "$QUIET" == "1" ]] || printf '[devcontainer] %s\n' "$*"; }
fail() { printf '[devcontainer] ERROR: %s\n' "$*" >&2; exit 1; }

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || fail 'Workspace is not a Git checkout.'
cd "$ROOT"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
bash "$SCRIPT_DIR/verify-apt-state.sh" --quiet
log "Debian snapshot and Git Subtree base-image lock: verified"

for tool in python3 git java mvn; do
  command -v "$tool" >/dev/null 2>&1 || fail "Required command not found: $tool"
done
PYTHON_LINE="$(python3 --version 2>&1)" || fail 'Python 3 is unavailable.'
[[ "$PYTHON_LINE" == "Python 3.13."* ]] || fail "Codespaces image must provide Python 3.13 exactly; found: $PYTHON_LINE"

SUBTREE_HELP="$(git subtree -h 2>&1 || true)"
[[ "$SUBTREE_HELP" == *"usage: git subtree"* ]] || fail "git subtree is not discoverable through the active Git exec path ($(git --exec-path)). Do not set GIT_EXEC_PATH manually; rebuild the Dev Container and inspect the Dockerfile image-build log."
LFS_LINE="$(git lfs version 2>&1)" || fail 'Git LFS is not installed.'
[[ "$LFS_LINE" == git-lfs/3.8.1* ]] || fail "Expected Git LFS 3.8.1; found: $LFS_LINE"

JAVA_LINE="$(java -version 2>&1 | head -n 1)"
[[ "$JAVA_LINE" =~ version[[:space:]]\"25([.]|\") ]] || fail "Java 25 must be the active default JDK; found: $JAVA_LINE"
SDKMAN_DIR="${SDKMAN_DIR:-/usr/local/sdkman}"
JDK21_FOUND=0
for candidate in "$SDKMAN_DIR"/candidates/java/21*; do
  [[ -d "$candidate" && -x "$candidate/bin/java" ]] || continue
  CANDIDATE_LINE="$("$candidate/bin/java" -version 2>&1 | head -n 1)"
  if [[ "$CANDIDATE_LINE" =~ version[[:space:]]\"21([.]|\") ]]; then
    JDK21_FOUND=1
    break
  fi
done
[[ "$JDK21_FOUND" == "1" ]] || fail "JDK 21 must be installed as an additional SDKMAN candidate under $SDKMAN_DIR/candidates/java"

if [[ -f pyproject.toml || -f requirements-dev.txt || -f requirements.txt ]]; then
  [[ -x .venv/bin/python ]] || fail 'Project files are present but .venv/bin/python is missing; rebuild the Dev Container so its bootstrap can create the complete environment.'
  .venv/bin/python - <<'PUBLISHER_PYTHON_CHECK'
import importlib.util
from pathlib import Path
required = ['yaml', 'jsonschema']
if Path('pyproject.toml').exists() or Path('requirements-dev.txt').exists():
    required.append('pytest')
missing = [name for name in required if importlib.util.find_spec(name) is None]
if missing:
    raise SystemExit('Missing Python dependencies in .venv: ' + ', '.join(missing))
if Path('pyproject.toml').exists():
    import importlib.metadata
    importlib.metadata.version('documentation-publisher')
PUBLISHER_PYTHON_CHECK
fi

log "Python: $PYTHON_LINE"
log "Git: $(git --version)"
log "Git exec path: $(git --exec-path)"
log "Java default: $JAVA_LINE"
log "Java 21 additional JDK: installed"
MAVEN_LINE="$(mvn --version 2>&1 | head -n 1)"
[[ "$MAVEN_LINE" == *"Apache Maven 3.10.0"* ]] || fail "Expected Maven 3.10.0; found: $MAVEN_LINE"
log "Maven: $MAVEN_LINE"
log "Git LFS: $LFS_LINE"
log 'git subtree: available through active Git exec path'
log 'Environment verification passed.'
