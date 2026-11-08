from __future__ import annotations

import json
import re
import shlex
from pathlib import PurePosixPath
from urllib.parse import urlparse
from typing import Any

from .config import reserved_live_site_origin_errors


class WorkflowError(ValueError):
    pass


_RESERVED_ENV_NAMES = {
    "PATH", "HOME", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "LANG", "LC_ALL",
    "CONFIG_FILE", "SELECTED_COMPONENTS", "PUBLISHER_REF", "GITHUB_ENV",
    "GITHUB_OUTPUT", "GITHUB_PATH", "GITHUB_STEP_SUMMARY", "PYTHONPATH",
    "PYTHONHOME", "GIT_DIR", "GIT_WORK_TREE", "GIT_EXEC_PATH", "BASH_ENV",
    "PUBLISHER_SECRET_VALUE", "PUBLISHER_SECRET_NAME",
}


def _reserved_env(name: str) -> bool:
    return name.startswith(("GITHUB_", "RUNNER_")) or name in _RESERVED_ENV_NAMES


def _yaml_string(value: str) -> str:
    """JSON strings are valid double-quoted YAML scalars and avoid injection."""
    return json.dumps(str(value), ensure_ascii=False)


def _validate_action_ref(key: str, ref: str) -> None:
    if "@" not in ref:
        raise WorkflowError(f"workflow.actions.{key} must be pinned to a full commit SHA")
    action, sha = ref.rsplit("@", 1)
    if (not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", action)
            or len(sha) != 40 or not re.fullmatch(r"[0-9a-fA-F]{40}", sha)):
        raise WorkflowError(
            f"workflow.actions.{key} must be a repository/action path pinned to a full 40-character commit SHA"
        )


def _secret_bindings(config: dict[str, Any]) -> dict[str, str]:
    bindings = dict(config.get("workflow", {}).get("secrets", {}))
    needed: set[str] = set()
    for section in (config.get("publisher", {}),):
        auth = section.get("auth", {})
        for key in ("secret_env", "username_env"):
            if auth.get(key):
                needed.add(auth[key])
    for source in config.get("sources", []):
        auth = source.get("vcs", {}).get("auth", {})
        for key in ("secret_env", "username_env"):
            if auth.get(key):
                needed.add(auth[key])
    for task in config.get("build_tasks", []):
        needed.update(task.get("secret_environment", []))
    target = next((x for x in config.get("publishing_targets", []) if x["id"] == config.get("publishing", {}).get("target_id")), {})
    needed.update(target.get("secret_environment", []))
    missing = sorted(needed - set(bindings))
    if missing:
        raise WorkflowError("workflow.secrets must map every secret environment name used by auth/tasks/publishing: " + ", ".join(missing))
    for env_name, secret_name in bindings.items():
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", env_name):
            raise WorkflowError(f"Invalid environment variable name in workflow.secrets: {env_name}")
        if _reserved_env(env_name):
            raise WorkflowError(f"workflow.secrets cannot export reserved runner environment variable {env_name}")
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", secret_name):
            raise WorkflowError(f"Invalid GitHub secret name in workflow.secrets: {secret_name}")
    return bindings


def _permissions_block(values: dict[str, str], *, required: dict[str, str],
                       allowed_values: dict[str, set[str]], label: str) -> list[str]:
    merged = dict(values or {})
    unknown = set(merged) - set(allowed_values)
    if unknown:
        raise WorkflowError(f"workflow.{label} contains unsupported permission(s): {', '.join(sorted(unknown))}")
    for key, minimum in required.items():
        actual = merged.get(key, minimum)
        if actual not in allowed_values.get(key, set()):
            raise WorkflowError(f"workflow.{label} cannot weaken required permission {key}: {minimum}")
        merged[key] = actual
    if not merged:
        raise WorkflowError(f"workflow.{label} cannot be empty")
    lines = []
    for key in sorted(merged):
        value = merged[key]
        if value not in allowed_values.get(key, set()):
            raise WorkflowError(f"workflow.{label}.{key} is not in the least-privilege permission allowlist")
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", key):
            raise WorkflowError(f"Invalid GitHub permission name: {key}")
        lines.append(f"      {key}: {value}")
    return lines


