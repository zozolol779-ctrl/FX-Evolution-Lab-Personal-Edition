"""Edge case tests for ImpactEngine."""
import os
import tempfile
import unittest
from collections import deque

from fx_evolution_lab.session import AnalysisSession
from fx_evolution_lab.registry import ArtifactRegistry
from fx_evolution_lab.scanner import ScannerEngine
from fx_evolution_lab.manifest import ManifestEngine
from fx_evolution_lab.snapshot import SnapshotEngine
from fx_evolution_lab.diff_engine import DiffEngine
from fx_evolution_lab.dependency_engine import DependencyEngine
from fx_evolution_lab.feature_engine import FeatureEngine
from fx_evolution_lab.impact_engine import ImpactEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _session(tmpdir, run_id="run-impact-edge"):
    return AnalysisSession(
        run_id=run_id,
        target_project=tmpdir,
        target_version="1.0",
        operator="tester",
        schema_version="1.0",
    )


def _snapshot(tmpdir, files: dict, session, registry):
    for rel, content in files.items():
        _write(os.path.join(tmpdir, rel), content)
    scanner = ScannerEngine(tmpdir)
    manifest = ManifestEngine(session, registry).build(list(scanner.iter_files()))
    snapshot = SnapshotEngine(session, registry).create(manifest)
    return manifest, snapshot


def _merged_session(new_dir):
    return AnalysisSession(
        run_id="run-merged",
        target_project=new_dir,
        target_version="1.0",
        operator="tester",
        schema_version="1.0",
    )


def _copy_into(src_registry, dst_registry):
    for a in src_registry.list_artifacts():
        dst_registry.entries.append(a)


# ---------------------------------------------------------------------------
# Artifact basics
# ---------------------------------------------------------------------------

class TestImpactArtifact(unittest.TestCase):

    def _empty_setup(self):
        session = AnalysisSession(run_id="r-art", target_project="/tmp",
                                  target_version="1.0", operator="t", schema_version="1.0")
        registry = ArtifactRegistry(session)
        return ImpactEngine(session, registry)

    def test_artifact_type_is_impact(self):
        engine = self._empty_setup()
        result = engine.assess("nonexistent-change")
        self.assertEqual(result["artifact_type"], "impact")

    def test_required_keys_present(self):
        required = {"artifact_id", "artifact_type", "change_id",
                    "affected_features", "affected_modules",
                    "impact_level", "confidence"}
        engine = self._empty_setup()
        result = engine.assess("nonexistent-change")
        for key in required:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_confidence_has_required_subkeys(self):
        engine = self._empty_setup()
        result = engine.assess("nonexistent-change")
        for key in ("score", "level", "reasoning", "evidence_refs"):
            self.assertIn(key, result["confidence"], f"Missing confidence key: {key}")


# ---------------------------------------------------------------------------
# Fallback path (no matching diff)
# ---------------------------------------------------------------------------

class TestImpactFallback(unittest.TestCase):

    def _engine(self):
        session = AnalysisSession(run_id="r-fb", target_project="/tmp",
                                  target_version="1.0", operator="t", schema_version="1.0")
        registry = ArtifactRegistry(session)
        return ImpactEngine(session, registry)

    def test_fallback_when_no_diff_in_registry(self):
        engine = self._engine()
        result = engine.assess("change-999")
        self.assertEqual(result["impact_level"], "low")
        self.assertEqual(result["affected_features"], [])
        self.assertEqual(result["affected_modules"], [])

    def test_fallback_change_id_stored(self):
        engine = self._engine()
        result = engine.assess("change-abc")
        self.assertEqual(result["change_id"], "change-abc")

    def test_fallback_confidence_score_low(self):
        engine = self._engine()
        result = engine.assess("missing")
        self.assertLessEqual(result["confidence"]["score"], 0.2)


# ---------------------------------------------------------------------------
# Lookup: change_id field vs artifact_id
# ---------------------------------------------------------------------------

class TestImpactLookup(unittest.TestCase):

    def _diff_in_registry(self, change_id_field="change-007"):
        session = AnalysisSession(run_id="r-lkp", target_project="/tmp",
                                  target_version="1.0", operator="t", schema_version="1.0")
        registry = ArtifactRegistry(session)
        # Manually register a diff artifact
        diff = registry.register("diff", {
            "change_id": change_id_field,
            "files_added": [],
            "files_removed": [],
            "files_modified": [],
            "files_renamed": [],
        })
        return ImpactEngine(session, registry), diff

    def test_lookup_by_change_id_field(self):
        engine, diff = self._diff_in_registry("change-007")
        result = engine.assess("change-007")
        self.assertEqual(result["artifact_type"], "impact")
        self.assertEqual(result["change_id"], "change-007")

    def test_lookup_by_artifact_id(self):
        engine, diff = self._diff_in_registry("change-007")
        result = engine.assess(diff["artifact_id"])
        self.assertEqual(result["artifact_type"], "impact")


# ---------------------------------------------------------------------------
# Impact level
# ---------------------------------------------------------------------------

