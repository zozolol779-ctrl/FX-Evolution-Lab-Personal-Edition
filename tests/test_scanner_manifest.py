import os
import tempfile
import unittest

from fx_evolution_lab.session import AnalysisSession
from fx_evolution_lab.registry import ArtifactRegistry
from fx_evolution_lab.scanner import ScannerEngine
from fx_evolution_lab.manifest import ManifestEngine


class ScannerManifestTests(unittest.TestCase):
    def test_scanner_builds_manifest_from_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "demo.py"), "w", encoding="utf-8") as handle:
                handle.write("print('hello')\n")
            session = AnalysisSession(run_id="run-test-003", target_project=tmpdir, target_version="1.0", operator="tester", schema_version="1.0")
            registry = ArtifactRegistry(session)
            scanner = ScannerEngine(tmpdir)
            files = list(scanner.iter_files())
            manifest_engine = ManifestEngine(session, registry)
            artifact = manifest_engine.build(files)
            self.assertEqual(artifact["artifact_type"], "manifest")
            self.assertEqual(len(artifact["files"]), 1)
            self.assertEqual(artifact["files"][0]["language"], "python")


if __name__ == "__main__":
    unittest.main()
