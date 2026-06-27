from __future__ import annotations

from typing import Any, Dict, List


class ManifestSchema:
    @staticmethod
    def from_data(data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "schema_version": data.get("schema_version", "1.0"),
            "generated_at": data.get("generated_at"),
            "root_path": data.get("root_path"),
            "files": data.get("files", []),
        }


class SnapshotSchema:
    @staticmethod
    def create(session: Any, registry: Any, manifest: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "snapshot_id": f"snapshot-{len(registry.list_artifacts()) + 1}",
            "manifest_id": "manifest-1",
            "timestamp": session.started_at,
            "project_version": session.target_version,
        }
        return registry.register("snapshot", payload)


class DiffSchema:
    @staticmethod
    def create(session: Any, registry: Any, old_snapshot: Dict[str, Any], new_snapshot: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "change_id": f"change-{len(registry.list_artifacts()) + 1}",
            "old_snapshot": old_snapshot["artifact_id"],
            "new_snapshot": new_snapshot["artifact_id"],
            "change_type": "unchanged",
            "old_file_id": None,
            "new_file_id": None,
            "lines_added": 0,
            "lines_removed": 0,
            "similarity": 1.0,
        }
        return registry.register("diff", payload)


class FeatureSchema:
    @staticmethod
    def create(session: Any, registry: Any, module_name: str, name: str) -> Dict[str, Any]:
        payload = {
            "feature_id": f"feature-{len(registry.list_artifacts()) + 1}",
            "module_id": f"module-{module_name}",
            "name": name,
            "kind": "function",
            "signature": None,
            "complexity": 1,
            "line_start": 1,
            "line_end": 1,
            "dependencies": [],
        }
        return registry.register("feature", payload)


class DependencySchema:
    @staticmethod
    def create(session: Any, registry: Any, source_module: str, target_module: str) -> Dict[str, Any]:
        payload = {
            "dependency_id": f"dependency-{len(registry.list_artifacts()) + 1}",
            "source_module": source_module,
            "target_module": target_module,
            "dependency_type": "import",
            "resolved": True,
        }
        return registry.register("dependency", payload)


class ImpactSchema:
    @staticmethod
    def create(session: Any, registry: Any, change_id: str) -> Dict[str, Any]:
        payload = {
            "impact_id": f"impact-{len(registry.list_artifacts()) + 1}",
            "change_id": change_id,
            "affected_features": [],
            "affected_modules": [],
            "impact_level": "low",
            "confidence": {"score": 0.0, "level": "low", "reasoning": "No impact evidence available", "evidence_refs": []},
        }
        return registry.register("impact", payload)


class RegressionSchema:
    @staticmethod
    def create(session: Any, registry: Any, impacted_feature: str, impact_id: str) -> Dict[str, Any]:
        payload = {
            "regression_id": f"regression-{len(registry.list_artifacts()) + 1}",
            "severity": "low",
            "impacted_feature": impacted_feature,
            "impact_id": impact_id,
            "evidence_ids": [],
        }
        return registry.register("regression", payload)


class RootCauseSchema:
    @staticmethod
    def create(session: Any, registry: Any, regression_id: str, change_id: str) -> Dict[str, Any]:
        payload = {
            "root_cause_id": f"root-cause-{len(registry.list_artifacts()) + 1}",
            "regression_id": regression_id,
            "change_id": change_id,
            "confidence": {"score": 0.0, "level": "low", "reasoning": "No root-cause evidence available", "evidence_refs": []},
            "reasoning": "No root-cause evidence available",
        }
        return registry.register("root_cause", payload)


class ReportSchema:
    @staticmethod
    def create(session: Any, registry: Any, summary: str, findings: List[Dict[str, Any]]) -> Dict[str, Any]:
        payload = {
            "report_id": f"report-{len(registry.list_artifacts()) + 1}",
            "run_id": session.run_id,
            "summary": summary,
            "findings": findings,
            "status": "needs_review",
        }
        return registry.register("report", payload)