class TestImpactLevel(unittest.TestCase):

    def _engine_with_diff(self, **diff_fields):
        session = AnalysisSession(run_id="r-lvl", target_project="/tmp",
                                  target_version="1.0", operator="t", schema_version="1.0")
        registry = ArtifactRegistry(session)
        diff = registry.register("diff", {
            "change_id": "change-1",
            "files_added": [],
            "files_removed": [],
            "files_modified": [],
            "files_renamed": [],
            **diff_fields,
        })
        return ImpactEngine(session, registry), diff

    def test_no_changes_impact_level_low(self):
        engine, diff = self._engine_with_diff()
        result = engine.assess(diff["change_id"])
        self.assertEqual(result["impact_level"], "low")

    def test_files_removed_impact_level_high(self):
        engine, diff = self._engine_with_diff(files_removed=["old.py"])
        result = engine.assess(diff["change_id"])
        self.assertEqual(result["impact_level"], "high")

    def test_high_impact_confidence_score_is_highest(self):
        engine, diff = self._engine_with_diff(files_removed=["gone.py"])
        result = engine.assess(diff["change_id"])
        self.assertGreaterEqual(result["confidence"]["score"], 0.8)

    def test_low_impact_confidence_score_below_medium(self):
        engine, diff = self._engine_with_diff(files_modified=["a.py"])
        result = engine.assess(diff["change_id"])
        self.assertLessEqual(result["confidence"]["score"], 0.5)

    def test_confidence_level_matches_impact_level(self):
        engine, diff = self._engine_with_diff(files_removed=["x.py"])
        result = engine.assess(diff["change_id"])
        self.assertEqual(result["confidence"]["level"], result["impact_level"])


# ---------------------------------------------------------------------------
# Affected modules
# ---------------------------------------------------------------------------

class TestImpactAffectedModules(unittest.TestCase):

    def _engine_with_diff(self, **diff_fields):
        session = AnalysisSession(run_id="r-mod", target_project="/tmp",
                                  target_version="1.0", operator="t", schema_version="1.0")
        registry = ArtifactRegistry(session)
        diff = registry.register("diff", {
            "change_id": "change-1",
            "files_added": [],
            "files_removed": [],
            "files_modified": [],
            "files_renamed": [],
            **diff_fields,
        })
        return ImpactEngine(session, registry), diff

    def test_empty_diff_empty_affected_modules(self):
        engine, diff = self._engine_with_diff()
        result = engine.assess(diff["change_id"])
        self.assertEqual(result["affected_modules"], [])

    def test_added_file_in_affected_modules(self):
        engine, diff = self._engine_with_diff(files_added=["new.py"])
        result = engine.assess(diff["change_id"])
        self.assertIn("new.py", result["affected_modules"])

    def test_removed_file_in_affected_modules(self):
        engine, diff = self._engine_with_diff(files_removed=["old.py"])
        result = engine.assess(diff["change_id"])
        self.assertIn("old.py", result["affected_modules"])

    def test_modified_file_in_affected_modules(self):
        engine, diff = self._engine_with_diff(files_modified=["core.py"])
        result = engine.assess(diff["change_id"])
        self.assertIn("core.py", result["affected_modules"])

    def test_renamed_both_paths_in_affected_modules(self):
        engine, diff = self._engine_with_diff(
            files_renamed=[("old_name.py", "new_name.py")]
        )
        result = engine.assess(diff["change_id"])
        self.assertIn("old_name.py", result["affected_modules"])
        self.assertIn("new_name.py", result["affected_modules"])

    def test_affected_modules_is_sorted(self):
        engine, diff = self._engine_with_diff(
            files_modified=["z.py", "a.py", "m.py"]
        )
        result = engine.assess(diff["change_id"])
        mods = result["affected_modules"]
        self.assertEqual(mods, sorted(mods))

    def test_no_duplicate_in_affected_modules(self):
        engine, diff = self._engine_with_diff(
            files_added=["x.py"],
            files_modified=["x.py"],  # same file in two lists
        )
        result = engine.assess(diff["change_id"])
        count = result["affected_modules"].count("x.py")
        self.assertEqual(count, 1, "Duplicate path in affected_modules")


# ---------------------------------------------------------------------------
# Transitive dependency propagation
# ---------------------------------------------------------------------------

