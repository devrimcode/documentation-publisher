from __future__ import annotations

import os
import re
from urllib.parse import urlparse
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from .process import run_process


class GitError(RuntimeError):
    pass


def run_git(args: list[str], cwd: Path | None = None, env: dict[str, str] | None = None, timeout: int = 600) -> str:
    command = ["git", *args]
    safe_args = ["<redacted>" if any(x in a.lower() for x in ("token=", "password=", "authorization")) else a for a in args]
    try:
        proc = run_process(command, cwd=cwd, env=env, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        def as_text(value: str | bytes | None) -> str:
            if value is None:
                return ""
            return value.decode("utf-8", "replace") if isinstance(value, bytes) else value
        raise GitError(
            f"Git command timed out after {timeout} seconds: git {' '.join(safe_args)}\n"
            f"stdout:\n{as_text(exc.stdout)[-4000:]}\nstderr:\n{as_text(exc.stderr)[-8000:]}"
        ) from exc
    if proc.returncode:
        raise GitError(
            f"Git command failed ({proc.returncode}): git {' '.join(safe_args)}\n"
            f"stdout:\n{proc.stdout[-4000:]}\nstderr:\n{proc.stderr[-8000:]}"
        )
    return proc.stdout.strip()


def ensure_git_subtree(timeout: int = 10) -> None:
    """Check the Git extension with bounded time and actionable exec-path diagnostics."""
    try:
        proc = run_process(["git", "subtree", "-h"], timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git subtree preflight timed out after {timeout}s; check the Git extension and GIT_EXEC_PATH") from exc
    except OSError as exc:
        raise GitError(f"Unable to execute Git during git-subtree preflight: {exc}") from exc
    if "usage: git subtree" not in (proc.stdout + proc.stderr):
        try:
            exec_result = run_process(["git", "--exec-path"], timeout=5)
            git_exec_path = exec_result.stdout.strip() if exec_result.returncode == 0 else "<unavailable>"
        except (OSError, subprocess.TimeoutExpired):
            git_exec_path = "<unavailable>"
        configured_exec_path = os.environ.get("GIT_EXEC_PATH", "<unset>")
        raise GitError(
            "git subtree is not discoverable by Git. "
            f"git --exec-path={git_exec_path}; GIT_EXEC_PATH={configured_exec_path}. "
            "Install/provide the git-subtree extension in that exec path or set GIT_EXEC_PATH "
            "to the directory containing git-subtree; no checkout fallback is permitted."
        )


def _validate_git_ref(ref: str, ref_type: str = "auto") -> None:
    """Validate a ref before passing it as a positional argument to `git fetch`.

    In particular, reject option-looking values before any network operation.
    Ref names are checked against Git's own grammar instead of approximating it
    with a permissive regular expression.
    """
    if not isinstance(ref, str) or not ref or ref.startswith("-") or "\x00" in ref or any(ch.isspace() for ch in ref):
        raise GitError(f"Unsafe or empty Git ref: {ref!r}")
    if ref_type not in {"auto", "branch", "tag", "commit"}:
        raise GitError(f"Unsupported Git ref_type: {ref_type}")
    if ref_type == "commit" or (ref_type == "auto" and len(ref) in (40, 64)
                                  and all(ch in "0123456789abcdefABCDEF" for ch in ref)):
        if len(ref) not in (40, 64) or any(ch not in "0123456789abcdefABCDEF" for ch in ref):
            raise GitError(f"Git commit ref must be a full SHA: {ref!r}")
        return

    candidates: list[str] = []
    if ref.startswith("refs/"):
        if ref_type == "branch" and not ref.startswith("refs/heads/"):
            raise GitError(f"Branch ref must use refs/heads/: {ref!r}")
        if ref_type == "tag" and not ref.startswith("refs/tags/"):
            raise GitError(f"Tag ref must use refs/tags/: {ref!r}")
        candidates.append(ref)
    elif ref_type == "branch":
        candidates.append(f"refs/heads/{ref}")
    elif ref_type == "tag":
        candidates.append(f"refs/tags/{ref}")
    else:
        candidates.extend((f"refs/heads/{ref}", f"refs/tags/{ref}"))

    for candidate in candidates:
        check = run_process(["git", "check-ref-format", candidate], max_output_bytes=0)
        if check.returncode == 0:
            return
    raise GitError(f"Invalid Git {ref_type} ref: {ref!r}")


def resolve_local_or_url(value: str, config_dir: Path) -> str:
    def expand(match):
        name = match.group(1)
        if name not in os.environ:
            raise GitError(f"Required environment variable {name!r} is not set")
        return os.environ[name]
    value = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", expand, value)
    parsed = urlparse(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise GitError("Repository URLs must not embed credentials, query strings, or fragments; use an auth secret reference")
    if value.startswith("file://"):
        raise GitError("file:// repository URLs are disabled; use an explicit local filesystem path")
    if value.startswith(("https://", "http://", "ssh://", "git@")):
        return value
    p = Path(value)
    if not p.is_absolute():
        p = (config_dir / p).resolve()
    return str(p)


def make_askpass_env(auth: dict[str, Any] | None, env: dict[str, str], run_root: Path) -> tuple[dict[str, str], Path | None]:
    auth = auth or {"mode": "none"}
    mode = auth.get("mode", "none")
    if mode == "none":
        return env, None
    if mode == "ssh_agent":
        if not env.get("SSH_AUTH_SOCK"):
            raise GitError("SSH agent authentication requested but SSH_AUTH_SOCK is not set")
        return env, None
    if mode != "environment":
        raise GitError(f"Unsupported Git auth mode: {mode}")
    secret_name = auth.get("secret_env")
    if not secret_name or not env.get(secret_name):
        raise GitError(f"Required Git credential environment variable {secret_name!r} is missing")
    username_name = auth.get("username_env")
    if username_name and not env.get(username_name):
        raise GitError(f"Required Git username environment variable {username_name!r} is not set")
    username = env.get(username_name, "x-access-token") if username_name else "x-access-token"
    askpass = run_root / "git-askpass.sh"
    askpass.write_text(
        '#!/bin/sh\ncase "$1" in\n  *sername*) printf "%s\\n" "$PUBLISHER_GIT_USERNAME" ;;\n'
        '  *assword*) printf "%s\\n" "$PUBLISHER_GIT_PASSWORD" ;;\n  *) exit 1 ;;\nesac\n',
        encoding="utf-8",
    )
    askpass.chmod(0o700)
    env.update({"GIT_ASKPASS": str(askpass), "GIT_TERMINAL_PROMPT": "0",
                "PUBLISHER_GIT_USERNAME": username, "PUBLISHER_GIT_PASSWORD": env[secret_name]})
    return env, askpass


def clone_publisher(clone_url: str, ref: str, destination: Path, env: dict[str, str], timeout: int = 1800) -> str:
    _validate_git_ref(ref)
    run_git(["clone", "--no-hardlinks", "--no-checkout", clone_url, str(destination)], env=env, timeout=timeout)
    run_git(["fetch", "--no-tags", "origin", ref], cwd=destination, env=env, timeout=timeout)
    commit = run_git(["rev-parse", "FETCH_HEAD"], cwd=destination, env=env)
    run_git(["checkout", "--detach", commit], cwd=destination, env=env, timeout=timeout)
    return run_git(["rev-parse", "HEAD"], cwd=destination, env=env)


def integrate_subtree(publisher_clone: Path, source: dict[str, Any], config_dir: Path,
                      run_root: Path, env: dict[str, str]) -> dict[str, str]:
    ensure_git_subtree()
    vcs = source["vcs"]
    integration = source["integration"]
    prefix = PurePosixPath(integration["prefix"].replace("\\", "/"))
    if prefix.is_absolute() or ".." in prefix.parts or not prefix.parts or any(":" in part for part in prefix.parts):
        raise GitError(f"Unsafe subtree prefix for source {source['id']}")
    prefix_path = publisher_clone / prefix
    if prefix_path.exists() or prefix_path.is_symlink():
        raise GitError(f"Subtree prefix already exists: {prefix}")
    url = resolve_local_or_url(vcs["clone_url"], config_dir)
    ref = vcs["default_ref"]
    ref_type = vcs.get("ref_type", "auto")
    # A repository_dispatch-triggered build may pin the exact source commit
    # supplied by the source repository's push event. Normal/manual builds
    # continue to use the configured default branch or tag.
    dispatch_sha_env = vcs.get("dispatch_sha_env")
    dispatch_sha = env.get(dispatch_sha_env, "") if dispatch_sha_env else ""
    if dispatch_sha:
        _validate_git_ref(dispatch_sha, "commit")
        ref = dispatch_sha
        ref_type = "commit"
    _validate_git_ref(ref, ref_type)
    git_env = env.copy()
    git_env, _ = make_askpass_env(vcs.get("auth"), git_env, run_root)
    timeout = int(vcs.get("clone_timeout_seconds", 1800))
    fetch = ["fetch", "--no-tags"]
    history = integration.get("history", "shallow")
    depth = vcs.get("depth", 1)
    if history != "full" and depth:
        fetch.extend(["--depth", str(depth)])
    fetch.extend([url, ref])
    run_git(fetch, cwd=publisher_clone, env=git_env, timeout=timeout)
    source_sha = run_git(["rev-parse", "FETCH_HEAD"], cwd=publisher_clone, env=git_env)
    if not (40 <= len(source_sha) <= 64) or any(c not in "0123456789abcdef" for c in source_sha):
        raise GitError(f"Source {source['id']} resolved to an invalid commit SHA")

    lfs_remote = None
    try:
        if vcs.get("lfs"):
            lfs = run_process(["git", "lfs", "version"], max_output_bytes=0)
            if lfs.returncode:
                raise GitError(f"Source {source['id']} requests Git LFS but git-lfs is unavailable")
            # Never reuse a predictable remote name: a failed `remote add` must not
            # cause cleanup to remove a remote that was already present in the clone.
            candidate_remote = f"publisher-lfs-{uuid.uuid4().hex[:16]}"
            run_git(["remote", "add", candidate_remote, url], cwd=publisher_clone, env=git_env)
            lfs_remote = candidate_remote  # set only after `remote add` succeeded
            # Git LFS include patterns are paths inside the *source repository*.
            # `integration.prefix` is the destination in the publisher checkout
            # and must never be used as an LFS source path.
            source_root = PurePosixPath(str(source.get("root", ".")).replace("\\", "/"))
            if source_root.is_absolute() or ".." in source_root.parts or any(":" in part for part in source_root.parts):
                raise GitError(f"Unsafe source root for Git LFS include filter: {source.get('root')!r}")
            lfs_include = "**" if source_root.as_posix() in ("", ".") else f"{source_root.as_posix().rstrip('/')}/**"
            run_git(["lfs", "fetch", f"--include={lfs_include}", lfs_remote, source_sha],
                    cwd=publisher_clone, env=git_env, timeout=timeout)

        args = ["subtree", "add", f"--prefix={prefix.as_posix()}", source_sha]
        if integration.get("squash", True):
            args.append("--squash")
        # This is the real git-subtree command. There is deliberately no fetch/checkout fallback.
        run_git(args, cwd=publisher_clone, env=git_env, timeout=timeout)
        nested_module_files = list((publisher_clone / prefix).rglob(".gitmodules"))
        if nested_module_files:
            raise GitError(
                f"Source {source['id']} contains .gitmodules under its subtree. "
                "Nested submodules are intentionally unsupported by the generic subtree adapter; "
                "use a dedicated materialization adapter or remove/materialize them before integration."
            )
        if vcs.get("lfs"):
            run_git(["lfs", "checkout", prefix.as_posix()], cwd=publisher_clone, env=git_env, timeout=timeout)
    finally:
        if lfs_remote:
            had_primary_error = sys.exc_info()[0] is not None
            try:
                run_git(["remote", "remove", lfs_remote], cwd=publisher_clone, env=git_env)
            except GitError:
                # Do not replace the actionable integration/LFS failure with a
                # secondary cleanup error. On a successful path, cleanup failure
                # remains fatal so a stale remote is not silently retained.
                if not had_primary_error:
                    raise

    return {"source_id": source["id"], "source_commit": source_sha,
            "subtree_prefix": prefix.as_posix(), "integration_commit": run_git(["rev-parse", "HEAD"], cwd=publisher_clone, env=env),
            "integration_mode": "git_subtree", "squash": str(bool(integration.get("squash", True))).lower(),
            "lfs": str(bool(vcs.get("lfs", False))).lower()}
