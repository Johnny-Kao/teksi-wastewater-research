# TEKSI QGIS field/form repair — eight-site research candidate

Date: 2026-11-23. Research only, not a public PR. Branch: `research/qgis-form-display-repair-20261123`.

## Finding and scope

Existing upstream `project/teksi_wastewater.qgs` loads 221 valid layers and 57 valid relations, but native QGIS detects **3 invalid display expressions** and **5 active attribute-editor form references with indices -1** against a clean TEKSI PUM-installed PostgreSQL database. The candidate fixes only those eight references, within one QGIS project XML file.

Generated patch: `scripts/prepare_qgis_8_fix.py` transforms the original read-only upstream project into a separate candidate project, preserving the original.

### Proposed fixes
- `vw_tww_ws_maintenance`: display `ws__bottom_label` (missing) → `ws_identifier` (exists).
- `vw_tww_additional_ws`: display `_label` (missing) → `identifier` (exists).
- `re_maintenance_event_wastewater_structure`: display `COALESCE("obj_id", '<NULL>')` (missing) → `COALESCE("id", '<NULL>')` (existing row identity; keeps original fallback). An earlier candidate used `fk_wastewater_structure` as primary label, but this would conflate distinct events attached to the same structure; rejected in review.
- `mvw_tww_channel`: two form references `_from_node`/`_to_node` missing → actual `_from_ne`/`_to_ne` fields; QGIS indices 42 and 45.
- `vw_tww_channel_maintenance`: same two replacements; indices 20 and 26.
- `measuring_point`: remove invalid field widget `fk_reference_station`. A similarly named association field exists in an independent mapping relation, so **do not add a column to measuring_point**. Confirm removal does not obscure intended relation UX.

## Controlled native Red/Green result

[Final reviewed GitHub Actions A/B #45251209853](https://github.com/Johnny-Kao/teksi-wastewater-research/actions/runs/45251209853) (SUCCESS, head 7287313): same docker QGIS stable-noble + official PUM DB; identical scripts applied to baseline and revised candidate. [Initial A/B #45249526400](https://github.com/Johnny-Kao/teksi-wastewater-research/actions/runs/45249526400) was also green, but its maintenance-event substitute was semantically weaker and has since been corrected.

| Check | Baseline | Research candidate |
|---|---:|---:|
| Project opened; valid layers | 221/221 | 221/221 |
| Valid QGIS relations | 57/57 | 57/57 |
| Invalid display expressions | **3** | **0** |
| Invalid active form field widgets | **5** | **0** |

CI SUCCESS. Artifact `qgis-eight-site-red-green` includes baseline and candidate native QGIS logs and a targeted unified XML patch.

## Limits and next decision

This is strong **native QGIS project/schema correctness** evidence, not yet a full user-visible form interaction test on representative populated records, and not proof of production data loss. Three display-label semantics and the measuring-point reference-station field UX require human review before claiming functional equivalence; four node-field replacements have actual matching schema and form indices.

One self-contained future PR is technically feasible, with **one project file changed** and a reproducible native integration test. Keep it wholly separate from SWMM PR #1253 and do not include the broader 556 metadata mismatches.

No upstream repo writes, issue or PR created.
