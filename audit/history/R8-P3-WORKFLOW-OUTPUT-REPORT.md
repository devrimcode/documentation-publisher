# R8 incremental correction P3 — workflow deploy decision output propagation

## Decision

**P3 is implemented and differentially regression-tested in this candidate.** This closes only the missing build-job output propagation defect. It does not authorize a GitHub Actions run, deployment, or release.

## Immutable starting point

- Starting package: `documentation-publisher-v2-r8-corrected-2.0.10-dev-P2-full-project.zip`
- P2 ZIP SHA-256: `7fa07da23ffb001d87db232525bc5046848104e91d62ce88627c5953c449f467`
- P2 archive checksums were verified using the P2 deliverables checksum file before extraction.
- P3 was applied only in an isolated working copy under `/mnt/data`.
- No change was made to the user's Codespace, branch, remotes, or Keycloak repository.

## Defect reproduced on P2

The generated workflow included a build step with `id: decision` that wrote `deploy=true|false` to `$GITHUB_OUTPUT`. The deploy job then read `needs.build.outputs.deploy`, but the build job did not declare `jobs.build.outputs.deploy`.

The same four-test P3 regression module was executed against a fresh P2 extraction:

- 3 tests failed (the build output mapping was missing; the downstream contract was therefore unresolved; one assertion raised `KeyError` because `build.outputs` did not exist).
- 1 dry-run control test passed, confirming dry-run remained build-only.

## Correction

Files changed by P3:

- `publisher_engine/workflow.py`
- `tests/test_p3_workflow_deploy_output.py` (new)

For non-dry-run workflows the generator now adds:

```yaml
jobs:
  build:
    outputs:
      deploy: ${{ steps.decision.outputs.deploy }}
```

The downstream deploy job continues to use:

```yaml
needs: build
if: needs.build.outputs.deploy == 'true'
```

Dry-run workflows intentionally receive no deploy output, decision step, artifact upload step, or deploy job.

## Differential acceptance

The identical four-test module was run against the immutable P2 baseline and the P3 candidate:

| Run | Result |
|---|---:|
| P2 baseline | 3 failures, 1 control passed |
| P3 candidate | 4/4 passed |

The tests parse the generated YAML with duplicate-key rejection and assert:

1. build job exports the decision step output;
2. deploy job consumes the declared build output;
3. dry-run has no decision output or deploy job;
4. the exported output references the unique decision step that writes both `true` and `false` values.

## Verification on the final P3 archive

- Full cumulative suite: **168 tests passed, 0 failed** (164 P2 tests plus 4 P3 tests).
- Targeted P3 module: **4 tests passed, 0 failed**.
- `python -m py_compile publisher_engine/*.py tests/*.py`: passed.
- CLI version: `2.0.10-dev`.
- `python -m publisher_engine.cli validate-config --config publisher.keycloak.smoke.yml`: passed (1 source, 1 component, 1 task).
- Generated YAML was parsed and the output contract asserted: `jobs.build.outputs.deploy == steps.decision.outputs.deploy` and `jobs.deploy.if == needs.build.outputs.deploy == 'true'`.
- The GitHub Actions job-output mapping follows GitHub's documented `jobs.<job_id>.outputs` and `needs.<job_id>.outputs` contract: https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/pass-job-outputs

## Limits

- No live GitHub Actions workflow run was performed.
- No Pages artifact was uploaded and no deployment was executed.
- Other previously identified workflow defects (environment propagation and pull-request path filters) remain separate work items (P4 and P5).
- R8-017, R8-019, R8-021, R8-022, R8-009, R8-011, and R8-027 remain open or partially accepted as already recorded in `R8-CORRECTION-STATUS.md`.
- No commit, push, publish, deployment, or user Codespace modification occurred.
