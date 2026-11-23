# TEKSI Wastewater: QGIS saved-field metadata research (2026-11-23)

**Status:** Research only; no upstream issue or PR. Source: `teksi/wastewater:main` at GitHub Actions checkout time. No upstream source changes.

## Question and initial false-positive control

Prior heuristic marked 520 QGIS settings without a matching `fieldConfiguration`; this is **not a count of bugs**. A revised per-layer unique-name count found 559 unmatched settings, including 2 old-name layer pairs already handled by #1253. Numbers differ because the heuristic and de-duplication rule changed; avoid combining them.

- [Structural QGIS triage](https://github.com/Johnny-Kao/teksi-wastewater-research/actions/runs/45244694297): 221 map layers; 557 non-#1253 unmatched layer/field entries across 40 layers, 295 distinct names.
- [Full PostgreSQL pg_catalog test](https://github.com/Johnny-Kao/teksi-wastewater-research/actions/runs/45246485569): install fresh official TEKSI database using PUM, inspect normal and materialized views (212 relations, 4,276 columns). Among 559 unmatched QGIS layer/field entries, **556 refer to absent database fields**; 3 are actually present despite being absent from QGIS form definitions. This does **not** imply 556 runtime bugs.
- Nontrivial QGIS XML uses of missing fields: **42 occurrences across 32 layer/field pairs**. Includes form references, expression options, label text, and relation metadata. Many are false-positive string matches or configuration-only usages, not executable paths.
- [Native QGIS + official PostgreSQL test](https://github.com/Johnny-Kao/teksi-wastewater-research/actions/runs/45246736307): 221 / 221 layers load valid, 57 / 57 relations valid. Complete native display-expression audit identified exactly **3 invalid expressions**; active edit-form audit identified **5 invalid field widgets** (index -1).

## Highest-confidence findings: 3 invalid display expressions

1. `vw_tww_ws_maintenance` references `"ws__bottom_label"`, absent from actual 32 QGIS/DB fields; `QgsExpression.prepare` fails. Candidate existing identifiers: `ws_identifier` and `me_identifier`. Meaning of desired label needs verification.
2. `vw_tww_additional_ws` references `"_label"`, absent from its 69 actual fields; `QgsExpression.prepare` fails. Existing `identifier` is plausible; view SQL explicitly selects `ws.identifier AS identifier` and exposes `_bottom_label`, `_cover_label` but not `_label`.
3. `re_maintenance_event_wastewater_structure` references `"obj_id"`, absent from actual fields `id`, `fk_maintenance_event`, `fk_wastewater_structure`; expression prepare fails. `id` exists, but desirable user-facing label needs functional inspection.

The defects are reproducible native QGIS expression-schema errors. **Not yet demonstrated:** erroneous output on actual populated user data or the value of alternative display labels. Do not claim production data loss.

## Five invalid active form field widgets

- `measuring_point`: `fk_reference_station` (index -1). A similarly named association field exists in the *separate* measuring-point/reference-station mapping model, so do not blindly add it to `measuring_point`.
- `mvw_tww_channel`: `_from_node`, `_to_node` (index -1); current view exposes `_from_ne`, `_to_ne`, but exact UI semantics must be checked.
- `vw_tww_channel_maintenance`: `_from_node`, `_to_node` (index -1); current view exposes `_from_ne`, `_to_ne`.

These are current active form config references, not merely inactive styles. QGIS may silently skip absent fields; verify visible effect with actual features before a contribution.

## Smart-PR evaluation

- **A: Display-label consistency** is the best candidate: only 3 native QGIS errors among 221 layers, all reproducible against official DB. Next gate: populate realistic feature fixtures or stable actual data, prove display failures and verify correct intended substitute labels. If effect is user-visible and no intentional hidden convention exists, propose a small isolated PR.
- **B: Invalid form references** deserves a separate follow-up. Prove which widgets are rendered or silently omitted and whether that affects a real workflow, before proposing rename/deletion.
- **C: Remaining DB-absent legacy settings** are not Smart-PR candidates as a bulk change. Cleanup only as part of demonstrated functional fixes; 556 is not evidence of 556 defects.
- Keep entirely separate from [already-reviewed SWMM PR #1253](https://github.com/teksi/wastewater/pull/1253); do not reopen its scope.

## Evidence and reproducibility

Research branch: `Johnny-Kao/teksi-wastewater-research:research/qgis-metadata-520-triage-20261123`.

Scripts: `scripts/triage_qgis_metadata_520.py`, `scripts/check_qgis_vs_postgres.py`, `scripts/qgis_native_integrity_probe.py`. The GitHub Actions artifacts contain the per-field inventory, PostgreSQL comparisons and QGIS native results. Avoid treating the first `information_schema` scan as complete; materialized views require `pg_catalog`.

**Next step:** targeted user-visible reproduction on the three display expressions, then choose at most one scoped patch based on actual UI behavior. No upstream actions authorized by this research alone.
