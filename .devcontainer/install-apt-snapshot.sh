#!/usr/bin/env bash
set -Eeuo pipefail

fail() {
  printf '[devcontainer-apt] ERROR: %s\n' "$*" >&2
  exit 1
}

SNAPSHOT="${DEBIAN_SNAPSHOT:-}"
[[ "$SNAPSHOT" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] \
  || fail "DEBIAN_SNAPSHOT must be an immutable UTC snapshot ID; got '${SNAPSHOT:-unset}'."

BASE_IMAGE_REF="${PUBLISHER_BASE_IMAGE_REF:-}"
[[ "$BASE_IMAGE_REF" =~ @sha256:[0-9a-f]{64}$ ]] \
  || fail "PUBLISHER_BASE_IMAGE_REF must be an OCI image reference pinned by a full SHA-256 digest; got '${BASE_IMAGE_REF:-unset}'."
BUILD_PLATFORM="${PUBLISHER_BUILD_PLATFORM:-}"
[[ "$BUILD_PLATFORM" == "linux/amd64" ]] \
  || fail "PUBLISHER_BUILD_PLATFORM must be linux/amd64; got '${BUILD_PLATFORM:-unset}'."

APT_GET_BIN="${APT_GET_BIN:-apt-get}"
DPKG_QUERY_BIN="${DPKG_QUERY_BIN:-dpkg-query}"
DPKG_BIN="${DPKG_BIN:-dpkg}"
GIT_BIN="${GIT_BIN:-git}"
[[ -z "${GIT_EXEC_PATH:-}" ]] \
  || fail 'GIT_EXEC_PATH must remain unset; install the helper in the default Git exec path instead of requiring an environment override.'
APT_SOURCES_FILE="${APT_SOURCES_FILE:-/etc/apt/sources.list.d/debian-snapshot.sources}"
APT_SOURCES_DIR="${APT_SOURCES_DIR:-/etc/apt/sources.list.d}"
APT_ROOT_SOURCES="${APT_ROOT_SOURCES:-/etc/apt/sources.list}"
APT_STATE_DIR="${APT_STATE_DIR:-/usr/local/share/devcontainer}"

[[ -s "$APT_SOURCES_FILE" ]] || fail "Pinned APT source file is missing: $APT_SOURCES_FILE"
[[ ! -s "$APT_ROOT_SOURCES" ]] || fail "Legacy APT sources are still active: $APT_ROOT_SOURCES"
while IFS= read -r source_file; do
  [[ "$source_file" == "$APT_SOURCES_FILE" ]] \
    || fail "Unexpected APT source remains active during snapshot validation: $source_file"
done < <(find "$APT_SOURCES_DIR" -maxdepth 1 -type f \( -name '*.list' -o -name '*.sources' \) -print)
grep -Fq "snapshot.debian.org/archive/debian/${SNAPSHOT}/" "$APT_SOURCES_FILE" \
  || fail 'Bookworm archive does not use the expected snapshot ID.'
grep -Fq "snapshot.debian.org/archive/debian-security/${SNAPSHOT}/" "$APT_SOURCES_FILE" \
  || fail 'Bookworm security archive does not use the expected snapshot ID.'
[[ "$(grep -c '^Check-Valid-Until: no$' "$APT_SOURCES_FILE")" -eq 2 ]] \
  || fail 'Both historical snapshot entries must explicitly disable only Valid-Until freshness checks.'
grep -Fq 'Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg' "$APT_SOURCES_FILE" \
  || fail 'Debian archive signature verification keyring is not explicitly configured.'

command -v "$GIT_BIN" >/dev/null 2>&1 || fail 'Git is not installed in the digest-pinned base image.'
command -v "$APT_GET_BIN" >/dev/null 2>&1 || fail 'apt-get is unavailable in the Debian base image.'

printf '[devcontainer-apt] Updating metadata from frozen Debian snapshot %s. No APT package installation is performed.\n' "$SNAPSHOT"
"$APT_GET_BIN" -o Acquire::Retries=5 -o Acquire::https::Timeout=30 update

# Debian Bookworm's `git` binary package ships /usr/lib/git-core/git-subtree.
# The package is part of the digest-pinned base image. The command is not a
# separate Debian binary package named `git-subtree`.
find_git_subtree() {
  local candidate git_exec_path
  git_exec_path="$("$GIT_BIN" --exec-path 2>/dev/null || true)"
  if [[ -n "$git_exec_path" ]]; then
    candidate="$git_exec_path/git-subtree"
    if [[ -f "$candidate" && -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  fi
  candidate="$(command -v git-subtree 2>/dev/null || true)"
  if [[ -n "$candidate" && -f "$candidate" && -x "$candidate" ]]; then
    printf '%s\n' "$candidate"
    return 0
  fi
  # The normal Codespaces image uses /usr/local/libexec/git-core as Git's
  # active exec path. Keep the Debian helper locations as production defaults,
  # but allow hermetic tests to provide an isolated candidate list so a helper
  # installed in the test runner cannot leak into a missing-helper fixture.
  local -a fallback_candidates
  if [[ ${GIT_SUBTREE_FALLBACK_PATHS+x} ]]; then
    IFS=: read -r -a fallback_candidates <<< "$GIT_SUBTREE_FALLBACK_PATHS"
  else
    fallback_candidates=(
      /usr/lib/git-core/git-subtree
      /usr/libexec/git-core/git-subtree
      /usr/local/lib/git-core/git-subtree
      /usr/local/libexec/git-core/git-subtree
    )
  fi
  for candidate in "${fallback_candidates[@]}"; do
    [[ -n "$candidate" ]] || continue
    if [[ -f "$candidate" && -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

SUBTREE_SOURCE="$(find_git_subtree || true)"
[[ -n "$SUBTREE_SOURCE" ]] \
  || fail 'git-subtree helper is absent. The pinned Debian Bookworm git package in the base image must provide it; do not try to install a nonexistent git-subtree package.'
SUBTREE_SOURCE="$(readlink -f -- "$SUBTREE_SOURCE")"
[[ -n "$SUBTREE_SOURCE" && -f "$SUBTREE_SOURCE" && -x "$SUBTREE_SOURCE" ]] \
  || fail "Resolved git-subtree helper is not an executable regular file: ${SUBTREE_SOURCE:-<empty>}"

OWNER_OUTPUT="$("$DPKG_QUERY_BIN" -S "$SUBTREE_SOURCE" 2>/dev/null || true)"
OWNER_LABEL="$(printf '%s\n' "$OWNER_OUTPUT" | awk -F ': ' -v path="$SUBTREE_SOURCE" '$2 == path { print $1; exit }')"
OWNER_PACKAGE="${OWNER_LABEL%%:*}"
[[ "$OWNER_PACKAGE" == "git" ]] \
  || fail "Expected $SUBTREE_SOURCE to be owned by Debian package 'git'; dpkg-query reported '${OWNER_LABEL:-no owner}'."
GIT_PACKAGE_VERSION="$("$DPKG_QUERY_BIN" -W -f='${Version}' git 2>/dev/null || true)"
[[ -n "$GIT_PACKAGE_VERSION" ]] \
  || fail "Could not read the installed Debian package version for git (helper owner: $OWNER_LABEL)."

GIT_EXEC_PATH="$("$GIT_BIN" --exec-path)"
[[ "$GIT_EXEC_PATH" == /* ]] || fail "git --exec-path did not return an absolute path: $GIT_EXEC_PATH"
install -d -m 0755 "$GIT_EXEC_PATH"
SUBTREE_TARGET="$GIT_EXEC_PATH/git-subtree"
SUBTREE_TARGET_REAL="$(readlink -f -- "$SUBTREE_TARGET" 2>/dev/null || true)"
if [[ -e "$SUBTREE_TARGET" || -L "$SUBTREE_TARGET" ]]; then
  [[ "$SUBTREE_TARGET_REAL" == "$SUBTREE_SOURCE" ]] \
    || fail "Refusing to replace an existing different Git helper at $SUBTREE_TARGET (resolves to '${SUBTREE_TARGET_REAL:-<broken-symlink>}')."
else
  ln -s "$SUBTREE_SOURCE" "$SUBTREE_TARGET"
fi
[[ -x "$SUBTREE_TARGET" ]] || fail "git-subtree helper is not executable through Git's active exec path: $SUBTREE_TARGET"
SUBTREE_TARGET_REAL="$(readlink -f -- "$SUBTREE_TARGET")"
[[ "$SUBTREE_TARGET_REAL" == "$SUBTREE_SOURCE" ]] \
  || fail "Git exec-path helper resolves to $SUBTREE_TARGET_REAL instead of $SUBTREE_SOURCE."

SUBTREE_HELP="$("$GIT_BIN" subtree -h 2>&1 || true)"
[[ "$SUBTREE_HELP" == *"usage: git subtree"* ]] \
  || fail "git subtree is still not discoverable through $GIT_EXEC_PATH after linking the packaged helper."

install -d -m 0755 "$APT_STATE_DIR"
LOCK_TMP="${APT_STATE_DIR}/toolchain-lock.tsv.tmp"
{
  printf '# format=devcontainer-apt-lock-v3\n'
  printf '# snapshot=%s\n' "$SNAPSHOT"
  printf '# source-sha256=%s\n' "$(sha256sum "$APT_SOURCES_FILE" | awk '{print $1}')"
  printf '# architecture=%s\n' "$("$DPKG_BIN" --print-architecture)"
  printf '# apt-version=%s\n' "$("$APT_GET_BIN" --version | sed -n '1p')"
  printf '# dpkg-version=%s\n' "$("$DPKG_QUERY_BIN" -W -f='${Version}' dpkg)"
  printf '# base-image-ref=%s\n' "$BASE_IMAGE_REF"
  printf '# build-platform=%s\n' "$BUILD_PLATFORM"
  printf '# git-version=%s\n' "$("$GIT_BIN" --version | sed -n '1p')"
  printf '# subtree-package=git\n'
  printf '# subtree-package-version=%s\n' "$GIT_PACKAGE_VERSION"
  printf '# subtree-source=%s\n' "$SUBTREE_SOURCE"
  printf '# subtree-source-sha256=%s\n' "$(sha256sum "$SUBTREE_SOURCE" | awk '{print $1}')"
  printf '# git-exec-path=%s\n' "$GIT_EXEC_PATH"
  printf '# subtree-target=%s\n' "$SUBTREE_TARGET"
  printf '# subtree-target-realpath=%s\n' "$SUBTREE_TARGET_REAL"
  printf '# package\tversion (base-image package owning the git-subtree helper; no APT install transaction)\n'
  printf 'git\t%s\n' "$GIT_PACKAGE_VERSION"
} > "$LOCK_TMP"
install -m 0644 "$LOCK_TMP" "${APT_STATE_DIR}/toolchain-lock.tsv"
rm -f "$LOCK_TMP"
printf '[devcontainer-apt] git subtree verified via %s -> %s.\n' "$SUBTREE_TARGET" "$SUBTREE_SOURCE"
printf '[devcontainer-apt] Wrote base-image/helper lock: %s\n' "${APT_STATE_DIR}/toolchain-lock.tsv"
