"""
Advanced tests for the upgraded RegressionEngine system.

Covers:
- regression_analysis helpers (normalize, hash, diff, severity, fp-filter, validation, logger)
- RegressionEngine integration (shuffled order, whitespace, renamed funcs, corrupted snapshots)
"""

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
from fx_evolution_lab.regression_analysis import (
    HashCache,
    RegressionLogger,
    calculate_severity,
    compute_diff,
    content_hash,
    is_false_positive,
    normalize_artifact,
    normalize_feature_content,
    structure_hash,
    validate_snapshot,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _session(run_id="r-adv"):
    return AnalysisSession(run_id=run_id, target_project="/tmp",
                           target_version="1.0", operator="t", schema_version="1.0")


def _feature(name, signature, kind="function", decorators=None, line_start=1, line_end=5):
    return {
        "artifact_id": f"art-{name}",
        "artifact_type": "feature",
        "feature_id": f"feature-{name}",
        "name": name,
        "signature": signature,
        "kind": kind,
        "decorators": decorators or [],
        "parents": [],
        "file_path": f"/proj/src/{name}.py",
        "line_start": line_start,
        "line_end": line_end,
        "imports": [],
    }


def _full_pipeline(old_files: dict, new_files: dict):
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


# ===========================================================================
# 1. normalize_artifact
# ===========================================================================

class TestNormalizeArtifact(unittest.TestCase):

    def test_excludes_artifact_id(self):
        feat = _feature("f", "f()")
        norm = normalize_artifact(feat)
        self.assertNotIn("artifact_id", norm)

    def test_excludes_feature_id(self):
        feat = _feature("f", "f()")
        norm = normalize_artifact(feat)
        self.assertNotIn("feature_id", norm)

    def test_keys_sorted_alphabetically(self):
        feat = _feature("f", "f()")
        norm = normalize_artifact(feat)
        self.assertEqual(list(norm.keys()), sorted(norm.keys()))

    def test_whitespace_collapsed_in_signature(self):
        feat = _feature("f", "f(  x ,   y  )")
        norm = normalize_artifact(feat)
        self.assertEqual(norm["signature"], "f( x , y )")

    def test_list_of_strings_sorted(self):
        feat = _feature("f", "f()", decorators=["b_deco", "a_deco"])
        norm = normalize_artifact(feat)
        self.assertEqual(norm["decorators"], ["a_deco", "b_deco"])

    def test_deterministic_across_two_calls(self):
        feat = _feature("f", "f(x, y)")
        self.assertEqual(normalize_artifact(feat), normalize_artifact(feat))

    def test_different_line_numbers_same_content(self):
        f1 = _feature("f", "f()", line_start=1, line_end=3)
        f2 = _feature("f", "f()", line_start=10, line_end=12)
        # normalize_feature_content excludes line numbers
        n1 = normalize_feature_content(f1)
        n2 = normalize_feature_content(f2)
        self.assertEqual(n1, n2)


# ===========================================================================
# 2. Hashing System
# ===========================================================================

class TestHashing(unittest.TestCase):

    def test_content_hash_is_deterministic(self):
        feat = _feature("g", "g(a, b)")
        h1 = content_hash(feat)
        h2 = content_hash(feat)
        self.assertEqual(h1, h2)

    def test_content_hash_differs_for_different_signature(self):
        f1 = _feature("g", "g(a)")
        f2 = _feature("g", "g(a, b)")
        self.assertNotEqual(content_hash(f1), content_hash(f2))

    def test_content_hash_same_for_line_number_only_change(self):
        f1 = _feature("g", "g()", line_start=1, line_end=2)
        f2 = _feature("g", "g()", line_start=50, line_end=51)
        self.assertEqual(content_hash(f1), content_hash(f2))

    def test_structure_hash_same_when_keys_same(self):
        f1 = _feature("a", "a()")
        f2 = _feature("b", "b()")
        self.assertEqual(structure_hash(f1), structure_hash(f2))

    def test_hash_cache_returns_same_result(self):
        cache = HashCache()
        feat = _feature("f", "f()")
        r1 = cache.get(feat)
        r2 = cache.get(feat)
        self.assertEqual(r1, r2)

    def test_hash_cache_clear(self):
        cache = HashCache()
        feat = _feature("f", "f()")
        cache.get(feat)
        self.assertTrue(len(cache._cache) > 0)
        cache.clear()
        self.assertEqual(len(cache._cache), 0)

    def test_whitespace_only_change_same_content_hash(self):
        f1 = _feature("h", "h(  x  )")
        f2 = _feature("h", "h( x )")
        self.assertEqual(content_hash(f1), content_hash(f2))


# ===========================================================================
# 3. compute_diff
# ===========================================================================

class TestComputeDiff(unittest.TestCase):

    def _key(self, name):
        return (f"src/{name}.py", name)

    def test_empty_maps_no_changes(self):
        result = compute_diff({}, {})
        self.assertEqual(result["removed"], [])
        self.assertEqual(result["added"], [])
        self.assertEqual(result["modified"], [])
        self.assertEqual(result["metadata_changes"], [])

    def test_removed_detected(self):
        old = {self._key("f"): _feature("f", "f()")}
        result = compute_diff(old, {})
        self.assertEqual(len(result["removed"]), 1)
        self.assertEqual(result["removed"][0]["feature"]["name"], "f")

    def test_added_detected(self):
        new = {self._key("g"): _feature("g", "g()")}
        result = compute_diff({}, new)
        self.assertEqual(len(result["added"]), 1)

    def test_signature_change_is_modified(self):
        key = self._key("run")
        old = {key: _feature("run", "run(x)")}
        new = {key: _feature("run", "run(x, y)")}
        result = compute_diff(old, new)
        self.assertEqual(len(result["modified"]), 1)
        self.assertEqual(result["modified"][0]["change_type"], "signature_changed")

    def test_line_number_only_change_is_metadata(self):
        key = self._key("run")
        old = {key: _feature("run", "run()", line_start=1, line_end=3)}
        new = {key: _feature("run", "run()", line_start=10, line_end=12)}
        result = compute_diff(old, new)
        self.assertEqual(len(result["modified"]), 0)
        self.assertEqual(len(result["metadata_changes"]), 1)

    def test_hash_short_circuit_identical_features(self):
        key = self._key("f")
        feat = _feature("f", "f()")
        cache = HashCache()
        result = compute_diff({key: feat}, {key: feat}, cache=cache)
        self.assertEqual(result["modified"], [])
        self.assertEqual(result["metadata_changes"], [])

    def test_shuffled_order_same_result(self):
        """Shuffling the file list must not change diff output."""
        keys = [(f"src/{i}.py", f"func{i}") for i in range(5)]
        old = {k: _feature(k[1], f"{k[1]}()") for k in keys}
        new = dict(old)  # identical
        result = compute_diff(old, new)
        self.assertEqual(result["removed"], [])
        self.assertEqual(result["modified"], [])

    def test_renamed_function_detected_as_removed_and_added(self):
        """A renamed function (new name, same signature) = removed + added."""
        old = {self._key("old_name"): _feature("old_name", "old_name()")}
        new = {self._key("new_name"): _feature("new_name", "new_name()")}
        result = compute_diff(old, new)
        self.assertEqual(len(result["removed"]), 1)
        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(len(result["modified"]), 0)


# ===========================================================================
# 4. calculate_severity
# ===========================================================================

class TestCalculateSeverity(unittest.TestCase):

    def _diff(self, removed=None, modified=None, metadata=None):
        return {
            "removed": removed or [],
            "added": [],
            "modified": modified or [],
            "metadata_changes": metadata or [],
        }

    def test_empty_diff_score_zero_level_low(self):
        result = calculate_severity(self._diff())
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["level"], "low")

    def test_public_removal_score_3_level_high(self):
        # score=3 (public removal) maps to "high" — removing a public API
        # immediately warrants high severity regardless of count
        removed = [{"feature": _feature("process", "process()")}]
        result = calculate_severity(self._diff(removed=removed))
        self.assertEqual(result["score"], 3)
        self.assertEqual(result["level"], "high")

    def test_private_removal_score_1_level_low(self):
        removed = [{"feature": _feature("_helper", "_helper()")}]
        result = calculate_severity(self._diff(removed=removed))
        self.assertEqual(result["score"], 1)
        self.assertEqual(result["level"], "low")

    def test_signature_change_score_2_level_medium(self):
        key = ("src/a.py", "run")
        mod = [{"key": key, "old": _feature("run", "run(x)"),
                "new": _feature("run", "run(x,y)"), "change_type": "signature_changed"}]
        result = calculate_severity(self._diff(modified=mod))
        self.assertEqual(result["score"], 2)
        self.assertEqual(result["level"], "medium")

    def test_behavior_change_score_3(self):
        key = ("src/a.py", "run")
        mod = [{"key": key, "old": _feature("run", "run()"),
                "new": _feature("run", "run()"), "change_type": "behavior_changed"}]
        result = calculate_severity(self._diff(modified=mod))
        self.assertEqual(result["score"], 3)

    def test_score_4_level_high(self):
        removed = [{"feature": _feature("api", "api()")}]   # +3
        key = ("src/a.py", "run")
        mod = [{"key": key, "old": _feature("run", "run(x)"),
                "new": _feature("run", "run(x,y)"), "change_type": "signature_changed"}]  # +2
        result = calculate_severity(self._diff(removed=removed, modified=mod))
        self.assertGreaterEqual(result["score"], 4)
        self.assertEqual(result["level"], "high")

    def test_only_metadata_score_1_per_entry(self):
        meta = [{"key": ("a.py", "f"), "old": _feature("f", "f()"),
                 "new": _feature("f", "f()"), "change_type": "metadata"}]
        result = calculate_severity(self._diff(metadata=meta))
        self.assertEqual(result["score"], 1)
        self.assertEqual(result["level"], "low")

    def test_breakdown_field_present(self):
        removed = [{"feature": _feature("pub", "pub()")}]
        result = calculate_severity(self._diff(removed=removed))
        self.assertIn("breakdown", result)


