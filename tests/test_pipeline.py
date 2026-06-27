import unittest

from fx_evolution_lab.session import AnalysisSession
from fx_evolution_lab.registry import ArtifactRegistry
from fx_evolution_lab.scanner import ScannerEngine
from fx_evolution_lab.manifest import ManifestEngine
from fx_evolution_lab.snapshot import SnapshotEngine
from fx_evolution_lab.diff_engine import DiffEngine
from fx_evolution_lab.feature_engine import FeatureEngine
from fx_evolution_lab.dependency_engine import DependencyEngine
from fx_evolution_lab.impact_engine import ImpactEngine
from fx_evolution_lab.regression_engine import RegressionEngine
from fx_evolution_lab.root_cause_engine import RootCauseEngine
from fx_evolution_lab.evolution_engine import EvolutionEngine
from fx_evolution_lab.report_engine import ReportEngine


class FullPipelineTests(unittest.TestCase):
    def test_full_analysis_pipeline(self):
        session = AnalysisSession(run_id="run-test-006", target_project="demo", target_version="1.0", operator="tester", schema_version="1.0")
        registry = ArtifactRegistry(session)

        scanner = ScannerEngine(".")
        manifest = ManifestEngine(session, registry).build(list(scanner.iter_files())[:1])
        snapshot = SnapshotEngine(session, registry).create(manifest)
        diff = DiffEngine(session, registry).compare(snapshot, snapshot)
        feature = FeatureEngine(session, registry).extract("demo.main", "run")
        dependency = DependencyEngine(session, registry).analyze("demo.main", "demo.utils")
        impact = ImpactEngine(session, registry).assess(diff["artifact_id"])
        regression = RegressionEngine(session, registry).detect(feature["name"], impact["artifact_id"])
        root_cause = RootCauseEngine(session, registry).analyze(regression["artifact_id"], diff["artifact_id"])
        evolution = EvolutionEngine(session, registry).build_timeline([snapshot])
        report = ReportEngine(session, registry).build("pipeline complete", [{"type": "regression", "id": regression["artifact_id"]}])

        self.assertEqual(manifest["artifact_type"], "manifest")
        self.assertEqual(snapshot["artifact_type"], "snapshot")
        self.assertEqual(diff["artifact_type"], "diff")
        self.assertEqual(feature["artifact_type"], "feature")
        self.assertEqual(dependency["artifact_type"], "dependency")
        self.assertEqual(impact["artifact_type"], "impact")
        self.assertEqual(regression["artifact_type"], "regression")
        self.assertEqual(root_cause["artifact_type"], "root_cause")
        self.assertEqual(evolution["artifact_type"], "evolution")
        self.assertEqual(report["artifact_type"], "report")


if __name__ == "__main__":
    unittest.main()
