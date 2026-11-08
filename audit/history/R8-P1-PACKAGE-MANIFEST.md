# P1 complete project package manifest

## Package identity

- Package: Documentation Publisher R8 correction, 2.0.10-dev, incremental P1
- Baseline archive: `documentation-publisher-v2-r8-corrected-2.0.10-dev-r8-027.zip`
- Baseline SHA-256: `6be1243c56f410aa920d5bb2083783613717854fe4adf21aeb1b87d329db9dac`
- Applied correction: independent validation switches (P1)

## Included project contents

This archive contains the complete project tree, including the Python package, JSON schema, example configurations, documentation, Dev Container feature, and full test suite. It also includes the P1 report, test output, and patch used to produce this version.

## Source changes relative to baseline

Exactly two executable/source files are changed by P1:

- `publisher_engine/engine.py`
- `tests/test_engine.py`

Additional documentation/evidence files are added:

- `R8-P1-VALIDATION-REPORT.md`
- `R8-P1-validation-switches.patch`
- `R8-P1-TEST-OUTPUT.txt`
- `R8-P1-PACKAGE-MANIFEST.md`

`R8-CORRECTION-STATUS.md` and `HARDENING-RELEASE-NOTES.md` contain an incremental P1 addendum.

## Verification

- Patch dry-run against the baseline: passed.
- Patch application against the baseline: passed.
- Targeted SiteValidationTests: 13 passed.
- Full suite: 149 passed, 0 failed.
- Python compilation: passed.

## Limits

P1 is the only new code correction in this package. No claim is made that P2–P7 or the remaining R8 audit findings have been fixed. No commit, push, publish, deployment, or modification of the user's Codespace was performed.