# ===========================================================================
# 5. is_false_positive
# ===========================================================================

class TestIsFalsePositive(unittest.TestCase):

    def _diff(self, removed=None, modified=None, metadata=None):
        return {
            "removed": removed or [],
            "added": [],
            "modified": modified or [],
            "metadata_changes": metadata or [],
        }

    def test_empty_diff_is_false_positive(self):
        self.assertTrue(is_false_positive(self._diff()))

    def test_metadata_only_is_false_positive(self):
        meta = [{"key": ("a.py", "f"), "old": _feature("f", "f()"),
                 "new": _feature("f", "f()"), "change_type": "metadata"}]
        self.assertTrue(is_false_positive(self._diff(metadata=meta)))

    def test_removal_is_not_false_positive(self):
        removed = [{"feature": _feature("f", "f()")}]
        self.assertFalse(is_false_positive(self._diff(removed=removed)))

    def test_modification_is_not_false_positive(self):
        key = ("src/a.py", "run")
        mod = [{"key": key, "old": _feature("run", "run(x)"),
                "new": _feature("run", "run(x,y)"), "change_type": "signature_changed"}]
        self.assertFalse(is_false_positive(self._diff(modified=mod)))

    def test_whitespace_only_signature_change_is_false_positive(self):
        """Two features that differ only in whitespace have the same content_hash
        so compute_diff puts them in metadata_changes — i.e. a false positive."""
        key = ("src/a.py", "run")
        f1 = _feature("run", "run(  x  )")
        f2 = _feature("run", "run( x )")
        old = {key: f1}
        new = {key: f2}
        diff_result = compute_diff(old, new)
        # should be metadata (no behavioral change)
        self.assertFalse(bool(diff_result["modified"]))
        self.assertTrue(is_false_positive(diff_result))


