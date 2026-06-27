import os
import tempfile
import unittest

from fx_evolution_lab.session import AnalysisSession
from fx_evolution_lab.registry import ArtifactRegistry
from fx_evolution_lab.scanner import ScannerEngine
from fx_evolution_lab.manifest import ManifestEngine
from fx_evolution_lab.snapshot import SnapshotEngine
from fx_evolution_lab.diff_engine import DiffEngine


class DiffEngineTests(unittest.TestCase):
    def test_diff_detects_added_removed_modified_and_renamed(self):
        with tempfile.TemporaryDirectory() as old_dir, tempfile.TemporaryDirectory() as new_dir:
            # old files
            os.makedirs(os.path.join(old_dir, "src"), exist_ok=True)
            with open(os.path.join(old_dir, "src", "app.py"), "w", encoding="utf-8") as fh:
                fh.write("print('old')\n")
            with open(os.path.join(old_dir, "src", "utils.py"), "w", encoding="utf-8") as fh:
                fh.write("def helper():\n    return 1\n")

            # new files: app.py modified, utils renamed to helpers.py, added new file extra.py
            os.makedirs(os.path.join(new_dir, "src"), exist_ok=True)
            with open(os.path.join(new_dir, "src", "app.py"), "w", encoding="utf-8") as fh:
                fh.write("print('new')\n")
            with open(os.path.join(new_dir, "src", "helpers.py"), "w", encoding="utf-8") as fh:
                fh.write("def helper():\n    return 1\n")
            with open(os.path.join(new_dir, "src", "extra.py"), "w", encoding="utf-8") as fh:
                fh.write("x = 1\n")

            # create manifests and snapshots
            session = AnalysisSession(run_id="run-diff-001", target_project=old_dir, target_version="1.0", operator="tester", schema_version="1.0")
            registry = ArtifactRegistry(session)
            scanner_old = ScannerEngine(old_dir)
            manifest_old = ManifestEngine(session, registry).build(list(scanner_old.iter_files()))
            snapshot_old = SnapshotEngine(session, registry).create(manifest_old)

            # create new manifest in same registry but with session.target_project set to new_dir
            session_new = AnalysisSession(run_id="run-diff-002", target_project=new_dir, target_version="1.0", operator="tester", schema_version="1.0")
            registry_new = ArtifactRegistry(session_new)
            scanner_new = ScannerEngine(new_dir)
            manifest_new = ManifestEngine(session_new, registry_new).build(list(scanner_new.iter_files()))
            snapshot_new = SnapshotEngine(session_new, registry_new).create(manifest_new)

            # For diff engine we need both manifests in same registry. Merge artifacts into single registry for simplicity
            merged_session = AnalysisSession(run_id="run-diff-003", target_project=new_dir, target_version="1.0", operator="tester", schema_version="1.0")
            merged_registry = ArtifactRegistry(merged_session)
            # copy artifacts
            for a in registry.list_artifacts():
                merged_registry.entries.append(a)
            for a in registry_new.list_artifacts():
                merged_registry.entries.append(a)

            diff = DiffEngine(merged_session, merged_registry).compare(snapshot_old, snapshot_new)
            self.assertTrue(any(p.endswith("app.py") for p in diff.get("files_modified", [])))
            self.assertTrue(any(r for r in diff.get("files_renamed", []) if r[0].endswith("utils.py") and r[1].endswith("helpers.py")))
            self.assertTrue(any(p.endswith("extra.py") for p in diff.get("files_added", [])))


if __name__ == "__main__":
    unittest.main()
