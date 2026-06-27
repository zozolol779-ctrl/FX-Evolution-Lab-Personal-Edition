from __future__ import annotations

from collections import deque
from typing import Any, Dict, List


def _file_path_matches(file_path: Any, rel_path: str) -> bool:
    """Return True when ``file_path`` refers to the same file as ``rel_path``.

    Guards against false positives like ``old_src/utils.py`` matching the
    relative path ``src/utils.py`` (they share the suffix ``src/utils.py``
    but ``old_src`` ≠ ``src``).

    A match requires either:
    - Exact equality (both are the same string), or
    - ``file_path`` ends with ``"/" + rel_path`` (directory-separator boundary).
    """
    if not file_path:
        return False
    fp = str(file_path)
    return fp == rel_path or fp.endswith("/" + rel_path)


class ImpactEngine:
    def __init__(self, session: Any, registry: Any):
        self.session = session
        self.registry = registry

    def assess(self, change_id: str) -> Dict[str, Any]:
        # Locate the diff artifact by artifact_id or change_id field
        diff = None
        for a in self.registry.list_artifacts():
            if a.get("artifact_type") == "diff" and (
                a.get("artifact_id") == change_id or a.get("change_id") == change_id
            ):
                diff = a
                break

        if not diff:
            # Fallback: create a lightweight impact when no diff artifact exists
            payload = {
                "impact_id": f"impact-{len(self.registry.list_artifacts()) + 1}",
                "change_id": change_id,
                "affected_features": [],
                "affected_modules": [],
                "impact_level": "low",
                "confidence": {
                    "score": 0.1,
                    "level": "low",
                    "reasoning": "No matching diff artifact found",
                    "evidence_refs": [],
                },
            }
            return self.registry.register("impact", payload)

        # Gather directly affected files from the diff
        affected_files: set = set()
        for k in ("files_added", "files_removed", "files_modified"):
            for p in diff.get(k, []) or []:
                affected_files.add(p)
        for old, new in diff.get("files_renamed", []) or []:
            affected_files.add(old)
            affected_files.add(new)

        # Find the most recent dependency_graph artifact (if any)
        dep_graph = None
        for a in reversed(self.registry.list_artifacts()):
            if a.get("artifact_type") == "dependency_graph":
                dep_graph = a
                break

        edges = dep_graph.get("edges", {}) if dep_graph else {}

        # Build reverse edges: target → [sources that depend on it]
        reverse: Dict[str, List[str]] = {}
        for src, targets in edges.items():
            for t in targets:
                reverse.setdefault(t, []).append(src)

        # BFS (O(n) with deque) to collect all transitively impacted modules
        impacted: set = set()
        queue: deque = deque(affected_files)
        while queue:
            current = queue.popleft()
            if current in impacted:
                continue
            impacted.add(current)
            for dep in reverse.get(current, []):
                if dep not in impacted:
                    queue.append(dep)

        # Match features by file path with directory-separator boundary guard
        features = [
            f for f in self.registry.list_artifacts()
            if f.get("artifact_type") == "feature"
        ]
        affected_features = [
            f for f in features
            if any(_file_path_matches(f.get("file_path"), p) for p in impacted)
        ]

        # Determine impact level
        impact_level = "low"
        if any(diff.get("files_removed", [])):
            impact_level = "high"
        elif affected_features and len(affected_features) >= 3:
            impact_level = "medium"

        confidence_score = (
            0.9 if impact_level == "high"
            else 0.6 if impact_level == "medium"
            else 0.2
        )

        payload = {
            "impact_id": f"impact-{len(self.registry.list_artifacts()) + 1}",
            "change_id": change_id,
            "affected_features": [f.get("artifact_id") for f in affected_features],
            "affected_modules": sorted(impacted),
            "impact_level": impact_level,
            "confidence": {
                "score": confidence_score,
                "level": impact_level,
                "reasoning": "Derived from diff and dependency graph",
                "evidence_refs": [diff.get("artifact_id")],
            },
        }
        return self.registry.register("impact", payload)
