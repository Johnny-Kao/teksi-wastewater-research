# TEKSI Wastewater — SWMM selection: EPA solver validation (2026-11-22)

Stage: Independent Research. No upstream issue or PR; no production deployment.

## Pinned source and evidence

- Upstream pinned: `553ce1bdaf0f21329d5c706c76daac3ced229095`
- Original `TwwSwmm.get_swmm_table`, `swmm_table`, `write_input` compiled unchanged from `plugin/teksi_wastewater/processing_provider/TwwSwmm.py`.
- Research script: [test_swmm_engine_scope.py](test_swmm_engine_scope.py)
- GitHub Actions **PASS 5/5**: https://github.com/Johnny-Kao/teksi-wastewater-research/actions/runs/45068017778
- PostgreSQL 16, minimal synthetic tables with columns aligned with actual TEKSI SWMM SQL views, `psycopg`, EPA SWMM 5.2.4 / `swmm-toolkit==0.17.0`.
- Inputs represent two independent legal small SWMM networks: N1 -> R1 -> O1, and N2 -> R2 -> O2; minimal hydraulic input includes JUNCTIONS, OUTFALLS, CONDUITS, XSECTIONS and COORDINATES.
- **Not** full QGIS GUI integration, a complete official TEKSI/PostGIS datamodel, or real municipality dataset.

## Confirmed observable outcomes

| Invocation `write_input(hierarchy, structures, reaches)` | Scope outcome | EPA SWMM outcome |
| --- | --- | --- |
| `('primary', None, None)` | Entire network | Success |
| `(None, ['N1','O1'], ['R1'])` | Selected first network | Success |
| `(None, ['N1','O1'], [])` | All conduits incl R2 but selected outfall O1 only; O2 omitted | **Error 209 undefined object O2**, model simulation aborts |
| `(None, [], ['R1'])` | R1 only, but both networks' unrelated Junctions/Outfalls exported | Success with excess nodes |
| `(None, [], [])` | Entire network (selection empty) | Success, but explicitly selected-only scope silently lost |

The first failure is caused by `get_swmm_table` interpreting `[]` as no predicate, so empty reach selection exports all conduits while the nonempty structure selection limits outfalls. In addition, `selected_ws_re` is only constructed when *both* lists are truthy, over-broadening junctions and coordinates.

## Intent and de-duplication

Official TEKSI SWMM docs `docs/en/tww_swmm/Create-Input.rst`: *Export only selected network* exports **selected** primary and secondary network; normal workflow usually selects upstream path (typically structures AND reaches). This mixed/empty selection behavior contradicts the option description, but may be uncommon with the recommended upstream-selection workflow.

Prior merged PR https://github.com/teksi/wastewater/pull/983 (2026-06-15) changed layer selection and primary classification; no patch to this `write_input` selected-list behavior in pinned upstream. Prior reported #797 / #803 are different SWMM issues. Search still not exhaustive for every historical duplicate.

## Risk and Priority

- **Confirmed:** valid export scope can be silently broadened and in one case EPA SWMM simulation fails on input references. Production code path reachable when optional `ONLY_SELECTED=True` and selections absent from one/both relevant layers; normal GUI function passes lists/None directly into unchanged `write_input`.
- **Not demonstrated:** silent incorrect flow values with realistic complete selection, or physical database corruption; no field incident frequency. End-to-end QGIS and official full model not run.
- Severity: **Moderate** for simulation availability/correctness of selected-only workflow, potentially higher scope/performance with huge networks; NOT demonstrated as critical CoreFoundry infrastructure defect.
- SmartPR potential: bounded regression for `None` (all) vs `[]` (none) plus referential closure of selected reach endpoints; a naive one-line fix of `selected_ws_re` alone is insufficient.
- CoreFoundry fit: **low-to-moderate**, since this is predominantly a QGIS-to-SWMM export scoping contract, not new graph/hydraulics algorithms.

## Next gate / decision

If contributor requires severe, frequent *normal operational* errors, **PARK** this as lower-tier unless official full-model import/reproduction or credible real-user report establishes greater incidence. No upstream writes. If contributor chooses SmartPR, build a minimal TEST/FIX staging only after verifying the intended selected-reach endpoint closure and an official full-model test.
