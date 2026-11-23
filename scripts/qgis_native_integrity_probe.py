#!/usr/bin/env python3
"""Read-only native QGIS integration audit against official TEKSI test DB."""
import json
import os
from collections import Counter
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from qgis.core import (
    QgsApplication, QgsProject, QgsExpression, QgsExpressionContext, QgsExpressionContextUtils,
)
app=QgsApplication([],False)
app.initQgis()
qgs=sys.argv[1]
project=QgsProject.instance()
ok=project.read(qgs)
print("QGIS_VERSION",QgsApplication.qgisSettingsDirPath())
print("PROJECT_READ",ok,"LAYER_COUNT",len(project.mapLayers()))
print("INVALID_LAYERS",[(layer.name(),layer.providerType()) for layer in project.mapLayers().values() if not layer.isValid()][:30])

names=["vw_tww_ws_maintenance","vw_tww_additional_ws","vw_tww_reach","vw_tww_channel_maintenance",
       "vw_tww_overflow","vw_tww_wastewater_structure","measure_point"]
results=[]
for name in names:
    layers=project.mapLayersByName(name)
    for layer in layers:
        fields={f.name() for f in layer.fields()}
        exp=layer.displayExpression()
        ctx=QgsExpressionContext()
        ctx.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
        expression=QgsExpression(exp)
        prepared=expression.prepare(ctx)
        values = {"name":name,"valid":layer.isValid(),"fields":len(fields),
                  "displayExpression":exp,"expression_parsed":not expression.hasParserError(),
                  "expression_prepared":prepared,
                  "referencedColumns":sorted(expression.referencedColumns()),
                  "missingReferencedColumns":sorted(set(expression.referencedColumns())-fields),
                  "missingRelevantFields":sorted(set(["_label","ws__bottom_label","ag64_fk_provider","ag96_fk_provider",
                                "fk_wastewater_structure","_from_node","_to_node"])-fields)}
        if prepared:
            expression.evaluate(ctx)
            values["evalError"]=expression.evalErrorString()
        results.append(values)
        print("LAYER",json.dumps(values))
print("PROJECT_RELATIONS")
rels=[]
for id, relation in project.relationManager().relations().items():
    values={"id":id,"name":relation.name(),"valid":relation.isValid(),
            "referencingLayer":relation.referencingLayer().name() if relation.referencingLayer() else None,
            "referencedLayer":relation.referencedLayer().name() if relation.referencedLayer() else None,
            "pairs":relation.fieldPairs()}
    rels.append(values)
    if not relation.isValid(): print("INVALID_RELATION",json.dumps(values))
print("RELATION_SUMMARY",len(rels),"invalid",sum(not v["valid"] for v in rels))
Path("/tmp/qgis-native-audit.json").write_text(json.dumps({"read":ok,"layers":results,"invalid_relations":[r for r in rels if not r["valid"]]},indent=2))
# Do not fail the entire workflow on invalid project entries; preserve evidence for triage.
