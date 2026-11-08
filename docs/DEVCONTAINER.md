# GitHub Codespaces / Dev Container

The repository carries an **active** configuration at `.devcontainer/devcontainer.json`.
Codespaces discovers this exact path when a new Codespace is created from a branch
that contains the file. The configuration builds `.devcontainer/Dockerfile` with the
repository root as its explicit Docker build context.

## Provisioned toolchain

- Python 3.13 from the Microsoft Dev Container Bookworm OCI image, pinned by its full
  image-index SHA-256 digest; build platform fixed to `linux/amd64`.
- Debian Bookworm, Bookworm updates and Bookworm security metadata are read from the
  signed snapshot. This is an APT-source reproducibility check; the build does **not**
  attempt to install a separate package named `git-subtree` (Debian Bookworm has no such
  package).
- The digest-pinned base image already contains Debian's `git` package, which supplies
  `/usr/lib/git-core/git-subtree`. The image build confirms the helper's dpkg owner is
  `git`, records that package's exact version and the helper SHA-256, then links the
  existing helper into the path reported by `git --exec-path`.
- Lock v3 records the Debian snapshot/source hash, architecture, APT and dpkg versions,
  exact base-image digest, build platform, Git version, helper owner/version/hash and
  active helper link. The runtime verifier checks those values and runs `git subtree -h`
  on every start.
- The original mutable Debian APT source entries from the base image are removed before
  the snapshot metadata update. No live `deb.debian.org` source can participate.
- Git LFS 3.8.1 through pinned Feature 1.2.5, with automatic pull disabled.
- Eclipse Temurin JDK 25 as default and JDK 21 additionally installed through pinned
  Java Feature 1.8.3; Maven 3.10.0 through the Java Feature.
- `.venv` created by `ensure-python-environment.sh`; project `.[dev]` or requirements-file dependencies are installed when present. A SHA-256 fingerprint makes later dependency-file additions or changes detectable on every container start and every new interactive Bash terminal.
- New interactive Bash terminals run the idempotent bootstrap and then activate the nearest repository `.venv`. This is separate from the VS Code Python interpreter preference, so an existing terminal cannot silently keep using the system interpreter after a new terminal is opened.

## APT snapshot update policy

The current Debian snapshot is deliberately fixed at `20261107T000000Z`. Do not replace
it with `bookworm`, `bookworm-updates` or `bookworm-security` live mirror URLs. To advance
the environment, review a new Debian snapshot, update `ARG DEBIAN_SNAPSHOT` in the
Dockerfile, rebuild the image, inspect the generated `toolchain-lock.tsv`, and run the
full regression suite. The lock records the exact base-image `git` package version that owns the
`git-subtree` helper, the helper's hash and its active Git exec-path link. The pinned
base-image digest, fixed build platform and archived APT metadata fix the environment
inputs. The generated lock records
the architecture and package-manager toolchain so a second clean build can be compared
as a concrete acceptance test.

A frozen snapshot does not receive later security fixes automatically. Advancing the
snapshot is therefore a deliberate maintenance/security update, not something to
leave indefinitely. Update the base image digest and Debian snapshot together after
reviewing the resulting toolchain.

## Before creating the first Codespace

Copy the complete `.devcontainer/` directory to the root of the fresh GitHub repository
and save it on the branch from which the Codespace will be created. Keep the `.devcontainer`
folder intact: the Dockerfile `COPY` instructions require the repository-root build context.

During the image build, the pinned APT snapshot metadata is validated and the existing
Debian `git` package's `git-subtree` helper is linked into Git's active exec path; no
nonexistent `git-subtree` package is installed. The Java and Git LFS Features install
their tools. `post-create.sh` calls the shared Python bootstrap, verifies the image's toolchain lock, and copies
the generated base-image / Git Subtree toolchain lock to `test-results/devcontainer-toolchain-lock.tsv` with a
sidecar SHA-256 file. `postStartCommand` runs the same dependency bootstrap before it rechecks the APT source hash/Git Subtree helper provenance and the declared Python/Java/Maven/Git-LFS versions.

A brand-new repository containing only `.devcontainer/` can still complete container setup. If Publisher source files arrive later, the bootstrap notices them on the next container start **and on the next new interactive Bash terminal**. It installs the newly declared dependency set before activating `.venv`; no manual one-off `pip install` is part of the setup contract. Existing terminals are not retroactively reconfigured, so open a new Bash terminal after source files are added.

## Verification

Immediately after first start:

```bash
bash .devcontainer/verify-apt-state.sh
bash .devcontainer/verify-environment.sh
```

After the Publisher files are present:

```bash
bash scripts/test-in-codespaces.sh
```

The script runs environment/CLI checks first, then executes four independent regression
groups: core, manifest/cleanup, wheel installation, and process/timeout. Each group
writes a separate log under `test-results/`.

An actual Docker/Codespaces image build and comparison of the generated APT/helper
lock from two fresh builds are still required to close F05/F16. The failed Workblock 06
build is retained as historical evidence: it reached the signed Debian snapshot but
failed because it requested the nonexistent `git-subtree` package. Workblock 07 restored
the correct helper-discovery/linking design; Workblock 09 adds the complete Python
`.venv` lifecycle and automatic terminal activation. The current Docker image has not
yet been rebuilt in the user's Codespace; only that external run can accept it.
