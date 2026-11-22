# SWMM hydraulic-load minimal staged fix — 2026-11-22

Status: **STAGING GREEN, NOT UPSTREAM.**

Upstream pinned source: `553ce1bdaf0f21329d5c706c76daac3ced229095`.

## Scope
- Test file `research/test_swmm_hydraulic_load_writeback.py` committed first (`459dae93d066db805921f12ef201f5dc1e691dfe`).
- CI workflow `.github/workflows/swmm-hydraulic-load-writeback.yml` committed separately; checks out the pinned upstream source, then applies optional research patch without changing upstream repository.
- Baseline red: https://github.com/Johnny-Kao/teksi-wastewater-research/actions/runs/45072727533 — both regression cases failed correctly: old target column was missing; old calculation returned coarse 0/100 percentages.
- Minimal two-line patch `research/patches/swmm_hydraulic_load.patch`, latest formatting-adjusted commit `8555eb993e25e460057f29a564a2da72a1964e52`:
  - `int(round(float(ratio))) * 100` → `round(float(ratio) * 100)`
  - `dss2020_hydraulic_load_current` → `hydraulic_load_current`
- Fixed green: https://github.com/Johnny-Kao/teksi-wastewater-research/actions/runs/45073083508 — **7 tests PASS**, including true EPA SWMM 5.2.4 .rpt parsing, PostgreSQL 16 writeback to reach table with official PUM column contract, and percentage boundary tests. Actual simulation ratio `0.02` → expected `2` → actual database `2`.
- Separate official installed PostGIS/PUM schema contract: https://github.com/Johnny-Kao/teksi-wastewater-research/actions/runs/45071961965 (old column missing, new column present). Current writeback test creates minimal `tww_od.reach` table with same field contract; **not full official QGIS/PUM populated-record integration**.
- A separate transaction-boundary research workflow also passed, but is not counted as evidence that GUI error presentation or future rollback behavior is fixed.

## Notes
- This is a focused two-line fix with no changes to export, other attributes, or database migrations.
- Production option `POPULATE_HYDRAULIC_LOAD` defaults false. Current bug fails to persist with old column; without fixing rounding, changing only column would introduce silently wrong percentages.
- **No upstream issue/PR/comment or direct changes to `teksi/wastewater`**.
- Next optional gate: full installed official PUM + actual reach row writeback under original and patch; checks of all existing TEKSI plugin tests with QGIS if upstream PR requested.
