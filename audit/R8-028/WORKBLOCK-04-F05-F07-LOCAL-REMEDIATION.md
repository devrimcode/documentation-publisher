# R8-028 Workblock 04 — local remediation for F05 and F07

**Parent:** `documentation-publisher-v2-r8-2.0.10-dev-P12-R8-028-RECONCILED-GROUP-3` only.

**Parent archive identity (verified before extraction):**

- ZIP SHA-256: `dc06b8b23c77f7999ac8a336565d99e95f3514149ea0ab629972c138eca43db3`
- TAR.GZ SHA-256: `cee4217a13faf5e2acddddcbac60e806f35fd49b71d6ab0a458f761a122d6c95`

Both exact parent archives were found in the Library, materialized without modification and checked against these hashes. Workblock 04 was created in a separate extracted working copy; the Library objects and the parent archive files were not overwritten.

## F05 — mutable Dev Container image and package resolution

The active Dev Container `FROM` line now pins the Microsoft Python 3.13 Bookworm OCI image index by digest while retaining the tag for readability:

`mcr.microsoft.com/devcontainers/python:3.13-bookworm@sha256:ac334d90ca71f23b58820c90a440b400d175b77d642d312cf67ff0cc9cb2056d`

The digest was read from the Microsoft Artifact Registry entry for the exact `3.13-bookworm` tag on 2026-11-07. The current pin stops that tag from silently resolving to a different image on the next rebuild. The Dockerfile comment establishes deliberate digest review/update as the update procedure.

The Java and Git LFS Dev Container Features remain version-pinned, and Maven remains pinned to 3.10.0 in the feature options.

**Not closed:** APT still resolves `git-subtree` and its dependencies against the then-current Debian package metadata. This workblock does not claim reproducible APT snapshots or exact package-version pinning. F05 remains partially mitigated until that separate supply-chain decision is implemented and the container is actually built.

## F07 — Python version compatibility

Added `.github/workflows/python-compatibility.yml`. It runs the core, manifest/cleanup, wheel-installation and process/timeout regression groups separately on Python 3.11, 3.12 and 3.13. Each matrix leg installs the project as an editable package with its declared development extra, runs `pip check` and compiles package, test and script sources before the test groups.

The workflow uses read-only `contents` permission and does not publish or deploy. The actions use the current major releases `actions/checkout@v7` and `actions/setup-python@v7` documented by the upstream action maintainers at implementation time.

A local structural test verifies the exact matrix, read-only permissions and presence of all four regression groups. The current local runtime is Python 3.13.5; Python 3.11 and 3.12 are not installed in this execution environment, so no local pass is claimed for those interpreters. The actual matrix remains pending a GitHub Actions run.

## Validation performed in this workblock

- Dockerfile digest-pin assertion added to the Dev Container tests.
- CI matrix structure test added.
- Regression results and the test-process isolation limitation are recorded in [`WORKBLOCK-04-TEST-SUMMARY.md`](WORKBLOCK-04-TEST-SUMMARY.md), with raw logs under `audit/evidence/R8-028-WORKBLOCK-04-*.txt`.

## Acceptance boundary

No Docker/Codespaces image build, GitHub-hosted Actions run, APT snapshot pin, production publish, push, PR or deployment was performed by this workblock.
