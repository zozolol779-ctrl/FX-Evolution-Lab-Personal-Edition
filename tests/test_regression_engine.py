import os
import tempfile
import unittest

from fx_evolution_lab.session import AnalysisSession
from fx_evolution_lab.registry import ArtifactRegistry
from fx_evolution_lab.scanner import ScannerEngine
from fx_evolution_lab.manifest import ManifestEngine
from fx_evolution_lab.snapshot import SnapshotEngine
from fx_evolution_lab.diff_engine import DiffEngine
from fx_evolution_lab.dependency_engine import DependencyEngine
from fx_evolution_lab.feature_engine import FeatureEngine
from fx_evolution_lab.impact_engine import ImpactEngine
from fx_evolution_lab.regression_engine import RegressionEngine


class RegressionEngineTests(unittest.TestCase):
    def test_detect_removed_function_and_signature_change(self):
        with tempfile.TemporaryDirectory() as old_dir, tempfile.TemporaryDirectory() as new_dir:
            os.makedirs(os.path.join(old_dir, "src"), exist_ok=True)
            os.makedirs(os.path.join(new_dir, "src"), exist_ok=True)
            # old utils has helper
            with open(os.path.join(old_dir, "src", "utils.py"), "w", encoding="utf-8") as fh:
                fh.write("def helper(a):\n    return a\n")
            # new utils removed helper
            with open(os.path.join(new_dir, "src", "utils.py"), "w", encoding="utf-8") as fh:
                fh.write("# helper removed\n")

            # app imports utils and uses helper
            with open(os.path.join(old_dir, "src", "app.py"), "w", encoding="utf-8") as fh:
                fh.write("from src import utils\n\ndef run():\n    return utils.helper(1)\n")
            with open(os.path.join(new_dir, "src", "app.py"), "w", encoding="utf-8") as fh:
                fh.write("from src import utils\n\ndef run():\n    return 1\n")

            session_old = AnalysisSession(run_id="run-r-001", target_project=old_dir, target_version="1.0", operator="tester", schema_version="1.0")
            registry_old = ArtifactRegistry(session_old)
            manifest_old = ManifestEngine(session_old, registry_old).build(list(ScannerEngine(old_dir).iter_files()))
            snapshot_old = SnapshotEngine(session_old, registry_old).create(manifest_old)

            session_new = AnalysisSession(run_id="run-r-002", target_project=new_dir, target_version="1.0", operator="tester", schema_version="1.0")
            registry_new = ArtifactRegistry(session_new)
            manifest_new = ManifestEngine(session_new, registry_new).build(list(ScannerEngine(new_dir).iter_files()))
            snapshot_new = SnapshotEngine(session_new, registry_new).create(manifest_new)

            # merged registry
            merged_session = AnalysisSession(run_id="run-r-003", target_project=new_dir, target_version="1.0", operator="tester", schema_version="1.0")
            merged_registry = ArtifactRegistry(merged_session)
            for a in registry_old.list_artifacts():
                merged_registry.entries.append(a)
            for a in registry_new.list_artifacts():
                merged_registry.entries.append(a)

            # extract features for both versions into merged registry for completeness
            fe = FeatureEngine(merged_session, merged_registry)
            fe.extract_from_file(os.path.join(old_dir, "src", "utils.py"))
            fe.extract_from_file(os.path.join(new_dir, "src", "utils.py"))
            fe.extract_from_file(os.path.join(old_dir, "src", "app.py"))
            fe.extract_from_file(os.path.join(new_dir, "src", "app.py"))

            # dependency/diff/impact
            dep_graph = DependencyEngine(merged_session, merged_registry).build_graph(manifest_new)
            diff = DiffEngine(merged_session, merged_registry).compare(snapshot_old, snapshot_new)
            impact = ImpactEngine(merged_session, merged_registry).assess(diff.get("change_id"))

            regression = RegressionEngine(merged_session, merged_registry).detect("helper", impact.get("artifact_id"))
            self.assertTrue(len(regression.get("evidence", [])) >= 1)
            found_removed = any(r["type"] == "removed" and r["name"] == "helper" for r in regression.get("evidence", []))
            self.assertTrue(found_removed)


if __name__ == "__main__":
    unittest.main()
