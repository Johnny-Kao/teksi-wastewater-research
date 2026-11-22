"""Regression: genuine SWMM report -> actual TEKSI importer -> PostgreSQL writeback.

The methods are compiled *unchanged* from the checked-out upstream
TwwSwmm.py, avoiding the QGIS dependency. The isolated PostgreSQL fixture
matches the official PUM 'reach.hydraulic_load_current smallint' contract.
"""
import ast
import codecs
import tempfile
import unittest
from pathlib import Path

import psycopg
from swmm.toolkit import solver
from test_swmm_engine_scope import EngineScope, SWMM, DSN, SQL_SUFFIX

SRC = Path(__file__).resolve().parents[1] / "upstream/plugin/teksi_wastewater/processing_provider/TwwSwmm.py"
TREE = ast.parse(SRC.read_text())
CLASS = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == "TwwSwmm")
METHODS = {
    "extract_summary_lines", "extract_link_flow_summary",
    "convert_max_over_full_flow", "import_hydraulic_load", "populate_attribute",
}
NODE = ast.ClassDef(
    name="OriginalImporter", bases=[], keywords=[],
    body=[n for n in CLASS.body if isinstance(n, ast.FunctionDef) and n.name in METHODS],
    decorator_list=[],
)
assert len(NODE.body) == len(METHODS)
ast.fix_missing_locations(NODE)
env = {"codecs": codecs, "psycopg": psycopg}
exec(compile(ast.Module(body=[NODE], type_ignores=[]), str(SRC), "exec"), env)
Importer = env["OriginalImporter"]


class HydraulicLoadWriteback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EngineScope.setUpClass()
        with psycopg.connect(DSN, autocommit=True) as con:
            con.execute("CREATE SCHEMA IF NOT EXISTS tww_od")
            con.execute("DROP TABLE IF EXISTS tww_od.reach")
            con.execute(
                "CREATE TABLE tww_od.reach (obj_id text PRIMARY KEY, "
                "hydraulic_load_current smallint)"
            )
            con.execute(
                "INSERT INTO tww_od.reach (obj_id, hydraulic_load_current) "
                "VALUES ('R1', NULL)"
            )

    def test_real_swmm_report_written_as_correct_percentage(self):
        with tempfile.TemporaryDirectory() as td:
            inp, rpt = Path(td) / "model.inp", Path(td) / "model.rpt"
            export = SWMM()
            export.title = "Hydraulic load integration"
            export.state = "current"
            export.input_file = str(inp)
            export.con = psycopg.connect(DSN, autocommit=True)
            export.copy_parameters_from_template = (
                lambda section: SQL_SUFFIX + "\n[DWF]\nN1 FLOW 0.02\n"
                if section == "OPTIONS" else ""
            )
            export.feedback_push = lambda *_: None
            export.feedback_set_progress = lambda *_: None
            try:
                export.write_input("primary", None, None)
            finally:
                export.con.close()

            solver.swmm_run(str(inp), str(rpt), str(Path(td) / "model.out"))
            importer = Importer()
            importer.rpt_file = str(rpt)
            importer.con = psycopg.connect(DSN)  # transactional, matching TEKSI
            errors = []
            importer.feedback_push = lambda level, msg: errors.append((level, msg))
            importer.feedback_set_progress = lambda _: None
            try:
                parsed = importer.extract_link_flow_summary()
                r1 = next(row for row in parsed if row["id"] == "R1")
                expected = round(float(r1["max_over_full_flow"]) * 100)
                self.assertEqual(expected, 2, r1)
                importer.import_hydraulic_load()
                self.assertFalse(
                    [msg for level, msg in errors if level == "error"],
                    errors,
                )
                with psycopg.connect(DSN, autocommit=True) as check:
                    actual = check.execute(
                        "SELECT hydraulic_load_current FROM tww_od.reach "
                        "WHERE obj_id = 'R1'"
                    ).fetchone()[0]
                print(
                    f"REAL_SWMM_MAX_FULL_RATIO={r1['max_over_full_flow']} "
                    f"EXPECTED_PERCENT={expected} DB_PERCENT={actual}",
                    flush=True,
                )
                self.assertEqual(actual, expected)
            finally:
                importer.con.close()

    def test_rounding_boundaries(self):
        importer = Importer()
        values = ["0.02", "0.20", "0.40", "0.60", "0.80", "0.99", "1.25"]
        rows = [{"max_over_full_flow": value} for value in values]
        actual = [row["max_over_full_flow"] for row in
                  importer.convert_max_over_full_flow(rows)]
        self.assertEqual(actual, [2, 20, 40, 60, 80, 99, 125])


if __name__ == "__main__":
    unittest.main(verbosity=2)
