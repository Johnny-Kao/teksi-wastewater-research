#!/usr/bin/env python3
"""Cross-check QGIS remembered field options against actual PostgreSQL catalog."""
from collections import Counter, defaultdict
from pathlib import Path
import json
import re
import sys
import xml.etree.ElementTree as ET

qgs_path, db_path = map(Path, sys.argv[1:3])
root = ET.parse(qgs_path).getroot()
items = json.loads(db_path.read_text())
catalog = defaultdict(set)
for d in items:
    catalog[(d["table_schema"],d["table_name"])].add(d["column_name"])
settings_by_field=defaultdict(list)
rows=[]
for layer in root.findall(".//projectlayers/maplayer"):
    layername=layer.findtext("layername") or "(unnamed)"
    ds=layer.findtext("datasource") or ""
    relation=re.search(r'table="([^"]+)"\."([^"]+)"',ds)
    if not relation: continue
    schema,tablename=relation.groups()
    dbcolumns=catalog.get((schema,tablename))
    if dbcolumns is None: continue
    definitions={f.get("name") for f in layer.findall(".//fieldConfiguration/field")}
    settings=defaultdict(set)
    for parent in layer.iter():
        if parent.tag not in ("editable","labelOnTop","reuseLastValue"): continue
        for node in parent:
            if node.tag=="field" and node.get("name"):
                settings[node.get("name")].add(parent.tag)
    for field,tags in settings.items():
        if field in definitions: continue
        known=(schema,tablename) in catalog
        status=("DB_PRESENT" if field in dbcolumns else "DB_ABSENT") if known else "RELATION_NOT_FOUND"
        rows.append({"layer":layername,"relation":f"{schema}.{tablename}",
                     "field":field,"status":status,"settings":sorted(tags),
                     "has_fieldConfig":field in definitions})
summary=Counter(r["status"] for r in rows)
bylayer=defaultdict(lambda:Counter())
for r in rows: bylayer[r["layer"]][r["status"]]+=1
absent=[r for r in rows if r["status"]=="DB_ABSENT"]
present=[r for r in rows if r["status"]=="DB_PRESENT"]
out={"source":"Fresh tww DB installed by official PUM in Actions",
     "catalog_relation_count":len(catalog),"columns_total":sum(map(len,catalog.values())),
     "unmatched_QGIS_fields":len(rows),"summary":dict(summary),
     "layers":sorted(({"layer":k,**v} for k,v in bylayer.items()),key=lambda x:x.get("DB_ABSENT",0),reverse=True),
     "absent":absent,"present":present}
Path("qgis-vs-postgres.json").write_text(json.dumps(out,indent=2))
print("DATABASE RELATIONS",len(catalog),"COLUMNS",out["columns_total"])
print("TOTAL QGIS UNMATCHED",len(rows),"CATEGORIES",dict(summary))
print("LARGEST ABSENT LAYERS")
for v in out["layers"][:20]: print(v)
print("EXAMPLES ABSENT:")
for r in absent[:50]: print(f"  {r['relation']} / {r['layer']}: {r['field']}")
print("EXAMPLES PRESENT:")
for r in present[:20]: print(f"  {r['relation']} / {r['layer']}: {r['field']}")
print("Note: DB-absent remembered QGIS option alone is NOT proven malfunction; verify expression, UI and writes.")
