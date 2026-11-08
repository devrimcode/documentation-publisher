# Workblock 07 — Codespaces-first test plan

**Authoritative test environment:** the user's `devrimcode/documentation-publisher` Codespace. Do not count tests run elsewhere as project acceptance.

## A. Image and Git Subtree provisioning

1. Rebuild the Dev Container from a clean Codespace.
2. Confirm the snapshot indexes download and the image build reaches the end without any `apt-get install git-subtree` call.
3. Confirm the `toolchain-lock.tsv` exists.
4. Run:

   ```bash
   bash .devcontainer/verify-apt-state.sh
   git --version
   git --exec-path
   command -v git-subtree || true
   ls -l /usr/lib/git-core/git-subtree "$(git --exec-path)/git-subtree"
   readlink -f "$(git --exec-path)/git-subtree"
   dpkg-query -S /usr/lib/git-core/git-subtree
   dpkg-query -W -f='${binary:Package} ${Version}\n' git
   git subtree -h
   ```

5. Confirm `GIT_EXEC_PATH` is unset and `git subtree -h` still works.
6. Confirm `postCreateCommand` and `postStartCommand` both completed successfully.

## B. Targeted correction regression

```bash
python -m pytest -q tests/test_devcontainer_apt.py tests/test_devcontainer_config.py tests/test_devcontainer_runtime.py
```

Expected purpose: helper discovery/link, same-helper idempotence, wrong/missing owner rejection, no request for a `git-subtree` APT package, deterministic v3 lock, base-image/platform checks, package/helper hash/version drift, mutable-source rejection and the full runtime verifier.

## C. Full Publisher regression

Run the repository's official four isolated groups (do not collapse them into a single pytest process in this Codespaces session):

```bash
bash scripts/test-in-codespaces.sh
```

Retain the complete console output and every log under `test-results/`. A skipped Git-LFS integration test is not a pass; resolve the skip with an actual Git LFS object transfer.

## D. Repeat-build reproducibility

1. Preserve the first build's `test-results/devcontainer-toolchain-lock.tsv` and SHA-256.
2. Create a second clean Codespace from the same commit, or rebuild from a clean base with no cached project image layers.
3. Compare both lock files using `cmp` and `sha256sum -c`.
4. Any difference must be explained by a proven mutable input; otherwise F05 remains open.

## E. Broader R8-028 programme (still required after the image works)

Continue all 20 findings F01–F20. Use the reconciled Group 3 matrices as the current coverage baseline: 250 option/contract nodes, 258 schema/dynamic-path rows, 31,125 unordered pairs, 87 explicitly scored direct relationships and 31,038 `N/A` pairs that remain unverified. The earlier full code/config audit is retained as the pre-Group-3 baseline and must not replace the reconciled Group 3 matrix. Exercise the schema paths and all enumerated options, then add behavior tests for every relevant direct relationship and higher-order interaction; `N/A` is never an assumed pass. Cover CLI, package, config, source retrieval, subtree integration, build, HTML/CSS/link validation, security, local/GitHub/GitLab publishing, real Git LFS transfer, Windows process-tree behavior, Project Pages browser acceptance and Keycloak editor/browser checks. Do not label a provider or platform externally accepted without an actual run there.
