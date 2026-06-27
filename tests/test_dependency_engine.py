import os
import tempfile
import unittest

from fx_evolution_lab.session import AnalysisSession
from fx_evolution_lab.registry import ArtifactRegistry
from fx_evolution_lab.scanner import ScannerEngine
from fx_evolution_lab.manifest import ManifestEngine
from fx_evolution_lab.dependency_engine import DependencyEngine


class DependencyEngineTests(unittest.TestCase):
    def test_build_graph_and_detect_cycle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
            # a imports b
            with open(os.path.join(tmpdir, "src", "a.py"), "w", encoding="utf-8") as fh:
                fh.write("from src import b\n")
            # b imports a
            with open(os.path.join(tmpdir, "src", "b.py"), "w", encoding="utf-8") as fh:
                fh.write("from src import a\n")

            session = AnalysisSession(run_id="run-dep-001", target_project=tmpdir, target_version="1.0", operator="tester", schema_version="1.0")
            registry = ArtifactRegistry(session)
            scanner = ScannerEngine(tmpdir)
            manifest = ManifestEngine(session, registry).build(list(scanner.iter_files()))

            dep_engine = DependencyEngine(session, registry)
            graph = dep_engine.build_graph(manifest)
            self.assertTrue(graph.get("cycle_detected"))
            self.assertTrue(any(len(c) >= 2 for c in graph.get("cycles", [])))


if __name__ == "__main__":
    unittest.main()
