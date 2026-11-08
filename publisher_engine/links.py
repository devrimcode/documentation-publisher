from __future__ import annotations

from html.parser import HTMLParser
from html import escape, unescape
from pathlib import PurePosixPath, Path
from urllib.parse import quote, urlencode, urlparse, parse_qsl, unquote, urljoin
from email.utils import parseaddr
import re
from typing import Any


class LinkResolutionError(ValueError):
    pass


def _safe_relpath(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts or "" in path.parts:
        raise LinkResolutionError(f"Unsafe source path for link: {value!r}")
    if any("\x00" in part for part in path.parts):
        raise LinkResolutionError(f"NUL character in source path for link: {value!r}")
    if any(":" in part for part in path.parts):
        raise LinkResolutionError(f"Drive-qualified source path is not permitted: {value!r}")
    return path.as_posix()


def build_edit_url(target: dict[str, Any], source_file: str, source_id: str) -> str:
    mapping = target.get("mapping", {})
    configured_source = target.get("source_id")
    if configured_source and configured_source != source_id:
        raise LinkResolutionError(
            f"Authoring target {target['id']!r} is not mapped for source {source_id!r}"
        )
    rel = _safe_relpath(source_file)
    for rule in mapping.get("rules", []):
        if rel == rule["source"]:
            rel = _safe_relpath(rule["target"])
            break
    else:
        source_prefix = mapping.get("source_prefix", "").strip("/")
        target_prefix = mapping.get("target_prefix", "").strip("/")
        if source_prefix:
            if rel != source_prefix and not rel.startswith(source_prefix + "/"):
                raise LinkResolutionError(f"Source path {rel!r} is outside mapping prefix {source_prefix!r}")
            rel = rel[len(source_prefix):].lstrip("/")
        strip_count = mapping.get("strip_leading_segments", 0)
        if strip_count:
            parts = rel.split("/")
            if strip_count >= len(parts):
                raise LinkResolutionError("Path mapping strip_leading_segments would remove the complete source path")
            rel = "/".join(parts[strip_count:])
        collapse_index = mapping.get("collapse_index_file", "")
        if collapse_index:
            if rel == collapse_index:
                rel = ""
            elif rel.endswith("/" + collapse_index):
                rel = rel[:-(len(collapse_index) + 1)]
        if target_prefix:
            rel = f"{target_prefix}/{rel}" if rel else target_prefix
    rel = _safe_relpath(rel)
    template = target["edit_url_template"]
    values = {
        "web_url": target["web_url"].rstrip("/"),
        "repository": target.get("repository", ""),
        "ref": quote(target["ref"], safe=""),
        "path": quote(rel, safe="/"),
        "source_id": source_id,
        "source_file": quote(_safe_relpath(source_file), safe="/"),
    }
    try:
        url = template.format_map(values)
    except KeyError as exc:
        raise LinkResolutionError(f"Unknown edit URL template variable: {exc}") from exc
    base = urlparse(target["web_url"])
    parsed = urlparse(url)
    if base.scheme != "https" or not base.netloc or base.query or base.fragment:
        raise LinkResolutionError("Authoring web_url must be an HTTPS origin/path without query or fragment")
    if parsed.scheme != "https" or not parsed.netloc or parsed.netloc.lower() != base.netloc.lower():
        raise LinkResolutionError("Edit URL must use HTTPS and the explicitly configured authoring host")
    sensitive_query_keys = {key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
    if parsed.username or parsed.password or sensitive_query_keys & {"token", "access_token", "password", "secret", "private_key", "authorization"}:
        raise LinkResolutionError("Edit URL must not embed credentials")
    return url


def build_communication_url(channel: str, settings: dict[str, Any], values: dict[str, str]) -> str:
    if channel == "email":
        address = settings["address"].strip()
        parsed_name, parsed_address = parseaddr(address)
        if not parsed_address or parsed_address != address or "\r" in address or "\n" in address:
            raise LinkResolutionError("communication.email address must be one plain mailbox address")
        query: dict[str, str] = {}
        if settings.get("cc"):
            query["cc"] = ",".join(settings["cc"])
        if settings.get("bcc"):
            query["bcc"] = ",".join(settings["bcc"])
        for key in ("subject", "body"):
            if settings.get(key):
                try:
                    query[key] = settings[key].format_map(values)
                except KeyError as exc:
                    raise LinkResolutionError(f"Unknown email template variable: {exc}") from exc
        return f"mailto:{address}" + ("?" + urlencode(query) if query else "")

    template = settings.get("url_template")
    if not template:
        raise LinkResolutionError(f"communication.{channel} has no url_template")
    merged = {**values, **{f"query_{k}": v for k, v in settings.get("query", {}).items()}}
    encoded = {k: quote(str(v), safe="") for k, v in merged.items()}
    try:
        url = template.format_map(encoded)
    except KeyError as exc:
        raise LinkResolutionError(f"Unknown communication URL template variable: {exc}") from exc
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise LinkResolutionError(f"communication.{channel} must produce an absolute HTTPS URL without credentials")
    allowed_hosts = {x.lower() for x in settings.get("allowed_hosts", [])}
    if "*" in allowed_hosts or any("*" in host for host in allowed_hosts):
        raise LinkResolutionError(f"communication.{channel}.allowed_hosts does not support wildcard hosts")
    if allowed_hosts and (parsed.hostname or "").lower() not in allowed_hosts:
        raise LinkResolutionError(f"communication.{channel} produced a host outside allowed_hosts: {parsed.hostname}")
    sensitive_query_keys = {key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
    if sensitive_query_keys & {"token", "access_token", "password", "secret", "private_key", "authorization"}:
        raise LinkResolutionError(f"communication.{channel} URL template must not put credentials in the query string")
    return url


def _prefix_suffix(original_url: str, prefixes: list[str]) -> str | None:
    """Return the suffix matched by an explicitly configured URL/path prefix.

    Absolute prefixes compare scheme/host/path. Root-relative prefixes compare
    only the URL path. Prefix matches must end on a path boundary so `/docs/`
    cannot accidentally select `/docs-old/`.
    """
    parsed = urlparse(original_url)
    if parsed.scheme and parsed.scheme.lower() != "https":
        return None
    if parsed.username or parsed.password:
        return None
    for raw_prefix in prefixes:
        prefix = str(raw_prefix).strip()
        if not prefix:
            continue
        prefix_parsed = urlparse(prefix)
        if prefix_parsed.scheme:
            if (prefix_parsed.scheme.lower(), prefix_parsed.netloc.lower()) != (
                parsed.scheme.lower(), parsed.netloc.lower()
            ):
                continue
            if prefix_parsed.scheme.lower() != "https":
                continue
            prefix_path = prefix_parsed.path or "/"
        else:
            prefix_path = prefix
            # A root-relative selector applies only to a root-relative input
            # href. It must never capture an absolute URL on an unrelated host.
            if not prefix_path.startswith("/") or parsed.scheme or parsed.netloc:
                continue
        if not parsed.path.startswith(prefix_path):
            continue
        if prefix_path != "/" and not prefix_path.endswith("/") and len(parsed.path) > len(prefix_path):
            if parsed.path[len(prefix_path)] != "/":
                continue
        return unquote(parsed.path[len(prefix_path):].lstrip("/"))
    return None


def _is_documentation_page_url(value: str) -> bool:
    """Limit neighbor routing to rendered pages, not images/downloads/assets."""
    path = urlparse(value).path.rstrip("/")
    suffix = PurePosixPath(path).suffix.casefold()
    return suffix in {"", ".html", ".htm", ".xhtml"}


def _map_link_path(path: str, mapping: dict[str, Any]) -> str:
    """Apply the same exact-rule/prefix mapping contract as authoring targets."""
    normalized = path.strip("/")
    if not normalized:
        raise LinkResolutionError("Mapped navigation link has an empty path")
    rel = _safe_relpath(normalized)
    for rule in mapping.get("rules", []):
        if rel == rule["source"]:
            return _safe_relpath(rule["target"])
    source_prefix = mapping.get("source_prefix", "").strip("/")
    target_prefix = mapping.get("target_prefix", "").strip("/")
    if source_prefix:
        if rel != source_prefix and not rel.startswith(source_prefix + "/"):
            raise LinkResolutionError(
                f"Navigation path {rel!r} is outside mapping prefix {source_prefix!r}"
            )
        rel = rel[len(source_prefix):].lstrip("/")
    strip_count = mapping.get("strip_leading_segments", 0)
    if strip_count:
        parts = rel.split("/")
        if strip_count >= len(parts):
            raise LinkResolutionError("Path mapping strip_leading_segments would remove the complete source path")
        rel = "/".join(parts[strip_count:])
    collapse_index = mapping.get("collapse_index_file", "")
    if collapse_index:
        if rel == collapse_index:
            rel = ""
        elif rel.endswith("/" + collapse_index):
            rel = rel[:-(len(collapse_index) + 1)]
    if target_prefix:
        rel = f"{target_prefix}/{rel}" if rel else target_prefix
    if not rel:
        raise LinkResolutionError("Mapped navigation link resolves to an empty repository path")
    return _safe_relpath(rel)


def build_routed_link_url(channel: str, settings: dict[str, Any], original_url: str,
                          values: dict[str, str]) -> str:
    """Build an explicitly configured destination for issue/navigation links.

    The target URL and URL template are always supplied by the project profile.
    Source URLs are used only to identify the incoming link and preserve its
    path/query/fragment; they never select the destination repository.
    """
    target_url = str(settings.get("target_url", "")).rstrip("/")
    base = urlparse(target_url)
    if (base.scheme != "https" or not base.netloc or base.username or base.password
            or base.query or base.fragment):
        raise LinkResolutionError(f"links.{channel}.target_url must be an HTTPS URL without credentials/query/fragment")

    parsed = urlparse(original_url)
    prefixes = settings.get("source_prefixes", [])
    matched_suffix = _prefix_suffix(original_url, prefixes) if prefixes else None
    if channel in {"issues", "navigation"}:
        if matched_suffix is None:
            raise LinkResolutionError(f"{channel} link does not match any configured source_prefixes entry")
        # `target_url` identifies the destination repository root. The
        # provider-specific route (for GitHub, `/issues/`) belongs in the
        # explicit URL template, not in the captured suffix. An empty suffix
        # therefore means the issue-list root; non-empty suffixes such as
        # `new` and `123` are mapped beneath that route by the configured
        # template. This keeps the repository target independent from the
        # provider route and avoids emitting `/repo/123` instead of
        # `/repo/issues/123`.
        if channel == "issues" and matched_suffix == "":
            mapped_path = ""
        else:
            mapped_path = _map_link_path(matched_suffix, settings.get("mapping", {}))
    else:
        raise LinkResolutionError(f"Unsupported routed link class: {channel!r}")

    query_keys = {key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
    if query_keys & {"token", "access_token", "password", "secret", "private_key", "authorization"}:
        raise LinkResolutionError(f"links.{channel} source URL contains a sensitive query parameter")
    query_suffix = "?" + parsed.query if parsed.query else ""
    fragment_suffix = "#" + quote(parsed.fragment, safe="-._~!$&'()*+,;=:@/?") if parsed.fragment else ""
    template_values = {
        **values,
        "target_url": target_url,
        "target_ref": quote(str(settings.get("target_ref", "")), safe=""),
        "path": quote(mapped_path, safe="/"),
        "original_path": quote(parsed.path, safe="/@:+!$&'()*,-._~%"),
        "original_url": original_url,
        "query_suffix": query_suffix,
        "fragment_suffix": fragment_suffix,
        "source_query": parsed.query,
        "source_fragment": parsed.fragment,
    }
    try:
        result = str(settings["url_template"]).format_map(template_values)
    except KeyError as exc:
        raise LinkResolutionError(f"Unknown links.{channel} URL template variable: {exc}") from exc
    except ValueError as exc:
        raise LinkResolutionError(f"Invalid links.{channel} URL template: {exc}") from exc
    rendered = urlparse(result)
    if rendered.scheme != "https" or not rendered.netloc or rendered.username or rendered.password:
        raise LinkResolutionError(f"links.{channel} must produce an absolute HTTPS URL without credentials")
    allowed_hosts = {str(host).lower() for host in settings.get("allowed_hosts", [])}
    if allowed_hosts and (rendered.hostname or "").lower() not in allowed_hosts:
        raise LinkResolutionError(
            f"links.{channel} produced a host outside allowed_hosts: {rendered.hostname}"
        )
    if rendered.netloc.lower() != base.netloc.lower():
        raise LinkResolutionError(f"links.{channel} URL template changed the explicitly configured target authority")
    base_path = base.path.rstrip("/")
    if base_path and rendered.path != base_path and not rendered.path.startswith(base_path + "/"):
        raise LinkResolutionError(f"links.{channel} URL template escaped the explicitly configured target repository path")
    if any(segment == ".." for segment in unquote(rendered.path).split("/")):
        raise LinkResolutionError(f"links.{channel} URL template produced a path traversal segment")
    result_query_keys = {key.lower() for key, _ in parse_qsl(rendered.query, keep_blank_values=True)}
    if result_query_keys & {"token", "access_token", "password", "secret", "private_key", "authorization"}:
        raise LinkResolutionError(f"links.{channel} URL template must not put credentials in its query string")
    return result


def transform_keycloak_asciidoc_edit_links(
    html_text: str, source: dict[str, Any], source_id: str,
    link_policies: dict[str, dict[str, Any]] | None = None,
    communication_channels: set[str] | None = None,
    page_rel: str = "",
) -> tuple[str, dict[str, int]]:
    """Attach source provenance to Keycloak edit links without choosing the editor target.

    The upstream HTML identifies its *source* repository and ref in the href:
    ``/<org>/<repo>/tree/<ref>/docs/documentation/<include_filename>``. Those
    values must be checked against the configured source identity, not against
    the separately configured authoring target. The normal marker resolver then
    maps the source-relative path to any explicitly configured authoring repo.
    Edit links are marked with exact source-file provenance. Issue links and
    explicitly configured neighboring-document URL prefixes receive distinct
    markers and can therefore be routed to independent destinations.
    """
    web = urlparse(str(source.get("web_url", "")))
    if web.scheme != "https" or (web.hostname or "").lower() != "github.com" or web.query or web.fragment:
        raise LinkResolutionError("Keycloak AsciiDoc adapter requires sources[].vcs.web_url to be an HTTPS GitHub repository URL")
    repo_path = web.path.strip("/")
    if not repo_path or len(repo_path.split("/")) != 2 or ".." in repo_path.split("/"):
        raise LinkResolutionError("Keycloak source web_url must identify exactly one GitHub owner/repository")
    ref = str(source.get("default_ref", ""))
    if not ref or "/" in ref or ref in {".", ".."}:
        raise LinkResolutionError("Keycloak AsciiDoc adapter requires a single-segment configured source ref")
    expected_prefixes = (
        f"/{repo_path}/edit/{ref}/docs/documentation/",
        f"/{repo_path}/tree/{ref}/docs/documentation/",
    )

    anchor_re = re.compile(r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a\s*>", re.IGNORECASE | re.DOTALL)
    href_re = re.compile(r"\bhref\s*=\s*([\"'])(.*?)\1", re.IGNORECASE | re.DOTALL)
    policies = link_policies or {}
    communication_channels = communication_channels or set()
    counts = {"edit": 0, "issues": 0, "navigation": 0}
    source_repo = urlparse(str(source.get("web_url", "")))
    source_issue_prefix = source_repo.path.rstrip("/") + "/issues/"
    issue_policy = policies.get("issues", {})
    navigation_policy = policies.get("navigation", {})

    def replace_anchor(match: re.Match[str]) -> str:
        attrs = match.group("attrs")
        body = match.group("body")
        label = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]*>", "", body))).strip().casefold()
        href_match = href_re.search(attrs)
        if not href_match:
            if label in {"edit this section", "edit this page"}:
                raise LinkResolutionError("Keycloak edit link has no href attribute")
            return match.group(0)
        href = unescape(href_match.group(2))
        parsed = urlparse(href)
        marker = ""
        marker_extra = ""

        if label in {"edit this section", "edit this page"}:
            matched_prefix = next(
                (prefix for prefix in expected_prefixes if parsed.path.startswith(prefix)), None
            )
            if (parsed.scheme != "https" or parsed.netloc.casefold() != "github.com"
                    or parsed.query or parsed.fragment or matched_prefix is None):
                raise LinkResolutionError(
                    "Keycloak edit link does not point to the configured source repository/ref "
                    "documentation edit or tree URL"
                )
            relative = unquote(parsed.path[len(matched_prefix):])
            source_file = _safe_relpath(f"docs/documentation/{relative}")
            if not source_file.lower().endswith(".adoc"):
                raise LinkResolutionError(f"Keycloak edit link does not identify an AsciiDoc source file: {source_file}")
            marker = "edit"
            marker_extra = (
                f' data-source-id="{escape(source_id, quote=True)}"'
                f' data-source-file="{escape(source_file, quote=True)}"'
            )
        else:
            # In override/disable mode the configured URL selectors define the
            # complete issue-link class. Do not depend on visible anchor text:
            # themes may rename the link, add icons, or localize its label.
            configured_issue_prefixes = issue_policy.get("source_prefixes", [])
            matches_configured_issue = (
                "issues" in policies
                and bool(configured_issue_prefixes)
                and _prefix_suffix(href, configured_issue_prefixes) is not None
            )
            label_is_issue = label in {"report an issue", "report issue"}
            matches_legacy_communication_issue = (
                label_is_issue and not configured_issue_prefixes
                and "issues" in communication_channels and "issues" not in policies
                and parsed.scheme == "https"
                and (parsed.hostname or "").lower() == (source_repo.hostname or "").lower()
                and parsed.path.startswith(source_issue_prefix)
            )
            if matches_configured_issue or matches_legacy_communication_issue:
                marker = "issues"
            else:
                navigation_prefixes = navigation_policy.get("source_prefixes", [])
                relative_prefixes = navigation_policy.get("relative_prefixes", [])
                routed_href = href
                is_selected_absolute_or_root = bool(
                    navigation_prefixes
                    and _prefix_suffix(href, navigation_prefixes) is not None
                    and _is_documentation_page_url(href)
                )
                is_selected_relative = bool(relative_prefixes) and any(
                    href.startswith(prefix) for prefix in relative_prefixes
                )
                if not is_selected_absolute_or_root and is_selected_relative:
                    source_page_base = navigation_policy.get("source_page_base_url", "")
                    if not source_page_base or not page_rel:
                        raise LinkResolutionError(
                            "Relative neighbor link selectors require links.navigation.source_page_base_url "
                            "and a component-relative page path"
                        )
                    current_source_page = urljoin(source_page_base.rstrip("/") + "/", page_rel)
                    routed_href = urljoin(current_source_page, href)
                    # A fragment or path that resolves back to the same page is not a neighbor page.
                    current_parsed = urlparse(current_source_page)
                    routed_parsed = urlparse(routed_href)
                    is_selected_absolute_or_root = (
                        routed_parsed.path != current_parsed.path
                        and navigation_prefixes
                        and _prefix_suffix(routed_href, navigation_prefixes) is not None
                        and _is_documentation_page_url(routed_href)
                    )
                if is_selected_absolute_or_root:
                    marker = "navigation"
                    href = routed_href

        if not marker:
            return match.group(0)
        cleaned = re.sub(
            r"\s+data-(?:publisher-link|source-id|source-file|original-href)\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)",
            "", attrs, flags=re.IGNORECASE,
        )
        marker_attrs = (
            f' data-publisher-link="{marker}"'
            f' data-original-href="{escape(href, quote=True)}"'
            + marker_extra
        )
        counts[marker] += 1
        return f"<a{cleaned}{marker_attrs}>{body}</a>"

    transformed = anchor_re.sub(replace_anchor, html_text)
    return transformed, counts


class MarkerLinkRewriter(HTMLParser):
    """Rewrites only explicit data-publisher-link markers; ordinary links/text remain untouched."""
    def __init__(self, *, edit: dict[str, Any], targets: dict[str, dict[str, Any]],
                 communication: dict[str, dict[str, Any]], source_id: str,
                 link_policies: dict[str, dict[str, Any]] | None = None,
                 page_rel: str = "", provenance: dict[str, Any] | None = None,
                 source_roots: dict[str, Any] | None = None, unresolved_policy: str = "fail",
                 template_context: dict[str, str] | None = None):
        super().__init__(convert_charrefs=False)
        self.edit = edit
        self.targets = targets
        self.communication = communication
        self.link_policies = link_policies or {}
        self.source_id = source_id
        self.page_rel = page_rel
        self.provenance = provenance or {}
        self.source_roots = source_roots or {}
        self.unresolved_policy = unresolved_policy
        self.template_context = template_context or {}
        self.output: list[str] = []
        self._suppressed_depth = 0
        self._anchor_stack: list[bool] = []
        self.errors: list[str] = []
        self.resolved_links: list[dict[str, str]] = []

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> str:
        bits = []
        for key, value in attrs:
            if value is None:
                bits.append(key)
            else:
                bits.append(f'{key}="{escape(value, quote=True)}"')
        return (" " + " ".join(bits)) if bits else ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        marker = attr_map.get("data-publisher-link")
        if marker is None and tag.lower() == "a":
            classes = (attr_map.get("class") or "").split()
            for cls in classes:
                if cls.startswith("publisher-link-"):
                    marker = cls[len("publisher-link-"):]
                    break
        if tag.lower() == "a" and marker:
            if marker != "edit" and marker not in self.communication and marker not in self.link_policies:
                self.errors.append(f"Unknown publisher link marker {marker!r}; configure communication.{marker} or remove the marker")
                self.output.append(f"<{tag}{self._attrs(attrs)}>")
                self._anchor_stack.append(False)
            else:
                self._rewrite_anchor(tag, attrs, marker)
            return
        if self._suppressed_depth:
            if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
                self._suppressed_depth += 1
            return
        self.output.append(f"<{tag}{self._attrs(attrs)}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._suppressed_depth:
            return
        self.output.append(f"<{tag}{self._attrs(attrs)} />")

    def _rewrite_anchor(self, tag: str, attrs: list[tuple[str, str | None]], marker: str) -> None:
        a = dict(attrs)
        if marker == "edit":
            settings = self.edit
        elif marker in self.link_policies:
            settings = self.link_policies[marker]
        else:
            settings = self.communication.get(marker, {"mode": "inherit"})
        mode = settings.get("mode", "inherit")
        if mode == "inherit":
            cleaned = [(k, v) for k, v in attrs if k not in {"data-publisher-link", "data-source-file", "data-source-id", "data-page-url", "data-page-title", "data-section-id", "data-original-href"}]
            if dict(cleaned).get("class"):
                classes = [x for x in dict(cleaned)["class"].split() if not x.startswith("publisher-link-")]
                cleaned = [(k, v) for k, v in cleaned if k != "class"] + ([ ("class", " ".join(classes)) ] if classes else [])
            self.resolved_links.append({"channel": marker, "mode": "inherit", "href": a.get("href", "")})
            self.output.append(f"<{tag}{self._attrs(cleaned)}>")
            self._anchor_stack.append(False)
            return
        if mode == "disable":
            self._anchor_stack.append(True)
            self.resolved_links.append({"channel": marker, "mode": "disable", "href": ""})
            self._suppressed_depth = 0
            return
        target_policy = self.unresolved_policy
        try:
            section_id = a.get("data-section-id", "")
            provenance_key = f"{self.page_rel}#{section_id}" if section_id else self.page_rel
            provenance = self.provenance.get("sections", {}).get(provenance_key) or self.provenance.get("files", {}).get(self.page_rel, {})
            values = {
                **self.template_context,
                "page_url": a.get("data-page-url", self.template_context.get("page_url", "")),
                "page_title": a.get("data-page-title", self.template_context.get("page_title", "")),
                "section_id": section_id,
                "source_id": a.get("data-source-id", provenance.get("source_id", self.source_id)),
                "source_file": a.get("data-source-file", provenance.get("source_file", "")),
            }
            original_href = a.get("data-original-href", a.get("href", ""))
            if not values["source_file"] and a.get("href", "").startswith("publisher-source:"):
                values["source_file"] = a["href"][len("publisher-source:"):].split("#", 1)[0]
            if marker == "edit":
                target_id = self.edit.get("target_id")
                if target_id not in self.targets:
                    raise LinkResolutionError("Edit target_id is not configured")
                target = self.targets[target_id]
                target_policy = target.get("unresolved_policy", target_policy)
                href = build_edit_url(target, values["source_file"], values["source_id"])
                source_root = self.source_roots.get(values["source_id"])
                if source_root is None:
                    raise LinkResolutionError(f"No configured build source matches provenance source_id {values['source_id']!r}")
                source_file = Path(source_root) / _safe_relpath(values["source_file"])
                if not source_file.is_file():
                    raise LinkResolutionError(f"Provenance source file does not exist in the checked-out source: {values['source_file']}")
            elif marker in self.link_policies:
                href = build_routed_link_url(marker, settings, original_href, values)
                target_policy = settings.get("unresolved_policy", target_policy)
            else:
                settings = self.communication.get(marker)
                if not settings:
                    raise LinkResolutionError(f"Communication channel {marker!r} is not configured")
                href = build_communication_url(marker, settings, values)
            cleaned = [(k, v) for k, v in attrs if k not in {"data-publisher-link", "data-source-file", "data-source-id", "data-page-url", "data-page-title", "data-section-id", "data-original-href"} and k != "href"]
            cleaned.append(("href", href))
            if settings_target := (settings.get("target") if marker != "edit" else None):
                cleaned.append(("target", settings_target))
                if settings_target == "_blank":
                    rel = set((dict(cleaned).get("rel") or "").split())
                    rel.update({"noopener", "noreferrer"})
                    cleaned = [(k, v) for k, v in cleaned if k != "rel"] + [("rel", " ".join(sorted(rel)))]
            if dict(cleaned).get("class"):
                classes = [x for x in dict(cleaned)["class"].split() if not x.startswith("publisher-link-")]
                cleaned = [(k, v) for k, v in cleaned if k != "class"] + ([ ("class", " ".join(classes)) ] if classes else [])
            self.output.append(f"<{tag}{self._attrs(cleaned)}>")
            self.resolved_links.append({"channel": marker, "mode": "override", "href": href, "source_file": values.get("source_file", "")})
            self._anchor_stack.append(False)
        except (LinkResolutionError, KeyError) as exc:
            policy = settings.get("unresolved_policy", target_policy) if marker in {"edit", *self.link_policies} else self.unresolved_policy
            if policy == "omit":
                self._anchor_stack.append(True)
            else:
                self.errors.append(f"{marker}: {exc}")
                self._anchor_stack.append(False)
                self.output.append(f"<{tag}{self._attrs(attrs)}>")

    def handle_endtag(self, tag: str) -> None:
        if self._suppressed_depth:
            self._suppressed_depth -= 1
            return
        if tag.lower() == "a" and self._anchor_stack:
            suppressed = self._anchor_stack.pop()
            if suppressed:
                return
        self.output.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self._suppressed_depth:
            self.output.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self._suppressed_depth:
            self.output.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self._suppressed_depth:
            self.output.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        if not self._suppressed_depth:
            self.output.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        if not self._suppressed_depth:
            self.output.append(f"<!{decl}>")

    def unknown_decl(self, data: str) -> None:
        if not self._suppressed_depth:
            self.output.append(f"<![{data}]>")


def rewrite_html_file(path, *, edit, targets, communication, source_id, link_policies=None, page_rel="", provenance=None, source_roots=None, unresolved_policy="fail", link_report=None, template_context=None) -> list[str]:
    from pathlib import Path
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    parser = MarkerLinkRewriter(edit=edit, targets=targets, communication=communication,
                                link_policies=link_policies,
                                source_id=source_id, page_rel=page_rel, provenance=provenance,
                                source_roots=source_roots, unresolved_policy=unresolved_policy,
                                template_context=template_context)
    parser.feed(text)
    parser.close()
    if link_report is not None:
        link_report.extend(parser.resolved_links)
    if parser.errors:
        return parser.errors
    file_path.write_text("".join(parser.output), encoding="utf-8")
    return []