def _repository_dispatch_contract(config: dict[str, Any], triggers: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str] | None:
    dispatch = triggers.get("repository_dispatch")
    if dispatch is None:
        return None
    if not isinstance(dispatch, dict):
        raise WorkflowError("triggers.repository_dispatch must be an object")
    event_type = dispatch.get("event_type")
    if not isinstance(event_type, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,99}", event_type):
        raise WorkflowError("triggers.repository_dispatch.event_type must be a lower-case event identifier")
    source_id = dispatch.get("source_id")
    source = next((item for item in config.get("sources", []) if item.get("id") == source_id), None)
    if source is None:
        raise WorkflowError("triggers.repository_dispatch.source_id must reference a configured source")
    repository = dispatch.get("source_repository")
    if not isinstance(repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise WorkflowError("triggers.repository_dispatch.source_repository must be owner/repository")
    branch = dispatch.get("source_branch")
    if (not isinstance(branch, str) or not re.fullmatch(r"[A-Za-z0-9._/-]{1,128}", branch)
            or branch.startswith((".", "-", "/")) or branch.endswith((".", "/"))
            or ".." in branch or "//" in branch):
        raise WorkflowError("triggers.repository_dispatch.source_branch must be a safe branch name")
    clone_url = str(source.get("vcs", {}).get("clone_url", ""))
    parsed = urlparse(clone_url)
    clone_repository = parsed.path.strip("/").removesuffix(".git")
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != "github.com" or clone_repository.casefold() != repository.casefold():
        raise WorkflowError("repository_dispatch.source_repository must match the selected source clone_url")
    if source.get("vcs", {}).get("default_ref") != branch:
        raise WorkflowError("repository_dispatch.source_branch must match the selected source default_ref")
    sha_env = source.get("vcs", {}).get("dispatch_sha_env")
    if not isinstance(sha_env, str) or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", sha_env) or _reserved_env(sha_env):
        raise WorkflowError("The repository-dispatch source must define a non-reserved vcs.dispatch_sha_env")
    return dispatch, source, sha_env


def generate_github_actions_workflow(config: dict[str, Any], *, profiles: list[str] | None = None) -> str:
    """Generate a GitHub Actions + Pages workflow with least-privilege jobs.

    Action references are never guessed: each action must be pinned by the caller
    to a full immutable commit SHA in configuration.
    """
    profiles = list(profiles or [])
    if any(not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name) for name in profiles):
        raise WorkflowError("Workflow profiles must be lower-case profile identifiers")
    if len(profiles) != len(set(profiles)):
        raise WorkflowError("A workflow profile may be selected only once")
    profile_args = "".join(f" --profile {shlex.quote(name)}" for name in profiles)
    wf = config.get("workflow")
    if not wf or wf.get("provider") != "github_actions":
        raise WorkflowError("workflow.provider must be explicitly configured as github_actions")
    actions = wf.get("actions", {})
    dry_run = bool(config.get("publishing", {}).get("dry_run", True))
    live_origin_errors = reserved_live_site_origin_errors(config)
    if live_origin_errors:
        raise WorkflowError("Unsafe live publication origin: " + "; ".join(live_origin_errors))
    required = ["checkout", "setup_python"]
    java_version = wf.get("java_version")
    setup_java = actions.get("setup_java")
    if java_version is not None:
        if (not isinstance(java_version, str)
                or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", java_version)):
            raise WorkflowError("workflow.java_version must be a numeric Java version such as '25'")
        if not setup_java:
            raise WorkflowError("workflow.java_version requires a pinned workflow.actions.setup_java ref")
        required.append("setup_java")
    elif setup_java:
        raise WorkflowError("workflow.actions.setup_java requires workflow.java_version")
    if not dry_run:
        required.extend(("upload_pages_artifact", "deploy_pages"))
    missing = [key for key in required if not actions.get(key)]
    if missing:
        raise WorkflowError("Workflow action refs must be explicitly pinned/configured: " + ", ".join(missing))
    for key in required:
        _validate_action_ref(key, actions[key])

    triggers = config.get("triggers", {"manual": True})
    dispatch_contract = _repository_dispatch_contract(config, triggers)
    trigger_lines: list[str] = []
    if triggers.get("manual", True):
        trigger_lines += [
            "  workflow_dispatch:", "    inputs:", "      components:",
            "        description: Component IDs separated by commas, or all",
            "        required: false", "        default: all", "        type: string",
        ]
    configured_paths = triggers.get("paths") or []
    if configured_paths and not (triggers.get("push_branches") or triggers.get("pull_request")):
        raise WorkflowError("triggers.paths requires at least one push_branches or pull_request event")
    if any(not isinstance(item, str) or not item or item == "!" for item in configured_paths):
        raise WorkflowError("triggers.paths entries must be non-empty path patterns")
    # GitHub Actions rejects a `paths` list containing only negative patterns.
    # The equivalent paths-ignore filter preserves the intended exclusion logic.
    only_exclusions = bool(configured_paths) and all(item.startswith("!") for item in configured_paths)
    path_key = "paths-ignore" if only_exclusions else "paths"
    path_values = [item[1:] for item in configured_paths] if only_exclusions else configured_paths
    if triggers.get("push_branches"):
        trigger_lines += ["  push:", "    branches:"] + [f"      - {_yaml_string(x)}" for x in triggers["push_branches"]]
        if configured_paths:
            trigger_lines += [f"    {path_key}:"] + [f"      - {_yaml_string(x)}" for x in path_values]
    if triggers.get("pull_request"):
        trigger_lines += ["  pull_request:"]
        if configured_paths:
            trigger_lines += [f"    {path_key}:"] + [f"      - {_yaml_string(x)}" for x in path_values]
    if triggers.get("schedule"):
        trigger_lines += ["  schedule:"] + [f"    - cron: {_yaml_string(x)}" for x in triggers["schedule"]]
    if triggers.get("workflow_call"):
        trigger_lines += ["  workflow_call:", "    inputs:", "      components:",
                          "        required: false", "        type: string"]
    if dispatch_contract:
        dispatch, _dispatch_source, _dispatch_sha_env = dispatch_contract
        trigger_lines += ["  repository_dispatch:", "    types:", f"      - {_yaml_string(dispatch['event_type'])}"]
    if not trigger_lines:
        raise WorkflowError("At least one GitHub Actions trigger must be configured")

    deploy_branch = triggers.get("deploy_branch")
    push_branches = triggers.get("push_branches", [])
    if not deploy_branch:
        if len(push_branches) > 1:
            raise WorkflowError("triggers.deploy_branch is required when multiple push_branches are configured")
        deploy_branch = push_branches[0] if push_branches else config["publisher"]["ref"]
    if not isinstance(deploy_branch, str) or not deploy_branch or deploy_branch.startswith("-") or any(c in deploy_branch for c in "\n\r\x00"):
        raise WorkflowError("triggers.deploy_branch is invalid")
    if push_branches and deploy_branch not in push_branches:
        raise WorkflowError("triggers.deploy_branch must be included in triggers.push_branches")

    secrets = _secret_bindings(config)
    if triggers.get("pull_request") and secrets:
        raise WorkflowError(
            "GitHub Actions pull_request builds cannot rely on configured repository secrets, "
            "because fork pull requests do not receive them. Disable pull_request or use public/read-only sources."
        )
    auth_sections = [config.get("publisher", {}).get("auth", {})]
    auth_sections.extend(source.get("vcs", {}).get("auth", {}) for source in config.get("sources", []))
    if any(auth.get("mode") == "ssh_agent" for auth in auth_sections):
        raise WorkflowError(
            "workflow.provider=github_actions does not provision SSH_AUTH_SOCK automatically. "
            "Use environment auth or provision an SSH agent in a separately reviewed custom workflow."
        )

    python_version = wf.get("python_version", "3.x")
    config_path = wf.get("config_file", "publisher.yml")
    # Build paths are resolved by the CLI relative to the configuration file's
    # directory. The Pages upload action runs from the checkout root, so mirror
    # that same base explicitly when the config lives in a subdirectory.
    config_rel = PurePosixPath(str(config_path).replace("\\", "/"))
    output_rel = PurePosixPath(str(config["site"]["output_directory"]).replace("\\", "/"))
    if (config_rel.is_absolute() or ".." in config_rel.parts or any(p.casefold() == ".git" for p in config_rel.parts)
            or output_rel.is_absolute() or ".." in output_rel.parts or any(p.casefold() == ".git" for p in output_rel.parts)):
        raise WorkflowError("Workflow config and artifact paths must remain outside Git metadata and inside the publisher checkout")
    config_parent = config_rel.parent
    artifact_rel = config_parent / output_rel
    if artifact_rel.is_absolute() or ".." in artifact_rel.parts:
        raise WorkflowError("The generated artifact path must remain inside the publisher checkout")
    artifact_path = artifact_rel.as_posix()
    retention = config.get("publishing", {}).get("retention_days", 1)
    checkout, setup_py = actions["checkout"], actions["setup_python"]
    setup_java_ref = actions.get("setup_java")
    upload = actions.get("upload_pages_artifact")
    deploy = actions.get("deploy_pages")
    runs_on = wf.get("runs_on", "ubuntu-latest")
    runner_value = "[" + ", ".join(_yaml_string(x) for x in runs_on) + "]" if isinstance(runs_on, list) else _yaml_string(runs_on)
    environment_name = wf.get("deploy_environment", "documentation-site")
    build_timeout = int(wf.get("build_timeout_minutes", 360))
    deploy_timeout = int(wf.get("deploy_timeout_minutes", 30))
    include_hidden = "true" if wf.get("include_hidden_files", True) else "false"
    extra_env = wf.get("environment", {})
    if set(extra_env) & set(secrets):
        raise WorkflowError("workflow.environment and workflow.secrets cannot define the same environment variable")
    extra_env_items = []
    for env_name, value in sorted(extra_env.items()):
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", env_name):
            raise WorkflowError(f"Invalid workflow.environment key: {env_name}")
        if _reserved_env(env_name):
            raise WorkflowError(f"workflow.environment cannot override reserved runner variable: {env_name}")
        if not isinstance(value, str):
            raise WorkflowError(f"workflow.environment values must be strings: {env_name}")
        if "\n" in value or "\r" in value:
            raise WorkflowError(f"Multiline workflow.environment value is forbidden: {env_name}")
        if "${{" in value:
            raise WorkflowError(f"workflow.environment values must be literal; use workflow.secrets for secrets: {env_name}")
        extra_env_items.append(f"          {env_name}: {_yaml_string(value)}")

    build_permissions = _permissions_block(
        wf.get("build_permissions", {}), required={"contents": "read"},
        allowed_values={"contents": {"read"}}, label="build_permissions"
    )
    deploy_permissions = []
    if not dry_run:
        deploy_permissions = _permissions_block(
            wf.get("deploy_permissions", {}),
            required={"pages": "write", "id-token": "write", "actions": "read"},
            allowed_values={"pages": {"write"}, "id-token": {"write"}, "actions": {"read"}},
            label="deploy_permissions"
        )
    concurrency_group = str(triggers.get("concurrency_group", "documentation-publisher"))
    if triggers.get("concurrency_group_per_ref", False):
        concurrency_group += "-${{ github.ref }}"

    lines = [
        f"name: {_yaml_string(wf.get('name', 'Documentation Publisher'))}", "", "on:", *trigger_lines, "",
        "permissions:", "  contents: read", "",
        "concurrency:", f"  group: {_yaml_string(concurrency_group)}",
        f"  cancel-in-progress: {'true' if triggers.get('cancel_in_progress', True) else 'false'}", "",
        "jobs:", "  build:", f"    runs-on: {runner_value}", f"    timeout-minutes: {build_timeout}",
        "    permissions:", *build_permissions, "    steps:",
        "      - name: Checkout workflow and configuration", f"        uses: {checkout}",
        "        with:", "          persist-credentials: false",
        "      - name: Set up Python", f"        uses: {setup_py}", "        with:", f"          python-version: {_yaml_string(python_version)}",
    ]
    if java_version is not None:
        lines += [
            "      - name: Set up Java", f"        uses: {setup_java_ref}", "        with:",
            "          distribution: temurin", f"          java-version: {_yaml_string(java_version)}",
        ]
    lines += [
        "      - name: Install engine package", "        run: python -m pip install .",
        "      - name: Validate configuration", "        env:",
        f"          CONFIG_FILE: {_yaml_string(config_path)}",
        *extra_env_items,
        f"        run: python -m publisher_engine.cli validate-config --config \"$CONFIG_FILE\"{profile_args}",
    ]
    if dispatch_contract:
        dispatch, dispatch_source, dispatch_sha_env = dispatch_contract
        source_repository = dispatch["source_repository"]
        source_branch = dispatch["source_branch"]
        lines += [
            "      - name: Validate source repository dispatch payload",
            "        if: github.event_name == 'repository_dispatch'",
            "        shell: bash",
            "        env:",
            f"          EXPECTED_SOURCE_REPOSITORY: {_yaml_string(source_repository)}",
            f"          EXPECTED_SOURCE_REF: {_yaml_string('refs/heads/' + source_branch)}",
            "          EVENT_SOURCE_REPOSITORY: ${{ github.event.client_payload.repository }}",
            "          EVENT_SOURCE_REF: ${{ github.event.client_payload.ref }}",
            "          EVENT_SOURCE_SHA: ${{ github.event.client_payload.sha }}",
            "        run: |",
            "          python - <<'PY'",
            "          import os, re, sys",
            "          expected_repo = os.environ['EXPECTED_SOURCE_REPOSITORY']",
            "          actual_repo = os.environ['EVENT_SOURCE_REPOSITORY']",
            "          expected_ref = os.environ['EXPECTED_SOURCE_REF']",
            "          actual_ref = os.environ['EVENT_SOURCE_REF']",
            "          source_sha = os.environ['EVENT_SOURCE_SHA']",
            "          if actual_repo.casefold() != expected_repo.casefold():",
            "              sys.exit(f'Untrusted source repository in dispatch: {actual_repo!r}')",
            "          if actual_ref != expected_ref:",
            "              sys.exit(f'Unexpected source branch in dispatch: {actual_ref!r}')",
            "          if not re.fullmatch(r'[0-9a-fA-F]{40}|[0-9a-fA-F]{64}', source_sha):",
            "              sys.exit('Dispatch payload must contain a full Git commit SHA')",
            "          print(f'Validated source dispatch: {actual_repo}@{source_sha}')",
            "          PY",
        ]
    # Forward the decision step output to the build job so the deploy job can
    # safely consume it through needs.build.outputs.deploy.
    if not dry_run:
        build_job_index = lines.index("  build:")
        lines[build_job_index + 1:build_job_index + 1] = [
            "    outputs:",
            "      deploy: ${{ steps.decision.outputs.deploy }}",
        ]
    for env_name, secret_name in sorted(secrets.items()):
        lines += [
            f"      - name: Export configured credential {env_name}",
            "        if: github.event_name != 'pull_request'",
            "        shell: bash", "        env:",
            f"          PUBLISHER_SECRET_VALUE: ${{{{ secrets.{secret_name} }}}}",
            f"          PUBLISHER_SECRET_NAME: {_yaml_string(env_name)}", "        run: |",
            "          python - <<'PY'", "          import os, secrets",
            "          name = os.environ['PUBLISHER_SECRET_NAME']",
            "          value = os.environ['PUBLISHER_SECRET_VALUE']",
            "          delimiter = 'PUBLISHER_' + secrets.token_hex(16)",
            "          with open(os.environ['GITHUB_ENV'], 'a', encoding='utf-8') as env_file:",
            "              env_file.write(f'{name}<<{delimiter}\\n{value}\\n{delimiter}\\n')",
            "          PY",
        ]
    lines += [
        "      - name: Build and validate site", "        env:",
        "          SELECTED_COMPONENTS: ${{ github.event.inputs.components || inputs.components || 'all' }}",
        "          PUBLISHER_REF: ${{ github.event.pull_request.base.sha || github.sha }}",
        f"          CONFIG_FILE: {_yaml_string(config_path)}",
    ]
    if dispatch_contract:
        _dispatch, _dispatch_source, dispatch_sha_env = dispatch_contract
        lines.append(f"          {dispatch_sha_env}: ${{{{ github.event.client_payload.sha }}}}")
    lines.extend(extra_env_items)
    lines.append(f"        run: python -m publisher_engine.cli build --config \"$CONFIG_FILE\"{profile_args} --components \"$SELECTED_COMPONENTS\" --publisher-ref \"$PUBLISHER_REF\"")
    # A dry-run workflow is a build/validation-only workflow. It intentionally
    # contains neither an artifact upload step nor a deploy job. Setting
    # publishing.dry_run=false is the explicit deployment opt-in.
    if not dry_run:
        freshness_source = dispatch_contract[1] if dispatch_contract else None
        freshness_dispatch, freshness_sha_env = (dispatch_contract[0], dispatch_contract[2]) if dispatch_contract else (None, None)
        if freshness_source is not None:
            source_clone_url = freshness_source["vcs"]["clone_url"]
            source_branch = freshness_dispatch["source_branch"]
            source_ref = f"refs/heads/{source_branch}"
            lines += [
                "      - name: Check source revision is current before artifact upload",
                "        id: source-freshness",
                "        if: github.event_name == 'repository_dispatch'",
                "        shell: bash",
                "        env:",
                f"          SOURCE_CLONE_URL: {_yaml_string(source_clone_url)}",
                f"          SOURCE_REF: {_yaml_string(source_ref)}",
                "          EVENT_SOURCE_SHA: ${{ github.event.client_payload.sha }}",
                "        run: |",
                "          set -euo pipefail",
                '          current_sha="$(git ls-remote --exit-code "$SOURCE_CLONE_URL" "$SOURCE_REF" | cut -f1)"',
                '          if [[ -z "$current_sha" ]]; then',
                "            echo 'Unable to resolve the configured source branch head' >&2",
                "            exit 1",
                "          fi",
                '          if [[ "${current_sha,,}" == "${EVENT_SOURCE_SHA,,}" ]]; then',
                '            echo current=true >> "$GITHUB_OUTPUT"',
                "          else",
                '            echo current=false >> "$GITHUB_OUTPUT"',
                '            echo "Skipping stale source revision ${EVENT_SOURCE_SHA}; current branch head is ${current_sha}"',
                "          fi",
            ]
        lines += [
            "      - name: Decide whether this run may deploy", "        id: decision", "        shell: bash", "        env:",
            f"          DEPLOY_BRANCH: {_yaml_string(deploy_branch)}",
            "          SOURCE_REVISION_CURRENT: ${{ steps.source-freshness.outputs.current || 'true' }}",
            "        run: |",
            '          if [[ "$GITHUB_EVENT_NAME" == repository_dispatch && "$SOURCE_REVISION_CURRENT" != true ]]; then',
            "            echo 'deploy=false' >> \"$GITHUB_OUTPUT\"",
            '          elif [[ "$GITHUB_REF" == "refs/heads/${DEPLOY_BRANCH}" && "$GITHUB_EVENT_NAME" != pull_request ]]; then',
            "            echo 'deploy=true' >> \"$GITHUB_OUTPUT\"",
            "          else",
            "            echo 'deploy=false' >> \"$GITHUB_OUTPUT\"",
            "          fi",
            "      - name: Upload GitHub Pages artifact", "        if: steps.decision.outputs.deploy == 'true'",
            f"        uses: {upload}", "        with:",
            f"          name: {_yaml_string(config.get('publishing', {}).get('artifact_name', 'documentation-site'))}",
            f"          path: {_yaml_string(artifact_path)}",
            f"          retention-days: {retention}", f"          include-hidden-files: {include_hidden}", "",
            "  deploy:", "    needs: build", "    if: needs.build.outputs.deploy == 'true'", f"    runs-on: {runner_value}",
            f"    timeout-minutes: {deploy_timeout}", "    permissions:", *deploy_permissions,
            "    environment:", f"      name: {_yaml_string(environment_name)}", "      url: ${{ steps.deployment.outputs.page_url }}", "    steps:",
        ]
        if freshness_source is not None:
            lines += [
                "      - name: Recheck source revision immediately before deployment",
                "        id: source-freshness",
                "        if: github.event_name == 'repository_dispatch'",
                "        shell: bash",
                "        env:",
                f"          SOURCE_CLONE_URL: {_yaml_string(freshness_source['vcs']['clone_url'])}",
                f"          SOURCE_REF: {_yaml_string(source_ref)}",
                "          EVENT_SOURCE_SHA: ${{ github.event.client_payload.sha }}",
                "        run: |",
                "          set -euo pipefail",
                '          current_sha="$(git ls-remote --exit-code "$SOURCE_CLONE_URL" "$SOURCE_REF" | cut -f1)"',
                '          if [[ -z "$current_sha" ]]; then',
                "            echo 'Unable to resolve the configured source branch head' >&2",
                "            exit 1",
                "          fi",
                '          if [[ "${current_sha,,}" == "${EVENT_SOURCE_SHA,,}" ]]; then',
                '            echo current=true >> "$GITHUB_OUTPUT"',
                "          else",
                '            echo current=false >> "$GITHUB_OUTPUT"',
                '            echo "Skipping deployment of stale source revision ${EVENT_SOURCE_SHA}; current branch head is ${current_sha}"',
                "          fi",
            ]
        lines += [
            "      - name: Deploy validated artifact",
            "        id: deployment",
        ]
        if freshness_source is not None:
            lines.append("        if: github.event_name != 'repository_dispatch' || steps.source-freshness.outputs.current == 'true'")
        lines += [
            f"        uses: {deploy}", "        with:",
            f"          artifact_name: {_yaml_string(config.get('publishing', {}).get('artifact_name', 'documentation-site'))}", "",
        ]
    return "\n".join(lines)


def _gitlab_branch(value: Any, *, label: str) -> str:
    """Return a conservative branch name safe to embed in GitLab rule expressions."""
    if isinstance(value, str) and value.startswith("refs/heads/"):
        value = value.removeprefix("refs/heads/")
    if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._/-]{1,128}", value)
            or value.startswith((".", "-", "/")) or value.endswith((".", "/"))
            or ".." in value or "//" in value):
        raise WorkflowError(f"{label} must be a simple Git branch name (letters, digits, dot, underscore, slash or hyphen)")
    return value