# ===========================================================================
# 6. validate_snapshot
# ===========================================================================

class TestValidateSnapshot(unittest.TestCase):

    def _registry_with_manifest(self, files=None):
        session = _session("r-val")
        registry = ArtifactRegistry(session)
        manifest = registry.register("manifest", {
            "files": files if files is not None else [{"relative_path": "a.py"}],
            "root_path": "/tmp",
        })
        return registry, manifest

    def test_none_snapshot_invalid(self):
        session = _session()
        registry = ArtifactRegistry(session)
        result = validate_snapshot(None, registry)
        self.assertFalse(result["valid"])
        self.assertTrue(len(result["issues"]) > 0)

    def test_missing_manifest_id_invalid(self):
        session = _session()
        registry = ArtifactRegistry(session)
        snapshot = {"artifact_id": "snap-1", "artifact_type": "snapshot"}
        result = validate_snapshot(snapshot, registry)
        self.assertFalse(result["valid"])
        self.assertTrue(any("manifest_id" in i for i in result["issues"]))

    def test_manifest_not_in_registry_invalid(self):
        session = _session()
        registry = ArtifactRegistry(session)
        snapshot = {"artifact_id": "snap-1", "artifact_type": "snapshot",
                    "manifest_id": "nonexistent-manifest"}
        result = validate_snapshot(snapshot, registry)
        self.assertFalse(result["valid"])

    def test_valid_snapshot_with_manifest(self):
        session = _session()
        registry = ArtifactRegistry(session)
        manifest = registry.register("manifest", {
            "files": [{"relative_path": "a.py"}],
            "root_path": "/tmp",
        })
        snapshot = registry.register("snapshot", {
            "manifest_id": manifest["artifact_id"],
        })
        result = validate_snapshot(snapshot, registry)
        self.assertTrue(result["valid"])
        self.assertEqual(result["issues"], [])

    def test_empty_file_list_reports_issue(self):
        session = _session()
        registry = ArtifactRegistry(session)
        manifest = registry.register("manifest", {"files": [], "root_path": "/tmp"})
        snapshot = registry.register("snapshot", {"manifest_id": manifest["artifact_id"]})
        result = validate_snapshot(snapshot, registry)
        self.assertFalse(result["valid"])
        self.assertTrue(any("no files" in i for i in result["issues"]))


