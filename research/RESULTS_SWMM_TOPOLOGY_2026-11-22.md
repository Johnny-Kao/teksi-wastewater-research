# SWMM selection and NetworkX graph — GC baseline (2026-11-22)

Upstream pinned commit: `553ce1bdaf0f21329d5c706c76daac3ced229095`.
Successful GitHub Actions: https://github.com/Johnny-Kao/teksi-wastewater-research/actions/runs/45066913142
Tests: 8/8 PASS (SWMM 5, topology 3).

## Method
- SWMM: compile original upstream `TwwSwmm.get_swmm_table`, `swmm_table`, `write_input` using AST without modification; use actual psycopg 3 client and PostgreSQL 16, isolated fixture tables exposed as `tww_app.swmm_vw_*`, run queries and write real `.inp` sections. No QGIS app, full TEKSI PostGIS model, or SWMM engine used.
- Topology: compile original upstream `TwwGraphManager.createGraph`, `_addEdges`, `shortestPath` with actual NetworkX 3.4.2 and fake minimal QGIS feature providers. No real QGIS or database network refresh performed.
- Baseline tests assert *observed unwanted behavior*. Passing CI means behavior was reproduced, NOT that upstream behavior is correct.

## SWMM findings
1. Reach-only selection `selected_structures=[]`, `selected_reaches=['R_SELECTED']` causes `selected_ws_re=None`; real SQL without selected ID predicate returns unselected JUNCTIONS/COORDINATES while CONDUITS are restricted.
2. Structure-only selection `selected_structures=['N_SELECTED']`, `selected_reaches=[]` causes `selected_ws_re=None`; unselected JUNCTIONS/COORDINATES and unselected CONDUITS persist. Only-selected input may be unexpectedly broadened.
3. Both lists populated yields filtered junctions and conduits for minimal fixture.
4. Original `swmm_table('TAGS', state, selected_ws_re)` passes `state` into `hierarchy`, list into `state`, no ID filtering; matching TAG omitted.
5. LOSSES written twice by `write_input` (duplicated section). Parser/model impact not proven.
Nuance: some extra nodes can be intentionally required to make a selected network self-contained; exact intended closure contract must be checked against official TEKSI docs and valid SWMM references. Not yet end-to-end SWMM hydraulic impact.

## Topology findings
1. Same ordered endpoints (A,B), two distinct features: `DiGraph.add_edge` overwrites `baseFeature` and `weight`; real upstream graph method reproduces.
2. Separate reach-point nodes (A-B-D versus A-C-D): both paths preserved; shortest route correct, matching `network_functions.sql` which creates reach-point vertices.
3. Fork retains both branches.
Production path for duplicate ordered **reach-point** node pairs not identified. PARK parallel edge hypothesis until grounded legitimate source data demonstrates it.

## Gate decision
SWMM selected-only export = research candidate with observed wrong scope in synthetic SQL views, still needs one official TEKSI fixture and SWMM parser or end-to-end check to establish severity. No upstream PR/issue yet.
Topology parallel edge = PARK without legal production reachability.
TAGS and LOSSES = secondary lower-priority candidates, not standalone high-impact PRs.
Prior A-01/A-02 remain PARKED.
