# TEKSI Wastewater — SWMM selection production-impact validation (2026-11-22)

Status: Research only. No upstream issue, PR, comment or staging modifications.

Pinned upstream: `553ce1bdaf0f21329d5c706c76daac3ced229095`.

## Full official TEKSI installed model / XTF

- GC PASS: https://github.com/Johnny-Kao/teksi-wastewater-research/actions/runs/45069430710 (official setup after downloading upstream ilivalidator JAR). Installed official PUM PostgreSQL 16/PostGIS data model and built official QGIS container; imported official Organization, SIA405 and DSS XTF sample files successfully.
- First integration run https://github.com/Johnny-Kao/teksi-wastewater-research/actions/runs/45069076998 was **not meaningful** because missing `ilivalidator-1.15.0.jar` caused importer to print errors while CLI exited 0. The data remained empty. The workflow was fixed to download the upstream dependency and assert at least one real `tww_od.reach`.
- Stronger official reference-validation GC PASS: https://github.com/Johnny-Kao/teksi-wastewater-research/actions/runs/45070196519. Original `TwwSwmm` exporter and actual installed `tww_app.swmm_vw_*` views generated .inp files. Official minimal XTF has one qualifying conduit, two junctions, **no outfall**, so not an independent valid SWMM hydraulic test.
- Whole exported INP: one conduit `ch000000WN000001 -> ch000000WN000002`, two nodes, zero missing endpoint references.
- Select conduit and only upstream junction: one conduit and one junction, **missing downstream node `ch000000WN000002`**; actual installed SQL view/export pipeline produces a dangling INP reference.
- Only structure selected (zero reaches selected), or zero features selected in selected-only mode: all available conduits exported (empty-list filtering conflated with no filter). Only-reach selection includes all junctions.
- Still not a full QGIS GUI selection action through interactive layer selection and no valid SWMM engine comparison for official XTF because fixture lacks an outfall.

## Actual EPA SWMM model and numeric outputs

- EPA SWMM 5.2.4 model-run control GC PASS 5/5: https://github.com/Johnny-Kao/teksi-wastewater-research/actions/runs/45068017778 with original upstream export methods, real PostgreSQL queries against **synthetic but SWMM-valid minimal-view fixtures**.
- Whole network and complete selected network simulate successfully. Selecting structures only (no selected reaches) exports extra conduit R2 without its unselected outfall O2, producing `ERROR 209: undefined object O2`. Selecting reaches only can simulate successfully but includes extra unrelated nodes. Selecting nothing silently exports whole network.
- Hydraulic time-series GC PASS 6/6 (including five inherited controls): https://github.com/Johnny-Kao/teksi-wastewater-research/actions/runs/45070378773. Added N1 DWF `0.02 m3/s` then read actual SWMM binary R1 FLOW_RATE via PySWMM. All 6 report steps are identical `0.01999999955 m3/s` for whole model, properly selected R1 network, and reach-only overbroad nodes. **No observed silent hydraulic flow error in this simple disconnected-network case**. More complex mixing/catchment dynamics not tested.

## Interpretation and decision gate

- Verified user-visible bug: selected-only export does not consistently respect selected structures/reaches and can create missing conduit endpoint nodes, which SWMM rejects. Official recommended path is usually "Upstream" + "Select current path" (both reaches and structures), which likely avoids this particular missing-selection mode. Production incidence unknown: source tests cannot measure field frequency.
- Not proven: normal recommended full-subnetwork selection gives wrong results; actual hydraulic flows silently wrong; permanent TEKSI data loss; municipal incidents.
- Severity moderate **conditional on incomplete selections**, not established critical. SmartPR possible (scoped selected-only semantics and referential closure), but CoreFoundry fit limited because export/selection correctness rather than infrastructure algorithm optimization.
- Under strict high-impact SmartPR/CoreFoundry gate: **PARK unless contributor chooses to pursue medium-priority UI/export correctness**. Do not submit upstream without authorization.
