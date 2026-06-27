from __future__ import annotations

from typing import Any, Dict
import os


class RegressionEngine:
    def __init__(self, session: Any, registry: Any):
        self.session = session
        self.registry = registry

    def detect(self, impacted_feature: str, impact_id: str) -> Dict[str, Any]:
        # Find impact artifact by artifact_id or impact_id field
        impact = None
        for a in self.registry.list_artifacts():
            if a.get("artifact_type") == "impact" and (
                a.get("artifact_id") == impact_id or a.get("impact_id") == impact_id
            ):
                impact = a
                break

        if not impact:
            raise KeyError(f"impact {impact_id} not found")

        change_id = impact.get("change_id")

        # Find the related diff artifact
        diff = None
        for a in self.registry.list_artifacts():
            if a.get("artifact_type") == "diff" and (
                a.get("artifact_id") == change_id or a.get("change_id") == change_id
            ):
                diff = a
                break

        if not diff:
            raise KeyError("related diff not found for impact")

        # Find old and new snapshots referenced by the diff
        old_snapshot_id = diff.get("old_snapshot")
        new_snapshot_id = diff.get("new_snapshot")
        old_snapshot = next(
            (a for a in self.registry.list_artifacts() if a.get("artifact_id") == old_snapshot_id),
            None,
        )
        new_snapshot = next(
            (a for a in self.registry.list_artifacts() if a.get("artifact_id") == new_snapshot_id),
            None,
        )
        if not old_snapshot or not new_snapshot:
            raise KeyError("snapshots for diff not found in registry")

        # Manifests may be absent — guard with empty defaults to avoid AttributeError
        old_manifest = next(
            (a for a in self.registry.list_artifacts()
             if a.get("artifact_id") == old_snapshot.get("manifest_id")),
            None,
        )
        new_manifest = next(
            (a for a in self.registry.list_artifacts()
             if a.get("artifact_id") == new_snapshot.get("manifest_id")),
            None,
        )

        from fx_evolution_lab.feature_engine import FeatureEngine
        from fx_evolution_lab.registry import ArtifactRegistry as TempRegistry

        temp_old_reg = TempRegistry(self.session)
        temp_new_reg = TempRegistry(self.session)
        feat_engine_old = FeatureEngine(self.session, temp_old_reg)
        feat_engine_new = FeatureEngine(self.session, temp_new_reg)

        # Extract features from old manifest files (gracefully skip unreadable files)
        old_files = old_manifest.get("files", []) if old_manifest else []
        old_root = (
            old_manifest.get("root_path", self.session.target_project)
            if old_manifest else self.session.target_project
        )
        for f in old_files:
            fp = f.get("relative_path")
            full = fp if os.path.isabs(fp) else os.path.join(old_root, fp)
            try:
                feat_engine_old.extract_from_file(full)
            except (FileNotFoundError, ValueError, UnicodeDecodeError, OSError):
                continue

        # Extract features from new manifest files (gracefully skip unreadable files)
        new_files = new_manifest.get("files", []) if new_manifest else []
        new_root = (
            new_manifest.get("root_path", self.session.target_project)
            if new_manifest else self.session.target_project
        )
        for f in new_files:
            fp = f.get("relative_path")
            full = fp if os.path.isabs(fp) else os.path.join(new_root, fp)
            try:
                feat_engine_new.extract_from_file(full)
            except (FileNotFoundError, ValueError, UnicodeDecodeError, OSError):
                continue

        def _feature_key(feature: Dict[str, Any], root: str):
            file_path = feature.get("file_path")
            if not file_path:
                return (None, feature.get("name"))
            if os.path.isabs(file_path):
                try:
                    rel_path = os.path.relpath(file_path, root)
                except ValueError:
                    rel_path = os.path.basename(file_path)
            else:
                rel_path = file_path
            return (rel_path.replace(os.sep, "/"), feature.get("name"))

        old_feats = {
            _feature_key(f, old_root): f
            for f in temp_old_reg.list_artifacts()
            if f.get("artifact_type") == "feature"
        }
        new_feats = {
            _feature_key(f, new_root): f
            for f in temp_new_reg.list_artifacts()
            if f.get("artifact_type") == "feature"
        }

        regressions = []

        # Detect removed functions/classes and signature changes
        for key, oldf in old_feats.items():
            name = oldf.get("name") or ""
            if key not in new_feats:
                # Guard: treat a missing or None name as non-public (low severity)
                severity = "high" if (name and not name.startswith("_")) else "low"
                regressions.append({
                    "type": "removed",
                    "name": name,
                    "file": oldf.get("file_path"),
                    "severity": severity,
                    "evidence": {"old_feature": oldf},
                })
            else:
                newf = new_feats[key]
                if oldf.get("signature") != newf.get("signature"):
                    regressions.append({
                        "type": "signature_changed",
                        "name": name,
                        "file": oldf.get("file_path"),
                        "severity": "medium",
                        "evidence": {"old": oldf, "new": newf},
                    })

        overall_severity = (
            "high" if any(r["severity"] == "high" for r in regressions)
            else "medium" if any(r["severity"] == "medium" for r in regressions)
            else "low"
        )

        payload = {
            "regression_id": f"regression-{len(self.registry.list_artifacts()) + 1}",
            "severity": overall_severity,
            "impacted_feature": impacted_feature,
            "impact_id": impact.get("impact_id") if impact else impact_id,
            "evidence": regressions,
        }
        return self.registry.register("regression", payload)