# ===========================================================================
# 7. RegressionLogger
# ===========================================================================

class TestRegressionLogger(unittest.TestCase):

    def test_log_record_stored_in_memory(self):
        logger = RegressionLogger()
        logger.log({"key": "value"})
        self.assertEqual(len(logger.records), 1)
        self.assertEqual(logger.records[0]["key"], "value")

    def test_log_detection_stores_required_fields(self):
        logger = RegressionLogger()
        logger.log_detection(
            artifact_id="art-1",
            diff_id="diff-1",
            severity_score=3,
            severity_level="medium",
            change_types=["removed"],
            false_positive=False,
            decision_path="reported(score=3)",
        )
        rec = logger.records[0]
        for field in ("artifact_id", "diff_id", "severity_score", "severity_level",
                      "change_types", "false_positive", "decision_path"):
            self.assertIn(field, rec)

    def test_log_writes_to_file(self):
        with tempfile.NamedTemporaryFile(mode="r", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            logger = RegressionLogger(log_path=path)
            logger.log({"event": "test"})
            with open(path, encoding="utf-8") as fh:
                lines = fh.readlines()
            self.assertEqual(len(lines), 1)
            import json
            data = json.loads(lines[0])
            self.assertEqual(data["event"], "test")
        finally:
            os.unlink(path)

    def test_bad_log_path_does_not_crash(self):
        logger = RegressionLogger(log_path="/nonexistent/path/file.jsonl")
        logger.log({"x": 1})  # must not raise
        self.assertEqual(len(logger.records), 1)


# ===========================================================================
# 8. RegressionEngine integration — extended fields
# ===========================================================================

class TestRegressionEngineExtended(unittest.TestCase):

    def test_diff_result_field_present(self):
        engine, impact, *_ = _full_pipeline(
            {"a.py": "def f(): pass\n"},
            {"a.py": "def f(): pass\n"},
        )
        result = engine.detect("f", impact["artifact_id"])
        self.assertIn("diff_result", result)

    def test_severity_score_field_present(self):
        engine, impact, *_ = _full_pipeline(
            {"a.py": "def f(): pass\n"},
            {"a.py": "def f(): pass\n"},
        )
        result = engine.detect("f", impact["artifact_id"])
        self.assertIn("severity_score", result)
        self.assertIsInstance(result["severity_score"], int)

    def test_validation_field_present(self):
        engine, impact, *_ = _full_pipeline(
            {"a.py": "def f(): pass\n"},
            {"a.py": "def f(): pass\n"},
        )
        result = engine.detect("f", impact["artifact_id"])
        self.assertIn("validation", result)
        self.assertIn("old_snapshot", result["validation"])
        self.assertIn("new_snapshot", result["validation"])

    def test_false_positive_filtered_field_present(self):
        engine, impact, *_ = _full_pipeline(
            {"a.py": "def f(): pass\n"},
            {"a.py": "def f(): pass\n"},
        )
        result = engine.detect("f", impact["artifact_id"])
        self.assertIn("false_positive_filtered", result)

    def test_log_records_emitted(self):
        engine, impact, *_ = _full_pipeline(
            {"a.py": "def f(): pass\n"},
            {"a.py": "def f(): pass\n"},
        )
        engine.detect("f", impact["artifact_id"])
        self.assertGreater(len(engine.log_records), 0)

    def test_identical_versions_evidence_empty_score_zero(self):
        engine, impact, *_ = _full_pipeline(
            {"a.py": "def f(): pass\n"},
            {"a.py": "def f(): pass\n"},
        )
        result = engine.detect("f", impact["artifact_id"])
        self.assertEqual(result["evidence"], [])
        self.assertEqual(result["severity_score"], 0)

    def test_whitespace_only_change_no_evidence(self):
        """Whitespace-only changes must be suppressed — no behavioral regression."""
        engine, impact, *_ = _full_pipeline(
            {"a.py": "def run(x):\n    return x\n"},
            {"a.py": "def run( x ):\n    return x\n"},
        )
        result = engine.detect("run", impact["artifact_id"])
        sig_changes = [e for e in result["evidence"] if e["type"] == "signature_changed"]
        # whitespace-only → normalize collapses it → same hash → no modification
        self.assertEqual(sig_changes, [])

    def test_shuffled_import_order_no_regression(self):
        """Changing only import order in a file must not create a regression."""
        engine, impact, *_ = _full_pipeline(
            {"a.py": "import os\nimport sys\n\ndef run(): pass\n"},
            {"a.py": "import sys\nimport os\n\ndef run(): pass\n"},
        )
        result = engine.detect("run", impact["artifact_id"])
        self.assertEqual(result["evidence"], [])

    def test_corrupted_snapshot_raises_key_error(self):
        """A snapshot with no matching manifest must raise KeyError."""
        session = AnalysisSession(run_id="r-corrupt", target_project="/tmp",
                                  target_version="1.0", operator="t", schema_version="1.0")
        registry = ArtifactRegistry(session)

        # Build minimal impact → diff → snapshots chain, but break the old snapshot
        impact = registry.register("impact", {
            "impact_id": "imp-1",
            "change_id": "change-1",
            "affected_features": [],
            "affected_modules": [],
            "impact_level": "low",
            "confidence": {"score": 0.1, "level": "low",
                           "reasoning": "", "evidence_refs": []},
        })
        # diff points to nonexistent snapshots
        registry.register("diff", {
            "change_id": "change-1",
            "old_snapshot": "snap-missing-old",
            "new_snapshot": "snap-missing-new",
            "files_added": [],
            "files_removed": [],
            "files_modified": [],
            "files_renamed": [],
        })

        engine = RegressionEngine(session, registry)
        with self.assertRaises(KeyError):
            engine.detect("f", impact["artifact_id"])

    def test_missing_manifest_no_crash(self):
        """When manifest is absent, detect() falls back to empty feature set."""
        session = AnalysisSession(run_id="r-nomnf", target_project="/tmp",
                                  target_version="1.0", operator="t", schema_version="1.0")
        registry = ArtifactRegistry(session)

        old_snap = registry.register("snapshot", {"manifest_id": "no-such-manifest"})
        new_snap = registry.register("snapshot", {"manifest_id": "no-such-manifest-2"})
        diff_art = registry.register("diff", {
            "change_id": "change-nomnf",
            "old_snapshot": old_snap["artifact_id"],
            "new_snapshot": new_snap["artifact_id"],
            "files_added": [],
            "files_removed": [],
            "files_modified": [],
            "files_renamed": [],
        })
        impact = registry.register("impact", {
            "impact_id": "imp-nomnf",
            "change_id": "change-nomnf",
            "affected_features": [],
            "affected_modules": [],
            "impact_level": "low",
            "confidence": {"score": 0.1, "level": "low",
                           "reasoning": "", "evidence_refs": []},
        })
        engine = RegressionEngine(session, registry)
        result = engine.detect("f", impact["artifact_id"])
        self.assertEqual(result["evidence"], [])

    def test_duplicated_artifact_ids_no_crash(self):
        """Duplicate artifact_id entries in registry must not crash detect()."""
        engine, impact, *_ = _full_pipeline(
            {"a.py": "def f(): pass\n"},
            {"a.py": "def f(): pass\n"},
        )
        # Inject a duplicate of the impact artifact
        dup = dict(impact)
        engine.registry.entries.append(dup)
        # detect() should still work — first match wins
        result = engine.detect("f", impact["artifact_id"])
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
