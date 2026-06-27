from __future__ import annotations

from typing import Any, Dict, List


class SnapshotEngine:
    def __init__(self, session: Any, registry: Any):
        self.session = session
        self.registry = registry

    def create(self, manifest: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "snapshot_id": f"snapshot-{len(self.registry.list_artifacts()) + 1}",
            "manifest_id": manifest["artifact_id"],
            "timestamp": self.session.started_at,
            "project_version": self.session.target_version,
        }
        return self.registry.register("snapshot", payload)
