"""Full official TEKSI PUM reach-row writeback integration, using an EPA SWMM report.

Runner executes after the actual upstream QGIS/INTERLIS import has added a
reach to a fresh PUM-installed official PostGIS database. Test the exact
upstream TwwSwmm methods, not a reimplementation, in red and green phases.
"""
import ast
import codecs
import os
from pathlib import Path
import tempfile
import unittest

import psycopg
from swmm.toolkit import solver

UPSTREAM = Path(__file__).resolve().parents[2] / "upstream"
SOURCE = UPSTREAM / "plugin/teksi_wastewater/processing_provider/TwwSwmm.py"
DSN = os.environ["OFFICIAL_TEST_DATABASE_URL"]
BASELINE = os.environ.get("EXPECT_BASELINE_FAILURE") == "1"

def original_importer():
    tree = ast.parse(SOURCE.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TwwSwmm")
    wanted = {
        "extract_summary_lines", "extract_link_flow_summary",
        "convert_max_over_full_flow", "populate_attribute", "import_hydraulic_load",
    }
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    assert len(methods) == len(wanted)
    node = ast.ClassDef(
        name="OriginalImporter", bases=[], keywords=[], body=methods,
        decorator_list=[],
    )
    ast.fix_missing_locations(node)
    namespace = {"codecs": codecs, "psycopg": psycopg}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace["OriginalImporter"]

class OfficialPostgisWriteback(unittest.TestCase):
    def test_original_importer_writes_official_reach(self):
        with psycopg.connect(DSN, autocommit=True) as db:
            row = db.execute(
                "SELECT obj_id FROM tww_od.reach ORDER BY obj_id LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(row, "Official XTF has no imported reach")
            reach_id = row[0]
            col = db.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='tww_od' AND table_name='reach' "
                "AND column_name IN ('hydraulic_load_current', "
                "'dss2020_hydraulic_load_current')"
            ).fetchall()
            self.assertEqual([r[0] for r in col], ["hydraulic_load_current"])

        with tempfile.TemporaryDirectory() as directory:
            inp = Path(directory) / "model.inp"
            rpt = Path(directory) / "model.rpt"
            inp.write_text(
                "[TITLE]\nOfficial TEKSI reach import test\n"
                "[OPTIONS]\nFLOW_UNITS CMS\nINFILTRATION HORTON\n"
                "FLOW_ROUTING KINWAVE\n"
                "START_DATE 01/01/2020\nEND_DATE 01/01/2020\n"
                "START_TIME 00:00:00\nEND_TIME 01:30:00\n"
                "REPORT_START_DATE 01/01/2020\nREPORT_START_TIME 00:00:00\n"
                "WET_STEP 00:15:00\nDRY_STEP 01:00:00\n"
                "REPORT_STEP 00:15:00\nROUTING_STEP 00:00:30\n"
                "[JUNCTIONS]\nN1 10 2 0 0 0\n"
                "[OUTFALLS]\nO1 9 FREE 0 NO 0\n"
                "[CONDUITS]\n" + reach_id + " N1 O1 10 0.013 0 0 0 0\n"
                "[XSECTIONS]\n" + reach_id + " CIRCULAR 0.5 0 0 0 1\n"
                "[DWF]\nN1 FLOW 0.02\n"
                "[REPORT]\nINPUT YES\nNODES ALL\nLINKS ALL\n"
            )
            solver.swmm_run(str(inp), str(rpt), str(Path(directory) / "model.out"))

            original = original_importer()()
            original.rpt_file = str(rpt)
            original.con = psycopg.connect(DSN)
            messages = []
            original.feedback_push = lambda level, message: messages.append((level, message))
            original.feedback_set_progress = lambda _: None
            try:
                rows = original.extract_link_flow_summary()
                expected_row = next(r for r in rows if r["id"] == reach_id)
                expected_pct = round(float(expected_row["max_over_full_flow"]) * 100)
                self.assertGreater(expected_pct, 0, expected_row)
                self.assertLess(expected_pct, 100, expected_row)
                original.import_hydraulic_load()
                error_messages = [msg for level, msg in messages if level == "error"]

                # Read in same transaction because original code only commits on success.
                actual = None
                if not original.con.info.transaction_status.name == "INERROR":
                    actual = original.con.execute(
                        "SELECT hydraulic_load_current FROM tww_od.reach "
                        "WHERE obj_id = %s", (reach_id,),
                    ).fetchone()[0]
                print(
                    f"OFFICIAL_REACH_ID={reach_id} "
                    f"SWMM_RATIO={expected_row['max_over_full_flow']} "
                    f"EXPECTED_PCT={expected_pct} ACTUAL_DB_PCT={actual} "
                    f"IMPORT_ERRORS={error_messages}",
                    flush=True,
                )
                if BASELINE:
                    self.assertTrue(error_messages, "Old code unexpectedly succeeded")
                    self.assertIsNone(actual)
                else:
                    self.assertFalse(error_messages)
                    self.assertEqual(actual, expected_pct)
            finally:
                original.con.close()

if __name__ == "__main__":
    unittest.main(verbosity=2)
