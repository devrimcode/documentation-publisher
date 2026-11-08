# Workblock 06 — F05 test report

**Project:** documentation-publisher `2.0.10-dev`
**Parent:** Workblock 05 F15 GitLab CI / GitLab Pages
**Acceptance classification:** local implementation/tests passed; real container build remains external.

## Targeted F05 checks

Command:

```bash
python -m pytest -q tests/test_devcontainer_apt.py tests/test_devcontainer_config.py tests/test_devcontainer_runtime.py
```

Result:

```text
26 passed, 8 subtests passed
```

Coverage includes snapshot stanza structure, fixed OCI image digest, fixed `linux/amd64` build target, live source removal, package-install simulation, `git-subtree` plan requirement, lock-v2 creation, architecture and APT/dpkg version metadata, package drift rejection, source-hash tampering, rejection of a live Debian mirror, and runtime toolchain verification.

## Four-group regression

The project's documented split was executed in four independent invocations:

| Group | Command | Result |
|---|---|---:|
| Main | `python -m pytest -q --ignore=tests/test_process.py --ignore=tests/test_packaging.py --ignore=tests/test_p6_p7_manifest_cleanup.py` | **256 passed, 1 skipped, 99 subtests** |
| Manifest / cleanup | `python -m pytest -q tests/test_p6_p7_manifest_cleanup.py` | **6 passed** |
| Wheel / packaging | `env -u PYTHONPATH -u PYTHONHOME -u PIP_CONFIG_FILE -u PIP_INDEX_URL -u PIP_EXTRA_INDEX_URL -u VIRTUAL_ENV python -m pytest -q tests/test_packaging.py` | **3 passed** |
| Process / timeout | `python -Werror::ResourceWarning -m pytest -q tests/test_process.py` | **6 passed** |

Combined result: **271 passed, 1 skipped, 0 failed; 99 subtests**. The one skip is the real Git LFS client/object-transfer test because the client is not installed in this environment.

## Additional static checks

- `bash -n .devcontainer/install-apt-snapshot.sh .devcontainer/verify-apt-state.sh .devcontainer/verify-environment.sh .devcontainer/post-create.sh` — passed.
- `apt-get indextargets` with the generated Deb822 Snapshot source file and isolated `Dir::Etc::sourcelist` / `Dir::Etc::sourceparts` overrides — exit 0; source syntax parsed. No repository download was performed by this command.
- `python -m compileall -q publisher_engine tests scripts` — passed.
- JSON parse of `.devcontainer/devcontainer.json`, `schemas/publisher.schema.json` and the packaged schema — passed.

## Environment limitations

- `docker`: unavailable.
- `podman`: unavailable.
- DNS lookup for `snapshot.debian.org`: unavailable; `curl` returned error 6, “Could not resolve host”.

Therefore no image build or real APT transaction was performed. In particular, the test fixtures use fake APT/dpkg commands; they prove lock-generation and drift-control behavior, not that the selected snapshot currently serves the package or what the actual Debian-resolved versions are. A fresh `linux/amd64` Codespaces/Docker build and second clean build comparison remain required before F05 can be marked closed.
