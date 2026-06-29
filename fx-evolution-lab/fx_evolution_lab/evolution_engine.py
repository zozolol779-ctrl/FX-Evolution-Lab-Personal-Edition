from __future__ import annotations

from typing import Any, Dict, List, Optional


class EvolutionEngine:
    def __init__(self, session: Any, registry: Any):
        self.session = session
        self.registry = registry

    def build_timeline(self, snapshots: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
        """Build an evolution timeline artifact from a list of snapshot dicts.

        Lenient ingestion policy: non-dict entries and entries with a missing or
        None ``artifact_id`` are silently skipped so that one malformed snapshot
        does not abort the entire timeline.
        """
        if not snapshots:
            snapshots = []
        snapshot_ids = [
            snap.get("artifact_id")
            for snap in snapshots
            if isinstance(snap, dict) and snap.get("artifact_id") is not None
        ]
        summary = f"timeline contains {len(snapshot_ids)} snapshot(s)" if snapshot_ids else "timeline is empty"
        payload = {
            "evolution_id": f"evolution-{len(self.registry.list_artifacts()) + 1}",
            "snapshots": snapshot_ids,
            "summary": summary,
        }
        return self.registry.register("evolution", payload)
