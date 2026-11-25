#!/usr/bin/env python3
"""Read-only classification against the actual provider fields in every QGIS style."""
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from qgis.core import (QgsApplication,QgsProject,QgsVectorLayer,QgsFeature,
    QgsExpression,QgsExpressionContext,QgsExpressionContextUtils)
app=QgsApplication([],False)
app.initQgis()
p=QgsProject.instance()
assert p.read(sys.argv[1])
root=ET.parse(sys.argv[1]).getroot()
xml={e.findtext("id"):e for e in root.findall(".//projectlayers/maplayer")}
out={"fields":{},"options":{},"form_fields":{},"expressions":{},"layers":{},"effective_options":{}}
for layer in p.mapLayers().values():
    if not isinstance(layer,QgsVectorLayer): continue
    assert layer.isValid(),layer.name()
    manager=layer.styleManager()
    original=manager.currentStyle()
    element=xml[layer.id()]
    for style in manager.styles():
        if style!=manager.currentStyle(): assert manager.setCurrentStyle(style),(layer.name(),style)
        key=layer.id()+"|"+style
        fields=layer.fields()
        names={f.name() for f in fields}
        out["fields"][key]=sorted(names)
        config=layer.editFormConfig()
        out["effective_options"][key]={field.name():[config.readOnly(idx),config.labelOnTop(idx),str(config.reuseLastValuePolicy(idx) if hasattr(config,"reuseLastValuePolicy") else config.reuseLastValue(idx))] for idx,field in enumerate(fields)}
        out["layers"][key]={"layer":layer.name(),"style":style,"source":layer.source()}
        ctx=QgsExpressionContext()
        ctx.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
        ctx.setFeature(QgsFeature(fields))
        def inspect(kind, owner, source):
            if not source: return
            exp=QgsExpression(source)
            missing=sorted(set(exp.referencedColumns())-names-{"#!"})
            ready=exp.prepare(ctx)
            value=exp.evaluate(ctx) if ready else None
            out["expressions"][key+"|"+kind+"|"+owner]=dict(layer=layer.name(),style=style,layer_style=key,kind=kind,field=owner,expression=source,missing=missing,prepared=ready,parser_error=exp.parserErrorString(),eval_error=exp.evalErrorString(),value=str(value))
        inspect("C1","",layer.displayExpression())
        for idx,field in enumerate(fields):
            inspect("C3",field.name(),layer.defaultValueDefinition(idx).expression())
            inspect("C4",field.name(),layer.constraintExpression(idx))
        scope=element if style==original else next((s.find("qgis") for s in element.findall("./map-layer-style-manager/map-layer-style") if s.get("name")==style),None)
        if scope is not None:
            for tag in ("editable","labelOnTop","reuseLastValue","reuseLastValuePolicy"):
                for node in scope.findall("./"+tag+"/field"):
                    field=node.get("name")
                    if not field: continue
                    ident=key+"|"+field
                    row=out["options"].setdefault(ident,dict(layer=layer.name(),style=style,layer_style=key,field=field,present=field in names,settings=[]))
                    row["settings"].append({"tag":tag,**node.attrib})
        def walk(e):
            if hasattr(e,"children"):
                for child in e.children(): walk(child)
            if hasattr(e,"idx") and hasattr(e,"name"):
                field=e.name()
                out["form_fields"][key+"|"+field]=dict(layer=layer.name(),style=style,layer_style=key,field=field,present=field in names,index=e.idx())
        for tab in layer.editFormConfig().tabs(): walk(tab)
        if layer.name()=="vw_tww_catchment_area_totals":
            print("CATCHMENT_FIELDS",style,json.dumps(sorted(names)))
            for prefix in ("hc_c_","hc_o_","hc_p_"):
                required=[prefix+x for x in ("fk_wastewater_node","status","pump_flow_min","pump_flow_max","identifier")]
                print("CATCHMENT_PREFIX",style,prefix,json.dumps({f:f in names for f in required}))
                if all(prefix+s in names for s in ("pump_flow_min","pump_flow_max")):
                    f=QgsFeature(fields)
                    f.setAttribute(prefix+"pump_flow_min",20)
                    f.setAttribute(prefix+"pump_flow_max",10)
                    c=QgsExpressionContext()
                    c.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
                    c.setFeature(f)
                    old=layer.constraintExpression(fields.indexFromName(prefix+"pump_flow_min"))
                    new='if( "{0}pump_flow_max" is not NULL, "{0}pump_flow_min" <= "{0}pump_flow_max", 1)'.format(prefix)
                    for minimum,maximum in ((20,10),(5,10),(10,10),(5,None)):
                        f.setAttribute(prefix+"pump_flow_min",minimum)
                        f.setAttribute(prefix+"pump_flow_max",maximum)
                        c.setFeature(f)
                        for version,expr in (("old",old),("candidate",new)):
                            e=QgsExpression(expr);ready=e.prepare(c);value=e.evaluate(c) if ready else None
                            print("CATCHMENT_CONSTRAINT",style,prefix,minimum,maximum,version,ready,repr(value),e.evalErrorString())
    if manager.currentStyle()!=original: assert manager.setCurrentStyle(original)
Path("/tmp/schema-variant.json").write_text(json.dumps(out,indent=2))
print("SCHEMA_VARIANT_COMPLETE",len(out["fields"]),len(out["options"]),len(out["form_fields"]))
