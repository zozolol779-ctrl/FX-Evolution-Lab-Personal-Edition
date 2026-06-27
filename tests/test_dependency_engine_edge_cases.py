"""Edge case tests for DependencyEngine."""
import os
import tempfile
import unittest

from fx_evolution_lab.session import AnalysisSession
from fx_evolution_lab.registry import ArtifactRegistry
from fx_evolution_lab.scanner import ScannerEngine
from fx_evolution_lab.manifest import ManifestEngine
from fx_evolution_lab.dependency_engine import DependencyEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _session_registry(tmpdir, run_id="run-dep-edge"):
    session = AnalysisSession(
        run_id=run_id,
        target_project=tmpdir,
        target_version="1.0",
        operator="tester",
        schema_version="1.0",
    )
    return session, ArtifactRegistry(session)


def _build(tmpdir, files: dict, run_id="run-dep-edge"):
    """Write files, scan, build manifest, return (engine, manifest)."""
    for rel, content in files.items():
        _write(os.path.join(tmpdir, rel), content)
    session, registry = _session_registry(tmpdir, run_id)
    scanner = ScannerEngine(tmpdir)
    manifest = ManifestEngine(session, registry).build(list(scanner.iter_files()))
    engine = DependencyEngine(session, registry)
    return engine, manifest


# ---------------------------------------------------------------------------
# analyze() backward-compat
# ---------------------------------------------------------------------------

class TestAnalyzeBackwardCompat(unittest.TestCase):

    def test_returns_dependency_artifact(self):
        session, registry = _session_registry("/tmp")
        engine = DependencyEngine(session, registry)
        result = engine.analyze("mod.a", "mod.b")
        self.assertEqual(result["artifact_type"], "dependency")

    def test_resolved_true_for_different_modules(self):
        session, registry = _session_registry("/tmp")
        engine = DependencyEngine(session, registry)
        result = engine.analyze("mod.a", "mod.b")
        self.assertTrue(result["resolved"])

    def test_resolved_false_same_module(self):
        session, registry = _session_registry("/tmp")
        engine = DependencyEngine(session, registry)
        result = engine.analyze("mod.a", "mod.a")
        self.assertFalse(result["resolved"])

    def test_resolved_false_empty_source(self):
        session, registry = _session_registry("/tmp")
        engine = DependencyEngine(session, registry)
        result = engine.analyze("", "mod.b")
        self.assertFalse(result["resolved"])

    def test_multiple_calls_unique_artifact_ids(self):
        session, registry = _session_registry("/tmp")
        engine = DependencyEngine(session, registry)
        r1 = engine.analyze("a", "b")
        r2 = engine.analyze("c", "d")
        self.assertNotEqual(r1["artifact_id"], r2["artifact_id"])


# ---------------------------------------------------------------------------
# build_graph() — artifact basics
# ---------------------------------------------------------------------------

class TestBuildGraphArtifact(unittest.TestCase):

    def test_returns_dependency_graph_artifact(self):
        with tempfile.TemporaryDirectory() as d:
            engine, manifest = _build(d, {"a.py": "x = 1\n"})
            graph = engine.build_graph(manifest)
            self.assertEqual(graph["artifact_type"], "dependency_graph")

    def test_required_keys_present(self):
        required = {"artifact_id", "artifact_type", "edges", "modules",
                    "cycle_detected", "cycles"}
        with tempfile.TemporaryDirectory() as d:
            engine, manifest = _build(d, {"a.py": "pass\n"})
            graph = engine.build_graph(manifest)
            for key in required:
                self.assertIn(key, graph, f"Missing key: {key}")

    def test_empty_project_no_crash(self):
        with tempfile.TemporaryDirectory() as d:
            engine, manifest = _build(d, {})
            graph = engine.build_graph(manifest)
            self.assertEqual(graph["edges"], {})
            self.assertEqual(graph["modules"], [])
            self.assertFalse(graph["cycle_detected"])


# ---------------------------------------------------------------------------
# build_graph() — edges / import resolution
# ---------------------------------------------------------------------------

