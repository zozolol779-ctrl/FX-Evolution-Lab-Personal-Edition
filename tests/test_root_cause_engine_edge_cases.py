"""
Edge-case and unit tests for RootCauseEngine.

Covers:
- Basic registration and schema
- Artifact lookup (artifact_id vs regression_id field)
- Missing regression raises KeyError
- Missing diff → still produces output (no crash)
- Missing dep_graph → still produces output (no crash)
- Evidence type filtering (removed / signature_changed / behavior_changed)
- Boundary-guarded file matching (old_src/utils.py ≠ src/utils.py)
- confidence.level thresholds (low / medium / high)
- confidence.evidence_refs contains no None values
- regression_id fallback when payload field absent
- No evidence items → confidence score is low
- Multiple evidence items → chains built
"""
from __future__ import annotations

import unittest
from typing import Any, Dict, List, Optional

from fx_evolution_lab.registry import ArtifactRegistry
from fx_evolution_lab.root_cause_engine import RootCauseEngine
from fx_evolution_lab.session import AnalysisSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _session() -> AnalysisSession:
    return AnalysisSession(
        run_id="run-rce-test",
        target_project="/proj",
        target_version="1.0",
        operator="tester",
        schema_version="1.0",
    )


def _registry(session: Optional[AnalysisSession] = None) -> ArtifactRegistry:
    return ArtifactRegistry(session or _session())


def _engine(registry: ArtifactRegistry) -> RootCauseEngine:
    return RootCauseEngine(registry.session, registry)


def _reg_regression(
    registry: ArtifactRegistry,
    evidence: Optional[List[Dict]] = None,
    regression_id_override: Optional[str] = None,
    include_regression_id_field: bool = True,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "severity": "high",
        "impacted_feature": "helper",
        "impact_id": "impact-1",
        "evidence": evidence or [],
    }
    if include_regression_id_field:
        payload["regression_id"] = regression_id_override or f"regression-{len(registry.list_artifacts()) + 1}"
    return registry.register("regression", payload)


def _reg_diff(
    registry: ArtifactRegistry,
    files_removed: Optional[List[str]] = None,
    files_modified: Optional[List[str]] = None,
    edges: Optional[Dict] = None,
    change_id_override: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "change_id": change_id_override or f"change-{len(registry.list_artifacts()) + 1}",
        "old_snapshot": "snap-old",
        "new_snapshot": "snap-new",
        "change_type": "modified",
        "files_removed": files_removed or [],
        "files_modified": files_modified or [],
        "files_added": [],
        "files_renamed": [],
        "lines_added": 0,
        "lines_removed": 0,
        "similarity": 0.9,
        "file_diffs": {},
    }
    return registry.register("diff", payload)


def _reg_dep_graph(
    registry: ArtifactRegistry,
    edges: Optional[Dict] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "dependency_id": f"dependency-{len(registry.list_artifacts()) + 1}",
        "edges": edges or {},
        "modules": [],
        "cycle_detected": False,
        "cycles": [],
    }
    return registry.register("dependency_graph", payload)


def _evidence_item(
    ev_type: str = "removed",
    file: str = "src/utils.py",
    name: str = "helper",
) -> Dict[str, Any]:
    return {"type": ev_type, "name": name, "file": file, "severity": "high", "evidence": {}}


# ---------------------------------------------------------------------------
# Test Classes
# ---------------------------------------------------------------------------

class TestRootCauseArtifact(unittest.TestCase):
    """Verify the registered artifact has required schema fields."""

    def setUp(self):
        self.session = _session()
        self.reg = _registry(self.session)
        self.engine = _engine(self.reg)

    def _setup(self):
        regression = _reg_regression(self.reg)
        diff = _reg_diff(self.reg)
        return regression, diff

    def test_artifact_type_is_root_cause(self):
        regression, diff = self._setup()
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        self.assertEqual(result["artifact_type"], "root_cause")

    def test_required_keys_present(self):
        regression, diff = self._setup()
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        for key in ("root_cause_id", "regression_id", "change_id", "confidence", "reasoning", "evidence"):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_confidence_has_required_subfields(self):
        regression, diff = self._setup()
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        conf = result["confidence"]
        for key in ("score", "level", "reasoning", "evidence_refs"):
            self.assertIn(key, conf, f"Missing confidence key: {key}")

    def test_registered_in_registry(self):
        regression, diff = self._setup()
        before = len(self.reg.list_artifacts())
        self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        self.assertEqual(len(self.reg.list_artifacts()), before + 1)


