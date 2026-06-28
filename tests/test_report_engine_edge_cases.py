"""
Edge-case tests for ReportEngine.build().

Covers:
- Basic schema and registration
- Path matching (endswith false-positive bug)
- Nested directory paths
- files_added / files_removed / files_modified aggregation
- functions_added / functions_removed classification
- classes_added / classes_removed classification
- Regression evidence supplementing functions_removed
- dependency_changes from dependency_graph cycles
- risk_level logic (low / medium / high)
- status field (complete vs needs_review)
- Missing / None artifact fields
- Empty registry
- Duplicate feature names not double-counted
- Malformed diff entries (None lists)
- Multiple diffs aggregated
- findings list reflected in output
"""
from __future__ import annotations

import unittest
from typing import Any, Dict, List, Optional

from fx_evolution_lab.registry import ArtifactRegistry
from fx_evolution_lab.report_engine import ReportEngine
from fx_evolution_lab.session import AnalysisSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _session() -> AnalysisSession:
    return AnalysisSession(
        run_id="run-report-test",
        target_project="/proj",
        target_version="1.0",
        operator="tester",
        schema_version="1.0",
    )


def _registry() -> ArtifactRegistry:
    return ArtifactRegistry(_session())


def _engine(reg: ArtifactRegistry) -> ReportEngine:
    return ReportEngine(reg.session, reg)


def _reg_diff(
    reg: ArtifactRegistry,
    files_added: Optional[List[str]] = None,
    files_removed: Optional[List[str]] = None,
    files_modified: Optional[List[str]] = None,
) -> Dict[str, Any]:
    payload = {
        "change_id": f"change-{len(reg.list_artifacts()) + 1}",
        "old_snapshot": "snap-old",
        "new_snapshot": "snap-new",
        "change_type": "modified",
        "files_added": files_added or [],
        "files_removed": files_removed or [],
        "files_modified": files_modified or [],
        "files_renamed": [],
        "lines_added": 0,
        "lines_removed": 0,
        "similarity": 1.0,
        "file_diffs": {},
    }
    return reg.register("diff", payload)


def _reg_feature(
    reg: ArtifactRegistry,
    name: str,
    kind: str = "function",
    file_path: str = "src/utils.py",
) -> Dict[str, Any]:
    payload = {
        "feature_id": f"feature-{len(reg.list_artifacts()) + 1}",
        "name": name,
        "kind": kind,
        "signature": f"{name}()",
        "file_path": file_path,
        "line_start": 1,
        "line_end": 5,
    }
    return reg.register("feature", payload)


def _reg_impact(
    reg: ArtifactRegistry,
    impact_level: str = "low",
) -> Dict[str, Any]:
    payload = {
        "impact_id": f"impact-{len(reg.list_artifacts()) + 1}",
        "change_id": "change-1",
        "affected_features": [],
        "affected_modules": [],
        "impact_level": impact_level,
        "confidence": {"score": 0.5, "level": impact_level, "reasoning": "", "evidence_refs": []},
    }
    return reg.register("impact", payload)


