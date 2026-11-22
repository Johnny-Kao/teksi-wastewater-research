# TEKSI Wastewater — SWMM hydraulic-load results import: source, history, GC, maintainer fit
Date: 2026-11-22
Stage: **confirmed two independent defects**, research only, no upstream issue/PR, no staged fix.

## Findings and exact upstream path

- `plugin/teksi_wastewater/processing_provider/swmm_import_results.py`: `POPULATE_HYDRAULIC_LOAD` is an explicit boolean **default False**. When enabled, `TwwSwmm.import_hydraulic_load()` is invoked.
- `TwwSwmm.py` calls `extract_link_flow_summary` → `convert_max_over_full_flow` → `populate_attribute(...,'reach','dss2020_hydraulic_load_current','max_over_full_flow')`.
- **Defect A (blocking):** original SQL target `dss2020_hydraulic_load_current` is absent from official PUM-installed `tww_od.reach`. Correct schema column is `hydraulic_load_current smallint`. Independent original UPDATE fails with SQL `ERROR: column ... does not exist`; same UPDATE using correct column succeeds. `populate_attribute` catches `psycopg.ProgrammingError` and reports an error, returns; GUI process can still report progress 100. This is not proof of silent database corruption in current code; it currently fails to persist. Verify exact GUI error visibility separately if pursuing.
- **Defect B (latent once A is fixed):** `int(round(float(value))) * 100` rounds the fraction **before** converting to percent: original function returns 0 for fractions under 0.5, 100 for fractions between 0.5 and 1.5, and 100 for 1.25 (actual 125%). Correct nominal integer percentage is `round(float(value) * 100)`. Existing DB is `smallint`, adequate for these examples. Requires full numeric/format handling follow-up test before patch.
- EPA SWMM 5.2 manual explicitly documents Link Flow Summary Max/Full Flow as the **ratio** of maximum flow to full normal flow, not already a percent: https://www.epa.gov/system/files/documents/2022-04/swmm-users-manual-version-5.2.pdf

## Original source / GC verification

1. Real source converter and AST call-chain: https://github.com/Johnny-Kao/teksi-wastewater-research/actions/runs/45071614496 (2 PASS).
2. Official PostGIS/PUM schema, direct SQL expected-fail vs success: https://github.com/Johnny-Kao/teksi-wastewater-research/actions/runs/45071961965 (PASS); legacy_column_exists=false, new_column_exists=true, original SQL rc=1 and renamed SQL rc=0.
3. Genuine SWMM 5.2.4 engine report, original upstream `extract_summary_lines`, `extract_link_flow_summary`, `convert_max_over_full_flow`: https://github.com/Johnny-Kao/teksi-wastewater-research/actions/runs/45072166933 (PASS). R1 actual Link Flow Summary Max/Full Flow `0.02` from engine; original importer returns 0%; intended 2%. Real parser/engine data, not injected ratio.
4. No end-to-end actual populated real official TEKSI reach row update using QGIS GUI yet; SQL column contract is separately proven on full installed DB.

## Earliest evidence and introduction

- PR #25, merged **2023-12-01**: specifically removes custom `dss2020_hydraulic_load_current` SQL column and explicitly says *use tww_od.reach.hydraulic_load_current instead*. https://github.com/teksi/wastewater/pull/25
- PR #23, merged **2024-01-25**, imports plugin from legacy `teksi/wastewater_old`. The exact old field name AND `int(round(float(...))) * 100` are already present in the earliest plugin commit `7f5a079ba8d9`. https://github.com/teksi/wastewater/pull/23
- Therefore the two-contract mismatch has been present in the integrated project since at least 2024-01-25. The rounding expression predates or coincides with the import; precise first-ever upstream creation date cannot be established from this repo because code was copied from legacy.
- Subsequent edit commits to TwwSwmm.py in 2025/2026 retained both defects.
- Hypothesis (not verified developer intent): plugin migration skipped old-to-new schema cross-check and percentages were incorrectly rounded pre-scaling. No evidence of intentional behavior or specific negligence.

## Duplicate / maintainer acceptance

- GitHub issue/PR search found no exact existing issue/PR for the percentage conversion or hydraulic writeback field; search is not absolute proof of absence.
- Strong evidence this area is maintained: #25 knowingly renamed column (cymed, merged), #983 SWMM input creation fix (cymed, merged 2026-06-15), #1158 imported data preservation fix (cymed, merged 2026-11-20), #1223 correct downstream Z (cymed, merged 2026-11-04).
- Acceptance probability: **medium-to-high if backed by the three independent GC proofs and a minimal two-line fix/test**, but **not guaranteed**: the option defaults off, no field reports or feature-use counts. Current release freeze may influence timing. No maintainer commitment.
- Priority distinction: Defect A = broken optional results-import feature (no data saved). Defect B = potentially silent wrong hydraulic percentage **after A is fixed**; don't claim current version is silently persisting wrong values.
- Suggested minimal regression cases: 0.02 => 2, 0.40 => 40, 0.80 => 80, 1.25 => 125, correct `hydraulic_load_current` column, return/error propagation, transaction rollback on failures; verify real report parser and official Postgres.
- **Recommendation:** strong SmartPR candidate for a focused paired correctness fix; CoreFoundry critical-infrastructure scope relevance moderate because optional feature, not automatic asset corruption. Keep staged research separate, no upstream submission until user authorizes.
