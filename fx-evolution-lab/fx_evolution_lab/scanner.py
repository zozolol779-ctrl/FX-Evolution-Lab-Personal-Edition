from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, Iterator, List, Optional, Set


class ScannerEngine:
    def __init__(self, root_path: str, ignore_rules: Optional[Set[str]] = None):
        self.root_path = root_path
        self.ignore_rules = ignore_rules or set()

    def iter_files(self) -> Iterator[Dict[str, Any]]:
        for dirpath, dirnames, filenames in os.walk(self.root_path):
            dirnames[:] = [d for d in dirnames if d not in self.ignore_rules and os.path.join(dirpath, d) not in self.ignore_rules]
            for filename in sorted(filenames):
                full_path = os.path.join(dirpath, filename)
                if full_path in self.ignore_rules:
                    continue
                yield self._scan_file(full_path)

    def _scan_file(self, path: str) -> Dict[str, Any]:
        rel_path = os.path.relpath(path, self.root_path)
        with open(path, "rb") as handle:
            data = handle.read()
        digest = hashlib.sha256(data).hexdigest()
        size = len(data)
        is_binary = b"\x00" in data
        language = self._detect_language(path)
        return {
            "file_id": f"file-{digest[:12]}",
            "relative_path": rel_path.replace(os.sep, "/"),
            "sha256": digest,
            "size": size,
            "mtime": None,
            "entropy": 0.0,
            "language": language,
            "binary_flag": is_binary,
        }

    def _detect_language(self, path: str) -> str:
        if path.endswith(".py"):
            return "python"
        if path.endswith(".md"):
            return "markdown"
        if path.endswith(".json"):
            return "json"
        if path.endswith(".txt"):
            return "text"
        return "unknown"
