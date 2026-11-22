"""SWMM numerical comparison: complete selected subnetwork vs extra unselected nodes.

Uses exact unmodified upstream TwwSwmm method, PostgreSQL view fixtures, EPA SWMM
solver and actual output flow time series. Not official municipal dataset.
"""
import sys
import tempfile
import unittest
from pathlib import Path

import psycopg
from swmm.toolkit import solver
from swmm.toolkit.shared_enum import LinkAttribute
from pyswmm import Output

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_swmm_engine_scope import EngineScope, SWMM, DSN, SQL_SUFFIX

class HydraulicScopeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EngineScope.setUpClass()
    def simulate_flow(self, structures, reaches):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"test.inp"
            obj=SWMM()
            obj.title="Hydraulic comparison"
            obj.state="current"
            obj.input_file=str(p)
            obj.con=psycopg.connect(DSN,autocommit=True)
            obj.copy_parameters_from_template=lambda name: (SQL_SUFFIX+"\n[DWF]\nN1 FLOW 0.02\n") if name=="OPTIONS" else ""
            obj.feedback_set_progress=lambda _:None
            obj.feedback_push=lambda *_:None
            try:
                obj.write_input(None if structures is not None else "primary",structures,reaches)
            finally:
                obj.con.close()
            solver.swmm_run(str(p),str(Path(td)/"test.rpt"),str(Path(td)/"test.out"))
            with Output(str(Path(td)/"test.out")) as model:
                flows=list(model.link_series("R1", LinkAttribute.FLOW_RATE).values())
            self.assertGreater(len(flows),0)
            print("FLOW_SCENARIO",structures,reaches,"count",len(flows),"min",min(flows),"max",max(flows),flush=True)
            return flows
    def test_unrelated_nodes_do_not_silently_change_flow_in_selected_reach(self):
        full=self.simulate_flow(None,None)
        selected=self.simulate_flow(["N1","O1"],["R1"])
        reach_only=self.simulate_flow([],["R1"])
        self.assertGreater(max(abs(f) for f in selected),0,"No meaningful hydraulic flow generated")
        self.assertEqual(len(full),len(selected))
        self.assertEqual(len(full),len(reach_only))
        self.assertLessEqual(max(abs(a-b) for a,b in zip(full,selected)),1e-6)
        self.assertLessEqual(max(abs(a-b) for a,b in zip(full,reach_only)),1e-6)
        print("HYDRAULIC_PARITY_CHECK_PASS",flush=True)

if __name__=="__main__":
    unittest.main(verbosity=2)
