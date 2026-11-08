from __future__ import annotations

import argparse
import json
from importlib import resources
import os
import sys
from pathlib import Path

from . import __version__
from .config import load_config, ConfigError
from .engine import build, publish, BuildError, safe_child, resolve_build_plan
from .workflow import generate_github_actions_workflow, generate_gitlab_ci_workflow
from .gitops import GitError


def _repository_root(config_path: Path) -> Path:
    """Find the nearest checkout root, falling back to the config directory.

    `.git` may be a directory or a gitfile (worktree/submodule checkout).
    This keeps workflow.file and workflow.config_file repository-relative even
    when the central configuration lives in a subdirectory.
    """
    resolved = config_path.resolve()
    for candidate in (resolved.parent, *resolved.parent.parents):
        marker = candidate / ".git"
        if marker.is_dir() or marker.is_file():
            return candidate
    return resolved.parent


def _explicit_workflow_output(path: Path) -> Path:
    """Resolve an explicit --output path without allowing writes into Git metadata.

    Unlike workflow.file, --output is intentionally allowed outside the checkout.
    The final path is still checked after resolving existing parent symlinks so an
    explicit override cannot accidentally target a .git directory.
    """
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    candidate = Path(os.path.abspath(candidate))
    if candidate.is_symlink():
        raise BuildError(f"Refusing to write a workflow through a symlink: {candidate}")
    try:
        resolved = candidate.parent.resolve(strict=False) / candidate.name
    except (OSError, RuntimeError) as exc:
        raise BuildError(f"Could not safely resolve workflow output path {candidate}: {exc}") from exc
    if any(part.casefold() == ".git" for part in resolved.parts):
        raise BuildError(f"Refusing explicit workflow output inside Git metadata: {candidate}")
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="documentation-publisher", description="Generic, configuration-driven documentation publisher")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate-config", help="Validate schema and semantic constraints")
    validate.add_argument("--config", type=Path, default=Path("publisher.yml"))
    validate.add_argument("--profile", action="append", default=[])

    plan = sub.add_parser("plan", help="Print the resolved component/task plan without executing it")
    plan.add_argument("--config", type=Path, default=Path("publisher.yml"))
    plan.add_argument("--profile", action="append", default=[])
    plan.add_argument("--components", default="all")

    build_cmd = sub.add_parser("build", help="Build and validate the configured static site")
    build_cmd.add_argument("--config", type=Path, default=Path("publisher.yml"))
    build_cmd.add_argument("--profile", action="append", default=[])
    build_cmd.add_argument("--components", default="all")
    build_cmd.add_argument("--replace-output", action="store_true")
    build_cmd.add_argument("--publisher-ref", default=None, help="Explicit publisher commit/ref override for reproducible CI runs")

    pub = sub.add_parser("publish", help="Run the configured publishing adapter")
    pub.add_argument("--config", type=Path, default=Path("publisher.yml"))
    pub.add_argument("--profile", action="append", default=[], help="Apply a named profile (may be repeated; order is significant)")
    pub.add_argument("--site", type=Path)

    workflow = sub.add_parser("generate-workflow", help="Generate the configured CI workflow from the central configuration")
    workflow.add_argument("--config", type=Path, default=Path("publisher.yml"))
    workflow.add_argument("--profile", action="append", default=[], help="Apply a named profile (may be repeated; order is significant)")
    workflow.add_argument("--output", type=Path)
    workflow.add_argument("--replace-existing", action="store_true",
                          help="Replace an existing workflow file; without this flag existing files are preserved")

    init_config = sub.add_parser("init-config", help="Create a new publisher.yml from the packaged generic starter template")
    init_config.add_argument("--output", type=Path, default=Path("publisher.yml"),
                             help="New configuration path (default: ./publisher.yml); existing files are never overwritten")
    init_config.add_argument("--template", type=Path,
                             help="Optional local YAML template; defaults to the packaged publisher.example.yml")

    sub.add_parser("capabilities", help="Print the machine-readable provider and adapter support contract")

    args = parser.parse_args(argv)
    try:
        if args.command == "validate-config":
            cfg = load_config(args.config.resolve(), args.profile)
            print(f"Configuration valid: {len(cfg['sources'])} source(s), {len(cfg['components'])} component(s), {len(cfg['build_tasks'])} task(s)")
        elif args.command == "plan":
            cfg = load_config(args.config.resolve(), args.profile)
            selected = None if args.components == "all" else [x.strip() for x in args.components.split(",") if x.strip()]
            plan = resolve_build_plan(cfg, selected)
            print(json.dumps({
                "project": cfg["project"],
                "selection": plan["chosen_ids"],
                "components": [{"id": component["id"], "route": component["route"],
                                "tasks": component.get("tasks", []),
                                "dependencies": component.get("dependencies", [])}
                               for component in plan["components"]],
                "sources": [{"id": source["id"], "mode": source["integration"]["mode"],
                             "prefix": source["integration"]["prefix"], "ref": source["vcs"]["default_ref"]}
                            for source in plan["sources"]],
                "tasks": [{"id": task["id"], "source_id": plan["task_source_ids"][task["id"]],
                           "depends_on": task.get("depends_on", [])}
                          for task in plan["tasks"]],
            }, indent=2))
        elif args.command == "build":
            selected = None if args.components == "all" else [x.strip() for x in args.components.split(",") if x.strip()]
            result = build(args.config, selected_ids=selected, profiles=args.profile, replace_output=args.replace_output, publisher_ref_override=args.publisher_ref)
            print(json.dumps(result, indent=2))
        elif args.command == "publish":
            result = publish(args.config, args.site, profiles=args.profile)
            print(json.dumps(result, indent=2))
        elif args.command == "generate-workflow":
            config_path = args.config.resolve()
            cfg = load_config(config_path, args.profile)
            repo_root = _repository_root(config_path)
            workflow_cfg = cfg.setdefault("workflow", {})
            workflow_provider = workflow_cfg.get("provider")
            # Unless explicitly overridden, point the generated workflow at the
            # exact configuration file used for generation, relative to checkout.
            if "config_file" not in workflow_cfg:
                workflow_cfg["config_file"] = config_path.relative_to(repo_root).as_posix()
            if args.output is not None:
                output = _explicit_workflow_output(args.output)
            else:
                default_workflow_file = (
                    ".gitlab-ci.yml" if workflow_provider == "gitlab_ci"
                    else ".github/workflows/documentation-publisher.yml"
                )
                workflow_file = workflow_cfg.get("file", default_workflow_file)
                output = safe_child(repo_root, workflow_file)
            generators = {
                "github_actions": generate_github_actions_workflow,
                "gitlab_ci": generate_gitlab_ci_workflow,
            }
            generator = generators.get(workflow_provider)
            if generator is None:
                raise BuildError(f"Unsupported workflow provider: {workflow_provider!r}")
            content = generator(cfg, profiles=args.profile)
            if output.is_symlink():
                raise BuildError(f"Refusing to write a workflow through a symlink: {output}")
            if output.exists() and not args.replace_existing:
                raise BuildError(f"Workflow already exists: {output}; choose another --output or pass --replace-existing after review")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(content, encoding="utf-8")
            print(f"Workflow generated: {output}")
        elif args.command == "init-config":
            if args.template is not None:
                template_path = args.template.expanduser()
                if template_path.is_symlink() or not template_path.is_file():
                    raise BuildError(f"Configuration template must be a regular, non-symlink file: {template_path}")
                template_text = template_path.read_text(encoding="utf-8")
            else:
                template_text = resources.files("publisher_engine").joinpath("data", "publisher.example.yml").read_text(encoding="utf-8")
            output_path = args.output.expanduser()
            if not output_path.is_absolute():
                output_path = Path.cwd() / output_path
            output_path = Path(os.path.abspath(output_path))
            if output_path.is_symlink():
                raise BuildError(f"Refusing to replace a symlink as configuration output: {output_path}")
            try:
                resolved_parent = output_path.parent.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise BuildError(f"Configuration output directory does not exist or cannot be resolved: {output_path.parent}") from exc
            if not resolved_parent.is_dir():
                raise BuildError(f"Configuration output parent is not a directory: {resolved_parent}")
            resolved_output = resolved_parent / output_path.name
            if any(part.casefold() == ".git" for part in resolved_output.parts):
                raise BuildError(f"Refusing to create configuration inside Git metadata: {resolved_output}")
            try:
                with resolved_output.open("x", encoding="utf-8", newline="") as handle:
                    handle.write(template_text)
            except FileExistsError as exc:
                raise BuildError(f"Configuration already exists and was not changed: {resolved_output}") from exc
            except OSError as exc:
                raise BuildError(f"Cannot create configuration {resolved_output}: {exc}") from exc
            print(f"Configuration template created: {resolved_output}")
            print("Replace every <PLACEHOLDER> value, then run: documentation-publisher validate-config --config " + str(resolved_output))
        elif args.command == "capabilities":
            capabilities = json.loads(
                resources.files("publisher_engine").joinpath("data", "provider-capabilities.json").read_text(encoding="utf-8")
            )
            print(json.dumps(capabilities, indent=2, sort_keys=True))
        return 0
    except (ConfigError, BuildError, GitError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