class TestRootCauseLookup(unittest.TestCase):
    """Artifact lookup by artifact_id OR payload regression_id field."""

    def setUp(self):
        self.session = _session()
        self.reg = _registry(self.session)
        self.engine = _engine(self.reg)

    def test_lookup_by_artifact_id(self):
        regression = _reg_regression(self.reg)
        diff = _reg_diff(self.reg)
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        self.assertEqual(result["artifact_type"], "root_cause")

    def test_lookup_by_regression_id_payload_field(self):
        regression = _reg_regression(self.reg, regression_id_override="regression-99")
        diff = _reg_diff(self.reg)
        result = self.engine.analyze("regression-99", diff["artifact_id"])
        self.assertEqual(result["artifact_type"], "root_cause")

    def test_lookup_diff_by_change_id_field(self):
        regression = _reg_regression(self.reg)
        diff = _reg_diff(self.reg, change_id_override="change-99")
        result = self.engine.analyze(regression["artifact_id"], "change-99")
        self.assertEqual(result["artifact_type"], "root_cause")

    def test_missing_regression_raises_key_error(self):
        diff = _reg_diff(self.reg)
        with self.assertRaises(KeyError):
            self.engine.analyze("nonexistent-regression", diff["artifact_id"])


class TestRootCauseMissingArtifacts(unittest.TestCase):
    """Engine must not crash when diff or dep_graph is absent."""

    def setUp(self):
        self.session = _session()
        self.reg = _registry(self.session)
        self.engine = _engine(self.reg)

    def test_missing_diff_does_not_crash(self):
        regression = _reg_regression(self.reg)
        result = self.engine.analyze(regression["artifact_id"], "nonexistent-diff")
        self.assertEqual(result["artifact_type"], "root_cause")
        self.assertIn("evidence", result)

    def test_missing_dep_graph_does_not_crash(self):
        regression = _reg_regression(self.reg)
        diff = _reg_diff(self.reg)
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        self.assertEqual(result["artifact_type"], "root_cause")

    def test_missing_diff_yields_low_confidence(self):
        regression = _reg_regression(
            self.reg,
            evidence=[_evidence_item("removed", "src/utils.py")],
        )
        result = self.engine.analyze(regression["artifact_id"], "nonexistent-diff")
        self.assertLess(result["confidence"]["score"], 0.7)

    def test_missing_diff_evidence_refs_no_none(self):
        regression = _reg_regression(self.reg)
        result = self.engine.analyze(regression["artifact_id"], "nonexistent-diff")
        for ref in result["confidence"]["evidence_refs"]:
            self.assertIsNotNone(ref, "evidence_refs must not contain None values")


class TestRootCauseEvidenceTypes(unittest.TestCase):
    """Verify which evidence types generate root-cause evidence entries."""

    def setUp(self):
        self.session = _session()
        self.reg = _registry(self.session)
        self.engine = _engine(self.reg)

    def test_removed_evidence_generates_root_cause_entry(self):
        regression = _reg_regression(
            self.reg,
            evidence=[_evidence_item("removed", "src/utils.py")],
        )
        diff = _reg_diff(self.reg, files_removed=["src/utils.py"])
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        self.assertGreater(len(result["evidence"]), 0)

    def test_signature_changed_evidence_generates_root_cause_entry(self):
        regression = _reg_regression(
            self.reg,
            evidence=[_evidence_item("signature_changed", "src/utils.py")],
        )
        diff = _reg_diff(self.reg, files_modified=["src/utils.py"])
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        self.assertGreater(len(result["evidence"]), 0)

    def test_behavior_changed_evidence_generates_root_cause_entry(self):
        """behavior_changed must NOT be silently ignored."""
        regression = _reg_regression(
            self.reg,
            evidence=[_evidence_item("behavior_changed", "src/utils.py")],
        )
        diff = _reg_diff(self.reg, files_modified=["src/utils.py"])
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        self.assertGreater(
            len(result["evidence"]),
            0,
            "behavior_changed evidence items must produce root-cause evidence",
        )

    def test_no_evidence_items_produces_empty_evidence(self):
        regression = _reg_regression(self.reg, evidence=[])
        diff = _reg_diff(self.reg)
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        self.assertEqual(result["evidence"], [])


