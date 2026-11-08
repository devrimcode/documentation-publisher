from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import urlparse, urlsplit, urlunsplit, unquote
from html.parser import HTMLParser
from html import escape as html_escape, unescape as html_unescape

from .config import load_config
from .archive import extract_zip, extract_tar
from .gitops import clone_publisher, integrate_subtree, resolve_local_or_url, run_git, make_askpass_env, GitError
from .links import rewrite_html_file, LinkResolutionError, transform_keycloak_asciidoc_edit_links
from .process import run_process


class BuildError(RuntimeError):
    pass


def safe_child(root: Path, relative: str, *, allow_dot: bool = False) -> Path:
    raw = PurePosixPath(relative.replace("\\", "/"))
    if raw.is_absolute() or ".." in raw.parts or (not allow_dot and not raw.parts):
        raise BuildError(f"Unsafe relative path: {relative!r}")
    if any("\x00" in part for part in raw.parts):
        raise BuildError(f"NUL character in relative path: {relative!r}")
    if any(":" in part for part in raw.parts):
        raise BuildError(f"Drive-qualified path is not permitted: {relative!r}")
    if any(part.casefold() == ".git" for part in raw.parts):
        raise BuildError(f"Path must not reference Git metadata (.git): {relative!r}")
    target = root.joinpath(*[p for p in raw.parts if p not in ("", ".")])
    resolved_root = root.resolve()
    resolved = target.resolve(strict=False)
    if not resolved.is_relative_to(resolved_root):
        raise BuildError(f"Path escapes configured root: {relative!r}")
    # Reject paths that enter Git's control directory through an existing
    # symlink as well as paths that name `.git` lexically. Looking only at the
    # configured spelling would allow e.g. `generated -> .git` followed by
    # `generated/config` to bypass the repository-metadata guard.
    resolved_relative = resolved.relative_to(resolved_root)
    if any(part.casefold() == ".git" for part in resolved_relative.parts):
        raise BuildError(f"Resolved path must not reference Git metadata (.git): {relative!r}")
    return target


def _git_context(project_dir: Path) -> tuple[Path, Path] | None:
    """Return the worktree root and actual git dir, or None outside a checkout."""
    try:
        root = Path(run_git(["rev-parse", "--show-toplevel"], cwd=project_dir, timeout=10)).resolve()
        git_dir = Path(run_git(["rev-parse", "--absolute-git-dir"], cwd=project_dir, timeout=10)).resolve()
        return root, git_dir
    except (GitError, OSError):
        return None


def _guard_not_git_metadata(path: Path, project_dir: Path, *, label: str) -> None:
    """Reject workspace/output locations inside a Git metadata directory."""
    candidate = path.resolve(strict=False)
    context = _git_context(project_dir)
    if context:
        _, git_dir = context
        if candidate == git_dir or candidate.is_relative_to(git_dir):
            raise BuildError(f"{label} must not be inside Git metadata: {candidate}")
    if any(parent.name.casefold() == ".git" for parent in (candidate, *candidate.parents)):
        raise BuildError(f"{label} must not be inside a .git directory: {candidate}")


def _guard_not_tracked_output(path: Path, project_dir: Path, *, label: str) -> None:
    """Refuse to replace paths that overlap any tracked file in the checkout."""
    context = _git_context(project_dir)
    if not context:
        return
    repo_root, git_dir = context
    candidate = path.resolve(strict=False)
    if candidate == git_dir or candidate.is_relative_to(git_dir):
        raise BuildError(f"{label} must not overlap Git metadata: {candidate}")
    try:
        relative = candidate.relative_to(repo_root).as_posix().casefold()
    except ValueError:
        # Explicit external publishing destinations are not part of this checkout.
        return
    if not relative or relative == ".":
        raise BuildError(f"{label} must not replace the repository root")
    tracked = run_git(["ls-files", "-z"], cwd=repo_root, timeout=10).split("\0")
    conflicts = []
    for item in tracked:
        if not item:
            continue
        key = item.replace("\\", "/").casefold()
        if key == relative or key.startswith(relative + "/") or relative.startswith(key + "/"):
            conflicts.append(item)
            if len(conflicts) >= 5:
                break
    if conflicts:
        sample = ", ".join(repr(x) for x in conflicts)
        raise BuildError(f"{label} overlaps tracked repository content and is protected: {candidate} (e.g. {sample})")


def _copy_regular_file_nofollow(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> str:
    """Copy a regular file without following a symlink swapped in during copying.

    O_NOFOLLOW is used where the platform provides it, followed by an fstat check
    on the opened descriptor. Symlink entries in copytree are separately preserved
    (`symlinks=True`) and rejected after staging; they are never dereferenced.
    """
    source_path = Path(source)
    destination_path = Path(destination)
    try:
        path_stat = source_path.lstat()
    except OSError as exc:
        raise BuildError(f"Could not inspect copy source {source_path}: {exc}") from exc
    if stat.S_ISLNK(path_stat.st_mode):
        raise BuildError(f"Refusing to copy a symlink source file: {source_path}")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        source_fd = os.open(source_path, flags)
    except OSError as exc:
        raise BuildError(f"Could not safely open regular file {source_path}: {exc}") from exc
    try:
        source_stat = os.fstat(source_fd)
        if not stat.S_ISREG(source_stat.st_mode):
            raise BuildError(f"Refusing to copy non-regular or symlink source file: {source_path}")
        if path_stat.st_ino and source_stat.st_ino and (path_stat.st_dev, path_stat.st_ino) != (source_stat.st_dev, source_stat.st_ino):
            raise BuildError(f"Copy source changed during safe-open check: {source_path}")
        destination_fd = os.open(
            destination_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            stat.S_IMODE(source_stat.st_mode) or 0o600,
        )
        try:
            with os.fdopen(source_fd, "rb", closefd=False) as src, os.fdopen(destination_fd, "wb", closefd=False) as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
                dst.flush()
                os.fsync(dst.fileno())
            try:
                os.utime(destination_path, ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns), follow_symlinks=False)
            except (NotImplementedError, OSError):
                pass
        finally:
            os.close(destination_fd)
    finally:
        os.close(source_fd)
    return str(destination_path)


def _remove_tree_strict(path: Path, retries: int = 1, delay: float = 0.15) -> None:
    if not path.exists() and not path.is_symlink():
        return
    last_error = None
    for _ in range(retries + 1):
        try:
            if path.is_symlink() or not path.is_dir():
                path.unlink(missing_ok=True)
            else:
                shutil.rmtree(path)
            return
        except OSError as exc:
            last_error = exc
            def repair(func, name, _exc):
                p = Path(name)
                try:
                    # Never chmod through a symlink while repairing permissions
                    # for recursive cleanup; that would modify its external target.
                    if p.is_symlink():
                        func(name)
                        return
                    p.chmod(0o700)
                    func(name)
                except OSError:
                    raise
            try:
                shutil.rmtree(path, onerror=repair)
                return
            except OSError as nested:
                last_error = nested
                time.sleep(max(0.0, delay))
    raise BuildError(f"Could not remove managed temporary path {path}: {last_error}")



class BuildLock:
    def __init__(self, output: Path, timeout: int):
        self.path = output.with_name(f".{output.name}.publisher.lock")
        self.timeout = timeout
        self.token = uuid.uuid4().hex
        self.acquired = False

    @staticmethod
    def _stale(path: Path) -> bool:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            pid = int(data.get("pid", -1))
            local_host = os.uname().nodename if hasattr(os, "uname") else os.environ.get("COMPUTERNAME", "unknown")
            if data.get("host") != local_host:
                return False
            os.kill(pid, 0)
            return False
        except ProcessLookupError:
            return True
        except (OSError, ValueError, TypeError, json.JSONDecodeError, AttributeError):
            return False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        host = os.uname().nodename if hasattr(os, "uname") else os.environ.get("COMPUTERNAME", "unknown")
        payload = json.dumps({"pid": os.getpid(), "host": host, "token": self.token})
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                self.acquired = True
                return self
            except FileExistsError:
                if self._stale(self.path):
                    try: self.path.unlink()
                    except OSError: pass
                    continue
                if time.monotonic() >= deadline:
                    raise BuildError(f"Another build holds lock {self.path}")
                time.sleep(0.2)

    def __exit__(self, exc_type, exc, tb):
        if self.acquired:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if data.get("token") == self.token:
                    self.path.unlink(missing_ok=True)
            finally:
                self.acquired = False


