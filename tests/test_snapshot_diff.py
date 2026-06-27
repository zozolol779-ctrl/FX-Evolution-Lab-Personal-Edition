import unittest

from fx_evolution_lab.session import AnalysisSession
from fx_evolution_lab.registry import ArtifactRegistry
from fx_evolution_lab.manifest import ManifestEngine
from fx_evolution_lab.snapshot import SnapshotEngine
from fx_evolution_lab.diff_engine import DiffEngine


class SnapshotDiffTests(unittest.TestCase):
    def test_snapshot_and_diff_pipeline(self):
        session = AnalysisSession(run_id="run-test-004", target_project="demo", target_version="1.0", operator="tester", schema_version="1.0")
        registry = ArtifactRegistry(session)
        manifest_engine = ManifestEngine(session, registry)
        manifest = manifest_engine.build([{"file_id": "file-1", "relative_path": "src/app.py", "language": "python"}])
        snapshot_engine = SnapshotEngine(session, registry)
        snapshot = snapshot_engine.create(manifest)
        diff_engine = DiffEngine(session, registry)
        diff = diff_engine.compare(snapshot, snapshot)
        self.assertEqual(diff["artifact_type"], "diff")
        self.assertEqual(diff["change_type"], "unchanged")


if __name__ == "__main__":
    unittest.main()
