"""Production SQL behavior of pinned upstream TwwSwmm methods, with small PostgreSQL fixtures.

The export methods are compiled unmodified from upstream source. This is not a
full TEKSI database or SWMM-engine validation.
"""
import ast
import codecs
import os
import re
import tempfile
import unittest
from pathlib import Path
import psycopg

SOURCE = Path(__file__).resolve().parents[1] / "upstream/plugin/teksi_wastewater/processing_provider/TwwSwmm.py"
DSN = os.environ["TEST_DATABASE_URL"]


def make_class():
    module = ast.parse(SOURCE.read_text())
    original = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == "TwwSwmm")
    wanted = {"get_swmm_table", "swmm_table", "write_input"}
    funcs = [n for n in original.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    assert {n.name for n in funcs} == wanted
    wrapper = ast.ClassDef(name="OriginalTwwSwmm", bases=[], keywords=[], body=funcs, decorator_list=[])
    ast.fix_missing_locations(wrapper)
    globals_ = {"codecs": codecs, "psycopg": psycopg}
    exec(compile(ast.Module(body=[wrapper], type_ignores=[]), str(SOURCE), "exec"), globals_)
    return globals_["OriginalTwwSwmm"]


Original = make_class()
ALL_SECTIONS = set(re.findall(r'self\.swmm_table\("([A-Z_]+)"', SOURCE.read_text()))


class ExportSelectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with psycopg.connect(DSN, autocommit=True) as db:
            db.execute("CREATE SCHEMA IF NOT EXISTS tww_app")
            for section in sorted(ALL_SECTIONS):
                # Real upstream PostgreSQL SELECT logic, isolated view fixtures.
                db.execute(f"DROP TABLE IF EXISTS tww_app.swmm_vw_{section.lower()}")
                db.execute(
                    f'CREATE TABLE tww_app.swmm_vw_{section.lower()} '
                    '(Name text, FromNode text, ToNode text, obj_id text, state text, hierarchy text)'
                )
            for name, obj_id in [("NODE_SELECTED", "N_SELECTED"), ("NODE_OTHER", "N_OTHER")]:
                for section in ("junctions", "coordinates"):
                    db.execute(
                        f"INSERT INTO tww_app.swmm_vw_{section} "
                        "(Name, obj_id, state, hierarchy) VALUES (%s,%s,'current','primary')",
                        (name, obj_id),
                    )
            for name, obj_id, src, dest in [
                ("REACH_SELECTED", "R_SELECTED", "NODE_SELECTED", "NODE_SELECTED"),
                ("REACH_OTHER", "R_OTHER", "NODE_OTHER", "NODE_OTHER"),
            ]:
                db.execute(
                    "INSERT INTO tww_app.swmm_vw_conduits "
                    "(Name, FromNode, ToNode, obj_id, state, hierarchy) "
                    "VALUES (%s,%s,%s,%s,'current','primary')",
                    (name, src, dest, obj_id),
                )
            db.execute(
                "INSERT INTO tww_app.swmm_vw_tags (Name, obj_id, state, hierarchy) "
                "VALUES ('TAG_SELECTED','N_SELECTED','current','primary')"
            )

    def export(self, structures, reaches):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "export.inp"
            obj = Original()
            obj.con = psycopg.connect(DSN, autocommit=True)
            obj.title = "Research fixture"
            obj.input_file = str(target)
            obj.state = "current"
            obj.copy_parameters_from_template = lambda _key: ""
            obj.feedback_set_progress = lambda _p: None
            obj.feedback_push = lambda *_a: None
            try:
                obj.write_input(None, structures, reaches)
                return target.read_text()
            finally:
                obj.con.close()

    @staticmethod
    def section(text, name):
        match = re.search(rf"(?ms)^\[{name}\]\n(.*?)(?=^\[[A-Z_]+\]\n|\Z)", text)
        return match.group(1) if match else ""

    def test_only_reach_selected_unexpected_extra_junctions(self):
        inp = self.export([], ["R_SELECTED"])
        self.assertIn("REACH_SELECTED", self.section(inp, "CONDUITS"))
        self.assertNotIn("REACH_OTHER", self.section(inp, "CONDUITS"))
        # No selected structures -> selected_ws_re remains None -> no junction filtering
        self.assertIn("NODE_OTHER", self.section(inp, "JUNCTIONS"))
        self.assertIn("NODE_OTHER", self.section(inp, "COORDINATES"))

    def test_only_structure_selected_unexpected_unselected_conduits(self):
        inp = self.export(["N_SELECTED"], [])
        self.assertIn("NODE_OTHER", self.section(inp, "JUNCTIONS"))
        self.assertIn("REACH_OTHER", self.section(inp, "CONDUITS"))

    def test_both_selected_applies_combined_junction_filter(self):
        inp = self.export(["N_SELECTED"], ["R_SELECTED"])
        self.assertIn("NODE_SELECTED", self.section(inp, "JUNCTIONS"))
        self.assertNotIn("NODE_OTHER", self.section(inp, "JUNCTIONS"))
        self.assertIn("REACH_SELECTED", self.section(inp, "CONDUITS"))
        self.assertNotIn("REACH_OTHER", self.section(inp, "CONDUITS"))

    def test_original_tag_argument_order_excludes_matching_tag(self):
        inp = self.export(["N_SELECTED"], ["R_SELECTED"])
        # Real upstream calls swmm_table("TAGS", state, selected_ws_re):
        # hierarchy="current", state=["N_SELECTED","R_SELECTED"], selected=[].
        self.assertNotIn("TAG_SELECTED", self.section(inp, "TAGS"))

    def test_duplicate_losses_sections(self):
        inp = self.export(["N_SELECTED"], ["R_SELECTED"])
        self.assertEqual(inp.count("[LOSSES]\n"), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
