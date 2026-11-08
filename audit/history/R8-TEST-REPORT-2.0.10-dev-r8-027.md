> **Historischer Testbericht:** Dieser Bericht prüfte die frühere lokale Feature-Variante. Sie ist nicht mehr Bestandteil des aktuellen Kandidaten; maßgeblich für R8-027 ist `audit/R8-027-ACTIVE-DEVCONTAINER-TEST-REPORT.md`.

# R8 2.0.10-dev – R8-027 Dev Container correction test report

**Result: 142/142 tests passed** in the isolated correction-package environment.

## Added coverage

- `test_links_existing_system_helper_into_active_git_exec_path`: simulates Git using an exec path that does not contain `git-subtree`, while the helper is installed elsewhere on `PATH`; verifies that the Dev Container feature creates a targeted symlink into Git's active exec path.
- `test_is_idempotent_when_git_subtree_is_already_available`: verifies the feature leaves an already-working installation untouched.

## Additional checks

- JSON parsing for `devcontainer-feature.json` and `devcontainer.json.example`: passed.
- `python -m py_compile publisher_engine/*.py tests/*.py`: passed.
- Full suite: `python -m unittest discover -s tests -v` – 142 tests in 13.355 seconds, `OK`.

## Scope and remaining acceptance

This report covers the superseded local-Feature implementation. The current candidate instead uses `.devcontainer/Dockerfile` to install and link `git-subtree` into the active `git --exec-path`.

This report does **not** claim that the user's live Codespace has been rebuilt with the feature. R8-027 remains partial until the feature is referenced from the repository's existing `.devcontainer/devcontainer.json` and that container rebuild is accepted. No commit, push, deployment, or edit to the Keycloak repository was performed.
