from __future__ import annotations

import copy
import ipaddress
import json
from importlib import resources
import os
import re
from pathlib import Path, PurePosixPath
from .process import run_process
from typing import Any
from urllib.parse import urlparse, unquote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from jsonschema import Draft202012Validator


class ConfigError(ValueError):
    pass


_WORKFLOW_RESERVED_ENV = {
    "PATH", "HOME", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "LANG", "LC_ALL",
    "CONFIG_FILE", "SELECTED_COMPONENTS", "PUBLISHER_REF", "GITHUB_ENV",
    "GITHUB_OUTPUT", "GITHUB_PATH", "GITHUB_STEP_SUMMARY", "PYTHONPATH",
    "PYTHONHOME", "GIT_DIR", "GIT_WORK_TREE", "GIT_EXEC_PATH", "BASH_ENV",
}


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects ambiguous duplicate mapping keys."""


def _construct_unique_mapping(loader: yaml.SafeLoader, node: yaml.nodes.MappingNode, deep: bool = False) -> dict:
    # Preserve standard YAML merge-key behavior (anchors/aliases), while rejecting
    # duplicate keys explicitly written in the same mapping. A deliberate explicit
    # value may still override a value inherited through `<<`, as YAML specifies.
    merge_tag = "tag:yaml.org,2002:merge"
    explicit_key_nodes = {
        id(key_node) for key_node, _ in node.value if key_node.tag != merge_tag
    }
    loader.flatten_mapping(node)
    mapping = {}
    explicit_seen = set()
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            is_explicit = id(key_node) in explicit_key_nodes
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a configuration mapping", node.start_mark,
                "found an unhashable mapping key", key_node.start_mark,
            ) from exc
        if is_explicit and key in explicit_seen:
            raise yaml.constructor.ConstructorError(
                "while constructing a configuration mapping", node.start_mark,
                f"found duplicate key {key!r}", key_node.start_mark,
            )
        if is_explicit:
            explicit_seen.add(key)
        # Repeated inherited keys follow PyYAML's normal merge precedence.
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deterministic recursive mapping merge; lists are replaced, never guessed/merged."""
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _read_mapping(path: Path) -> dict[str, Any]:
    try:
        value = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeySafeLoader)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Cannot read configuration {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"Configuration root must be a mapping: {path}")
    return value


