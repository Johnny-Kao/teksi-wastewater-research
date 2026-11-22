"""Use a genuine EPA SWMM 5.2.4 .rpt to validate original TEKSI summary parsing.

This test exercises original upstream extract_summary_lines,
extract_link_flow_summary and convert_max_over_full_flow against the actual
report output of a SWMM simulation with valid synthetic PostgreSQL view rows.
"""
import ast
import tempfile
import unittest
from pathlib import Path

from swmm.toolkit import solver

from test_swmm_engine_scope import EngineScope, SWMM, DSN, SQL_SUFFIX

import psycopg

SOURCE=Path(__file__).resolve().parents[1]/"upstream/plugin/teksi_wastewater/processing_provider/TwwSwmm.py"
tree=ast.parse(SOURCE.read_text())
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=="TwwSwmm")
funcs=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in {
    "extract_summary_lines","extract_link_flow_summary","convert_max_over_full_flow"}]
wrapper=ast.ClassDef(name="Report",bases=[],keywords=[],body=funcs,decorator_list=[])
ast.fix_missing_locations(wrapper)
env={"codecs":__import__("codecs")}
exec(compile(ast.Module(body=[wrapper],type_ignores=[]),str(SOURCE),"exec"),env)
Report=env["Report"]

class RealReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EngineScope.setUpClass()
    def test_true_swmm_link_flow_report_rounding(self):
        with tempfile.TemporaryDirectory() as d:
            inp=Path(d)/"swmm.inp"
            rpt=Path(d)/"swmm.rpt"
            obj=SWMM()
            obj.title="SWMM actual report research"
            obj.state="current"
            obj.input_file=str(inp)
            obj.con=psycopg.connect(DSN,autocommit=True)
            obj.copy_parameters_from_template=lambda section: (SQL_SUFFIX+"\n[DWF]\nN1 FLOW 0.02\n") if section=="OPTIONS" else ""
            obj.feedback_set_progress=lambda _:None
            obj.feedback_push=lambda *_:None
            obj.write_input("primary",None,None)
            obj.con.close()
            solver.swmm_run(str(inp),str(rpt),str(Path(d)/"swmm.out"))
            report=Report()
            report.rpt_file=str(rpt)
            rows=report.extract_link_flow_summary()
            print("ACTUAL_SWMM_LINK_SUMMARY",rows,flush=True)
            conduits=[r for r in rows if r.get("type")=="CONDUIT" and r["id"]=="R1"]
            self.assertEqual(len(conduits),1, rows)
            flow=float(conduits[0]["max_over_full_flow"])
            print("ACTUAL_SWMM_MAX_FULL_FLOW_RATIO",flow,flush=True)
            self.assertGreater(flow,0)
            self.assertLess(flow,0.5, "Fixture should be a partially loaded conduit")
            result=report.convert_max_over_full_flow(conduits)
            actual=result[0]["max_over_full_flow"]
            intended=round(flow*100)
            print("ACTUAL_TE KSI_WRITTEN_PERCENT".replace(" ",""), actual,"EXPECTED",intended,flush=True)
            self.assertEqual(actual,0)
            self.assertGreater(intended,0)

if __name__=="__main__":
    unittest.main(verbosity=2)
