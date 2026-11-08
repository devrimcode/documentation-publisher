from __future__ import annotations

import json
import io
import os
import subprocess
import sys
import tempfile
import tarfile
import unittest
import zipfile
from pathlib import Path
import stat
from unittest.mock import patch

import yaml


class NoDuplicateKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys instead of silently overwriting them."""


def _construct_unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark,
                "found an unhashable mapping key", key_node.start_mark,
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark,
                f"found duplicate key {key!r}", key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


NoDuplicateKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from publisher_engine.config import ConfigError, load_config, semantic_validate, validate_schema, _read_mapping
from publisher_engine.engine import (build, publish, BuildError, BuildLock, _run_command,
                                     safe_child, validate_site, _commit_output,
                                     _copy_component_output, _copy_static_assets,
                                     _copy_regular_file_nofollow, _remove_tree_strict,
                                     _guard_not_git_metadata, _guard_not_tracked_output,
                                     _site_public_url, _site_public_path,
                                     _rewrite_root_relative_site_urls,
                                     _inject_noindex, _rewrite_links)
from publisher_engine.links import build_edit_url, build_communication_url, rewrite_html_file, LinkResolutionError
from publisher_engine.archive import extract_zip, extract_tar, ArchiveError
from publisher_engine.workflow import generate_github_actions_workflow, generate_gitlab_ci_workflow, WorkflowError
from publisher_engine.gitops import make_askpass_env, resolve_local_or_url, clone_publisher, run_git, integrate_subtree, ensure_git_subtree, GitError
from publisher_engine.cli import main as cli_main


def git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, text=True, check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()


def init_remote(path: Path, files: dict[str, str]) -> Path:
    bare = path.with_suffix(".git")
    work = path.with_name(path.name + "-work")
    git(["init", "--bare", str(bare)], path.parent)
    git(["init", "-b", "main", str(work)], path.parent)
    git(["config", "user.name", "Fixture Author"], work)
    git(["config", "user.email", "fixture@example.invalid"], work)
    for name, content in files.items():
        target = work / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    git(["add", "."], work)
    git(["commit", "-m", "fixture"], work)
    git(["remote", "add", "origin", str(bare)], work)
    git(["push", "-u", "origin", "main"], work)
    return bare


def base_config(tmp: Path, publisher_remote: Path, source_remote: Path) -> dict:
    task_code = (
        "from pathlib import Path; "
        "p=Path('build/generated/guide'); p.mkdir(parents=True, exist_ok=True); "
        "(p/'index.html').write_text('''<!doctype html><html><body>"
        "<a class=\\\"publisher-link-edit\\\" href=\\\"publisher-source:docs/page.adoc\\\">Edit this section</a> "
        "<a class=\\\"publisher-link-issues\\\" data-page-title=\\\"Example page\\\" href=\\\"https://old.invalid/issue\\\">Report issue</a> "
        "<a class=\\\"publisher-link-email\\\" href=\\\"mailto:old@example.invalid\\\">Email</a>"
        "</body></html>''', encoding='utf-8')"
    )
    return {
        "schema_version": 2,
        "project": {"id": "fixture-docs", "title": "Fixture Documentation", "locale": "en"},
        "publisher": {"clone_url": str(publisher_remote), "ref": "main"},
        "sources": [{
            "id": "content", "vcs": {"provider": "git", "clone_url": str(source_remote), "default_ref": "main", "ref_type": "branch", "depth": 1},
            "root": ".", "integration": {"mode": "git_subtree", "prefix": "subtrees/content", "squash": True, "history": "shallow"}
        }],
        "authoring_targets": [{
            "id": "authoring", "provider": "generic", "web_url": "https://authoring.example.invalid/project",
            "repository": "authoring/project", "ref": "work", "ref_type": "branch", "source_id": "content",
            "edit_url_template": "{web_url}/edit/{ref}/{path}",
            "mapping": {"source_prefix": "docs", "target_prefix": "content", "rules": []},
            "unresolved_policy": "fail"
        }],
        "build_tasks": [{
            "id": "build-guide", "source_id": "content", "adapter": "command", "working_directory": ".",
            "argv": [sys.executable, "-c", task_code], "environment": {}, "pass_environment": ["PATH", "HOME"],
            "secret_environment": [], "depends_on": [], "timeout_seconds": 30, "retry": 0, "outputs": ["build/generated/guide"]
        }],
        "components": [
            {"id": "guide", "title": "Guide", "source_id": "content", "route": "guide",
             "tasks": ["build-guide"], "output_path": "build/generated/guide", "output_kind": "directory",
             "fallback": {"mode": "redirect", "url": "https://original.example.invalid/guide/"}},
            {"id": "other", "title": "Other", "source_id": "content", "route": "other",
             "tasks": [], "output_path": "not-built", "output_kind": "directory",
             "fallback": {"mode": "redirect", "url": "https://original.example.invalid/other/"}}
        ],
        "site": {"base_url": "https://docs.example.invalid", "base_path": "/project", "output_directory": "_site", "components_root": "docs", "version": "v1", "generate_index": True, "robots": "noindex"},
        "links": {"edit": {"mode": "override", "target_id": "authoring", "unresolved_policy": "fail"}},
        "communication": {
            "issues": {"mode": "override", "url_template": "https://issues.example.invalid/new?title={page_title}"},
            "email": {"mode": "override", "address": "docs@example.invalid", "subject": "Feedback: {page_title}", "body": "Page: {page_url}"}
        },
        "validation": {"require_no_symlinks": True, "validate_local_links": True, "validate_fragments": True,
                       "validate_css_assets": True, "validate_edit_links": True, "validate_communication_links": True,
                       "unresolved_edit_policy": "fail", "max_site_bytes": 10000000, "max_files": 1000},
        "workspace": {"temp_root": str(tmp / "runs"), "git_user_name": "Publisher Fixture", "git_user_email": "publisher@example.invalid",
                      "cleanup_on_success": True, "cleanup_on_failure": True, "fail_on_cleanup_error": True, "cleanup_retries": 1},
        "publishing_targets": [{"id": "artifact", "adapter": "artifact", "output_path": "_site"}],
        "publishing": {"target_id": "artifact", "artifact_name": "test-site", "retention_days": 1}
    }


class GenericConfigTests(unittest.TestCase):
    def test_roles_are_independent(self):
        target = {
            "id": "a", "web_url": "https://edit.example.invalid/repo", "ref": "docs",
            "source_id": "build-source", "edit_url_template": "{web_url}/edit/{ref}/{path}",
            "mapping": {"source_prefix": "docs", "target_prefix": "content"}
        }
        self.assertEqual(
            build_edit_url(target, "docs/guide.adoc", "build-source"),
            "https://edit.example.invalid/repo/edit/docs/content/guide.adoc"
        )
        with self.assertRaises(LinkResolutionError):
            build_edit_url(target, "docs/guide.adoc", "some-other-source")

    def test_email_and_generic_issue_templates(self):
        email = build_communication_url("email", {"address": "team@example.invalid", "subject": "About {page_title}", "body": "See {page_url}"}, {"page_title": "Guide", "page_url": "https://docs.invalid/guide"})
        self.assertTrue(email.startswith("mailto:team@example.invalid?"))
        self.assertIn("About+Guide", email)
        issue = build_communication_url("issues", {"url_template": "https://issues.invalid/new?title={page_title}"}, {"page_title": "Guide"})
        self.assertEqual(issue, "https://issues.invalid/new?title=Guide")

    def test_inherit_preserves_original_href(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "index.html"
            p.write_text('<a class="publisher-link-edit" href="https://source.invalid/edit">Edit</a>', encoding="utf-8")
            errors = rewrite_html_file(p, edit={"mode": "inherit"}, targets={}, communication={}, source_id="s")
            self.assertFalse(errors)
            self.assertIn('href="https://source.invalid/edit"', p.read_text())

    def test_disable_removes_anchor_but_keeps_text(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "index.html"
            p.write_text('<p><a class="publisher-link-issues" href="https://old.invalid">Report</a></p>', encoding="utf-8")
            errors = rewrite_html_file(p, edit={"mode": "inherit"}, targets={}, communication={"issues": {"mode": "disable"}}, source_id="s")
            self.assertFalse(errors)
            result = p.read_text()
            self.assertNotIn("<a", result)
            self.assertIn("Report", result)

    def test_override_uses_section_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "index.html"
            p.write_text('<a class="publisher-link-edit" href="#" data-section-id="one">Edit</a>', encoding="utf-8")
            target = {"id":"a", "web_url":"https://edit.invalid/repo", "ref":"docs", "source_id":"s",
                      "edit_url_template":"{web_url}/edit/{ref}/{path}", "mapping":{"source_prefix":"docs", "target_prefix":"content"}}
            provenance = {"sections":{"index.html#one":{"source_id":"s", "source_file":"docs/one.adoc"}}}
            source_root = Path(td) / "source"
            (source_root / "docs").mkdir(parents=True)
            (source_root / "docs/one.adoc").write_text("= Original section", encoding="utf-8")
            errors = rewrite_html_file(p, edit={"mode":"override","target_id":"a"}, targets={"a":target}, communication={}, source_id="s", page_rel="index.html", provenance=provenance, source_roots={"s": source_root})
            self.assertFalse(errors)
            self.assertIn('href="https://edit.invalid/repo/edit/docs/content/one.adoc"', p.read_text())

    def test_missing_source_identity_is_not_guessed(self):
        target = {"id":"a", "web_url":"https://edit.invalid/repo", "ref":"docs", "source_id":"s",
                  "edit_url_template":"{web_url}/edit/{ref}/{path}", "mapping":{}}
        with self.assertRaises(LinkResolutionError):
            build_edit_url(target, "", "s")

    def test_drive_qualified_and_nested_alternate_stream_source_paths_are_rejected(self):
        target = {"id": "a", "web_url": "https://edit.invalid/repo", "ref": "main", "source_id": "s",
                  "edit_url_template": "{web_url}/edit/{ref}/{path}", "mapping": {}}
        for path in ("C:private/secret.adoc", "docs/secret.adoc:alternate", "docs/bad\x00name.adoc"):
            with self.subTest(path=path), self.assertRaises(LinkResolutionError):
                build_edit_url(target, path, "s")


    def test_authoring_provider_is_metadata_and_never_selects_adapter(self):
        target = {
            "id": "a", "provider_label": "gitlab", "web_url": "https://edit.example.invalid/group/project",
            "repository": "group/project", "ref": "main",
            "edit_url_template": "{web_url}/custom-edit/{ref}/{path}", "mapping": {}
        }
        expected = "https://edit.example.invalid/group/project/custom-edit/main/docs/guide.adoc"
        self.assertEqual(build_edit_url(target, "docs/guide.adoc", "s"), expected)
        target["provider_label"] = "bitbucket"
        self.assertEqual(build_edit_url(target, "docs/guide.adoc", "s"), expected)
        target.pop("provider_label")
        target["provider"] = "github"  # legacy metadata alias
        self.assertEqual(build_edit_url(target, "docs/guide.adoc", "s"), expected)

    def test_authoring_provider_label_schema_is_optional_and_alias_conflict_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = base_config(Path(td), Path(td)/"publisher.git", Path(td)/"source.git")
            cfg["authoring_targets"][0].pop("provider")
            cfg["authoring_targets"][0]["provider_label"] = "gitlab"
            validate_schema(cfg)
            semantic_validate(cfg)
            cfg["authoring_targets"][0]["provider"] = "github"
            with self.assertRaisesRegex(ConfigError, "not both"):
                semantic_validate(cfg)

    def test_communication_provider_label_does_not_change_generated_destination(self):
        settings = {"mode": "override", "url_template": "https://issues.example.invalid/new?title={page_title}",
                    "allowed_hosts": ["issues.example.invalid"], "provider_label": "github"}
        expected = "https://issues.example.invalid/new?title=Guide"
        self.assertEqual(build_communication_url("issues", settings, {"page_title": "Guide"}), expected)
        settings["provider_label"] = "gitlab"
        self.assertEqual(build_communication_url("issues", settings, {"page_title": "Guide"}), expected)

    def test_security_target_requires_explicit_operator_attestation_and_warns_semantically(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = base_config(Path(td), Path(td)/"publisher.git", Path(td)/"source.git")
            cfg["communication"]["security"] = {
                "mode": "override", "url_template": "https://security.example.invalid/new",
                "allowed_hosts": ["security.example.invalid"], "private_target_attested": True,
            }
            semantic_validate(cfg)
            cfg["communication"]["security"]["private_target"] = False
            with self.assertRaisesRegex(ConfigError, "conflict"):
                semantic_validate(cfg)
            cfg["communication"]["security"].pop("private_target")
            cfg["communication"]["security"]["private_target_attested"] = False
            with self.assertRaisesRegex(ConfigError, "operator attestation"):
                semantic_validate(cfg)

    def test_legacy_private_target_true_remains_accepted_only_as_attestation(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = base_config(Path(td), Path(td)/"publisher.git", Path(td)/"source.git")
            cfg["communication"]["security"] = {
                "mode": "override", "url_template": "https://security.example.invalid/new",
                "allowed_hosts": ["security.example.invalid"], "private_target": True,
            }
            semantic_validate(cfg)
            cfg["communication"]["issues"] = {
                "mode": "override", "url_template": "https://issues.example.invalid/new",
                "private_target": True,
            }
            with self.assertRaisesRegex(ConfigError, "only valid for security-report"):
                semantic_validate(cfg)

    def test_dynamic_communication_channel_and_query_key_contract_is_enforced(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = base_config(Path(td), Path(td)/"publisher.git", Path(td)/"source.git")
            cfg["communication"]["custom_feed-v2"] = {
                "mode": "override", "url_template": "https://feed.example.invalid/new?title={query_title}",
                "allowed_hosts": ["feed.example.invalid"], "query": {"title": "A Guide & More", "component_id": "guide"},
            }
            semantic_validate(cfg)
            url = build_communication_url("custom_feed-v2", cfg["communication"]["custom_feed-v2"],
                                          {"page_title": "A Guide & More", "component_id": "guide"})
            self.assertEqual(url, "https://feed.example.invalid/new?title=A%20Guide%20%26%20More")
            cfg["communication"]["custom_feed-v2"]["query"]["invalid-key"] = "x"
            with self.assertRaisesRegex(ConfigError, "query keys must match"):
                semantic_validate(cfg)

    def test_dynamic_communication_channel_names_are_validated_at_runtime_and_schema(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = base_config(Path(td), Path(td)/"publisher.git", Path(td)/"source.git")
            cfg["communication"]["Bad Channel"] = {"mode": "inherit"}
            with self.assertRaisesRegex(ConfigError, "channel name must match"):
                semantic_validate(cfg)
            with self.assertRaises(Exception):
                validate_schema(cfg)

    def test_channel_mode_rejects_ignored_and_cross_channel_override_fields(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = base_config(Path(td), Path(td)/"publisher.git", Path(td)/"source.git")
            cfg["communication"]["issues"] = {"mode": "inherit", "url_template": "https://issues.example.invalid"}
            with self.assertRaisesRegex(ConfigError, "cannot carry inactive override settings"):
                semantic_validate(cfg)
            cfg["communication"]["issues"] = {"mode": "override", "address": "team@example.invalid"}
            with self.assertRaisesRegex(ConfigError, "URL-channel override does not support"):
                semantic_validate(cfg)
            cfg["communication"]["issues"] = {"mode": "inherit"}
            cfg["communication"]["email"] = {"mode": "override", "url_template": "https://mail.example.invalid"}
            with self.assertRaisesRegex(ConfigError, "email override does not support"):
                semantic_validate(cfg)

    def test_component_level_dynamic_communication_uses_same_contract(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = base_config(Path(td), Path(td)/"publisher.git", Path(td)/"source.git")
            cfg["components"][0]["link_overrides"] = {"communication": {
                "custom": {"mode": "override", "url_template": "https://custom.example.invalid/new",
                           "allowed_hosts": ["custom.example.invalid"], "query": {"page_title": "{page_title}"}}
            }}
            semantic_validate(cfg)
            cfg["components"][0]["link_overrides"]["communication"]["custom"]["query"] = {"bad-key": "x"}
            with self.assertRaisesRegex(ConfigError, "query keys must match"):
                semantic_validate(cfg)


class ConfigValidationTests(unittest.TestCase):
    def test_configuration_preserves_yaml_merge_key_semantics(self):
        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / "publisher.yml"
            config_path.write_text(
                "defaults: &defaults\n  value: inherited\n  keep: true\n"
                "merged:\n  <<: *defaults\n  value: explicit\n",
                encoding="utf-8",
            )
            parsed = _read_mapping(config_path)
            self.assertEqual(parsed["merged"], {"value": "explicit", "keep": True})

    def test_configuration_rejects_duplicate_yaml_mapping_keys(self):
        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / "publisher.yml"
            config_path.write_text("schema_version: 2\nschema_version: 2\n", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "duplicate key"):
                load_config(config_path)

    def test_schema_rejects_unknown_keys(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = {"schema_version":2, "unexpected":True}
            p = Path(td)/"bad.yml"
            p.write_text(yaml.safe_dump(cfg))
            with self.assertRaises(ConfigError):
                load_config(p)

    def test_schema_validation_precedes_nested_environment_expansion(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["communication"] = ["not-a-channel-mapping"]
            path = root / "bad-nested-type.yml"
            path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "Configuration does not match schema"):
                load_config(path)

    def test_provider_capability_contract_rejects_unsupported_identifiers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            mutations = [
                ("workflow", lambda c: c.update({"workflow": {"provider": "bitbucket_pipelines"}})),
                ("source", lambda c: c["sources"][0]["vcs"].update({"provider": "gitlab"})),
                ("publishing", lambda c: c["publishing_targets"][0].update({"adapter": "gitlab_pages"})),
                ("component", lambda c: c["components"][0].update({"link_adapter": "github_asciidoc"})),
            ]
            for label, mutate in mutations:
                candidate = base_config(root, root / "publisher.git", root / "source.git")
                mutate(candidate)
                with self.subTest(provider_surface=label), self.assertRaises(ConfigError):
                    validate_schema(candidate)

            gitlab = base_config(root, root / "publisher.git", root / "source.git")
            gitlab["workflow"] = {
                "provider": "gitlab_ci",
                "container_image": "registry.example.invalid/docs/python@sha256:" + "a" * 64,
                "python_version": "3.13",
            }
            validate_schema(gitlab)
            gitlab["workflow"].pop("container_image")
            with self.assertRaises(ConfigError):
                validate_schema(gitlab)

    def test_profile_names_are_safe_unique_identifiers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["profiles"] = {"production": {"site": {"version": "prod"}}}
            path = root / "publisher.yml"
            path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
            self.assertEqual(load_config(path, ["production"]) ["site"]["version"], "prod")
            for invalid, profiles in (("Bad", ["Bad"]), ("../prod", ["../prod"]), ("prod;touch", ["prod;touch"]), ("production", ["production", "production"])):
                candidate = base_config(root, root / "publisher.git", root / "source.git")
                candidate["profiles"] = {invalid: {}}
                path.write_text(yaml.safe_dump(candidate, sort_keys=False), encoding="utf-8")
                with self.subTest(profile=invalid, selected=profiles), self.assertRaises(ConfigError):
                    load_config(path, profiles)

    def test_profiles_container_and_inactive_profiles_are_type_checked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["profiles"] = ["not-a-profile-map"]
            path = root / "bad-profiles.yml"
            path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "profiles must be a mapping"):
                load_config(path)

            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["profiles"] = {"unused": ["not-a-mapping"]}
            path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "Profile 'unused' must be a named mapping"):
                load_config(path)

    def test_environment_expansion_is_limited_to_explicit_nonsecret_fields(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["project"]["homepage_url"] = "https://${DOCS_HOST}/"
            cfg["publisher"]["clone_url"] = "https://${DOCS_HOST}/publisher.git"
            cfg["publisher"]["ref"] = "${PUBLISHER_REF}"
            cfg["sources"][0]["vcs"]["clone_url"] = "https://${DOCS_HOST}/source.git"
            cfg["sources"][0]["vcs"]["default_ref"] = "${SOURCE_REF}"
            cfg["authoring_targets"][0]["web_url"] = "https://${DOCS_HOST}/authoring"
            cfg["site"]["base_path"] = "/${SITE_BASE_PATH}"
            cfg["site"]["output_directory"] = "${SITE_OUTPUT}"
            cfg["publishing_targets"][0]["output_path"] = "${SITE_OUTPUT}"
            cfg["workspace"]["temp_root"] = "${WORK_ROOT}"
            cfg["communication"]["email"]["address"] = "${DOCS_EMAIL}"
            cfg["communication"]["email"]["cc"] = ["${DOCS_CC}"]
            cfg["build_tasks"][0]["secret_environment"] = ["BUILD_SECRET"]
            cfg["build_tasks"][0]["environment"] = {"API_TOKEN": "${BUILD_SECRET}"}
            # Workflow environment values are emitted literally to the runner; they
            # are not part of the publisher's explicit ${NAME} expansion contract.
            cfg["workflow"] = {"environment": {"PUBLIC_LABEL": "${DOCS_HOST}"}}
            path = root / "publisher.yml"
            path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
            env = {
                "DOCS_HOST": "docs.example.invalid", "PUBLISHER_REF": "release",
                "SOURCE_REF": "main", "SITE_BASE_PATH": "docs", "SITE_OUTPUT": "_site-from-env",
                "WORK_ROOT": str(root / "runs-from-env"), "DOCS_EMAIL": "docs@example.invalid",
                "DOCS_CC": "review@example.invalid", "BUILD_SECRET": "never-copy-this-secret",
            }
            with patch.dict(os.environ, env, clear=False):
                with self.assertRaisesRegex(ConfigError, "Unsupported or unallowlisted environment variable"):
                    load_config(path)
                cfg["workflow"].pop("environment")
                path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
                loaded = load_config(path)
            self.assertEqual(loaded["project"]["homepage_url"], "https://docs.example.invalid/")
            self.assertEqual(loaded["publisher"]["clone_url"], "https://docs.example.invalid/publisher.git")
            self.assertEqual(loaded["publisher"]["ref"], "release")
            self.assertEqual(loaded["sources"][0]["vcs"]["default_ref"], "main")
            self.assertEqual(loaded["authoring_targets"][0]["web_url"], "https://docs.example.invalid/authoring")
            self.assertEqual(loaded["site"]["base_path"], "/docs")
            self.assertEqual(loaded["site"]["output_directory"], "_site-from-env")
            self.assertEqual(loaded["workspace"]["temp_root"], str(root / "runs-from-env"))
            self.assertEqual(loaded["communication"]["email"]["address"], "docs@example.invalid")
            self.assertEqual(loaded["communication"]["email"]["cc"], ["review@example.invalid"])
            self.assertEqual(loaded["build_tasks"][0]["environment"]["API_TOKEN"], "${BUILD_SECRET}")

    def test_missing_public_environment_reference_is_reported_or_preserved_by_mode(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["project"]["homepage_url"] = "https://${DOC_PUBLISHER_TEST_MISSING_HOST}/"
            path = root / "missing-env.yml"
            path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
            with patch.dict(os.environ, {"DOC_PUBLISHER_TEST_MISSING_HOST": ""}, clear=False):
                os.environ.pop("DOC_PUBLISHER_TEST_MISSING_HOST", None)
                with self.assertRaisesRegex(ConfigError, "requires environment variable"):
                    load_config(path)
                loaded = load_config(path, allow_missing_env=True)
            self.assertEqual(loaded["project"]["homepage_url"], "https://${DOC_PUBLISHER_TEST_MISSING_HOST}/")

    def test_profiles_merge_mapping_and_replace_lists(self):
        from publisher_engine.config import deep_merge
        self.assertEqual(deep_merge({"a":{"x":1,"y":2},"list":[1]}, {"a":{"x":3},"list":[2]}),
                         {"a":{"x":3,"y":2},"list":[2]})

    def test_task_cycle_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            pub = Path(td)/"publisher.git"
            src = Path(td)/"source.git"
            # Validate only; these local remotes need not be real for semantic validation.
            cfg = base_config(Path(td), pub, src)
            cfg["build_tasks"][0]["depends_on"] = ["build-guide"]
            p=Path(td)/"publisher.yml"; p.write_text(yaml.safe_dump(cfg, sort_keys=False))
            with self.assertRaises(ConfigError): load_config(p)

    def test_unresolved_placeholder_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = {"schema_version":2, "publisher":{"clone_url":"<URL>"}}
            p=Path(td)/"publisher.yml"; p.write_text(yaml.safe_dump(cfg))
            with self.assertRaises(ConfigError): load_config(p)

    def test_repository_host_allowlists_reject_wildcards_and_accept_exact_hosts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["publisher"]["clone_url"] = "https://git.publisher.invalid/org/publisher.git"
            cfg["publisher"]["allowed_hosts"] = ["*"]
            with self.assertRaisesRegex(ConfigError, "wildcard hosts"):
                semantic_validate(cfg)

            for invalid_host in ("*.example.com", "-bad.example.com", "bad-.example.com", "bad..example.com"):
                cfg = base_config(root, root / "publisher.git", root / "source.git")
                cfg["publisher"]["clone_url"] = "https://git.publisher.invalid/org/publisher.git"
                cfg["publisher"]["allowed_hosts"] = [invalid_host]
                with self.subTest(host=invalid_host), self.assertRaises(ConfigError):
                    semantic_validate(cfg)

            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["publisher"]["clone_url"] = "https://git.publisher.invalid/org/publisher.git"
            cfg["publisher"]["allowed_hosts"] = ["git.publisher.invalid"]
            cfg["sources"][0]["vcs"]["clone_url"] = "https://git.source.invalid/org/source.git"
            cfg["sources"][0]["vcs"]["allowed_hosts"] = ["git.source.invalid"]
            semantic_validate(cfg)

    def test_communication_host_allowlists_reject_wildcards_at_global_and_component_scope(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["communication"]["issues"]["allowed_hosts"] = ["*"]
            with self.assertRaisesRegex(ConfigError, "wildcard hosts"):
                semantic_validate(cfg)

            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["components"][0]["link_overrides"] = {"communication": {
                "issues": {"mode": "override", "url_template": "https://issues.example.invalid/new", "allowed_hosts": ["*.example.invalid"]}
            }}
            with self.assertRaisesRegex(ConfigError, "wildcard hosts"):
                semantic_validate(cfg)

    def test_live_publishing_rejects_reserved_example_and_test_origins(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for origin in (
                "https://example.invalid", "https://docs.example", "https://preview.test",
                "https://example.com", "https://docs.example.com", "https://preview.example.org",
                "https://127.0.0.1", "https://192.0.2.10",
            ):
                cfg = base_config(root, root / "publisher.git", root / "source.git")
                cfg["site"]["base_url"] = origin
                cfg["publishing"]["dry_run"] = False
                with self.subTest(origin=origin), self.assertRaisesRegex(ConfigError, "reserved example/test or non-global IP origins"):
                    semantic_validate(cfg)

    def test_live_publishing_rejects_reserved_canonical_origin_even_when_base_origin_is_real(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["site"]["base_url"] = "https://docs.example.org"
            cfg["site"]["canonical_base_url"] = "https://example.invalid"
            cfg["publishing"]["dry_run"] = False
            with self.assertRaisesRegex(ConfigError, "site.canonical_base_url"):
                semantic_validate(cfg)

    def test_reserved_example_origins_remain_valid_for_explicit_dry_run(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["site"]["base_url"] = "https://example.invalid"
            cfg["publishing"]["dry_run"] = True
            semantic_validate(cfg)

    def test_generic_configuration_template_has_explicit_host_placeholders(self):
        template = ROOT / "publisher.example.yml"
        text = template.read_text(encoding="utf-8")
        self.assertIn("<PUBLISHER_ALLOWED_HOST>", text)
        self.assertIn("<SOURCE_ALLOWED_HOST>", text)
        self.assertNotIn('allowed_hosts: ["*"]', text)
        cfg_path = ROOT / "publisher.example.yml"
        with self.assertRaisesRegex(ConfigError, "Unresolved configuration placeholders"):
            load_config(cfg_path)

    def test_keycloak_configuration_is_named_and_marked_as_smoke_only(self):
        smoke_path = ROOT / "publisher.keycloak.smoke.yml"
        self.assertTrue(smoke_path.is_file())
        self.assertFalse((ROOT / "publisher.keycloak.example.yml").exists())
        text = smoke_path.read_text(encoding="utf-8")
        self.assertIn("NOT A GENERIC OR LIVE DEPLOYMENT CONFIGURATION", text)
        self.assertIn("publishing.dry_run: true", text)
        loaded = load_config(smoke_path)
        self.assertTrue(loaded["publishing"].get("dry_run", True))
        self.assertTrue(loaded["site"]["base_url"].endswith("example.invalid"))

    def test_security_reporting_override_requires_private_target(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = base_config(Path(td), Path(td)/"publisher.git", Path(td)/"source.git")
            cfg["communication"]["security"] = {
                "mode": "override", "url_template": "https://public.example.invalid/issues/new",
                "private_target": False,
            }
            with self.assertRaises(ConfigError):
                semantic_validate(cfg)

    def test_required_files_and_subtree_paths_reject_traversal_or_drive_prefix(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = base_config(Path(td), Path(td) / "publisher.git", Path(td) / "source.git")
            cfg["validation"]["required_files"] = ["../outside.txt"]
            with self.assertRaises(ConfigError):
                semantic_validate(cfg)
            cfg = base_config(Path(td), Path(td) / "publisher.git", Path(td) / "source.git")
            cfg["sources"][0]["integration"]["prefix"] = "C:subtrees/content"
            with self.assertRaises(ConfigError):
                semantic_validate(cfg)

    def test_generated_site_paths_cannot_overlap_static_assets_or_not_found_page(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["site"]["static_assets"] = [{"source": "assets/logo.svg", "destination": "index.html"}]
            with self.assertRaisesRegex(ConfigError, "overlaps generated output"):
                semantic_validate(cfg)

            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["site"]["not_found_path"] = "docs/v1/guide/404.html"
            with self.assertRaisesRegex(ConfigError, "overlaps generated output"):
                semantic_validate(cfg)

            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["site"]["not_found_path"] = "index.html"
            with self.assertRaisesRegex(ConfigError, "reserved root output"):
                semantic_validate(cfg)

            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["site"]["not_found_path"] = "index.html/nested/404.html"
            with self.assertRaisesRegex(ConfigError, "overlaps generated output"):
                semantic_validate(cfg)

    def test_workflow_environment_rejects_runner_overrides_and_secret_expressions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["workflow"] = {"provider": "github_actions", "environment": {"GITHUB_TOKEN": "literal"}}
            with self.assertRaisesRegex(ConfigError, "reserved runner"):
                semantic_validate(cfg)

            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["workflow"] = {"provider": "github_actions", "environment": {"TOKEN": "${{ secrets.TOKEN }}"}}
            with self.assertRaisesRegex(ConfigError, "Unresolved configuration placeholders"):
                semantic_validate(cfg)

            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["workflow"] = {"provider": "github_actions", "environment": {"DEPLOY_TOKEN": "literal"}}
            with self.assertRaisesRegex(ConfigError, "use workflow.secrets"):
                semantic_validate(cfg)

    def test_workflow_paths_must_remain_inside_publisher_checkout(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["workflow"] = {"provider": "github_actions", "file": "../outside.yml"}
            with self.assertRaisesRegex(ConfigError, "workflow.file"):
                semantic_validate(cfg)

            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["workflow"] = {"provider": "github_actions", "config_file": "../../secrets/publisher.yml"}
            with self.assertRaisesRegex(ConfigError, "workflow.config_file"):
                semantic_validate(cfg)

    def test_site_symlink_requirement_cannot_be_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["validation"]["require_no_symlinks"] = False
            with self.assertRaisesRegex(ConfigError, "must remain true"):
                semantic_validate(cfg)

    def test_active_redirect_schemes_are_never_allowlisted(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = base_config(Path(td), Path(td) / "publisher.git", Path(td) / "source.git")
            cfg["validation"]["validate_redirect_schemes"] = ["https", "javascript"]
            with self.assertRaises(ConfigError):
                semantic_validate(cfg)

    def test_authoring_mapping_paths_reject_drive_nested_alternate_stream_and_nul_paths(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = base_config(Path(td), Path(td) / "publisher.git", Path(td) / "source.git")
            cfg["authoring_targets"][0]["mapping"]["target_prefix"] = "C:private"
            with self.assertRaises(ConfigError):
                semantic_validate(cfg)
            cfg = base_config(Path(td), Path(td) / "publisher.git", Path(td) / "source.git")
            cfg["site"]["static_assets"] = [{"source": "assets/logo.svg:alternate", "destination": "assets/logo.svg"}]
            with self.assertRaises(ConfigError):
                semantic_validate(cfg)
            cfg = base_config(Path(td), Path(td) / "publisher.git", Path(td) / "source.git")
            cfg["site"]["static_assets"] = [{"source": "assets/bad\x00name.svg", "destination": "assets/logo.svg"}]
            with self.assertRaises(ConfigError):
                semantic_validate(cfg)

    def test_safe_child_rejects_drive_nested_alternate_stream_and_nul_paths(self):
        with tempfile.TemporaryDirectory() as td:
            for path in ("C:outside/file.html", "docs/guide.html:alternate", "docs/bad\x00name.html",
                         ".git/config", "docs/.GIT/config"):
                with self.subTest(path=path), self.assertRaises(BuildError):
                    safe_child(Path(td), path)

    def test_safe_child_rejects_symlink_resolving_into_git_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            git_dir = root / ".git"
            git_dir.mkdir()
            alias = root / "generated"
            try:
                alias.symlink_to(git_dir, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Symlink creation is unavailable on this platform")
            with self.assertRaisesRegex(BuildError, "Resolved path.*Git metadata"):
                safe_child(root, "generated/config.yml")

    def test_repository_paths_cannot_target_git_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mutations = [
                ("site.output_directory", lambda c: c["site"].update(output_directory=".git/publisher-output")),
                ("site.components_root", lambda c: c["site"].update(components_root="docs/.git/components")),
                ("static asset source", lambda c: c["site"].update(static_assets=[{"source": ".git/config", "destination": "assets/config.txt"}])),
                ("static asset destination", lambda c: c["site"].update(static_assets=[{"source": "assets/logo.svg", "destination": "assets/.git/logo.svg"}])),
                ("component route", lambda c: c["components"][0].update(route=".git/content")),
                ("component output", lambda c: c["components"][0].update(output_path="build/.git/output")),
                ("workflow path", lambda c: c.update(workflow={"provider": "github_actions", "file": ".git/workflows/publisher.yml"})),
            ]
            for label, mutate in mutations:
                cfg = base_config(root, root / "publisher.git", root / "source.git")
                mutate(cfg)
                with self.subTest(path=label), self.assertRaisesRegex(ConfigError, r"Git metadata|Unsafe component route|Rendered component route"):
                    semantic_validate(cfg)

    def test_publishing_command_env_policy_rejects_ambiguous_or_unsafe_settings(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            target = {"id": "ship", "adapter": "command", "output_path": "unused",
                      "argv": [sys.executable, "-c", "pass"],
                      "pass_environment": ["DEPLOY_TOKEN"],
                      "secret_environment": ["DEPLOY_TOKEN"]}
            cfg["publishing_targets"] = [target]
            cfg["publishing"] = {"target_id": "ship"}
            with self.assertRaisesRegex(ConfigError, "both ordinary and secret"):
                semantic_validate(cfg)

            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["build_tasks"][0]["pass_environment"] = ["PATH", "HOME"]
            cfg["publishing_targets"] = [{"id": "ship", "adapter": "command", "output_path": "unused",
                                           "argv": [sys.executable, "-c", "pass"],
                                           "pass_environment": ["DEPLOY_TOKEN"]}]
            cfg["publishing"] = {"target_id": "ship"}
            with self.assertRaisesRegex(ConfigError, "must use secret_environment"):
                semantic_validate(cfg)

            cfg["publishing_targets"] = [{"id": "ship", "adapter": "command", "output_path": "unused",
                                           "argv": [sys.executable, "-c", "pass"],
                                           "environment": {"API_TOKEN": "literal-secret"}}]
            with self.assertRaisesRegex(ConfigError, "must reference secret_environment"):
                semantic_validate(cfg)

            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["publishing_targets"] = [{"id": "ship", "adapter": "command", "output_path": "unused",
                                           "argv": [sys.executable, "-c", "pass"],
                                           "environment": {"TOKEN": "${MISSING_TOKEN}"}}]
            cfg["publishing"] = {"target_id": "ship"}
            with self.assertRaisesRegex(ConfigError, "not allowlisted"):
                semantic_validate(cfg)

            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["build_tasks"][0]["environment"] = {"TASK_KEY": "literal-secret"}
            with self.assertRaisesRegex(ConfigError, "sensitive environment value"):
                semantic_validate(cfg)

            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["build_tasks"][0]["environment"] = {"TOKEN": "${NOT_ALLOWLISTED}"}
            with self.assertRaisesRegex(ConfigError, "not allowlisted"):
                semantic_validate(cfg)

            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["publishing_targets"] = [{"id": "ship", "adapter": "command", "output_path": "unused",
                                           "argv": [sys.executable, "-c", "pass"],
                                           "environment": {"API_KEY": "literal-secret"}}]
            cfg["publishing"] = {"target_id": "ship"}
            with self.assertRaisesRegex(ConfigError, "must reference secret_environment"):
                semantic_validate(cfg)

    def test_common_pat_and_jwt_environment_names_require_secret_classification(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["build_tasks"][0]["pass_environment"] = ["PATH", "HOME", "GH_PAT"]
            with self.assertRaisesRegex(ConfigError, "GH_PAT.*secret_environment"):
                semantic_validate(cfg)

            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["publishing_targets"] = [{
                "id": "ship", "adapter": "command", "output_path": "unused",
                "argv": [sys.executable, "-c", "pass"], "pass_environment": ["JWT"],
            }]
            cfg["publishing"] = {"target_id": "ship"}
            with self.assertRaisesRegex(ConfigError, "JWT.*secret_environment"):
                semantic_validate(cfg)

            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["workflow"] = {"provider": "github_actions", "environment": {"GH_PAT": "literal-value"}}
            with self.assertRaisesRegex(ConfigError, "GH_PAT.*workflow.secrets"):
                semantic_validate(cfg)

            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["build_tasks"][0]["secret_environment"] = ["GH_PAT"]
            cfg["build_tasks"][0]["environment"] = {"API_TOKEN": "${GH_PAT}"}
            semantic_validate(cfg)

    def test_non_command_publisher_rejects_command_only_configuration(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["publishing_targets"] = [{"id": "file", "adapter": "filesystem", "output_path": "published",
                                           "argv": [sys.executable, "-c", "pass"]}]
            cfg["publishing"] = {"target_id": "file"}
            with self.assertRaisesRegex(ConfigError, "require adapter=command"):
                semantic_validate(cfg)


class SiteValidationTests(unittest.TestCase):
    def test_html_void_elements_do_not_inflate_maximum_nesting_depth(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            voids = "".join("<meta charset=\"utf-8\"><img src=\"pixel.png\"><br>" for _ in range(20))
            (root / "index.html").write_text(f"<html><head>{voids}</head><body><div>content</div></body></html>", encoding="utf-8")
            cfg = {"validation": {"validate_local_links": False, "validate_css_assets": False,
                                  "require_build_manifest": False, "max_files": 100,
                                  "max_site_bytes": 100000, "max_html_depth": 3},
                   "site": {"base_path": "", "base_url": "https://example.invalid"}}
            errors = validate_site(root, cfg)
            self.assertFalse(any("HTML nesting depth" in item for item in errors), errors)

    def _config(self, tmp: Path) -> dict:
        cfg = base_config(tmp, tmp / "publisher.git", tmp / "source.git")
        cfg["validation"]["require_build_manifest"] = False
        return cfg

    def test_fragment_validation_runs_when_local_link_validation_is_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            (site / "target.html").write_text('<h1 id="present">Target</h1>', encoding="utf-8")
            (site / "index.html").write_text(
                '<a href="target.html#missing">bad fragment</a>', encoding="utf-8"
            )
            cfg = self._config(root)
            cfg["validation"].update({
                "validate_local_links": False,
                "validate_fragments": True,
                "validate_css_assets": False,
                "max_html_depth": 0,
            })
            errors = validate_site(site, cfg)
            self.assertTrue(any("Missing fragment" in item for item in errors), errors)
            self.assertFalse(any("Broken local link" in item for item in errors), errors)

    def test_disabling_local_link_validation_skips_missing_local_target_checks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            (site / "index.html").write_text(
                '<a href="not-present.html">not present</a>', encoding="utf-8"
            )
            cfg = self._config(root)
            cfg["validation"].update({
                "validate_local_links": False,
                "validate_fragments": False,
                "validate_css_assets": False,
            })
            errors = validate_site(site, cfg)
            self.assertFalse(any("Broken local link" in item for item in errors), errors)

    def test_disabling_fragment_validation_does_not_disable_local_link_validation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            (site / "target.html").write_text('<h1 id="present">Target</h1>', encoding="utf-8")
            (site / "index.html").write_text(
                '<a href="target.html#missing">bad fragment</a>', encoding="utf-8"
            )
            cfg = self._config(root)
            cfg["validation"].update({
                "validate_local_links": True,
                "validate_fragments": False,
                "validate_css_assets": False,
            })
            errors = validate_site(site, cfg)
            self.assertFalse(any("Missing fragment" in item for item in errors), errors)
            self.assertFalse(any("Broken local link" in item for item in errors), errors)

    def test_external_host_allowlist_runs_when_local_link_validation_is_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            (site / "index.html").write_text(
                '<a href="https://blocked.example.invalid/docs">external</a>', encoding="utf-8"
            )
            cfg = self._config(root)
            cfg["validation"].update({
                "validate_local_links": False,
                "validate_external_links": True,
                "allowed_external_hosts": ["allowed.example.invalid"],
                "validate_css_assets": False,
            })
            errors = validate_site(site, cfg)
            self.assertTrue(any("External host is not allowed" in item for item in errors), errors)

    def test_max_html_depth_runs_when_local_link_validation_is_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            (site / "index.html").write_text(
                "<html><body><div><section><p>too deep</p></section></div></body></html>",
                encoding="utf-8",
            )
            cfg = self._config(root)
            cfg["validation"].update({
                "validate_local_links": False,
                "validate_css_assets": False,
                "max_html_depth": 3,
            })
            errors = validate_site(site, cfg)
            self.assertTrue(any("HTML nesting depth" in item for item in errors), errors)

    def test_css_external_host_allowlist_runs_when_css_asset_validation_is_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            (site / "index.html").write_text("<html><body>ok</body></html>", encoding="utf-8")
            (site / "style.css").write_text(
                '@import url("https://blocked.example.invalid/remote.css");', encoding="utf-8"
            )
            cfg = self._config(root)
            cfg["validation"].update({
                "validate_local_links": False,
                "validate_css_assets": False,
                "validate_external_links": True,
                "allowed_external_hosts": ["allowed.example.invalid"],
            })
            errors = validate_site(site, cfg)
            self.assertTrue(any("External CSS host is not allowed" in item for item in errors), errors)
            self.assertFalse(any("Broken CSS asset" in item for item in errors), errors)

    def test_active_url_schemes_remain_blocked_when_local_link_validation_is_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            (site / "index.html").write_text(
                '<a href="javascript:alert(1)">unsafe</a>', encoding="utf-8"
            )
            cfg = self._config(root)
            cfg["validation"].update({
                "validate_local_links": False,
                "validate_css_assets": False,
            })
            errors = validate_site(site, cfg)
            self.assertTrue(any("URL scheme is not permitted" in item for item in errors), errors)

    def test_broken_links_fragments_css_assets_and_active_schemes_are_reported(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            (site / "sub").mkdir(parents=True)
            (site / "sub/index.html").write_text('<html><body><h1 id="known">Guide</h1></body></html>', encoding="utf-8")
            (site / "index.html").write_text(
                '<html><body><a href="missing.html">missing</a>'
                '<a href="sub/#absent">bad fragment</a>'
                '<a href="javascript:alert(1)">unsafe</a></body></html>',
                encoding="utf-8",
            )
            (site / "style.css").write_text("body{background:url(missing.png)}", encoding="utf-8")
            errors = validate_site(site, self._config(root))
            self.assertTrue(any("Broken local link" in item for item in errors), errors)
            self.assertTrue(any("Missing fragment" in item for item in errors), errors)
            self.assertTrue(any("URL scheme is not permitted" in item for item in errors), errors)
            self.assertTrue(any("Broken CSS asset" in item for item in errors), errors)

    def test_valid_directory_index_fragment_and_base_path_are_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            (site / "guide").mkdir(parents=True)
            (site / "guide/index.html").write_text('<html><body><h1 id="start">Guide</h1></body></html>', encoding="utf-8")
            (site / "index.html").write_text(
                '<html><body><a href="/project/guide/#start">Guide</a></body></html>', encoding="utf-8"
            )
            cfg = self._config(root)
            cfg["site"]["base_path"] = "/project"
            errors = validate_site(site, cfg)
            self.assertEqual(errors, [])

    def test_backslash_and_encoded_backslash_paths_are_normalized_before_validation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            (root / "outside.txt").write_text("outside", encoding="utf-8")
            (site / "index.html").write_text(
                '<a href="..\\outside.txt">escape</a> '
                '<a href="..%5Coutside.txt">encoded escape</a>',
                encoding="utf-8",
            )
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["validation"]["require_build_manifest"] = False
            cfg["validation"]["validate_css_assets"] = False
            errors = validate_site(site, cfg)
            self.assertGreaterEqual(sum("Link escapes site" in e for e in errors), 2)

    def test_css_backslash_paths_are_normalized_before_validation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            (root / "outside.png").write_bytes(b"outside")
            (site / "styles.css").write_text("body { background: url(..\\outside.png); }", encoding="utf-8")
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["validation"]["require_build_manifest"] = False
            cfg["validation"]["validate_local_links"] = False
            errors = validate_site(site, cfg)
            self.assertTrue(any("Broken CSS asset" in e for e in errors), errors)

    def test_site_size_file_count_and_required_file_limits_are_enforced(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            (site / "index.html").write_text("x" * 32, encoding="utf-8")
            cfg = self._config(root)
            cfg["validation"].update({"max_site_bytes": 4, "max_files": 1, "required_files": ["missing.txt"]})
            errors = validate_site(site, cfg)
            self.assertTrue(any("maximum" in item for item in errors), errors)
            self.assertTrue(any("Required output file missing" in item for item in errors), errors)


class SymlinkCopySafetyTests(unittest.TestCase):
    def _symlink(self, target: Path, link: Path) -> None:
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Symlinks are unavailable in this test environment: {exc}")

    def test_regular_file_copy_refuses_symlink_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            external = root / "outside-secret.txt"
            external.write_text("must not be copied", encoding="utf-8")
            link = root / "linked.txt"
            self._symlink(external, link)
            with self.assertRaisesRegex(BuildError, "symlink"):
                _copy_regular_file_nofollow(link, root / "copy.txt")
            self.assertFalse((root / "copy.txt").exists())

    def test_regular_file_copy_detects_source_swapped_to_symlink_after_lstat(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.txt"
            source.write_text("public", encoding="utf-8")
            outside = root / "outside.txt"
            outside.write_text("private", encoding="utf-8")
            destination = root / "copy.txt"
            original_open = os.open
            swapped = False

            def swap_before_open(path, flags, mode=0o777):
                nonlocal swapped
                if Path(path) == source and not swapped:
                    source.unlink()
                    source.symlink_to(outside)
                    swapped = True
                return original_open(path, flags, mode)

            with patch("publisher_engine.engine.os.open", side_effect=swap_before_open):
                with self.assertRaises(BuildError):
                    _copy_regular_file_nofollow(source, destination)
            self.assertTrue(swapped)
            self.assertFalse(destination.exists())

    def test_component_tree_copy_preserves_then_rejects_symlink_without_dereferencing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_root = root / "source"
            output = source_root / "build/generated/guide"
            output.mkdir(parents=True)
            (output / "index.html").write_text("<html><body>guide</body></html>", encoding="utf-8")
            outside = root / "outside-secret.txt"
            outside.write_text("secret data", encoding="utf-8")
            self._symlink(outside, output / "leak.txt")
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            staging = root / "staging"
            staging.mkdir()
            with self.assertRaisesRegex(BuildError, "Symlink in component output"):
                _copy_component_output(source_root, cfg["components"][0], staging, cfg)
            copied = staging / "docs/v1/guide/leak.txt"
            self.assertTrue(copied.is_symlink())
            self.assertFalse(copied.is_file() and not copied.is_symlink())

    def test_static_asset_tree_copy_rejects_nested_symlink_without_copying_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            publisher_root = root / "publisher"
            assets = publisher_root / "assets"
            assets.mkdir(parents=True)
            (assets / "logo.svg").write_text("<svg/>", encoding="utf-8")
            outside = root / "private.txt"
            outside.write_text("private", encoding="utf-8")
            self._symlink(outside, assets / "private.txt")
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["site"]["static_assets"] = [{"source": "assets", "destination": "public-assets"}]
            staging = root / "staging"
            staging.mkdir()
            with self.assertRaisesRegex(BuildError, "Symlink inside configured static asset source"):
                _copy_static_assets(staging, publisher_root, cfg)
            copied = staging / "public-assets/private.txt"
            self.assertTrue(copied.is_symlink())
            self.assertNotEqual(copied.lstat().st_size, outside.stat().st_size)

    def test_cleanup_never_changes_permissions_of_a_symlink_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tree = root / "cleanup-tree"
            tree.mkdir()
            outside = root / "external-target.txt"
            outside.write_text("keep permissions", encoding="utf-8")
            original_mode = stat.S_IMODE(outside.stat().st_mode)
            link = tree / "external-link"
            self._symlink(outside, link)

            def fake_rmtree(path, onerror=None):
                if onerror is None:
                    raise PermissionError("simulated read-only cleanup failure")
                onerror(os.unlink, str(link), PermissionError("simulated unlink failure"))

            with patch("publisher_engine.engine.shutil.rmtree", side_effect=fake_rmtree):
                _remove_tree_strict(tree, retries=0, delay=0)
            self.assertFalse(link.exists() or link.is_symlink())
            self.assertEqual(stat.S_IMODE(outside.stat().st_mode), original_mode)


class SubtreeEndToEndTests(unittest.TestCase):
    def test_project_pages_base_path_rewrites_real_build_html_and_css(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            publisher_remote = init_remote(tmp / "publisher", {
                "README.md": "publisher fixture\n",
                "public/site.css": 'body{background:url("/public/background.png")}\n',
                "public/background.png": "fixture image bytes",
            })
            source_remote = init_remote(tmp / "source", {
                "docs/page.adoc": "= Source page\n",
                "docs/second.adoc": "= Second\n",
            })
            cfg = base_config(tmp, publisher_remote, source_remote)
            cfg["site"]["base_path"] = "/keycloak-pages"
            cfg["site"]["static_assets"] = [{"source": "public", "destination": "public"}]
            generated_code = (
                "from pathlib import Path; "
                "p=Path('build/generated/guide'); p.mkdir(parents=True, exist_ok=True); "
                "(p/'index.html').write_text('''<!doctype html><html><head>"
                "<link rel=\\\"stylesheet\\\" href=\\\"/public/site.css\\\"></head><body>"
                "<a href=\\\"/docs/v1/other/\\\">Other guide</a>"
                "<img src=\\\"/public/background.png\\\" alt=\\\"background\\\">"
                "<a class=\\\"publisher-link-edit\\\" href=\\\"publisher-source:docs/page.adoc\\\">Edit</a>"
                "<a class=\\\"publisher-link-issues\\\" href=\\\"https://old.invalid\\\">Report issue</a>"
                "<a class=\\\"publisher-link-email\\\" href=\\\"mailto:old@example.invalid\\\">Email</a>"
                "</body></html>''', encoding='utf-8')"
            )
            cfg["build_tasks"][0]["argv"] = [sys.executable, "-c", generated_code]
            config_path = tmp / "publisher.yml"
            config_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

            result = build(config_path, selected_ids=["guide"])
            site = tmp / "_site"
            html = (site / "docs/v1/guide/index.html").read_text(encoding="utf-8")
            css = (site / "public/site.css").read_text(encoding="utf-8")

            self.assertEqual(result["status"], "success")
            self.assertIn('href="/keycloak-pages/public/site.css"', html)
            self.assertIn('href="/keycloak-pages/docs/v1/other/"', html)
            self.assertIn('src="/keycloak-pages/public/background.png"', html)
            self.assertIn('url("/keycloak-pages/public/background.png")', css)
            # Canonical links and publisher template values use the same base
            # path; this also covers the canonical base URL override.
            version_index = (site / "docs/v1/index.html").read_text(encoding="utf-8")
            self.assertIn('href="https://docs.example.invalid/keycloak-pages/docs/v1/index.html"', version_index)

    def test_real_subtree_builds_site_and_keeps_source_and_authoring_separate(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            publisher_remote = init_remote(tmp/"publisher", {"README.md":"publisher fixture\n"})
            source_remote = init_remote(tmp/"source", {"docs/page.adoc":"= Source page\n", "docs/second.adoc":"= Second\n"})
            publisher_before = git(["--git-dir", str(publisher_remote), "rev-parse", "refs/heads/main"], tmp)
            cfg = base_config(tmp, publisher_remote, source_remote)
            config_path = tmp/"publisher.yml"
            config_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
            result = build(config_path, selected_ids=["guide"])
            site = tmp/"_site"
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["sources"][0]["integration_mode"], "git_subtree")
            self.assertEqual(result["sources"][0]["source_commit"], git(["--git-dir", str(source_remote), "rev-parse", "refs/heads/main"], tmp))
            page = (site/"docs/v1/guide/index.html").read_text(encoding="utf-8")
            self.assertIn("https://authoring.example.invalid/project/edit/work/content/page.adoc", page)
            self.assertIn("https://issues.example.invalid/new?title=Example%20page", page)
            self.assertIn("mailto:docs@example.invalid?", page)
            self.assertTrue((site/"docs/v1/other/index.html").is_file())
            self.assertTrue((site/".nojekyll").is_file())
            self.assertFalse(any(p.name == ".git" for p in site.rglob("*")))
            publisher_after = git(["--git-dir", str(publisher_remote), "rev-parse", "refs/heads/main"], tmp)
            self.assertEqual(publisher_before, publisher_after, "source integration must not write to publisher remote")
            runs = tmp/"runs"
            self.assertTrue(runs.exists())
            self.assertEqual(list(runs.iterdir()), [], "temporary publisher clone/subtree must be removed")

    def test_real_subtree_build_routes_issue_paths_under_independent_target_repository(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            publisher_remote = init_remote(tmp / "publisher", {"README.md": "publisher fixture\n"})
            source_remote = init_remote(tmp / "source", {
                "docs/documentation/server_admin/index.adoc": "= Keycloak source guide\n",
            })
            cfg = base_config(tmp, publisher_remote, source_remote)
            cfg["sources"][0]["vcs"].update({
                "web_url": "https://github.com/keycloak/keycloak",
                "default_ref": "main",
            })
            generated_html = """<!doctype html><html><body>
                <a href="https://github.com/keycloak/keycloak/tree/main/docs/documentation/server_admin/index.adoc">Edit this section</a>
                <a href="https://github.com/keycloak/keycloak/issues/new?template=bug.yml&amp;title=Docs">Report an issue</a>
                <a href="https://github.com/keycloak/keycloak/issues/123?tab=comments#issuecomment-7">View related ticket</a>
                <a href="https://github.com/keycloak/keycloak/issues">Browse all issues</a>
                <a href="https://www.keycloak.org/docs/latest/server_admin/">Server Administration Guide</a>
                <a class="publisher-link-email" href="mailto:old@example.invalid">Email</a>
            </body></html>"""
            task_code = (
                "from pathlib import Path; "
                "p=Path('build/generated/guide'); p.mkdir(parents=True, exist_ok=True); "
                f"(p/'index.html').write_text({generated_html!r}, encoding='utf-8')"
            )
            cfg["build_tasks"][0]["argv"] = [sys.executable, "-c", task_code]
            cfg["components"][0]["link_adapter"] = "keycloak_asciidoc"
            cfg["links"]["edit"]["require_markers"] = True
            cfg["links"]["issues"] = {
                "mode": "override",
                "source_prefixes": ["https://github.com/keycloak/keycloak/issues"],
                "target_url": "https://github.com/xyz/mein-keycloak",
                "url_template": "{target_url}/issues/{path}{query_suffix}{fragment_suffix}",
                "require_markers": True,
            }
            cfg["links"]["navigation"] = {
                "mode": "override",
                "source_prefixes": ["https://www.keycloak.org/docs/"],
                "target_url": "https://github.com/devrimcode/keycloak",
                "target_ref": "main",
                "url_template": "{target_url}/tree/{target_ref}/{path}{query_suffix}{fragment_suffix}",
                "mapping": {
                    "strip_leading_segments": 1,
                    "target_prefix": "docs/documentation",
                },
                "require_markers": True,
            }
            config_path = tmp / "publisher.yml"
            config_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

            result = build(config_path, selected_ids=["guide"])
            page = (tmp / "_site/docs/v1/guide/index.html").read_text(encoding="utf-8")

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["sources"][0]["integration_mode"], "git_subtree")
            self.assertEqual(result["link_summary"], {"edit": 1, "issues": 3, "navigation": 1, "email": 1})
            self.assertIn(
                'href="https://authoring.example.invalid/project/edit/work/content/documentation/server_admin/index.adoc"',
                page,
            )
            self.assertIn(
                'href="https://github.com/xyz/mein-keycloak/issues/new?template=bug.yml&amp;title=Docs"',
                page,
            )
            self.assertIn(
                'href="https://github.com/xyz/mein-keycloak/issues/123?tab=comments#issuecomment-7"',
                page,
            )
            self.assertIn('href="https://github.com/xyz/mein-keycloak/issues/"', page)
            self.assertIn(
                'href="https://github.com/devrimcode/keycloak/tree/main/docs/documentation/server_admin"',
                page,
            )

    def test_static_assets_are_copied_when_index_generation_is_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            publisher_remote = init_remote(tmp / "publisher", {
                "README.md": "publisher fixture\n",
                "public/logo.svg": "<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>",
            })
            source_remote = init_remote(tmp / "source", {"docs/page.adoc": "= Source page\n"})
            cfg = base_config(tmp, publisher_remote, source_remote)
            cfg["site"]["generate_index"] = False
            cfg["site"]["not_found_path"] = "404.html"
            cfg["site"]["static_assets"] = [{"source": "public/logo.svg", "destination": "assets/logo.svg"}]
            config_path = tmp / "publisher.yml"
            config_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
            result = build(config_path, selected_ids=["guide"])
            site = tmp / "_site"
            self.assertEqual(result["status"], "success")
            self.assertEqual((site / "assets/logo.svg").read_text(encoding="utf-8"), "<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>")
            self.assertTrue((site / "404.html").is_file())
            self.assertFalse((site / "index.html").exists())

    def test_fallback_can_use_a_nested_index_file(self):
        from publisher_engine.engine import _make_fallback
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            staging = root / "site"
            staging.mkdir()
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            component = {
                "id": "guide", "title": "Guide", "route": "guide", "index_file": "nested/fallback.html",
                "fallback": {"mode": "stub"},
            }
            _make_fallback(component, staging, cfg)
            self.assertTrue((staging / "docs/v1/guide/nested/fallback.html").is_file())

    def test_keep_failed_workspace_does_not_preserve_successful_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            publisher_remote = init_remote(tmp / "publisher", {"README.md": "publisher fixture\n"})
            source_remote = init_remote(tmp / "source", {"docs/page.adoc": "= Page\n"})
            cfg = base_config(tmp, publisher_remote, source_remote)
            cfg["workspace"]["keep_failed_workspace"] = True
            cfg["workspace"]["keep_on_success"] = False
            path = tmp / "publisher.yml"
            path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
            result = build(path, selected_ids=["guide"])
            self.assertEqual(result["status"], "success")
            self.assertEqual(list((tmp / "runs").iterdir()), [])

    def test_build_failure_cleans_workspace_and_does_not_create_site(self):
        with tempfile.TemporaryDirectory() as td:
            tmp=Path(td)
            pub=init_remote(tmp/"publisher", {"README.md":"x"})
            src=init_remote(tmp/"source", {"docs/page.adoc":"x"})
            cfg=base_config(tmp,pub,src)
            cfg["build_tasks"][0]["argv"]=[sys.executable,"-c","raise SystemExit(17)"]
            p=tmp/"publisher.yml"; p.write_text(yaml.safe_dump(cfg,sort_keys=False))
            with self.assertRaises(BuildError): build(p, selected_ids=["guide"])
            self.assertFalse((tmp/"_site").exists())
            self.assertEqual(list((tmp/"runs").iterdir()), [])


class ArchiveSecurityTests(unittest.TestCase):
    def test_zip_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"bad.zip"
            with zipfile.ZipFile(p,"w") as z: z.writestr("../escape.txt","bad")
            with self.assertRaises(ArchiveError): extract_zip(p,Path(td)/"out",max_bytes=1000,max_files=10)

    def test_zip_rejects_nested_windows_alternate_data_stream_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "alternate-stream.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("folder/visible.txt", "visible")
                z.writestr("folder/visible.txt:hidden", "hidden metadata")
            output = root / "out"
            with self.assertRaisesRegex(ArchiveError, "Colon-bearing Windows path"):
                extract_zip(archive, output, max_bytes=1000, max_files=10)
            self.assertFalse(output.exists())

    def test_zip_symlink_is_rejected(self):
        import stat
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"bad.zip"
            info=zipfile.ZipInfo("link")
            info.create_system=3
            info.external_attr=(stat.S_IFLNK|0o777)<<16
            with zipfile.ZipFile(p,"w") as z: z.writestr(info,"target")
            with self.assertRaises(ArchiveError): extract_zip(p,Path(td)/"out",max_bytes=1000,max_files=10)

    def test_zip_limits_case_collisions_and_partial_cleanup(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            too_large = root / "large.zip"
            with zipfile.ZipFile(too_large, "w", compression=zipfile.ZIP_DEFLATED) as z:
                z.writestr("large.txt", "x" * 4096)
            output = root / "large-out"
            with self.assertRaises(ArchiveError):
                extract_zip(too_large, output, max_bytes=128, max_files=10)
            self.assertFalse(output.exists(), "failed extraction must remove partial output")

            collision = root / "collision.zip"
            with zipfile.ZipFile(collision, "w") as z:
                z.writestr("Guide/index.html", "one")
                z.writestr("guide/INDEX.html", "two")
            output = root / "collision-out"
            with self.assertRaises(ArchiveError):
                extract_zip(collision, output, max_bytes=1000, max_files=10)
            self.assertFalse(output.exists())

    def test_zip_entry_compression_ratio_is_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "ratio.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
                z.writestr("repeat.txt", "a" * 8192)
            with self.assertRaises(ArchiveError):
                extract_zip(archive, root / "out", max_bytes=10000, max_files=10, max_ratio=2)

    def test_tar_extracts_regular_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "site.tar.gz"
            payload = b"hello tar\n"
            with tarfile.open(archive, "w:gz") as tf:
                info = tarfile.TarInfo("docs/index.html")
                info.size = len(payload)
                import io
                tf.addfile(info, io.BytesIO(payload))
            output = root / "out"
            size = extract_tar(archive, output, max_bytes=1000, max_files=10)
            self.assertEqual(size, len(payload))
            self.assertEqual((output / "docs/index.html").read_bytes(), payload)

    def test_tar_accepts_harmless_root_directory_entry(self):
        import io
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "dot-root.tar"
            with tarfile.open(archive, "w") as tf:
                directory = tarfile.TarInfo("./")
                directory.type = tarfile.DIRTYPE
                tf.addfile(directory)
                payload = b"root file"
                info = tarfile.TarInfo("./index.html")
                info.size = len(payload)
                tf.addfile(info, io.BytesIO(payload))
            output = root / "out"
            extract_tar(archive, output, max_bytes=1000, max_files=10)
            self.assertEqual((output / "index.html").read_bytes(), b"root file")

    def test_tar_traversal_and_symlink_are_rejected_and_cleaned(self):
        import io
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            traversal = root / "traversal.tar"
            with tarfile.open(traversal, "w") as tf:
                info = tarfile.TarInfo("../escape.txt")
                info.size = 3
                tf.addfile(info, io.BytesIO(b"bad"))
            out = root / "traversal-out"
            with self.assertRaises(ArchiveError):
                extract_tar(traversal, out, max_bytes=1000, max_files=10)
            self.assertFalse(out.exists())

            symlink_archive = root / "symlink.tar"
            with tarfile.open(symlink_archive, "w") as tf:
                info = tarfile.TarInfo("docs/link")
                info.type = tarfile.SYMTYPE
                info.linkname = "../../outside"
                tf.addfile(info)
            out = root / "symlink-out"
            with self.assertRaises(ArchiveError):
                extract_tar(symlink_archive, out, max_bytes=1000, max_files=10)
            self.assertFalse(out.exists())

    def test_tar_entry_count_limit_is_enforced_while_streaming(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "many.tar"
            with tarfile.open(archive, "w") as tf:
                for name in ("a.txt", "b.txt", "c.txt"):
                    info = tarfile.TarInfo(name)
                    info.size = 1
                    import io
                    tf.addfile(info, io.BytesIO(b"x"))
            out = root / "out"
            with self.assertRaises(ArchiveError):
                extract_tar(archive, out, max_bytes=1000, max_files=2)
            self.assertFalse(out.exists())


class OutputReplacementSafetyTests(unittest.TestCase):
    def test_build_output_restores_untouched_backup_if_installation_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current = root / "site"
            current.mkdir()
            (current / "old.txt").write_text("old live site", encoding="utf-8")
            missing_staging = root / "missing-staging"
            with self.assertRaisesRegex(BuildError, "previous output was restored"):
                _commit_output(missing_staging, current, replace=True)
            self.assertEqual((current / "old.txt").read_text(encoding="utf-8"), "old live site")
            self.assertEqual(list(root.glob("site.backup-*")), [])

    def test_build_output_keeps_new_tree_if_backup_cleanup_partially_fails(self):
        from publisher_engine.engine import _remove_tree_strict as real_remove
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current = root / "site"
            current.mkdir()
            (current / "old.txt").write_text("old live site", encoding="utf-8")
            staging = root / "site.staging"
            staging.mkdir()
            (staging / "new.txt").write_text("new live site", encoding="utf-8")

            def fail_after_partial_backup_cleanup(path, *args, **kwargs):
                if ".backup-" in path.name:
                    (path / "old.txt").unlink(missing_ok=True)
                    raise BuildError("simulated disk cleanup failure")
                return real_remove(path, *args, **kwargs)

            with patch("publisher_engine.engine._remove_tree_strict", side_effect=fail_after_partial_backup_cleanup):
                with self.assertRaisesRegex(BuildError, "New output is active"):
                    _commit_output(staging, current, replace=True)

            self.assertEqual((current / "new.txt").read_text(encoding="utf-8"), "new live site")
            backups = list(root.glob("site.backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertFalse((backups[0] / "old.txt").exists(), "test simulates a partially deleted previous backup")

class PublishingAdapterTests(unittest.TestCase):
    def _config(self, root: Path, *, output_path: str, replace: bool = False,
                allow_external: bool = False, atomic: bool = True) -> Path:
        cfg = base_config(root, root / "publisher.git", root / "source.git")
        # Publishing-adapter tests exercise local filesystem/command behavior, not
        # a reserved documentation origin. Use a syntactically real public origin
        # so the live-publish example-domain guard is tested separately.
        cfg["site"]["base_url"] = "https://docs.keycloak.org"
        cfg["publishing_targets"] = [{
            "id": "filesystem", "adapter": "filesystem", "output_path": output_path,
            "replace_existing": replace, "allow_external_destination": allow_external,
        }]
        cfg["publishing"] = {
            "target_id": "filesystem", "dry_run": False,
            "atomic": atomic, "pre_publish_validation": False,
        }
        path = root / "publisher.yml"
        path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
        return path

    def test_publish_api_applies_selected_profiles(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["site"]["base_url"] = "https://docs.keycloak.org"
            cfg["publishing"]["pre_publish_validation"] = False
            cfg["profiles"] = {"live": {"publishing": {"dry_run": False}}}
            config_path = root / "publisher.yml"
            config_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
            site = root / "_site"
            site.mkdir()
            (site / "index.html").write_text("<html><body>ready</body></html>", encoding="utf-8")
            preview = publish(config_path, site)
            live = publish(config_path, site, profiles=["live"])
            self.assertEqual(preview["status"], "planned")
            self.assertEqual(live["status"], "ready")

    def test_filesystem_publish_keeps_new_destination_if_backup_cleanup_fails(self):
        from publisher_engine.engine import _remove_tree_strict as real_remove
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "_site"
            site.mkdir()
            (site / "new.txt").write_text("new site", encoding="utf-8")
            destination = root / "deploy"
            destination.mkdir()
            (destination / "old.txt").write_text("old site", encoding="utf-8")
            config_path = self._config(root, output_path=str(destination), replace=True)

            def fail_after_partial_backup_cleanup(path, *args, **kwargs):
                if ".backup-" in path.name:
                    (path / "old.txt").unlink(missing_ok=True)
                    raise BuildError("simulated disk cleanup failure")
                return real_remove(path, *args, **kwargs)

            with patch("publisher_engine.engine._remove_tree_strict", side_effect=fail_after_partial_backup_cleanup):
                with self.assertRaisesRegex(BuildError, "New output is active"):
                    publish(config_path)

            self.assertEqual((destination / "new.txt").read_text(encoding="utf-8"), "new site")
            backups = list(root.glob("deploy.backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertFalse((backups[0] / "old.txt").exists(), "test simulates a partially deleted previous backup")

    def test_filesystem_publish_rejects_source_destination_overlap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            (site / "index.html").write_text("new", encoding="utf-8")
            config = self._config(root, output_path="site/published")
            with self.assertRaisesRegex(BuildError, "must be disjoint"):
                publish(config, site)
            self.assertFalse((site / "published").exists())

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            destination = root / "deploy"
            site = destination / "site"
            site.mkdir(parents=True)
            (site / "index.html").write_text("new", encoding="utf-8")
            config = self._config(root, output_path="deploy", replace=True)
            with self.assertRaisesRegex(BuildError, "must be disjoint"):
                publish(config, site)
            self.assertTrue((site / "index.html").is_file())

    def test_filesystem_publish_rechecks_symlinks_in_staged_copy_before_commit(self):
        from publisher_engine.engine import shutil as engine_shutil
        real_copytree = engine_shutil.copytree
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            (site / "index.html").write_text("new", encoding="utf-8")
            outside = root / "outside.txt"
            outside.write_text("must not be followed", encoding="utf-8")
            config = self._config(root, output_path="published")

            def add_symlink_after_precheck(src, dst, **kwargs):
                (site / "raced-link.txt").symlink_to(outside)
                return real_copytree(src, dst, **kwargs)

            with patch("publisher_engine.engine.shutil.copytree", side_effect=add_symlink_after_precheck):
                with self.assertRaisesRegex(BuildError, "staged site containing symlinks"):
                    publish(config, site)
            self.assertFalse((root / "published").exists())
            self.assertFalse(any(root.glob(".published.publishing-*")))

    def test_filesystem_publish_copies_site_atomically(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            (site / "index.html").write_text("new", encoding="utf-8")
            config = self._config(root, output_path="published")
            result = publish(config, site)
            self.assertEqual(result["status"], "published")
            self.assertEqual((root / "published/index.html").read_text(), "new")
            self.assertFalse(any(p.name.startswith(".published.publishing-") for p in root.iterdir()))

    def test_filesystem_publish_refuses_existing_destination_without_replace(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            (site / "index.html").write_text("new", encoding="utf-8")
            destination = root / "published"
            destination.mkdir()
            (destination / "index.html").write_text("old", encoding="utf-8")
            config = self._config(root, output_path="published", replace=False)
            with self.assertRaises(BuildError):
                publish(config, site)
            self.assertEqual((destination / "index.html").read_text(), "old")

    def test_filesystem_publish_replaces_existing_destination_when_enabled(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            (site / "index.html").write_text("new", encoding="utf-8")
            destination = root / "published"
            destination.mkdir()
            (destination / "old.txt").write_text("old", encoding="utf-8")
            config = self._config(root, output_path="published", replace=True)
            result = publish(config, site)
            self.assertEqual(result["status"], "published")
            self.assertEqual((destination / "index.html").read_text(), "new")
            self.assertFalse((destination / "old.txt").exists())

    def test_non_atomic_copy_failure_restores_previous_destination(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            (site / "new.txt").write_text("new", encoding="utf-8")
            destination = root / "published"
            destination.mkdir()
            (destination / "old.txt").write_text("old", encoding="utf-8")
            config = self._config(root, output_path="published", replace=True, atomic=False)

            def fail_after_partial_copy(src, dst, **kwargs):
                Path(dst).mkdir()
                (Path(dst) / "partial.txt").write_text("partial", encoding="utf-8")
                raise OSError("simulated interrupted copy")

            with patch("publisher_engine.engine.shutil.copytree", side_effect=fail_after_partial_copy):
                with self.assertRaisesRegex(BuildError, "previous output was restored"):
                    publish(config, site)
            self.assertEqual((destination / "old.txt").read_text(encoding="utf-8"), "old")
            self.assertFalse((destination / "partial.txt").exists())
            self.assertFalse(list(root.glob("published.backup-*")))

    def test_non_atomic_copy_failure_removes_partial_new_destination(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            (site / "new.txt").write_text("new", encoding="utf-8")
            config = self._config(root, output_path="published", atomic=False)

            def fail_after_partial_copy(src, dst, **kwargs):
                Path(dst).mkdir()
                (Path(dst) / "partial.txt").write_text("partial", encoding="utf-8")
                raise OSError("simulated interrupted copy")

            with patch("publisher_engine.engine.shutil.copytree", side_effect=fail_after_partial_copy):
                with self.assertRaisesRegex(BuildError, "Non-atomic publish failed"):
                    publish(config, site)
            self.assertFalse((root / "published").exists())

    def test_filesystem_publish_non_atomic_mode_copies_site(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            (site / "index.html").write_text("new", encoding="utf-8")
            config = self._config(root, output_path="published", atomic=False)
            result = publish(config, site)
            self.assertEqual(result["status"], "published")
            self.assertEqual(result["atomic"], "false")
            self.assertEqual((root / "published/index.html").read_text(encoding="utf-8"), "new")

    def _command_config(self, root: Path, argv: list[str], *, timeout: int = 5,
                        environment: dict[str, str] | None = None,
                        pass_environment: list[str] | None = None,
                        secret_environment: list[str] | None = None) -> Path:
        cfg = base_config(root, root / "publisher.git", root / "source.git")
        # The command adapter is a local fixture; do not combine its live-mode
        # tests with a reserved example origin that must now be rejected.
        cfg["site"]["base_url"] = "https://docs.keycloak.org"
        cfg["publishing_targets"] = [{
            "id": "command", "adapter": "command", "output_path": "command-destination",
            "argv": argv, "timeout_seconds": timeout,
            "environment": environment or {},
            "pass_environment": pass_environment or [],
            "secret_environment": secret_environment or [],
        }]
        cfg["publishing"] = {"target_id": "command", "dry_run": False,
                             "pre_publish_validation": False}
        path = root / "publisher.yml"
        path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
        return path

    def test_command_publish_executes_with_explicit_environment(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            script = "import os,sys; print(os.environ['DEPLOY_LABEL']); print(sys.argv[1])"
            config = self._command_config(root, [sys.executable, "-c", script, "{project_id}"],
                                          environment={"DEPLOY_LABEL": "staging"})
            result = publish(config, site)
            self.assertEqual(result["status"], "published")
            self.assertEqual(result["stdout_tail"].splitlines(), ["staging", "fixture-docs"])

    def test_command_publish_redacts_secret_on_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            secret = "publish-secret-should-not-leak"
            script = "import os,sys; print(os.environ['API_TOKEN']); sys.exit(7)"
            config = self._command_config(root, [sys.executable, "-c", script],
                                          environment={"API_TOKEN": "${DEPLOY_TOKEN}"},
                                          secret_environment=["DEPLOY_TOKEN"])
            with patch.dict(os.environ, {"DEPLOY_TOKEN": secret}):
                with self.assertRaises(BuildError) as caught:
                    publish(config, site)
            message = str(caught.exception)
            self.assertIn("<redacted>", message)
            self.assertNotIn(secret, message)

    def test_command_publish_masks_timeout_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            secret = "timeout-secret-do-not-print"
            script = "import os,time; print(os.environ['API_TOKEN'], flush=True); time.sleep(3)"
            config = self._command_config(root, [sys.executable, "-c", script], timeout=1,
                                          environment={"API_TOKEN": "${DEPLOY_TOKEN}"},
                                          secret_environment=["DEPLOY_TOKEN"])
            with patch.dict(os.environ, {"DEPLOY_TOKEN": secret}):
                with self.assertRaisesRegex(BuildError, "timed out") as caught:
                    publish(config, site)
            self.assertNotIn(secret, str(caught.exception))

    def test_command_publish_rejects_unknown_template_placeholder(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            config = self._command_config(root, [sys.executable, "-c", "pass", "{unknown}"])
            with self.assertRaisesRegex(BuildError, "unknown placeholder"):
                publish(config, site)

    def test_publish_rejects_symlink_inside_site_even_when_prevalidation_is_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            outside = root / "outside-secret.txt"
            outside.write_text("must-not-be-copied", encoding="utf-8")
            (site / "leak.txt").symlink_to(outside)
            config = self._config(root, output_path="published")
            cfg = yaml.safe_load(config.read_text(encoding="utf-8"))
            cfg["publishing"]["pre_publish_validation"] = False
            config.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(BuildError, "containing symlinks"):
                publish(config, site)
            self.assertFalse((root / "published").exists())

    def test_filesystem_publish_rejects_symlink_destination_even_with_replace(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            (site / "index.html").write_text("new", encoding="utf-8")
            actual = root / "actual"
            actual.mkdir()
            (actual / "keep.txt").write_text("keep", encoding="utf-8")
            link = root / "published-link"
            link.symlink_to(actual, target_is_directory=True)
            config = self._config(root, output_path="published-link", replace=True)
            with self.assertRaises(BuildError):
                publish(config, site)
            self.assertTrue(link.is_symlink())
            self.assertEqual((actual / "keep.txt").read_text(), "keep")

    def test_filesystem_publish_rejects_file_and_project_parent_destinations(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            (site / "index.html").write_text("new", encoding="utf-8")
            existing_file = root / "README.md"
            existing_file.write_text("do not replace", encoding="utf-8")
            config = self._config(root, output_path="README.md", replace=True)
            with self.assertRaises(BuildError):
                publish(config, site)
            self.assertEqual(existing_file.read_text(), "do not replace")

            config = self._config(root, output_path=str(root.parent), replace=True, allow_external=True)
            with self.assertRaises(BuildError):
                publish(config, site)

    def test_publish_rejects_symlink_site_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site"
            site.mkdir()
            (site / "index.html").write_text("content", encoding="utf-8")
            link = root / "site-link"
            link.symlink_to(site, target_is_directory=True)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            config = root / "publisher.yml"
            config.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
            with self.assertRaises(BuildError):
                publish(config, link)


class GitAuthenticationTests(unittest.TestCase):
    def test_repository_location_expansion_and_credential_rejection(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.environ["PUBLISHER_TEST_REPO"] = str(root / "source.git")
            try:
                self.assertEqual(resolve_local_or_url("${PUBLISHER_TEST_REPO}", root), str(root / "source.git"))
            finally:
                os.environ.pop("PUBLISHER_TEST_REPO", None)
            self.assertEqual(resolve_local_or_url("https://git.example.invalid/docs.git", root),
                             "https://git.example.invalid/docs.git")
            for unsafe in (
                "https://user:password@git.example.invalid/docs.git",
                "https://git.example.invalid/docs.git?token=abc",
                "https://git.example.invalid/docs.git#fragment",
            ):
                with self.subTest(unsafe=unsafe), self.assertRaises(GitError):
                    resolve_local_or_url(unsafe, root)
            with self.assertRaises(GitError):
                resolve_local_or_url("${PUBLISHER_MISSING_REPO}", root)

    def test_askpass_requires_and_uses_explicit_environment_secrets(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = {"PATH": os.environ.get("PATH", ""), "PUBLISH_TOKEN": "do-not-log-this"}
            result, script = make_askpass_env(
                {"mode": "environment", "secret_env": "PUBLISH_TOKEN"}, env.copy(), root
            )
            self.assertIsNotNone(script)
            self.assertEqual(script.stat().st_mode & 0o777, 0o700)
            self.assertEqual(result["PUBLISHER_GIT_PASSWORD"], "do-not-log-this")
            self.assertEqual(result["PUBLISHER_GIT_USERNAME"], "x-access-token")
            self.assertNotIn("do-not-log-this", script.read_text(encoding="utf-8"))
            with self.assertRaises(GitError):
                make_askpass_env({"mode": "environment", "secret_env": "MISSING"}, env.copy(), root)

    def test_ssh_agent_auth_requires_socket_and_none_auth_is_inert(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            original = {"PATH": "/bin"}
            returned, script = make_askpass_env({"mode": "none"}, original.copy(), root)
            self.assertIsNone(script)
            self.assertEqual(returned, original)
            with self.assertRaises(GitError):
                make_askpass_env({"mode": "ssh_agent"}, original.copy(), root)
            env = {**original, "SSH_AUTH_SOCK": "/tmp/test-agent.sock"}
            returned, script = make_askpass_env({"mode": "ssh_agent"}, env.copy(), root)
            self.assertIsNone(script)
            self.assertEqual(returned["SSH_AUTH_SOCK"], "/tmp/test-agent.sock")

    def test_git_command_timeout_is_reported_as_git_error_with_output(self):
        timeout = subprocess.TimeoutExpired(["git", "fetch"], 1, output=b"partial stdout", stderr=b"partial stderr")
        with patch("publisher_engine.gitops.run_process", side_effect=timeout):
            with self.assertRaisesRegex(GitError, "timed out after 600 seconds") as caught:
                run_git(["fetch", "origin", "main"])
        self.assertIn("partial stdout", str(caught.exception))
        self.assertIn("partial stderr", str(caught.exception))

    def test_publisher_ref_override_is_validated_before_clone(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            destination = root / "publisher-clone"
            for unsafe in ("--upload-pack=/bin/sh", "bad ref", "bad..ref", "ref.lock", "bad\x00ref"):
                with self.subTest(ref=unsafe), self.assertRaises(GitError):
                    clone_publisher("/does/not/matter.git", unsafe, destination, os.environ.copy())
                self.assertFalse(destination.exists(), "invalid refs must fail before cloning")

    def _lfs_source(self):
        return {
            "id": "docs",
            "vcs": {"clone_url": "https://example.invalid/docs.git", "default_ref": "main",
                    "ref_type": "branch", "depth": 1, "lfs": True},
            "integration": {"prefix": "subtrees/docs", "squash": True, "history": "shallow"},
        }

    def test_lfs_remote_is_unique_and_removed_after_success(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            clone = root / "publisher-clone"
            clone.mkdir()
            calls = []
            def fake_run_git(args, **kwargs):
                calls.append(list(args))
                if args[:2] == ["rev-parse", "FETCH_HEAD"]:
                    return "a" * 40
                if args[:2] == ["subtree", "add"]:
                    (clone / "subtrees/docs").mkdir(parents=True, exist_ok=True)
                if args[:2] == ["rev-parse", "HEAD"]:
                    return "b" * 40
                return ""
            with patch("publisher_engine.gitops.ensure_git_subtree"), \
                 patch("publisher_engine.gitops.run_process", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")), \
                 patch("publisher_engine.gitops.run_git", side_effect=fake_run_git):
                result = integrate_subtree(clone, self._lfs_source(), root, root / "run", {"PATH": os.environ.get("PATH", "")})
            added = next(c[2] for c in calls if c[:2] == ["remote", "add"])
            removed = next(c[2] for c in calls if c[:2] == ["remote", "remove"])
            self.assertTrue(added.startswith("publisher-lfs-"))
            self.assertEqual(added, removed)
            self.assertEqual(result["source_commit"], "a" * 40)

    def test_lfs_remote_add_failure_never_removes_preexisting_remote(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            clone = root / "publisher-clone"
            clone.mkdir()
            calls = []
            def fake_run_git(args, **kwargs):
                calls.append(list(args))
                if args[:2] == ["rev-parse", "FETCH_HEAD"]:
                    return "a" * 40
                if args[:2] == ["remote", "add"]:
                    raise GitError("remote name already exists")
                return ""
            with patch("publisher_engine.gitops.ensure_git_subtree"), \
                 patch("publisher_engine.gitops.run_process", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")), \
                 patch("publisher_engine.gitops.run_git", side_effect=fake_run_git):
                with self.assertRaisesRegex(GitError, "remote name already exists"):
                    integrate_subtree(clone, self._lfs_source(), root, root / "run", {"PATH": os.environ.get("PATH", "")})
            self.assertFalse(any(c[:2] == ["remote", "remove"] for c in calls))


class BuildTaskAndLockTests(unittest.TestCase):
    def _task(self, argv: list[str], **overrides) -> dict:
        task = {
            "id": "test-task", "argv": argv, "environment": {},
            "pass_environment": [], "secret_environment": [],
            "working_directory_scope": "source", "working_directory": ".",
            "timeout_seconds": 5, "retry": 0, "outputs": [],
        }
        task.update(overrides)
        return task

    def test_task_sensitive_passthrough_requires_secret_environment(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["build_tasks"][0]["pass_environment"] = ["PATH", "BUILD_TOKEN"]
            p = root / "publisher.yml"
            p.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "must use secret_environment"):
                load_config(p)


    def test_task_environment_is_allowlisted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            publisher = root / "publisher"
            source.mkdir(); publisher.mkdir()
            result = _run_command(
                self._task([sys.executable, "-c", "import os; print(os.getenv('ALLOWED')); print(os.getenv('NOT_ALLOWED'))"],
                           pass_environment=["ALLOWED"]),
                publisher, source, root, {"PATH": os.environ.get("PATH", ""), "ALLOWED": "yes", "NOT_ALLOWED": "no"}, {},
            )
            self.assertEqual(result["status"], "success")

    def test_task_secret_is_redacted_from_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            publisher = root / "publisher"
            source.mkdir(); publisher.mkdir()
            task = self._task(
                [sys.executable, "-c", "import os,sys; print(os.environ['API_KEY']); sys.exit(7)"],
                environment={"API_KEY": "${BUILD_SECRET}"}, secret_environment=["BUILD_SECRET"],
            )
            with self.assertRaises(BuildError) as caught:
                _run_command(task, publisher, source, root,
                             {"PATH": os.environ.get("PATH", ""), "BUILD_SECRET": "private-value"}, {})
            self.assertNotIn("private-value", str(caught.exception))
            self.assertIn("<redacted>", str(caught.exception))

    def test_task_rejects_unallowlisted_secret_and_escaping_working_directory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            publisher = root / "publisher"
            source.mkdir(); publisher.mkdir()
            task = self._task([sys.executable, "-c", "pass"], environment={"X": "${NOT_ALLOWED}"})
            with self.assertRaises(BuildError):
                _run_command(task, publisher, source, root, {"PATH": os.environ.get("PATH", "")}, {})
            task = self._task([sys.executable, "-c", "pass"], working_directory="../outside")
            with self.assertRaises(BuildError):
                _run_command(task, publisher, source, root, {"PATH": os.environ.get("PATH", "")}, {})

    def test_task_timeout_and_declared_output_validation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            publisher = root / "publisher"
            source.mkdir(); publisher.mkdir()
            timeout_task = self._task([sys.executable, "-c", "import time; time.sleep(2)"], timeout_seconds=1)
            with self.assertRaisesRegex(BuildError, "timeout"):
                _run_command(timeout_task, publisher, source, root, {"PATH": os.environ.get("PATH", "")}, {})
            missing_output = self._task([sys.executable, "-c", "pass"], outputs=["missing/*.html"])
            with self.assertRaisesRegex(BuildError, "did not match"):
                _run_command(missing_output, publisher, source, root, {"PATH": os.environ.get("PATH", "")}, {})
            unsafe_output = self._task([sys.executable, "-c", "pass"], outputs=["../outside"])
            with self.assertRaisesRegex(BuildError, "unsafe declared output"):
                _run_command(unsafe_output, publisher, source, root, {"PATH": os.environ.get("PATH", "")}, {})

    def test_task_retry_succeeds_after_transient_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            publisher = root / "publisher"
            source.mkdir(); publisher.mkdir()
            code = (
                "from pathlib import Path; import sys; "
                "p=Path(r'{run_root}/attempted'); "
                "(sys.exit(0) if p.exists() else (p.write_text('1'), sys.exit(1)))"
            )
            task = self._task([sys.executable, "-c", code], retry=1, retry_delay_seconds=0)
            result = _run_command(task, publisher, source, root, {"PATH": os.environ.get("PATH", "")}, {})
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["attempt"], 2)

    def test_build_lock_rejects_a_concurrent_writer_and_releases_its_lock(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "_site"
            with BuildLock(output, timeout=0):
                lock_path = output.with_name("._site.publisher.lock")
                self.assertTrue(lock_path.is_file())
                with self.assertRaisesRegex(BuildError, "Another build holds lock"):
                    with BuildLock(output, timeout=0):
                        self.fail("second lock should not be acquired")
            self.assertFalse(lock_path.exists())

    def test_build_lock_detects_dead_local_process_lock(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "_site"
            lock_path = output.with_name("._site.publisher.lock")
            import json
            host = os.uname().nodename if hasattr(os, "uname") else os.environ.get("COMPUTERNAME", "unknown")
            lock_path.write_text(json.dumps({"pid": 999999999, "host": host, "token": "stale"}), encoding="utf-8")
            self.assertTrue(BuildLock._stale(lock_path))
            with BuildLock(output, timeout=0):
                self.assertTrue(lock_path.exists())
            self.assertFalse(lock_path.exists())


class CliSafetyTests(unittest.TestCase):
    def _workflow_config(self) -> dict:
        sha = "c" * 40
        return {
            "workflow": {"provider": "github_actions", "actions": {
                "checkout": f"actions/checkout@{sha}", "setup_python": f"actions/setup-python@{sha}",
                "upload_pages_artifact": f"actions/upload-pages-artifact@{sha}",
                "deploy_pages": f"actions/deploy-pages@{sha}",
            }},
            "triggers": {"manual": True}, "publisher": {"ref": "main"},
            "site": {"output_directory": "_site"}, "publishing": {"target_id": "artifact"},
            "workflow_file": ".github/workflows/publish.yml",
        }

    def test_cli_preserves_existing_workflow_without_explicit_replace(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "workflow.yml"
            output.write_text("keep existing", encoding="utf-8")
            stderr = io.StringIO()
            with patch("publisher_engine.cli.load_config", return_value=self._workflow_config()), \
                 patch("publisher_engine.cli.generate_github_actions_workflow", return_value="new workflow"), \
                 patch("sys.stderr", stderr):
                result = cli_main(["generate-workflow", "--config", str(Path(td) / "publisher.yml"), "--output", str(output)])
            self.assertEqual(result, 1)
            self.assertEqual(output.read_text(encoding="utf-8"), "keep existing")
            self.assertIn("already exists", stderr.getvalue())

            with patch("publisher_engine.cli.load_config", return_value=self._workflow_config()), \
                 patch("publisher_engine.cli.generate_github_actions_workflow", return_value="new workflow"):
                result = cli_main(["generate-workflow", "--config", str(Path(td) / "publisher.yml"),
                                   "--output", str(output), "--replace-existing"])
            self.assertEqual(result, 0)
            self.assertEqual(output.read_text(encoding="utf-8"), "new workflow")

    def test_cli_explicit_output_rejects_git_metadata_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            git_dir = root / ".git"
            git_dir.mkdir()
            output = git_dir / "generated-workflow.yml"
            stderr = io.StringIO()
            with patch("publisher_engine.cli.load_config", return_value=self._workflow_config()), \
                 patch("publisher_engine.cli.generate_github_actions_workflow", return_value="must not write"), \
                 patch("sys.stderr", stderr):
                result = cli_main(["generate-workflow", "--config", str(root / "publisher.yml"),
                                   "--output", str(output)])
            self.assertEqual(result, 1)
            self.assertFalse(output.exists())
            self.assertIn("Git metadata", stderr.getvalue())

    def test_cli_explicit_output_rejects_symlink_parent_into_git_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            git_dir = root / ".git"
            git_dir.mkdir()
            link = root / "workflow-output"
            try:
                link.symlink_to(git_dir, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Symlink creation is unavailable on this platform")
            output = link / "generated-workflow.yml"
            stderr = io.StringIO()
            with patch("publisher_engine.cli.load_config", return_value=self._workflow_config()), \
                 patch("publisher_engine.cli.generate_github_actions_workflow", return_value="must not write"), \
                 patch("sys.stderr", stderr):
                result = cli_main(["generate-workflow", "--config", str(root / "publisher.yml"),
                                   "--output", str(output)])
            self.assertEqual(result, 1)
            self.assertFalse((git_dir / "generated-workflow.yml").exists())
            self.assertIn("Git metadata", stderr.getvalue())

    def test_cli_explicit_output_still_allows_an_explicit_external_directory(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside_td:
            root = Path(td)
            output = Path(outside_td) / "generated.yml"
            with patch("publisher_engine.cli.load_config", return_value=self._workflow_config()), \
                 patch("publisher_engine.cli.generate_github_actions_workflow", return_value="generated"):
                result = cli_main(["generate-workflow", "--config", str(root / "publisher.yml"),
                                   "--output", str(output)])
            self.assertEqual(result, 0)
            self.assertEqual(output.read_text(encoding="utf-8"), "generated")

    def test_cli_rejects_workflow_path_through_symlink_into_git_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            git_dir = root / ".git"
            git_dir.mkdir()
            try:
                (root / ".github").symlink_to(git_dir, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Symlink creation is unavailable on this platform")
            config = self._workflow_config()
            config["workflow_file"] = ".github/workflows/generated.yml"
            config["workflow"]["file"] = ".github/workflows/generated.yml"
            stderr = io.StringIO()
            with patch("publisher_engine.cli.load_config", return_value=config), \
                 patch("publisher_engine.cli.generate_github_actions_workflow", return_value="should not be written"), \
                 patch("sys.stderr", stderr):
                result = cli_main(["generate-workflow", "--config", str(root / "publisher.yml")])
            self.assertEqual(result, 1)
            self.assertIn("Git metadata", stderr.getvalue())
            self.assertFalse((git_dir / "workflows" / "generated.yml").exists())

    def test_cli_nested_config_generates_workflow_at_checkout_root_and_uses_that_config(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".git").mkdir()
            config_dir = root / "configuration"
            config_dir.mkdir()
            config_path = config_dir / "publisher.yml"
            config = self._workflow_config()
            config["workflow"]["file"] = ".github/workflows/generated.yml"
            captured = {}
            def capture(cfg, *, profiles=None):
                captured.update(cfg)
                captured["_selected_profiles"] = profiles
                return "workflow content"
            with patch("publisher_engine.cli.load_config", return_value=config), \
                 patch("publisher_engine.cli.generate_github_actions_workflow", side_effect=capture):
                result = cli_main(["generate-workflow", "--config", str(config_path)])
            output = root / ".github" / "workflows" / "generated.yml"
            self.assertEqual(result, 0)
            self.assertEqual(output.read_text(encoding="utf-8"), "workflow content")
            self.assertEqual(captured["workflow"]["config_file"], "configuration/publisher.yml")

    def test_cli_writes_configured_workflow_path_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config_path = root / "publisher.yml"
            config = self._workflow_config()
            config["workflow"]["file"] = "automation/generated.yml"
            with patch("publisher_engine.cli.load_config", return_value=config), \
                 patch("publisher_engine.cli.generate_github_actions_workflow", return_value="generated workflow"):
                result = cli_main(["generate-workflow", "--config", str(config_path)])
            output = root / "automation" / "generated.yml"
            self.assertEqual(result, 0)
            self.assertEqual(output.read_text(encoding="utf-8"), "generated workflow")

    def test_cli_rejects_symlinked_workflow_parent_directory(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside_td:
            root = Path(td)
            outside = Path(outside_td)
            (root / "automation-link").symlink_to(outside, target_is_directory=True)
            config = self._workflow_config()
            config["workflow"]["file"] = "automation-link/generated.yml"
            stderr = io.StringIO()
            with patch("publisher_engine.cli.load_config", return_value=config), \
                 patch("publisher_engine.cli.generate_github_actions_workflow", return_value="new workflow"), \
                 patch("sys.stderr", stderr):
                result = cli_main(["generate-workflow", "--config", str(root / "publisher.yml")])
            self.assertEqual(result, 1)
            self.assertFalse((outside / "generated.yml").exists())
            self.assertIn("Path escapes configured root", stderr.getvalue())

    def test_cli_does_not_write_configured_workflow_outside_project(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            publisher_remote = init_remote(root / "publisher", {"README.md": "x"})
            source_remote = init_remote(root / "source", {"docs/page.adoc": "x"})
            cfg = base_config(root, publisher_remote, source_remote)
            cfg["workflow"] = {"provider": "github_actions", "file": "../outside.yml"}
            config = root / "publisher.yml"
            outside = root.parent / f"{root.name}-outside.yml"
            config.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
            result = cli_main(["generate-workflow", "--config", str(config)])
            self.assertEqual(result, 1)
            self.assertFalse(outside.exists())

    def test_cli_refuses_workflow_symlink_and_handles_git_errors_cleanly(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "target.yml"
            target.write_text("keep", encoding="utf-8")
            output = root / "workflow.yml"
            try:
                output.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("Symlink creation is unavailable on this platform")
            stderr = io.StringIO()
            with patch("publisher_engine.cli.load_config", return_value=self._workflow_config()), \
                 patch("publisher_engine.cli.generate_github_actions_workflow", return_value="new"), \
                 patch("sys.stderr", stderr):
                result = cli_main(["generate-workflow", "--config", str(root / "publisher.yml"), "--output", str(output), "--replace-existing"])
            self.assertEqual(result, 1)
            self.assertEqual(target.read_text(encoding="utf-8"), "keep")
            self.assertIn("symlink", stderr.getvalue())

            stderr = io.StringIO()
            with patch("publisher_engine.cli.build", side_effect=GitError("remote fetch failed")), \
                 patch("sys.stderr", stderr):
                result = cli_main(["build", "--config", str(root / "publisher.yml")])
            self.assertEqual(result, 1)
            self.assertIn("remote fetch failed", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_init_config_creates_packaged_fail_closed_template_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "publisher.yml"
            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                result = cli_main(["init-config", "--output", str(output)])
            self.assertEqual(result, 0)
            packaged = (ROOT / "publisher_engine" / "data" / "publisher.example.yml").read_text(encoding="utf-8")
            generated = output.read_text(encoding="utf-8")
            self.assertEqual(generated, packaged)
            self.assertIn("Replace every <PLACEHOLDER>", stdout.getvalue())
            self.assertIn("<PUBLISHER_GIT_CLONE_URL>", generated)
            self.assertIn("<BUILD_SOURCE_GIT_URL>", generated)
            self.assertIn("<SOURCE_ALLOWED_HOST>", generated)
            self.assertNotIn("https://example.invalid", generated)
            self.assertNotIn("keycloak/keycloak", generated)

            output.write_text("operator-owned configuration", encoding="utf-8")
            stderr = io.StringIO()
            with patch("sys.stderr", stderr):
                result = cli_main(["init-config", "--output", str(output)])
            self.assertEqual(result, 1)
            self.assertEqual(output.read_text(encoding="utf-8"), "operator-owned configuration")
            self.assertIn("was not changed", stderr.getvalue())

    def test_init_config_rejects_git_metadata_and_missing_parent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".git").mkdir()
            stderr = io.StringIO()
            with patch("sys.stderr", stderr):
                result = cli_main(["init-config", "--output", str(root / ".git" / "publisher.yml")])
            self.assertEqual(result, 1)
            self.assertFalse((root / ".git" / "publisher.yml").exists())
            self.assertIn("Git metadata", stderr.getvalue())

            missing = root / "not-created" / "publisher.yml"
            stderr = io.StringIO()
            with patch("sys.stderr", stderr):
                result = cli_main(["init-config", "--output", str(missing)])
            self.assertEqual(result, 1)
            self.assertFalse(missing.parent.exists())
            self.assertIn("output directory does not exist", stderr.getvalue())

    def test_init_config_accepts_an_explicit_regular_template(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            template = root / "custom.yml"
            template.write_text("custom: template\n", encoding="utf-8")
            output = root / "generated.yml"
            self.assertEqual(cli_main(["init-config", "--template", str(template), "--output", str(output)]), 0)
            self.assertEqual(output.read_text(encoding="utf-8"), "custom: template\n")

    def test_cli_capabilities_matches_schema_supported_ids_and_discloses_unimplemented_providers(self):
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            result = cli_main(["capabilities"])
        self.assertEqual(result, 0)
        capabilities = json.loads(stdout.getvalue())
        schema = json.loads((ROOT / "schemas" / "publisher.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(
            set(capabilities["providers"]["workflow"]),
            set(schema["properties"]["workflow"]["properties"]["provider"]["enum"]),
        )
        self.assertEqual(
            set(capabilities["providers"]["publishing_adapters"]),
            set(schema["$defs"]["publishingTarget"]["properties"]["adapter"]["enum"]),
        )
        self.assertEqual(
            set(capabilities["providers"]["component_link_adapters"]),
            set(schema["$defs"]["component"]["properties"]["link_adapter"]["enum"]),
        )
        self.assertEqual(
            set(capabilities["providers"]["source_vcs"]),
            {schema["$defs"]["source"]["properties"]["vcs"]["properties"]["provider"]["const"]},
        )
        self.assertIn("bitbucket_pipeline_provider", capabilities["not_implemented"])
        self.assertEqual(capabilities["providers"]["workflow"]["gitlab_ci"]["status"], "implemented")
        self.assertEqual(capabilities["providers"]["authoring_links"]["provider_label_semantics"], "metadata_only")
        self.assertEqual(capabilities["providers"]["communication"]["provider_label_semantics"], "metadata_only")

    def test_cli_profile_is_forwarded_to_publish(self):
        stdout = io.StringIO()
        with patch("publisher_engine.cli.publish", return_value={"status": "planned"}) as mocked, \
             patch("sys.stdout", stdout):
            result = cli_main(["publish", "--config", "publisher.yml", "--profile", "staging", "--profile", "production"])
        self.assertEqual(result, 0)
        self.assertEqual(mocked.call_args.args[0], Path("publisher.yml"))
        self.assertEqual(mocked.call_args.kwargs["profiles"], ["staging", "production"])

    def test_cli_profile_is_forwarded_to_workflow_generation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config_path = root / "publisher.yml"
            output = root / "workflow.yml"
            config = self._workflow_config()
            captured = {}
            def capture(cfg, *, profiles=None):
                captured.update(cfg)
                captured["_selected_profiles"] = profiles
                return "workflow content"
            with patch("publisher_engine.cli.load_config", return_value=config) as loader, \
                 patch("publisher_engine.cli.generate_github_actions_workflow", side_effect=capture):
                result = cli_main(["generate-workflow", "--config", str(config_path), "--output", str(output),
                                   "--profile", "staging", "--profile", "production"])
            self.assertEqual(result, 0)
            self.assertEqual(loader.call_args.args[1], ["staging", "production"])
            self.assertEqual(output.read_text(encoding="utf-8"), "workflow content")


class WorkflowGenerationTests(unittest.TestCase):
    def _valid_config(self) -> dict:
        sha = "b" * 40
        return {
            "workflow": {
                "provider": "github_actions",
                "actions": {
                    "checkout": f"actions/checkout@{sha}",
                    "setup_python": f"actions/setup-python@{sha}",
                    "upload_pages_artifact": f"actions/upload-pages-artifact@{sha}",
                    "deploy_pages": f"actions/deploy-pages@{sha}",
                },
            },
            "triggers": {"manual": True},
            "publisher": {"ref": "main"},
            "site": {"output_directory": "_site"},
            "publishing": {"artifact_name": "site", "retention_days": 1, "dry_run": False},
        }

    def test_workflow_requires_full_sha_action_refs(self):
        cfg={"workflow":{"provider":"github_actions","actions":{"checkout":"actions/checkout@v4"}},"triggers":{"manual":True},"publisher":{"ref":"main"},"site":{"output_directory":"_site"}}
        with self.assertRaises(WorkflowError): generate_github_actions_workflow(cfg)

    def test_action_ref_rejects_yaml_injection_and_non_repository_action(self):
        cfg = self._valid_config()
        cfg["workflow"]["actions"]["checkout"] = "actions/checkout@" + "a" * 40 + "\n    run: echo injected"
        with self.assertRaisesRegex(WorkflowError, "repository/action path"):
            generate_github_actions_workflow(cfg)

        cfg = self._valid_config()
        cfg["workflow"]["actions"]["checkout"] = "docker://attacker/image@" + "a" * 40
        with self.assertRaises(WorkflowError):
            generate_github_actions_workflow(cfg)

    def test_generated_workflow_installs_the_packaged_project_not_only_dependencies(self):
        cfg = self._valid_config()
        rendered = generate_github_actions_workflow(cfg)
        self.assertIn("- name: Install engine package", rendered)
        self.assertIn("run: python -m pip install .", rendered)
        self.assertNotIn("pip install -r requirements.txt", rendered)

    def test_selected_profiles_are_forwarded_to_generated_validation_and_build_steps(self):
        cfg = self._valid_config()
        rendered = generate_github_actions_workflow(cfg, profiles=["base", "production-2026"])
        validate_line = next(line for line in rendered.splitlines() if "validate-config --config" in line)
        build_line = next(line for line in rendered.splitlines() if "cli build --config" in line)
        self.assertIn("--profile base --profile production-2026", validate_line)
        self.assertIn("--profile base --profile production-2026", build_line)

    def test_generated_workflow_rejects_unsafe_profile_names(self):
        cfg = self._valid_config()
        for bad in ("Prod", "../prod", "prod;touch-pwned", "", "-prod"):
            with self.subTest(profile=bad), self.assertRaisesRegex(WorkflowError, "lower-case profile identifiers"):
                generate_github_actions_workflow(cfg, profiles=[bad])

    def test_config_path_is_passed_through_env_not_shell_interpolation(self):
        cfg = self._valid_config()
        injected = "$(touch /tmp/publisher-config-path-injection)"
        cfg["workflow"]["config_file"] = injected
        result = generate_github_actions_workflow(cfg)
        self.assertIn(f"CONFIG_FILE: {json.dumps(injected)}", result)
        self.assertIn('run: python -m publisher_engine.cli validate-config --config "$CONFIG_FILE"', result)
        self.assertNotIn(f'validate-config --config {json.dumps(injected)}', result)
        self.assertIsNotNone(yaml.compose(result))

    def test_secret_binding_is_required_and_pull_request_secret_use_is_rejected(self):
        cfg = self._valid_config()
        cfg["publisher"]["auth"] = {"mode": "environment", "secret_env": "PUBLISH_TOKEN"}
        with self.assertRaisesRegex(WorkflowError, "must map every secret"):
            generate_github_actions_workflow(cfg)

        cfg["workflow"]["secrets"] = {"PUBLISH_TOKEN": "PUBLISHER_TOKEN"}
        cfg["triggers"] = {"manual": True, "pull_request": True}
        with self.assertRaisesRegex(WorkflowError, "pull_request builds cannot rely"):
            generate_github_actions_workflow(cfg)

    def test_ssh_agent_and_weak_permissions_are_rejected(self):
        cfg = self._valid_config()
        cfg["publisher"]["auth"] = {"mode": "ssh_agent"}
        with self.assertRaisesRegex(WorkflowError, "does not provision SSH_AUTH_SOCK"):
            generate_github_actions_workflow(cfg)

        cfg = self._valid_config()
        cfg["workflow"]["build_permissions"] = {"contents": "none"}
        with self.assertRaisesRegex(WorkflowError, "cannot weaken required permission"):
            generate_github_actions_workflow(cfg)

        cfg = self._valid_config()
        cfg["workflow"]["deploy_permissions"] = {"pages": "read", "id-token": "write", "actions": "read"}
        with self.assertRaisesRegex(WorkflowError, "cannot weaken required permission"):
            generate_github_actions_workflow(cfg)

    def test_trigger_and_environment_constraints_are_enforced(self):
        cfg = self._valid_config()
        cfg["triggers"] = {"manual": False}
        with self.assertRaisesRegex(WorkflowError, "At least one"):
            generate_github_actions_workflow(cfg)

        cfg = self._valid_config()
        cfg["triggers"] = {"manual": True, "push_branches": ["main", "stable"]}
        with self.assertRaisesRegex(WorkflowError, "deploy_branch is required"):
            generate_github_actions_workflow(cfg)

        cfg = self._valid_config()
        cfg["workflow"]["environment"] = {"BAD-NAME": "value"}
        with self.assertRaisesRegex(WorkflowError, "Invalid workflow.environment"):
            generate_github_actions_workflow(cfg)

        cfg = self._valid_config()
        cfg["workflow"]["environment"] = {"GOOD_NAME": "line1\nline2"}
        with self.assertRaisesRegex(WorkflowError, "Multiline"):
            generate_github_actions_workflow(cfg)

        cfg = self._valid_config()
        cfg["workflow"]["environment"] = {"TOKEN": "${{ secrets.MY_TOKEN }}"}
        with self.assertRaisesRegex(WorkflowError, "use workflow.secrets"):
            generate_github_actions_workflow(cfg)

        cfg = self._valid_config()
        cfg["workflow"]["environment"] = {"GITHUB_TOKEN": "literal"}
        with self.assertRaisesRegex(WorkflowError, "reserved runner variable"):
            generate_github_actions_workflow(cfg)

        cfg = self._valid_config()
        cfg["publisher"]["auth"] = {"mode": "environment", "secret_env": "PUBLISH_TOKEN"}
        cfg["workflow"]["secrets"] = {"PUBLISH_TOKEN": "PUBLISHER_TOKEN"}
        cfg["workflow"]["environment"] = {"PUBLISH_TOKEN": "override"}
        with self.assertRaisesRegex(WorkflowError, "cannot define the same environment"):
            generate_github_actions_workflow(cfg)

    def test_artifact_path_is_relative_to_nested_configuration_file(self):
        cfg = self._valid_config()
        cfg["workflow"]["config_file"] = "configuration/publisher.yml"
        result = generate_github_actions_workflow(cfg)
        parsed = yaml.load(result, Loader=NoDuplicateKeyLoader)
        upload_step = next(
            step for step in parsed["jobs"]["build"]["steps"]
            if step.get("name") == "Upload GitHub Pages artifact"
        )
        self.assertEqual(upload_step["with"]["path"], "configuration/_site")

    def test_workflow_rejects_artifact_paths_that_escape_checkout(self):
        cfg = self._valid_config()
        cfg["workflow"]["config_file"] = "configuration/publisher.yml"
        cfg["site"]["output_directory"] = "../../outside"
        with self.assertRaisesRegex(WorkflowError, "inside the publisher checkout"):
            generate_github_actions_workflow(cfg)

    def test_strict_yaml_loader_rejects_duplicate_mapping_keys(self):
        duplicate = "jobs:\n  build:\n    run: first\n    run: second\n"
        with self.assertRaisesRegex(yaml.constructor.ConstructorError, "duplicate key"):
            yaml.load(duplicate, Loader=NoDuplicateKeyLoader)

        cfg = self._valid_config()
        generated = generate_github_actions_workflow(cfg)
        parsed = yaml.load(generated, Loader=NoDuplicateKeyLoader)
        build_steps = parsed["jobs"]["build"]["steps"]
        build_step = next(step for step in build_steps if step.get("name") == "Build and validate site")
        self.assertEqual(build_step["run"].count("publisher_engine.cli build"), 1)
        self.assertEqual(build_step["env"]["CONFIG_FILE"], "publisher.yml")

    def test_workflow_generates_separate_build_and_deploy_jobs(self):
        sha="a"*40
        cfg={"workflow":{"provider":"github_actions","actions":{"checkout":f"actions/checkout@{sha}","setup_python":f"actions/setup-python@{sha}","upload_pages_artifact":f"actions/upload-pages-artifact@{sha}","deploy_pages":f"actions/deploy-pages@{sha}"}},
             "triggers":{"manual":True,"push_branches":["stable"],"deploy_branch":"stable"},
             "publisher":{"ref":"stable"},"site":{"output_directory":"_site"},"publishing":{"artifact_name":"site","retention_days":1,"dry_run":False}}
        result=generate_github_actions_workflow(cfg)
        self.assertIn("  build:", result)
        self.assertIn("  deploy:", result)
        self.assertIn("actions: read", result)
        self.assertIn("github.sha", result)
        self.assertIn('name: "site"', result)
        self.assertIn('artifact_name: "site"', result)
        self.assertNotIn("artifact_name: github-pages", result)
        self.assertIsNotNone(yaml.compose(result))
        yaml.load(result, Loader=NoDuplicateKeyLoader)
        self.assertNotIn("artifact_name: github-pages", result)
        # PyYAML's compose parses the generated workflow without depending on
        # YAML 1.1's special treatment of the GitHub key named `on`.
        self.assertIsNotNone(yaml.compose(result))


class GitLabWorkflowGenerationTests(unittest.TestCase):
    def _config(self, *, dry_run: bool = True) -> dict:
        return {
            "workflow": {
                "provider": "gitlab_ci",
                "container_image": "registry.example.invalid/docs/python@sha256:" + "a" * 64,
                "python_version": "3.13",
                "config_file": "publisher.yml",
            },
            "triggers": {
                "manual": True,
                "push_branches": ["main"],
                "pull_request": True,
                "deploy_branch": "main",
                "paths": ["docs/**/*", "publisher.yml"],
            },
            "publisher": {"ref": "main"},
            "site": {"output_directory": "_site"},
            "publishing": {"artifact_name": "site", "retention_days": 1, "dry_run": dry_run},
        }

    def test_gitlab_dry_run_generates_validation_and_build_without_pages_job(self):
        rendered = generate_gitlab_ci_workflow(self._config(dry_run=True), profiles=["base", "staging"])
        parsed = yaml.load(rendered, Loader=NoDuplicateKeyLoader)
        self.assertEqual(parsed["default"]["image"], "registry.example.invalid/docs/python@sha256:" + "a" * 64)
        self.assertEqual(set(parsed["stages"]), {"validate", "build"})
        self.assertIn("validate-config", parsed)
        self.assertIn("build-site", parsed)
        self.assertNotIn("deploy-pages", parsed)
        self.assertEqual(parsed["build-site"]["artifacts"]["paths"], ["_site"])
        build_command = "\n".join(parsed["build-site"]["script"])
        self.assertIn("--profile base --profile staging", build_command)
        self.assertIn("--publisher-ref", build_command)
        self.assertNotIn("CI_JOB_TOKEN", build_command.split("--publisher-ref", 1)[-1])
        self.assertIn("when: never", rendered)

    def test_gitlab_live_pages_job_is_branch_gated_and_uses_pages_publish(self):
        parsed = yaml.load(generate_gitlab_ci_workflow(self._config(dry_run=False)), Loader=NoDuplicateKeyLoader)
        self.assertEqual(parsed["stages"], ["validate", "build", "deploy"])
        deploy = parsed["deploy-pages"]
        self.assertEqual(deploy["needs"], [{"job": "build-site", "artifacts": True}])
        self.assertEqual(deploy["pages"], {"publish": "_site"})
        self.assertEqual(deploy["artifacts"]["paths"], ["_site"])
        self.assertEqual(deploy["rules"][-1], {"when": "never"})
        self.assertIn('"main"', deploy["rules"][0]["if"])

    def test_gitlab_config_directory_is_applied_to_pages_path(self):
        cfg = self._config(dry_run=False)
        cfg["workflow"]["config_file"] = "configuration/publisher.yml"
        parsed = yaml.load(generate_gitlab_ci_workflow(cfg), Loader=NoDuplicateKeyLoader)
        self.assertEqual(parsed["build-site"]["artifacts"]["paths"], ["configuration/_site"])
        self.assertEqual(parsed["deploy-pages"]["pages"]["publish"], "configuration/_site")

    def test_gitlab_container_image_must_be_digest_pinned(self):
        for value in ("python:3.13-slim", "registry.example.invalid/docs@sha256:abc", "-bad@sha256:" + "a" * 64):
            cfg = self._config()
            cfg["workflow"]["container_image"] = value
            with self.subTest(image=value), self.assertRaisesRegex(WorkflowError, "full sha256 digest"):
                generate_gitlab_ci_workflow(cfg)

    def test_gitlab_rejects_untrusted_merge_request_secrets(self):
        cfg = self._config()
        cfg["workflow"]["secrets"] = {"SOURCE_TOKEN": "DOCS_SOURCE_TOKEN"}
        with self.assertRaisesRegex(WorkflowError, "merge-request pipelines"):
            generate_gitlab_ci_workflow(cfg)

    def test_gitlab_secret_mapping_exports_only_explicit_variables(self):
        cfg = self._config()
        cfg["triggers"]["pull_request"] = False
        cfg["workflow"]["secrets"] = {"SOURCE_TOKEN": "DOCS_SOURCE_TOKEN"}
        rendered = generate_gitlab_ci_workflow(cfg)
        self.assertIn('export SOURCE_TOKEN="${DOCS_SOURCE_TOKEN:?Required GitLab CI/CD variable DOCS_SOURCE_TOKEN is missing}"', rendered)
        self.assertIn("env -u CI_JOB_TOKEN", rendered)
        parsed = yaml.load(rendered, Loader=NoDuplicateKeyLoader)
        self.assertNotIn("DOCS_SOURCE_TOKEN", parsed["build-site"]["variables"])
        validation_install = parsed["validate-config"]["script"][1]
        build_install = parsed["build-site"]["script"][2]
        for install_command in (validation_install, build_install):
            self.assertIn("env -u CI_JOB_TOKEN", install_command)
            self.assertIn("-u CI_REPOSITORY_URL", install_command)
            self.assertIn("-u CI_REGISTRY_PASSWORD", install_command)
            self.assertIn("-u CI_DEPLOY_PASSWORD", install_command)
            self.assertIn("python -m pip install", install_command)

    def test_gitlab_rejects_reserved_runner_overrides_and_secret_names(self):
        for environment in ({"CI_JOB_TOKEN": "x"}, {"GITLAB_USER_LOGIN": "x"}):
            cfg = self._config()
            cfg["workflow"]["environment"] = environment
            with self.subTest(environment=environment), self.assertRaises(WorkflowError):
                generate_gitlab_ci_workflow(cfg)
        cfg = self._config()
        cfg["triggers"]["pull_request"] = False
        cfg["workflow"]["secrets"] = {"SOURCE_TOKEN": "CI_JOB_TOKEN"}
        with self.assertRaisesRegex(WorkflowError, "reserved GitLab runner variable"):
            generate_gitlab_ci_workflow(cfg)

    def test_gitlab_rejects_unsupported_trigger_and_path_semantics(self):
        cfg = self._config()
        cfg["triggers"]["workflow_call"] = True
        with self.assertRaisesRegex(WorkflowError, "workflow_call"):
            generate_gitlab_ci_workflow(cfg)
        cfg = self._config()
        cfg["triggers"]["paths"] = ["!secret/**"]
        with self.assertRaisesRegex(WorkflowError, "positive path patterns"):
            generate_gitlab_ci_workflow(cfg)

    def test_gitlab_cli_defaults_to_gitlab_ci_filename(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config_path = root / "publisher.yml"
            config = self._config()
            captured = {}
            def capture(cfg, *, profiles=None):
                captured["provider"] = cfg["workflow"]["provider"]
                return "stages:\n  - validate\n"
            with patch("publisher_engine.cli.load_config", return_value=config), \
                 patch("publisher_engine.cli.generate_gitlab_ci_workflow", side_effect=capture):
                result = cli_main(["generate-workflow", "--config", str(config_path)])
            self.assertEqual(result, 0)
            self.assertEqual(captured["provider"], "gitlab_ci")
            self.assertTrue((root / ".gitlab-ci.yml").is_file())


class R8CorrectionRegressionTests(unittest.TestCase):
    def test_dry_run_workflow_is_build_only_even_without_deploy_action_refs(self):
        cfg = WorkflowGenerationTests()._valid_config()
        cfg["publishing"]["dry_run"] = True
        cfg["workflow"]["actions"].pop("upload_pages_artifact")
        cfg["workflow"]["actions"].pop("deploy_pages")
        rendered = generate_github_actions_workflow(cfg)
        self.assertIn("  build:", rendered)
        self.assertNotIn("  deploy:", rendered)
        self.assertNotIn("Upload GitHub Pages artifact", rendered)
        self.assertNotIn("Deploy validated artifact", rendered)
        self.assertNotIn("uses: actions/upload-pages-artifact@", rendered)
        self.assertIsNotNone(yaml.compose(rendered))

    def test_artifact_target_output_path_must_match_site_output_directory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["publishing_targets"][0]["output_path"] = "different-directory"
            with self.assertRaisesRegex(ConfigError, "must match site.output_directory"):
                semantic_validate(cfg)

    def test_non_dry_run_is_explicit_deployment_opt_in(self):
        cfg = WorkflowGenerationTests()._valid_config()
        cfg["publishing"]["dry_run"] = False
        rendered = generate_github_actions_workflow(cfg)
        self.assertIn("  deploy:", rendered)
        self.assertIn("Upload GitHub Pages artifact", rendered)

    def test_checkout_does_not_persist_credentials(self):
        cfg = WorkflowGenerationTests()._valid_config()
        rendered = generate_github_actions_workflow(cfg)
        parsed = yaml.load(rendered, Loader=NoDuplicateKeyLoader)
        checkout = next(step for step in parsed["jobs"]["build"]["steps"]
                        if step.get("name") == "Checkout workflow and configuration")
        self.assertIs(checkout["with"]["persist-credentials"], False)

    def test_build_permission_allowlist_rejects_writes_and_extra_scopes(self):
        for permissions in ({"contents": "write"}, {"contents": "read", "id-token": "write"}):
            with self.subTest(permissions=permissions):
                cfg = WorkflowGenerationTests()._valid_config()
                cfg["workflow"]["build_permissions"] = permissions
                with self.assertRaises(WorkflowError):
                    generate_github_actions_workflow(cfg)

    def test_reserved_internal_environment_variables_cannot_be_overridden(self):
        for name in ("PATH", "CONFIG_FILE", "SELECTED_COMPONENTS", "PUBLISHER_REF", "GITHUB_ENV"):
            with self.subTest(name=name):
                cfg = WorkflowGenerationTests()._valid_config()
                cfg["workflow"]["environment"] = {name: "attacker-value"}
                with self.assertRaisesRegex(WorkflowError, "reserved runner variable"):
                    generate_github_actions_workflow(cfg)

    def test_workspace_path_inside_git_metadata_is_rejected_before_creation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            git(["init", "-b", "main"], root)
            target = root / ".git" / "objects" / "publisher-tmp"
            with self.assertRaisesRegex(BuildError, "Git metadata"):
                _guard_not_git_metadata(target, root, label="workspace.temp_root")
            self.assertFalse(target.exists())

    def test_workspace_symlink_resolving_into_git_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            git(["init", "-b", "main"], root)
            link = root / "temporary"
            try:
                link.symlink_to(root / ".git", target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable")
            with self.assertRaisesRegex(BuildError, "Git metadata"):
                _guard_not_git_metadata(link / "objects" / "publisher-tmp", root,
                                        label="workspace.temp_root")

    def test_site_output_overlapping_tracked_code_is_rejected_without_modification(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            git(["init", "-b", "main"], root)
            git(["config", "user.name", "Publisher Test"], root)
            git(["config", "user.email", "publisher-test@example.invalid"], root)
            protected = root / "publisher_engine" / "engine.py"
            protected.parent.mkdir()
            protected.write_text("protected-code\n", encoding="utf-8")
            git(["add", "publisher_engine/engine.py"], root)
            git(["commit", "-m", "baseline"], root)
            before = protected.read_bytes()
            with self.assertRaisesRegex(BuildError, "tracked repository content"):
                _guard_not_tracked_output(root / "publisher_engine", root, label="site.output_directory")
            self.assertEqual(protected.read_bytes(), before)

    def test_component_parent_child_routes_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["components"][1]["route"] = "guide/server_admin"
            with self.assertRaisesRegex(ConfigError, "routes overlap"):
                semantic_validate(cfg)

    def test_fallback_scheme_validation_matches_runtime_allowlist(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["components"][0]["fallback"] = {"mode": "redirect", "url": "http://legacy.example.invalid/"}
            cfg["validation"]["validate_redirect_schemes"] = ["https"]
            with self.assertRaisesRegex(ConfigError, r"allowed absolute HTTP\(S\) scheme"):
                semantic_validate(cfg)
            cfg["validation"]["validate_redirect_schemes"] = ["https", "http"]
            semantic_validate(cfg)

    def test_repository_refs_are_checked_with_git_grammar_before_clone(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for target in ("publisher", "source", "authoring"):
                cfg = base_config(root, root / "publisher.git", root / "source.git")
                if target == "publisher":
                    cfg["publisher"]["ref"] = "bad?ref"
                elif target == "source":
                    cfg["sources"][0]["vcs"]["default_ref"] = "bad?ref"
                else:
                    cfg["authoring_targets"][0]["ref"] = "bad?ref"
                with self.subTest(target=target), self.assertRaisesRegex(ConfigError, "not a valid Git"):
                    semantic_validate(cfg)

    def test_git_subtree_preflight_reports_exec_path_and_environment_override(self):
        from subprocess import CompletedProcess
        failed = CompletedProcess(["git", "subtree", "-h"], 1, "", "git: 'subtree' is not a git command")
        exec_path = CompletedProcess(["git", "--exec-path"], 0, "/usr/lib/git-core\n", "")
        with patch("publisher_engine.gitops.run_process", side_effect=[failed, exec_path]), \
             patch.dict(os.environ, {"GIT_EXEC_PATH": "/custom/git-core"}, clear=False):
            with self.assertRaisesRegex(GitError, "git --exec-path=/usr/lib/git-core; GIT_EXEC_PATH=/custom/git-core"):
                ensure_git_subtree()

    def test_git_subtree_preflight_timeout_is_bounded_and_reported(self):
        import subprocess as subprocess_module
        with patch("publisher_engine.gitops.run_process", side_effect=subprocess_module.TimeoutExpired(["git", "subtree", "-h"], 10)):
            with self.assertRaisesRegex(GitError, "preflight timed out after 10s"):
                ensure_git_subtree()

    def test_file_repository_urls_cannot_bypass_host_allowlist(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["sources"][0]["vcs"]["clone_url"] = "file:///tmp/private-source.git"
            cfg["sources"][0]["vcs"]["allowed_hosts"] = ["github.com"]
            with self.assertRaisesRegex(ConfigError, "file://"):
                semantic_validate(cfg)

    def test_empty_component_output_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["components"][0]["output_path"] = ""
            with self.assertRaisesRegex(ConfigError, "output_path must be a non-empty"):
                semantic_validate(cfg)

    def test_site_base_url_query_and_fragment_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for suffix in ("?preview=1", "#section"):
                cfg = base_config(root, root / "publisher.git", root / "source.git")
                cfg["site"]["base_url"] = "https://docs.example.invalid" + suffix
                with self.subTest(suffix=suffix), self.assertRaisesRegex(ConfigError, "query string or fragment"):
                    semantic_validate(cfg)

    def test_public_page_url_contains_github_pages_base_path(self):
        cfg = {"site": {"base_url": "https://example.invalid", "base_path": "/keycloak-pages"}}
        self.assertEqual(_site_public_url(cfg, "docs/current/server_admin/index.html"),
                         "https://example.invalid/keycloak-pages/docs/current/server_admin/index.html")

    def test_public_page_url_uses_custom_canonical_origin_and_project_path(self):
        cfg = {"site": {"base_url": "https://org.github.io", "canonical_base_url": "https://docs.example.invalid",
                        "base_path": "keycloak-pages/"}}
        self.assertEqual(_site_public_url(cfg, "docs/current/index.html"),
                         "https://docs.example.invalid/keycloak-pages/docs/current/index.html")

    def test_root_relative_html_references_are_prefixed_for_project_pages(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            page = root / "index.html"
            page.write_text(
                '<!doctype html>\n<html><head>\n'
                '<link rel="stylesheet" href="/assets/site.css">\n'
                '<meta http-equiv="refresh" content="0;url=/docs/current/">\n'
                '<style>.hero{background:url(/images/hero.svg)} @import "/css/extra.css";</style>\n'
                '</head><body>\n'
                '<a href="/docs/current/guide/?from=home&amp;view=full#intro">Guide</a>\n'
                '<img src="/images/logo.svg" srcset="/images/logo-1x.png 1x, /images/logo-2x.png 2x">\n'
                '<script src=/assets/app.js></script>\n'
                '<iframe src="/embedded/help.html"></iframe>\n'
                '<object data="/files/guide.pdf"></object>\n'
                '<form action="/search"><button formaction="/search/advanced">Search</button></form>\n'
                '<div style="background-image:url(\'/images/panel.svg?theme=dark&size=2\')"></div>\n'
                '<a href="/keycloak-pages/already-prefixed.html">Already prefixed</a>\n'
                '<a href="//cdn.example.invalid/lib.js">CDN</a> <a href="../relative.html">Relative</a>\n'
                '<a href="\\legacy-rooted.html">Backslash-rooted</a>\n'
                '<a href="#section">Fragment</a>\n'
                '</body></html>', encoding="utf-8")
            (root / "assets").mkdir()
            (root / "assets/site.css").write_text(
                'body{background:url("/images/background.png?v=2&theme=dark")}\n'
                '@import "/assets/theme.css";\n'
                '.external{background:url(https://cdn.example.invalid/x.png)}', encoding="utf-8")
            cfg = {"site": {"base_url": "https://example.invalid", "base_path": "/keycloak-pages"}}

            first_count = _rewrite_root_relative_site_urls(root, cfg)
            rewritten = page.read_text(encoding="utf-8")
            css = (root / "assets/site.css").read_text(encoding="utf-8")

            for expected in (
                'href="/keycloak-pages/assets/site.css"',
                'content="0;url=/keycloak-pages/docs/current/"',
                'url(/keycloak-pages/images/hero.svg)',
                '@import "/keycloak-pages/css/extra.css"',
                'href="/keycloak-pages/docs/current/guide/?from=home&amp;view=full#intro"',
                'src="/keycloak-pages/images/logo.svg"',
                'srcset="/keycloak-pages/images/logo-1x.png 1x, /keycloak-pages/images/logo-2x.png 2x"',
                'src=/keycloak-pages/assets/app.js',
                'src="/keycloak-pages/embedded/help.html"',
                'data="/keycloak-pages/files/guide.pdf"',
                'action="/keycloak-pages/search"',
                'formaction="/keycloak-pages/search/advanced"',
                'url(&#x27;/keycloak-pages/images/panel.svg?theme=dark&amp;size=2&#x27;)',
                'href="/keycloak-pages/already-prefixed.html"',
                'href="//cdn.example.invalid/lib.js"',
                'href="../relative.html"',
                'href="/keycloak-pages/legacy-rooted.html"',
                'href="#section"',
            ):
                with self.subTest(expected=expected):
                    self.assertIn(expected, rewritten)
            self.assertIn('url("/keycloak-pages/images/background.png?v=2&theme=dark")', css)
            self.assertIn('@import "/keycloak-pages/assets/theme.css"', css)
            self.assertIn('url(https://cdn.example.invalid/x.png)', css)
            self.assertGreaterEqual(first_count, 10)

            # Running the base-path transformation twice must not duplicate it.
            second_count = _rewrite_root_relative_site_urls(root, cfg)
            self.assertEqual(second_count, 0)
            self.assertEqual(page.read_text(encoding="utf-8"), rewritten)
            self.assertEqual((root / "assets/site.css").read_text(encoding="utf-8"), css)

    def test_root_relative_rewrite_is_noop_for_domain_root_deployment(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            page = root / "index.html"
            original = '<a href="/docs/current/">Docs</a><img src="/assets/logo.svg">'
            page.write_text(original, encoding="utf-8")
            self.assertEqual(_rewrite_root_relative_site_urls(root, {"site": {"base_url": "https://docs.example.invalid", "base_path": ""}}), 0)
            self.assertEqual(page.read_text(encoding="utf-8"), original)

    def test_page_url_template_context_includes_project_pages_prefix(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            (source / "docs").mkdir(parents=True)
            (source / "docs/page.adoc").write_text("= Guide", encoding="utf-8")
            staging = root / "staging"
            page = staging / "docs/current/guide/index.html"
            page.parent.mkdir(parents=True)
            page.write_text('<a class="publisher-link-issues" href="https://old.invalid">Report</a>', encoding="utf-8")
            config = {
                "project": {"id": "fixture", "title": "Fixture", "locale": "en"},
                "site": {"base_url": "https://org.github.io", "base_path": "/keycloak-pages",
                         "components_root": "docs", "version": "current",
                         "component_path_template": "{components_root}/{version}/{route}"},
                "links": {"edit": {"mode": "inherit"}},
                "communication": {"issues": {"mode": "override",
                                                "url_template": "https://issues.example.invalid/new?page={page_url}"}},
                "authoring_targets": [], "validation": {},
                "components": [{"id": "guide", "title": "Guide", "source_id": "content", "route": "guide"}],
            }
            errors, report = _rewrite_links(staging, config, config["components"], {"content": source})
            self.assertEqual(errors, [])
            self.assertEqual(len(report), 1)
            self.assertEqual(report[0]["href"],
                             "https://issues.example.invalid/new?page=https%3A%2F%2Forg.github.io%2Fkeycloak-pages%2Fdocs%2Fcurrent%2Fguide%2Findex.html")

    def test_site_public_path_preserves_query_fragment_and_is_idempotent(self):
        cfg = {"site": {"base_path": "/repo"}}
        self.assertEqual(_site_public_path(cfg, "/assets/app.js?v=2#main"), "/repo/assets/app.js?v=2#main")
        self.assertEqual(_site_public_path(cfg, "/repo/assets/app.js?v=2#main"), "/repo/assets/app.js?v=2#main")
        self.assertEqual(_site_public_path(cfg, "https://cdn.example.invalid/app.js"), "https://cdn.example.invalid/app.js")
        self.assertEqual(_site_public_path(cfg, "//cdn.example.invalid/app.js"), "//cdn.example.invalid/app.js")

    def test_noindex_is_injected_into_root_404_and_component_html(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name, html in {
                "index.html": "<!doctype html><html><head><title>Root</title></head><body>root</body></html>",
                "404.html": "<html><body>missing</body></html>",
                "docs/current/guide/index.html": "<html><head><meta charset='utf-8'></head><body>guide</body></html>",
            }.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(html, encoding="utf-8")
            _inject_noindex(root)
            for page in root.rglob("*.html"):
                content = page.read_text(encoding="utf-8")
                self.assertIn('name="robots" content="noindex,nofollow"', content)

    def test_active_data_urls_and_srcdoc_are_rejected_but_passive_png_image_is_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "index.html").write_text(
                '<html><body><iframe src="data:text/html;base64,PHNjcmlwdD4="></iframe>'
                '<script src="data:text/javascript;base64,YWxlcnQoMSk=" ></script>'
                '<img src="data:image/png;base64,AAAA" alt="pixel"></body></html>', encoding="utf-8")
            cfg = {"validation": {"validate_local_links": True, "validate_css_assets": False,
                                  "require_build_manifest": False, "max_files": 100,
                                  "max_site_bytes": 100000, "validate_fragments": False},
                   "site": {"base_path": "repo", "base_url": "https://example.invalid"}}
            errors = validate_site(root, cfg)
            self.assertTrue(any("Data URL is not permitted in iframe src" in e for e in errors), errors)
            self.assertTrue(any("Data URL is not permitted in script src" in e for e in errors), errors)
            self.assertFalse(any("img src" in e for e in errors), errors)

    def test_iframe_srcdoc_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "index.html").write_text('<iframe srcdoc="<script>alert(1)</script>"></iframe>', encoding="utf-8")
            cfg = {"validation": {"validate_local_links": True, "validate_css_assets": False,
                                  "require_build_manifest": False, "max_files": 100,
                                  "max_site_bytes": 100000, "validate_fragments": False},
                   "site": {"base_path": "repo", "base_url": "https://example.invalid"}}
            errors = validate_site(root, cfg)
            self.assertTrue(any("srcdoc is not permitted" in e for e in errors), errors)

    def test_keycloak_asciidoc_header_links_get_exact_file_provenance_and_editor_url(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            source_file = source / "docs/documentation/server_admin/index.adoc"
            source_file.parent.mkdir(parents=True)
            source_file.write_text("= Keycloak Server Administration", encoding="utf-8")
            staging = root / "staging"
            page = staging / "docs/current/keycloak/index.html"
            page.parent.mkdir(parents=True)
            page.write_text(
                '<html><body><nav class="page-links">'
                '<a href="https://github.com/keycloak/keycloak/edit/main/docs/documentation/server_admin/index.adoc" target="_blank">Edit this section</a>'
                '<a href="https://github.com/keycloak/keycloak/issues/new?template=bug.yml&amp;title=Docs">Report an issue</a>'
                '</nav></body></html>', encoding="utf-8")
            target = {
                "id": "keycloak-authoring", "provider_label": "github",
                "web_url": "https://github.com/devrimcode/keycloak",
                "repository": "devrimcode/keycloak", "ref": "main", "ref_type": "branch",
                "source_id": "keycloak",
                "edit_url_template": "{web_url}/edit/{ref}/{path}",
                "mapping": {"source_prefix": "docs/documentation", "target_prefix": "docs/documentation"},
            }
            config = {
                "project": {"id": "keycloak-docs", "title": "Keycloak", "locale": "en"},
                "sources": [{"id": "keycloak", "vcs": {
                    "web_url": "https://github.com/keycloak/keycloak", "default_ref": "main"
                }}],
                "site": {"base_url": "https://docs.example.invalid", "base_path": "/keycloak-pages",
                         "components_root": "docs", "version": "current",
                         "component_path_template": "{components_root}/{version}/{route}"},
                "links": {"edit": {"mode": "override", "target_id": "keycloak-authoring",
                                    "unresolved_policy": "fail", "require_markers": True}},
                "authoring_targets": [target],
                "communication": {},
                "validation": {"unresolved_edit_policy": "fail"},
                "components": [{
                    "id": "keycloak-docs", "title": "Keycloak Documentation", "source_id": "keycloak",
                    "route": "keycloak", "locale": "en", "version": "current",
                    "link_adapter": "keycloak_asciidoc", "link_overrides": {"edit": {"mode": "inherit"}},
                }],
            }
            errors, report = _rewrite_links(staging, config, config["components"], {"keycloak": source})
            self.assertEqual(errors, [])
            html = page.read_text(encoding="utf-8")
            self.assertIn('href="https://github.com/devrimcode/keycloak/edit/main/docs/documentation/server_admin/index.adoc"', html)
            self.assertNotIn('href="https://github.com/keycloak/keycloak/edit/main/', html)
            self.assertIn('href="https://github.com/keycloak/keycloak/issues/new?template=bug.yml&amp;title=Docs"', html)
            edit_items = [item for item in report if item["channel"] == "edit"]
            self.assertEqual(len(edit_items), 1)
            self.assertEqual(edit_items[0]["source_file"], "docs/documentation/server_admin/index.adoc")

    def test_keycloak_edit_issue_and_neighbor_links_have_three_independent_destinations(self):
        """The three link classes must not derive destinations from publisher/source identity."""
        scenarios = [
            {
                "name": "separate targets",
                "edit": "https://github.com/devrimcode/keycloak",
                "issues": "https://github.com/keycloak/keycloak",
                "navigation": "https://github.com/devrimcode/keycloak",
            },
            {
                "name": "edit target changed alone",
                "edit": "https://github.com/xyz/mein-keycloak",
                "issues": "https://github.com/keycloak/keycloak",
                "navigation": "https://github.com/devrimcode/keycloak",
            },
            {
                "name": "issue target changed alone",
                "edit": "https://github.com/devrimcode/keycloak",
                "issues": "https://github.com/xyz/mein-keycloak",
                "navigation": "https://github.com/devrimcode/keycloak",
            },
            {
                "name": "navigation target changed alone",
                "edit": "https://github.com/devrimcode/keycloak",
                "issues": "https://github.com/keycloak/keycloak",
                "navigation": "https://github.com/xyz/mein-keycloak",
            },
            {
                "name": "all targets independently changed",
                "edit": "https://github.com/xyz/mein-keycloak",
                "issues": "https://github.com/xyz/mein-keycloak",
                "navigation": "https://github.com/xyz/mein-keycloak",
            },
        ]
        for scenario in scenarios:
            with self.subTest(scenario=scenario["name"]), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                source = root / "source"
                source_file = source / "docs/documentation/server_admin/index.adoc"
                source_file.parent.mkdir(parents=True)
                source_file.write_text("= Source guide", encoding="utf-8")

                staging = root / "staging"
                page = staging / "docs/current/keycloak/index.html"
                page.parent.mkdir(parents=True)
                page.write_text(
                    '<html><body><nav>'
                    '<a href="https://github.com/keycloak/keycloak/tree/main/docs/documentation/server_admin/index.adoc">Edit this section</a>'
                    '<a href="https://github.com/keycloak/keycloak/issues/new?template=bug.yml&amp;title=Docs">Report an issue</a>'
                    '<a href="https://github.com/keycloak/keycloak/issues/123">View related ticket</a>'
                    '<a href="https://github.com/keycloak/keycloak/issues">Browse all issues</a>'
                    '<a href="https://www.keycloak.org/docs/latest/server_admin/">Server Administration Guide</a>'
                    '<a href="https://www.example.org/outside/">Unrelated external link</a>'
                    '</nav></body></html>', encoding="utf-8")

                edit_target = {
                    "id": "keycloak-authoring", "provider_label": "github",
                    "web_url": scenario["edit"], "repository": scenario["edit"].split("github.com/")[1],
                    "ref": "main", "ref_type": "branch", "source_id": "keycloak",
                    "edit_url_template": "{web_url}/edit/{ref}/{path}",
                    "mapping": {"source_prefix": "docs/documentation", "target_prefix": "docs/documentation"},
                }
                config = {
                    "project": {"id": "keycloak-docs", "title": "Keycloak", "locale": "en"},
                    "publisher": {"clone_url": "https://github.com/devrimcode/documentation-publisher.git", "ref": "main"},
                    "sources": [{"id": "keycloak", "vcs": {
                        "web_url": "https://github.com/keycloak/keycloak", "default_ref": "main"
                    }}],
                    "site": {"base_url": "https://docs.example.invalid", "base_path": "/publisher",
                             "components_root": "docs", "version": "current",
                             "component_path_template": "{components_root}/{version}/{route}"},
                    "links": {
                        "edit": {"mode": "override", "target_id": "keycloak-authoring", "require_markers": True},
                        "issues": {
                            "mode": "override",
                            "source_prefixes": ["https://github.com/keycloak/keycloak/issues"],
                            "target_url": scenario["issues"],
                            "url_template": "{target_url}/issues/{path}{query_suffix}{fragment_suffix}",
                            "require_markers": True,
                        },
                        "navigation": {
                            "mode": "override",
                            "source_prefixes": ["https://www.keycloak.org/docs/", "/docs/"],
                            "relative_prefixes": ["../"],
                            "source_page_base_url": "https://www.keycloak.org/docs/latest/",
                            "target_url": scenario["navigation"], "target_ref": "main",
                            "url_template": "{target_url}/tree/{target_ref}/{path}{query_suffix}{fragment_suffix}",
                            "mapping": {"strip_leading_segments": 1, "target_prefix": "docs/documentation",
                                        "collapse_index_file": "index.html"},
                            "require_markers": True,
                        },
                    },
                    "authoring_targets": [edit_target],
                    "communication": {},
                    "validation": {"unresolved_edit_policy": "fail"},
                    "components": [{
                        "id": "keycloak-docs", "title": "Keycloak Documentation", "source_id": "keycloak",
                        "route": "keycloak", "locale": "en", "version": "current",
                        "link_adapter": "keycloak_asciidoc",
                    }],
                }
                errors, report = _rewrite_links(staging, config, config["components"], {"keycloak": source})
                self.assertEqual(errors, [])
                html = page.read_text(encoding="utf-8")

                edit_path = "docs/documentation/server_admin/index.adoc"
                self.assertIn(f'href="{scenario["edit"]}/edit/main/{edit_path}"', html)
                self.assertIn(
                    f'href="{scenario["issues"]}/issues/new?template=bug.yml&amp;title=Docs"', html
                )
                self.assertIn(f'href="{scenario["issues"]}/issues/123"', html)
                self.assertIn(f'href="{scenario["issues"]}/issues/"', html)
                self.assertIn(
                    f'href="{scenario["navigation"]}/tree/main/docs/documentation/server_admin"', html
                )
                self.assertIn('href="https://www.example.org/outside/"', html)
                self.assertNotIn("https://www.keycloak.org/docs/", html)

                counts = {name: len([item for item in report if item["channel"] == name])
                          for name in ("edit", "issues", "navigation")}
                self.assertEqual(counts, {"edit": 1, "issues": 3, "navigation": 1})

    def test_issue_route_is_preserved_beneath_independently_configured_repository_target(self):
        from publisher_engine.links import build_routed_link_url

        settings = {
            "mode": "override",
            "source_prefixes": ["https://github.com/keycloak/keycloak/issues"],
            "target_url": "https://github.com/xyz/mein-keycloak",
            "url_template": "{target_url}/issues/{path}{query_suffix}{fragment_suffix}",
        }
        self.assertEqual(
            build_routed_link_url(
                "issues", settings,
                "https://github.com/keycloak/keycloak/issues/123?tab=comments#issuecomment-456", {},
            ),
            "https://github.com/xyz/mein-keycloak/issues/123?tab=comments#issuecomment-456",
        )
        self.assertEqual(
            build_routed_link_url(
                "issues", settings, "https://github.com/keycloak/keycloak/issues/new", {},
            ),
            "https://github.com/xyz/mein-keycloak/issues/new",
        )
        self.assertEqual(
            build_routed_link_url(
                "issues", settings, "https://github.com/keycloak/keycloak/issues", {},
            ),
            "https://github.com/xyz/mein-keycloak/issues/",
        )

    def test_routed_navigation_override_requires_explicit_source_prefixes(self):
        from publisher_engine.config import _validate_routed_link
        with self.assertRaisesRegex(ConfigError, "source_prefixes must explicitly identify incoming navigation links"):
            _validate_routed_link(
                "navigation",
                {"mode": "override", "target_url": "https://github.com/org/docs",
                 "url_template": "{target_url}/tree/main/{path}"},
                "links.navigation",
            )

    def test_routed_link_template_must_preserve_the_matched_path(self):
        from publisher_engine.config import _validate_routed_link
        with self.assertRaisesRegex(ConfigError, r"must contain \{path\}"):
            _validate_routed_link(
                "issues",
                {"mode": "override", "target_url": "https://github.com/org/repo",
                 "source_prefixes": ["https://upstream.example/issues/"],
                 "url_template": "{target_url}"},
                "links.issues",
            )

    def test_issue_and_navigation_link_classes_can_be_disabled_independently(self):
        from publisher_engine.links import MarkerLinkRewriter, transform_keycloak_asciidoc_edit_links
        source = {"web_url": "https://github.com/keycloak/keycloak", "default_ref": "main"}
        policies = {
            "issues": {"mode": "disable", "source_prefixes": ["https://github.com/keycloak/keycloak/issues"]},
            "navigation": {"mode": "disable", "source_prefixes": ["https://www.keycloak.org/docs/"]},
        }
        markup = (
            '<a href="https://github.com/keycloak/keycloak/issues/new">Report an issue</a>'
            '<a href="https://www.keycloak.org/docs/latest/server_admin/">Neighbor guide</a>'
            '<a href="https://other.example/docs/latest/server_admin/">External link</a>'
        )
        converted, counts = transform_keycloak_asciidoc_edit_links(markup, source, "keycloak", policies)
        self.assertEqual(counts["issues"], 1)
        self.assertEqual(counts["navigation"], 1)
        parser = MarkerLinkRewriter(edit={"mode": "inherit"}, targets={}, communication={},
                                    link_policies=policies, source_id="keycloak")
        parser.feed(converted)
        parser.close()
        rendered = "".join(parser.output)
        self.assertEqual(parser.errors, [])
        self.assertNotIn('href="https://github.com/keycloak/keycloak/issues/new"', rendered)
        self.assertNotIn('href="https://www.keycloak.org/docs/latest/server_admin/"', rendered)
        self.assertIn("Report an issue", rendered)
        self.assertIn("Neighbor guide", rendered)
        self.assertIn('href="https://other.example/docs/latest/server_admin/"', rendered)

    def test_relative_neighbor_link_resolves_from_current_source_page(self):
        from publisher_engine.links import transform_keycloak_asciidoc_edit_links, MarkerLinkRewriter
        source = {"web_url": "https://github.com/keycloak/keycloak", "default_ref": "main"}
        policies = {"navigation": {
            "mode": "override",
            "source_prefixes": ["https://www.keycloak.org/docs/", "/docs/"],
            "relative_prefixes": ["../"],
            "source_page_base_url": "https://www.keycloak.org/docs/latest/",
            "target_url": "https://github.com/devrimcode/keycloak",
            "target_ref": "main",
            "url_template": "{target_url}/tree/{target_ref}/{path}{query_suffix}{fragment_suffix}",
            "mapping": {"strip_leading_segments": 1, "target_prefix": "docs/documentation", "collapse_index_file": "index.html"},
        }}
        markup = (
            '<a href="../server_admin/index.html#realm-settings">Server Administration</a>'
            '<a href="#local-section">Local section</a>'
            '<a href="other-local-page.html">Same-guide page</a>'
            '<a href="../assets/guide.pdf">PDF download</a>'
        )
        converted, counts = transform_keycloak_asciidoc_edit_links(
            markup, source, "keycloak", policies, page_rel="authorization_services/index.html"
        )
        self.assertEqual(counts["navigation"], 1)
        parser = MarkerLinkRewriter(edit={"mode": "inherit"}, targets={}, communication={},
                                    link_policies=policies, source_id="keycloak")
        parser.feed(converted)
        parser.close()
        rendered = "".join(parser.output)
        self.assertEqual(parser.errors, [])
        self.assertIn(
            'href="https://github.com/devrimcode/keycloak/tree/main/docs/documentation/server_admin#realm-settings"',
            rendered,
        )
        self.assertIn('href="#local-section"', rendered)
        self.assertIn('href="other-local-page.html"', rendered)
        self.assertIn('href="../assets/guide.pdf"', rendered)

    def test_disabled_routed_link_still_requires_explicit_source_selectors(self):
        from publisher_engine.config import _validate_routed_link
        _validate_routed_link(
            "issues", {"mode": "disable", "source_prefixes": ["https://github.com/org/repo/"]},
            "links.issues",
        )
        with self.assertRaisesRegex(ConfigError, "source_prefixes must explicitly identify incoming issues links"):
            _validate_routed_link("issues", {"mode": "disable"}, "links.issues")

    def test_keycloak_root_relative_neighbor_link_is_routed_but_foreign_absolute_is_not(self):
        from publisher_engine.links import transform_keycloak_asciidoc_edit_links
        source = {"web_url": "https://github.com/keycloak/keycloak", "default_ref": "main"}
        policy = {"navigation": {"mode": "override", "source_prefixes": ["/docs/"],
                                  "target_url": "https://github.com/devrimcode/keycloak",
                                  "target_ref": "main",
                                  "url_template": "{target_url}/tree/{target_ref}/{path}",
                                  "mapping": {"strip_leading_segments": 1, "target_prefix": "docs/documentation"}}}
        markup = (
            '<a href="/docs/26.8.2/server_admin/">Neighbor guide</a>'
            '<a href="https://evil.example/docs/26.8.2/server_admin/">Foreign guide</a>'
        )
        converted, counts = transform_keycloak_asciidoc_edit_links(markup, source, "keycloak", policy)
        self.assertEqual(counts["navigation"], 1)
        self.assertIn('data-publisher-link="navigation"', converted)
        self.assertIn('href="https://evil.example/docs/26.8.2/server_admin/"', converted)

    def test_routed_link_prefix_and_target_path_safety(self):
        from publisher_engine.links import _prefix_suffix, build_routed_link_url
        self.assertIsNone(_prefix_suffix(
            "https://evil.example/docs/latest/server_admin/", ["/docs/"]
        ))
        self.assertEqual(
            _prefix_suffix("/docs/latest/server_admin/", ["/docs/"]),
            "latest/server_admin/",
        )
        settings = {
            "target_url": "https://github.com/org/repo", "target_ref": "feature/docs",
            "source_prefixes": ["https://docs.example/docs/"],
            "mapping": {"strip_leading_segments": 1, "target_prefix": "docs",
                         "collapse_index_file": "index.html"},
            "url_template": "{target_url}/tree/{target_ref}/{path}",
        }
        self.assertEqual(
            build_routed_link_url("navigation", settings,
                                  "https://docs.example/docs/26.8.2/caf%C3%A9/", {}),
            "https://github.com/org/repo/tree/feature%2Fdocs/docs/caf%C3%A9",
        )
        self.assertEqual(
            build_routed_link_url("navigation", settings,
                                  "https://docs.example/docs/26.8.2/server_admin/index.html", {}),
            "https://github.com/org/repo/tree/feature%2Fdocs/docs/server_admin",
        )
        settings["url_template"] = "{target_url}/../../outside/{path}"
        with self.assertRaisesRegex(LinkResolutionError, "path traversal segment|escaped the explicitly configured target repository path"):
            build_routed_link_url("navigation", settings,
                                  "https://docs.example/docs/latest/guide/", {})

    def test_keycloak_asciidoc_adapter_fails_closed_on_source_ref_mismatch(self):
        from publisher_engine.links import transform_keycloak_asciidoc_edit_links
        source = {"web_url": "https://github.com/keycloak/keycloak", "default_ref": "release-branch"}
        markup = ('<a href="https://github.com/keycloak/keycloak/tree/main/docs/documentation/server_admin/index.adoc">'
                  'Edit this section</a>')
        with self.assertRaisesRegex(LinkResolutionError, "configured source repository/ref"):
            transform_keycloak_asciidoc_edit_links(markup, source, "keycloak")

    def test_component_inherit_uses_global_edit_override(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            source_file = source / "docs/page.adoc"
            source_file.parent.mkdir(parents=True)
            source_file.write_text("= Source", encoding="utf-8")
            staging = root / "staging"
            page = staging / "docs/current/guide/index.html"
            page.parent.mkdir(parents=True)
            page.write_text('<a data-publisher-link="edit" data-source-id="content" data-source-file="docs/page.adoc">Edit</a>', encoding="utf-8")
            target = {"id": "authoring", "web_url": "https://edit.example.invalid/repo",
                      "repository": "org/repo", "ref": "main", "source_id": "content",
                      "edit_url_template": "{web_url}/edit/{ref}/{path}",
                      "mapping": {"source_prefix": "docs", "target_prefix": "content"}}
            component = {"id": "guide", "title": "Guide", "source_id": "content", "route": "guide",
                         "link_overrides": {"edit": {"mode": "inherit", "require_markers": True}}}
            config = {
                "project": {"id": "fixture", "title": "Fixture", "locale": "en"},
                "site": {"base_url": "https://docs.example.invalid", "base_path": "",
                         "components_root": "docs", "version": "current",
                         "component_path_template": "{components_root}/{version}/{route}"},
                "links": {"edit": {"mode": "override", "target_id": "authoring", "require_markers": True}},
                "authoring_targets": [target], "communication": {},
                "validation": {"unresolved_edit_policy": "fail"}, "components": [component],
            }
            errors, report = _rewrite_links(staging, config, [component], {"content": source})
            self.assertEqual(errors, [])
            self.assertIn('href="https://edit.example.invalid/repo/edit/main/content/page.adoc"', page.read_text())
            self.assertEqual(len([x for x in report if x["channel"] == "edit"]), 1)


    def test_project_timezone_is_validated_as_an_installed_iana_name(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["project"]["timezone"] = "UTC"
            path = root / "timezone.yml"
            path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
            self.assertEqual(load_config(path)["project"]["timezone"], "UTC")
            for invalid in ("", "Mars/Olympus_Mons", "UTC+02:00"):
                cfg["project"]["timezone"] = invalid
                path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
                with self.subTest(timezone=invalid), self.assertRaisesRegex(ConfigError, "project.timezone"):
                    load_config(path)

    def test_unexpanded_environment_references_are_rejected_outside_supported_fields(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mutations = [
                ("workflow.environment", lambda cfg: cfg.update({"workflow": {"environment": {"PUBLIC_LABEL": "${DOCS_HOST}"}}})),
                ("component.output_path", lambda cfg: cfg["components"][0].update({"output_path": "${SITE_OUTPUT}"})),
                ("workflow.file", lambda cfg: cfg.update({"workflow": {"provider": "github_actions", "file": "${WORKFLOW_FILE}"}})),
                ("task.argv", lambda cfg: cfg["build_tasks"][0].update({"argv": [sys.executable, "-c", "print('${UNEXPANDED}')"]})),
                ("partial adapter reference", lambda cfg: cfg["build_tasks"][0].update({"environment": {"PUBLIC_LABEL": "prefix-${DOCS_HOST}"}, "pass_environment": ["PATH", "HOME", "DOCS_HOST"]})),
            ]
            for label, mutate in mutations:
                cfg = base_config(root, root / "publisher.git", root / "source.git")
                mutate(cfg)
                path = root / f"{label.replace('.', '-')}.yml"
                path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
                with self.subTest(location=label), self.assertRaisesRegex(ConfigError, "Unsupported or unallowlisted environment variable reference"):
                    load_config(path)

    def test_allow_missing_env_only_preserves_supported_expansion_fields(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["project"]["homepage_url"] = "https://${DOC_PUBLISHER_TEST_MISSING_HOST}/"
            path = root / "missing-public-env.yml"
            path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("DOC_PUBLISHER_TEST_MISSING_HOST", None)
                with self.assertRaisesRegex(ConfigError, "requires environment variable"):
                    load_config(path)
                loaded = load_config(path, allow_missing_env=True)
                self.assertEqual(loaded["project"]["homepage_url"], "https://${DOC_PUBLISHER_TEST_MISSING_HOST}/")

            cfg["workflow"] = {"environment": {"PUBLIC_LABEL": "${UNSUPPORTED_ENV}"}}
            path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "Unsupported or unallowlisted environment variable reference"):
                load_config(path, allow_missing_env=True)

    def test_exact_allowlisted_adapter_environment_references_remain_symbolic(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["build_tasks"][0]["environment"] = {"BUILD_LABEL": "${BUILD_LABEL}", "API_TOKEN": "${API_TOKEN}"}
            cfg["build_tasks"][0]["pass_environment"] = ["PATH", "HOME", "BUILD_LABEL"]
            cfg["build_tasks"][0]["secret_environment"] = ["API_TOKEN"]
            path = root / "adapter-env.yml"
            path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
            loaded = load_config(path)
            self.assertEqual(loaded["build_tasks"][0]["environment"], cfg["build_tasks"][0]["environment"])

    def test_workflow_generation_defensively_rejects_non_public_live_origin(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = base_config(root, root / "publisher.git", root / "source.git")
            cfg["publishing"]["dry_run"] = False
            cfg["site"]["base_url"] = "https://127.0.0.1"
            cfg["workflow"] = {
                "provider": "github_actions",
                "actions": {
                    "checkout": "actions/checkout@0123456789abcdef0123456789abcdef01234567",
                    "setup_python": "actions/setup-python@0123456789abcdef0123456789abcdef01234567",
                    "upload_pages_artifact": "actions/upload-pages-artifact@0123456789abcdef0123456789abcdef01234567",
                    "deploy_pages": "actions/deploy-pages@0123456789abcdef0123456789abcdef01234567",
                },
            }
            with self.assertRaisesRegex(WorkflowError, "Unsafe live publication origin"):
                generate_github_actions_workflow(cfg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