def _run_command(task: dict[str, Any], publisher_root: Path, source_root: Path, run_root: Path,
                 global_env: dict[str, str], all_source_roots: dict[str, Path]) -> dict[str, Any]:
    values = {"source_root": str(source_root), "publisher_root": str(publisher_root),
              "workspace": str(publisher_root), "run_root": str(run_root)}
    for source_id, path in all_source_roots.items():
        values[f"source:{source_id}"] = str(path)
    token_re = re.compile(r"\{(source_root|publisher_root|workspace|run_root|source:[A-Za-z][A-Za-z0-9_.-]{0,63})\}")
    expand = lambda value: token_re.sub(lambda m: values[m.group(1)], str(value))
    argv = [expand(arg) for arg in task["argv"]]
    allow_env = set(task.get("pass_environment", []))
    secret_env = set(task.get("secret_environment", []))
    task_env = {key: global_env[key] for key in allow_env if key in global_env}
    for key in ("PATH", "HOME", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL", "JAVA_HOME"):
        if key in global_env:
            task_env.setdefault(key, global_env[key])
    secrets_for_redaction: list[str] = []
    for key, value in task.get("environment", {}).items():
        if value.startswith("${") and value.endswith("}"):
            name = value[2:-1]
            allowed = allow_env | secret_env
            if name not in allowed:
                raise BuildError(f"Task {task['id']}: environment variable {name} is not explicitly allowlisted")
            if name not in global_env:
                raise BuildError(f"Task {task['id']}: environment variable {name} is not set")
            task_env[key] = global_env[name]
            if name in secret_env and global_env[name]:
                secrets_for_redaction.append(global_env[name])
        else:
            task_env[key] = expand(value)
    # Never pass repository credentials or askpass helpers to arbitrary build commands.
    for key in ("PUBLISHER_GIT_PASSWORD", "PUBLISHER_GIT_USERNAME", "GIT_ASKPASS", "GIT_TRACE", "GIT_CURL_VERBOSE"):
        task_env.pop(key, None)

    scope = task.get("working_directory_scope", "source")
    allowed_root = source_root if scope == "source" else publisher_root
    workdir_value = expand(task.get("working_directory", "."))
    workdir = Path(workdir_value)
    if not workdir.is_absolute():
        workdir = allowed_root / workdir
    if not workdir.resolve().is_relative_to(allowed_root.resolve()):
        raise BuildError(f"Task {task['id']}: working directory escapes configured {scope} root")
    if not workdir.is_dir():
        raise BuildError(f"Task {task['id']}: working directory does not exist: {workdir}")

    def redact(text: str) -> str:
        for secret in sorted(set(secrets_for_redaction), key=len, reverse=True):
            text = text.replace(secret, "<redacted>")
        return text

    attempts = task.get("retry", 0) + 1
    started = time.monotonic()
    last = None
    last_output = ""
    for attempt in range(1, attempts + 1):
        try:
            proc = run_process(argv, cwd=workdir, env=task_env,
                               timeout=task.get("timeout_seconds", 3600),
                               stderr_to_stdout=True, max_output_bytes=16_000)
        except subprocess.TimeoutExpired as exc:
            last = f"timeout after {task.get('timeout_seconds')} seconds"
            output = (exc.stdout or "")
            if isinstance(output, bytes):
                output = output.decode("utf-8", "replace")
            last_output = redact(output[-16000:])
            last += "\n" + last_output
        else:
            last_output = redact(proc.stdout[-16000:])
            if proc.returncode == 0:
                outputs: list[str] = []
                for pattern in task.get("outputs", []):
                    rel = PurePosixPath(str(pattern).replace("\\", "/"))
                    if (rel.is_absolute() or ".." in rel.parts
                            or any("\x00" in part or ":" in part or part.casefold() == ".git" for part in rel.parts)):
                        raise BuildError(f"Task {task['id']}: unsafe declared output path {pattern!r}")
                    matches = sorted(allowed_root.glob(rel.as_posix()))
                    if not matches:
                        raise BuildError(f"Task {task['id']}: declared output did not match any files: {pattern}")
                    for item in matches:
                        if not item.resolve().is_relative_to(allowed_root.resolve()) or item.is_symlink():
                            raise BuildError(f"Task {task['id']}: declared output is unsafe: {item}")
                        outputs.append(item.relative_to(allowed_root).as_posix())
                return {"task_id": task["id"], "status": "success", "attempt": attempt,
                        "duration_seconds": round(time.monotonic() - started, 3), "outputs": outputs}
            last = f"exit code {proc.returncode}\n{last_output}"
        if attempt < attempts:
            time.sleep(min(float(task.get("retry_delay_seconds", 1)) * attempt, 15))
    raise BuildError(f"Task {task['id']} failed after {attempts} attempt(s):\n{last}")

def _task_order(tasks: list[dict[str, Any]], wanted: set[str]) -> list[dict[str, Any]]:
    by_id = {t["id"]: t for t in tasks}
    result: list[dict[str, Any]] = []
    visited: set[str] = set()
    def visit(task_id: str) -> None:
        if task_id in visited:
            return
        if task_id not in by_id:
            raise BuildError(f"Unknown task {task_id}")
        for dependency in by_id[task_id].get("depends_on", []):
            visit(dependency)
        visited.add(task_id)
        result.append(by_id[task_id])
    for task_id in sorted(wanted):
        visit(task_id)
    return result


def resolve_build_plan(config: dict[str, Any], selected_ids: list[str] | None = None) -> dict[str, Any]:
    """Resolve the exact component/task/source closure used by a build.

    This is the single planning implementation shared by `plan` and `build` so
    previews cannot advertise work or sources that the subsequent build omits.
    """
    available = {component["id"]: component for component in config["components"]}
    requested_ids = selected_ids if selected_ids is not None else list(available)
    unknown = set(requested_ids) - set(available)
    if unknown:
        raise BuildError(f"Unknown component(s): {', '.join(sorted(unknown))}")
    if not requested_ids:
        raise BuildError("At least one component must be selected")

    chosen_set: set[str] = set()

    def add_component(component_id: str) -> None:
        if component_id in chosen_set:
            return
        component = available[component_id]
        for dependency in component.get("dependencies", []):
            if dependency not in available:
                raise BuildError(f"Component {component_id} has unknown dependency {dependency}")
            add_component(dependency)
        chosen_set.add(component_id)

    for component_id in requested_ids:
        add_component(component_id)

    chosen_ids = [component["id"] for component in config["components"] if component["id"] in chosen_set]
    chosen = [available[component_id] for component_id in chosen_ids]
    wanted_tasks: set[str] = set()
    required_source_ids = {component["source_id"] for component in chosen}
    for component in chosen:
        wanted_tasks.update(component.get("tasks", []))
    ordered_tasks = _task_order(config["build_tasks"], wanted_tasks)
    for task in ordered_tasks:
        if task.get("source_id"):
            required_source_ids.add(task["source_id"])
    unresolved_task_sources = [task["id"] for task in ordered_tasks if not task.get("source_id")]
    if unresolved_task_sources and len(required_source_ids) != 1:
        raise BuildError(
            "Tasks without source_id are ambiguous because the selected components use multiple sources: "
            + ", ".join(unresolved_task_sources)
        )
    inferred_source_id = next(iter(required_source_ids)) if required_source_ids else None
    task_source_ids = {task["id"]: task.get("source_id") or inferred_source_id for task in ordered_tasks}
    known_sources = {source["id"] for source in config["sources"]}
    for task_id, source_id in task_source_ids.items():
        if source_id not in known_sources:
            raise BuildError(f"Task {task_id} references unknown source_id {source_id!r}")
        required_source_ids.add(source_id)

    sources = [source for source in config["sources"] if source["id"] in required_source_ids]
    return {
        "requested_ids": list(requested_ids),
        "chosen_ids": chosen_ids,
        "components": chosen,
        "tasks": ordered_tasks,
        "task_source_ids": task_source_ids,
        "sources": sources,
        "required_source_ids": required_source_ids,
    }


class _HTMLCollector(HTMLParser):
    _VOID_ELEMENTS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.refs: list[tuple[str, str, str]] = []
        self.errors: list[str] = []
        self.stack: list[str] = []
        self.depth = 0
        self.max_depth = 0
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        normalized_tag = tag.lower()
        if normalized_tag not in self._VOID_ELEMENTS:
            self.stack.append(normalized_tag)
        self.depth = len(self.stack)
        self.max_depth = max(self.max_depth, self.depth)
        if a.get("srcdoc") is not None:
            self.errors.append(f"{tag} srcdoc is not permitted")
        for key in ("id", "name"):
            if a.get(key): self.ids.add(a[key])
        for key in ("href", "src", "poster", "data", "action", "formaction",
                    "cite", "background", "manifest", "xlink:href"):
            if a.get(key): self.refs.append((normalized_tag, key, a[key]))
        if a.get("srcset"):
            for part in a["srcset"].split(","):
                url = part.strip().split()[0] if part.strip() else ""
                if url: self.refs.append((normalized_tag, "srcset", url))
        # A meta refresh is a navigation/redirect target, but unlike ordinary
        # links it is embedded in the content attribute. Feed its destination
        # into the same scheme, external-host, local-path and fragment checks.
        if normalized_tag == "meta" and (a.get("http-equiv") or "").strip().casefold() == "refresh":
            refresh_target, refresh_error = _meta_refresh_target(a.get("content") or "")
            if refresh_error:
                self.errors.append(f"Malformed meta refresh URL: {refresh_error}")
            elif refresh_target:
                self.refs.append((normalized_tag, "meta-refresh", refresh_target))
    def handle_endtag(self, tag):
        normalized_tag = tag.lower()
        if normalized_tag in self.stack:
            index = len(self.stack) - 1 - self.stack[::-1].index(normalized_tag)
            del self.stack[index:]
        self.depth = len(self.stack)


def _meta_refresh_target(content: str) -> tuple[str | None, str | None]:
    """Extract a destination from an HTML meta-refresh content attribute.

    HTMLParser has already decoded character references in attribute values.
    Accept the common HTML forms `0;url=/path`, `0; URL='/path'`, and
    `0;url="/path"`, without treating a delay-only refresh as a link.
    Return a parse error for malformed quoted destinations so disabling local
    path lint cannot accidentally disable redirect syntax validation.
    """
    match = re.search(r"(?:^|;)\s*url\s*=\s*(.*?)\s*$", content, re.IGNORECASE)
    if not match:
        return None, None
    raw_target = match.group(1).strip()
    if raw_target[:1] in {"'", '"'}:
        quote = raw_target[0]
        closing = raw_target.find(quote, 1)
        if closing < 0:
            return None, "unterminated quoted destination"
        if raw_target[closing + 1:].strip():
            return None, "unexpected characters after quoted destination"
        target = raw_target[1:closing].strip()
    else:
        target = raw_target
    return (target or None), None


def _site_symlink_errors(site_root: Path) -> list[str]:
    if site_root.is_symlink():
        return [f"Site root is a symlink: {site_root}"]
    errors = []
    for path in site_root.rglob("*"):
        if path.is_symlink():
            errors.append(f"Symlink in site: {path.relative_to(site_root)}")
    return errors


def _write_final_build_manifest(site_root: Path, manifest: dict[str, Any]) -> None:
    """Write a stable manifest whose byte/file totals include the manifest itself."""
    manifest_path = site_root / "build-manifest.json"
    for _ in range(12):
        files = [path for path in site_root.rglob("*") if path.is_file()]
        manifest["site_files"] = len(files)
        manifest["site_bytes"] = sum(path.stat().st_size for path in files)
        payload = json.dumps(manifest, indent=2)
        try:
            current = manifest_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            current = None
        if current == payload:
            # Recompute once after the last write; values must describe the final tree.
            final_files = [path for path in site_root.rglob("*") if path.is_file()]
            final_bytes = sum(path.stat().st_size for path in final_files)
            if len(final_files) == manifest["site_files"] and final_bytes == manifest["site_bytes"]:
                return
        manifest_path.write_text(payload, encoding="utf-8")
    raise BuildError("Could not stabilize build-manifest.json self-accounting totals")


def validate_site(site_root: Path, config: dict[str, Any]) -> list[str]:
    # Symlink freedom is a publication invariant, not a tunable lint option.
    # Stop before stat/read operations can follow an out-of-tree link.
    errors = _site_symlink_errors(site_root)
    if errors:
        return errors
    files = [p for p in site_root.rglob("*") if p.is_file()]
    max_files = config["validation"].get("max_files", 200000)
    if len(files) > max_files:
        errors.append(f"Site has {len(files)} files; maximum is {max_files}")
    total = sum(p.stat().st_size for p in files)
    maximum = config["validation"].get("max_site_bytes", 1_000_000_000)
    if total > maximum:
        errors.append(f"Site is {total} bytes; maximum is {maximum}")
    if any(p.name == ".git" or ".git" in p.parts for p in files):
        errors.append("Git metadata leaked into the site")
    if config["validation"].get("require_build_manifest", True):
        manifest_path = site_root / "build-manifest.json"
        if not manifest_path.is_file():
            errors.append("Required build-manifest.json is missing")
        else:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest.get("schema_version") != 2:
                    errors.append("build-manifest.json has an unsupported schema_version")
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"build-manifest.json is invalid: {exc}")
    for required in config["validation"].get("required_files", []):
        p = safe_child(site_root, required)
        if not p.is_file(): errors.append(f"Required output file missing: {required}")

    # Parse HTML independently from local-path existence validation. The
    # individual validation switches control their own checks; disabling local
    # link checks must not disable fragment, depth, external-host, or invariant
    # security checks.
    html_data: dict[Path, _HTMLCollector] = {}
    validate_local_links = config["validation"].get("validate_local_links", True)
    validate_fragments = config["validation"].get("validate_fragments", True)
    validate_external_links = config["validation"].get("validate_external_links", False)
    max_depth = config["validation"].get("max_html_depth", 0)
    allowed_redirect_schemes = set(
        config["validation"].get("validate_redirect_schemes", ["https", "http"])
    )
    allowed_external_hosts = {
        value.lower() for value in config["validation"].get("allowed_external_hosts", [])
    }

    for page in (p for p in files if p.suffix.lower() in {".html", ".htm"}):
        try:
            text = page.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            # Reading is necessary for the always-on active-content checks as
            # well as any optional HTML validation, so fail closed.
            errors.append(f"Cannot read HTML {page.relative_to(site_root)}: {exc}")
            continue
        parser = _HTMLCollector()
        parser.feed(text)
        parser.close()
        html_data[page] = parser
        if max_depth and parser.max_depth > max_depth:
            errors.append(
                f"HTML nesting depth in {page.relative_to(site_root)} is {parser.max_depth}; maximum is {max_depth}"
            )
        # srcdoc and active data/URL schemes are publication safety invariants,
        # not optional local-link linting.
        errors.extend(
            f"{page.relative_to(site_root)}: {message}" for message in parser.errors
        )

    for page, parser in html_data.items():
        for tag, kind, ref in parser.refs:
            parsed = urlparse(ref)
            scheme = parsed.scheme.lower()
            if scheme == "data":
                # Only allow passive raster image data on <img>. SVG and data
                # URLs in scripts, frames, objects, embeds, media and srcset
                # are deliberately excluded.
                passive_image = (
                    tag == "img" and kind == "src"
                    and re.match(r"^data:image/(?:png|jpeg|gif|webp|avif);base64,", ref, re.I)
                )
                if not passive_image:
                    errors.append(
                        f"Data URL is not permitted in {tag} {kind} on {page.relative_to(site_root)}"
                    )
                continue
            if kind == "meta-refresh" and scheme:
                # validate_redirect_schemes governs actual redirects only. It
                # must not reject ordinary documentation hyperlinks to HTTP
                # service endpoints (for example localhost/admin examples).
                if scheme not in allowed_redirect_schemes:
                    errors.append(f"URL scheme is not permitted in {page.relative_to(site_root)}: {ref}")
                    continue
            elif kind == "href" and scheme and tag in {"a", "area"}:
                # Ordinary navigation links may legitimately use HTTP, HTTPS,
                # mailto or tel. Active/unsupported schemes remain blocked;
                # meta-refresh and generated fallback redirects keep the
                # stricter validate_redirect_schemes allowlist above.
                if scheme not in {"http", "https", "mailto", "tel"}:
                    errors.append(f"URL scheme is not permitted in {page.relative_to(site_root)}: {ref}")
                    continue
            if scheme in {"javascript", "vbscript", "file"}:
                errors.append(f"Forbidden URL scheme in {page.relative_to(site_root)}: {ref}")
                continue
            if scheme in {"http", "https"} or ref.startswith("//"):
                external = parsed if scheme else urlparse("https:" + ref)
                if not external.netloc:
                    errors.append(f"Malformed external URL in {page.relative_to(site_root)}: {ref}")
                if validate_external_links:
                    host = (external.hostname or "").lower()
                    if not allowed_external_hosts or (host not in allowed_external_hosts and "*" not in allowed_external_hosts):
                        errors.append(
                            f"External host is not allowed in {page.relative_to(site_root)}: {external.hostname}"
                        )
                continue
            if scheme in {"mailto", "tel"}:
                continue
            if scheme:
                errors.append(f"Unsupported URL scheme in {page.relative_to(site_root)}: {ref}")
                continue
            if ref.startswith("//"):
                continue

            # Resolve local targets only when either existence checking or
            # fragment checking needs them. Fragment checks remain independent
            # from validate_local_links.
            if not validate_local_links and not (validate_fragments and parsed.fragment):
                continue
            raw_path = unquote(parsed.path).replace("\\", "/")
            if raw_path.startswith("/"):
                rooted = raw_path.lstrip("/")
                base_path = _site_base_path(config).strip("/")
                if base_path and (rooted == base_path or rooted.startswith(base_path + "/")):
                    rooted = rooted[len(base_path):].lstrip("/")
                target = (site_root / rooted).resolve()
            else:
                target = (page.parent / raw_path).resolve() if raw_path else page.resolve()
            if not target.is_relative_to(site_root.resolve()):
                errors.append(f"Link escapes site: {page.relative_to(site_root)} -> {ref}")
                continue
            if validate_local_links and raw_path and not target.is_file() and not (
                target.is_dir() and (target / "index.html").is_file()
            ):
                errors.append(f"Broken local link: {page.relative_to(site_root)} -> {ref}")
                continue
            if validate_fragments and parsed.fragment:
                fragment_page = target if raw_path else page
                if fragment_page.is_dir() and (fragment_page / "index.html").is_file():
                    fragment_page = (fragment_page / "index.html").resolve()
                if fragment_page.suffix.lower() in {".html", ".htm"} and fragment_page in html_data:
                    if unquote(parsed.fragment) not in html_data[fragment_page].ids:
                        errors.append(f"Missing fragment: {page.relative_to(site_root)} -> {ref}")

    # External-host policy is independent of CSS asset existence validation.
    # When CSS asset validation is disabled, external URLs are still checked
    # against allowed_external_hosts if validate_external_links is enabled.
    validate_css_assets = config["validation"].get("validate_css_assets", True)
    if validate_css_assets or validate_external_links:
        css_url = re.compile(r"url\(\s*['\"]?([^)'\"]+)['\"]?\s*\)|@import\s+['\"]([^'\"]+)['\"]", re.I)
        for css in (p for p in files if p.suffix.lower() == ".css"):
            try:
                text = css.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                if validate_css_assets:
                    errors.append(f"Cannot read CSS {css.relative_to(site_root)}")
                continue
            for match in css_url.finditer(text):
                ref = match.group(1) or match.group(2)
                parsed_ref = urlparse(ref)
                if parsed_ref.scheme in {"http", "https"} or ref.startswith("//"):
                    if validate_external_links:
                        external = parsed_ref if parsed_ref.scheme else urlparse("https:" + ref)
                        host = (external.hostname or "").lower()
                        if not allowed_external_hosts or (host not in allowed_external_hosts and "*" not in allowed_external_hosts):
                            errors.append(
                                f"External CSS host is not allowed in {css.relative_to(site_root)}: {external.hostname}"
                            )
                    continue
                if not validate_css_assets:
                    continue
                if parsed_ref.scheme == "data" or ref.startswith("#"):
                    continue
                if parsed_ref.scheme:
                    errors.append(f"Unsupported CSS URL scheme in {css.relative_to(site_root)}: {ref}")
                    continue
                path = unquote(parsed_ref.path).replace("\\", "/")
                if path.startswith("/"):
                    rooted = path.lstrip("/")
                    base_path = _site_base_path(config).strip("/")
                    if base_path and (rooted == base_path or rooted.startswith(base_path + "/")):
                        rooted = rooted[len(base_path):].lstrip("/")
                    target = (site_root / rooted).resolve()
                else:
                    target = (css.parent / path).resolve()
                if not target.is_relative_to(site_root.resolve()) or not target.is_file():
                    errors.append(f"Broken CSS asset: {css.relative_to(site_root)} -> {ref}")
    return errors


