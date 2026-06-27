import os
import tempfile
import unittest

from fx_evolution_lab.session import AnalysisSession
from fx_evolution_lab.registry import ArtifactRegistry
from fx_evolution_lab.feature_engine import FeatureEngine


class FeatureEngineASTTests(unittest.TestCase):
    def test_extract_simple_functions_and_classes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "sample.py")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("""
import os

class User:
    def login(self):
        pass

def helper():
    return 1
""")
            session = AnalysisSession(run_id="run-feat-001", target_project=tmpdir, target_version="1.0", operator="tester", schema_version="1.0")
            registry = ArtifactRegistry(session)
            engine = FeatureEngine(session, registry)
            features = engine.extract_from_file(path)
            names = {f["name"]: f for f in features}
            self.assertIn("User", names)
            self.assertIn("login", names)
            self.assertIn("helper", names)
            # class should have kind 'class'
            self.assertEqual(names["User"]["kind"], "class")
            # method should have kind 'method' and parent User
            self.assertEqual(names["login"]["kind"], "method")
            self.assertIn("User", names["login"]["parents"]) 


if __name__ == "__main__":
    unittest.main()