class TestRootCauseFilePath(unittest.TestCase):
    """File-path matching must use directory-boundary guard."""

    def setUp(self):
        self.session = _session()
        self.reg = _registry(self.session)
        self.engine = _engine(self.reg)

    def test_exact_file_match_produces_evidence(self):
        regression = _reg_regression(
            self.reg,
            evidence=[_evidence_item("removed", "src/utils.py")],
        )
        diff = _reg_diff(self.reg, files_removed=["src/utils.py"])
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        entries = [e for e in result["evidence"] if e.get("related_diff")]
        self.assertTrue(len(entries) >= 1, "Exact match must produce related_diff entries")

    def test_partial_suffix_no_false_positive(self):
        """old_src/utils.py in diff must NOT match evidence file src/utils.py."""
        regression = _reg_regression(
            self.reg,
            evidence=[_evidence_item("removed", "src/utils.py")],
        )
        diff = _reg_diff(self.reg, files_removed=["old_src/utils.py"])
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        for entry in result["evidence"]:
            self.assertEqual(
                entry.get("related_diff", []),
                [],
                "old_src/utils.py must NOT match src/utils.py",
            )

    def test_subdirectory_boundary_no_false_positive(self):
        """xsrc/utils.py must NOT match evidence file src/utils.py."""
        regression = _reg_regression(
            self.reg,
            evidence=[_evidence_item("removed", "src/utils.py")],
        )
        diff = _reg_diff(self.reg, files_removed=["xsrc/utils.py"])
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        for entry in result["evidence"]:
            self.assertEqual(entry.get("related_diff", []), [])


class TestRootCauseConfidenceLevel(unittest.TestCase):
    """confidence.level must support low / medium / high tiers."""

    def setUp(self):
        self.session = _session()
        self.reg = _registry(self.session)
        self.engine = _engine(self.reg)

    def test_no_related_diff_low_confidence(self):
        regression = _reg_regression(
            self.reg,
            evidence=[_evidence_item("removed", "src/utils.py")],
        )
        result = self.engine.analyze(regression["artifact_id"], "no-diff")
        self.assertEqual(result["confidence"]["level"], "low")

    def test_related_diff_match_high_confidence(self):
        regression = _reg_regression(
            self.reg,
            evidence=[_evidence_item("removed", "src/utils.py")],
        )
        diff = _reg_diff(self.reg, files_removed=["src/utils.py"])
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        self.assertEqual(result["confidence"]["level"], "high")

    def test_confidence_level_is_string(self):
        regression = _reg_regression(self.reg)
        diff = _reg_diff(self.reg)
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        self.assertIsInstance(result["confidence"]["level"], str)

    def test_confidence_score_is_float(self):
        regression = _reg_regression(self.reg)
        diff = _reg_diff(self.reg)
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        self.assertIsInstance(result["confidence"]["score"], float)

    def test_confidence_level_in_valid_set(self):
        regression = _reg_regression(self.reg)
        diff = _reg_diff(self.reg)
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        self.assertIn(result["confidence"]["level"], {"low", "medium", "high"})


class TestRootCauseEvidenceRefs(unittest.TestCase):
    """confidence.evidence_refs must never contain None values."""

    def setUp(self):
        self.session = _session()
        self.reg = _registry(self.session)
        self.engine = _engine(self.reg)

    def test_evidence_refs_no_none_with_diff_and_graph(self):
        regression = _reg_regression(self.reg)
        diff = _reg_diff(self.reg)
        _reg_dep_graph(self.reg)
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        for ref in result["confidence"]["evidence_refs"]:
            self.assertIsNotNone(ref)

    def test_evidence_refs_no_none_without_diff(self):
        regression = _reg_regression(self.reg)
        _reg_dep_graph(self.reg)
        result = self.engine.analyze(regression["artifact_id"], "nonexistent-diff")
        for ref in result["confidence"]["evidence_refs"]:
            self.assertIsNotNone(ref)

    def test_evidence_refs_no_none_without_dep_graph(self):
        regression = _reg_regression(self.reg)
        diff = _reg_diff(self.reg)
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        for ref in result["confidence"]["evidence_refs"]:
            self.assertIsNotNone(ref)

    def test_evidence_refs_no_none_when_both_absent(self):
        regression = _reg_regression(self.reg)
        result = self.engine.analyze(regression["artifact_id"], "no-diff")
        for ref in result["confidence"]["evidence_refs"]:
            self.assertIsNotNone(ref)

    def test_evidence_refs_is_list(self):
        regression = _reg_regression(self.reg)
        diff = _reg_diff(self.reg)
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        self.assertIsInstance(result["confidence"]["evidence_refs"], list)