class TestImpactTransitive(unittest.TestCase):

    def test_transitive_dependents_included(self):
        """A→B→C: when C changes, both B and A must appear in affected_modules."""
        session = AnalysisSession(run_id="r-trans", target_project="/tmp",
                                  target_version="1.0", operator="t", schema_version="1.0")
        registry = ArtifactRegistry(session)
        # edges: B depends on C, A depends on B
        registry.register("dependency_graph", {
            "edges": {"a.py": ["b.py"], "b.py": ["c.py"], "c.py": []},
            "modules": ["a.py", "b.py", "c.py"],
            "cycle_detected": False,
            "cycles": [],
        })
        diff = registry.register("diff", {
            "change_id": "change-trans",
            "files_modified": ["c.py"],
            "files_added": [],
            "files_removed": [],
            "files_renamed": [],
        })
        engine = ImpactEngine(session, registry)
        result = engine.assess(diff["change_id"])
        mods = result["affected_modules"]
        self.assertIn("c.py", mods, "Changed file must be in affected_modules")
        self.assertIn("b.py", mods, "Direct dependent must be in affected_modules")
        self.assertIn("a.py", mods, "Transitive dependent must be in affected_modules")

    def test_unrelated_module_not_in_affected(self):
        """Module with no dependency path to changed file must not appear."""
        session = AnalysisSession(run_id="r-unrel", target_project="/tmp",
                                  target_version="1.0", operator="t", schema_version="1.0")
        registry = ArtifactRegistry(session)
        registry.register("dependency_graph", {
            "edges": {"a.py": ["b.py"], "b.py": [], "unrelated.py": []},
            "modules": ["a.py", "b.py", "unrelated.py"],
            "cycle_detected": False,
            "cycles": [],
        })
        diff = registry.register("diff", {
            "change_id": "change-unrel",
            "files_modified": ["b.py"],
            "files_added": [],
            "files_removed": [],
            "files_renamed": [],
        })
        engine = ImpactEngine(session, registry)
        result = engine.assess(diff["change_id"])
        self.assertNotIn("unrelated.py", result["affected_modules"])

    def test_no_dependency_graph_uses_only_diff_files(self):
        """Without a dependency graph, affected_modules equals the changed files."""
        session = AnalysisSession(run_id="r-nodep", target_project="/tmp",
                                  target_version="1.0", operator="t", schema_version="1.0")
        registry = ArtifactRegistry(session)
        diff = registry.register("diff", {
            "change_id": "change-nodep",
            "files_modified": ["x.py"],
            "files_added": [],
            "files_removed": [],
            "files_renamed": [],
        })
        engine = ImpactEngine(session, registry)
        result = engine.assess(diff["change_id"])
        self.assertIn("x.py", result["affected_modules"])
        self.assertEqual(result["affected_modules"], ["x.py"])


# ---------------------------------------------------------------------------
# Feature matching — false positive guard
# ---------------------------------------------------------------------------

class TestImpactFeatureMatching(unittest.TestCase):

    def test_no_false_positive_suffix_match(self):
        """Feature in 'old_src/utils.py' must NOT match impacted path 'src/utils.py'."""
        session = AnalysisSession(run_id="r-fp", target_project="/tmp",
                                  target_version="1.0", operator="t", schema_version="1.0")
        registry = ArtifactRegistry(session)
        # Register a feature whose file_path shares a suffix but is a different directory
        registry.register("feature", {
            "feature_id": "feature-fp-1",
            "name": "fake_match",
            "kind": "function",
            "signature": "fake_match()",
            "decorators": [],
            "parents": [],
            "line_start": 1,
            "line_end": 1,
            "file_path": "/tmp/proj/old_src/utils.py",   # different dir!
            "imports": [],
        })
        diff = registry.register("diff", {
            "change_id": "change-fp",
            "files_modified": ["src/utils.py"],
            "files_added": [],
            "files_removed": [],
            "files_renamed": [],
        })
        engine = ImpactEngine(session, registry)
        result = engine.assess(diff["change_id"])
        self.assertEqual(result["affected_features"], [],
                         "Feature in old_src/utils.py must not match impact on src/utils.py")

    def test_correct_feature_matched(self):
        """Feature whose file_path ends with the impacted relative path is matched."""
        session = AnalysisSession(run_id="r-cfm", target_project="/tmp",
                                  target_version="1.0", operator="t", schema_version="1.0")
        registry = ArtifactRegistry(session)
        feat = registry.register("feature", {
            "feature_id": "feature-cfm-1",
            "name": "real_func",
            "kind": "function",
            "signature": "real_func()",
            "decorators": [],
            "parents": [],
            "line_start": 1,
            "line_end": 5,
            "file_path": "/tmp/proj/src/utils.py",
            "imports": [],
        })
        diff = registry.register("diff", {
            "change_id": "change-cfm",
            "files_modified": ["src/utils.py"],
            "files_added": [],
            "files_removed": [],
            "files_renamed": [],
        })
        engine = ImpactEngine(session, registry)
        result = engine.assess(diff["change_id"])
        self.assertNotEqual(result["affected_features"], [],
                            "Feature in /tmp/proj/src/utils.py must match src/utils.py")

    def test_feature_with_none_file_path_does_not_crash(self):
        """Feature with file_path=None must not crash assess()."""
        session = AnalysisSession(run_id="r-none-fp", target_project="/tmp",
                                  target_version="1.0", operator="t", schema_version="1.0")
        registry = ArtifactRegistry(session)
        registry.register("feature", {
            "feature_id": "feature-none-1",
            "name": "orphan",
            "kind": "function",
            "signature": "orphan()",
            "decorators": [],
            "parents": [],
            "line_start": 1,
            "line_end": 1,
            "file_path": None,
            "imports": [],
        })
        diff = registry.register("diff", {
            "change_id": "change-none",
            "files_modified": ["src/utils.py"],
            "files_added": [],
            "files_removed": [],
            "files_renamed": [],
        })
        engine = ImpactEngine(session, registry)
        result = engine.assess(diff["change_id"])   # must not raise
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
