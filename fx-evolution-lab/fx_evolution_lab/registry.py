from __future__ import annotations

from typing import Any, Dict, List
from uuid import uuid4


class ArtifactRegistry:
    def __init__(self, session: Any):
        self.session = session
        self.entries: List[Dict[str, Any]] = []

    def register(self, artifact_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        artifact = {
            "artifact_id": f"artifact-{uuid4().hex[:8]}",
            "artifact_type": artifact_type,
            "created_at": self.session.started_at,
            "analysis_run_id": self.session.run_id,
            "parent_ids": [],
            "child_ids": [],
            **payload,
        }
        self.entries.append(artifact)
        return artifact

    def list_artifacts(self) -> List[Dict[str, Any]]:
        return list(self.entries)