def validate_schema(config: dict[str, Any], schema_path: Path | None = None) -> None:
    try:
        if schema_path is not None:
            schema_source = schema_path.read_text(encoding="utf-8")
            schema_label = str(schema_path)
        else:
            schema_resource = resources.files("publisher_engine").joinpath("data", "publisher.schema.json")
            schema_source = schema_resource.read_text(encoding="utf-8")
            schema_label = "publisher_engine/data/publisher.schema.json"
        schema = json.loads(schema_source)
    except (OSError, ModuleNotFoundError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Cannot load JSON Schema {schema_label if 'schema_label' in locals() else 'package resource'}: {exc}") from exc
    errors = sorted(Draft202012Validator(schema).iter_errors(config), key=lambda e: list(map(str, e.path)))
    if errors:
        details = "\n".join(
            f" - /{'/'.join(map(str, err.absolute_path)) or '<root>'}: {err.message}"
            for err in errors[:50]
        )
        raise ConfigError(f"Configuration does not match schema:\n{details}")


_PLACEHOLDER = re.compile(r"<[A-Z][A-Z0-9_]*>|\{\{[^}]+\}\}")
_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_SENSITIVE_ENV_NAME = re.compile(
    r"(?:^|_)(?:secret|token|password|credentials?|key|api_?key|access_?key|private_?key|ssh_?key|"
    r"pat|jwt|bearer|client_?secret|refresh_?token|signing_?key)(?:_|$)",
    re.I,
)


def _is_sensitive_env_name(name: str) -> bool:
    return bool(_SENSITIVE_ENV_NAME.search(name))


def _resolve_selected_environment(config: dict[str, Any], *, allow_missing: bool = False) -> dict[str, Any]:
    """Expand ordinary configuration values without ever expanding secret references."""
    result = copy.deepcopy(config)
    def resolve(value: Any, where: str) -> Any:
        if not isinstance(value, str):
            return value
        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in os.environ:
                if allow_missing:
                    return match.group(0)
                raise ConfigError(f"Configuration value {where} requires environment variable {name!r}")
            return os.environ[name]
        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", replace, value)

    def at(mapping: dict[str, Any], key: str, where: str) -> None:
        if key in mapping:
            mapping[key] = resolve(mapping[key], where)

    project = result.get("project", {})
    for key in ("homepage_url", "repository_url", "logo", "favicon"):
        at(project, key, f"project.{key}")
    publisher = result.get("publisher", {})
    for key in ("clone_url", "web_url", "ref"):
        at(publisher, key, f"publisher.{key}")
    for source in result.get("sources", []):
        vcs = source.get("vcs", {})
        for key in ("clone_url", "web_url", "default_ref"):
            at(vcs, key, f"sources.{source.get('id')}.vcs.{key}")
    for target in result.get("authoring_targets", []):
        for key in ("web_url", "repository", "ref"):
            at(target, key, f"authoring_targets.{target.get('id')}.{key}")
    for link_class in ("issues", "navigation"):
        settings = result.get("links", {}).get(link_class, {})
        for key in ("target_url", "url_template", "target_ref", "source_page_base_url"):
            at(settings, key, f"links.{link_class}.{key}")
        for list_key in ("source_prefixes", "relative_prefixes"):
            if list_key in settings:
                settings[list_key] = [
                    resolve(value, f"links.{link_class}.{list_key}")
                    for value in settings[list_key]
                ]
    for component in result.get("components", []):
        for link_class in ("issues", "navigation"):
            settings = component.get("link_overrides", {}).get(link_class, {})
            for key in ("target_url", "url_template", "target_ref", "source_page_base_url"):
                at(settings, key, f"components.{component.get('id')}.link_overrides.{link_class}.{key}")
            for list_key in ("source_prefixes", "relative_prefixes"):
                if list_key in settings:
                    settings[list_key] = [
                        resolve(value, f"components.{component.get('id')}.link_overrides.{link_class}.{list_key}")
                        for value in settings[list_key]
                    ]
    site = result.get("site", {})
    for key in ("base_url", "base_path", "output_directory", "components_root", "version", "canonical_base_url", "root_index_target", "not_found_path"):
        at(site, key, f"site.{key}")
    workspace = result.get("workspace", {})
    at(workspace, "temp_root", "workspace.temp_root")
    for channel, settings in result.get("communication", {}).items():
        for key in ("address", "url_template", "subject", "body"):
            at(settings, key, f"communication.{channel}.{key}")
        for key in ("cc", "bcc"):
            if key in settings:
                settings[key] = [resolve(value, f"communication.{channel}.{key}") for value in settings[key]]
    for component in result.get("components", []):
        for channel, settings in component.get("link_overrides", {}).get("communication", {}).items():
            for key in ("address", "url_template", "subject", "body"):
                at(settings, key, f"components.{component.get('id')}.link_overrides.communication.{channel}.{key}")
            for key in ("cc", "bcc"):
                if key in settings:
                    settings[key] = [resolve(value, f"components.{component.get('id')}.link_overrides.communication.{channel}.{key}") for value in settings[key]]
    for target in result.get("publishing_targets", []):
        at(target, "output_path", f"publishing_targets.{target.get('id')}.output_path")
    return result

def resolve_profiles(raw: dict[str, Any], profile_names: list[str] | None = None) -> dict[str, Any]:
    config = copy.deepcopy(raw)
    profiles = config.pop("profiles", {})
    if not isinstance(profiles, dict):
        raise ConfigError("profiles must be a mapping of profile names to mappings")
    for profile_name, profile in profiles.items():
        if not isinstance(profile_name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", profile_name):
            raise ConfigError(f"Profile name {profile_name!r} must be a lower-case identifier")
        if not isinstance(profile, dict):
            raise ConfigError(f"Profile {profile_name!r} must be a named mapping")
    active = profile_names or config.get("active_profiles", [])
    config.pop("active_profiles", None)
    if not isinstance(active, list) or any(
        not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name)
        for name in active
    ):
        raise ConfigError("active_profiles/--profile must contain lower-case profile identifiers")
    if len(active) != len(set(active)):
        raise ConfigError("A profile may be selected only once in one invocation")
    for name in active:
        if name not in profiles:
            raise ConfigError(f"Unknown profile: {name}")
        config = deep_merge(config, profiles[name])
    return config


def _unique(items: list[dict[str, Any]], where: str) -> None:
    ids = [item.get("id") for item in items]
    if len(ids) != len(set(ids)):
        raise ConfigError(f"Duplicate id in {where}")



def _validate_git_ref(value: str, ref_type: str, where: str) -> None:
    if not isinstance(value, str) or not value or value.startswith("-") or "\x00" in value or any(ch.isspace() for ch in value):
        raise ConfigError(f"{where} is missing or is not a safe Git ref")
    if ref_type not in {"auto", "branch", "tag", "commit"}:
        raise ConfigError(f"{where} has unsupported ref_type {ref_type!r}")
    if ref_type == "commit":
        if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", value):
            raise ConfigError(f"{where} commit ref must be a full 40- or 64-character SHA")
        return
    if value.startswith("refs/"):
        if ref_type == "branch" and not value.startswith("refs/heads/"):
            raise ConfigError(f"{where} branch ref must use refs/heads/")
        if ref_type == "tag" and not value.startswith("refs/tags/"):
            raise ConfigError(f"{where} tag ref must use refs/tags/")
        candidates = [value]
    elif ref_type == "branch":
        candidates = [f"refs/heads/{value}"]
    elif ref_type == "tag":
        candidates = [f"refs/tags/{value}"]
    else:
        candidates = [f"refs/heads/{value}", f"refs/tags/{value}"]
    for candidate in candidates:
        try:
            checked = run_process(["git", "check-ref-format", candidate], max_output_bytes=0)
        except OSError as exc:
            raise ConfigError(f"{where} cannot be checked because Git is unavailable: {exc}") from exc
        if checked.returncode == 0:
            return
    raise ConfigError(f"{where} is not a valid Git {ref_type} ref: {value!r}")


def _repository_host(value: str) -> str | None:
    if value.startswith("git@") and ":" in value:
        return value[4:].split(":", 1)[0].lower()
    parsed = urlparse(value)
    return parsed.hostname.lower() if parsed.hostname else None


def _validate_allowed_hosts(allowed_hosts: list[str] | None, where: str) -> None:
    """Validate exact host allowlists; wildcard entries are deliberately unsupported."""
    if allowed_hosts is None:
        return
    if not isinstance(allowed_hosts, list):
        raise ConfigError(f"{where} must be a list of exact hostnames")
    for host in allowed_hosts:
        if not isinstance(host, str) or not host or host.strip() != host:
            raise ConfigError(f"{where} must contain non-empty exact hostnames")
        if host == "*" or "*" in host:
            raise ConfigError(f"{where} does not support wildcard hosts; list each permitted hostname explicitly")
        if any(ch in host for ch in "/\\:@?#") or re.search(r"\s", host):
            raise ConfigError(f"{where} entry {host!r} must be a hostname only, without scheme, path, port or credentials")
        normalized = host[1:-1] if host.startswith("[") and host.endswith("]") else host
        labels = normalized.split(".")
        label_pattern = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")
        if (not normalized or len(normalized) > 253
                or any(not label_pattern.fullmatch(label) for label in labels)):
            raise ConfigError(f"{where} entry {host!r} is not a valid hostname")


def _is_reserved_live_origin(value: str) -> bool:
    """Return true for reserved example/test-only origins, not public origins."""
    host = (urlparse(value).hostname or "").rstrip(".").lower()
    if not host:
        return False
    # Documentation domains are reserved with all their subdomains, not just
    # the four exact apex names. The special-use suffixes are likewise closed.
    reserved_roots = ("example.com", "example.net", "example.org", "localhost")
    if any(host == root or host.endswith("." + root) for root in reserved_roots):
        return True
    if any(host == suffix or host.endswith("." + suffix)
           for suffix in ("example", "invalid", "test", "localhost")):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    # A live public-site origin must not point at loopback, private, link-local,
    # documentation-only, multicast or otherwise non-global IP address space.
    return not address.is_global


def reserved_live_site_origin_errors(config: dict[str, Any]) -> list[str]:
    """Return reserved/non-public origins that must not back a live publish.

    This reuses the stricter validator for reserved suffixes and non-global IP ranges.
    It is also used by workflow generation as a defense-in-depth check for callers
    that pass an in-memory mapping without first invoking load_config().
    """
    if bool(config.get("publishing", {}).get("dry_run", True)):
        return []
    site = config.get("site", {})
    return [
        f"{name} uses a reserved example/test or non-global IP origin"
        for name, value in (("site.base_url", site.get("base_url")),
                            ("site.canonical_base_url", site.get("canonical_base_url")))
        if value and _is_reserved_live_origin(str(value))
    ]


def _validate_repository_url(value: str, where: str, allowed_hosts: list[str] | None = None) -> None:
    if not value:
        raise ConfigError(f"{where} is required")
    if re.search(r"\s", value):
        raise ConfigError(f"{where} contains whitespace")
    parsed = urlparse(value)
    if parsed.username or parsed.password:
        raise ConfigError(f"{where} must not embed credentials; use an explicit auth secret reference")
    if parsed.scheme == "file":
        raise ConfigError(f"{where} must not use file://; use an explicit local filesystem path instead")
    if parsed.scheme and parsed.scheme not in {"https", "ssh"}:
        raise ConfigError(f"{where} uses unsupported or insecure URL scheme {parsed.scheme!r}")
    if parsed.query or parsed.fragment:
        raise ConfigError(f"{where} must not contain query strings or fragments")
    # SCP-style SSH remotes (git@host:group/repo.git) have no parsed URL scheme.
    if value.startswith("git@") and ":" in value:
        pass
    elif parsed.scheme in {"https", "ssh"} and not parsed.hostname:
        raise ConfigError(f"{where} must include a hostname")
    host = _repository_host(value)
    if allowed_hosts:
        _validate_allowed_hosts(allowed_hosts, f"{where}.allowed_hosts")
        if host is None:
            raise ConfigError(f"{where} has no hostname to validate against allowed_hosts")
        if host not in {x.lower().strip("[]") for x in allowed_hosts}:
            raise ConfigError(f"{where} host {host!r} is not in its configured allowed_hosts list")


def _validate_channel_override(channel: str, settings: dict[str, Any], where: str) -> None:
    """Validate the dynamic communication-channel contract without silent no-ops."""
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", channel):
        raise ConfigError(f"{where}: channel name must match ^[a-z][a-z0-9_-]{{0,63}}$")
    if not isinstance(settings, dict):
        raise ConfigError(f"{where}: channel configuration must be a mapping")

    # provider/provider_label are labels for humans and migrations only. Neither
    # selects an adapter; actual behavior comes from URL templates or channel kind.
    if "provider" in settings and "provider_label" in settings:
        raise ConfigError(f"{where}: use provider_label or legacy provider, not both")
    for label_key in ("provider", "provider_label"):
        if label_key in settings and (not isinstance(settings[label_key], str) or not settings[label_key].strip()):
            raise ConfigError(f"{where}.{label_key} must be a non-empty display label")

    mode = settings.get("mode")
    if mode not in {"inherit", "override", "disable"}:
        raise ConfigError(f"{where}.mode must be inherit, override or disable")

    security_channels = {"security", "security_reports", "vulnerability_reports"}
    privacy_keys = {"private_target", "private_target_attested"}
    common_keys = {"mode", "provider", "provider_label", "require_markers"}
    if mode != "override":
        unexpected = set(settings) - common_keys
        if unexpected:
            raise ConfigError(
                f"{where}: {mode} mode cannot carry inactive override settings: "
                + ", ".join(sorted(unexpected))
            )
        return


    if channel == "email":
        allowed = common_keys | {"address", "cc", "bcc", "subject", "body", "target"}
        unexpected = set(settings) - allowed
        if unexpected:
            raise ConfigError(f"{where}: email override does not support: " + ", ".join(sorted(unexpected)))
        from email.utils import parseaddr
        address = settings.get("address", "")
        if not isinstance(address, str):
            raise ConfigError(f"{where}: override requires one plain mailbox address")
        address = address.strip()
        _, parsed = parseaddr(address)
        if not address or parsed != address or "\r" in address or "\n" in address:
            raise ConfigError(f"{where}: override requires one plain mailbox address")
        for field in ("cc", "bcc"):
            values = settings.get(field, [])
            if not isinstance(values, list):
                raise ConfigError(f"{where}.{field} must be a list of mailbox addresses")
            for mailbox in values:
                if not isinstance(mailbox, str):
                    raise ConfigError(f"{where}: invalid mailbox in {field}")
                _, parsed_mailbox = parseaddr(mailbox)
                if parsed_mailbox != mailbox or "\r" in mailbox or "\n" in mailbox:
                    raise ConfigError(f"{where}: invalid mailbox in {field}")
    else:
        allowed = common_keys | {"url_template", "target", "query", "allowed_hosts"} | privacy_keys
        unexpected = set(settings) - allowed
        if unexpected:
            raise ConfigError(f"{where}: URL-channel override does not support: " + ", ".join(sorted(unexpected)))
        template = settings.get("url_template", "")
        if not isinstance(template, str) or not template:
            raise ConfigError(f"{where}: override requires url_template")
        if not template.startswith("https://"):
            raise ConfigError(f"{where}: override URL template must start with https://")
        query = settings.get("query", {})
        if not isinstance(query, dict):
            raise ConfigError(f"{where}.query must be a mapping")
        invalid_query_keys = [key for key in query if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key)]
        if invalid_query_keys:
            raise ConfigError(
                f"{where}.query keys must match ^[a-z][a-z0-9_]{{0,63}}$: "
                + ", ".join(repr(key) for key in invalid_query_keys)
            )
        if channel not in security_channels and privacy_keys & set(settings):
            raise ConfigError(f"{where}: privacy attestation fields are only valid for security-report channels")

    if channel in security_channels:
        legacy = settings.get("private_target")
        attested = settings.get("private_target_attested")
        if legacy is not None and attested is not None and bool(legacy) != bool(attested):
            raise ConfigError(f"{where}: private_target and private_target_attested conflict")
        if not (attested is True or legacy is True):
            raise ConfigError(
                f"{where}: security reporting override requires private_target_attested: true "
                "(legacy private_target: true is accepted as an operator attestation only; privacy is not verified)"
            )


