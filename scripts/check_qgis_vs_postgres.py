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

# Audit whether DB-absent fields occur in expressions or other nontrivial QGIS XML.
# All classifications are static leads; a reference in metadata is not a proven failure.
absent_index={(r["layer"],r["field"]):r for r in absent}
operational=[]
usage_tags=Counter()
metadata_usage=Counter()
safe_parent_tags={"editable","labelOnTop","reuseLastValue","fieldConfiguration",
                  "aliases","defaults","constraints","constraintExpressions",
                  "attributetableconfig","splitPolicies","duplicatePolicies"}
for layer in root.findall(".//projectlayers/maplayer"):
    lname=layer.findtext("layername") or "(unnamed)"
    fields={f for (n,f) in absent_index if n==lname}
    if not fields: continue
    re_fields=re.compile(r"(?<![A-Za-z0-9_])(?:"+"|".join(re.escape(f) for f in sorted(fields,key=len,reverse=True))+r")(?![A-Za-z0-9_])")
    parent={child:p for p in layer.iter() for child in p}
    for e in layer.iter():
        values=[("@"+k,v) for k,v in e.attrib.items()]
        if e.text and e.text.strip(): values.append(("#text",e.text))
        for location,content in values:
            matches=set(m.group() for m in re_fields.finditer(content))
            if not matches: continue
            ancestry=[]
            node=e
            while node is not None and node is not layer:
                ancestry.append(node.tag)
                node=parent.get(node)
            classification="saved_field_metadata" if any(tag in safe_parent_tags for tag in ancestry) else "requires_review"
            for field in matches:
                entry={"layer":lname,"field":field,"tag":e.tag,"location":location,
                       "classification":classification,
                       "value":content.strip()[:190],"path":"/".join(reversed(ancestry))}
                if classification=="requires_review":
                    operational.append(entry)
                    usage_tags[(e.tag,location)]+=1
                else:
                    metadata_usage[(e.tag,location)]+=1

out={"source":"Fresh tww DB installed by official PUM in Actions",
     "catalog_relation_count":len(catalog),"columns_total":sum(map(len,catalog.values())),
     "unmatched_QGIS_fields":len(rows),"summary":dict(summary),
     "layers":sorted(({"layer":k,**v} for k,v in bylayer.items()),key=lambda x:x.get("DB_ABSENT",0),reverse=True),
     "absent":absent,"present":present}
out["nontrivial_references"]=operational
out["nontrivial_tag_counts"]=[{"tag":k[0],"location":k[1],"count":v} for k,v in usage_tags.most_common()]
out["metadata_tag_counts"]=[{"tag":k[0],"location":k[1],"count":v} for k,v in metadata_usage.most_common(25)]
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

print("NONTRIVIAL REF COUNTS",len(operational),"distinct fields",len(set((r["layer"],r["field"]) for r in operational)))
print("NONTRIVIAL TAGS",out["nontrivial_tag_counts"][:25])
for ref in operational[:70]: print("NONTRIVIAL",ref)