def _redirect_html(title: str, url: str) -> str:
    safe_title = (title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    safe_url = url.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
    return ("<!doctype html><html><head><meta charset=\"utf-8\"><title>" + safe_title +
            "</title><meta http-equiv=\"refresh\" content=\"0;url=" + safe_url +
            "\"></head><body><p>Continue to <a href=\"" + safe_url + "\">" + safe_title + "</a>.</p></body></html>")


def _site_public_url(config: dict[str, Any], relative_path: str) -> str:
    """Build a public/canonical URL using the configured origin and base path.

    `relative_path` is always a path inside the generated site tree.  The
    returned URL therefore includes the GitHub Pages repository prefix when
    one is configured, regardless of whether the canonical origin is the
    normal site origin or a separate custom-domain origin.
    """
    site = config["site"]
    origin = str(site.get("canonical_base_url") or site.get("base_url", "")).rstrip("/")
    base_path = _site_base_path(config).strip("/")
    relative = str(relative_path).replace("\\", "/").lstrip("/")
    suffix = "/".join(part for part in (base_path, relative) if part)
    return f"{origin}/{suffix}" if suffix else origin + "/"


def _site_base_path(config: dict[str, Any]) -> str:
    """Return the normalized URL path prefix for this published site."""
    raw = str(config.get("site", {}).get("base_path", "")).replace("\\", "/").strip("/")
    return "/" + raw if raw else ""


def _site_public_path(config: dict[str, Any], path: str) -> str:
    """Prefix a root-relative URL path with the configured site base path.

    Relative URLs, fragments, query-only URLs, external URLs and protocol-
    relative URLs are intentionally left alone.  A URL already carrying the
    configured prefix is also left alone, making this operation idempotent.
    """
    base_path = _site_base_path(config)
    if not base_path:
        return path
    decoded = html_unescape(path)
    # Do not reinterpret protocol-relative URLs as local paths.
    if decoded.startswith("//") or decoded.startswith("\\\\"):
        return path
    if decoded.startswith("\\"):
        decoded = "/" + decoded.lstrip("\\")
    parsed = urlsplit(decoded)
    if parsed.scheme or parsed.netloc:
        return path
    normalized_path = parsed.path.replace("\\", "/")
    if not normalized_path.startswith("/"):
        return path
    existing_path = normalized_path
    if existing_path == base_path or existing_path.startswith(base_path + "/"):
        return path
    prefixed_path = base_path + existing_path
    rewritten = urlunsplit((parsed.scheme, parsed.netloc, prefixed_path, parsed.query, parsed.fragment))
    return rewritten


_HTML_URL_ATTRIBUTE = re.compile(
    r"(?P<prefix>(?<![\w:-])(?:href|src|poster|action|formaction|cite|background|manifest|data|xlink:href)\s*=\s*)"
    r"(?:(?P<quote>[\"'])(?P<quoted>.*?)(?P=quote)|(?P<unquoted>[^\s>]+))",
    re.IGNORECASE,
)
_HTML_SRCSET_ATTRIBUTE = re.compile(
    r"(?P<prefix>(?<![\w:-])srcset\s*=\s*)(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
    re.IGNORECASE,
)
_HTML_STYLE_ATTRIBUTE = re.compile(
    r"(?P<prefix>(?<![\w:-])style\s*=\s*)(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
    re.IGNORECASE,
)
_CSS_URL = re.compile(r"url\(\s*(?P<quote>[\"']?)(?P<url>[^)\"']+?)(?P=quote)\s*\)", re.IGNORECASE)
_CSS_IMPORT = re.compile(r"(?P<prefix>@import\s+)(?P<quote>[\"'])(?P<url>/[^\"']+)(?P=quote)", re.IGNORECASE)


def _rewrite_srcset(value: str, config: dict[str, Any]) -> str:
    # A srcset URL ends at whitespace or a candidate separator.  Commas in
    # URL paths should be percent-encoded by producers, as required by the
    # srcset grammar; data URLs are not modified by this matcher.
    candidate = re.compile(r"(^|,\s*)(/[^,\s]+)")
    def rewrite_candidate(match: re.Match[str]) -> str:
        original = match.group(2)
        rewritten = _site_public_path(config, original)
        return match.group(1) + (original if rewritten == original else rewritten)
    return candidate.sub(rewrite_candidate, value)


def _rewrite_css_urls(css: str, config: dict[str, Any]) -> str:
    def rewrite_url(match: re.Match[str]) -> str:
        value = match.group("url").strip()
        rewritten = _site_public_path(config, value)
        if rewritten == value:
            return match.group(0)
        quote = match.group("quote")
        return "url(" + quote + rewritten + quote + ")"

    css = _CSS_URL.sub(rewrite_url, css)
    css = _CSS_IMPORT.sub(
        lambda match: match.group("prefix") + match.group("quote")
        + _site_public_path(config, match.group("url")) + match.group("quote"),
        css,
    )
    return css


def _rewrite_html_start_tag(start_tag: str, config: dict[str, Any]) -> str:
    def rewrite_url_attribute(match: re.Match[str]) -> str:
        if match.group("quote"):
            original = match.group("quoted")
            rewritten = _site_public_path(config, original)
            if rewritten == original:
                return match.group(0)
            return match.group("prefix") + match.group("quote") + html_escape(rewritten, quote=True) + match.group("quote")
        original = match.group("unquoted")
        rewritten = _site_public_path(config, original)
        if rewritten == original:
            return match.group(0)
        return match.group("prefix") + html_escape(rewritten, quote=True)

    updated = _HTML_URL_ATTRIBUTE.sub(rewrite_url_attribute, start_tag)
    def rewrite_srcset_attribute(match: re.Match[str]) -> str:
        rewritten = _rewrite_srcset(match.group("value"), config)
        if rewritten == match.group("value"):
            return match.group(0)
        return match.group("prefix") + match.group("quote") + html_escape(rewritten, quote=True) + match.group("quote")
    updated = _HTML_SRCSET_ATTRIBUTE.sub(rewrite_srcset_attribute, updated)
    updated = _HTML_STYLE_ATTRIBUTE.sub(
        lambda match: match.group("prefix") + match.group("quote")
        + html_escape(_rewrite_css_urls(html_unescape(match.group("value")), config), quote=True)
        + match.group("quote"),
        updated,
    )

    # Meta refresh URLs are navigation targets too, although they are stored
    # inside the `content` attribute rather than a URL-named attribute.
    if re.match(r"<\s*meta\b", updated, re.IGNORECASE) and re.search(
        r"\bhttp-equiv\s*=\s*(?:[\"']\s*)?refresh", updated, re.IGNORECASE
    ):
        content_attr = re.compile(
            r"(?P<prefix>(?<![\w:-])content\s*=\s*)(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
            re.IGNORECASE,
        )
        refresh_url = re.compile(r"(?P<prefix>url\s*=\s*)(?P<quote>[\"']?)(?P<url>[^;\s\"']+)(?P=quote)", re.IGNORECASE)
        def rewrite_refresh(match: re.Match[str]) -> str:
            raw_value = html_unescape(match.group("value"))
            value = refresh_url.sub(
                lambda item: item.group("prefix") + item.group("quote")
                + _site_public_path(config, item.group("url")) + item.group("quote"),
                raw_value,
            )
            return match.group("prefix") + match.group("quote") + html_escape(value, quote=True) + match.group("quote")
        updated = content_attr.sub(rewrite_refresh, updated)
    return updated


class _HTMLBasePathRewriter(HTMLParser):
    """Locate start tags while preserving every unrelated byte of source HTML."""

    def __init__(self, source: str, config: dict[str, Any]):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.config = config
        self.line_offsets = [0]
        self.line_offsets.extend(match.end() for match in re.finditer("\n", source))
        self.replacements: list[tuple[int, int, str]] = []

    def _record(self) -> None:
        raw = self.get_starttag_text()
        if not raw:
            return
        line, column = self.getpos()
        start = self.line_offsets[line - 1] + column
        rewritten = _rewrite_html_start_tag(raw, self.config)
        if rewritten != raw:
            self.replacements.append((start, start + len(raw), rewritten))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._record()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._record()


def _rewrite_root_relative_site_urls(site_root: Path, config: dict[str, Any]) -> int:
    """Apply GitHub Pages `base_path` to root-relative HTML and CSS references.

    This runs after component copying and link adaptation, so it covers both
    generated navigation and upstream-generated documentation.  It is a
    no-op for domain-root deployments and is safe to run more than once.
    Returns the number of rewritten URL references (not the number of files).
    """
    if not _site_base_path(config):
        return 0
    rewritten_count = 0
    html_extensions = {".html", ".htm", ".xhtml", ".svg"}
    for page in site_root.rglob("*"):
        if not page.is_file() or page.suffix.lower() not in html_extensions:
            continue
        source = page.read_text(encoding="utf-8")
        parser = _HTMLBasePathRewriter(source, config)
        parser.feed(source)
        parser.close()
        updated = source
        for start, end, replacement in reversed(parser.replacements):
            updated = updated[:start] + replacement + updated[end:]

        # CSS embedded in style elements is not represented as an HTML start
        # tag attribute, so rewrite it separately while retaining its markup.
        style_block = re.compile(r"(?P<open><style\b[^>]*>)(?P<css>.*?)(?P<close></style\s*>)", re.IGNORECASE | re.DOTALL)
        updated = style_block.sub(
            lambda match: match.group("open") + _rewrite_css_urls(match.group("css"), config)
            + match.group("close"), updated,
        )
        if updated != source:
            # Count references rather than pages for diagnostics and tests.
            rewritten_count += sum(1 for start, end, _ in parser.replacements)
            page.write_text(updated, encoding="utf-8")

    for css_file in site_root.rglob("*.css"):
        if not css_file.is_file():
            continue
        source = css_file.read_text(encoding="utf-8")
        updated = _rewrite_css_urls(source, config)
        if updated != source:
            rewritten_count += len(_CSS_URL.findall(source)) + len(_CSS_IMPORT.findall(source))
            css_file.write_text(updated, encoding="utf-8")
    return rewritten_count


def _inject_noindex(site_root: Path) -> None:
    """Ensure every HTML file in the final tree is explicitly noindex/nofollow."""
    robots = '<meta name="robots" content="noindex,nofollow">'
    present = re.compile(
        r'<meta\b(?=[^>]*\bname\s*=\s*["\']robots["\'])'
        r'(?=[^>]*\bcontent\s*=\s*["\'][^"\']*noindex)[^>]*>', re.I
    )
    head = re.compile(r"<head\b[^>]*>", re.I)
    html = re.compile(r"<html\b[^>]*>", re.I)
    for page in site_root.rglob("*"):
        if not page.is_file() or page.suffix.lower() not in {".html", ".htm"}:
            continue
        content = page.read_text(encoding="utf-8")
        if present.search(content):
            continue
        match = head.search(content)
        if match:
            content = content[:match.end()] + robots + content[match.end():]
        else:
            match = html.search(content)
            if match:
                content = content[:match.end()] + "<head>" + robots + "</head>" + content[match.end():]
            else:
                content = "<!doctype html><html><head>" + robots + "</head><body>" + content + "</body></html>"
        page.write_text(content, encoding="utf-8")


def _component_route(root: Path, config: dict[str, Any], component: dict[str, Any]) -> Path:
    site = config["site"]
    values = {
        "components_root": site["components_root"].strip("/"),
        "version": component.get("version") or site["version"],
        "locale": component.get("locale") or config["project"]["locale"],
        "route": component["route"].strip("/"),
        "component_id": component["id"],
    }
    template = site.get("component_path_template", "{components_root}/{version}/{route}")
    try:
        relative = template.format_map(values)
    except KeyError as exc:
        raise BuildError(f"Unknown component_path_template variable: {exc}") from exc
    return safe_child(root, relative)


def _version_index_path(root: Path, config: dict[str, Any], locale: str, version: str) -> Path:
    site = config["site"]
    values = {"components_root": site["components_root"].strip("/"), "locale": locale, "version": version}
    template = site.get("version_index_path_template", "{components_root}/{version}/index.html")
    try:
        relative = template.format_map(values)
    except KeyError as exc:
        raise BuildError(f"Unknown version_index_path_template variable: {exc}") from exc
    return safe_child(root, relative)


def _copy_component_output(source_root: Path, component: dict[str, Any], staging: Path, config: dict[str, Any]) -> None:
    site = config["site"]
    archive_limits = config["validation"]
    route = _component_route(staging, config, component)
    if route.exists():
        raise BuildError(f"Two components map to the same route: {component['route']}")
    route.parent.mkdir(parents=True, exist_ok=True)
    out_rel = component["output_path"]
    output = safe_child(source_root, out_rel)
    if not output.exists() or output.is_symlink():
        raise BuildError(f"Component {component['id']} output is missing or unsafe: {output}")
    kind = component.get("output_kind", "directory")
    if kind == "directory":
        if not output.is_dir(): raise BuildError(f"Component {component['id']} expected a directory output")
        shutil.copytree(output, route, symlinks=True, copy_function=_copy_regular_file_nofollow)
        symlink_errors = _site_symlink_errors(route)
        if symlink_errors:
            raise BuildError(f"Symlink in component output {component['id']}: " + "; ".join(symlink_errors[:20]))
    elif kind == "file":
        if not output.is_file(): raise BuildError(f"Component {component['id']} expected a file output")
        route.mkdir(parents=True)
        destination_file = route / component.get("index_file", "index.html")
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        _copy_regular_file_nofollow(output, destination_file)
    elif kind in {"zip", "tar"}:
        if not output.is_file(): raise BuildError(f"Component {component['id']} expected an archive output")
        temp = Path(tempfile.mkdtemp(prefix=".component-extract-", dir=staging))
        try:
            extraction = temp / "extracted"
            staged_archive = temp / ("component-output.zip" if kind == "zip" else "component-output.tar")
            _copy_regular_file_nofollow(output, staged_archive)
            if kind == "zip":
                extract_zip(staged_archive, extraction, max_bytes=archive_limits["max_site_bytes"], max_files=archive_limits["max_files"], max_ratio=archive_limits.get("max_archive_ratio", 1000))
            else:
                extract_tar(staged_archive, extraction, max_bytes=archive_limits["max_site_bytes"], max_files=archive_limits["max_files"], max_ratio=archive_limits.get("max_archive_ratio", 1000))
            archive_root = component.get("archive_root", ".")
            extracted_root = safe_child(extraction, archive_root, allow_dot=True)
            if not extracted_root.is_dir(): raise BuildError(f"Configured archive_root is not a directory: {archive_root}")
            shutil.copytree(extracted_root, route, symlinks=True, copy_function=_copy_regular_file_nofollow)
            symlink_errors = _site_symlink_errors(route)
            if symlink_errors:
                raise BuildError(f"Symlink in extracted component output {component['id']}: " + "; ".join(symlink_errors[:20]))
        finally:
            _remove_tree_strict(temp, retries=1)
    else:
        raise BuildError(f"Unsupported output_kind {kind!r} for component {component['id']}")
    for required in component.get("required_output_files", []):
        required_path = safe_child(route, required)
        if not required_path.is_file():
            raise BuildError(f"Component {component['id']} is missing required output file {required!r}")


def _make_fallback(component: dict[str, Any], staging: Path, config: dict[str, Any]) -> None:
    site = config["site"]
    fallback = component["fallback"]
    mode = fallback["mode"]
    if mode == "omit": return
    route = _component_route(staging, config, component)
    if route.exists(): return
    route.mkdir(parents=True, exist_ok=True)
    index = route / component.get("index_file", "index.html")
    index.parent.mkdir(parents=True, exist_ok=True)
    if mode in {"redirect", "inherit"}:
        parsed = urlparse(fallback["url"])
        allowed_schemes = {str(x).lower() for x in config["validation"].get("validate_redirect_schemes", ["https", "http"])}
        if parsed.scheme not in allowed_schemes or not parsed.netloc:
            raise BuildError(f"Component {component['id']} fallback URL has unsupported or malformed scheme")
        index.write_text(_redirect_html(component["title"], fallback["url"]), encoding="utf-8")
    elif mode == "stub":
        index.write_text("<!doctype html><html><head><meta charset=\"utf-8\"><title>" + html_escape(component["title"]) + "</title></head><body><h1>" + html_escape(component["title"]) + "</h1><p>This component is not included in this publication.</p></body></html>", encoding="utf-8")
    elif mode == "error":
        raise BuildError(f"Component {component['id']} is not selected and fallback mode is {mode!r}")


def _generate_index(staging: Path, config: dict[str, Any], components: list[dict[str, Any]], publisher_root: Path) -> None:
    site = config["site"]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for component in components:
        locale = component.get("locale") or config["project"]["locale"]
        version = component.get("version") or site["version"]
        groups.setdefault((locale, version), []).append(component)

    for (locale, version), grouped in groups.items():
        index_path = _version_index_path(staging, config, locale, version)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        links = []
        navigation = site.get("navigation")
        if navigation:
            for item in sorted(navigation, key=lambda x: x.get("order", 0)):
                if item.get("group") and item["group"] not in {locale, version, f"{locale}:{version}"}:
                    continue
                values = {"locale": locale, "version": version, "components_root": site["components_root"]}
                href = item["href"].format_map(values)
                links.append(f'<li><a href="{html_escape(href, quote=True)}">{html_escape(item["label"])}</a></li>')
        else:
            for component in grouped:
                if component["fallback"]["mode"] == "omit" and not component.get("_selected"):
                    continue
                route_path = _component_route(staging, config, component)
                relative_href = os.path.relpath(route_path, index_path.parent).replace(os.sep, "/")
                if site.get("trailing_slash", True):
                    relative_href = relative_href.rstrip("/") + "/"
                else:
                    relative_href = relative_href.rstrip("/") + "/" + component.get("index_file", "index.html")
                links.append(f'<li><a href="{html_escape(relative_href, quote=True)}">{html_escape(component["title"])}</a></li>')
        robots = '<meta name="robots" content="noindex,nofollow">' if site.get("robots") == "noindex" else ""
        canonical_base = site.get("canonical_base_url") or site.get("base_url")
        canonical = ""
        if canonical_base:
            canonical_url = _site_public_url(config, index_path.relative_to(staging).as_posix())
            canonical = f'<link rel="canonical" href="{html_escape(canonical_url, quote=True)}">'
        description = config["project"].get("description", "")
        description_tag = f'<meta name="description" content="{html_escape(description, quote=True)}">' if description else ""
        favicon = config["project"].get("favicon", "")
        favicon_tag = f'<link rel="icon" href="{html_escape(favicon, quote=True)}">' if favicon else ""
        logo = config["project"].get("logo", "")
        logo_html = f'<img class="project-logo" src="{html_escape(logo, quote=True)}" alt="">' if logo else ""
        homepage = config["project"].get("homepage_url", "")
        homepage_html = f'<p><a href="{html_escape(homepage, quote=True)}">Project home</a></p>' if homepage else ""
        html = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>" + html_escape(config["project"]["title"]) +
                "</title>" + description_tag + robots + canonical + favicon_tag + "</head><body>" + logo_html + "<h1>" + html_escape(config["project"]["title"]) +
                "</h1>" + homepage_html + "<ul>" + "".join(links) + "</ul></body></html>")
        index_path.write_text(html, encoding="utf-8")

    default_locale = site.get("default_locale", config["project"]["locale"])
    default_version = site.get("default_version", site["version"])
    root_target = site.get("root_index_target")
    if not root_target and site.get("default_component"):
        default_component = next((x for x in components if x["id"] == site["default_component"]), None)
        if default_component is None:
            raise BuildError(f"site.default_component references unknown component {site['default_component']!r}")
        target_path = _component_route(Path("."), config, default_component)
        if site.get("trailing_slash", True):
            root_target = target_path.as_posix().rstrip("/") + "/"
        else:
            root_target = target_path.as_posix().rstrip("/") + "/" + default_component.get("index_file", "index.html")
    if not root_target:
        default_group_exists = any(locale == default_locale and version == default_version for locale, version in groups)
        if not default_group_exists:
            raise BuildError(f"Default locale/version {default_locale!r}/{default_version!r} has no generated index")
        root_target = _version_index_path(Path("."), config, default_locale, default_version).as_posix()
    if site.get("default_component"):
        default_component = next(x for x in components if x["id"] == site["default_component"])
        if not default_component.get("_selected") and default_component["fallback"]["mode"] == "omit":
            raise BuildError("site.default_component is not selected and its fallback mode is omit")
    root_index = safe_child(staging, "index.html")
    root_index.write_text(_redirect_html(config["project"]["title"], root_target), encoding="utf-8")
    (staging / ".nojekyll").write_text("", encoding="utf-8")
    not_found_path = site.get("not_found_path")
    if not_found_path:
        not_found = safe_child(staging, not_found_path)
        not_found.parent.mkdir(parents=True, exist_ok=True)
        not_found.write_text("<!doctype html><html><head><meta charset=\"utf-8\"><title>Not found</title></head><body><h1>Not found</h1><p>" + html_escape(config["project"]["title"]) + "</p></body></html>", encoding="utf-8")

