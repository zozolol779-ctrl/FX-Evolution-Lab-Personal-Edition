from __future__ import annotations

from typing import Any, Dict, List


class ImpactEngine:
    def __init__(self, session: Any, registry: Any):
        self.session = session
        self.registry = registry

    def assess(self, change_id: str) -> Dict[str, Any]:
        # locate the diff artifact by artifact_id or change_id for compatibility
        diff = None
        for a in self.registry.list_artifacts():
            if a.get("artifact_type") == "diff" and (a.get("artifact_id") == change_id or a.get("change_id") == change_id):
                diff = a
                break

        if not diff:
            # fallback: create a lightweight impact from the supplied identifier when no diff exists
            payload = {
                "impact_id": f"impact-{len(self.registry.list_artifacts()) + 1}",
                "change_id": change_id,
                "affected_features": [],
                "affected_modules": [],
                "impact_level": "low",
                "confidence": {"score": 0.1, "level": "low", "reasoning": "No matching diff artifact found", "evidence_refs": []},
            }
            return self.registry.register("impact", payload)

        # gather affected files from diff
        affected_files = set()
        for k in ("files_added", "files_removed", "files_modified"):
            for p in diff.get(k, []) or []:
                affected_files.add(p)
        for old, new in diff.get("files_renamed", []) or []:
            affected_files.add(old)
            affected_files.add(new)

        # find latest dependency_graph artifact
        dep_graph = None
        for a in reversed(self.registry.list_artifacts()):
            if a.get("artifact_type") == "dependency_graph":
                dep_graph = a
                break

        edges = dep_graph.get("edges", {}) if dep_graph else {}

        # build reverse edges
        reverse = {}
        for src, targets in edges.items():
            for t in targets:
                reverse.setdefault(t, []).append(src)

        # BFS to find dependents of affected files
        impacted = set()
        queue = list(affected_files)
        while queue:
            current = queue.pop(0)
            if current in impacted:
                continue
            impacted.add(current)
            for dep in reverse.get(current, []):
                if dep not in impacted:
                    queue.append(dep)

        # find affected features by file_path
        features = [f for f in self.registry.list_artifacts() if f.get("artifact_type") == "feature"]
        affected_features = [f for f in features if any(str(f.get("file_path", "")).endswith(p) for p in impacted)]

        # determine impact level deterministically
        impact_level = "low"
        if any(p for p in diff.get("files_removed", [])):
            impact_level = "high"
        elif affected_features and len(affected_features) >= 3:
            impact_level = "medium"

        confidence_score = 0.9 if impact_level == "high" else (0.6 if impact_level == "medium" else 0.2)

        payload = {
            "impact_id": f"impact-{len(self.registry.list_artifacts()) + 1}",
            "change_id": change_id,
            "affected_features": [f.get("feature_id") for f in affected_features],
            "affected_modules": sorted(list(impacted)),
            "impact_level": impact_level,
            "confidence": {"score": confidence_score, "level": impact_level, "reasoning": "Derived from diff and dependency graph", "evidence_refs": [diff.get("artifact_id")]},
        }
        return self.registry.register("impact", payload)
