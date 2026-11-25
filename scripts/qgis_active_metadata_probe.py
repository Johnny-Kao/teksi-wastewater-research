#!/usr/bin/env python3
"""Inspect native active field metadata; report leads, not automatic fixes."""
import collections
import json
import os
import sys
import xml.etree.ElementTree as ET

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from qgis.core import (QgsApplication, QgsProject, QgsExpression,
    QgsExpressionContext, QgsExpressionContextUtils, QgsFeature)

app = QgsApplication([], False)
app.initQgis()
project = QgsProject.instance()
assert project.read(sys.argv[1])
root = ET.parse(sys.argv[1]).getroot()
xml_layers = {e.findtext("id"): e for e in root.findall(".//projectlayers/maplayer")}
counts = collections.Counter()
findings = []
for layer in project.mapLayers().values():
    if not hasattr(layer, "fields"):
        continue
    assert layer.isValid(), layer.name()
    fields = layer.fields()
    names = {f.name() for f in fields}
    ctx = QgsExpressionContext()
    ctx.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
    feature = QgsFeature(fields)
    ctx.setFeature(feature)
    def check(kind, owner, source):
        if not source:
            return
        counts[kind] += 1
        exp = QgsExpression(source)
        missing = sorted(set(exp.referencedColumns()) - names - {"#!"})
        ready = exp.prepare(ctx)
        if missing or exp.hasParserError() or not ready:
            findings.append(dict(layer=layer.name(), kind=kind, owner=owner,
                expression=source, missing=missing, prepared=ready,
                parser_error=exp.parserErrorString(), eval_error=exp.evalErrorString()))
    check("display", "", layer.displayExpression())
    for i, field in enumerate(fields):
        check("default", field.name(), layer.defaultValueDefinition(i).expression())
        check("constraint", field.name(), layer.constraintExpression(i))
    xml = xml_layers.get(layer.id())
    if xml is None:
        continue
    settings = collections.defaultdict(set)
    for parent in xml.iter():
        if parent.tag in ("editable", "labelOnTop", "reuseLastValue"):
            for elem in parent.findall("field"):
                if elem.get("name"):
                    settings[elem.get("name")].add(parent.tag)
    for name, tags in settings.items():
        counts["saved_option_pairs"] += 1
        if name not in names:
            counts["absent_saved_option_pairs"] += 1
            print("INACTIVE_OR_UNRESOLVED_OPTION", json.dumps(
                dict(layer=layer.name(), field=name, tags=sorted(tags)), ensure_ascii=False))
    # Evaluate the three targeted display expressions on an in-memory feature
    # with distinct values so a successful prepare is not the sole evidence.
    labels = {"vw_tww_ws_maintenance": "ws_identifier",
        "vw_tww_additional_ws": "identifier",
        "re_maintenance_event_wastewater_structure": "id"}
    if layer.name() in labels:
        target = labels[layer.name()]
        idx = fields.indexFromName(target)
        if idx >= 0:
            feature.setAttribute(idx, "42" if target == "id" else "TEKSI-audit-label")
            ctx.setFeature(feature)
            exp = QgsExpression(layer.displayExpression())
            prepared = exp.prepare(ctx)
            value = exp.evaluate(ctx) if prepared else None
            print("DISPLAY_FIXTURE", json.dumps(dict(layer=layer.name(), target=target,
                prepared=prepared, value=str(value), error=exp.evalErrorString())))
# Saved styles are switchable configurations, not necessarily dead metadata.
# Inspect each style through QGIS itself and restore the original selection.
for layer in project.mapLayers().values():
    if not hasattr(layer, "fields"):
        continue
    manager = layer.styleManager()
    original = manager.currentStyle()
    for style in manager.styles():
        if not manager.setCurrentStyle(style):
            print("STYLE_SWITCH_FAILED", layer.name(), style)
            continue
        counts["styles_tested"] += 1
        fields = layer.fields()
        names = {f.name() for f in fields}
        def inspect(element):
            if hasattr(element, "children"):
                for child in element.children():
                    inspect(child)
            if hasattr(element, "idx") and hasattr(element, "name"):
                idx = element.idx()
                name = element.name()
                if idx < 0 or idx >= len(fields) or fields[idx].name() != name:
                    counts["style_invalid_form"] += 1
                    print("STYLE_INVALID_FORM", json.dumps(dict(layer=layer.name(),
                        style=style, field=name, index=idx, present=name in names)))
        for tab in layer.editFormConfig().tabs():
            inspect(tab)
        ctx = QgsExpressionContext()
        ctx.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
        ctx.setFeature(QgsFeature(fields))
        exp = QgsExpression(layer.displayExpression())
        if layer.displayExpression() and not exp.prepare(ctx):
            counts["style_invalid_display"] += 1
            print("STYLE_INVALID_DISPLAY", json.dumps(dict(layer=layer.name(),
                style=style, expression=layer.displayExpression(),
                error=exp.evalErrorString())))
    manager.setCurrentStyle(original)
for finding in findings:
    print("EXPRESSION_LEAD", json.dumps(finding, ensure_ascii=False))
print("AUDIT_COUNTS", json.dumps(dict(counts), sort_keys=True))
print("EXPRESSION_LEADS_TOTAL", len(findings))
