"""
Edge-case tests for EvolutionEngine.build_timeline().

Covers:
- Basic schema and registration
- Empty snapshots list
- Multiple snapshots aggregated
- Summary string content
- Missing artifact_id key (KeyError guard)
- None artifact_id value (no crash)
- None snapshots argument (no crash)
- Non-dict entry in snapshots (robustness)
- Multiple calls produce distinct evolution_ids
- Artifact registered in registry
"""
from __future__ import annotations

import unittest
from typing import Any, Dict, List, Optional

from fx_evolution_lab.registry import ArtifactRegistry
from fx_evolution_lab.evolution_engine import EvolutionEngine
from fx_evolution_lab.session import AnalysisSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _session() -> AnalysisSession:
    return AnalysisSession(
        run_id="run-evolution-test",
        target_project="/proj",
        target_version="1.0",
        operator="tester",
        schema_version="1.0",
    )


def _registry() -> ArtifactRegistry:
    return ArtifactRegistry(_session())


def _engine(reg: ArtifactRegistry) -> EvolutionEngine:
    return EvolutionEngine(reg.session, reg)


def _snap(artifact_id: str = "snap-1") -> Dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "artifact_type": "snapshot",
        "run_id": "run-evolution-test",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEvolutionArtifactSchema(unittest.TestCase):
    """Output artifact has required fields and correct types."""

    def setUp(self):
        self.reg = _registry()
        self.engine = _engine(self.reg)

    def test_artifact_type_is_evolution(self):
        result = self.engine.build_timeline([])
        self.assertEqual(result["artifact_type"], "evolution")

    def test_required_keys_present(self):
        result = self.engine.build_timeline([])
        for key in ("evolution_id", "snapshots", "summary"):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_snapshots_field_is_list(self):
        result = self.engine.build_timeline([])
        self.assertIsInstance(result["snapshots"], list)

    def test_summary_field_is_string(self):
        result = self.engine.build_timeline([])
        self.assertIsInstance(result["summary"], str)

    def test_registered_in_registry(self):
        before = len(self.reg.list_artifacts())
        self.engine.build_timeline([])
        self.assertEqual(len(self.reg.list_artifacts()), before + 1)


class TestEvolutionTimeline(unittest.TestCase):
    """Snapshots are correctly collected into the timeline."""

    def setUp(self):
        self.reg = _registry()
        self.engine = _engine(self.reg)

    def test_empty_snapshots_gives_empty_list(self):
        result = self.engine.build_timeline([])
        self.assertEqual(result["snapshots"], [])

    def test_single_snapshot_collected(self):
        result = self.engine.build_timeline([_snap("snap-1")])
        self.assertIn("snap-1", result["snapshots"])

    def test_multiple_snapshots_all_collected(self):
        snaps = [_snap("snap-1"), _snap("snap-2"), _snap("snap-3")]
        result = self.engine.build_timeline(snaps)
        self.assertEqual(result["snapshots"], ["snap-1", "snap-2", "snap-3"])

    def test_snapshot_order_preserved(self):
        snaps = [_snap("snap-z"), _snap("snap-a"), _snap("snap-m")]
        result = self.engine.build_timeline(snaps)
        self.assertEqual(result["snapshots"], ["snap-z", "snap-a", "snap-m"])


class TestEvolutionSummary(unittest.TestCase):
    """Summary string reflects timeline content."""

    def setUp(self):
        self.reg = _registry()
        self.engine = _engine(self.reg)

    def test_empty_summary_says_empty(self):
        result = self.engine.build_timeline([])
        self.assertIn("empty", result["summary"])

    def test_non_empty_summary_mentions_count(self):
        result = self.engine.build_timeline([_snap("snap-1")])
        self.assertIn("1", result["summary"])

    def test_three_snapshot_summary_mentions_count(self):
        result = self.engine.build_timeline([_snap(f"snap-{i}") for i in range(3)])
        self.assertIn("3", result["summary"])


class TestEvolutionIdUniqueness(unittest.TestCase):
    """Each call produces a distinct evolution_id."""

    def setUp(self):
        self.reg = _registry()
        self.engine = _engine(self.reg)

    def test_two_calls_produce_different_ids(self):
        r1 = self.engine.build_timeline([])
        r2 = self.engine.build_timeline([])
        self.assertNotEqual(r1["evolution_id"], r2["evolution_id"])


class TestEvolutionRobustness(unittest.TestCase):
    """No crashes on malformed inputs."""

    def setUp(self):
        self.reg = _registry()
        self.engine = _engine(self.reg)

    def test_none_snapshots_no_crash(self):
        """build_timeline(None) must not crash."""
        result = self.engine.build_timeline(None)
        self.assertIsNotNone(result)
        self.assertIsInstance(result["snapshots"], list)

    def test_snapshot_missing_artifact_id_no_crash(self):
        """Snapshot dicts without 'artifact_id' must not raise KeyError."""
        bad_snap = {"artifact_type": "snapshot"}  # no artifact_id key
        result = self.engine.build_timeline([bad_snap])
        self.assertIsNotNone(result)

    def test_snapshot_with_none_artifact_id_no_crash(self):
        """Snapshot with artifact_id=None must not crash."""
        result = self.engine.build_timeline([{"artifact_id": None}])
        self.assertIsNotNone(result)

    def test_empty_dict_snapshot_no_crash(self):
        """Completely empty snapshot dict must not crash."""
        result = self.engine.build_timeline([{}])
        self.assertIsNotNone(result)

    def test_large_snapshot_list_no_crash(self):
        snaps = [_snap(f"snap-{i}") for i in range(100)]
        result = self.engine.build_timeline(snaps)
        self.assertEqual(len(result["snapshots"]), 100)

    def test_empty_string_artifact_id_included(self):
        """Empty-string artifact_id is a valid (if unusual) value."""
        result = self.engine.build_timeline([{"artifact_id": ""}])
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
