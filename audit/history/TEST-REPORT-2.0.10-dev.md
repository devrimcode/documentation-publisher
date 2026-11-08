> **Historischer Testbericht:** Dieser Bericht gehört zum früheren P11-Ausgangsstand vor R8-028-P1A. Die frühere Datei `publisher.keycloak.example.yml` wurde im aktuellen Kandidaten als `publisher.keycloak.smoke.yml` klar als Smoke-Fixture umbenannt. Maßgeblich für den aktuellen Stand ist `audit/R8-028-P1A-SECURITY-TOOLCHAIN-REPORT.md`.

# Test report – Documentation Publisher 2.0.10-dev

## Result

- Unit/regression tests: **140 passed, 0 failed** (134 existing tests plus 6 R8-009 regression/integration tests)
- Python bytecode compilation: passed
- CLI `--version`: reports `2.0.10-dev`
- CLI `validate-config --config publisher.keycloak.example.yml`: passed (1 source, 1 component, 1 task)
- JSON Schema metaschema check: passed
- Real local Git-subtree Project-Site fixture build: passed; generated HTML, static CSS, assets, canonical URL and local-link validation verified together

## R8-009 coverage

Regression coverage includes:

- GitHub Pages Project-Site prefixing for root-relative HTML/SVG URLs and CSS resources
- canonical URLs, custom canonical origin, and `{page_url}` template values
- HTML URL attributes including `href`, `src`, `poster`, `action`, `formaction`, `cite`, `background`, `manifest`, `data`, and `xlink:href`
- `srcset`, inline styles, `<style>` blocks, CSS `url(...)`, CSS `@import`, and meta-refresh targets
- query strings, fragments, backslash-rooted references, already-prefixed references, and idempotence
- no-op behavior for domain-root deployments and preservation of external/protocol-relative/relative URLs
- local HTML and CSS link validation after the prefix has been applied

## Commands

```bash
python -m unittest discover -s tests -v
python -m py_compile publisher_engine/*.py tests/*.py
python -m publisher_engine.cli --version
python -m publisher_engine.cli --help
python -m publisher_engine.cli validate-config --config publisher.keycloak.example.yml
```

## Scope limits

This report establishes local implementation and regression-test evidence. It does **not** claim a live browser acceptance on GitHub Pages, a production/custom-domain DNS setup, a GitHub Actions run, a full upstream Keycloak Maven build, browser/editor verification of Keycloak edit links, live Git LFS acceptance, a staging deployment, or production publishing. R8-009 remains subject to browser verification of a deployed Project-Site path before the finding is treated as fully accepted for release. See `R8-CORRECTION-STATUS.md`.
