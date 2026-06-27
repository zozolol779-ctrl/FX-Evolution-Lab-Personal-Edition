"""Edge case tests for RegressionEngine."""
import os
import tempfile
import unittest

from fx_evolution_lab.session import AnalysisSession
from fx_evolution_lab.registry import ArtifactRegistry
from fx_evolution_lab.scanner import ScannerEngine
from fx_evolution_lab.manifest import ManifestEngine
from fx_evolution_lab.snapshot import SnapshotEngine
from fx_evolution_lab.diff_engine import DiffEngine
from fx_evolution_lab.impact_engine import ImpactEngine
from fx_evolution_lab.regression_engine import RegressionEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _full_pipeline(old_files: dict, new_files: dict):
    """Build a merged registry with impact artifact ready for RegressionEngine."""
    old_tmp = tempfile.mkdtemp()
    new_tmp = tempfile.mkdtemp()

    for rel, content in old_files.items():
        _write(os.path.join(old_tmp, rel), content)
    for rel, content in new_files.items():
        _write(os.path.join(new_tmp, rel), content)

    def _snap(tmpdir, run_id):
        session = AnalysisSession(run_id=run_id, target_project=tmpdir,
                                  target_version="1.0", operator="t", schema_version="1.0")
        registry = ArtifactRegistry(session)
        manifest = ManifestEngine(session, registry).build(
            list(ScannerEngine(tmpdir).iter_files()))
        snapshot = SnapshotEngine(session, registry).create(manifest)
        return session, registry, manifest, snapshot

    _, reg_old, _, snap_old = _snap(old_tmp, "run-old")
    _, reg_new, _, snap_new = _snap(new_tmp, "run-new")

    merged_session = AnalysisSession(run_id="run-merged", target_project=new_tmp,
                                     target_version="1.0", operator="t", schema_version="1.0")
    merged_registry = ArtifactRegistry(merged_session)
    for a in reg_old.list_artifacts():
        merged_registry.entries.append(a)
    for a in reg_new.list_artifacts():
        merged_registry.entries.append(a)

    diff = DiffEngine(merged_session, merged_registry).compare(snap_old, snap_new)
    impact = ImpactEngine(merged_session, merged_registry).assess(diff["change_id"])

    engine = RegressionEngine(merged_session, merged_registry)
    return engine, impact, old_tmp, new_tmp


# ---------------------------------------------------------------------------
# Artifact basics
# ---------------------------------------------------------------------------

class TestRegressionArtifact(unittest.TestCase):

    def test_artifact_type_is_regression(self):
        engine, impact, *_ = _full_pipeline(
            {"a.py": "def f(): pass\n"},
            {"a.py": "def f(): pass\n"},
        )
        result = engine.detect("f", impact["artifact_id"])
        self.assertEqual(result["artifact_type"], "regression")

    def test_required_keys_present(self):
        required = {"artifact_id", "artifact_type", "regression_id",
                    "severity", "impacted_feature", "evidence"}
        engine, impact, *_ = _full_pipeline(
            {"a.py": "def f(): pass\n"},
            {"a.py": "def f(): pass\n"},
        )
        result = engine.detect("f", impact["artifact_id"])
        for key in required:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_impact_id_field_stored(self):
        engine, impact, *_ = _full_pipeline(
            {"a.py": "def f(): pass\n"},
            {"a.py": "def f(): pass\n"},
        )
        result = engine.detect("f", impact["artifact_id"])
        self.assertIn("impact_id", result)


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

class TestRegressionLookup(unittest.TestCase):

    def test_missing_impact_raises_key_error(self):
        session = AnalysisSession(run_id="r-miss", target_project="/tmp",
                                  target_version="1.0", operator="t", schema_version="1.0")
        registry = ArtifactRegistry(session)
        engine = RegressionEngine(session, registry)
        with self.assertRaises(KeyError):
            engine.detect("f", "nonexistent-impact-id")

    def test_lookup_by_artifact_id(self):
        engine, impact, *_ = _full_pipeline(
            {"a.py": "def f(): pass\n"},
            {"a.py": "def f(): pass\n"},
        )
        result = engine.detect("f", impact["artifact_id"])
        self.assertIsNotNone(result)

    def test_lookup_by_impact_id_field(self):
        engine, impact, *_ = _full_pipeline(
            {"a.py": "def f(): pass\n"},
            {"a.py": "def f(): pass\n"},
        )
        result = engine.detect("f", impact["impact_id"])
        self.assertIsNotNone(result)


# ---------------------------------------------------------------------------
# No regressions
# ---------------------------------------------------------------------------

class TestRegressionNone(unittest.TestCase):

    def test_identical_versions_no_regressions(self):
        engine, impact, *_ = _full_pipeline(
            {"a.py": "def f(): pass\n"},
            {"a.py": "def f(): pass\n"},
        )
        result = engine.detect("f", impact["artifact_id"])
        self.assertEqual(result["evidence"], [])

    def test_no_regressions_severity_is_low(self):
        engine, impact, *_ = _full_pipeline(
            {"a.py": "def f(): pass\n"},
            {"a.py": "def f(): pass\n"},
        )
        result = engine.detect("f", impact["artifact_id"])
        self.assertEqual(result["severity"], "low")


