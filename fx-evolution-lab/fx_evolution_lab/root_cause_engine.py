from __future__ import annotations

from typing import Any, Dict


class RootCauseEngine:
    def __init__(self, session: Any, registry: Any):
        self.session = session
        self.registry = registry

    def analyze(self, regression_id: str, change_id: str) -> Dict[str, Any]:
        # locate regression, diff and dependency graph artifacts
        regression = next((a for a in self.registry.list_artifacts() if a.get("artifact_type") == "regression" and (a.get("artifact_id") == regression_id or a.get("regression_id") == regression_id)), None)
        if not regression:
            raise KeyError(f"regression {regression_id} not found")

        diff = next((a for a in self.registry.list_artifacts() if a.get("artifact_type") == "diff" and (a.get("artifact_id") == change_id or a.get("change_id") == change_id)), None)

        dep_graph = next((a for a in reversed(self.registry.list_artifacts()) if a.get("artifact_type") == "dependency_graph"), None)

        evidence = []
        for item in regression.get("evidence", []):
            if item.get("type") in {"removed", "signature_changed"}:
                file = item.get("file")
                related = []
                if diff:
                    if file and any(str(f).endswith(file) for f in diff.get("files_removed", [])):
                        related.append({"diff": diff.get("artifact_id")})
                    if file and any(str(f).endswith(file) for f in diff.get("files_modified", [])):
                        related.append({"diff": diff.get("artifact_id")})

                chains = []
                if dep_graph:
                    edges = dep_graph.get("edges", {})
                    # build reverse mapping
                    rev = {}
                    for s, ts in edges.items():
                        for t in ts:
                            rev.setdefault(t, []).append(s)

                    # find chains leading to the file
                    stack = [[file]]
                    while stack:
                        path = stack.pop()
                        node = path[-1]
                        for prev in rev.get(node, []):
                            if prev in path:
                                continue
                            newp = path + [prev]
                            chains.append(newp)
                            stack.append(newp)

                evidence.append({"regression_item": item, "related_diff": related, "dependency_chains": chains})

        confidence_score = 0.8 if any(e.get("related_diff") for e in evidence) else 0.3

        payload = {
            "root_cause_id": f"root-cause-{len(self.registry.list_artifacts()) + 1}",
            "regression_id": regression.get("regression_id"),
            "change_id": change_id,
            "confidence": {"score": confidence_score, "level": "high" if confidence_score >= 0.7 else "low", "reasoning": "Correlation between removed features and diffs/dependencies", "evidence_refs": [diff.get("artifact_id") if diff else None, dep_graph.get("artifact_id") if dep_graph else None]},
            "reasoning": "; ".join([str(e) for e in evidence]),
            "evidence": evidence,
        }
        return self.registry.register("root_cause", payload)