def _validate_routed_link(link_class: str, settings: dict[str, Any], where: str) -> None:
    """Validate one independently configured issue or neighbor-link destination."""
    if not isinstance(settings, dict):
        raise ConfigError(f"{where} must be a mapping")
    mode = settings.get("mode")
    if mode not in {"inherit", "override", "disable"}:
        raise ConfigError(f"{where}.mode must be inherit, override or disable")
    common = {"mode", "require_markers"}
    allowed = common | {
        "target_url", "target_ref", "url_template", "source_prefixes", "relative_prefixes",
        "source_page_base_url", "mapping",
        "allowed_hosts", "unresolved_policy", "target",
    }
    unexpected = set(settings) - allowed
    if unexpected:
        raise ConfigError(f"{where} has unsupported properties: " + ", ".join(sorted(unexpected)))

    if mode == "inherit":
        inactive = set(settings) - common
        if inactive:
            raise ConfigError(
                f"{where}: inherit mode cannot carry inactive destination settings: "
                + ", ".join(sorted(inactive))
            )
        return

    prefixes = settings.get("source_prefixes", [])
    if not isinstance(prefixes, list) or any(not isinstance(x, str) or not x.strip() for x in prefixes):
        raise ConfigError(f"{where}.source_prefixes must be a list of non-empty URL/path prefixes")
    if not prefixes:
        raise ConfigError(f"{where}.source_prefixes must explicitly identify incoming {link_class} links")
    for prefix in prefixes:
        parsed_prefix = urlparse(prefix)
        if parsed_prefix.scheme:
            if (parsed_prefix.scheme != "https" or not parsed_prefix.netloc or parsed_prefix.username
                    or parsed_prefix.password or parsed_prefix.query or parsed_prefix.fragment):
                raise ConfigError(f"{where}.source_prefixes entries must be HTTPS URL prefixes without credentials/query/fragment")
        elif not prefix.startswith("/") or ".." in PurePosixPath(prefix).parts or "?" in prefix or "#" in prefix:
            raise ConfigError(f"{where}.source_prefixes relative entries must be safe root-relative URL paths")
    relative_prefixes = settings.get("relative_prefixes", [])
    if relative_prefixes and link_class != "navigation":
        raise ConfigError(f"{where}.relative_prefixes are supported only for navigation links")
    if not isinstance(relative_prefixes, list) or any(not isinstance(x, str) or not x for x in relative_prefixes):
        raise ConfigError(f"{where}.relative_prefixes must be a list of non-empty relative href prefixes")
    for prefix in relative_prefixes:
        if (urlparse(prefix).scheme or urlparse(prefix).netloc or prefix.startswith(("/", "?", "#"))
                or "\\" in prefix or "?" in prefix or "#" in prefix or "\x00" in prefix):
            raise ConfigError(f"{where}.relative_prefixes entries must be safe relative href prefixes")
        parts = [part for part in prefix.split("/") if part]
        seen_content = False
        for part in parts:
            if part == ".." and seen_content:
                raise ConfigError(f"{where}.relative_prefixes may contain parent segments only at the beginning")
            if part not in {".", ".."}:
                seen_content = True
    source_page_base = settings.get("source_page_base_url")
    if relative_prefixes:
        parsed_base = urlparse(source_page_base or "")
        if parsed_base.scheme != "https" or not parsed_base.netloc or parsed_base.username or parsed_base.password or parsed_base.query or parsed_base.fragment:
            raise ConfigError(f"{where}.source_page_base_url must be an explicit HTTPS base URL when relative_prefixes are configured")
    elif source_page_base is not None:
        parsed_base = urlparse(source_page_base)
        if parsed_base.scheme != "https" or not parsed_base.netloc or parsed_base.username or parsed_base.password or parsed_base.query or parsed_base.fragment:
            raise ConfigError(f"{where}.source_page_base_url must be an HTTPS URL without credentials/query/fragment")

    if mode == "disable":
        inactive = set(settings) - (common | {"source_prefixes", "relative_prefixes", "source_page_base_url"})
        if inactive:
            raise ConfigError(
                f"{where}: disable mode cannot carry destination settings: "
                + ", ".join(sorted(inactive))
            )
        return

    target_url = settings.get("target_url", "")
    if not isinstance(target_url, str):
        raise ConfigError(f"{where}.target_url must be an explicit HTTPS destination URL")
    parsed_target = urlparse(target_url)
    if (parsed_target.scheme != "https" or not parsed_target.netloc
            or parsed_target.username or parsed_target.password or parsed_target.query or parsed_target.fragment
            or any(segment in {".", ".."} for segment in unquote(parsed_target.path).split("/"))):
        raise ConfigError(f"{where}.target_url must be an explicit safe HTTPS destination URL without credentials/query/fragment")
    template = settings.get("url_template", "")
    if not isinstance(template, str) or not template or "{target_url}" not in template:
        raise ConfigError(f"{where}.url_template must be non-empty and contain {{target_url}}")
    if "{path}" not in template:
        raise ConfigError(f"{where}.url_template must contain {{path}} so the incoming link remains specific to its target file or route")
    if not (template.startswith("https://") or template.startswith("{target_url}")):
        raise ConfigError(f"{where}.url_template must start with https:// or the validated {{target_url}} variable")
    if "{target_ref}" in template:
        _validate_git_ref(settings.get("target_ref", ""), "branch", f"{where}.target_ref")
    elif settings.get("target_ref"):
        _validate_git_ref(settings["target_ref"], "branch", f"{where}.target_ref")
    if settings.get("unresolved_policy", "fail") not in {"fail", "omit"}:
        raise ConfigError(f"{where}.unresolved_policy must be fail or omit")
    if settings.get("target") not in (None, "_self", "_blank"):
        raise ConfigError(f"{where}.target must be _self or _blank")
    _validate_allowed_hosts(settings.get("allowed_hosts", []), f"{where}.allowed_hosts")
    mapping = settings.get("mapping", {})
    if not isinstance(mapping, dict):
        raise ConfigError(f"{where}.mapping must be a mapping")
    for name in ("source_prefix", "target_prefix"):
        value = mapping.get(name, "").replace("\\", "/")
        if value:
            _safe_relative(value, f"{where}.mapping.{name}")
    strip_count = mapping.get("strip_leading_segments", 0)
    if isinstance(strip_count, bool) or not isinstance(strip_count, int) or strip_count < 0 or strip_count > 64:
        raise ConfigError(f"{where}.mapping.strip_leading_segments must be an integer between 0 and 64")
    collapse_index = mapping.get("collapse_index_file", "")
    if collapse_index:
        collapse_path = _safe_relative(collapse_index, f"{where}.mapping.collapse_index_file")
        if len(collapse_path.parts) != 1:
            raise ConfigError(f"{where}.mapping.collapse_index_file must be a single filename")
    for rule in mapping.get("rules", []):
        for name in ("source", "target"):
            _safe_relative(rule[name].replace("\\", "/"), f"{where}.mapping.rules[].{name}")


