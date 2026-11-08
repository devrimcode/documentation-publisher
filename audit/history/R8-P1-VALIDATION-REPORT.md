# R8 P1 — Independent validation switches

## Scope of this work step

This is the first isolated correction against the hash-identified R8-027 baseline package. It addresses only defect P1 from `R8-CONSOLIDATED-DEFECT-MATRIX.csv`:

- `validation.validate_fragments`
- `validation.validate_external_links`
- `validation.max_html_depth`
- independent handling of HTML vs. local-link/CSS-asset checks

It does not include P2–P7, R8-017/019/021/022, or the R8-009/011/027 acceptance work.

## Immutable baseline

- Input: `documentation-publisher-v2-r8-corrected-2.0.10-dev-r8-027.zip`
- SHA-256: `6be1243c56f410aa920d5bb2083783613717854fe4adf21aeb1b87d329db9dac`

All work was performed in an extracted copy under `/mnt/data`; the source archive and user's Codespace were not changed.

## Code changes

Only these two files changed:

- `publisher_engine/engine.py`
- `tests/test_engine.py`

`validate_site()` now parses HTML independently of local path existence validation. `validate_local_links` controls local target existence checks only. Fragment validation, external-host allowlisting, `max_html_depth`, and always-on active-content/scheme checks execute independently. CSS external-host allowlisting also runs when `validate_css_assets` is false; local CSS-asset existence checks remain controlled by `validate_css_assets`.

## Regression cases added

1. Fragment validation still runs with `validate_local_links=false`.
2. External-host allowlisting still runs with `validate_local_links=false`.
3. `max_html_depth` still runs with `validate_local_links=false`.
4. CSS external-host allowlisting still runs with `validate_css_assets=false`.
5. Active URL schemes remain blocked with `validate_local_links=false`.
6. Disabling local-link validation does disable missing-local-target errors.
7. Disabling fragment validation does not disable local-link existence checks.

## Test evidence

- Targeted `SiteValidationTests`: **13 passed**.
- Full baseline suite plus new regressions: **149 passed, 0 failed** (`python -m unittest discover -s tests -v`).
- Python compilation: passed (`python -m py_compile publisher_engine/*.py tests/*.py`).

## Disposition

P1 is corrected in this isolated candidate and has targeted regression coverage. It is not yet merged into a consolidated candidate with P2–P7. No commit, push, publish, deploy, or change to the user's active Codespace was performed.