def _copy_static_assets(staging: Path, publisher_root: Path, config: dict[str, Any]) -> None:
    for asset in config["site"].get("static_assets", []):
        source = safe_child(publisher_root, asset["source"])
        destination = safe_child(staging, asset["destination"])
        if not source.exists() or source.is_symlink():
            raise BuildError(f"Configured static asset source is missing or unsafe: {source}")
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=False, symlinks=True,
                            copy_function=_copy_regular_file_nofollow)
            symlink_errors = _site_symlink_errors(destination)
            if symlink_errors:
                raise BuildError(f"Symlink inside configured static asset source {source}: " + "; ".join(symlink_errors[:20]))
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            _copy_regular_file_nofollow(source, destination)


def _rewrite_links(staging: Path, config: dict[str, Any], selected: list[dict[str, Any]], source_roots: dict[str, Path]) -> tuple[list[str], list[dict[str, str]]]:
    global_links = config.get("links", {})
    global_edit = global_links.get("edit", {"mode": "inherit"})
    global_link_policies = {
        name: global_links[name] for name in ("issues", "navigation") if name in global_links
    }
    global_communication = config.get("communication", {})
    targets = {x["id"]: x for x in config.get("authoring_targets", [])}
    errors: list[str] = []
    link_report: list[dict[str, str]] = []
    component_by_prefix = {
        _component_route(Path("/publisher-site"), config, c).relative_to(Path("/publisher-site")).as_posix(): c
        for c in selected
    }

    provenance_by_component: dict[str, dict[str, Any]] = {}
    for comp in selected:
        marker = comp.get("provenance_file")
        if not marker:
            continue
        route = _component_route(staging, config, comp)
        provenance_path = safe_child(route, marker)
        if not provenance_path.is_file() or provenance_path.is_symlink():
            raise BuildError(f"Component {comp['id']} declares missing or unsafe provenance_file: {marker}")
        try:
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise BuildError(f"Invalid provenance JSON in {comp['id']}: {exc}") from exc
        if not isinstance(provenance, dict) or set(provenance) - {"files", "sections", "schema_version"}:
            raise BuildError(f"Provenance file for {comp['id']} must contain only files/sections/schema_version mappings")
        if provenance.get("schema_version", 1) not in {1, 2}:
            raise BuildError(f"Unsupported provenance schema version in {comp['id']}")
        for map_name in ("files", "sections"):
            mapping = provenance.get(map_name, {})
            if not isinstance(mapping, dict):
                raise BuildError(f"Provenance {map_name} in {comp['id']} must be an object")
            for key, item in mapping.items():
                if not isinstance(key, str) or not isinstance(item, dict):
                    raise BuildError(f"Invalid provenance entry in {comp['id']}:{map_name}:{key}")
                source_id = item.get("source_id", comp["source_id"])
                if source_id not in source_roots:
                    raise BuildError(f"Provenance entry references unknown source_id {source_id!r}")
                source_file = item.get("source_file")
                if not isinstance(source_file, str) or not source_file:
                    raise BuildError(f"Provenance entry is missing source_file: {comp['id']}:{key}")
                source_path = safe_child(source_roots[source_id], source_file)
                if not source_path.is_file() or source_path.is_symlink():
                    raise BuildError(f"Provenance source file is missing or unsafe: {source_id}:{source_file}")
        provenance_by_component[comp["id"]] = provenance
        provenance_path.unlink()

    component_counts: dict[str, dict[str, int]] = {}
    for page in staging.rglob("*.html"):
        rel = page.relative_to(staging).as_posix()
        component = None
        page_rel = page.name
        for relative_prefix, candidate in component_by_prefix.items():
            if rel == relative_prefix or rel.startswith(relative_prefix + "/"):
                component = candidate
                tail = rel[len(relative_prefix):].lstrip("/")
                page_rel = tail or page.name
                break
        try:
            page_text = page.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            errors.append(f"{rel}: cannot read HTML for link rewriting: {exc}")
            continue

        component_overrides = (component or {}).get("link_overrides", {})
        component_edit = component_overrides.get("edit")
        # A component-level `inherit` means inherit the global setting; it must
        # not silently disable a global override. Explicit override/disable wins.
        if not component_edit or component_edit.get("mode") == "inherit":
            edit = global_edit
        else:
            edit = {**global_edit, **component_edit}
        communication = dict(global_communication)
        communication.update(component_overrides.get("communication", {}))
        effective_link_policies: dict[str, dict[str, Any]] = {}
        for link_class in ("issues", "navigation"):
            component_policy = component_overrides.get(link_class)
            if not component_policy or component_policy.get("mode") == "inherit":
                if link_class in global_link_policies:
                    effective_link_policies[link_class] = global_link_policies[link_class]
            else:
                effective_link_policies[link_class] = {
                    **global_link_policies.get(link_class, {"mode": "inherit"}),
                    **component_policy,
                }
        source_id = component["source_id"] if component else ""

        adapter = (component or {}).get("link_adapter")
        if adapter:
            if adapter != "keycloak_asciidoc":
                errors.append(f"{rel}: unsupported component link_adapter {adapter!r}")
                continue
            target_id = edit.get("target_id")
            target = targets.get(target_id)
            if edit.get("mode", "inherit") == "override" and not target:
                errors.append(f"{rel}: Keycloak AsciiDoc adapter requires a configured edit target_id")
                continue
            if target and target.get("source_id") not in (None, source_id):
                errors.append(f"{rel}: Keycloak authoring target is configured for a different source_id")
                continue
            source_config = next((item for item in config.get("sources", []) if item.get("id") == source_id), None)
            source_vcs = (source_config or {}).get("vcs", {})
            try:
                page_text, _converted = transform_keycloak_asciidoc_edit_links(
                    page_text, source_vcs, source_id,
                    link_policies=effective_link_policies,
                    communication_channels=set(communication),
                    page_rel=page_rel,
                )
                page.write_text(page_text, encoding="utf-8")
            except (LinkResolutionError, OSError) as exc:
                errors.append(f"{rel}: Keycloak AsciiDoc link adaptation failed: {exc}")
                continue

        if "data-publisher-link" not in page_text and "publisher-link-" not in page_text:
            continue

        title = (component or {}).get("title", config["project"]["title"])
        locale = (component or {}).get("locale") or config["project"]["locale"]
        version = (component or {}).get("version") or config["site"]["version"]
        page_url = _site_public_url(config, rel)
        template_context = {
            "project_id": config["project"]["id"],
            "project_title": config["project"]["title"],
            "component_id": (component or {}).get("id", ""),
            "component_title": title,
            "component_locale": locale,
            "component_version": version,
            "site_locale": locale,
            "site_version": version,
            "page_title": title,
            "page_url": page_url,
            "page_path": rel,
        }
        component_provenance = provenance_by_component.get(component["id"], {}) if component else {}
        page_report: list[dict[str, str]] = []
        err = rewrite_html_file(
            page, edit=edit, targets=targets, communication=communication,
            link_policies=effective_link_policies,
            source_id=source_id, page_rel=page_rel, provenance=component_provenance,
            source_roots=source_roots,
            unresolved_policy=edit.get("unresolved_policy", config["validation"].get("unresolved_edit_policy", "fail")),
            link_report=page_report, template_context=template_context,
        )
        errors.extend(f"{rel}: {e}" for e in err)
        for item in page_report:
            report_item = {**item, "page": rel, "component": (component or {}).get("id", "")}
            link_report.append(report_item)
            if component:
                counts = component_counts.setdefault(component["id"], {})
                counts[item["channel"]] = counts.get(item["channel"], 0) + 1

    def check_required_markers(scope: str, edit_settings: dict[str, Any], channels: dict[str, Any],
                               link_policies: dict[str, Any]) -> None:
        counts = component_counts.get(scope, {}) if scope else {}
        if edit_settings.get("mode") in {"override", "disable"} and edit_settings.get("require_markers", True) and counts.get("edit", 0) == 0:
            errors.append(f"{scope or 'global'}: edit link configuration requires an edit marker but none was found")
        for link_class, settings in link_policies.items():
            if settings.get("mode") in {"override", "disable"} and settings.get("require_markers", True) and counts.get(link_class, 0) == 0:
                errors.append(f"{scope or 'global'}: links.{link_class} requires a matching link but none was found")
        for channel, settings in channels.items():
            if settings.get("mode") in {"override", "disable"} and settings.get("require_markers", True) and counts.get(channel, 0) == 0:
                errors.append(f"{scope or 'global'}: communication.{channel} requires a marker but none was found")

    # Validate per-component overrides independently so a marker in one component cannot
    # accidentally satisfy another component's required marker contract.
    for comp in selected:
        overrides = comp.get("link_overrides", {})
        component_edit = overrides.get("edit")
        effective_edit = (global_edit if not component_edit or component_edit.get("mode") == "inherit"
                          else {**global_edit, **component_edit})
        effective_link_policies = {}
        for link_class in ("issues", "navigation"):
            component_policy = overrides.get(link_class)
            if not component_policy or component_policy.get("mode") == "inherit":
                if link_class in global_link_policies:
                    effective_link_policies[link_class] = global_link_policies[link_class]
            else:
                effective_link_policies[link_class] = {
                    **global_link_policies.get(link_class, {"mode": "inherit"}),
                    **component_policy,
                }
        check_required_markers(comp["id"], effective_edit,
                               {**global_communication, **overrides.get("communication", {})},
                               effective_link_policies)
    return errors, link_report