def _safe_relative(value: str, where: str, *, allow_dot: bool = False) -> PurePosixPath:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or (not allow_dot and (not path.parts or path.as_posix() in {"", "."})):
        raise ConfigError(f"{where} must be a safe repository-relative path")
    if any("\x00" in part for part in path.parts):
        raise ConfigError(f"{where} must not contain NUL characters")
    if any(":" in part for part in path.parts):
        raise ConfigError(f"{where} must not be drive-qualified")
    # A repository's .git directory is control data, not an ordinary content
    # directory. Never let configurable inputs point into it or publish output
    # beneath it (including case variants on case-insensitive filesystems).
    if any(part.casefold() == ".git" for part in path.parts):
        raise ConfigError(f"{where} must not reference Git metadata (.git)")
    if any(part in {"", "."} for part in path.parts) and not allow_dot:
        raise ConfigError(f"{where} must not contain empty or dot path segments")
    return path


def _validate_https_url(value: str, where: str, *, allow_path: bool = True) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ConfigError(f"{where} must be an absolute HTTPS URL without credentials")
    if parsed.query or parsed.fragment:
        raise ConfigError(f"{where} must not contain a query string or fragment")
    if not allow_path and parsed.path not in {"", "/"}:
        raise ConfigError(f"{where} must be an HTTPS origin without a path")



def _expandable_environment_paths(config: dict[str, Any]) -> set[tuple[str | int, ...]]:
    """Paths whose plain ${NAME} references are expanded from the host environment."""
    paths: set[tuple[str | int, ...]] = set()

    def add_fields(prefix: tuple[str | int, ...], values: Any, keys: tuple[str, ...]) -> None:
        if not isinstance(values, dict):
            return
        for key in keys:
            if key in values:
                paths.add(prefix + (key,))

    add_fields(("project",), config.get("project"), ("homepage_url", "repository_url", "logo", "favicon"))
    add_fields(("publisher",), config.get("publisher"), ("clone_url", "web_url", "ref"))
    for index, source in enumerate(config.get("sources", [])):
        if isinstance(source, dict):
            add_fields(("sources", index, "vcs"), source.get("vcs"), ("clone_url", "web_url", "default_ref"))
    for index, target in enumerate(config.get("authoring_targets", [])):
        if isinstance(target, dict):
            add_fields(("authoring_targets", index), target, ("web_url", "repository", "ref"))
    add_fields(("site",), config.get("site"), (
        "base_url", "base_path", "output_directory", "components_root", "version",
        "canonical_base_url", "root_index_target", "not_found_path",
    ))
    add_fields(("workspace",), config.get("workspace"), ("temp_root",))

    def add_communication(prefix: tuple[str | int, ...], mapping: Any) -> None:
        if not isinstance(mapping, dict):
            return
        for channel, settings in mapping.items():
            if not isinstance(settings, dict):
                continue
            channel_path = prefix + (channel,)
            add_fields(channel_path, settings, ("address", "url_template", "subject", "body"))
            for list_key in ("cc", "bcc"):
                values = settings.get(list_key)
                if isinstance(values, list):
                    for index, _ in enumerate(values):
                        paths.add(channel_path + (list_key, index))

    add_communication(("communication",), config.get("communication"))
    for index, component in enumerate(config.get("components", [])):
        if isinstance(component, dict):
            overrides = component.get("link_overrides", {})
            if isinstance(overrides, dict):
                add_communication(("components", index, "link_overrides", "communication"), overrides.get("communication"))
    for index, target in enumerate(config.get("publishing_targets", [])):
        if isinstance(target, dict):
            add_fields(("publishing_targets", index), target, ("output_path",))
    return paths


def _validate_environment_reference_paths(config: dict[str, Any], *, allow_missing_env: bool = False) -> None:
    expandable_paths = _expandable_environment_paths(config)
    adapter_environment_reference_paths: set[tuple[str | int, ...]] = set()
    for section in ("build_tasks", "publishing_targets"):
        for index, adapter in enumerate(config.get(section, [])):
            if not isinstance(adapter, dict):
                continue
            environment = adapter.get("environment", {})
            if isinstance(environment, dict):
                for env_key, value in environment.items():
                    match = _ENV_REFERENCE.fullmatch(value) if isinstance(value, str) else None
                    if match:
                        # Exact adapter references are checked later by the adapter-specific
                        # pass, which can provide the precise allowlist diagnostic.
                        adapter_environment_reference_paths.add((section, index, "environment", env_key))

    invalid: list[str] = []

    def walk(value: Any, path: tuple[str | int, ...] = ()) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, path + (str(key),))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, path + (index,))
        elif isinstance(value, str) and _ENV_REFERENCE.search(value):
            if path in adapter_environment_reference_paths:
                return
            if allow_missing_env and path in expandable_paths:
                return
            invalid.append("/" + "/".join(map(str, path)))

    walk(config)
    if invalid:
        raise ConfigError(
            "Unsupported or unallowlisted environment variable reference(s) at: "
            + ", ".join(invalid[:50])
            + ". Expand only documented configuration fields or use an exact allowlisted "
              "${NAME} reference in build_tasks[].environment / publishing_targets[].environment."
        )


