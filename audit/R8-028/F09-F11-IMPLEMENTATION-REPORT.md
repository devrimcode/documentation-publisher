# R8-028 Workblock 02 — F09/F10/F11

## F09 — provider fields are labels, not adapters

- Authoring target `provider` is no longer required by schema and is marked deprecated. `provider_label` is the preferred optional non-empty metadata property.
- Communication channels have the same `provider_label` preference; legacy `provider` remains a deprecated metadata alias.
- Configuring both aliases on one object is rejected.
- Neither field dispatches provider-specific behavior. Authoring URLs continue to be rendered from `edit_url_template`; communication URLs use the shared channel formatter. Actual behavior must not be inferred from a label.
- Generic and Keycloak smoke examples now use `provider_label`.

## F10 — private destination is an operator assertion

- `private_target_attested: true` is the preferred security-channel attestation.
- Legacy `private_target: true` remains accepted as a deprecated compatibility alias.
- Conflicting aliases are rejected; false or missing attestation is rejected for security-report overrides.
- Privacy attestation is only a configuration assertion. The engine does not inspect endpoint visibility, membership, ACLs, authentication, or provider permission settings. Real provider-side acceptance remains mandatory before production use.

## F11 — dynamic communication channels and query keys

- Global and component-level dynamic channel names must match `^[a-z][a-z0-9_-]{0,63}$` in JSON Schema and semantic validation.
- Dynamic query keys must match `^[a-z][a-z0-9_]{0,63}$` in JSON Schema and semantic validation.
- Query values are percent-encoded by the shared formatter before insertion as `{query_<key>}` values.
- `inherit` and `disable` cannot carry inactive override fields.
- Email override fields and generic URL-channel fields are checked against separate contracts; cross-channel fields are rejected rather than silently ignored.
- Global and component-level contract tests are present. This is not a claim that every channel has been browser-accepted or that external endpoints are reachable/private.

## Test IDs

- `test_authoring_provider_is_metadata_and_never_selects_adapter`
- `test_authoring_provider_label_schema_is_optional_and_alias_conflict_is_rejected`
- `test_communication_provider_label_does_not_change_generated_destination`
- `test_security_target_requires_explicit_operator_attestation_and_warns_semantically`
- `test_legacy_private_target_true_remains_accepted_only_as_attestation`
- `test_dynamic_communication_channel_and_query_key_contract_is_enforced`
- `test_dynamic_communication_channel_names_are_validated_at_runtime_and_schema`
- `test_channel_mode_rejects_ignored_and_cross_channel_override_fields`
- `test_component_level_dynamic_communication_uses_same_contract`

Additional tests ported from Workblock 01 cover exact environment-reference validation and installed IANA timezone values.

## Acceptance status

F09 is **partially closed**: label semantics and no-dispatch behavior are tested, but provider-specific adapters are still not implemented. F10 is **partially closed**: the operator-attestation contract is enforced, but actual endpoint privacy/ACL remains external. F11 is **locally implemented and tested for the documented dynamic contract**, but channel-by-channel browser behavior remains an external acceptance task.


## Matrix reconciliation (Group 2)

The unified matrix contains 239 unique option/contract nodes. The schema/dynamic-path coverage file contains 258 rows. The pairwise file contains all 28,441 unordered combinations (`239 × 238 / 2`). Across that file, 74 unique direct relationship IDs are attached to 75 pair rows: the earlier C01–C60 set plus 14 F09–F11 contracts. The remaining 28,366 pair rows are `N/A`; they have not been behaviorally verified and are not scored as compatible.

The direct relationship ledger is `F09-F11-CONTRACT-RELATIONSHIPS.csv`. Its statuses distinguish local output/validation evidence from external provider and endpoint acceptance.