def _replace_directory_from_staging(staging: Path, destination: Path, *, retries: int, delay: float) -> None:
    """Install a complete staged tree without rolling back to a possibly partial backup.

    The old directory is first renamed aside, then the staged directory is installed.
    If installation fails, the still-untouched backup is restored. Once installation
    succeeds, the new directory is the committed version: backup cleanup failure must
    never move a possibly half-deleted backup back into the live destination.
    """
    backup = destination.with_name(destination.name + f".backup-{uuid.uuid4().hex}")
    destination.rename(backup)
    try:
        staging.rename(destination)
    except Exception as install_error:
        try:
            if destination.exists() or destination.is_symlink():
                raise BuildError(
                    f"Replacement did not complete cleanly; previous output remains at {backup} "
                    f"and an unexpected destination exists at {destination}"
                )
            backup.rename(destination)
        except Exception as restore_error:
            raise BuildError(
                f"Could not install staged output ({install_error}); previous output remains at "
                f"backup path {backup} because restoration also failed ({restore_error})"
            ) from restore_error
        raise BuildError(
            f"Could not install staged output at {destination}; previous output was restored: {install_error}"
        ) from install_error

    try:
        _remove_tree_strict(backup, retries=retries, delay=delay)
    except Exception as cleanup_error:
        raise BuildError(
            f"New output is active at {destination}, but cleanup of the previous backup failed. "
            f"Inspect the remaining backup path {backup} before removing it: {cleanup_error}"
        ) from cleanup_error


