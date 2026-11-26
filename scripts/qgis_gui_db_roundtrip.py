#!/usr/bin/env python3
"""Exercise the exact audited project in native QGIS GUI and disposable PostgreSQL.

Run separately against baseline and candidate. Keep database fixture IDs
distinct per invocation. Fail on actual form/transaction discrepancies.
"""
import collections
import json
import sys
import traceback
from pathlib import Path

from qgis.PyQt.QtWidgets import QWidget
from qgis.core import (
    QgsApplication, QgsFeature, QgsFeatureRequest, QgsFieldConstraints,
    QgsProject, QgsVectorLayer, QgsExpression, QgsExpressionContext,
    QgsExpressionContextUtils,
)
from qgis.gui import (
    QgsAttributeForm, QgsAttributeEditorContext, QgsEditorWidgetWrapper,
    QgsGui, QgsMapCanvas,
)
try:
    import psycopg as pg
except ImportError:
    import psycopg2 as pg

project_path, manifest_path, version, variant = sys.argv[1:5]
assert version in ("baseline", "candidate")
app = QgsApplication([], True)
app.initQgis()
canvas = QgsMapCanvas()
QgsGui.editorWidgetRegistry().initEditors(canvas)
project = QgsProject.instance()
assert project.read(project_path), project_path
manifest = json.loads(Path(manifest_path).read_text())["changes"]
db = pg.connect("service=pg_tww")
db.autocommit = False
errors = []
results = []
tag = "B" if version == "baseline" else "A"
prefix = "TWWQA" + tag

def sql(query, params=(), fetch=False):
    with db.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall() if fetch else None

def scalar(query, params=()):
    rows = sql(query, params, True)
    assert len(rows) == 1, (query, rows)
    return rows[0][0]

def layer(lid):
    obj = project.mapLayer(lid)
    assert isinstance(obj, QgsVectorLayer) and obj.isValid(), lid
    return obj

def record(name, fn):
    try:
        fn()
        results.append((name, "PASS"))
        print("GUI_DB_PASS", name, flush=True)
    except Exception as exc:
        db.rollback()
        errors.append((name, repr(exc)))
        results.append((name, "FAIL"))
        print("GUI_DB_FAIL", name, repr(exc), flush=True)
        traceback.print_exc()

def feature(obj, oid):
    req = QgsFeatureRequest().setFilterExpression('"obj_id" = ' + QgsExpression.quotedString(oid))
    rows = list(obj.getFeatures(req))
    assert len(rows) == 1, (obj.name(), oid, len(rows))
    return rows[0]

def empty(obj):
    f = QgsFeature(obj.fields())
    f.setAttributes([None] * len(obj.fields()))
    f.setValid(True)
    return f

def form_for(obj, f):
    context = QgsAttributeEditorContext()
    context.setMapCanvas(canvas)
    form = QgsAttributeForm(obj, f, context)
    form.resize(1100, 800)
    form.show()
    app.processEvents()
    return form

def wrappers(form):
    result = collections.defaultdict(list)
    for widget in form.findChildren(QWidget):
        wrapper = QgsEditorWidgetWrapper.fromWidget(widget)
        if wrapper is not None:
            result[wrapper.field().name()].append(wrapper)
    return result

def form_field(form, name):
    w = wrappers(form).get(name, [])
    assert w, (name, sorted(wrappers(form)))
    return w[0]

def change(form, name, value):
    form.changeAttribute(name, value)
    app.processEvents()

def evaluate(obj, f, expr):
    ctx = QgsExpressionContext()
    ctx.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(obj))
    ctx.setFeature(f)
    e = QgsExpression(expr)
    assert e.prepare(ctx), e.evalErrorString()
    value = e.evaluate(ctx)
    assert not e.hasEvalError(), e.evalErrorString()
    return value

def commit_layer(obj):
    assert obj.commitChanges(), (obj.name(), obj.commitErrors())
    obj.reload()
    app.processEvents()

def rollback_layer(obj):
    assert obj.rollBack(), obj.name()
    obj.reload()

