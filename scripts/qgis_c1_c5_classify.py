#!/usr/bin/env python3
"""Build a fixed five-category review inventory; never auto-edit source."""
import collections
import json
import pathlib
import re
import sys
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher

root=pathlib.Path(sys.argv[1])
variants={p.parent.name.removeprefix("schema-"):json.loads(p.read_text())
          for p in pathlib.Path(sys.argv[2]).glob("*/schema-variant.json")}
assert set(variants)=={"standard","agxx","webgis"},variants.keys()
base=variants["standard"]
migrations=[]
for path in sorted((root/"datamodel/changelogs").rglob("*.sql")):
    for line_no,line in enumerate(path.read_text(errors="replace").splitlines(),1):
        if re.search(r"\b(rename\s+(?:column|to)|drop\s+column|add\s+column)\b",line,re.I):
            migrations.append((str(path.relative_to(root)),line_no,line.strip()))
def provenance(field):
    pattern=re.compile(r"\b"+re.escape(field)+r"\b",re.I)
    return [{"path":p,"line":n,"sql":s} for p,n,s in migrations if pattern.search(s)]
def candidate_names(field,names):
    hits=[]
    for name in sorted(names):
        if name==field:continue
        if name.endswith("_"+field) or field.endswith("_"+name) or SequenceMatcher(None,field,name).ratio()>=0.84:
            hits.append(name)
    return hits[:25]
rows=[]
coverage={}
for kind,cat in (("form_fields","C2"),("options","C5")):
    keys=set().union(*(set(v[kind]) for v in variants.values()))
    coverage[cat]=len(keys)
    for key in sorted(keys):
        row=next(v[kind][key] for v in variants.values() if key in v[kind])
        field=row["field"]
        schema_key=row["layer_style"]
        present=[name for name,v in variants.items() if field in v["fields"].get(schema_key,[])]
        if len(present)==len(variants):continue
        names=set().union(*(set(v["fields"].get(schema_key,[])) for v in variants.values()))
        migration=provenance(field)
        options=row.get("settings",[])
        important=any(s.get("editable")=="0" or s.get("labelOnTop")=="1" or s.get("reuseLastValue")=="1" for s in options)
        disposition=("PRESERVE_VARIANT" if present else
                     "REVIEW_RENAME_OR_RETIRE" if cat=="C2" or important or migration else "INERT_CLEANUP_CANDIDATE")
        rows.append(dict(category=cat,**row,available_in=present,nondefault=important,
                         disposition=disposition,migration=migration,replacement_leads=candidate_names(field,names)))
for cat in ("C1","C3","C4"):
    keys=set().union(*(set(v["expressions"]) for v in variants.values()))
    keys={k for k in keys if any(v["expressions"].get(k,{}).get("kind")==cat for v in variants.values())}
    coverage[cat]=len(keys)
    for key in sorted(keys):
        checks={name:v["expressions"][key] for name,v in variants.items() if key in v["expressions"]}
        invalid=[name for name,r in checks.items() if not r["prepared"] or r["missing"] or r["parser_error"]]
        if not invalid:continue
        row=next(iter(checks.values()))
        rows.append(dict(category=cat,**row,invalid_in=invalid,disposition="REVIEW_EXPRESSION",
                         checks=checks,migration=[m for f in row["missing"] for m in provenance(f)]))
# Inventory other shipped QGIS templates (runtime SWMM report layers are separate).
templates=[]
for path in sorted(root.rglob("*.qgs")):
    project=ET.parse(path).getroot()
    layers=project.findall(".//projectlayers/maplayer")
    counts=collections.Counter()
    for layer in layers:
        for scope in [layer]+[s.find("qgis") for s in layer.findall("./map-layer-style-manager/map-layer-style") if s.find("qgis") is not None]:
            counts["styles"]+=1
            counts["C1"]+=len(scope.findall("./previewExpression"))
            counts["C2"]+=len(scope.findall(".//attributeEditorForm//attributeEditorField"))
            counts["C3"]+=len(scope.findall("./defaults/default"))
            counts["C4"]+=len(scope.findall("./constraintExpressions/constraint"))
            counts["C5"]+=sum(len(scope.findall("./"+tag+"/field")) for tag in ("editable","labelOnTop","reuseLastValue","reuseLastValuePolicy"))
    templates.append(dict(path=str(path.relative_to(root)),layers=len(layers),counts=dict(counts),
        validation="native matrix" if path.name=="teksi_wastewater.qgs" else "XML inventory only; runtime report inputs required"))
out={"coverage":coverage,"templates":templates,"review":rows}
pathlib.Path("c1-c5-inventory.json").write_text(json.dumps(out,indent=2))
print("COVERAGE",json.dumps(coverage))
print("TEMPLATES",json.dumps(templates))
for cat in ("C1","C2","C3","C4","C5"):
    selected=[r for r in rows if r["category"]==cat]
    print("CATEGORY",cat,len(selected),dict(collections.Counter(r["disposition"] for r in selected)))
    for row in selected:
        if cat!="C5" or row.get("nondefault") or row.get("migration"):
            print("REVIEW_ROW",json.dumps({k:v for k,v in row.items() if k!="checks"},ensure_ascii=False))
print("C1_C5_INVENTORY_COMPLETE")