class TestBuildGraphEdges(unittest.TestCase):

    def test_no_imports_empty_edges(self):
        with tempfile.TemporaryDirectory() as d:
            engine, manifest = _build(d, {"a.py": "x = 1\n", "b.py": "y = 2\n"})
            graph = engine.build_graph(manifest)
            for targets in graph["edges"].values():
                self.assertEqual(targets, [])

    def test_import_resolves_to_local_module(self):
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "utils.py"), "def helper(): pass\n")
            _write(os.path.join(d, "main.py"), "import utils\n")
            session, registry = _session_registry(d)
            scanner = ScannerEngine(d)
            manifest = ManifestEngine(session, registry).build(list(scanner.iter_files()))
            engine = DependencyEngine(session, registry)
            graph = engine.build_graph(manifest)
            # main.py imports utils.py
            main_edges = graph["edges"].get("main.py", [])
            self.assertIn("utils.py", main_edges,
                          f"Expected utils.py in main.py edges, got {main_edges}")

    def test_from_import_resolves_to_local_module(self):
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "helpers.py"), "def fn(): pass\n")
            _write(os.path.join(d, "app.py"), "from helpers import fn\n")
            session, registry = _session_registry(d)
            scanner = ScannerEngine(d)
            manifest = ManifestEngine(session, registry).build(list(scanner.iter_files()))
            engine = DependencyEngine(session, registry)
            graph = engine.build_graph(manifest)
            app_edges = graph["edges"].get("app.py", [])
            self.assertIn("helpers.py", app_edges,
                          f"Expected helpers.py in app.py edges, got {app_edges}")

    def test_stdlib_import_not_added_as_local_edge(self):
        """Importing 'os' or 'sys' must NOT produce a local edge."""
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "script.py"), "import os\nimport sys\n")
            session, registry = _session_registry(d)
            scanner = ScannerEngine(d)
            manifest = ManifestEngine(session, registry).build(list(scanner.iter_files()))
            engine = DependencyEngine(session, registry)
            graph = engine.build_graph(manifest)
            self.assertEqual(graph["edges"].get("script.py", []), [],
                             "stdlib imports must not produce local edges")

    def test_no_false_suffix_match(self):
        """import 'b' must NOT match local module 'src.ab' via endswith."""
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "src"), exist_ok=True)
            _write(os.path.join(d, "src", "ab.py"), "x = 1\n")
            _write(os.path.join(d, "main.py"), "import b\n")  # 'b' is external
            session, registry = _session_registry(d)
            scanner = ScannerEngine(d)
            manifest = ManifestEngine(session, registry).build(list(scanner.iter_files()))
            engine = DependencyEngine(session, registry)
            graph = engine.build_graph(manifest)
            main_edges = graph["edges"].get("main.py", [])
            self.assertNotIn("src/ab.py", main_edges,
                             f"'import b' must not match 'src/ab.py': {main_edges}")

    def test_no_false_suffix_match_web(self):
        """import 'web' must NOT match local module 'src.web' via endswith when src.web differs."""
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "src"), exist_ok=True)
            _write(os.path.join(d, "src", "web.py"), "x = 1\n")
            _write(os.path.join(d, "main.py"), "import web\n")  # external 'web'
            session, registry = _session_registry(d)
            scanner = ScannerEngine(d)
            manifest = ManifestEngine(session, registry).build(list(scanner.iter_files()))
            engine = DependencyEngine(session, registry)
            graph = engine.build_graph(manifest)
            main_edges = graph["edges"].get("main.py", [])
            # 'import web' should only match 'web.py' at root, not 'src/web.py'
            self.assertNotIn("src/web.py", main_edges,
                             f"'import web' must not match 'src/web.py': {main_edges}")

    def test_init_py_package_import(self):
        """import 'mypkg' must resolve to mypkg/__init__.py."""
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "mypkg"), exist_ok=True)
            _write(os.path.join(d, "mypkg", "__init__.py"), "VERSION = '1.0'\n")
            _write(os.path.join(d, "consumer.py"), "import mypkg\n")
            session, registry = _session_registry(d)
            scanner = ScannerEngine(d)
            manifest = ManifestEngine(session, registry).build(list(scanner.iter_files()))
            engine = DependencyEngine(session, registry)
            graph = engine.build_graph(manifest)
            consumer_edges = graph["edges"].get("consumer.py", [])
            self.assertIn("mypkg/__init__.py", consumer_edges,
                          f"'import mypkg' must resolve to mypkg/__init__.py: {consumer_edges}")

    def test_edges_are_sorted(self):
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "z.py"), "pass\n")
            _write(os.path.join(d, "a.py"), "pass\n")
            _write(os.path.join(d, "m.py"), "import z\nimport a\n")
            session, registry = _session_registry(d)
            scanner = ScannerEngine(d)
            manifest = ManifestEngine(session, registry).build(list(scanner.iter_files()))
            engine = DependencyEngine(session, registry)
            graph = engine.build_graph(manifest)
            edges = graph["edges"].get("m.py", [])
            self.assertEqual(edges, sorted(edges))

    def test_no_self_edge(self):
        """A module must not list itself as a dependency."""
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "solo.py"), "import solo\n")
            session, registry = _session_registry(d)
            scanner = ScannerEngine(d)
            manifest = ManifestEngine(session, registry).build(list(scanner.iter_files()))
            engine = DependencyEngine(session, registry)
            graph = engine.build_graph(manifest)
            # solo.py should not have itself as a dependency
            self.assertNotIn("solo.py", graph["edges"].get("solo.py", []))