def fixture():
    # Use the same view and geometry construction as upstream test_views.py.
    ws = scalar("""
        INSERT INTO tww_app.vw_tww_wastewater_structure
          (identifier, ws_type, situation3d_geometry, wn_backflow_level_current)
        VALUES (%s, 'manhole', ST_SetSRID(ST_MakePoint(2600000,1200000),2056),100)
        RETURNING obj_id
    """, (prefix,))
    wn = scalar("SELECT wn_obj_id FROM tww_app.vw_tww_wastewater_structure WHERE obj_id=%s", (ws,))
    log = prefix + "LOG"
    sql("INSERT INTO tww_od.log_card (obj_id,fk_pwwf_wastewater_node) VALUES (%s,%s)", (log,wn))
    for suffix, status in (("C",6372),("O",6373),("P",6371)):
        sql("""INSERT INTO tww_od.hydraulic_char_data
            (obj_id,identifier,fk_wastewater_node,status,pump_flow_min,pump_flow_max)
            VALUES (%s,%s,%s,%s,5,10)""",
            (prefix+suffix, "old-"+suffix, wn,status))
    cat = prefix+"CAT"
    sql("""INSERT INTO tww_od.catchment_area_totals
            (obj_id,identifier,fk_hydraulic_char_data,fk_log_card)
            VALUES (%s,%s,%s,%s)""", (cat,prefix,prefix+"C",log))
    ov = prefix+"PUMP"
    sql("INSERT INTO tww_od.overflow (obj_id,identifier,fk_wastewater_node) VALUES (%s,%s,%s)",(ov,ov,wn))
    sql("INSERT INTO tww_od.pump (obj_id,pump_flow_min_single,pump_flow_max_single) VALUES (%s,5,10)",(ov,))
    db.commit()
    print("FIXTURE_COMMITTED", ws, wn, log, cat, ov, flush=True)
    return ws,wn,log,cat,ov

def check_forms():
    groups = collections.defaultdict(list)
    for row in manifest:
        if row["category"]=="C2":
            groups[row["layer_style"]].append(row)
    count = 0
    for key,rows in groups.items():
        lid,style = key.rsplit("|",1)
        obj = layer(lid)
        manager = obj.styleManager()
        oldstyle = manager.currentStyle()
        if style != oldstyle:
            assert manager.setCurrentStyle(style), key
        try:
            form = form_for(obj, empty(obj))
            try:
                fields = wrappers(form)
                for row in rows:
                    old = row["field"]
                    if row["action"]=="preserve_supported_extension":
                        if obj.fields().indexFromName(old)>=0:
                            assert old in fields, (key,old)
                            count+=1
                        continue
                    if version=="candidate":
                        assert old not in fields,(key,old)
                        new=row.get("target")
                        if new and obj.fields().indexFromName(new)>=0:
                            assert new in fields,(key,new,sorted(fields))
                            count+=1
                    else:
                        # Baseline must not silently be treated as repaired.
                        new=row.get("target")
                        if new and obj.fields().indexFromName(new)>=0:
                            print("BASELINE_FORM_TARGET",key,old,new,new in fields,flush=True)
                if version=="candidate" and lid.startswith("mvw_tww_channel_"):
                    for name in ("_from_ne","_to_ne"):
                        assert obj.editFormConfig().readOnly(obj.fields().indexFromName(name))
                        assert name in fields
            finally:
                form.close()
                form.deleteLater()
                app.processEvents()
        finally:
            if manager.currentStyle()!=oldstyle:
                assert manager.setCurrentStyle(oldstyle),key
    print("GUI_FORM_BINDINGS_VERIFIED",count,flush=True)

record("C2_C5_open_native_forms",check_forms)
try:
    ws,wn,log,cat,ov=fixture()
except Exception:
    db.rollback()
    traceback.print_exc()
    raise

target = layer("vw_tww_catchment_area_totals_fccd22f0_6775_46cf_8065_a8ecd98f82b3")
overflow = layer("vw_tww_overflow_019e62f3_992b_4fbb_8b5a_7fd3e2b7b223")
labels = dict(sql("SELECT code,value_en FROM tww_vl.hydraulic_char_data_status WHERE code IN (6372,6373,6371)",fetch=True))
assert set(labels)=={6372,6373,6371}

def check_default_constraints():
    target.reload()
    f = feature(target,cat)
    assert f["wn_obj_id"]==wn and f["fk_log_card"]==log, f.attributes()
    assert target.startEditing()
    form = form_for(target,f)
    try:
        for p,code in (("hc_c_",6372),("hc_o_",6373),("hc_p_",6371)):
            default = target.defaultValueDefinition(target.fields().indexFromName(p+"identifier"))
            if version=="candidate":
                result=evaluate(target,f,default.expression())
                assert result==(prefix+"-"+labels[code])[:20],(p,result)
                print("REAL_DB_DEFAULT",p,result,flush=True)
            else:
                try:
                    result=evaluate(target,f,default.expression())
                except AssertionError as exc:
                    print("BASELINE_DEFAULT_FAILURE",p,str(exc),flush=True)
                else:
                    raise AssertionError(("baseline default unexpectedly evaluated",p,result))
            minimum=p+"pump_flow_min";maximum=p+"pump_flow_max"
            wrapper=form_field(form,minimum)
            strength=target.fields()[target.fields().indexFromName(minimum)].constraints().constraintStrength(QgsFieldConstraints.ConstraintExpression)
            assert strength==QgsFieldConstraints.ConstraintStrengthSoft,(p,strength)
            for lo,hi,expected in ((20,10,False),(5,10,True),(10,10,True),(5,None,True)):
                change(form,maximum,hi);change(form,minimum,lo)
                current=form.currentFormFeature()
                assert float(current[minimum])==lo,(p,current[minimum],lo)
                # Re-evaluate widget constraint against the complete live form.
                wrapper.updateConstraint(current)
                valid=wrapper.isValidConstraint()
                print("GUI_CONSTRAINT",p,lo,hi,valid,wrapper.constraintFailureReason(),flush=True)
                if version=="candidate":
                    assert valid==expected,(p,lo,hi,valid)
                    if not expected:
                        assert wrapper.constraintResult()==QgsEditorWidgetWrapper.ConstraintResultFailSoft
    finally:
        form.close();form.deleteLater();app.processEvents()
        rollback_layer(target)

