from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fx_evolution_lab.regression_analysis import (
    HashCache,
    RegressionLogger,
    calculate_severity,
    compute_diff,
    is_false_positive,
    normalize_feature_content,
    validate_snapshot,
)


class RegressionEngine:
    """Detect regressions between two versions of a project.

    Upgrade summary over the baseline
    ----------------------------------
    * Normalize Layer    — canonical artifact representation before comparison
    * Hashing System     — content_hash / structure_hash with per-call caching
    * Structured Diff    — compute_diff() producing {removed, added, modified, metadata_changes}
    * Severity Scoring   — numeric score → low / medium / high
    * False-Positive     — suppresses metadata-only or reorder-only noise
    * Snapshot Validation — guards against missing manifests / empty file sets
    * Observability      — JSONL structured log via RegressionLogger
    """

    def __init__(
        self,
        session: Any,
        registry: Any,
        log_path: Optional[str] = None,
    ) -> None:
        self.session = session
        self.registry = registry
        self._logger = RegressionLogger(log_path=log_path)

    # ------------------------------------------------------------------
    # Public API (backward-compatible)
    # ------------------------------------------------------------------

    def detect(self, impacted_feature: str, impact_id: str) -> Dict[str, Any]:
        """Detect regressions associated with *impact_id*.

        Parameters
        ----------
        impacted_feature : human-readable label for the feature under test
        impact_id        : artifact_id or impact_id field of an impact artifact

        Returns
        -------
        Registered ``regression`` artifact with keys:
            artifact_id, artifact_type, regression_id, severity,
            impacted_feature, impact_id, evidence,
            diff_result, severity_score, false_positive_filtered,
            validation
        """
        cache = HashCache()

        # ── 1. Locate impact artifact ──────────────────────────────────
        impact = self._find_artifact("impact", impact_id)
        if not impact:
            raise KeyError(f"impact {impact_id!r} not found")

        change_id = impact.get("change_id")

        # ── 2. Locate diff artifact ────────────────────────────────────
        diff_artifact = self._find_artifact("diff", change_id)
        if not diff_artifact:
            raise KeyError("related diff not found for impact")

        # ── 3. Locate snapshots ────────────────────────────────────────
        old_snapshot = self._artifact_by_id(diff_artifact.get("old_snapshot"))
        new_snapshot = self._artifact_by_id(diff_artifact.get("new_snapshot"))
        if not old_snapshot or not new_snapshot:
            raise KeyError("snapshots for diff not found in registry")

        # ── 4. Snapshot validation ─────────────────────────────────────
        old_val = validate_snapshot(old_snapshot, self.registry)
        new_val = validate_snapshot(new_snapshot, self.registry)
        validation = {
            "old_snapshot": old_val,
            "new_snapshot": new_val,
        }

        # ── 5. Locate manifests (absent → empty defaults) ──────────────
        old_manifest = self._artifact_by_id(old_snapshot.get("manifest_id"))
        new_manifest = self._artifact_by_id(new_snapshot.get("manifest_id"))

        old_root = (
            old_manifest.get("root_path", self.session.target_project)
            if old_manifest else self.session.target_project
        )
        new_root = (
            new_manifest.get("root_path", self.session.target_project)
            if new_manifest else self.session.target_project
        )

        # ── 6. Extract features for both versions ─────────────────────
        old_feats_list = self._extract_features(
            old_manifest.get("files", []) if old_manifest else [],
            old_root,
        )
        new_feats_list = self._extract_features(
            new_manifest.get("files", []) if new_manifest else [],
            new_root,
        )

        old_feats = {
            self._feature_key(f, old_root): f for f in old_feats_list
        }
        new_feats = {
            self._feature_key(f, new_root): f for f in new_feats_list
        }

        # ── 7. Structured diff (with hash short-circuit) ───────────────
        diff_result = compute_diff(old_feats, new_feats, cache=cache)

        # ── 8. False-positive suppression ─────────────────────────────
        fp = is_false_positive(diff_result)

        # ── 9. Severity scoring ────────────────────────────────────────
        severity_info = calculate_severity(diff_result)

        # ── 10. Build legacy evidence list (backward compat) ──────────
        evidence, fp_filtered = self._build_evidence(diff_result, skip_fp=fp)

        # ── 11. Observability log entry ────────────────────────────────
        change_types = (
            (["removed"] if diff_result["removed"] else []) +
            ([e["change_type"] for e in diff_result["modified"]]) +
            (["metadata"] if diff_result["metadata_changes"] else [])
        )
        self._logger.log_detection(
            artifact_id=impact.get("artifact_id", ""),
            diff_id=diff_artifact.get("artifact_id", ""),
            severity_score=severity_info["score"],
            severity_level=severity_info["level"],
            change_types=list(set(change_types)),
            false_positive=fp,
            decision_path=(
                "suppressed(false_positive)" if fp
                else f"reported(score={severity_info['score']})"
            ),
        )

        # ── 12. Register artifact ──────────────────────────────────────
        payload: Dict[str, Any] = {
            "regression_id": f"regression-{len(self.registry.list_artifacts()) + 1}",
            "severity": severity_info["level"],
            "impacted_feature": impacted_feature,
            "impact_id": impact.get("impact_id") or impact_id,
            "evidence": evidence,
            # Extended fields
            "diff_result": {
                "removed_count": len(diff_result["removed"]),
                "added_count": len(diff_result["added"]),
                "modified_count": len(diff_result["modified"]),
                "metadata_changes_count": len(diff_result["metadata_changes"]),
            },
            "severity_score": severity_info["score"],
            "false_positive_filtered": fp_filtered,
            "validation": validation,
        }
        return self.registry.register("regression", payload)

    @property
    def log_records(self) -> list:
        """Return all in-memory log records emitted by this engine instance."""
        return self._logger.records

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _find_artifact(self, artifact_type: str, lookup_id: str) -> Optional[Dict]:
        """Find an artifact by artifact_id OR by its <type>_id payload field."""
        id_field = f"{artifact_type}_id"
        for a in self.registry.list_artifacts():
            if a.get("artifact_type") == artifact_type and (
                a.get("artifact_id") == lookup_id
                or a.get(id_field) == lookup_id
                or a.get("change_id") == lookup_id  # diff uses change_id
            ):
                return a
        return None

    def _artifact_by_id(self, artifact_id: Optional[str]) -> Optional[Dict]:
        if not artifact_id:
            return None
        for a in self.registry.list_artifacts():
            if a.get("artifact_id") == artifact_id:
                return a
        return None

    def _extract_features(
        self, files: List[Dict], root: str
    ) -> List[Dict[str, Any]]:
        """Extract features from a list of manifest file entries."""
        from fx_evolution_lab.feature_engine import FeatureEngine
        from fx_evolution_lab.registry import ArtifactRegistry as TempRegistry

        temp_reg = TempRegistry(self.session)
        engine = FeatureEngine(self.session, temp_reg)

        for f in files:
            fp = f.get("relative_path") or ""
            full = fp if os.path.isabs(fp) else os.path.join(root, fp)
            try:
                engine.extract_from_file(full)
            except (FileNotFoundError, ValueError, UnicodeDecodeError, OSError):
                continue

        return [
            a for a in temp_reg.list_artifacts()
            if a.get("artifact_type") == "feature"
        ]

    @staticmethod
    def _feature_key(feature: Dict[str, Any], root: str) -> tuple:
        """Stable (relative_path, name) key for a feature artifact."""
        file_path = feature.get("file_path")
        if not file_path:
            return (None, feature.get("name"))
        if os.path.isabs(file_path):
            try:
                rel = os.path.relpath(file_path, root)
            except ValueError:
                rel = os.path.basename(file_path)
        else:
            rel = file_path
        return (rel.replace(os.sep, "/"), feature.get("name"))

    def _build_evidence(
        self,
        diff_result: Dict[str, Any],
        skip_fp: bool,
    ) -> tuple:
        """Convert structured diff to the legacy evidence list format.

        Returns (evidence_list, filtered_count) where filtered_count is the
        number of metadata-only entries that were suppressed.
        """
        evidence: List[Dict[str, Any]] = []
        filtered = 0

        if skip_fp:
            filtered = (
                len(diff_result.get("removed", []))
                + len(diff_result.get("modified", []))
                + len(diff_result.get("metadata_changes", []))
            )
            return evidence, filtered

        for entry in diff_result.get("removed", []):
            oldf = entry["feature"]
            name = oldf.get("name") or ""
            severity = "high" if (name and not name.startswith("_")) else "low"
            evidence.append({
                "type": "removed",
                "name": name,
                "file": oldf.get("file_path"),
                "severity": severity,
                "evidence": {"old_feature": oldf},
            })

        for entry in diff_result.get("modified", []):
            oldf = entry["old"]
            newf = entry["new"]
            name = oldf.get("name") or ""
            evidence.append({
                "type": entry["change_type"],
                "name": name,
                "file": oldf.get("file_path"),
                "severity": "medium",
                "evidence": {"old": oldf, "new": newf},
            })

        for entry in diff_result.get("metadata_changes", []):
            filtered += 1  # metadata-only → suppress from evidence

        return evidence, filtered
