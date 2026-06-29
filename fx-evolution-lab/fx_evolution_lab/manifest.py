from __future__ import annotations

from typing import Any, Dict, List


class ManifestEngine:
    def __init__(self, session: Any, registry: Any):
        self.session = session
        self.registry = registry

    def build(self, files: List[Dict[str, Any]]) -> Dict[str, Any]:
        manifest = {
            "schema_version": self.session.schema_version,
            "generated_at": self.session.started_at,
            "root_path": self.session.target_project,
            "files": files if files is not None else [],
        }
        return self.registry.register("manifest", manifest)
