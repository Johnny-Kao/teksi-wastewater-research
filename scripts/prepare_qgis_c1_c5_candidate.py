#!/usr/bin/env python3
"""Prepare a narrow, reviewable patch using verified schema mappings.

Leave unresolved semantics, conflicts and custom extension options untouched.
Preserve unrelated XML formatting; never serialize the complete project.
"""
import collections
import json
import pathlib
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

source, output, variants_dir = map(pathlib.Path, sys.argv[1:4])
variants = {p.parent.name.removeprefix("schema-"): json.loads(p.read_text())
            for p in variants_dir.glob("*/schema-variant.json")}
assert set(variants) == {"standard", "agxx", "webgis"}
# The existing eight-site patch has native QGIS red/green evidence.
subprocess.run([sys.executable, str(pathlib.Path(__file__).with_name("prepare_qgis_8_fix.py")),
                str(source), str(output)], check=True)
original = output.read_text()
changes = []
deferred = []
def record(category, layer, style, old, new, reason):
    changes.append(dict(category=category, layer=layer, style=style,
                        old=old, new=new, reason=reason))

overflow = {name: "pu_"+name for name in (
    "construction_type", "operating_point", "stop_level", "start_level",
    "pump_flow_min_single", "pump_flow_max_single", "placement_of_pump",
    "placement_of_actuation")}
overflow.update({name: "pw_"+name for name in (
    "hydraulic_overflow_length", "level_max", "level_min", "weir_edge", "weir_kind")})
overflow.update({name: "lw_"+name for name in ("length", "width", "opening_shape")})
ag_fields = [f"ag{version}_{name}" for version in (64,96)
             for name in ("remark","fk_provider","last_modification")]
overflow.update({name: "ov_"+name for name in ag_fields})
mappings = {
    "vw_tww_overflow": overflow,
    "vw_tww_reach": {name:"ne_"+name for name in ag_fields},
    "vw_tww_wastewater_structure": {
        "ag96_fk_measure":"ws_ag96_fk_measure",
        "wn_ag64_last_modification":"ne_ag64_last_modification",
        "wn_ag96_last_modification":"ne_ag96_last_modification",
    },
    "mvw_tww_channel":{"_from_node":"_from_ne","_to_node":"_to_ne"},
    "vw_tww_channel_maintenance":{"_from_node":"_from_ne","_to_node":"_to_ne"},
}
retired = {
    "measuring_point": {"fk_reference_station"},
    "vw_tww_wastewater_structure":{"_input_label","_output_label"},
}
def parse(text):
    return ET.fromstring(text)

def field_availability(lid, style, name):
    key=lid+"|"+style
    return {v for v,data in variants.items() if name in data["fields"].get(key,[])}

