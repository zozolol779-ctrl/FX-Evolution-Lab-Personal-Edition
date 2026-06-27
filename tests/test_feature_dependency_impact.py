import unittest

from fx_evolution_lab.session import AnalysisSession
from fx_evolution_lab.registry import ArtifactRegistry
from fx_evolution_lab.feature_engine import FeatureEngine
from fx_evolution_lab.dependency_engine import DependencyEngine
from fx_evolution_lab.impact_engine import ImpactEngine


class FeatureDependencyImpactTests(unittest.TestCase):
    def test_feature_dependency_and_impact_pipeline(self):
        session = AnalysisSession(run_id="run-test-005", target_project="demo", target_version="1.0", operator="tester", schema_version="1.0")
        registry = ArtifactRegistry(session)
        feature_engine = FeatureEngine(session, registry)
        dependency_engine = DependencyEngine(session, registry)
        impact_engine = ImpactEngine(session, registry)

        feature = feature_engine.extract("demo.main", "run")
        dependency = dependency_engine.analyze("demo.main", "demo.utils")
        impact = impact_engine.assess("change-1")

        self.assertEqual(feature["artifact_type"], "feature")
        self.assertEqual(dependency["artifact_type"], "dependency")
        self.assertEqual(impact["artifact_type"], "impact")


if __name__ == "__main__":
    unittest.main()
