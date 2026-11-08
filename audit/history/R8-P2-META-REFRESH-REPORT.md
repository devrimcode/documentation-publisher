# R8 incremental correction P2 — meta-refresh validation

## Decision

**P2 is implemented and differentially regression-tested in this candidate.** This closes only the meta-refresh validation defect described below. It does not close the remaining R8 audit findings or authorize release/publication.

## Immutable starting point

- Starting package: `documentation-publisher-v2-r8-corrected-2.0.10-dev-P1-full-project.zip`
- Starting SHA-256: `0b003f46ba7877b9f8ef77a69a0f7be2baf1c247c8f411196ef522cc208ec78f`
- The baseline was freshly extracted before the differential run.
- All modifications were made in an isolated working copy under `/mnt/data`.
- No change was made to the user's Codespace, branch, remotes, or Keycloak repository.

## Defect reproduced

`_HTMLCollector` collected URL-bearing HTML attributes (`href`, `src`, `poster`, etc.) but did not extract navigation destinations from `<meta http-equiv="refresh" content="...">`.

As a result, the site validator did not apply `validate_redirect_schemes`, `validate_external_links`, local-target existence checks, fragment checks, or active-scheme protections to those meta-refresh destinations. Malicious or invalid meta-refresh URLs could therefore pass validation.

## Correction

Files changed by P2:

- `publisher_engine/engine.py`
- `tests/test_p2_meta_refresh.py` (new)

Implementation behavior:

1. `_HTMLCollector` recognizes `meta` elements whose `http-equiv` value is `refresh`, case-insensitively.
2. `_meta_refresh_target()` extracts quoted and unquoted `url=` destinations from the content attribute.
3. Malformed quoted destinations are rejected independently of `validate_local_links`.
4. Meta-refresh URLs enter the same redirect scheme, external-host allowlist, local-target, and fragment validation path as navigation links.
5. Unlike ordinary `href`, meta-refresh does not permit `mailto:` or `tel:` destinations.
6. Delay-only refresh content without a URL is not treated as a missing link.

## Differential acceptance

The **same final 15-test P2 test module** was run against:

- a fresh extraction of the immutable P1 baseline; and
- the P2 corrected candidate.

Results:

| Run | Result |
|---|---:|
| P1 baseline, before P2 | 11 failures, 4 control cases passed |
| P2 corrected candidate | 15/15 passed |

The 11 baseline failures include:

- `javascript:` meta-refresh was not blocked;
- `data:` meta-refresh was not blocked;
- `mailto:` was incorrectly not rejected as a redirect scheme;
- `http:` did not respect the redirect-scheme allowlist;
- external and protocol-relative hosts did not respect the external-host allowlist;
- missing local targets and fragments were not reported;
- malformed quoted destinations were not rejected;
- a real subtree build containing a `javascript:` meta-refresh completed instead of failing site validation.

The four baseline controls passed before the correction: valid allowlisted HTTPS, valid existing local target, delay-only refresh, and valid Project-Site base-path target.

## Verification on the P2 candidate

- Targeted P2 tests: **15 passed, 0 failed**.
- Full test suite: **164 passed, 0 failed** (149 P1 tests plus 15 P2 tests).
- Python compilation: passed (`python -m py_compile publisher_engine/*.py tests/*.py`).
- CLI version: `2.0.10-dev`.
- Keycloak sample config validation: passed (1 source, 1 component, 1 task).
- The real local Git-subtree build test generated an unsafe meta-refresh HTML page; build validation rejected it and did not install `_site`.
- Failed build workspace was cleaned.

## Remaining limitations

- No live GitHub Pages deployment or browser test was performed.
- The user's actual Keycloak `_site-smoke` output was not rebuilt in this step.
- This is not a full configuration-effectiveness acceptance and does not close R8-009, R8-011, R8-017, R8-019, R8-021, R8-022, or R8-027.
- No commit, push, publish, deployment, or change to the user's Codespace was performed.