def _commit_output(staging: Path, output: Path, replace: bool) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        raise BuildError(f"Refusing to replace a symlink as site output: {output}")
    if output.exists():
        if not replace:
            raise BuildError(f"Refusing to overwrite existing site output: {output}; use --replace-output after verifying its contents")
        _replace_directory_from_staging(staging, output, retries=2, delay=0.15)
    else:
        staging.rename(output)


def build(config_path: Path, *, selected_ids: list[str] | None = None,
          profiles: list[str] | None = None, replace_output: bool = False,
          publisher_ref_override: str | None = None) -> dict[str, Any]:
    config_path = config_path.resolve()
    config = load_config(config_path, profiles)
    output = safe_child(config_path.parent, config["site"]["output_directory"])
    timeout = config["workspace"].get("lock_timeout_seconds", 60)
    with BuildLock(output, timeout):
        return _build_loaded(config_path, config, selected_ids=selected_ids,
                             replace_output=replace_output, publisher_ref_override=publisher_ref_override)


def _build_loaded(config_path: Path, config: dict[str, Any], *, selected_ids: list[str] | None = None,
                  replace_output: bool = False, publisher_ref_override: str | None = None) -> dict[str, Any]:
    config_path = config_path.resolve()
    config_dir = config_path.parent
    plan = resolve_build_plan(config, selected_ids)
    chosen_ids = plan["chosen_ids"]
    chosen = plan["components"]

    output = safe_child(config_dir, config["site"]["output_directory"])
    if output == config_dir or output == config_dir / ".git" or not output.resolve().is_relative_to(config_dir):
        raise BuildError("site.output_directory must be a safe child of the configuration directory")
    _guard_not_git_metadata(output, config_dir, label="site.output_directory")
    _guard_not_tracked_output(output, config_dir, label="site.output_directory")
    if output.exists() and not replace_output:
        raise BuildError(f"Refusing to overwrite existing site output: {output}; use --replace-output after verifying its contents")

    workspace_raw = config["workspace"]["temp_root"]
    if workspace_raw.startswith("${") and workspace_raw.endswith("}"):
        env_name = workspace_raw[2:-1]
        if env_name not in os.environ:
            raise BuildError(f"workspace.temp_root environment variable {env_name!r} is not set")
        workspace_root = Path(os.environ[env_name]).expanduser().resolve()
    else:
        workspace_root = Path(workspace_raw).expanduser()
        if not workspace_root.is_absolute(): workspace_root = (config_dir / workspace_root)
        workspace_root = workspace_root.resolve()
    _guard_not_git_metadata(workspace_root, config_dir, label="workspace.temp_root")
    workspace_root.mkdir(parents=True, exist_ok=True)
    run_root = Path(tempfile.mkdtemp(prefix="documentation-publisher-", dir=workspace_root))
    publisher_clone = run_root / "publisher-worktree"
    staging: Path | None = None
    completed = False
    cleanup_error = None
    manifest: dict[str, Any] = {
        "schema_version": 2, "run_id": run_root.name, "project": {k: config["project"][k] for k in ("id", "title", "description", "locale") if k in config["project"]},
        "selection": chosen_ids, "sources": [], "tasks": [], "outputs": [], "status": "running"
    }
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
        env = os.environ.copy()
        pub_url = resolve_local_or_url(config["publisher"]["clone_url"], config_dir)
        pub_env, _ = make_askpass_env(config["publisher"].get("auth"), env.copy(), run_root)
        publisher_ref = publisher_ref_override or config["publisher"]["ref"]
        publisher_sha = clone_publisher(pub_url, publisher_ref, publisher_clone, pub_env,
                                        timeout=int(config["publisher"].get("clone_timeout_seconds", 1800)))
        run_git(["config", "user.name", config["workspace"]["git_user_name"]], cwd=publisher_clone, env=pub_env)
        run_git(["config", "user.email", config["workspace"]["git_user_email"]], cwd=publisher_clone, env=pub_env)
        manifest["publisher_commit"] = publisher_sha

        ordered_tasks = plan["tasks"]
        task_source_ids = plan["task_source_ids"]
        required_source_ids = plan["required_source_ids"]

        source_roots: dict[str, Path] = {}
        for source in config["sources"]:
            if source["id"] not in required_source_ids:
                continue
            record = integrate_subtree(publisher_clone, source, config_dir, run_root, env)
            manifest["sources"].append(record)
            base = safe_child(publisher_clone, source["integration"]["prefix"])
            root = safe_child(base, source.get("root", "."), allow_dot=True)
            if not root.is_dir():
                raise BuildError(f"Source {source['id']} root does not exist: {root}")
            source_roots[source["id"]] = root

        for task in ordered_tasks:
            source_id = task_source_ids[task["id"]]
            manifest["tasks"].append(_run_command(task, publisher_clone, source_roots[source_id], run_root, env, source_roots))

        selected_set = {c["id"] for c in chosen}
        for comp in chosen:
            source_root = source_roots[comp["source_id"]]
            _copy_component_output(source_root, comp, staging, config)
            manifest["outputs"].append({"component": comp["id"], "route": comp["route"], "source_id": comp["source_id"]})
        rendered_components = []
        for comp in config["components"]:
            decorated = {**comp, "_selected": comp["id"] in selected_set}
            rendered_components.append(decorated)
            if comp["id"] not in selected_set:
                _make_fallback(comp, staging, config)
        if config["site"].get("generate_index", True):
            _generate_index(staging, config, rendered_components, publisher_clone)
        else:
            (staging / ".nojekyll").write_text("", encoding="utf-8")
            if config["site"].get("not_found_path"):
                not_found = safe_child(staging, config["site"]["not_found_path"])
                not_found.parent.mkdir(parents=True, exist_ok=True)
                not_found.write_text("<!doctype html><html><head><meta charset=\"utf-8\"><title>Not found</title></head><body><h1>Not found</h1></body></html>", encoding="utf-8")

        # Static assets are independent of whether the publisher creates navigation/index pages.
        _copy_static_assets(staging, publisher_clone, config)
        link_errors, link_report = _rewrite_links(staging, config, chosen, source_roots)
        if link_errors:
            raise BuildError("Link rewriting failed:\n" + "\n".join(f" - {x}" for x in link_errors[:100]))
        # GitHub Pages Project Sites are served below a repository path.  A
        # leading slash in upstream HTML/CSS otherwise escapes that prefix and
        # points at the domain root.  Apply the same base-path policy to every
        # generated/copied document after link adaptation and before checking
        # local destinations.
        _rewrite_root_relative_site_urls(staging, config)
        link_counts: dict[str, int] = {}
        for item in link_report:
            link_counts[item["channel"]] = link_counts.get(item["channel"], 0) + 1
        manifest["link_summary"] = link_counts

        if config["site"].get("robots") == "noindex":
            _inject_noindex(staging)

        manifest["status"] = "validated"
        manifest["source_revisions"] = {x["source_id"]: x["source_commit"] for x in manifest["sources"]}
        # Public manifest contains provenance but never repository credentials or complete
        # configuration (which may contain private clone URLs or internal paths).
        manifest["configuration_file"] = config_path.name
        manifest["configuration_sha256"] = __import__("hashlib").sha256(config_path.read_bytes()).hexdigest()
        manifest["sources"] = [{k: v for k, v in item.items() if k != "clone_url"} for item in manifest["sources"]]
        # The build manifest remains part of every successful output for provenance.
        # require_build_manifest controls schema validation, not whether it is emitted.
        manifest_requested = True
        _write_final_build_manifest(staging, manifest)
        # The manifest is the final site file: limits and required_files must be
        # evaluated after it exists, not against the pre-manifest staging tree.
        errors = validate_site(staging, config)
        if config["validation"].get("validate_edit_links", True):
            for item in link_report:
                if item["channel"] == "edit" and item["mode"] == "override" and not item.get("href", "").startswith("https://"):
                    errors.append(f"Edit link is not an HTTPS URL: {item.get('page', '')}")
        if config["validation"].get("validate_communication_links", True):
            for item in link_report:
                if item["channel"] == "email" and item["mode"] == "override" and not item.get("href", "").startswith("mailto:"):
                    errors.append(f"Email link does not use mailto: {item.get('page', '')}")
                if item["channel"] != "email" and item["mode"] == "override" and item.get("href") and not item["href"].startswith("https://"):
                    errors.append(f"Communication link is not HTTPS: {item.get('page', '')}")
        if errors:
            raise BuildError("Site validation failed:\n" + "\n".join(f" - {x}" for x in errors[:100]))

        # The temporary clone, containing all subtrees and remotes, is removed before the site is committed.
        if (config["workspace"].get("cleanup_on_success", True)
                and not config["workspace"].get("keep_on_success", False)):
            try:
                _remove_tree_strict(run_root, config["workspace"].get("cleanup_retries", 1),
                                    float(config["workspace"].get("cleanup_delay_seconds", 0.15)))
            except Exception as exc:
                if config["workspace"].get("fail_on_cleanup_error", True):
                    raise BuildError(f"Build succeeded but workspace cleanup failed: {exc}") from exc
                manifest["cleanup_warning"] = str(exc)
                if manifest_requested:
                    _write_final_build_manifest(staging, manifest)
                    cleanup_validation_errors = validate_site(staging, config)
                    if cleanup_validation_errors:
                        raise BuildError(
                            "Site validation failed after non-fatal cleanup warning:\n"
                            + "\n".join(f" - {item}" for item in cleanup_validation_errors[:100])
                        )
        _commit_output(staging, output, replace_output)
        completed = True
        manifest["status"] = "success"
        manifest["site_output"] = str(output)
        return manifest
    finally:
        if not completed:
            cleanup_enabled = config["workspace"].get("cleanup_on_failure", True) and not config["workspace"].get("keep_failed_workspace", False)
            if cleanup_enabled:
                try:
                    _remove_tree_strict(run_root, config["workspace"].get("cleanup_retries", 1),
                                        float(config["workspace"].get("cleanup_delay_seconds", 0.15)))
                except Exception as exc:
                    cleanup_error = exc
            if staging is not None:
                try:
                    _remove_tree_strict(staging, config["workspace"].get("cleanup_retries", 1),
                                        float(config["workspace"].get("cleanup_delay_seconds", 0.15)))
                except Exception as exc:
                    cleanup_error = cleanup_error or exc
            if cleanup_error and config["workspace"].get("fail_on_cleanup_error", True):
                raise BuildError(f"Build failed and cleanup also failed: {cleanup_error}") from cleanup_error
        else:
            # staging was renamed into the final output directory.
            pass


