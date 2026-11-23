#!/usr/bin/env python3
"""Prepare a strictly scoped eight-site QGIS project fix candidate for research only.

Never modifies the upstream clone. Exits on unexpected schema, duplicate matches,
or drift in the upstream file.
"""
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

source, output = map(Path, sys.argv[1:3])
original = source.read_text(encoding="utf-8")
targets = {
    "vw_tww_ws_maintenance": ("ws__bottom_label", "ws_identifier"),
    "vw_tww_additional_ws": ("_label", "identifier"),
    "re_maintenance_event_wastewater_structure": ('COALESCE("obj_id", \'<NULL>\')', 'COALESCE("fk_wastewater_structure", "id")'),
}
form_targets = {
    "mvw_tww_channel": {"_from_node":("_from_ne", 42), "_to_node":("_to_ne", 45)},
    "vw_tww_channel_maintenance": {"_from_node":("_from_ne", 20), "_to_node":("_to_ne", 26)},
}
hits = []
def patch_layer(match):
    raw = match.group(0)
    layer = ET.fromstring(raw)
    name = layer.findtext("layername")
    if name in targets:
        old, new = targets[name]
        expr = layer.findtext("previewExpression")
        assert expr is not None, name
        assert old in expr, (name,expr)
        if name != "re_maintenance_event_wastewater_structure":
            assert expr == f'"{old}"', (name,expr)
            before,after = f'<previewExpression>"{old}"</previewExpression>',f'<previewExpression>"{new}"</previewExpression>'
        else:
            # XML markup uses literal single quotes and escaped angle brackets if any.
            before=f"<previewExpression>{old.replace('<','&lt;').replace('>','&gt;')}</previewExpression>"
            after=f"<previewExpression>{new}</previewExpression>"
        assert raw.count(before)==1,(name,before)
        raw=raw.replace(before,after,1)
        hits.append(("display",name,old,new))
    if name in form_targets:
        cfg=[e.get("name") for e in layer.findall("./fieldConfiguration/field")]
        for old,(new,index) in form_targets[name].items():
            assert cfg[index]==new, (name,new,index)
            pattern=rf'(<attributeEditorField\b[^>]*\bindex=")-1("[^>]*\bname="{re.escape(old)}")'
            raw,count=re.subn(pattern,lambda m:m.group(1)+str(index)+m.group(2).replace(f'name="{old}"',f'name="{new}"'),raw)
            assert count==1,(name,old,count)
            hits.append(("form_replace",name,old,new))
    if name=="measuring_point":
        pattern=r'(?m)^[ \t]*<attributeEditorField\b[^>]*\bname="fk_reference_station"[^>]*>.*?</attributeEditorField>\n?'
        raw,count=re.subn(pattern,"",raw,flags=re.DOTALL)
        assert count==1,(name,count)
        hits.append(("form_remove",name,"fk_reference_station","(obsolete field widget)"))
    return raw
updated,matched=re.subn(r'<maplayer\b[^>]*>.*?</maplayer>',patch_layer,original,flags=re.DOTALL)
assert len(hits)==8,(len(hits),hits)
assert matched==221,matched
root=ET.fromstring(updated)
assert len(root.findall(".//projectlayers/maplayer"))==221
output.parent.mkdir(parents=True,exist_ok=True)
output.write_text(updated,encoding="utf-8")
for v in hits:print("CANDIDATE",*v,sep=" | ")
print("PATCHED_PROJECT",output)