def semantic_validate(config: dict[str, Any], *, allow_missing_env: bool = False) -> None:
    def scan_placeholders(value: Any, path: str = "") -> list[str]:
        found: list[str] = []
        if isinstance(value, dict):
            for key, item in value.items(): found.extend(scan_placeholders(item, f"{path}/{key}"))
        elif isinstance(value, list):
            for index, item in enumerate(value): found.extend(scan_placeholders(item, f"{path}/{index}"))
        elif isinstance(value, str) and _PLACEHOLDER.search(value):
            found.append(path or "/")
        return found
    unresolved = scan_placeholders(config)
    if unresolved:
        raise ConfigError("Unresolved configuration placeholders at: " + ", ".join(unresolved[:50]))
    _validate_environment_reference_paths(config, allow_missing_env=allow_missing_env)
    if config.get("schema_version") != 2:
        raise ConfigError("schema_version must be 2")
    timezone_name = config.get("project", {}).get("timezone")
    if timezone_name is not None:
        if not isinstance(timezone_name, str) or not timezone_name.strip():
            raise ConfigError("project.timezone must be a non-empty IANA timezone name when configured")
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ConfigError(
                f"project.timezone must name an installed IANA timezone (for example UTC or Europe/Berlin): {timezone_name!r}"
            ) from exc
    for key in ("sources", "authoring_targets", "components", "build_tasks", "publishing_targets"):
        _unique(config.get(key, []), key)

    publisher_url = config["publisher"].get("clone_url", "")
    _validate_allowed_hosts(config["publisher"].get("allowed_hosts"), "publisher.allowed_hosts")
    if not publisher_url or _PLACEHOLDER.search(publisher_url):
        raise ConfigError("publisher.clone_url is missing or still a placeholder")
    _validate_repository_url(publisher_url, "publisher.clone_url", config["publisher"].get("allowed_hosts"))
    publisher_ref = config["publisher"].get("ref", "")
    _validate_git_ref(publisher_ref, "auto", "publisher.ref")
    publisher_auth = config["publisher"].get("auth", {"mode": "none"})
    if publisher_auth.get("mode", "none") == "environment" and not publisher_auth.get("secret_env"):
        raise ConfigError("publisher.auth.mode=environment requires secret_env")
    if publisher_auth.get("mode", "none") == "environment" and publisher_auth.get("username_env"):
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", publisher_auth["username_env"]):
            raise ConfigError("publisher.auth.username_env must be an uppercase environment variable name")

    site = config["site"]
    if config.get("validation", {}).get("require_no_symlinks", True) is not True:
        raise ConfigError("validation.require_no_symlinks must remain true; public site publication never follows symlinks")
    for asset in site.get("static_assets", []):
        _safe_relative(asset["source"], "site.static_assets[].source")
        _safe_relative(asset["destination"], "site.static_assets[].destination")
    _validate_https_url(site.get("base_url", ""), "site.base_url", allow_path=False)
    if site.get("canonical_base_url"):
        _validate_https_url(site["canonical_base_url"], "site.canonical_base_url", allow_path=False)
    if config.get("publishing", {}).get("dry_run", True) is False:
        reserved_origins = [
            name for name, value in (("site.base_url", site.get("base_url", "")),
                                     ("site.canonical_base_url", site.get("canonical_base_url", "")))
            if value and _is_reserved_live_origin(value)
        ]
        if reserved_origins:
            raise ConfigError(
                "Live publishing is blocked for reserved example/test or non-global IP origins: "
                + ", ".join(reserved_origins)
                + ". Configure a real public HTTPS origin or keep publishing.dry_run: true."
            )
    _safe_relative(site.get("output_directory", ""), "site.output_directory")
    _safe_relative(site.get("components_root", ""), "site.components_root")
    not_found_path = site.get("not_found_path")
    if not_found_path:
        normalized_not_found = _safe_relative(not_found_path, "site.not_found_path").as_posix()
        if normalized_not_found in {"index.html", ".nojekyll", "build-manifest.json"}:
            raise ConfigError("site.not_found_path must not overwrite a reserved root output")
    for required_file in config.get("validation", {}).get("required_files", []):
        _safe_relative(required_file, "validation.required_files[]")
    redirect_schemes = {str(x).lower() for x in config.get("validation", {}).get("validate_redirect_schemes", ["https", "http"])}
    unsupported_redirect_schemes = redirect_schemes - {"https", "http"}
    if unsupported_redirect_schemes:
        raise ConfigError("validation.validate_redirect_schemes may contain only http and https: " + ", ".join(sorted(unsupported_redirect_schemes)))
    base_path = site.get("base_path", "").replace("\\", "/").strip("/")
    if base_path and ".." in PurePosixPath(base_path).parts:
        raise ConfigError("site.base_path must not contain parent path segments")
    if site.get("root_index_target"):
        root_target = site["root_index_target"]
        parsed_root = urlparse(root_target)
        if parsed_root.scheme and parsed_root.scheme.lower() not in redirect_schemes:
            raise ConfigError("site.root_index_target uses a scheme not allowed by validation.validate_redirect_schemes")
        if parsed_root.scheme and not parsed_root.netloc:
            raise ConfigError("site.root_index_target is a malformed absolute URL")
        if not parsed_root.scheme:
            _safe_relative(root_target, "site.root_index_target")
    if site.get("default_component") and site["default_component"] not in {x["id"] for x in config["components"]}:
        raise ConfigError("site.default_component must reference a configured component")

    source_ids = {x["id"] for x in config.get("sources", [])}
    authoring_ids = {x["id"] for x in config.get("authoring_targets", [])}
    task_ids = {x["id"] for x in config.get("build_tasks", [])}
    component_ids = {x["id"] for x in config.get("components", [])}

    subtree_prefixes: list[tuple[str, str]] = []
    for source in config.get("sources", []):
        integ = source["integration"]
        if integ["mode"] != "git_subtree":
            raise ConfigError(f"Source {source['id']}: only explicit git_subtree integration is supported in v2; no fallback is performed")
        prefix = _safe_relative(integ["prefix"], f"Source {source['id']}.integration.prefix")
        if prefix.parts[0] == ".git":
            raise ConfigError(f"Source {source['id']}: unsafe subtree prefix")
        prefix_text = prefix.as_posix().strip("/")
        for existing, existing_id in subtree_prefixes:
            if prefix_text == existing or prefix_text.startswith(existing + "/") or existing.startswith(prefix_text + "/"):
                raise ConfigError(f"Source subtree prefixes overlap: {source['id']} ({prefix_text}) and {existing_id} ({existing})")
        subtree_prefixes.append((prefix_text, source["id"]))
        vcs = source["vcs"]
        _validate_allowed_hosts(vcs.get("allowed_hosts"), f"sources.{source['id']}.vcs.allowed_hosts")
        if vcs.get("provider") != "git":
            raise ConfigError(f"Source {source['id']}: git_subtree requires vcs.provider=git; non-Git sources need a separate materialization adapter")
        clone_url = vcs.get("clone_url", "")
        if not clone_url or _PLACEHOLDER.search(clone_url):
            raise ConfigError(f"Source {source['id']}: clone_url is missing or still a placeholder")
        _validate_repository_url(clone_url, f"sources.{source['id']}.vcs.clone_url", vcs.get("allowed_hosts"))
        if vcs.get("web_url"):
            _validate_https_url(vcs["web_url"], f"sources.{source['id']}.vcs.web_url")
            web_host = (urlparse(vcs["web_url"]).hostname or "").lower()
            if vcs.get("allowed_hosts") and web_host not in {x.lower().strip("[]") for x in vcs["allowed_hosts"]}:
                raise ConfigError(f"sources.{source['id']}.vcs.web_url host {web_host!r} is not in its configured allowed_hosts list")
        # Git submodules are deliberately rejected: .gitmodules nested below a subtree
        # prefix is not automatically a superproject submodule definition.
        if vcs.get("submodules", False):
            raise ConfigError(f"Source {source['id']}: nested submodules need a dedicated materialization adapter; the core will not silently mis-handle them")
        if vcs.get("sparse_paths"):
            raise ConfigError(f"Source {source['id']}: sparse_paths is not supported by git_subtree; use a source adapter or a full subtree")
        _validate_git_ref(vcs.get("default_ref", ""), vcs.get("ref_type", "auto"),
                          f"Source {source['id']}.vcs.default_ref")
        if vcs.get("auth", {}).get("mode") == "environment" and not vcs.get("auth", {}).get("secret_env"):
            raise ConfigError(f"Source {source['id']}: auth.mode=environment requires secret_env")
        _safe_relative(source.get("root", "."), f"Source {source['id']}.root", allow_dot=True)
        if vcs.get("depth", 1) < 0:
            raise ConfigError(f"Source {source['id']}: depth cannot be negative")
        dispatch_sha_env = vcs.get("dispatch_sha_env")
        if dispatch_sha_env:
            if (not isinstance(dispatch_sha_env, str)
                    or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", dispatch_sha_env)
                    or dispatch_sha_env.startswith(("GITHUB_", "RUNNER_"))
                    or dispatch_sha_env in _WORKFLOW_RESERVED_ENV):
                raise ConfigError(
                    f"Source {source['id']}.vcs.dispatch_sha_env must be a non-reserved uppercase environment name"
                )

    # A repository_dispatch trigger is a narrowly-scoped cross-repository
    # source-update contract. Its identity and branch must match the selected
    # source clone URL and configured branch; its SHA is used as an immutable ref.
    dispatch = config.get("triggers", {}).get("repository_dispatch")
    if dispatch is not None:
        if not isinstance(dispatch, dict):
            raise ConfigError("triggers.repository_dispatch must be an object")
        event_type = dispatch.get("event_type")
        if not isinstance(event_type, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,99}", event_type):
            raise ConfigError("triggers.repository_dispatch.event_type must be 1-100 lower-case letters/digits/hyphens/underscores and start with a letter")
        source_id = dispatch.get("source_id")
        source = next((item for item in config.get("sources", []) if item.get("id") == source_id), None)
        if source is None:
            raise ConfigError("triggers.repository_dispatch.source_id must reference a configured source")
        repository = dispatch.get("source_repository")
        if not isinstance(repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ConfigError("triggers.repository_dispatch.source_repository must be owner/repository")
        branch = dispatch.get("source_branch")
        _validate_git_ref(branch, "branch", "triggers.repository_dispatch.source_branch")
        clone = urlparse(source["vcs"].get("clone_url", ""))
        clone_repository = clone.path.strip("/").removesuffix(".git")
        if clone.scheme != "https" or (clone.hostname or "").lower() != "github.com" or clone_repository.casefold() != repository.casefold():
            raise ConfigError(
                "triggers.repository_dispatch.source_repository must match the GitHub owner/repository in the selected source's vcs.clone_url"
            )
        if source["vcs"].get("default_ref") != branch:
            raise ConfigError("triggers.repository_dispatch.source_branch must match the selected source's vcs.default_ref")
        if not source["vcs"].get("dispatch_sha_env"):
            raise ConfigError("The selected repository-dispatch source must configure vcs.dispatch_sha_env")
        used_sha_envs = [item.get("vcs", {}).get("dispatch_sha_env") for item in config.get("sources", []) if item.get("vcs", {}).get("dispatch_sha_env")]
        if used_sha_envs.count(source["vcs"]["dispatch_sha_env"]) != 1:
            raise ConfigError("Each sources[].vcs.dispatch_sha_env must be unique")

    for task in config.get("build_tasks", []):
        if task.get("source_id") is not None and task["source_id"] not in source_ids:
            raise ConfigError(f"Task {task['id']}: unknown source_id")
        for dependency in task.get("depends_on", []):
            if dependency not in task_ids:
                raise ConfigError(f"Task {task['id']}: unknown dependency {dependency}")
        if task["adapter"] == "command" and not task.get("argv"):
            raise ConfigError(f"Task {task['id']}: command adapter requires argv")
        if task.get("retry", 0) and not task.get("retry_safe", False):
            raise ConfigError(f"Task {task['id']}: retry > 0 requires retry_safe: true")
        if task.get("working_directory_scope", "source") not in {"source", "publisher"}:
            raise ConfigError(f"Task {task['id']}: invalid working_directory_scope")
        task_pass = set(task.get("pass_environment", []))
        task_secret = set(task.get("secret_environment", []))
        for env_name in task_pass | task_secret | set(task.get("environment", {})):
            if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", env_name):
                raise ConfigError(f"Task {task['id']}: invalid environment variable name {env_name!r}")
        if task_pass & task_secret:
            raise ConfigError(f"Task {task['id']}: an environment variable cannot be both ordinary and secret")
        for env_name in task_pass:
            if _is_sensitive_env_name(env_name):
                raise ConfigError(f"Task {task['id']}: sensitive environment variable {env_name!r} must use secret_environment")
        for env_key, env_value in task.get("environment", {}).items():
            reference = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", env_value)
            if reference and reference.group(1) not in task_pass | task_secret:
                raise ConfigError(f"Task {task['id']}: environment variable {reference.group(1)!r} is not allowlisted")
            if _is_sensitive_env_name(env_key):
                if not reference or reference.group(1) not in task_secret:
                    raise ConfigError(f"Task {task['id']}: sensitive environment value {env_key!r} must reference secret_environment")

    for component in config.get("components", []):
        if component["source_id"] not in source_ids:
            raise ConfigError(f"Component {component['id']}: unknown source_id")
        if component.get("link_adapter") == "keycloak_asciidoc":
            source_cfg = next(item for item in config.get("sources", []) if item.get("id") == component["source_id"])
            if not source_cfg.get("vcs", {}).get("web_url"):
                raise ConfigError(
                    f"Component {component['id']}: keycloak_asciidoc requires an explicit sources[].vcs.web_url "
                    "separate from the authoring target"
                )
        if not isinstance(component.get("output_path"), str) or not component["output_path"].strip():
            raise ConfigError(f"Component {component['id']}.output_path must be a non-empty repository-relative path")
        _safe_relative(component["output_path"], f"Component {component['id']}.output_path")
        _safe_relative(component.get("index_file", "index.html"), f"Component {component['id']}.index_file")
        for required_file in component.get("required_output_files", []):
            _safe_relative(required_file, f"Component {component['id']}.required_output_files[]")
        if component.get("provenance_file"):
            _safe_relative(component["provenance_file"], f"Component {component['id']}.provenance_file")
        if component.get("archive_root"):
            _safe_relative(component["archive_root"], f"Component {component['id']}.archive_root", allow_dot=True)
        for task_id in component.get("tasks", []):
            if task_id not in task_ids:
                raise ConfigError(f"Component {component['id']}: unknown build task {task_id}")
        fallback = component.get("fallback", {})
        if fallback.get("mode") in {"redirect", "inherit"} and not fallback.get("url"):
            raise ConfigError(f"Component {component['id']}: {fallback.get('mode')} fallback requires an explicit url")
        if fallback.get("mode") in {"redirect", "inherit"}:
            parsed_fallback = urlparse(fallback["url"])
            if parsed_fallback.scheme.lower() not in redirect_schemes or not parsed_fallback.netloc or parsed_fallback.username or parsed_fallback.password:
                raise ConfigError(f"Component {component['id']}: fallback URL must use an allowed absolute HTTP(S) scheme without credentials")
        overrides = component.get("link_overrides", {})
        component_edit = overrides.get("edit")
        if component_edit and component_edit.get("mode") == "override" and component_edit.get("target_id") not in authoring_ids:
            raise ConfigError(f"Component {component['id']}: edit override references an unknown authoring target")
        for link_class in ("issues", "navigation"):
            if link_class in overrides:
                _validate_routed_link(
                    link_class, overrides[link_class],
                    f"components.{component['id']}.link_overrides.{link_class}",
                )
        for channel, settings in overrides.get("communication", {}).items():
            _validate_channel_override(channel, settings, f"components.{component['id']}.link_overrides.communication.{channel}")
            _validate_allowed_hosts(settings.get("allowed_hosts", []),
                                    f"components.{component['id']}.link_overrides.communication.{channel}.allowed_hosts")

    for target in config.get("authoring_targets", []):
        if "provider" in target and "provider_label" in target:
            raise ConfigError(
                f"Authoring target {target['id']}: use provider_label or legacy provider, not both"
            )
        for label_key in ("provider", "provider_label"):
            if label_key in target and (not isinstance(target[label_key], str) or not target[label_key].strip()):
                raise ConfigError(f"Authoring target {target['id']}.{label_key} must be a non-empty display label")
        if target.get("source_id") and target["source_id"] not in source_ids:
            raise ConfigError(f"Authoring target {target['id']}: unknown source_id")
        web_url = target.get("web_url", "")
        parsed_web = urlparse(web_url)
        if parsed_web.scheme != "https" or not parsed_web.netloc or parsed_web.username or parsed_web.password or parsed_web.query or parsed_web.fragment:
            raise ConfigError(f"Authoring target {target['id']}: web_url must be an HTTPS repository URL without credentials/query/fragment")
        template = target.get("edit_url_template", "")
        for required_token in ("{web_url}", "{ref}", "{path}"):
            if required_token not in template:
                raise ConfigError(f"Authoring target {target['id']}: edit_url_template must explicitly contain {required_token}")
        _validate_git_ref(target.get("ref", ""), target.get("ref_type", "branch"),
                          f"Authoring target {target['id']}.ref")
        mapping = target.get("mapping", {})
        for name in ("source_prefix", "target_prefix"):
            value = mapping.get(name, "").replace("\\", "/")
            if value:
                _safe_relative(value, f"Authoring target {target['id']}.mapping.{name}")
        strip_count = mapping.get("strip_leading_segments", 0)
        if isinstance(strip_count, bool) or not isinstance(strip_count, int) or strip_count < 0 or strip_count > 64:
            raise ConfigError(f"Authoring target {target['id']}.mapping.strip_leading_segments must be an integer between 0 and 64")
        collapse_index = mapping.get("collapse_index_file", "")
        if collapse_index:
            collapse_path = _safe_relative(collapse_index, f"Authoring target {target['id']}.mapping.collapse_index_file")
            if len(collapse_path.parts) != 1:
                raise ConfigError(f"Authoring target {target['id']}.mapping.collapse_index_file must be a single filename")
        for rule in mapping.get("rules", []):
            for name in ("source", "target"):
                value = rule[name].replace("\\", "/")
                _safe_relative(value, f"Authoring target {target['id']}.mapping.rules[].{name}")

    links = config.get("links", {})
    edit = links.get("edit", {"mode": "inherit"})
    if edit["mode"] == "override" and edit.get("target_id") not in authoring_ids:
        raise ConfigError("links.edit.override requires an existing authoring target_id")
    for link_class in ("issues", "navigation"):
        if link_class in links:
            _validate_routed_link(link_class, links[link_class], f"links.{link_class}")
    for channel, settings in config.get("communication", {}).items():
        _validate_channel_override(channel, settings, f"communication.{channel}")
        _validate_allowed_hosts(settings.get("allowed_hosts", []), f"communication.{channel}.allowed_hosts")

    workflow = config.get("workflow", {})
    if workflow.get("file"):
        _safe_relative(workflow["file"], "workflow.file")
    if workflow.get("config_file"):
        _safe_relative(workflow["config_file"], "workflow.config_file")
    for env_name, secret_name in workflow.get("secrets", {}).items():
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", env_name) or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", secret_name):
            raise ConfigError("workflow.secrets keys and values must be uppercase environment/secret identifiers")
        if (env_name.startswith(("GITHUB_", "RUNNER_", "CI_", "GITLAB_"))
                or env_name in _WORKFLOW_RESERVED_ENV):
            raise ConfigError(f"workflow.secrets cannot export reserved runner environment variable {env_name}")
    for env_name, env_value in workflow.get("environment", {}).items():
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", env_name):
            raise ConfigError(f"workflow.environment has invalid environment variable name {env_name!r}")
        if (env_name.startswith(("GITHUB_", "RUNNER_", "CI_", "GITLAB_"))
                or env_name in _WORKFLOW_RESERVED_ENV):
            raise ConfigError(f"workflow.environment cannot override reserved runner variable {env_name}")
        if _is_sensitive_env_name(env_name):
            raise ConfigError(f"workflow.environment cannot contain sensitive variable {env_name}; use workflow.secrets")
        if ("\n" in env_value or "\r" in env_value or "${{" in env_value
                or (workflow.get("provider") == "gitlab_ci" and "$" in env_value)):
            raise ConfigError(f"workflow.environment.{env_name} must be a literal single-line value; use workflow.secrets for secrets")

    publishing_by_id = {x["id"]: x for x in config["publishing_targets"]}
    publish_id = config["publishing"].get("target_id")
    if publish_id not in publishing_by_id:
        raise ConfigError("publishing.target_id must refer to a configured publishing_target")
    target = publishing_by_id[publish_id]
    if target["adapter"] == "command" and not target.get("argv"):
        raise ConfigError("Command publishing adapter requires argv")
    if target["adapter"] != "command" and any(
        target.get(key) for key in ("argv", "environment", "pass_environment", "secret_environment")
    ):
        raise ConfigError(f"Publishing target {target['id']}: argv/environment settings require adapter=command")
    target_pass = set(target.get("pass_environment", []))
    target_secret = set(target.get("secret_environment", []))
    if target_pass & target_secret:
        raise ConfigError(f"Publishing target {target['id']}: an environment variable cannot be both ordinary and secret")
    for env_name in target_pass:
        if _is_sensitive_env_name(env_name):
            raise ConfigError(f"Publishing target {target['id']}: sensitive environment variable {env_name!r} must use secret_environment")
    for env_name in target_pass | target_secret | set(target.get("environment", {})):
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", env_name):
            raise ConfigError(f"Publishing target {target['id']}: invalid environment variable name {env_name!r}")
    for env_key, env_value in target.get("environment", {}).items():
        reference = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", env_value)
        if reference and reference.group(1) not in target_pass | target_secret:
            raise ConfigError(f"Publishing target {target['id']}: environment variable {reference.group(1)} is not allowlisted")
        if _is_sensitive_env_name(env_key):
            if not reference or reference.group(1) not in target_secret:
                raise ConfigError(f"Publishing target {target['id']}: sensitive environment value {env_key!r} must reference secret_environment")
    if target["adapter"] == "filesystem":
        destination = Path(target["output_path"]).expanduser()
        if not destination.is_absolute() and not target.get("allow_external_destination", False):
            _safe_relative(target["output_path"], "publishing_targets[].output_path")
    if target["adapter"] == "artifact":
        target_output = _safe_relative(
            target["output_path"], f"publishing_targets.{target['id']}.output_path"
        )
        site_output = _safe_relative(config["site"]["output_directory"], "site.output_directory")
        if target_output != site_output:
            raise ConfigError(
                f"Artifact publishing target {target['id']} output_path ({target_output}) must match "
                f"site.output_directory ({site_output}); the configured CI Pages workflow uploads site.output_directory"
            )
    workflow_provider = config.get("workflow", {}).get("provider")
    if workflow_provider in {"github_actions", "gitlab_ci"} and target["adapter"] != "artifact":
        target_name = "GitHub Pages" if workflow_provider == "github_actions" else "GitLab Pages"
        raise ConfigError(f"The generated {target_name} workflow requires a publishing target with adapter=artifact")
    if workflow_provider == "gitlab_ci":
        if config.get("workflow", {}).get("python_version", "3.13") not in {"3.11", "3.12", "3.13"}:
            raise ConfigError("GitLab workflow.python_version must be one of 3.11, 3.12 or 3.13")
        if config.get("triggers", {}).get("workflow_call"):
            raise ConfigError("GitLab CI does not support triggers.workflow_call")

    # Component dependency validation and cycle detection.
    component_graph = {x["id"]: set(x.get("dependencies", [])) for x in config.get("components", [])}
    for cid, deps in component_graph.items():
        unknown_deps = deps - component_ids
        if unknown_deps:
            raise ConfigError(f"Component {cid}: unknown dependencies {', '.join(sorted(unknown_deps))}")
    cvisiting: set[str] = set()
    cvisited: set[str] = set()
    def visit_component(node: str) -> None:
        if node in cvisiting: raise ConfigError(f"Component dependency cycle detected at {node}")
        if node in cvisited: return
        cvisiting.add(node)
        for dep in component_graph[node]: visit_component(dep)
        cvisiting.remove(node)
        cvisited.add(node)
    for node in component_graph: visit_component(node)

    # Route uniqueness and path safety are validated before any working directory is created.
    routes = [PurePosixPath(x["route"].replace("\\", "/")) for x in config.get("components", [])]
    seen_routes: set[str] = set()
    for route in routes:
        if (route.is_absolute() or ".." in route.parts or not route.parts
                or any("\x00" in part or ":" in part or part.casefold() == ".git" for part in route.parts)):
            raise ConfigError(f"Unsafe component route: {route}")
        normalized_route = route.as_posix().casefold()
        if normalized_route in seen_routes:
            raise ConfigError(f"Duplicate component route: {route}")
        seen_routes.add(normalized_route)
    site = config.get("site", {})
    route_template = site.get("component_path_template", "{components_root}/{version}/{route}")
    actual_routes: dict[str, str] = {}
    for component in config.get("components", []):
        values = {
            "components_root": str(site.get("components_root", "components")).strip("/"),
            "locale": component.get("locale") or config["project"]["locale"],
            "version": component.get("version") or site.get("version", "current"),
            "route": component["route"].strip("/"),
            "component_id": component["id"],
        }
        try:
            actual = PurePosixPath(route_template.format_map(values))
        except KeyError as exc:
            raise ConfigError(f"site.component_path_template has unknown variable {exc}") from exc
        if (actual.is_absolute() or ".." in actual.parts or not actual.parts
                or any("\x00" in part or ":" in part or part.casefold() == ".git" for part in actual.parts)):
            raise ConfigError(f"Rendered component route is unsafe for {component['id']}: {actual}")
        rendered = actual.as_posix()
        rendered_key = rendered.casefold()
        if rendered_key in actual_routes:
            raise ConfigError(f"Components {actual_routes[rendered_key]} and {component['id']} map to the same site route {rendered}")
        for existing_route, existing_id in actual_routes.items():
            if (rendered_key.startswith(existing_route.rstrip("/") + "/")
                    or existing_route.startswith(rendered_key.rstrip("/") + "/")):
                raise ConfigError(
                    f"Component routes overlap: {existing_id} ({existing_route}) and "
                    f"{component['id']} ({rendered_key})"
                )
        actual_routes[rendered_key] = component["id"]
        if site.get("locales") and values["locale"] not in site["locales"]:
            raise ConfigError(f"Component {component['id']} uses locale {values['locale']!r} outside site.locales")
        if site.get("versions") and values["version"] not in site["versions"]:
            raise ConfigError(f"Component {component['id']} uses version {values['version']!r} outside site.versions")
    index_template = site.get("version_index_path_template", "{components_root}/{version}/index.html")
    index_paths: set[str] = set()
    for component in config.get("components", []):
        locale = component.get("locale") or config["project"]["locale"]
        version = component.get("version") or site.get("version", "current")
        try:
            index_rel = PurePosixPath(index_template.format_map({
                "components_root": str(site.get("components_root", "components")).strip("/"),
                "locale": locale, "version": version,
            }))
        except KeyError as exc:
            raise ConfigError(f"site.version_index_path_template has unknown variable {exc}") from exc
        if (index_rel.is_absolute() or ".." in index_rel.parts
                or any("\x00" in part or ":" in part or part.casefold() == ".git" for part in index_rel.parts)):
            raise ConfigError(f"Unsafe version index path: {index_rel}")
        index_paths.add(index_rel.as_posix())
    index_paths_folded = {x.casefold() for x in index_paths}
    for route in actual_routes:
        if route in index_paths_folded or any(index.startswith(route + "/") for index in index_paths_folded):
            raise ConfigError(f"Component route {route!r} overlaps a generated version index")

    def overlaps(left: str, right: str) -> bool:
        return left == right or left.startswith(right.rstrip("/") + "/") or right.startswith(left.rstrip("/") + "/")

    reserved_destinations = {"index.html", ".nojekyll", "build-manifest.json", *index_paths, *actual_routes}
    if not_found_path:
        not_found = _safe_relative(not_found_path, "site.not_found_path").as_posix()
        for reserved in reserved_destinations:
            if overlaps(not_found, reserved):
                raise ConfigError(f"site.not_found_path {not_found!r} overlaps generated output {reserved!r}")
    static_asset_destinations: list[str] = []
    for asset in site.get("static_assets", []):
        destination = _safe_relative(asset["destination"], "site.static_assets[].destination").as_posix()
        for reserved in reserved_destinations:
            if overlaps(destination, reserved):
                raise ConfigError(f"Static asset destination {destination!r} overlaps generated output {reserved!r}")
        if not_found_path and overlaps(destination, _safe_relative(not_found_path, "site.not_found_path").as_posix()):
            raise ConfigError(f"Static asset destination {destination!r} overlaps site.not_found_path")
        for existing in static_asset_destinations:
            if overlaps(destination, existing):
                raise ConfigError(f"Static asset destinations overlap: {destination!r} and {existing!r}")
        static_asset_destinations.append(destination)
    if len(set(site.get("locales", []))) > 1 and "{locale}" not in site.get("version_index_path_template", "{components_root}/{version}/index.html"):
        raise ConfigError("site.version_index_path_template must include {locale} when multiple locales are configured")
    if len(set(site.get("versions", []))) > 1 and "{version}" not in site.get("version_index_path_template", "{components_root}/{version}/index.html"):
        raise ConfigError("site.version_index_path_template must include {version} when multiple versions are configured")
    if site.get("default_locale") and site.get("locales") and site["default_locale"] not in site["locales"]:
        raise ConfigError("site.default_locale must be listed in site.locales")
    if site.get("default_version") and site.get("versions") and site["default_version"] not in site["versions"]:
        raise ConfigError("site.default_version must be listed in site.versions")

    # Build task dependency cycle detection.
    graph = {x["id"]: set(x.get("depends_on", [])) for x in config.get("build_tasks", [])}
    visiting: set[str] = set()
    visited: set[str] = set()
    def visit(node: str) -> None:
        if node in visiting:
            raise ConfigError(f"Build task dependency cycle detected at {node}")
        if node in visited:
            return
        visiting.add(node)
        for dep in graph[node]:
            visit(dep)
        visiting.remove(node)
        visited.add(node)
    for node in graph:
        visit(node)


def load_config(path: Path, profiles: list[str] | None = None, *, allow_missing_env: bool = False) -> dict[str, Any]:
    raw = _read_mapping(path)
    config = resolve_profiles(raw, profiles)
    # Validate the merged shape before environment expansion. This prevents malformed
    # nested values (for example communication: []) from causing incidental Python
    # exceptions inside the resolver instead of a useful schema diagnostic.
    validate_schema(config)
    # Resolve only explicit non-secret configuration fields. Task/publish command
    # environment references and all secret values remain symbolic and are read only
    # inside their allowlisted adapter.
    config = _resolve_selected_environment(config, allow_missing=allow_missing_env)
    validate_schema(config)
    semantic_validate(config, allow_missing_env=allow_missing_env)
    return config


def redacted_copy(value: Any) -> Any:
    """Redact values only under keys explicitly named like secrets/tokens/passwords."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if re.search(r"secret|token|password|private_key|credential", str(key), re.I):
                result[key] = "<redacted>" if item not in (None, "") else item
            else:
                result[key] = redacted_copy(item)
        return result
    if isinstance(value, list):
        return [redacted_copy(x) for x in value]
    return value