record("C3_C4_real_data_and_gui_warnings",check_default_constraints)

def check_pump_write():
    overflow.reload()
    m=overflow.styleManager()
    old=m.currentStyle()
    if variant=="agxx":
        assert m.setCurrentStyle("AG-64/96")
    try:
        assert overflow.startEditing()
        f=feature(overflow,ov)
        form=form_for(overflow,f)
        try:
            name="pu_pump_flow_min_single"
            if version=="baseline" and variant=="agxx":
                print("BASELINE_PUMP_WIDGET",name,name in wrappers(form),flush=True)
                if name not in wrappers(form):
                    rollback_layer(overflow)
                    return
            form_field(form,name)
            change(form,name,6)
            assert form.save(), "QGIS attribute form save failed"
            commit_layer(overflow)
            assert float(scalar("SELECT pump_flow_min_single FROM tww_od.pump WHERE obj_id=%s",(ov,)))==6
            db.commit()
            print("PUMP_COMMIT_READBACK",6,flush=True)
        finally:
            form.close();form.deleteLater();app.processEvents()
        assert overflow.startEditing()
        form=form_for(overflow,feature(overflow,ov))
        try:
            change(form,name,8)
            assert form.save()
            rollback_layer(overflow)
            assert float(scalar("SELECT pump_flow_min_single FROM tww_od.pump WHERE obj_id=%s",(ov,)))==6
            db.commit()
            print("PUMP_ROLLBACK_READBACK",6,flush=True)
        finally:
            form.close();form.deleteLater();app.processEvents()
    finally:
        if overflow.isEditable():overflow.rollBack()
        if m.currentStyle()!=old:m.setCurrentStyle(old)

record("C2_C5_pump_form_commit_and_rollback",check_pump_write)

def check_catchment_write():
    # Save via the unmodified application's view and INSTEAD OF triggers.
    # Never substitute a direct table write for an unsuccessful view write.
    target.reload()
    assert target.startEditing()
    form=form_for(target,feature(target,cat))
    try:
        for p,code in (("hc_c_",6372),("hc_o_",6373),("hc_p_",6371)):
            change(form,p+"pump_flow_min",6)
            if version=="candidate":
                actual=form.currentFormFeature()[p+"identifier"]
                expected=(prefix+"-"+labels[code])[:20]
                assert actual==expected,(p,actual,expected)
        assert form.save(), "QGIS catchment form save failed"
        commit_layer(target)
        rows=sql("SELECT status,identifier,pump_flow_min FROM tww_od.hydraulic_char_data WHERE fk_wastewater_node=%s ORDER BY status",(wn,),True)
        assert len(rows)==3,rows
        for code,name,flow in rows:
            assert float(flow)==6,(code,name,flow)
            if version=="candidate":
                assert name==(prefix+"-"+labels[code])[:20],(code,name)
        db.commit()
        print("CATCHMENT_COMMIT_READBACK",rows,flush=True)
    finally:
        form.close();form.deleteLater();app.processEvents()
        if target.isEditable():target.rollBack()
    assert target.startEditing()
    form=form_for(target,feature(target,cat))
    try:
        change(form,"hc_c_pump_flow_min",8)
        assert form.save()
        rollback_layer(target)
        assert float(scalar("SELECT pump_flow_min FROM tww_od.hydraulic_char_data WHERE obj_id=%s",(prefix+"C",)))==6
        db.commit()
        print("CATCHMENT_ROLLBACK_READBACK",6,flush=True)
    finally:
        form.close();form.deleteLater();app.processEvents()
        if target.isEditable():target.rollBack()

record("C3_C4_catchment_form_commit_and_rollback",check_catchment_write)
db.close()
print("GUI_DB_RESULTS",json.dumps(results),flush=True)
assert not errors,errors
print("GUI_DB_COMPLETE_PASS",version,variant,flush=True)