def _validate_publishing_destination(target: dict[str, Any], config_dir: Path) -> Path:
    candidate = Path(target["output_path"]).expanduser()
    if not candidate.is_absolute():
        candidate = config_dir / candidate
    # Normalize `.` and `..` lexically, but do not dereference the final
    # component. Resolving the whole destination first would hide a symlink
    # from the explicit symlink rejection in the filesystem adapter.
    candidate = Path(os.path.abspath(candidate))
    if candidate.is_symlink():
        raise BuildError(f"Refusing a symlink publishing destination: {candidate}")
    path = candidate.parent.resolve() / candidate.name
    if path.is_symlink():
        raise BuildError(f"Refusing a symlink publishing destination: {path}")
    _guard_not_git_metadata(path, config_dir, label="publishing destination")
    _guard_not_tracked_output(path, config_dir, label="publishing destination")
    if path.exists() and not path.is_dir():
        raise BuildError(f"Publishing destination exists but is not a directory: {path}")
    project_root = config_dir.resolve()
    if project_root.is_relative_to(path):
        raise BuildError("Publishing destination must not be the publisher project directory or one of its parents")
    if not target.get("allow_external_destination", False) and not path.is_relative_to(project_root):
        raise BuildError("Publishing destination is outside the publisher project; set allow_external_destination: true only when intentional")
    if path == project_root or path.is_relative_to(project_root / ".git"):
        raise BuildError("Publishing destination points to a protected publisher path")
    return path