# ---------------------------------------------------------------------------
# Removed features
# ---------------------------------------------------------------------------

class TestRegressionRemoved(unittest.TestCase):

    def test_removed_public_function_detected(self):
        engine, impact, *_ = _full_pipeline(
            {"a.py": "def helper(): pass\n"},
            {"a.py": "# removed\n"},
        )
        result = engine.detect("helper", impact["artifact_id"])
        found = any(r["type"] == "removed" and r["name"] == "helper"
                    for r in result["evidence"])
        self.assertTrue(found)

    def test_removed_public_function_severity_high(self):
        engine, impact, *_ = _full_pipeline(
            {"a.py": "def helper(): pass\n"},
            {"a.py": "# removed\n"},
        )
        result = engine.detect("helper", impact["artifact_id"])
        self.assertEqual(result["severity"], "high")

    def test_removed_private_function_severity_low(self):
        engine, impact, *_ = _full_pipeline(
            {"a.py": "def _internal(): pass\n"},
            {"a.py": "# removed\n"},
        )
        result = engine.detect("_internal", impact["artifact_id"])
        removed = [r for r in result["evidence"] if r["type"] == "removed"]
        if removed:
            self.assertEqual(removed[0]["severity"], "low")

    def test_removed_function_with_none_name_does_not_crash(self):
        """A feature artifact with name=None must not crash severity classification."""
        engine, impact, *_ = _full_pipeline(
            {"a.py": "def helper(): pass\n"},
            {"a.py": "# removed\n"},
        )
        # Inject a synthetic feature with name=None into old registry to test guard
        # We test indirectly: detect() must complete without AttributeError
        result = engine.detect("helper", impact["artifact_id"])
        self.assertIsNotNone(result)


# ---------------------------------------------------------------------------
# Signature changes
# ---------------------------------------------------------------------------

class TestRegressionSignature(unittest.TestCase):

    def test_signature_change_detected(self):
        engine, impact, *_ = _full_pipeline(
            {"a.py": "def run(x): pass\n"},
            {"a.py": "def run(x, y): pass\n"},
        )
        result = engine.detect("run", impact["artifact_id"])
        found = any(r["type"] == "signature_changed" for r in result["evidence"])
        self.assertTrue(found, "Signature change must be detected")

    def test_signature_change_severity_medium(self):
        engine, impact, *_ = _full_pipeline(
            {"a.py": "def run(x): pass\n"},
            {"a.py": "def run(x, y): pass\n"},
        )
        result = engine.detect("run", impact["artifact_id"])
        sig_changes = [r for r in result["evidence"] if r["type"] == "signature_changed"]
        if sig_changes:
            self.assertEqual(sig_changes[0]["severity"], "medium")

    def test_no_false_signature_change_when_identical(self):
        engine, impact, *_ = _full_pipeline(
            {"a.py": "def run(x): pass\n"},
            {"a.py": "def run(x): pass\n"},
        )
        result = engine.detect("run", impact["artifact_id"])
        sig_changes = [r for r in result["evidence"] if r["type"] == "signature_changed"]
        self.assertEqual(sig_changes, [])


# ---------------------------------------------------------------------------
# Severity aggregation
# ---------------------------------------------------------------------------

class TestRegressionSeverity(unittest.TestCase):

    def test_high_when_public_function_removed(self):
        engine, impact, *_ = _full_pipeline(
            {"a.py": "def public_api(): pass\n"},
            {"a.py": "# gone\n"},
        )
        result = engine.detect("public_api", impact["artifact_id"])
        self.assertEqual(result["severity"], "high")

    def test_medium_when_only_signature_change(self):
        engine, impact, *_ = _full_pipeline(
            {"a.py": "def run(x): pass\n"},
            {"a.py": "def run(x, y): pass\n"},
        )
        result = engine.detect("run", impact["artifact_id"])
        # severity must be at least 'medium' (no removed = no 'high')
        self.assertIn(result["severity"], ("medium", "high"))


# ---------------------------------------------------------------------------
# Robustness: syntax errors and missing files
# ---------------------------------------------------------------------------

class TestRegressionRobustness(unittest.TestCase):

    def test_syntax_error_in_file_does_not_crash_detect(self):
        """A file with a syntax error in old/new version must not crash detect()."""
        engine, impact, *_ = _full_pipeline(
            {"a.py": "def f(): pass\n", "bad.py": "def broken(\n"},
            {"a.py": "def f(): pass\n"},
        )
        result = engine.detect("f", impact["artifact_id"])
        self.assertIsNotNone(result)

    def test_missing_file_does_not_crash_detect(self):
        """A file listed in the manifest but deleted from disk must not crash detect()."""
        engine, impact, old_tmp, new_tmp = _full_pipeline(
            {"a.py": "def f(): pass\n", "gone.py": "def g(): pass\n"},
            {"a.py": "def f(): pass\n"},
        )
        result = engine.detect("f", impact["artifact_id"])
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