# ---------------------------------------------------------------------------
# build_graph() — cycle detection
# ---------------------------------------------------------------------------

class TestBuildGraphCycles(unittest.TestCase):

    def test_simple_cycle_detected(self):
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "a.py"), "import b\n")
            _write(os.path.join(d, "b.py"), "import a\n")
            session, registry = _session_registry(d)
            scanner = ScannerEngine(d)
            manifest = ManifestEngine(session, registry).build(list(scanner.iter_files()))
            engine = DependencyEngine(session, registry)
            graph = engine.build_graph(manifest)
            self.assertTrue(graph["cycle_detected"])
            self.assertTrue(len(graph["cycles"]) > 0)

    def test_no_cycle_linear_chain(self):
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "a.py"), "import b\n")
            _write(os.path.join(d, "b.py"), "import c\n")
            _write(os.path.join(d, "c.py"), "pass\n")
            session, registry = _session_registry(d)
            scanner = ScannerEngine(d)
            manifest = ManifestEngine(session, registry).build(list(scanner.iter_files()))
            engine = DependencyEngine(session, registry)
            graph = engine.build_graph(manifest)
            self.assertFalse(graph["cycle_detected"])
            self.assertEqual(graph["cycles"], [])

    def test_no_cycle_no_imports(self):
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "x.py"), "pass\n")
            _write(os.path.join(d, "y.py"), "pass\n")
            session, registry = _session_registry(d)
            scanner = ScannerEngine(d)
            manifest = ManifestEngine(session, registry).build(list(scanner.iter_files()))
            engine = DependencyEngine(session, registry)
            graph = engine.build_graph(manifest)
            self.assertFalse(graph["cycle_detected"])

    def test_three_node_cycle(self):
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "a.py"), "import b\n")
            _write(os.path.join(d, "b.py"), "import c\n")
            _write(os.path.join(d, "c.py"), "import a\n")
            session, registry = _session_registry(d)
            scanner = ScannerEngine(d)
            manifest = ManifestEngine(session, registry).build(list(scanner.iter_files()))
            engine = DependencyEngine(session, registry)
            graph = engine.build_graph(manifest)
            self.assertTrue(graph["cycle_detected"])

    def test_cycle_path_length_at_least_two(self):
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "a.py"), "import b\n")
            _write(os.path.join(d, "b.py"), "import a\n")
            session, registry = _session_registry(d)
            scanner = ScannerEngine(d)
            manifest = ManifestEngine(session, registry).build(list(scanner.iter_files()))
            engine = DependencyEngine(session, registry)
            graph = engine.build_graph(manifest)
            self.assertTrue(any(len(c) >= 2 for c in graph["cycles"]))


# ---------------------------------------------------------------------------
# build_graph() — robustness
# ---------------------------------------------------------------------------

class TestBuildGraphRobustness(unittest.TestCase):

    def test_syntax_error_file_does_not_crash(self):
        """A .py file with a SyntaxError must not crash build_graph."""
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "broken.py"), "def bad(:\n    pass\n")
            _write(os.path.join(d, "good.py"), "import os\n")
            session, registry = _session_registry(d)
            scanner = ScannerEngine(d)
            manifest = ManifestEngine(session, registry).build(list(scanner.iter_files()))
            engine = DependencyEngine(session, registry)
            graph = engine.build_graph(manifest)
            self.assertIsNotNone(graph)
            self.assertIn("good.py", graph["edges"])

    def test_missing_file_on_disk_does_not_crash(self):
        """If a file listed in the manifest is missing from disk, build_graph must continue."""
        session = AnalysisSession(
            run_id="r-missing", target_project="/nonexistent/root",
            target_version="1.0", operator="t", schema_version="1.0",
        )
        registry = ArtifactRegistry(session)
        manifest = ManifestEngine(session, registry).build([
            {"file_id": "fx", "relative_path": "ghost.py"}
        ])
        engine = DependencyEngine(session, registry)
        graph = engine.build_graph(manifest)
        self.assertIsNotNone(graph)
        self.assertIn("ghost.py", graph["edges"])
        self.assertEqual(graph["edges"]["ghost.py"], [])


if __name__ == "__main__":
    unittest.main()