def _gitlab_yaml_if(expression: str) -> str:
    """Quote a GitLab `if:` expression as a single-quoted YAML scalar."""
    return "'" + expression.replace("'", "''") + "'"


def generate_gitlab_ci_workflow(config: dict[str, Any], *, profiles: list[str] | None = None) -> str:
    """Generate a GitLab CI pipeline with an optional GitLab Pages deployment.

    The runner image must be supplied by the operator and pinned by OCI digest.
    A dry-run config receives validate/build jobs only; Pages deployment is an
    explicit opt-in through publishing.dry_run=false and is branch-gated.
    """
    profiles = list(profiles or [])
    if any(not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name) for name in profiles):
        raise WorkflowError("Workflow profiles must be lower-case profile identifiers")
    if len(profiles) != len(set(profiles)):
        raise WorkflowError("A workflow profile may be selected only once")

    wf = config.get("workflow") or {}
    if wf.get("provider") != "gitlab_ci":
        raise WorkflowError("workflow.provider must be explicitly configured as gitlab_ci")
    image = wf.get("container_image")
    if not isinstance(image, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}", image):
        raise WorkflowError("workflow.container_image must be an OCI image reference pinned by a full sha256 digest")
    python_version = wf.get("python_version", "3.13")
    if python_version not in {"3.11", "3.12", "3.13"}:
        raise WorkflowError("GitLab workflow.python_version must be one of 3.11, 3.12 or 3.13")
    if config.get("triggers", {}).get("workflow_call"):
        raise WorkflowError("GitLab CI does not support the workflow_call trigger; use a separately reviewed child pipeline")

    dry_run = bool(config.get("publishing", {}).get("dry_run", True))
    live_origin_errors = reserved_live_site_origin_errors(config)
    if live_origin_errors:
        raise WorkflowError("Unsafe live publication origin: " + "; ".join(live_origin_errors))

    config_path = wf.get("config_file", "publisher.yml")
    config_rel = PurePosixPath(str(config_path).replace("\\", "/"))
    output_rel = PurePosixPath(str(config["site"]["output_directory"]).replace("\\", "/"))
    if (config_rel.is_absolute() or ".." in config_rel.parts or any(p.casefold() == ".git" for p in config_rel.parts)
            or output_rel.is_absolute() or ".." in output_rel.parts or any(p.casefold() == ".git" for p in output_rel.parts)):
        raise WorkflowError("GitLab workflow config and artifact paths must remain outside Git metadata and inside the checkout")
    artifact_rel = config_rel.parent / output_rel
    if artifact_rel.is_absolute() or ".." in artifact_rel.parts:
        raise WorkflowError("The GitLab Pages artifact path must remain inside the publisher checkout")
    artifact_path = artifact_rel.as_posix()

    triggers = config.get("triggers", {"manual": True})
    if triggers.get("repository_dispatch"):
        raise WorkflowError("GitLab CI does not support the GitHub repository_dispatch trigger")
    push_branches = [_gitlab_branch(x, label="triggers.push_branches[]") for x in triggers.get("push_branches", [])]
    if triggers.get("paths") and any(not isinstance(p, str) or not p or p.startswith("!") or "\n" in p or "\r" in p for p in triggers["paths"]):
        raise WorkflowError("GitLab triggers.paths accepts only non-empty positive path patterns; negated patterns are not supported")
    if triggers.get("paths") and not (push_branches or triggers.get("pull_request")):
        raise WorkflowError("GitLab triggers.paths requires at least one push_branches or pull_request event")
    branch_candidate = triggers.get("deploy_branch") or (push_branches[0] if len(push_branches) == 1 else config.get("publisher", {}).get("ref", "main"))
    if isinstance(branch_candidate, str) and branch_candidate.startswith("refs/heads/"):
        branch_candidate = branch_candidate.removeprefix("refs/heads/")
    deploy_branch = _gitlab_branch(
        branch_candidate,
        label="triggers.deploy_branch",
    )
    if len(push_branches) > 1 and not triggers.get("deploy_branch"):
        raise WorkflowError("triggers.deploy_branch is required when multiple push_branches are configured")
    if push_branches and deploy_branch not in push_branches:
        raise WorkflowError("triggers.deploy_branch must be included in triggers.push_branches")

    rules: list[tuple[str, list[str] | None]] = []
    if triggers.get("manual", True):
        rules.append(('$CI_PIPELINE_SOURCE == "web"', None))
    if triggers.get("schedule"):
        rules.append(('$CI_PIPELINE_SOURCE == "schedule"', None))
    if triggers.get("pull_request"):
        changes = list(triggers.get("paths") or []) or None
        rules.append(('$CI_PIPELINE_SOURCE == "merge_request_event"', changes))
    if triggers.get("pull_request") and push_branches:
        rules.append(('$CI_PIPELINE_SOURCE == "push" && $CI_COMMIT_BRANCH && $CI_OPEN_MERGE_REQUESTS', None))
        # This rule is a deny rule and is rendered ahead of branch allow rules.
    for branch in push_branches:
        expression = '$CI_PIPELINE_SOURCE == "push" && $CI_COMMIT_BRANCH == ' + json.dumps(branch)
        rules.append((expression, list(triggers.get("paths") or []) or None))
    if not rules:
        raise WorkflowError("At least one supported GitLab CI trigger must be configured (manual, push, pull_request or schedule)")

    secrets = _secret_bindings(config)
    if triggers.get("pull_request") and secrets:
        raise WorkflowError(
            "GitLab merge-request pipelines cannot rely on configured workflow.secrets; "
            "use public/read-only sources or disable pull_request for secret-bearing builds"
        )
    auth_sections = [config.get("publisher", {}).get("auth", {})]
    auth_sections.extend(source.get("vcs", {}).get("auth", {}) for source in config.get("sources", []))
    if any(auth.get("mode") == "ssh_agent" for auth in auth_sections):
        raise WorkflowError("GitLab CI does not provision SSH_AUTH_SOCK; use explicit environment credentials")

    extra_env = wf.get("environment", {})
    if set(extra_env) & set(secrets):
        raise WorkflowError("workflow.environment and workflow.secrets cannot define the same environment variable")
    extra_env_lines: list[str] = []
    for env_name, value in sorted(extra_env.items()):
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", env_name):
            raise WorkflowError(f"Invalid workflow.environment key: {env_name}")
        if _reserved_env(env_name) or env_name.startswith(("CI_", "GITLAB_")):
            raise WorkflowError(f"workflow.environment cannot override reserved GitLab runner variable: {env_name}")
        if not isinstance(value, str) or any(c in value for c in "\r\n$"):
            raise WorkflowError(f"GitLab workflow.environment values must be literal single-line strings without variable expansion: {env_name}")
        extra_env_lines.append(f"    {env_name}: {_yaml_string(value)}")
    for env_name, secret_name in secrets.items():
        if _reserved_env(env_name) or env_name.startswith(("CI_", "GITLAB_")):
            raise WorkflowError(f"workflow.secrets cannot export reserved GitLab runner variable {env_name}")
        if secret_name.startswith(("CI_", "GITLAB_")):
            raise WorkflowError(f"workflow.secrets cannot read reserved GitLab runner variable {secret_name}")

    profile_args = "".join(f" --profile {shlex.quote(name)}" for name in profiles)
    config_arg = shlex.quote(str(config_rel))
    build_timeout = int(wf.get("build_timeout_minutes", 360))
    deploy_timeout = int(wf.get("deploy_timeout_minutes", 30))
    retention = int(config.get("publishing", {}).get("retention_days", 1))
    retention_text = "1 day" if retention == 1 else f"{retention} days"
    resource_group = str(triggers.get("concurrency_group", "documentation-publisher"))
    environment_name = str(wf.get("deploy_environment", "production"))

    lines = [
        "# Generated by documentation-publisher; edit publisher.yml, not this file.",
        "# GitLab Pages deployment requires GitLab 17.9 or newer.",
        "default:", f"  image: {_yaml_string(image)}", "  interruptible: true", "",
        "variables:", '  PIP_DISABLE_PIP_VERSION_CHECK: "1"', '  PIP_NO_INPUT: "1"', "",
        "stages:", "  - validate", "  - build",
    ]
    if not dry_run:
        lines.append("  - deploy")
    lines += ["", "workflow:", "  rules:"]
    # Suppress duplicate branch pipelines when merge-request pipelines are enabled.
    ordered_rules = list(rules)
    if triggers.get("pull_request") and push_branches:
        deny = next((item for item in ordered_rules if "$CI_OPEN_MERGE_REQUESTS" in item[0]), None)
        ordered_rules.remove(deny)
        ordered_rules.insert(0, deny)
    for expression, changes in ordered_rules:
        lines += [f"    - if: {_gitlab_yaml_if(expression)}"]
        if changes:
            lines.append("      changes:")
            lines.extend(f"        - {_yaml_string(path)}" for path in changes)
        if "$CI_OPEN_MERGE_REQUESTS" in expression:
            lines[-1] = "    - if: " + _gitlab_yaml_if(expression)
            lines.append("      when: never")
    version_guard = (
        f"python -c 'import sys; assert sys.version_info[:2] == ({int(python_version.split('.')[0])}, "
        f"{int(python_version.split('.')[1])}), f\"Expected Python {python_version}, got {{sys.version}}\"'"
    )
    validate_install = "env -u CI_JOB_TOKEN -u CI_REPOSITORY_URL -u CI_REGISTRY_PASSWORD -u CI_DEPLOY_PASSWORD python -m pip install --disable-pip-version-check ."
    validate_command = (
        f"env -u CI_JOB_TOKEN -u CI_REPOSITORY_URL -u CI_REGISTRY_PASSWORD -u CI_DEPLOY_PASSWORD "
        f"python -m publisher_engine.cli validate-config --config {config_arg}{profile_args}"
    )
    lines += ["    - when: never", "", "validate-config:", "  stage: validate",
              f"  timeout: {_yaml_string(f'{min(build_timeout, 30)} minutes')}", "  script:",
              f"    - {_yaml_string(version_guard)}",
              f"    - {_yaml_string(validate_install)}",
              f"    - {_yaml_string(validate_command)}", ""]

    lines += ["build-site:", "  stage: build", "  needs:", "    - validate-config",
              f"  timeout: {_yaml_string(f'{build_timeout} minutes')}", "  variables:",
              f"    CONFIG_FILE: {_yaml_string(str(config_rel))}", '    SELECTED_COMPONENTS: "all"']
    lines.extend(extra_env_lines)
    lines += ["  script:", f"    - {_yaml_string(version_guard)}",
              f"    - {_yaml_string('git subtree -h >/tmp/git-subtree-help 2>&1 || grep -qi \'^usage: git subtree\' /tmp/git-subtree-help')}"]
    if any(source.get("vcs", {}).get("lfs", False) for source in config.get("sources", [])):
        lines.append(f"    - {_yaml_string('git lfs version')}")
    lines.append(f"    - {_yaml_string('env -u CI_JOB_TOKEN -u CI_REPOSITORY_URL -u CI_REGISTRY_PASSWORD -u CI_DEPLOY_PASSWORD python -m pip install --disable-pip-version-check .')}")
    if secrets:
        export_lines = ["set +x"]
        for env_name, secret_name in sorted(secrets.items()):
            export_lines.append(f'export {env_name}="${{{secret_name}:?Required GitLab CI/CD variable {secret_name} is missing}}"')
        lines += ["    - |", *[f"      {item}" for item in export_lines]]
    build_command = (
        f'env -u CI_JOB_TOKEN -u CI_REPOSITORY_URL -u CI_REGISTRY_PASSWORD -u CI_DEPLOY_PASSWORD '
        f'python -m publisher_engine.cli build --config "$CONFIG_FILE"{profile_args} '
        '--components "${SELECTED_COMPONENTS:-all}" --publisher-ref "$CI_COMMIT_SHA"'
    )
    lines.append(f"    - {_yaml_string(build_command)}")
    lines += ["  artifacts:", f"    expire_in: {_yaml_string(retention_text)}", "    paths:",
              f"      - {_yaml_string(artifact_path)}", ""]

    if not dry_run:
        lines += ["deploy-pages:", "  stage: deploy", "  needs:", "    - job: build-site", "      artifacts: true",
                  f"  timeout: {_yaml_string(f'{deploy_timeout} minutes')}", f"  resource_group: {_yaml_string(resource_group)}",
                  "  script:", f"    - {_yaml_string('test -s ' + shlex.quote(artifact_path + '/index.html'))}",
                  "  pages:", f"    publish: {_yaml_string(artifact_path)}", "  artifacts:", "    paths:",
                  f"      - {_yaml_string(artifact_path)}", "  environment:", f"    name: {_yaml_string(environment_name)}",
                  "  rules:",
                  f"    - if: {_gitlab_yaml_if('$CI_COMMIT_BRANCH == ' + json.dumps(deploy_branch) + ' && $CI_PIPELINE_SOURCE != "merge_request_event"')}",
                  "      when: on_success", "    - when: never", ""]
    return "\n".join(lines)
