"""Regression probe for actual upstream SWMM Max/Full Flow -> hydraulic load conversion.

Uses upstream TwwSwmm.convert_max_over_full_flow unchanged, no source edits.
"""
import ast
import unittest
from pathlib import Path

SOURCE=Path(__file__).resolve().parents[1]/"upstream/plugin/teksi_wastewater/processing_provider/TwwSwmm.py"
source=ast.parse(SOURCE.read_text())
klass=next(n for n in source.body if isinstance(n,ast.ClassDef) and n.name=="TwwSwmm")
func=next(n for n in klass.body if isinstance(n,ast.FunctionDef) and n.name=="convert_max_over_full_flow")
cl=ast.ClassDef(name="Original",bases=[],keywords=[],body=[func],decorator_list=[])
ast.fix_missing_locations(cl)
scope={}
exec(compile(ast.Module(body=[cl],type_ignores=[]),str(SOURCE),"exec"),scope)
original=scope["Original"]()

class HydraulicLoadConversion(unittest.TestCase):
    def test_fractional_values_quantized_before_percentage(self):
        rows=[{"max_over_full_flow": x} for x in ("0.01","0.20","0.40","0.60","0.80","0.99","1.25")]
        converted=original.convert_max_over_full_flow(rows)
        observed=[row["max_over_full_flow"] for row in converted]
        expected=[1,20,40,60,80,99,125]
        print("SWMM_MAX_FULL_INPUTS",["0.01","0.20","0.40","0.60","0.80","0.99","1.25"])
        print("UPSTREAM_PERCENT_OUTPUTS",observed)
        print("EXPECTED_PERCENT_OUTPUTS",expected)
        self.assertEqual(observed,[0,0,0,100,100,100,100])
        self.assertNotEqual(observed,expected)
    def test_function_used_in_actual_writeback_path(self):
        methods={n.name:n for n in klass.body if isinstance(n,ast.FunctionDef)}
        assert "import_hydraulic_load" in methods
        calls=[(x.func.attr if isinstance(x.func,ast.Attribute) else None) for x in ast.walk(methods["import_hydraulic_load"]) if isinstance(x,ast.Call)]
        self.assertIn("convert_max_over_full_flow",calls)
        self.assertIn("populate_attribute",calls)
        print("CALL_CHAIN_CONFIRMED",calls)

if __name__=="__main__":
    unittest.main(verbosity=2)
