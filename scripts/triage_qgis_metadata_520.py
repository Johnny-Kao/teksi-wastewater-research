#!/usr/bin/env python3
"""Triage QGIS saved field settings against actual layer form configurations.
No mutation: findings are leads, not confirmed database-schema defects.
"""
import collections
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

source=Path(sys.argv[1])
root=ET.parse(source).getroot()
rows=[]
layers=[]
for layer in root.findall(".//projectlayers/maplayer"):
    name=layer.findtext("layername") or "(unnamed)"
    lid=layer.findtext("id") or "(unknown)"
    provider=layer.findtext("provider") or ""
    datasource=layer.findtext("datasource") or ""
    all_fields=collections.defaultdict(set)
    for elem in layer.iter():
        if elem.tag == "field" and elem.get("name"):
            all_fields[elem.get("name")].add("field:"+str(elem.attrib))
        elif elem.tag in ("alias","column","default","constraint","policy","editWidget") and (elem.get("field") or elem.get("name")):
            all_fields[elem.get("field") or elem.get("name")].add(elem.tag)
    definitions={e.get("name") for e in layer.findall(".//fieldConfiguration/field") if e.get("name")}
    attributes={e.get("name") for e in layer.findall(".//editforminitcodesource/field") if e.get("name")}
    settings=collections.defaultdict(set)
    for parent in layer.iter():
        if parent.tag in ("editable","labelOnTop","reuseLastValue"):
            for e in parent:
                if e.tag=="field" and e.get("name"):
                    settings[e.get("name")].add(parent.tag)
    if settings:
        unknown={f for f in settings if f not in definitions}
        for field in sorted(unknown):
            metadata=sorted(all_fields[field])
            rows.append({
                "layer":name,"id":lid,"field":field,
                "settings":sorted(settings[field]),
                "configured_definition":field in definitions,
                "other_metadata":metadata[:7],
                "source":datasource[:270],"provider":provider,
                "known_form_definition_count":len(definitions),
            })
        layers.append({"layer":name,"id":lid,"provider":provider,
            "configured_definitions":len(definitions),"setting_fields":len(settings),
            "unmatched_unique_fields":len(unknown),"source":datasource[:270],
            "unmatched_examples":sorted(unknown)[:12]})
legacy=[r for r in rows if r["field"]=="dss2020_hydraulic_load_current"]
subset=[r for r in rows if r["field"]!="dss2020_hydraulic_load_current"]
counts=collections.Counter(r["layer"] for r in subset)
prefixes=collections.Counter(r["field"].split("_")[0] for r in subset)
with_definition=collections.Counter()
for r in subset:
    if r["known_form_definition_count"]==0: k="NO_FIELD_CONFIGURATION_AT_ALL"
    elif r["other_metadata"]: k="OTHER_METADATA_PRESENT"
    else: k="NO_OTHER_METADATA"
    with_definition[k]+=1
out={"counts":{"layers_total":len(root.findall(".//projectlayers/maplayer")),"rows_settings_unmatched_unique":len(rows),"rows_excluding_legacy":len(subset),"legacy_unique_layer_entries":len(legacy),
     "unique_names_excluding_legacy":len(set(r["field"] for r in subset)),"layers_affected_excluding_legacy":len(counts)},
     "cause_buckets":dict(with_definition),"layers_ranked":counts.most_common(40),
     "field_prefixes":prefixes.most_common(30),"layer_detail":layers,
     "nonlegacy_unmatched":subset}
Path("metadata-520-triage.json").write_text(json.dumps(out,indent=2))
print("COUNTS",out["counts"])
print("CAUSE BUCKETS",out["cause_buckets"])
print("TOP LAYERS",out["layers_ranked"][:25])
print("PREFIX",out["field_prefixes"][:15])
print("LAYER SUMMARY")
for d in sorted(layers,key=lambda x:x["unmatched_unique_fields"],reverse=True)[:35]:
    print(json.dumps(d))
print("FOLLOWUP HYPOTHESIS: QGIS editable/labelOnTop/reuseLastValue may retain field names from historic schemas.")
print("These are not runtime bug confirmations. Need compare actual PostgreSQL views/table columns and QGIS schema resolver.")