def patch_scope(raw, lname, lid, style):
    scope=parse(raw)
    mapping=mappings.get(lname,{})
    live_old={old for old in mapping if field_availability(lid,style,old)}
    approved={old:new for old,new in mapping.items()
              if old not in live_old and field_availability(lid,style,new)}
    for old,new in mapping.items():
        if old not in approved and old not in live_old:
            deferred.append(dict(layer=lname,style=style,field=old,reason="target not present in native schema"))
    config=[f.get("name") for f in scope.findall("./fieldConfiguration/field")]
    # QGIS resolves form fields by name; preserve an explicit configuration
    # index where present, otherwise retain the unresolved index for native
    # re-resolution and require the post-patch audit to prove the target works.
    forms=scope.findall("./attributeEditorForm//attributeEditorField")
    form_names={f.get("name") for f in forms}
    for old,new in approved.items():
        if old not in form_names: continue
        if new in form_names:
            deferred.append(dict(layer=lname,style=style,field=old,reason="existing target form widget; needs duplicate review"))
            continue
        def replace_form(m):
            tag=m.group(0)
            elem=parse(tag[:-1]+"/>") if not tag.endswith("/>") else parse(tag)
            if elem.get("name")!=old:return tag
            result=re.sub(r'\bname="'+re.escape(old)+r'"','name="'+new+'"',tag,count=1)
            if new in config:
                result=re.sub(r'\bindex="-?\d+"','index="'+str(config.index(new))+'"',result,count=1)
            record("C2",lname,style,old,new,"view prefix / explicit field mapping")
            return result
        # Match only actual form field start tags, not similarly named options.
        def form_block(m):
            return re.sub(r'<attributeEditorField\b[^>]*>',replace_form,m.group(0))
        raw=re.sub(r'<attributeEditorForm\b[^>]*>.*?</attributeEditorForm>',form_block,raw,flags=re.S)
    for old in retired.get(lname,set()):
        if field_availability(lid,style,old):continue
        def remove_form(m):
            name=parse(m.group(0).lstrip()).get("name")
            if name!=old:return m.group(0)
            record("C2",lname,style,old,None,"explicit DROP COLUMN migration")
            return ""
        raw=re.sub(r'(?m)^[ \t]*<attributeEditorField\b[^>]*(?:/>|>.*?</attributeEditorField>)\n?',remove_form,raw,flags=re.S)
    # Only migrate known, same-semantics field options. Keep existing target
    # values intact if they disagree; never overwrite a legitimate setting.
    for tag in ("editable","labelOnTop","reuseLastValue","reuseLastValuePolicy"):
        def patch_options(m):
            block=m.group(0)
            opts={e.get("name"):e.attrib for e in parse(block).findall("field")}
            def patch_option(n):
                line=n.group(0)
                elem=parse(line.strip())
                old=elem.get("name")
                if not old or field_availability(lid,style,old):return line
                if old in retired.get(lname,set()):
                    record("C5",lname,style,old,None,tag+": explicitly retired")
                    return ""
                new=approved.get(old)
                if not new:return line
                if new in opts:
                    same={k:v for k,v in elem.attrib.items() if k!="name"}=={k:v for k,v in opts[new].items() if k!="name"}
                    if not same:
                        deferred.append(dict(layer=lname,style=style,field=old,target=new,reason=tag+": existing target differs"))
                        return line
                    record("C5",lname,style,old,None,tag+": redundant equivalent target")
                    return ""
                record("C5",lname,style,old,new,tag+": explicit mapping")
                return re.sub(r'\bname="'+re.escape(old)+r'"','name="'+new+'"',line,count=1)
            return re.sub(r'(?m)^[ \t]*<field\b[^>]*?/>\n?',patch_option,block)
        raw=re.sub(r'<'+tag+r'\b[^>]*>.*?</'+tag+r'>',patch_options,raw,flags=re.S)
    if lname=="vw_tww_catchment_area_totals":
        def patch_constraint(m):
            node=parse(m.group(0))
            field=node.get("field","")
            if field not in {"hc_c_pump_flow_min","hc_o_pump_flow_min","hc_p_pump_flow_min"}:return m.group(0)
            prefix=field.removesuffix("pump_flow_min")
            if not all(field_availability(lid,style,prefix+name) for name in ("pump_flow_min","pump_flow_max")):
                deferred.append(dict(layer=lname,style=style,field=field,reason="constraint target absent"))
                return m.group(0)
            old=node.get("exp","")
            if '"pump_flow_max"' not in old or '"pump_flow_min"' not in old:return m.group(0)
            new=old.replace('"pump_flow_max"','"'+prefix+'pump_flow_max"').replace('"pump_flow_min"','"'+prefix+'pump_flow_min"')
            def xmlattr(s):return escape(s, {'"':"&quot;"})
            before='exp="'+xmlattr(old)+'"'
            assert before in m.group(0),(lname,field,m.group(0))
            record("C4",lname,style,old,new,field)
            return m.group(0).replace(before,'exp="'+xmlattr(new)+'"',1)
        raw=re.sub(r'<constraintExpressions\b[^>]*>.*?</constraintExpressions>',
                   lambda m:re.sub(r'<constraint\b[^>]*?/>',patch_constraint,m.group(0)),raw,flags=re.S)
    return raw

def layer_patch(m):
    raw=m.group(0)
    layer=parse(raw)
    lname=layer.findtext("layername")
    lid=layer.findtext("id")
    manager=layer.find("map-layer-style-manager")
    current=manager.get("current","default") if manager is not None else "default"
    # Remove embedded styles temporarily to prevent changing them as default.
    saved=[]
    def hold(s):
        style=parse(s.group(0))
        name=style.get("name")
        patched=re.sub(r'<qgis\b[^>]*>.*?</qgis>',lambda q:patch_scope(q.group(0),lname,lid,name),s.group(0),flags=re.S)
        saved.append(patched)
        return f"<!--RESEARCH_STYLE_{len(saved)-1}-->"
    top=re.sub(r'<map-layer-style\b[^>]*>.*?</map-layer-style>',hold,raw,flags=re.S)
    top=patch_scope(top,lname,lid,current)
    for i,s in enumerate(saved):top=top.replace(f"<!--RESEARCH_STYLE_{i}-->",s,1)
    parse(top)
    return top
result=re.sub(r'<maplayer\b[^>]*>.*?</maplayer>',layer_patch,original,flags=re.S)
assert len(parse(result).findall(".//projectlayers/maplayer"))==221
output.write_text(result)
report={"changes":changes,"deferred":deferred,
        "scope":"original eight + explicit schema mappings; unresolved C3 and C5 kept"}
output.with_suffix(".review.json").write_text(json.dumps(report,indent=2))
print("PATCH_COUNTS",dict(collections.Counter(r["category"] for r in changes)))
for row in changes:print("PATCH_CHANGE",json.dumps(row))
for row in deferred:print("PATCH_DEFERRED",json.dumps(row))
print("CANDIDATE_READY")
