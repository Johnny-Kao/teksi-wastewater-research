"""Official TEKSI installed PostGIS model + official XTF: SWMM export scope probe.

Executed inside upstream's QGIS Docker container. All imported source data are
from pinned upstream fixture files; no modifications to upstream source.
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, "/usr/src/plugin")

from teksi_wastewater.utils.database_utils import DatabaseUtils
from teksi_wastewater.processing_provider.TwwSwmm import TwwSwmm

dbc = DatabaseUtils.databaseConfig
dbc.PGSERVICE="pg_tww"
dbc.PGHOST=None
dbc.PGPORT=None
dbc.PGDATABASE=None
dbc.PGUSER=None
dbc.PGPASS=None

OUTPUT=Path("/usr/src/plugin/research_swmm_official_output")
OUTPUT.mkdir(exist_ok=True)

def ids_for(view):
    with TwwSwmm("probe","pg_tww","current",None,None,None,None,None) as obj:
        # bypass hierarchy filtering to get realistic available IDs
        data, attributes=obj.get_swmm_table(view, "current", None, None)
        ids=[]
        if data:
            for row in data:
                row=dict(zip(attributes,row))
                ids.append({k:str(row[k]) for k in ["obj_id","name","fromnode","tonode"] if k in row and row[k] is not None})
        return ids

catalog={kind:ids_for(kind) for kind in ["CONDUITS","JUNCTIONS","OUTFALLS","STORAGES"]}
print("OFFICIAL_DATASET_VIEW_COUNTS",json.dumps({k:len(v) for k,v in catalog.items()}),flush=True)
for k,v in catalog.items():
    print("OFFICIAL_SAMPLE",k,json.dumps(v[:3]),flush=True)

template="/usr/src/plugin/teksi_wastewater/swmm_templates/default_tww_swmm_parameters.inp"
if not Path(template).exists():
    paths=list(Path("/usr/src/plugin/teksi_wastewater/swmm_templates").glob("*.inp"))
    template=str(paths[0])
print("TEMPLATE",template,flush=True)

def generate(name,structures,reaches):
    file=str(OUTPUT/(name+".inp"))
    with TwwSwmm("official-fixture", "pg_tww","current",file,template,None,None,None) as obj:
        obj.write_input(None if structures is not None else "primary",structures,reaches)
    txt=Path(file).read_text()
    sections={}
    for key in ["CONDUITS","JUNCTIONS","OUTFALLS","STORAGES","COORDINATES"]:
        lines=txt.split("["+key+"]\n")
        if len(lines)>1:
            end=lines[1].split("\n[")[0]
            sections[key]=sum(1 for z in end.splitlines() if z.strip() and not z.strip().startswith(";"))
    def data_rows(section):
        import re
        matched=re.search(rf"(?ms)^\\[{section}\\]\\n(.*?)(?=^\\[[A-Z_]+\\]\\n|\\Z)",txt)
        if not matched:
            return []
        return [line.strip().split() for line in matched.group(1).splitlines()
                if line.strip() and not line.lstrip().startswith(";")]
    nodes={r[0] for sect in ("JUNCTIONS","OUTFALLS","STORAGES") for r in data_rows(sect)}
    refs={(r[1],r[2]) for r in data_rows("CONDUITS") if len(r)>=3}
    dangling=sorted({node for pair in refs for node in pair if node not in nodes})
    print("OFFICIAL_GENERATED",name,json.dumps(sections),flush=True)
    print("OFFICIAL_REFERENCES",name,json.dumps({"nodes":sorted(nodes),"conduit_endpoint_pairs":sorted([list(p) for p in refs]),"missing_endpoint_nodes":dangling}),flush=True)
    return sections,dangling

try:
    assert len(catalog["CONDUITS"])>0 and len(catalog["JUNCTIONS"])>=2, "Official imported XTF had insufficient realistic fixture rows"
    full=generate("whole",None,None)
    assert not full[1], "Unexpected dangling reference in official full model"
    selected_structures=[row["obj_id"] for rows in (catalog["JUNCTIONS"],catalog["OUTFALLS"]) for row in rows[:1] if "obj_id" in row]
    selected_reaches=[row["obj_id"] for row in catalog["CONDUITS"][:1] if "obj_id" in row]
    if not selected_structures or not selected_reaches:
        print("INSUFFICIENT_OFFICIAL_FIXTURE_FOR_COMPLETE_SELECTION",flush=True)
    results={}
    for name,structures,reaches in [
        ("selected_both",selected_structures,selected_reaches),
        ("selected_structures_only",selected_structures,[]),
        ("selected_reaches_only",[],selected_reaches),
        ("selected_none",[],[]),
    ]:
        results[name]=generate(name,structures,reaches)
    assert results["selected_both"][1], "A selected conduit with only one endpoint selected should reveal a missing endpoint"
    assert results["selected_structures_only"][0]["CONDUITS"]>0, "Empty reaches unexpectedly excluded all conduits"
    assert results["selected_none"][0]["CONDUITS"]>0, "Empty selection unexpectedly excluded all conduits"
finally:
    print("OFFICIAL_SWMM_PROBE_COMPLETE",flush=True)
