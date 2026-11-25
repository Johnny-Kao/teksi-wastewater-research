#!/usr/bin/env python3
"""Native verification of identifier defaults and flow constraint boundaries."""
import json,os,sys
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from qgis.core import (QgsApplication,QgsProject,QgsVectorLayer,QgsFeature,
    QgsFeatureRequest,QgsExpression,QgsExpressionContext,QgsExpressionContextUtils)
app=QgsApplication([],False);app.initQgis()
p=QgsProject.instance()
assert p.read(sys.argv[1])
target=p.mapLayer("vw_tww_catchment_area_totals_fccd22f0_6775_46cf_8065_a8ecd98f82b3")
node_id="vw_tww_wastewater_node"
log_id="vw_tww_log_card_10cf0437_ed7a_4299_adc6_9d00c3f1703f"
status_id="hydraulic_char_data_status_30c0bb3f_0f3d_4219_8fcd_37605e554496"
for lid,fields in ((node_id,("obj_id","identifier")),(log_id,("obj_id","identifier")),(status_id,("code","value_en"))):
    l=p.mapLayer(lid)
    assert l and l.isValid(),lid
    assert set(fields)<={f.name() for f in l.fields()},lid
fields=target.fields()
status=p.mapLayer(status_id)
labels={}
for code in (6372,6373,6371):
    records=list(status.getFeatures(QgsFeatureRequest().setFilterExpression('"code" = '+str(code))))
    assert len(records)==1,(code,records)
    labels[code]=str(records[0]["value_en"])
    assert labels[code]
# The shipped database starts empty. Replace the two referenced data layers
# with deterministic in-memory fixtures, retaining the real status table.
for lid,records in ((node_id,[("node-1","Node A"),("node-long","ABCDEFGHIJKLMNOPQRSTUVWXYZ")]),
                    (log_id,[("log-1","Log A")])):
    p.removeMapLayer(lid)
    layer=QgsVectorLayer("None?field=obj_id:string&field=identifier:string",lid,"memory")
    assert layer.isValid(),lid
    for record in records:
        f=QgsFeature(layer.fields());f.setAttributes(list(record))
        assert layer.dataProvider().addFeatures([f])[0]
    p.addMapLayer(layer)
def evaluate(source,attributes):
    f=QgsFeature(fields)
    for name,value in attributes.items():assert f.setAttribute(name,value),name
    ctx=QgsExpressionContext()
    ctx.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(target))
    ctx.setFeature(f)
    e=QgsExpression(source)
    assert e.prepare(ctx),(source,e.parserErrorString(),e.evalErrorString())
    value=e.evaluate(ctx)
    assert not e.hasEvalError(),(source,e.evalErrorString())
    return value
for prefix,code in (("hc_c_",6372),("hc_o_",6373),("hc_p_",6371)):
    field=prefix+"identifier";idx=fields.indexFromName(field)
    default=target.defaultValueDefinition(idx)
    assert default.applyOnUpdate()
    for attrs,name in (({"fk_log_card":"log-1","wn_obj_id":"node-1"},"Log A"),
                       ({"wn_obj_id":"node-1"},"Node A"),
                       ({"wn_obj_id":"node-long"},"ABCDEFGHIJKLMNOPQRSTUVWXYZ")):
        actual=evaluate(default.expression(),attrs)
        expected=(name+"-"+labels[code])[:20]
        assert actual==expected,(field,actual,expected,attrs)
        print("DEFAULT_PASS",field,repr(actual))
    constraint=target.constraintExpression(fields.indexFromName(prefix+"pump_flow_min"))
    for minimum,maximum,expected in ((20,10,False),(5,10,True),(10,10,True),(5,None,True)):
        actual=evaluate(constraint,{prefix+"pump_flow_min":minimum,prefix+"pump_flow_max":maximum})
        assert bool(actual)==expected,(prefix,minimum,maximum,actual)
        print("CONSTRAINT_PASS",prefix,minimum,maximum,actual)
print("NATIVE_C3_C4_PASS")
