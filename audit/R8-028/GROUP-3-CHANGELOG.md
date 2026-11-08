# Group 3 cumulative change log — F12/F14/F15/F19

The sole parent is the reconciled P12 Group 2 project. No older project archive or parallel Workblock 01 code was merged.

1. **F12 — init-config:** added a safe first-run command using the packaged generic fail-closed template; custom template is optional; overwrite, symlink, missing parent and `.git` destinations are rejected.
2. **F14 — installable package:** added `pyproject.toml`, package data, runtime resources, the `documentation-publisher` console entry point, and wheel build/install tests.
3. **F15 — provider contract:** added a versioned provider capability registry and CLI output. Supported adapters are compared against schema identifiers; unsupported provider families are explicitly disclosed, not implied to work.
4. **F19 — profiles:** added repeated ordered `--profile` to publish and generate-workflow; profile selection is passed through the engine and reproduced in generated CI validate/build commands.
5. **Codespaces packaging:** post-create now installs the Publisher editable package plus dev extras when `pyproject.toml` is present. `TEST-IN-CODESPACES.md` now describes the full source-root requirement and current Python/JDK/Maven/Git-LFS contract.
6. **Portable packaging test:** the wheel test uses a temporary virtual environment, the platform-specific Scripts/bin directory and the actual installed console entry point; it verifies package metadata and resources.
7. **Audit:** F01–F20 status, the option/pair matrices and direct relationship ledger are updated. Current status lives only in `STATUS.md`; older status files remain under `audit/history/`.

No GitHub repository, Codespace, Keycloak upstream, remote branch or deployment was modified. No commit, push, PR or release upload was performed.
