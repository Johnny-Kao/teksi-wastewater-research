"""Test exact upstream NetworkX graph construction with stub QGIS feature layers.

The SQL-generated reach-point vertex uniqueness contract is inspected separately.
"""
import ast
import collections
import unittest
from pathlib import Path
import networkx as nx

SOURCE = Path(__file__).resolve().parents[1] / "upstream/plugin/teksi_wastewater/tools/twwnetwork.py"


def original_class():
    tree = ast.parse(SOURCE.read_text())
    cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == "TwwGraphManager")
    wanted = {"_addEdges", "createGraph", "shortestPath"}
    funcs = [x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name in wanted]
    assert set(x.name for x in funcs) == wanted
    wrapped = ast.ClassDef(name="OriginalGraph", bases=[], keywords=[], body=funcs, decorator_list=[])
    ast.fix_missing_locations(wrapped)
    namespace = {"nx": nx, "defaultdict": collections.defaultdict}
    exec(compile(ast.Module(body=[wrapped], type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace["OriginalGraph"]


Original = original_class()


class Feature(dict):
    def __init__(self, feature_id, name, source, target, weight):
        super().__init__(obj_id=name, type="reach", from_obj_id=source,
                         to_obj_id=target, length_calc=weight)
        self.feature_id = feature_id

    def id(self):
        return self.feature_id


class Provider:
    def __init__(self, features):
        self.features = features

    def getFeatures(self):
        return iter(self.features)


class Layer:
    def __init__(self, features):
        self.provider = Provider(features)

    def dataProvider(self):
        return self.provider


def run_graph(features):
    graph = Original()
    graph.dirty = True
    graph.timings = []
    graph.edge_layer = Layer(features)
    graph._profile = lambda _name: None
    def seed_vertices():
        graph.vertexIds = {"A": 1, "B": 2, "C": 3, "D": 4}
        for key, n in graph.vertexIds.items():
            graph.graph.add_node(n, objId=key)
    graph._addVertices = seed_vertices
    graph.createGraph()
    return graph


class GraphTest(unittest.TestCase):
    def test_parallel_directed_edges_overwrite_feature_and_weight(self):
        # A source-edge precondition probe, NOT proof that normal SQL-generated
        # wastewater graph can have both edges between the same reach-point IDs.
        graph = run_graph([
            Feature(101, "short_reach", "A", "B", 2),
            Feature(102, "long_reach", "A", "B", 11),
        ])
        self.assertEqual(graph.graph.number_of_edges(), 1)
        self.assertEqual(graph.graph.edges[1, 2]["baseFeature"], "long_reach")
        self.assertEqual(graph.graph.edges[1, 2]["weight"], 11)
        path, edges = graph.shortestPath(1, 2)
        self.assertEqual(path, [1, 2])
        self.assertEqual(edges[0][2]["weight"], 11)

    def test_distinct_reach_point_vertices_keep_both_physical_parallel_routes(self):
        # More representative of the upstream network SQL: separate reach
        # points are distinct vertices for distinct physical reaches.
        graph = run_graph([
            Feature(101, "short_left", "A", "B", 2),
            Feature(102, "short_end", "B", "D", 2),
            Feature(103, "long_left", "A", "C", 11),
            Feature(104, "long_end", "C", "D", 11),
        ])
        self.assertEqual(graph.graph.number_of_edges(), 4)
        path, edges = graph.shortestPath(1, 4)
        self.assertEqual(path, [1, 2, 4])
        self.assertEqual(sum(edge["weight"] for _, _, edge in edges), 4)

    def test_fork_tracks_both_branches(self):
        graph = run_graph([
            Feature(1, "up_a", "A", "C", 1),
            Feature(2, "up_b", "B", "C", 1),
            Feature(3, "down", "C", "D", 1),
        ])
        self.assertEqual(set(graph.graph.predecessors(3)), {1, 2})
        self.assertEqual(graph.graph.number_of_edges(), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
