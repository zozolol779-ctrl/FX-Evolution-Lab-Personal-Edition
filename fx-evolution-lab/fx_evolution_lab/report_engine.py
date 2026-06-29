from __future__ import annotations

from typing import Any, Dict, List


def _path_matches(feature_path: str, diff_path: str) -> bool:
    """Return True when feature_path and diff_path refer to the same file.

    Guards against raw ``endswith()`` false positives that arise when the diff
    path is a bare string suffix of the feature path without a separator
    boundary.  For example::

        "xsrc/utils.py".endswith("src/utils.py")  # True — wrong
        "src/utils.py".endswith("utils.py")        # True — wrong

    Only two forms are accepted as a match:

    * exact equality (``feature_path == diff_path``), or
    * ``feature_path`` ends with ``"/" + diff_path`` (diff_path is a proper
      path suffix — the preceding character must be a separator).
    """
    if not feature_path or not diff_path:
        return False
    return feature_path == diff_path or feature_path.endswith("/" + diff_path)


class ReportEngine:
    def __init__(self, session: Any, registry: Any):
        self.session = session
        self.registry = registry

    def build(self, summary: str, findings: List[Dict[str, Any]]) -> Dict[str, Any]:
        artifacts = self.registry.list_artifacts()
        diffs = [a for a in artifacts if a.get("artifact_type") == "diff"]
        features = [a for a in artifacts if a.get("artifact_type") == "feature"]
        dependencies = [a for a in artifacts if a.get("artifact_type") == "dependency_graph"]
        impacts = [a for a in artifacts if a.get("artifact_type") == "impact"]
        regressions = [a for a in artifacts if a.get("artifact_type") == "regression"]
        root_causes = [a for a in artifacts if a.get("artifact_type") == "root_cause"]

        files_added = []
        files_removed = []
        files_modified = []
        functions_added = []
        functions_removed = []
        classes_added = []
        classes_removed = []
        dependency_changes = []

        for diff in diffs:
            files_added.extend(diff.get("files_added", []) or [])
            files_removed.extend(diff.get("files_removed", []) or [])
            files_modified.extend(diff.get("files_modified", []) or [])

        for feature in features:
            kind = feature.get("kind")
            file_path = feature.get("file_path") or ""
            if kind == "function":
                if any(_path_matches(file_path, p) for p in files_added):
                    functions_added.append(feature.get("name"))
                if any(_path_matches(file_path, p) for p in files_removed):
                    functions_removed.append(feature.get("name"))
            elif kind == "class":
                if any(_path_matches(file_path, p) for p in files_added):
                    classes_added.append(feature.get("name"))
                if any(_path_matches(file_path, p) for p in files_removed):
                    classes_removed.append(feature.get("name"))

        for regression in regressions:
            for entry in regression.get("evidence", []):
                if entry.get("type") == "removed":
                    if entry.get("name") and entry.get("name") not in functions_removed:
                        functions_removed.append(entry.get("name"))
        for dep in dependencies:
            dependency_changes.extend(dep.get("cycles", []))

        risk_level = "high" if regressions or any(i.get("impact_level") == "high" for i in impacts) else "medium" if impacts else "low"

        payload = {
            "report_id": f"report-{len(artifacts) + 1}",
            "run_id": self.session.run_id,
            "summary": summary,
            "files_added": files_added,
            "files_removed": files_removed,
            "files_modified": files_modified,
            "functions_added": functions_added,
            "functions_removed": functions_removed,
            "classes_added": classes_added,
            "classes_removed": classes_removed,
            "dependency_changes": dependency_changes,
            "regressions": [r.get("regression_id") for r in regressions],
            "root_cause_findings": [r.get("root_cause_id") for r in root_causes],
            "overall_risk_level": risk_level,
            "findings": findings,
            "status": "needs_review" if findings else "complete",
        }
        return self.registry.register("report", payload)
