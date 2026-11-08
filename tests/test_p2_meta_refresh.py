from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from test_engine import base_config, init_remote
from publisher_engine.engine import BuildError, build, validate_site


class MetaRefreshValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.publisher = init_remote(self.root / "publisher", {"README.md": "publisher"})
        self.source = init_remote(self.root / "source", {"docs/index.adoc": "= docs"})
        self.cfg = base_config(self.root, self.publisher, self.source)
        self.cfg["validation"]["require_build_manifest"] = False
        self.cfg["validation"]["validate_local_links"] = True
        self.cfg["validation"]["validate_fragments"] = True
        self.cfg["validation"]["validate_external_links"] = False
        self.cfg["validation"]["allowed_external_hosts"] = ["trusted.example.invalid"]
        self.site = self.root / "site"
        self.site.mkdir()
        (self.site / "index.html").write_text("<!doctype html><html><body>index</body></html>", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def page(self, html: str):
        (self.site / "index.html").write_text(html, encoding="utf-8")
        return validate_site(self.site, self.cfg)

    def test_javascript_meta_refresh_is_rejected_even_when_local_links_disabled(self):
        self.cfg["validation"]["validate_local_links"] = False
        errors = self.page('<html><head><meta http-equiv="refresh" content="0;url=javascript:alert(1)"></head></html>')
        self.assertTrue(any("scheme" in e.lower() and "javascript:" in e.lower() for e in errors), errors)

    def test_refresh_scheme_uses_validate_redirect_schemes(self):
        self.cfg["validation"]["validate_redirect_schemes"] = ["https"]
        errors = self.page('<html><head><meta http-equiv="refresh" content="0; URL=http://legacy.example.invalid/"></head></html>')
        self.assertTrue(any("scheme" in e.lower() and "http://legacy.example.invalid/" in e for e in errors), errors)

    def test_http_documentation_anchors_are_not_redirects(self):
        self.cfg["validation"]["validate_redirect_schemes"] = ["https"]
        http_examples = [
            "http://localhost:8080",
            "http://localhost:8080/admin/",
            "http://broker-keycloak:8180/realms/test/protocol/openid-connect/certs",
            "http://broker-keycloak:8180",
            "http://host.com/*$$",
            "http://host:port/realms/master/account",
            "http://localhost:8080/any",
            "http://localhost:8080/admin/realms/master/users",
            "http://localhost:8080/admin/realms/master/clients",
            "http://localhost:8080/admin/realms/demorealm/users",
        ]
        anchors = "".join(f'<a href="{url}">Example {index}</a>' for index, url in enumerate(http_examples))
        errors = self.page(f'<html><body>{anchors}</body></html>')
        self.assertEqual(errors, [], errors)

    def test_unsupported_anchor_schemes_remain_blocked(self):
        errors = self.page('<html><body><a href="ftp://example.invalid/file">unsupported</a></body></html>')
        self.assertTrue(any("URL scheme is not permitted" in e and "ftp://" in e for e in errors), errors)

    def test_external_refresh_host_uses_external_host_allowlist(self):
        self.cfg["validation"]["validate_external_links"] = True
        errors = self.page('<html><head><meta http-equiv="refresh" content="0;url=https://evil.example.invalid/landing"></head></html>')
        self.assertTrue(any("External host is not allowed" in e and "evil.example.invalid" in e for e in errors), errors)

    def test_local_refresh_target_must_exist(self):
        errors = self.page('<html><head><meta http-equiv="refresh" content="0;url=missing.html"></head></html>')
        self.assertTrue(any("Broken local link" in e and "missing.html" in e for e in errors), errors)

    def test_existing_local_refresh_target_is_accepted(self):
        (self.site / "next.html").write_text('<html><body id="next">next</body></html>', encoding="utf-8")
        errors = self.page('<html><head><meta http-equiv="Refresh" content="0; URL=\'next.html#next\'"></head></html>')
        self.assertEqual(errors, [])

    def test_no_url_refresh_is_not_treated_as_a_missing_link(self):
        errors = self.page('<html><head><meta http-equiv="refresh" content="5"></head></html>')
        self.assertEqual(errors, [])

    def test_root_relative_refresh_resolves_inside_project_base_path(self):
        (self.site / "next.html").write_text('<html><body>next</body></html>', encoding="utf-8")
        self.cfg["site"]["base_path"] = "/project"
        errors = self.page('<html><head><meta http-equiv="refresh" content="0;url=/project/next.html"></head></html>')
        self.assertEqual(errors, [])

    def test_allowed_https_refresh_host_is_accepted(self):
        self.cfg["validation"]["validate_external_links"] = True
        errors = self.page('<meta content="2; URL=\'https://trusted.example.invalid/landing?x=1&amp;y=2\'" HTTP-EQUIV="Refresh">')
        self.assertEqual(errors, [])

    def test_mailto_is_not_an_allowed_meta_refresh_scheme(self):
        errors = self.page('<meta http-equiv="refresh" content="0;url=mailto:docs@example.invalid">')
        self.assertTrue(any("URL scheme is not permitted" in e and "mailto:" in e for e in errors), errors)

    def test_data_url_is_not_an_allowed_meta_refresh_target(self):
        errors = self.page('<meta http-equiv="refresh" content="0;url=data:text/html,hello">')
        self.assertTrue(any("Data URL is not permitted" in e for e in errors), errors)

    def test_protocol_relative_refresh_host_uses_external_allowlist(self):
        self.cfg["validation"]["validate_external_links"] = True
        errors = self.page('<meta http-equiv="refresh" content="0; url=//evil.example.invalid/landing">')
        self.assertTrue(any("External host is not allowed" in e and "evil.example.invalid" in e for e in errors), errors)

    def test_missing_fragment_on_existing_local_refresh_target_is_rejected(self):
        (self.site / "next.html").write_text('<html><body><h1 id="present">next</h1></body></html>', encoding="utf-8")
        errors = self.page('<meta http-equiv="refresh" content="0;url=next.html#absent">')
        self.assertTrue(any("Missing fragment" in e and "next.html#absent" in e for e in errors), errors)

    def test_unterminated_quoted_refresh_target_is_rejected_when_local_check_is_disabled(self):
        self.cfg["validation"]["validate_local_links"] = False
        errors = self.page('<meta http-equiv="refresh" content="0;url=\'javascript:alert(1)">')
        self.assertTrue(any("Malformed meta refresh URL" in e for e in errors), errors)

    def test_unquoted_meta_refresh_content_is_still_validated(self):
        self.cfg["validation"]["validate_local_links"] = False
        errors = self.page('<meta HTTP-EQUIV=Refresh content=0;url=javascript:alert(1)>')
        self.assertTrue(any("URL scheme is not permitted" in e and "javascript:" in e for e in errors), errors)

    def test_real_subtree_build_accepts_http_documentation_anchors_with_https_only_redirects(self):
        http_examples = [
            "http://localhost:8080",
            "http://localhost:8080/admin/",
            "http://broker-keycloak:8180/realms/test/protocol/openid-connect/certs",
            "http://broker-keycloak:8180",
            "http://host.com/*$$",
            "http://host:port/realms/master/account",
            "http://localhost:8080/any",
            "http://localhost:8080/admin/realms/master/users",
            "http://localhost:8080/admin/realms/master/clients",
            "http://localhost:8080/admin/realms/demorealm/users",
        ]
        html = "".join(f'<a href="{url}">Example {i}</a>' for i, url in enumerate(http_examples))
        generated_code = (
            "from pathlib import Path; "
            "p=Path('build/generated/guide'); p.mkdir(parents=True, exist_ok=True); "
            f"(p/'index.html').write_text({html!r}, encoding='utf-8')"
        )
        self.cfg["build_tasks"][0]["argv"] = [sys.executable, "-c", generated_code]
        self.cfg["validation"]["validate_redirect_schemes"] = ["https"]
        self.cfg["links"]["edit"]["mode"] = "inherit"
        self.cfg["communication"]["issues"] = {"mode": "inherit"}
        self.cfg["communication"]["email"] = {"mode": "inherit"}
        config_path = self.root / "publisher.yml"
        config_path.write_text(yaml.safe_dump(self.cfg, sort_keys=False), encoding="utf-8")

        result = build(config_path, selected_ids=["guide"])

        self.assertEqual(result["status"], "success")
        published_page = self.root / "_site/docs/v1/guide/index.html"
        self.assertTrue(published_page.is_file())
        published_html = published_page.read_text(encoding="utf-8")
        for url in http_examples:
            self.assertIn(url, published_html)

    def test_real_subtree_build_rejects_javascript_meta_refresh_before_site_commit(self):
        generated_code = (
            "from pathlib import Path; "
            "p=Path('build/generated/guide'); p.mkdir(parents=True, exist_ok=True); "
            "(p/'index.html').write_text(\"<!doctype html><html><head>"
            "<meta http-equiv='refresh' content='0;url=javascript:alert(1)'>"
            "</head><body>unsafe redirect</body></html>\", encoding='utf-8')"
        )
        self.cfg["build_tasks"][0]["argv"] = [sys.executable, "-c", generated_code]
        # The test is specifically about site validation, so preserve upstream
        # links rather than requiring authoring/communication fixture markers.
        self.cfg["links"]["edit"]["mode"] = "inherit"
        self.cfg["communication"]["issues"] = {"mode": "inherit"}
        self.cfg["communication"]["email"] = {"mode": "inherit"}
        config_path = self.root / "publisher.yml"
        config_path.write_text(yaml.safe_dump(self.cfg, sort_keys=False), encoding="utf-8")
        with self.assertRaisesRegex(BuildError, "URL scheme is not permitted"):
            build(config_path, selected_ids=["guide"])
        self.assertFalse((self.root / "_site").exists(), "unsafe site output must not be committed")
        self.assertEqual(list((self.root / "runs").iterdir()), [], "failed build workspace must be cleaned")


if __name__ == "__main__":
    unittest.main(verbosity=2)
