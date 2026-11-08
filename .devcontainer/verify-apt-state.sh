#!/usr/bin/env bash
set -Eeuo pipefail

QUIET=0
if [[ "${1:-}" == "--quiet" ]]; then QUIET=1; fi
log() { [[ "$QUIET" == "1" ]] || printf '[devcontainer-apt] %s\n' "$*"; }
fail() { printf '[devcontainer-apt] ERROR: %s\n' "$*" >&2; exit 1; }

DPKG_QUERY_BIN="${DPKG_QUERY_BIN:-dpkg-query}"
DPKG_BIN="${DPKG_BIN:-dpkg}"
APT_GET_BIN="${APT_GET_BIN:-apt-get}"
GIT_BIN="${GIT_BIN:-git}"
[[ -z "${GIT_EXEC_PATH:-}" ]] \
  || fail 'GIT_EXEC_PATH must remain unset; install the helper in the default Git exec path instead of requiring an environment override.'
APT_SOURCES_FILE="${APT_SOURCES_FILE:-/etc/apt/sources.list.d/debian-snapshot.sources}"
APT_SOURCES_DIR="${APT_SOURCES_DIR:-/etc/apt/sources.list.d}"
APT_ROOT_SOURCES="${APT_ROOT_SOURCES:-/etc/apt/sources.list}"
APT_LOCK_FILE="${APT_LOCK_FILE:-/usr/local/share/devcontainer/toolchain-lock.tsv}"

lock_value() {
  local key="$1"
  sed -n "s/^# ${key}=//p" "$APT_LOCK_FILE" | head -n 1
}

[[ -s "$APT_SOURCES_FILE" ]] || fail "Pinned APT source file is missing: $APT_SOURCES_FILE"
[[ ! -s "$APT_ROOT_SOURCES" ]] || fail "Unexpected legacy APT source file exists: $APT_ROOT_SOURCES"
while IFS= read -r source_file; do
  [[ "$source_file" == "$APT_SOURCES_FILE" ]] \
    || fail "Unexpected APT source file exists outside the locked snapshot: $source_file"
done < <(find "$APT_SOURCES_DIR" -maxdepth 1 -type f \( -name '*.list' -o -name '*.sources' \) -print 2>/dev/null || true)
[[ -s "$APT_LOCK_FILE" ]] || fail "APT/helper lock is missing: $APT_LOCK_FILE; rebuild the Dev Container image."
[[ "$(sed -n '1p' "$APT_LOCK_FILE")" == "# format=devcontainer-apt-lock-v3" ]] \
  || fail 'APT/helper lock format is unsupported; rebuild the Dev Container image.'

EXPECTED_SNAPSHOT="$(lock_value snapshot)"
EXPECTED_SOURCE_SHA="$(lock_value source-sha256)"
EXPECTED_ARCH="$(lock_value architecture)"
EXPECTED_APT_VERSION="$(lock_value apt-version)"
EXPECTED_DPKG_VERSION="$(lock_value dpkg-version)"
EXPECTED_BASE_IMAGE="$(lock_value base-image-ref)"
EXPECTED_PLATFORM="$(lock_value build-platform)"
EXPECTED_GIT_VERSION="$(lock_value git-version)"
EXPECTED_SUBTREE_PACKAGE="$(lock_value subtree-package)"
EXPECTED_SUBTREE_PACKAGE_VERSION="$(lock_value subtree-package-version)"
EXPECTED_SUBTREE_SOURCE="$(lock_value subtree-source)"
EXPECTED_SUBTREE_SOURCE_SHA="$(lock_value subtree-source-sha256)"
EXPECTED_GIT_EXEC_PATH="$(lock_value git-exec-path)"
EXPECTED_SUBTREE_TARGET="$(lock_value subtree-target)"
EXPECTED_SUBTREE_TARGET_REAL="$(lock_value subtree-target-realpath)"

