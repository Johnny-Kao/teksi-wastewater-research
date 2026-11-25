#!/usr/bin/env python3
"""Compare effective field options with and without currently unresolved saved names."""
import collections
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from qgis.core import QgsApplication, QgsProject, QgsVectorLayer
app = QgsApplication([], False)
app.initQgis()
p = QgsProject.instance()
source = Path(sys.argv[1])
candidate = source.with_name("teksi_wastewater_saved_options_probe.qgs")
tags = {"editable", "labelOnTop", "reuseLastValue", "reuseLastValuePolicy"}
def snapshot(path):
    p.clear()
    assert p.read(str(path)), path
    out, schemas = {}, {}
    for layer in p.mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue
        assert layer.isValid(), layer.name()
        manager = layer.styleManager()
        original = manager.currentStyle()
        for style in manager.styles():
            if style != manager.currentStyle():
                assert manager.setCurrentStyle(style), (layer.name(), style)
            config = layer.editFormConfig()
            schema = {field.name() for field in layer.fields()}
            schemas[(layer.id(), style)] = schema
            result = {}
            for idx, field in enumerate(layer.fields()):
                policy = (config.reuseLastValuePolicy(idx)
                          if hasattr(config, "reuseLastValuePolicy")
                          else config.reuseLastValue(idx))
                result[field.name()] = [config.readOnly(idx), config.labelOnTop(idx), str(policy)]
            out[(layer.id(), style)] = result
        if manager.currentStyle() != original:
            assert manager.setCurrentStyle(original)
        schemas[(layer.id(), None)] = schemas[(layer.id(), original)]
    return out, schemas
before, schemas = snapshot(source)
parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
tree = ET.parse(source, parser=parser)
removed = []
for layer in tree.getroot().findall(".//projectlayers/maplayer"):
    lid = layer.findtext("id")
    scopes = [(None, layer)]
    for style in layer.findall("./map-layer-style-manager/map-layer-style"):
        qgis = style.find("qgis")
        if qgis is not None:
            scopes.append((style.get("name"), qgis))
    for style, scope in scopes:
        names = schemas.get((lid, style))
        if names is None:
            continue
        # Only direct edit-form option entries; do not touch expressions, fields,
        # aliases, relations, widgets, or any actual current field.
        for tag in tags:
            parent = scope.find(tag)
            if parent is None:
                continue
            for item in list(parent):
                name = item.get("name")
                if item.tag == "field" and name and name not in names:
                    removed.append(dict(layer=layer.findtext("layername"), style=style,
                                        field=name, tag=tag, attributes=item.attrib))
                    parent.remove(item)
tree.write(candidate, encoding="utf-8", xml_declaration=True)
after, schemas_after = snapshot(candidate)
print("REMOVED_OPTION_ENTRIES", len(removed))
print("REMOVED_LAYER_STYLE_FIELD_PAIRS", len({(r["layer"],r["style"],r["field"]) for r in removed}))
print("STYLE_SNAPSHOTS", len(before))
print("LIVE_FIELD_OPTION_VALUES", sum(len(v)*3 for v in before.values()))
for r in removed:
    print("OPTION_CANDIDATE", json.dumps(r, sort_keys=True))
diff = [key for key in set(before)|set(after) if before.get(key)!=after.get(key)]
print("CHANGED_EFFECTIVE_STYLES", len(diff))
print("CHANGED_SCHEMAS", len([key for key in set(schemas)|set(schemas_after) if schemas.get(key)!=schemas_after.get(key)]))
assert before == after, diff
assert schemas == schemas_after
print("SAVED_OPTION_AB_PASS")
