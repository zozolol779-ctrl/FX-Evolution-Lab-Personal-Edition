from __future__ import annotations

from typing import Any, Dict, List, Optional


# Evidence types that trigger root-cause analysis.
# "removed"          — function/class was deleted entirely
# "signature_changed"— call contract broke
# "behavior_changed" — kind/decorator/parent changed (structural, not just positional)
_ANALYSED_EVIDENCE_TYPES = frozenset({"removed", "signature_changed", "behavior_changed"})


def _file_matches(evidence_file: Optional[str], diff_path: str) -> bool:
    """Return True when *diff_path* refers to the same file as *evidence_file*.

    Uses a directory-separator boundary guard to prevent false positives:
    ``old_src/utils.py`` must NOT match ``src/utils.py``.

    A match requires either:
    - Exact equality, or
    - ``diff_path`` ends with ``"/" + evidence_file`` (directory boundary).
    """
    if not evidence_file:
        return False
    ef = str(evidence_file)
    dp = str(diff_path)
    return dp == ef or dp.endswith("/" + ef)


class RootCauseEngine:
    def __init__(self, session: Any, registry: Any) -> None:
        self.session = session
        self.registry = registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, regression_id: str, change_id: str) -> Dict[str, Any]:
        """Correlate a regression with its root cause in the diff and dependency graph.

        Parameters
        ----------
        regression_id : artifact_id OR regression_id payload field of a regression artifact
        change_id     : artifact_id OR change_id payload field of a diff artifact

        Returns
        -------
        Registered ``root_cause`` artifact with keys:
            root_cause_id, regression_id, change_id, confidence,
            reasoning, evidence
        """
        regression = self._find_regression(regression_id)
        if not regression:
            raise KeyError(f"regression {regression_id!r} not found")

        diff = self._find_diff(change_id)
        dep_graph = self._latest_dep_graph()

        evidence = self._build_evidence(regression, diff, dep_graph)

        has_related_diff = any(e.get("related_diff") for e in evidence)
        confidence_score = 0.8 if has_related_diff else 0.3
        confidence_level = (
            "high" if confidence_score >= 0.7
            else "medium" if confidence_score >= 0.5
            else "low"
        )

        # Collect non-None artifact IDs for evidence_refs
        evidence_ref_ids: List[str] = []
        if diff:
            aid = diff.get("artifact_id")
            if aid is not None:
                evidence_ref_ids.append(aid)
        if dep_graph:
            aid = dep_graph.get("artifact_id")
            if aid is not None:
                evidence_ref_ids.append(aid)

        payload: Dict[str, Any] = {
            "root_cause_id": f"root-cause-{len(self.registry.list_artifacts()) + 1}",
            # regression_id from payload field; fall back to the lookup key so it is
            # never None even when the payload field is absent.
            "regression_id": regression.get("regression_id") or regression_id,
            "change_id": change_id,
            "confidence": {
                "score": confidence_score,
                "level": confidence_level,
                "reasoning": "Correlation between changed features and diffs/dependencies",
                "evidence_refs": evidence_ref_ids,
            },
            "reasoning": "; ".join(str(e) for e in evidence) if evidence else "No correlated evidence found",
            "evidence": evidence,
        }
        return self.registry.register("root_cause", payload)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _find_regression(self, regression_id: str) -> Optional[Dict[str, Any]]:
        """Find a regression artifact by artifact_id OR regression_id payload field."""
        for a in self.registry.list_artifacts():
            if a.get("artifact_type") == "regression" and (
                a.get("artifact_id") == regression_id
                or a.get("regression_id") == regression_id
            ):
                return a
        return None

    def _find_diff(self, change_id: str) -> Optional[Dict[str, Any]]:
        """Find a diff artifact by artifact_id OR change_id payload field."""
        for a in self.registry.list_artifacts():
            if a.get("artifact_type") == "diff" and (
                a.get("artifact_id") == change_id
                or a.get("change_id") == change_id
            ):
                return a
        return None

    def _latest_dep_graph(self) -> Optional[Dict[str, Any]]:
        """Return the most recently registered dependency_graph artifact, or None."""
        for a in reversed(self.registry.list_artifacts()):
            if a.get("artifact_type") == "dependency_graph":
                return a
        return None

    def _build_evidence(
        self,
        regression: Dict[str, Any],
        diff: Optional[Dict[str, Any]],
        dep_graph: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Correlate each regression evidence item with diff entries and dependency chains."""
        evidence: List[Dict[str, Any]] = []

        edges: Dict[str, List[str]] = dep_graph.get("edges", {}) if dep_graph else {}

        # Build reverse edge map: target → [sources that depend on it]
        rev: Dict[str, List[str]] = {}
        for src, targets in edges.items():
            for t in targets:
                rev.setdefault(t, []).append(src)

        for item in regression.get("evidence", []):
            if item.get("type") not in _ANALYSED_EVIDENCE_TYPES:
                continue

            file = item.get("file") or ""

            # Correlate with diff using boundary-guarded matching
            related: List[Dict[str, Any]] = []
            if diff:
                diff_aid = diff.get("artifact_id")
                removed_files = diff.get("files_removed", []) or []
                modified_files = diff.get("files_modified", []) or []
                if file and any(_file_matches(file, f) for f in removed_files):
                    related.append({"diff": diff_aid})
                elif file and any(_file_matches(file, f) for f in modified_files):
                    related.append({"diff": diff_aid})

            # Build dependency chains leading to the file (bounded DFS)
            chains: List[List[str]] = []
            if file and dep_graph:
                stack: List[List[str]] = [[file]]
                while stack:
                    path = stack.pop()
                    node = path[-1]
                    for prev in rev.get(node, []):
                        if prev in path:
                            continue
                        new_path = path + [prev]
                        chains.append(new_path)
                        stack.append(new_path)

            evidence.append({
                "regression_item": item,
                "related_diff": related,
                "dependency_chains": chains,
            })

        return evidence
