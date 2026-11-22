"""Execute original TEKSI SWMM exporter against modeled SQL views then EPA SWMM solver.

This test is a real simulator validation of export selection behavior; the SQL
views are minimal synthetic fixtures representing two independent valid networks.
"""
import ast
import codecs
import os
import re
import tempfile
from pathlib import Path
import unittest
import psycopg
from swmm.toolkit import solver

UPSTREAM=Path(__file__).resolve().parents[1]/"upstream/plugin/teksi_wastewater/processing_provider/TwwSwmm.py"
DSN=os.environ["TEST_DATABASE_URL"]
SQL_SUFFIX=(
  "\n[OPTIONS]\nFLOW_UNITS CMS\nINFILTRATION HORTON\nFLOW_ROUTING KINWAVE\n"
  "START_DATE 01/01/2020\nSTART_TIME 00:00:00\nEND_DATE 01/01/2020\n"
  "END_TIME 01:30:00\nREPORT_START_DATE 01/01/2020\nREPORT_START_TIME 00:00:00\n"
  "WET_STEP 00:15:00\nDRY_STEP 01:00:00\nREPORT_STEP 00:15:00\nROUTING_STEP 00:00:30\n"
  "\n[REPORT]\nINPUT YES\nNODES ALL\nLINKS ALL\n"
)
def get_original():
    tree=ast.parse(UPSTREAM.read_text())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=="TwwSwmm")
    methods=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in ("get_swmm_table","swmm_table","write_input")]
    cl=ast.ClassDef(name="RealSWMM",bases=[],keywords=[],body=methods,decorator_list=[])
    ast.fix_missing_locations(cl)
    d={"codecs":codecs,"psycopg":psycopg}
    exec(compile(ast.Module(body=[cl],type_ignores=[]),str(UPSTREAM),"exec"),d)
    return d["RealSWMM"]

SWMM=get_original()
SECTIONS=set(re.findall(r'self\.swmm_table\("([A-Z_]+)"',UPSTREAM.read_text()))
SCHEMAS={
    "JUNCTIONS":'"Name" text, "InvertElev" float, "MaxDepth" float, "InitDepth" float, "SurchargeDepth" float, "PondedArea" float',
    "OUTFALLS":'"Name" text, "InvertElev" float, "Type" text, "Gated" text',
    "CONDUITS":'"Name" text, "FromNode" text, "ToNode" text, "Length" float, "Roughness" float, "InletOffset" float, "OutletOffset" float, "InitFlow" float, "MaxFlow" float',
    "XSECTIONS":'"Link" text, "Shape" text, "Geom1" float, "Geom2" float, "Geom3" float, "Geom4" float, "Barrels" integer',
    "COORDINATES":'"Node" text, "XCoord" float, "YCoord" float',
}
BASE='"obj_id" text, "state" text, "hierarchy" text'
TABLE_DATA={
  "JUNCTIONS":[("N1",10.,2.,0.,0.,0.,"N1"),("N2",10.,2.,0.,0.,0.,"N2")],
  "OUTFALLS":[("O1",9.,"FREE","NO","O1"),("O2",9.,"FREE","NO","O2")],
  "CONDUITS":[("R1","N1","O1",10.,0.013,0.,0.,0.,0.,"R1"),("R2","N2","O2",10.,0.013,0.,0.,0.,0.,"R2")],
  "XSECTIONS":[("R1","CIRCULAR",0.5,0.,0.,0.,1,"R1"),("R2","CIRCULAR",0.5,0.,0.,0.,1,"R2")],
  "COORDINATES":[("N1",0.,0.,"N1"),("O1",10.,0.,"O1"),("N2",0.,10.,"N2"),("O2",10.,10.,"O2")],
}
class EngineScope(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with psycopg.connect(DSN,autocommit=True) as db:
            db.execute("CREATE SCHEMA IF NOT EXISTS tww_app")
            for s in sorted(SECTIONS):
                name=f'tww_app.swmm_vw_{s.lower()}'
                db.execute(f"DROP TABLE IF EXISTS {name}")
                cols=SCHEMAS.get(s,'"Name" text')
                db.execute(f"CREATE TABLE {name} ({cols}, {BASE})")
                for row in TABLE_DATA.get(s,[]):
                    placeholders=",".join(["%s"]*(len(row)+2))
                    db.execute(f"INSERT INTO {name} VALUES ({placeholders})",(*row,"current","primary"))
    def simulate(self,structs,reaches):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"model.inp"
            sw=SWMM()
            sw.title="Network scope research"
            sw.state="current"
            sw.input_file=str(p)
            sw.con=psycopg.connect(DSN,autocommit=True)
            sw.copy_parameters_from_template=lambda section: SQL_SUFFIX if section=="OPTIONS" else ""
            sw.feedback_set_progress=lambda _:None
            sw.feedback_push=lambda *args:None
            try:
                sw.write_input(None if structs is not None else "primary",structs,reaches)
            finally:
                sw.con.close()
            text=p.read_text()
            try:
                solver.swmm_run(str(p),str(Path(td)/"model.rpt"),str(Path(td)/"model.out"))
                status="success"
            except Exception as e:
                status=f"{type(e).__name__}: {e}"
            report=Path(td)/"model.rpt"
            report_text=report.read_text(errors="replace") if report.exists() else ""
            print("SCOPE",str(structs),str(reaches),"STATUS",status)
            print("ERROR_REPORT", "\n".join(x for x in report_text.splitlines() if "ERROR" in x or "WARNING" in x)[:1200])
            return status,text,report_text
    def test_control_whole_valid_two_networks(self):
        status,_,report=self.simulate(None,None)
        self.assertEqual(status,"success",report[-1200:])
        self.assertNotIn("ERROR",report)
    def test_select_first_network_structure_only_exposes_missing_unselected_outfall(self):
        status,text,report=self.simulate(["N1","O1"],[])
        self.assertIn("R2",text)
        self.assertNotIn("O2",self.section(text,"OUTFALLS"))
        self.assertIn("O2",self.section(text,"CONDUITS"))
        self.assertIn("ERROR",report, (status, report[-1200:]))
    @staticmethod
    def section(text, name):
        m=re.search(rf"(?ms)^\[{name}\]\n(.*?)(?=^\[[A-Z_]+\]\n|\Z)",text)
        return m.group(1) if m else ""

if __name__=="__main__":
    unittest.main(verbosity=2)