def _reg_regression(
    reg: ArtifactRegistry,
    evidence: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    payload = {
        "regression_id": f"regression-{len(reg.list_artifacts()) + 1}",
        "severity": "high",
        "impacted_feature": "helper",
        "impact_id": "impact-1",
        "evidence": evidence or [],
    }
    return reg.register("regression", payload)


def _reg_root_cause(reg: ArtifactRegistry) -> Dict[str, Any]:
    payload = {
        "root_cause_id": f"root-cause-{len(reg.list_artifacts()) + 1}",
        "regression_id": "regression-1",
        "change_id": "change-1",
        "confidence": {"score": 0.8, "level": "high", "reasoning": "", "evidence_refs": []},
        "reasoning": "test",
        "evidence": [],
    }
    return reg.register("root_cause", payload)


def _reg_dep_graph(
    reg: ArtifactRegistry,
    cycles: Optional[List] = None,
) -> Dict[str, Any]:
    payload = {
        "dependency_id": f"dependency-{len(reg.list_artifacts()) + 1}",
        "edges": {},
        "modules": [],
        "cycle_detected": bool(cycles),
        "cycles": cycles or [],
    }
    return reg.register("dependency_graph", payload)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestReportArtifactSchema(unittest.TestCase):
    """Output artifact has required fields and correct types."""

    def setUp(self):
        self.reg = _registry()
        self.engine = _engine(self.reg)

    def test_artifact_type_is_report(self):
        result = self.engine.build("summary", [])
        self.assertEqual(result["artifact_type"], "report")

    def test_required_keys_present(self):
        result = self.engine.build("summary", [])
        for key in (
            "report_id", "run_id", "summary",
            "files_added", "files_removed", "files_modified",
            "functions_added", "functions_removed",
            "classes_added", "classes_removed",
            "dependency_changes", "regressions", "root_cause_findings",
            "overall_risk_level", "findings", "status",
        ):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_run_id_matches_session(self):
        result = self.engine.build("summary", [])
        self.assertEqual(result["run_id"], self.reg.session.run_id)

    def test_summary_stored(self):
        result = self.engine.build("test summary text", [])
        self.assertEqual(result["summary"], "test summary text")

    def test_registered_in_registry(self):
        before = len(self.reg.list_artifacts())
        self.engine.build("summary", [])
        self.assertEqual(len(self.reg.list_artifacts()), before + 1)


class TestReportStatus(unittest.TestCase):
    """status field: 'complete' when no findings, 'needs_review' when findings present."""

    def setUp(self):
        self.reg = _registry()
        self.engine = _engine(self.reg)

    def test_status_complete_when_no_findings(self):
        result = self.engine.build("ok", [])
        self.assertEqual(result["status"], "complete")

    def test_status_needs_review_when_findings_present(self):
        result = self.engine.build("ok", [{"issue": "something"}])
        self.assertEqual(result["status"], "needs_review")

    def test_findings_stored_in_output(self):
        findings = [{"issue": "bug"}, {"issue": "risk"}]
        result = self.engine.build("ok", findings)
        self.assertEqual(result["findings"], findings)

    def test_empty_findings_list_complete(self):
        result = self.engine.build("ok", [])
        self.assertEqual(result["status"], "complete")


class TestReportRiskLevel(unittest.TestCase):
    """overall_risk_level: low / medium / high."""

    def setUp(self):
        self.reg = _registry()
        self.engine = _engine(self.reg)

    def test_risk_low_when_empty_registry(self):
        result = self.engine.build("summary", [])
        self.assertEqual(result["overall_risk_level"], "low")

    def test_risk_medium_when_impacts_present(self):
        _reg_impact(self.reg, "low")
        result = self.engine.build("summary", [])
        self.assertEqual(result["overall_risk_level"], "medium")

    def test_risk_high_when_high_impact(self):
        _reg_impact(self.reg, "high")
        result = self.engine.build("summary", [])
        self.assertEqual(result["overall_risk_level"], "high")

    def test_risk_high_when_regression_present(self):
        _reg_regression(self.reg)
        result = self.engine.build("summary", [])
        self.assertEqual(result["overall_risk_level"], "high")

    def test_risk_high_takes_priority_over_medium(self):
        _reg_impact(self.reg, "low")
        _reg_regression(self.reg)
        result = self.engine.build("summary", [])
        self.assertEqual(result["overall_risk_level"], "high")


class TestReportFilesAggregation(unittest.TestCase):
    """files_added / files_removed / files_modified come from diff artifacts."""

    def setUp(self):
        self.reg = _registry()
        self.engine = _engine(self.reg)

    def test_files_added_from_diff(self):
        _reg_diff(self.reg, files_added=["src/new.py"])
        result = self.engine.build("summary", [])
        self.assertIn("src/new.py", result["files_added"])

    def test_files_removed_from_diff(self):
        _reg_diff(self.reg, files_removed=["src/old.py"])
        result = self.engine.build("summary", [])
        self.assertIn("src/old.py", result["files_removed"])

    def test_files_modified_from_diff(self):
        _reg_diff(self.reg, files_modified=["src/utils.py"])
        result = self.engine.build("summary", [])
        self.assertIn("src/utils.py", result["files_modified"])

    def test_multiple_diffs_aggregated(self):
        _reg_diff(self.reg, files_added=["a.py"])
        _reg_diff(self.reg, files_added=["b.py"])
        result = self.engine.build("summary", [])
        self.assertIn("a.py", result["files_added"])
        self.assertIn("b.py", result["files_added"])

    def test_no_diffs_gives_empty_lists(self):
        result = self.engine.build("summary", [])
        self.assertEqual(result["files_added"], [])
        self.assertEqual(result["files_removed"], [])
        self.assertEqual(result["files_modified"], [])

    def test_diff_with_none_lists_no_crash(self):
        """Diff artifacts with None for file lists must not crash."""
        payload = {
            "change_id": "change-null",
            "files_added": None,
            "files_removed": None,
            "files_modified": None,
            "files_renamed": [],
        }
        self.reg.register("diff", payload)
        result = self.engine.build("summary", [])
        self.assertIsNotNone(result)


class TestReportFunctionsAdded(unittest.TestCase):
    """functions_added: features of kind='function' in an added file."""

    def setUp(self):
        self.reg = _registry()
        self.engine = _engine(self.reg)

    def test_function_in_added_file_is_reported(self):
        _reg_diff(self.reg, files_added=["src/new.py"])
        _reg_feature(self.reg, "my_func", "function", "src/new.py")
        result = self.engine.build("summary", [])
        self.assertIn("my_func", result["functions_added"])

    def test_function_NOT_in_added_file_is_not_reported(self):
        _reg_diff(self.reg, files_added=["src/new.py"])
        _reg_feature(self.reg, "other_func", "function", "src/unchanged.py")
        result = self.engine.build("summary", [])
        self.assertNotIn("other_func", result["functions_added"])

    def test_class_in_added_file_not_in_functions_added(self):
        _reg_diff(self.reg, files_added=["src/new.py"])
        _reg_feature(self.reg, "MyClass", "class", "src/new.py")
        result = self.engine.build("summary", [])
        self.assertNotIn("MyClass", result["functions_added"])

    def test_no_false_positive_path_prefix(self):
        """old_src/utils.py added must NOT match feature at src/utils.py."""
        _reg_diff(self.reg, files_added=["old_src/utils.py"])
        _reg_feature(self.reg, "helper", "function", "src/utils.py")
        result = self.engine.build("summary", [])
        self.assertNotIn(
            "helper",
            result["functions_added"],
            "old_src/utils.py must NOT match feature at src/utils.py",
        )

    def test_no_false_positive_xsrc_prefix(self):
        """xsrc/utils.py added must NOT match feature at src/utils.py."""
        _reg_diff(self.reg, files_added=["xsrc/utils.py"])
        _reg_feature(self.reg, "helper", "function", "src/utils.py")
        result = self.engine.build("summary", [])
        self.assertNotIn("helper", result["functions_added"])

    def test_nested_directory_exact_match(self):
        """Feature at a/b/c/utils.py must match diff path a/b/c/utils.py."""
        _reg_diff(self.reg, files_added=["a/b/c/utils.py"])
        _reg_feature(self.reg, "deep_func", "function", "a/b/c/utils.py")
        result = self.engine.build("summary", [])
        self.assertIn("deep_func", result["functions_added"])

    def test_nested_directory_boundary_guard(self):
        """Feature at b/c/utils.py must NOT match diff path a/b/c/utils.py."""
        _reg_diff(self.reg, files_added=["a/b/c/utils.py"])
        _reg_feature(self.reg, "deep_func", "function", "b/c/utils.py")
        result = self.engine.build("summary", [])
        self.assertNotIn("deep_func", result["functions_added"])

    def test_filename_only_no_false_positive(self):
        """utils.py alone (no dir) must NOT match src/utils.py in the diff."""
        _reg_diff(self.reg, files_added=["src/utils.py"])
        _reg_feature(self.reg, "lone_func", "function", "utils.py")
        result = self.engine.build("summary", [])
        self.assertNotIn("lone_func", result["functions_added"])

    def test_function_with_none_file_path_no_crash(self):
        _reg_diff(self.reg, files_added=["src/new.py"])
        payload = {"feature_id": "f-x", "name": "no_path", "kind": "function", "file_path": None}
        self.reg.register("feature", payload)
        result = self.engine.build("summary", [])
        self.assertIsNotNone(result)


class TestReportFunctionsRemoved(unittest.TestCase):
    """functions_removed: features of kind='function' in a removed file."""

    def setUp(self):
        self.reg = _registry()
        self.engine = _engine(self.reg)

    def test_function_in_removed_file_is_reported(self):
        _reg_diff(self.reg, files_removed=["src/old.py"])
        _reg_feature(self.reg, "gone_func", "function", "src/old.py")
        result = self.engine.build("summary", [])
        self.assertIn("gone_func", result["functions_removed"])

    def test_no_false_positive_on_removed_path(self):
        """old_src/utils.py removed must NOT match feature at src/utils.py."""
        _reg_diff(self.reg, files_removed=["old_src/utils.py"])
        _reg_feature(self.reg, "helper", "function", "src/utils.py")
        result = self.engine.build("summary", [])
        self.assertNotIn(
            "helper",
            result["functions_removed"],
            "old_src/utils.py must NOT match feature at src/utils.py",
        )

    def test_nested_removed_boundary_guard(self):
        """Feature at b/c/gone.py must NOT match diff path a/b/c/gone.py."""
        _reg_diff(self.reg, files_removed=["a/b/c/gone.py"])
        _reg_feature(self.reg, "nested_func", "function", "b/c/gone.py")
        result = self.engine.build("summary", [])
        self.assertNotIn("nested_func", result["functions_removed"])

    def test_regression_evidence_supplements_functions_removed(self):
        """Removed function from regression evidence appears in functions_removed
        even when no diff file list covers it."""
        _reg_regression(
            self.reg,
            evidence=[{"type": "removed", "name": "ev_func", "file": "src/old.py", "severity": "high", "evidence": {}}],
        )
        result = self.engine.build("summary", [])
        self.assertIn("ev_func", result["functions_removed"])

    def test_regression_evidence_no_duplicate(self):
        """Function already in functions_removed from diff must not appear twice."""
        _reg_diff(self.reg, files_removed=["src/old.py"])
        _reg_feature(self.reg, "dup_func", "function", "src/old.py")
        _reg_regression(
            self.reg,
            evidence=[{"type": "removed", "name": "dup_func", "file": "src/old.py", "severity": "high", "evidence": {}}],
        )
        result = self.engine.build("summary", [])
        self.assertEqual(result["functions_removed"].count("dup_func"), 1)

    def test_regression_evidence_none_name_no_crash(self):
        _reg_regression(
            self.reg,
            evidence=[{"type": "removed", "name": None, "file": "src/old.py", "severity": "high", "evidence": {}}],
        )
        result = self.engine.build("summary", [])
        self.assertIsNotNone(result)

    def test_regression_evidence_non_removed_type_ignored(self):
        _reg_regression(
            self.reg,
            evidence=[{"type": "signature_changed", "name": "sig_func", "file": "src/old.py", "severity": "medium", "evidence": {}}],
        )
        result = self.engine.build("summary", [])
        self.assertNotIn("sig_func", result["functions_removed"])


class TestReportClassesAddedRemoved(unittest.TestCase):
    """classes_added / classes_removed from feature artifacts of kind='class'."""

    def setUp(self):
        self.reg = _registry()
        self.engine = _engine(self.reg)

    def test_class_in_added_file_reported(self):
        _reg_diff(self.reg, files_added=["src/models.py"])
        _reg_feature(self.reg, "MyModel", "class", "src/models.py")
        result = self.engine.build("summary", [])
        self.assertIn("MyModel", result["classes_added"])

    def test_class_in_removed_file_reported(self):
        _reg_diff(self.reg, files_removed=["src/models.py"])
        _reg_feature(self.reg, "OldModel", "class", "src/models.py")
        result = self.engine.build("summary", [])
        self.assertIn("OldModel", result["classes_removed"])

    def test_no_false_positive_class_path(self):
        """old_src/models.py removed must NOT match class at src/models.py."""
        _reg_diff(self.reg, files_removed=["old_src/models.py"])
        _reg_feature(self.reg, "SafeModel", "class", "src/models.py")
        result = self.engine.build("summary", [])
        self.assertNotIn("SafeModel", result["classes_removed"])

    def test_method_kind_not_in_classes_or_functions(self):
        """Methods (kind='method') should not appear in classes_added or functions_added."""
        _reg_diff(self.reg, files_added=["src/models.py"])
        payload = {"feature_id": "f-m", "name": "__init__", "kind": "method", "file_path": "src/models.py"}
        self.reg.register("feature", payload)
        result = self.engine.build("summary", [])
        self.assertNotIn("__init__", result["classes_added"])
        self.assertNotIn("__init__", result["functions_added"])


class TestReportDependencyChanges(unittest.TestCase):
    """dependency_changes comes from cycles in dependency_graph artifacts."""

    def setUp(self):
        self.reg = _registry()
        self.engine = _engine(self.reg)

    def test_no_dep_graph_empty_dependency_changes(self):
        result = self.engine.build("summary", [])
        self.assertEqual(result["dependency_changes"], [])

    def test_cycles_appear_in_dependency_changes(self):
        _reg_dep_graph(self.reg, cycles=[["a.py", "b.py", "a.py"]])
        result = self.engine.build("summary", [])
        self.assertIn(["a.py", "b.py", "a.py"], result["dependency_changes"])

    def test_no_cycles_empty_dependency_changes(self):
        _reg_dep_graph(self.reg, cycles=[])
        result = self.engine.build("summary", [])
        self.assertEqual(result["dependency_changes"], [])

    def test_multiple_dep_graphs_aggregated(self):
        _reg_dep_graph(self.reg, cycles=[["a.py", "b.py"]])
        _reg_dep_graph(self.reg, cycles=[["c.py", "d.py"]])
        result = self.engine.build("summary", [])
        self.assertIn(["a.py", "b.py"], result["dependency_changes"])
        self.assertIn(["c.py", "d.py"], result["dependency_changes"])


class TestReportRegressionsAndRootCauses(unittest.TestCase):
    """regressions and root_cause_findings list IDs from registered artifacts."""

    def setUp(self):
        self.reg = _registry()
        self.engine = _engine(self.reg)

    def test_regressions_list_regression_ids(self):
        _reg_regression(self.reg)
        result = self.engine.build("summary", [])
        self.assertEqual(len(result["regressions"]), 1)

    def test_root_cause_findings_list_root_cause_ids(self):
        _reg_root_cause(self.reg)
        result = self.engine.build("summary", [])
        self.assertEqual(len(result["root_cause_findings"]), 1)

    def test_multiple_regressions_all_listed(self):
        _reg_regression(self.reg)
        _reg_regression(self.reg)
        result = self.engine.build("summary", [])
        self.assertEqual(len(result["regressions"]), 2)

    def test_empty_registry_empty_lists(self):
        result = self.engine.build("summary", [])
        self.assertEqual(result["regressions"], [])
        self.assertEqual(result["root_cause_findings"], [])


class TestReportRobustness(unittest.TestCase):
    """No crashes on unusual inputs."""

    def setUp(self):
        self.reg = _registry()
        self.engine = _engine(self.reg)

    def test_empty_registry_no_crash(self):
        result = self.engine.build("empty", [])
        self.assertIsNotNone(result)

    def test_empty_summary_string(self):
        result = self.engine.build("", [])
        self.assertEqual(result["summary"], "")

    def test_feature_with_missing_kind_no_crash(self):
        _reg_diff(self.reg, files_added=["src/new.py"])
        payload = {"feature_id": "f-nk", "name": "no_kind", "file_path": "src/new.py"}
        self.reg.register("feature", payload)
        result = self.engine.build("summary", [])
        self.assertIsNotNone(result)

    def test_regression_with_no_evidence_key_no_crash(self):
        payload = {"regression_id": "regression-x", "severity": "low"}
        self.reg.register("regression", payload)
        result = self.engine.build("summary", [])
        self.assertIsNotNone(result)

    def test_impact_with_no_impact_level_no_crash(self):
        payload = {"impact_id": "impact-x", "change_id": "change-1"}
        self.reg.register("impact", payload)
        result = self.engine.build("summary", [])
        self.assertIsNotNone(result)

    def test_large_findings_list_no_crash(self):
        findings = [{"issue": f"bug-{i}"} for i in range(100)]
        result = self.engine.build("summary", findings)
        self.assertEqual(len(result["findings"]), 100)


if __name__ == "__main__":
    unittest.main()