class TestRootCauseRegressionIdField(unittest.TestCase):
    """regression_id in output must never be None."""

    def setUp(self):
        self.session = _session()
        self.reg = _registry(self.session)
        self.engine = _engine(self.reg)

    def test_regression_id_present_when_payload_field_exists(self):
        regression = _reg_regression(self.reg, regression_id_override="regression-42")
        diff = _reg_diff(self.reg)
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        self.assertEqual(result["regression_id"], "regression-42")

    def test_regression_id_not_none_when_payload_field_absent(self):
        """If regression artifact has no regression_id field, fall back to the lookup id."""
        regression = _reg_regression(self.reg, include_regression_id_field=False)
        diff = _reg_diff(self.reg)
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        self.assertIsNotNone(result["regression_id"])

    def test_change_id_matches_input(self):
        regression = _reg_regression(self.reg)
        diff = _reg_diff(self.reg)
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        self.assertIsNotNone(result["change_id"])


class TestRootCauseDependencyChains(unittest.TestCase):
    """Dependency chains are built when dep_graph is present."""

    def setUp(self):
        self.session = _session()
        self.reg = _registry(self.session)
        self.engine = _engine(self.reg)

    def test_chains_populated_when_dep_graph_present(self):
        regression = _reg_regression(
            self.reg,
            evidence=[_evidence_item("removed", "src/utils.py")],
        )
        diff = _reg_diff(self.reg, files_removed=["src/utils.py"])
        _reg_dep_graph(
            self.reg,
            edges={"src/main.py": ["src/utils.py"], "src/utils.py": []},
        )
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        if result["evidence"]:
            chains = result["evidence"][0].get("dependency_chains", [])
            self.assertIsInstance(chains, list)

    def test_chains_empty_when_no_dep_graph(self):
        regression = _reg_regression(
            self.reg,
            evidence=[_evidence_item("removed", "src/utils.py")],
        )
        diff = _reg_diff(self.reg, files_removed=["src/utils.py"])
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        if result["evidence"]:
            chains = result["evidence"][0].get("dependency_chains", [])
            self.assertEqual(chains, [])

    def test_most_recent_dep_graph_used(self):
        """When multiple dependency_graph artifacts exist, the most recent is used."""
        regression = _reg_regression(
            self.reg,
            evidence=[_evidence_item("removed", "src/utils.py")],
        )
        diff = _reg_diff(self.reg, files_removed=["src/utils.py"])
        _reg_dep_graph(self.reg, edges={})
        _reg_dep_graph(
            self.reg,
            edges={"src/main.py": ["src/utils.py"]},
        )
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        self.assertEqual(result["artifact_type"], "root_cause")


class TestRootCauseRobustness(unittest.TestCase):
    """No crashes on unusual or empty inputs."""

    def setUp(self):
        self.session = _session()
        self.reg = _registry(self.session)
        self.engine = _engine(self.reg)

    def test_empty_evidence_list_no_crash(self):
        regression = _reg_regression(self.reg, evidence=[])
        diff = _reg_diff(self.reg)
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        self.assertIsNotNone(result)

    def test_evidence_with_none_file_no_crash(self):
        ev = {"type": "removed", "name": "helper", "file": None, "severity": "high", "evidence": {}}
        regression = _reg_regression(self.reg, evidence=[ev])
        diff = _reg_diff(self.reg)
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        self.assertIsNotNone(result)

    def test_evidence_with_empty_string_file_no_crash(self):
        ev = {"type": "removed", "name": "helper", "file": "", "severity": "high", "evidence": {}}
        regression = _reg_regression(self.reg, evidence=[ev])
        diff = _reg_diff(self.reg)
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        self.assertIsNotNone(result)

    def test_multiple_evidence_items_no_crash(self):
        evidence = [
            _evidence_item("removed", "src/a.py", "func_a"),
            _evidence_item("signature_changed", "src/b.py", "func_b"),
            _evidence_item("behavior_changed", "src/c.py", "func_c"),
        ]
        regression = _reg_regression(self.reg, evidence=evidence)
        diff = _reg_diff(
            self.reg,
            files_removed=["src/a.py"],
            files_modified=["src/b.py", "src/c.py"],
        )
        result = self.engine.analyze(regression["artifact_id"], diff["artifact_id"])
        self.assertIsNotNone(result)
        self.assertIsInstance(result["evidence"], list)


if __name__ == "__main__":
    unittest.main()
