from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class AnalysisSession:
    run_id: str
    target_project: str
    target_version: str
    operator: str
    schema_version: str
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    finished_at: Optional[str] = None

    def start(self) -> None:
        self.started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    def finish(self) -> None:
        self.finished_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "target_project": self.target_project,
            "target_version": self.target_version,
            "operator": self.operator,
            "schema_version": self.schema_version,
        }
