#!/usr/bin/env python3
"""Fault injection into the exact upstream interlis_import orchestration code.

This is a control-flow integration test with real PostgreSQL state and synthetic
dependencies. It does NOT install QGIS or a full TEKSI production database.
"""
import ast
import logging
import os
import textwrap
import unittest
from pathlib import Path
import psycopg

DSN=os.environ["TEST_DATABASE_URL"]
SOURCE=Path(__file__).resolve().parents[1]/"upstream/plugin/teksi_wastewater/interlis/interlis_importer_exporter.py"

class Config:
    MODEL_NAME_SIA405_BASE_ABWASSER="BASE"
    MODEL_NAME_VSA_KEK="KEK"
    MODEL_NAME_SIA405_ABWASSER="SIA"
    MODEL_NAME_DSS="DSS"
    MODEL_NAME_AG96="AG96"
    MODEL_NAME_AG64="AG64"

class InterlisImporterExporterError(Exception): pass
class InterlisImporterExporterStopped(Exception): pass

def read_upstream_methods():
    source=SOURCE.read_text()
    tree=ast.parse(source)
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=="InterlisImporterExporter")
    needed=["interlis_import","_import_disable_symbology_and_modification_triggers","_import_enable_symbology_and_modification_triggers"]
    methods=[n for n in cls.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in needed]
    assert len(methods)==len(needed)
    classdef=ast.ClassDef(name="UpstreamImport",bases=[],keywords=[],body=methods,decorator_list=[])
    ast.fix_missing_locations(classdef)
    ns={
        "config":Config,
        "logger":logging.getLogger("fault-injection"),
        "InterlisImporterExporterError":InterlisImporterExporterError,
        "InterlisImporterExporterStopped":InterlisImporterExporterStopped,
    }
    return ns,classdef

class DBUtils:
    inject_disable_modification_failure=False
    @staticmethod
    def update(column,value):
        with psycopg.connect(DSN,autocommit=True) as conn:
            conn.execute(f"UPDATE import_trigger_state SET {column} = %s WHERE id=1",(value,))
    @classmethod
    def disable_symbology_triggers(cls): cls.update("symbology_enabled",False)
    @classmethod
    def disable_modification_triggers(cls):
        if cls.inject_disable_modification_failure:
            raise PermissionError("simulated second disable failed")
        cls.update("modification_enabled",False)
    @classmethod
    def enable_symbology_triggers(cls): cls.update("symbology_enabled",True)
    @classmethod
    def update_symbology(cls): pass
    @classmethod
    def enable_modification_triggers(cls): cls.update("modification_enabled",True)

ns, cls=read_upstream_methods()
ns["DatabaseUtils"]=DBUtils
exec(compile(ast.Module(body=[cls],type_ignores=[]),str(SOURCE),"exec"),ns)
UpstreamImport=ns["UpstreamImport"]

def make_import(fail_after_write=False):
    obj=UpstreamImport()
    obj.base_log_path=None
    obj.interlisTools=type("Tools",(),{"get_xtf_models":lambda self, filename:["DSS"]})()
    obj._progress_done=lambda *a,**kw:None
    obj._import_validate_xtf_file=lambda *a:None
    obj._clear_ili_schema=lambda **kw:None
    obj._create_ili_schema=lambda *a,**kw:None
    obj._import_xtf_file=lambda **kw:None
    def next_phase(*args):
        if fail_after_write: raise RuntimeError("simulated failure after trigger disable")
        raise RuntimeError("stop to avoid further stubbed stages")
    obj._import_from_intermediate_schema=next_phase
    return obj

class ImportTriggerState(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with psycopg.connect(DSN,autocommit=True) as db:
            db.execute("CREATE TABLE IF NOT EXISTS import_trigger_state (id int PRIMARY KEY,symbology_enabled bool,modification_enabled bool)")
    def setUp(self):
        DBUtils.inject_disable_modification_failure=False
        with psycopg.connect(DSN,autocommit=True) as db:
            db.execute("TRUNCATE import_trigger_state")
            db.execute("INSERT INTO import_trigger_state VALUES (1,true,true)")
    def flags(self):
        with psycopg.connect(DSN,autocommit=True) as db:
            return db.execute("SELECT symbology_enabled,modification_enabled FROM import_trigger_state WHERE id=1").fetchone()
    def test_original_import_exception_on_second_trigger_disable_leaves_first_disabled(self):
        DBUtils.inject_disable_modification_failure=True
        with self.assertRaises(PermissionError):
            make_import().interlis_import("synthetic.xtf")
        self.assertEqual(self.flags(),(False,True))
    def test_original_import_exception_inside_try_restores_both_triggers(self):
        with self.assertRaises(RuntimeError):
            make_import(fail_after_write=True).interlis_import("synthetic.xtf")
        self.assertEqual(self.flags(),(True,True))

if __name__=="__main__": unittest.main(verbosity=2)
