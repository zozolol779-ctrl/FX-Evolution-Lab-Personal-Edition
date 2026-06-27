import json
import tempfile
import unittest
from pathlib import Path

from fx_evolution_lab.session import AnalysisSession
from fx_evolution_lab.registry import ArtifactRegistry
from fx_evolution_lab.schemas import (
    ManifestSchema,
    SnapshotSchema,
    DiffSchema,
    FeatureSchema,
    DependencySchema,
    ImpactSchema,
    RegressionSchema,
    RootCauseSchema,
    ReportSchema,
)


class CoreArchitectureTests(unittest.TestCase):
    def test_session_and_registry_create_artifacts(self):
        session = AnalysisSession(
            run_id="run-test-001",
            target_project="demo",
            target_version="1.0",
            operator="tester",
            schema_version="1.0",
        )
        registry = ArtifactRegistry(session)
        artifact = registry.register("manifest", {"path": "src/app.py"})
        self.assertEqual(artifact["artifact_type"], "manifest")
        self.assertTrue(artifact["artifact_id"].startswith("artifact-"))
        self.assertEqual(artifact["analysis_run_id"], session.run_id)

    def test_schema_validation(self):
        manifest = ManifestSchema.from_data(
            {
                "schema_version": "1.0",
                "generated_at": "2026-06-25T00:00:00Z",
                "root_path": "/tmp/demo",
                "files": [
                    {
                        "file_id": "file-1",
                        "relative_path": "src/app.py",
                        "sha256": "a" * 64,
                        "size": 10,
                        "mtime": "2026-06-25T00:00:00Z",
                        "entropy": 0.0,
                        "language": "python",
                        "binary_flag": False,
                    }
                ],
            }
        )
        self.assertEqual(manifest["files"][0]["relative_path"], "src/app.py")

    def test_snapshot_and_diff_round_trip(self):
        session = AnalysisSession(run_id="run-test-002", target_project="demo", target_version="1.0", operator="tester", schema_version="1.0")
        registry = ArtifactRegistry(session)
        old_manifest = {"files": [{"file_id": "file-1", "relative_path": "src/app.py"}]}
        new_manifest = {"files": [{"file_id": "file-1", "relative_path": "src/app.py"}]}
        snapshot_old = SnapshotSchema.create(session, registry, old_manifest)
        snapshot_new = SnapshotSchema.create(session, registry, new_manifest)
        diff = DiffSchema.create(session, registry, snapshot_old, snapshot_new)
        self.assertEqual(diff["change_type"], "unchanged")


if __name__ == "__main__":
    unittest.main()
