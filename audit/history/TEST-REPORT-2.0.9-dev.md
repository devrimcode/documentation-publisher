> **Historischer Testbericht:** Dieser Bericht dokumentiert 2.0.9-dev und ist kein aktueller Nachweis für den P12/R8-028-Kandidaten.

# Test report – Documentation Publisher 2.0.9-dev

## Result

- Unit tests: **134 passed, 0 failed**
- Python bytecode compilation: passed
- Keycloak example config validation: passed (1 source, 1 component, 1 task)

## Commands

```bash
python -m unittest discover -s tests -v
python -m py_compile publisher_engine/*.py tests/*.py
python -m publisher_engine.cli validate-config --config publisher.keycloak.example.yml
```

## Scope limits

This report covers the local unit/regression suite and semantic validation of the example Keycloak configuration. It does not claim a full Keycloak Maven build, live Git LFS acceptance, a GitHub Actions run, browser/editor acceptance, staging deployment, or production publishing. See `R8-CORRECTION-STATUS.md` for open audit findings and release gates.