def _ensure_disjoint_trees(source: Path, destination: Path) -> None:
    """Reject source/destination identity and ancestor relationships before copying.

    A staging directory is created beside the destination. If that location is
    inside the source, copytree can recursively copy its own staging tree; if the
    destination contains the source, replacement can remove the source itself.
    """
    source_root = source.resolve()
    destination_root = destination.resolve(strict=False)
    if (source_root == destination_root
            or source_root.is_relative_to(destination_root)
            or destination_root.is_relative_to(source_root)):
        raise BuildError(
            f"Publishing source and destination must be disjoint directories: "
            f"source={source_root}, destination={destination_root}"
        )


def _validate_publishing_copy(path: Path, config: dict[str, Any]) -> None:
    symlink_errors = _site_symlink_errors(path)
    if symlink_errors:
        raise BuildError("Refusing to publish a copied site containing symlinks:\n" +
                         "\n".join(f" - {x}" for x in symlink_errors[:100]))
    if config["publishing"].get("pre_publish_validation", True):
        errors = validate_site(path, config)
        if errors:
            raise BuildError("Copied filesystem site failed validation:\n" +
                             "\n".join(f" - {x}" for x in errors[:100]))


def _non_atomic_copy_tree(source: Path, destination: Path, *, replace_existing: bool,
                          retries: int, delay: float, validator: Callable[[Path], None]) -> None:
    """Copy directly to the destination, but preserve/restore any previous tree on failure.

    This mode is intentionally not gap-free. It must nevertheless never leave a
    partial tree active after a failed copy or validation, and backup cleanup must
    not roll back to a partially deleted old tree.
    """
    if destination.is_symlink():
        raise BuildError(f"Refusing to publish over a symlink: {destination}")
    _ensure_disjoint_trees(source, destination)
    backup: Path | None = None
    if destination.exists():
        if not replace_existing:
            raise BuildError(f"Publishing destination already exists: {destination}")
        backup = destination.with_name(destination.name + f".backup-{uuid.uuid4().hex}")
        destination.rename(backup)
    try:
        shutil.copytree(source, destination, symlinks=True, copy_function=_copy_regular_file_nofollow)
        validator(destination)
    except Exception as publish_error:
        cleanup_error = None
        if destination.exists() or destination.is_symlink():
            try:
                _remove_tree_strict(destination, retries=retries, delay=delay)
            except Exception as exc:
                cleanup_error = exc
        if cleanup_error:
            raise BuildError(
                f"Non-atomic publish failed ({publish_error}) and partial destination cleanup failed ({cleanup_error}); "
                f"previous output, if any, remains at {backup}"
            ) from cleanup_error
        if backup is not None:
            try:
                backup.rename(destination)
            except Exception as restore_error:
                raise BuildError(
                    f"Non-atomic publish failed ({publish_error}); previous output remains at backup path "
                    f"{backup} because restoration failed ({restore_error})"
                ) from restore_error
        raise BuildError(f"Non-atomic publish failed; previous output was restored where applicable: {publish_error}") from publish_error

    if backup is not None:
        try:
            _remove_tree_strict(backup, retries=retries, delay=delay)
        except Exception as cleanup_error:
            raise BuildError(
                f"New output is active at {destination}, but cleanup of the previous backup failed. "
                f"Inspect the remaining backup path {backup} before removing it: {cleanup_error}"
            ) from cleanup_error


def _atomic_copy_tree(source: Path, destination: Path, *, replace_existing: bool, retries: int, delay: float,
                      validator: Callable[[Path], None]) -> None:
    if destination.is_symlink():
        raise BuildError(f"Refusing to publish over a symlink: {destination}")
    _ensure_disjoint_trees(source, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.publishing-", dir=destination.parent))
    _remove_tree_strict(staging, retries=1, delay=delay)
    try:
        # Preserve symlinks during staging rather than dereferencing them. The
        # staged tree is checked before it can become the public destination.
        shutil.copytree(source, staging, symlinks=True, copy_function=_copy_regular_file_nofollow)
        symlink_errors = _site_symlink_errors(staging)
        if symlink_errors:
            raise BuildError("Refusing to publish a staged site containing symlinks:\n" +
                             "\n".join(f" - {x}" for x in symlink_errors[:100]))
        validator(staging)
        if destination.exists():
            if not replace_existing:
                raise BuildError(f"Publishing destination already exists: {destination}")
            _replace_directory_from_staging(staging, destination, retries=retries, delay=delay)
        else:
            staging.rename(destination)
    finally:
        if staging.exists():
            _remove_tree_strict(staging, retries=retries, delay=delay)


def publish(config_path: Path, site_path: Path | None = None, *, profiles: list[str] | None = None) -> dict[str, Any]:
    config_path = config_path.resolve()
    config = load_config(config_path, profiles)
    target_id = config["publishing"]["target_id"]
    target = next(x for x in config["publishing_targets"] if x["id"] == target_id)
    source_candidate = Path(site_path).expanduser() if site_path is not None else (config_path.parent / config["site"]["output_directory"])
    if source_candidate.is_symlink():
        raise BuildError(f"Site directory is a symlink and is unsafe: {source_candidate}")
    source = Path(os.path.abspath(source_candidate))
    if not source.is_dir() or source.is_symlink():
        raise BuildError(f"Site directory is missing or unsafe: {source}")
    symlink_errors = _site_symlink_errors(source)
    if symlink_errors:
        raise BuildError("Refusing to publish a site containing symlinks:\n" + "\n".join(f" - {x}" for x in symlink_errors[:100]))
    if config["publishing"].get("pre_publish_validation", True):
        errors = validate_site(source, config)
        if errors:
            raise BuildError("Pre-publish validation failed:\n" + "\n".join(f" - {x}" for x in errors[:100]))
    adapter = target["adapter"]
    dry_run = bool(config["publishing"].get("dry_run", True))
    if adapter == "artifact":
        result = {"status": "planned" if dry_run else "ready", "adapter": adapter,
                  "site": str(source), "artifact_name": config["publishing"].get("artifact_name", "documentation-site")}
        return result

    destination = _validate_publishing_destination(target, config_path.parent)
    _ensure_disjoint_trees(source, destination)
    if dry_run:
        return {"status": "planned", "adapter": adapter, "site": str(source), "destination": str(destination)}

    timeout = int(target.get("timeout_seconds", config["publishing"].get("timeout_seconds", 600)))
    if adapter == "filesystem":
        atomic = bool(config["publishing"].get("atomic", True))
        replace_existing = bool(target.get("replace_existing", False))
        if atomic:
            _atomic_copy_tree(source, destination, replace_existing=replace_existing,
                              retries=int(config["workspace"].get("cleanup_retries", 2)),
                              delay=float(config["workspace"].get("cleanup_delay_seconds", 0.15)),
                              validator=lambda copied: _validate_publishing_copy(copied, config))
        else:
            _non_atomic_copy_tree(
                source, destination, replace_existing=replace_existing,
                retries=int(config["workspace"].get("cleanup_retries", 2)),
                delay=float(config["workspace"].get("cleanup_delay_seconds", 0.15)),
                validator=lambda copied: _validate_publishing_copy(copied, config),
            )
        return {"status": "published", "adapter": adapter, "destination": str(destination), "atomic": str(atomic).lower()}

    if adapter == "command":
        try:
            argv = [x.format_map({"site_path": str(source), "destination": str(destination), "project_id": config["project"]["id"]}) for x in target.get("argv", [])]
        except KeyError as exc:
            raise BuildError(f"Publishing command contains an unknown placeholder: {exc}") from exc
        if not argv:
            raise BuildError("Command publishing adapter requires argv")
        allowed = set(target.get("pass_environment", [])) | set(target.get("secret_environment", []))
        env = {key: os.environ[key] for key in allowed if key in os.environ}
        for key in ("PATH", "HOME", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "LANG", "LC_ALL"):
            if key in os.environ:
                env.setdefault(key, os.environ[key])
        secrets_for_redaction: list[str] = []
        for key, value in target.get("environment", {}).items():
            if value.startswith("${") and value.endswith("}"):
                name = value[2:-1]
                if name not in allowed or name not in os.environ:
                    raise BuildError(f"Publishing environment variable {name!r} is not explicitly allowlisted and present")
                env[key] = os.environ[name]
                if name in target.get("secret_environment", []) and os.environ[name]:
                    secrets_for_redaction.append(os.environ[name])
            else:
                env[key] = value
        try:
            proc = run_process(argv, cwd=config_path.parent, env=env, timeout=timeout,
                               stderr_to_stdout=True, max_output_bytes=12_000)
            output = proc.stdout[-12000:]
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout or ""
            if isinstance(output, bytes):
                output = output.decode("utf-8", "replace")
            output = output[-12000:]
            for secret in sorted(set(secrets_for_redaction), key=len, reverse=True):
                output = output.replace(secret, "<redacted>")
            raise BuildError(f"Publish command timed out after {timeout} seconds: {output}") from exc
        for secret in sorted(set(secrets_for_redaction), key=len, reverse=True):
            output = output.replace(secret, "<redacted>")
        if proc.returncode:
            raise BuildError(f"Publish command failed ({proc.returncode}): {output}")
        return {"status": "published", "adapter": adapter, "stdout_tail": output[-4000:]}
    raise BuildError(f"Unsupported publishing adapter: {adapter}")
