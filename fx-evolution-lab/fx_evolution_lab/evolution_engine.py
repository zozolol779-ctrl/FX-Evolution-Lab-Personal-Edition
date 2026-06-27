from __future__ import annotations

from typing import Any, Dict, List


class EvolutionEngine:
    def __init__(self, session: Any, registry: Any):
        self.session = session
        self.registry = registry

    def build_timeline(self, snapshots: List[Dict[str, Any]]) -> Dict[str, Any]:
        snapshot_ids = [snap["artifact_id"] for snap in snapshots]
        summary = f"timeline contains {len(snapshot_ids)} snapshot(s)" if snapshot_ids else "timeline is empty"
        payload = {
            "evolution_id": f"evolution-{len(self.registry.list_artifacts()) + 1}",
            "snapshots": snapshot_ids,
            "summary": summary,
        }
        return self.registry.register("evolution", payload)