[[ "$EXPECTED_SNAPSHOT" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || fail 'APT lock has no valid immutable snapshot ID.'
[[ -n "$EXPECTED_SOURCE_SHA" ]] || fail 'APT lock has no source-file SHA-256.'
[[ "$EXPECTED_ARCH" == "amd64" ]] || fail "APT lock architecture must be amd64; found '$EXPECTED_ARCH'."
[[ -n "$EXPECTED_APT_VERSION" ]] || fail 'APT lock has no APT version.'
[[ -n "$EXPECTED_DPKG_VERSION" ]] || fail 'APT lock has no dpkg version.'
[[ "$EXPECTED_BASE_IMAGE" =~ @sha256:[0-9a-f]{64}$ ]] || fail 'APT lock base image is not pinned by a full SHA-256 digest.'
[[ "$EXPECTED_PLATFORM" == "linux/amd64" ]] || fail "APT lock build platform must be linux/amd64; found '$EXPECTED_PLATFORM'."
[[ "$EXPECTED_GIT_VERSION" == *"git version "* ]] || fail 'APT lock has no Git version.'
[[ "$EXPECTED_SUBTREE_PACKAGE" == "git" ]] || fail "git-subtree helper must be provided by Debian package 'git'; lock says '$EXPECTED_SUBTREE_PACKAGE'."
[[ -n "$EXPECTED_SUBTREE_PACKAGE_VERSION" ]] || fail 'APT lock has no Git package version.'
[[ -n "$EXPECTED_SUBTREE_SOURCE" && -n "$EXPECTED_SUBTREE_SOURCE_SHA" ]] || fail 'APT lock has no helper source path or SHA-256.'
[[ -n "$EXPECTED_GIT_EXEC_PATH" && -n "$EXPECTED_SUBTREE_TARGET" && -n "$EXPECTED_SUBTREE_TARGET_REAL" ]] \
  || fail 'APT lock has incomplete Git exec-path/helper-link metadata.'

[[ "${DEBIAN_SNAPSHOT:-}" == "$EXPECTED_SNAPSHOT" ]] \
  || fail "Container DEBIAN_SNAPSHOT (${DEBIAN_SNAPSHOT:-unset}) differs from lock ($EXPECTED_SNAPSHOT)."
[[ "${PUBLISHER_BASE_IMAGE_REF:-}" == "$EXPECTED_BASE_IMAGE" ]] \
  || fail 'Container base-image reference differs from the lock.'
[[ "${PUBLISHER_BUILD_PLATFORM:-}" == "$EXPECTED_PLATFORM" ]] \
  || fail 'Container build platform differs from the lock.'
ACTUAL_SOURCE_SHA="$(sha256sum "$APT_SOURCES_FILE" | awk '{print $1}')"
ACTUAL_ARCH="$("$DPKG_BIN" --print-architecture)"
ACTUAL_APT_VERSION="$("$APT_GET_BIN" --version | sed -n '1p')"
ACTUAL_DPKG_VERSION="$("$DPKG_QUERY_BIN" -W -f='${Version}' dpkg)"
[[ "$ACTUAL_SOURCE_SHA" == "$EXPECTED_SOURCE_SHA" ]] \
  || fail 'Pinned APT source file changed after the image was built.'
[[ "$ACTUAL_ARCH" == "$EXPECTED_ARCH" ]] \
  || fail "APT architecture drift: expected $EXPECTED_ARCH, found $ACTUAL_ARCH"
[[ "$ACTUAL_APT_VERSION" == "$EXPECTED_APT_VERSION" ]] \
  || fail "APT version drift: expected $EXPECTED_APT_VERSION, found $ACTUAL_APT_VERSION"
[[ "$ACTUAL_DPKG_VERSION" == "$EXPECTED_DPKG_VERSION" ]] \
  || fail "dpkg version drift: expected $EXPECTED_DPKG_VERSION, found $ACTUAL_DPKG_VERSION"
grep -Fq "snapshot.debian.org/archive/debian/${EXPECTED_SNAPSHOT}/" "$APT_SOURCES_FILE" \
  || fail 'Bookworm APT source no longer points to the locked snapshot.'
grep -Fq "snapshot.debian.org/archive/debian-security/${EXPECTED_SNAPSHOT}/" "$APT_SOURCES_FILE" \
  || fail 'Bookworm security APT source no longer points to the locked snapshot.'

ACTUAL_GIT_VERSION="$("$GIT_BIN" --version | sed -n '1p')"
ACTUAL_GIT_EXEC_PATH="$("$GIT_BIN" --exec-path)"
[[ "$ACTUAL_GIT_VERSION" == "$EXPECTED_GIT_VERSION" ]] \
  || fail "Git version drift: expected $EXPECTED_GIT_VERSION, found $ACTUAL_GIT_VERSION"
[[ "$ACTUAL_GIT_EXEC_PATH" == "$EXPECTED_GIT_EXEC_PATH" ]] \
  || fail "Git exec-path drift: expected $EXPECTED_GIT_EXEC_PATH, found $ACTUAL_GIT_EXEC_PATH"
[[ "$EXPECTED_SUBTREE_TARGET" == "$ACTUAL_GIT_EXEC_PATH/git-subtree" ]] \
  || fail 'Locked git-subtree target does not match the current Git exec path.'
[[ -f "$EXPECTED_SUBTREE_SOURCE" && -x "$EXPECTED_SUBTREE_SOURCE" ]] \
  || fail "Locked git-subtree source is missing or not executable: $EXPECTED_SUBTREE_SOURCE"
ACTUAL_SUBTREE_SOURCE_SHA="$(sha256sum "$EXPECTED_SUBTREE_SOURCE" | awk '{print $1}')"
[[ "$ACTUAL_SUBTREE_SOURCE_SHA" == "$EXPECTED_SUBTREE_SOURCE_SHA" ]] \
  || fail 'The packaged git-subtree helper changed after the image was built.'
[[ -x "$EXPECTED_SUBTREE_TARGET" ]] \
  || fail "git-subtree is not executable through Git's active exec path: $EXPECTED_SUBTREE_TARGET"
ACTUAL_SUBTREE_TARGET_REAL="$(readlink -f -- "$EXPECTED_SUBTREE_TARGET" 2>/dev/null || true)"
[[ "$ACTUAL_SUBTREE_TARGET_REAL" == "$EXPECTED_SUBTREE_TARGET_REAL" ]] \
  || fail 'The active git-subtree helper link no longer resolves to its locked target.'
[[ "$ACTUAL_SUBTREE_TARGET_REAL" == "$EXPECTED_SUBTREE_SOURCE" ]] \
  || fail 'The active Git exec-path helper does not resolve to the locked packaged source.'

OWNER_OUTPUT="$("$DPKG_QUERY_BIN" -S "$EXPECTED_SUBTREE_SOURCE" 2>/dev/null || true)"
OWNER_LABEL="$(printf '%s\n' "$OWNER_OUTPUT" | awk -F ': ' -v path="$EXPECTED_SUBTREE_SOURCE" '$2 == path { print $1; exit }')"
OWNER_PACKAGE="${OWNER_LABEL%%:*}"
[[ "$OWNER_PACKAGE" == "$EXPECTED_SUBTREE_PACKAGE" ]] \
  || fail "git-subtree helper package-owner drift: expected $EXPECTED_SUBTREE_PACKAGE, found '${OWNER_LABEL:-no owner}'."
ACTUAL_GIT_PACKAGE_VERSION="$("$DPKG_QUERY_BIN" -W -f='${Version}' "$EXPECTED_SUBTREE_PACKAGE" 2>/dev/null || true)"
[[ "$ACTUAL_GIT_PACKAGE_VERSION" == "$EXPECTED_SUBTREE_PACKAGE_VERSION" ]] \
  || fail "Git package version drift: expected $EXPECTED_SUBTREE_PACKAGE_VERSION, found ${ACTUAL_GIT_PACKAGE_VERSION:-<not installed>}"
SUBTREE_HELP="$("$GIT_BIN" subtree -h 2>&1 || true)"
[[ "$SUBTREE_HELP" == *"usage: git subtree"* ]] \
  || fail "git subtree is not discoverable through the active Git exec path ($ACTUAL_GIT_EXEC_PATH)."

PACKAGE_COUNT=0
while IFS=$'\t' read -r package expected_version; do
  [[ -n "$package" && "$package" != \#* ]] || continue
  [[ -n "$expected_version" ]] || fail "APT lock contains an empty version for $package."
  actual_version="$("$DPKG_QUERY_BIN" -W -f='${Version}' "$package" 2>/dev/null)" \
    || fail "Locked base-image package is not installed: $package"
  [[ "$actual_version" == "$expected_version" ]] \
    || fail "Base-image package drift for $package: expected $expected_version, found $actual_version"
  PACKAGE_COUNT=$((PACKAGE_COUNT + 1))
done < "$APT_LOCK_FILE"
(( PACKAGE_COUNT > 0 )) || fail 'APT lock contains no base-image package records.'

log "Debian snapshot: $EXPECTED_SNAPSHOT"
log "APT source SHA-256: $ACTUAL_SOURCE_SHA"
log "APT architecture: $ACTUAL_ARCH"
log "APT version: $ACTUAL_APT_VERSION"
log "dpkg version: $ACTUAL_DPKG_VERSION"
log "Pinned base image: $EXPECTED_BASE_IMAGE"
log "Git package version: $ACTUAL_GIT_PACKAGE_VERSION"
log "git-subtree helper SHA-256: $ACTUAL_SUBTREE_SOURCE_SHA"
log "Git exec-path link: $EXPECTED_SUBTREE_TARGET -> $ACTUAL_SUBTREE_TARGET_REAL"
log "Base-image package versions verified: $PACKAGE_COUNT"
