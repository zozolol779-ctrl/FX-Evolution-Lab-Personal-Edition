from __future__ import annotations

import difflib
import os
from typing import Any, Dict, List, Set, Tuple


class DiffEngine:
    def __init__(self, session: Any, registry: Any):
        self.session = session
        self.registry = registry

    def _find_artifact(self, artifact_id: str) -> Dict[str, Any]:
        for a in self.registry.list_artifacts():
            if a["artifact_id"] == artifact_id:
                return a
        raise KeyError(f"artifact {artifact_id} not found")

    def _read_file_lines(self, root: str, rel_path: str) -> List[str]:
        try:
            p = os.path.join(root, rel_path)
            with open(p, "r", encoding="utf-8", errors="replace") as fh:
                return fh.read().splitlines()
        except OSError:
            return []

    def compare(self, old_snapshot: Dict[str, Any], new_snapshot: Dict[str, Any]) -> Dict[str, Any]:
        old_manifest = self._find_artifact(old_snapshot.get("manifest_id"))
        new_manifest = self._find_artifact(new_snapshot.get("manifest_id"))

        old_files = {f["relative_path"]: f for f in old_manifest.get("files", [])}
        new_files = {f["relative_path"]: f for f in new_manifest.get("files", [])}

        added = [p for p in new_files.keys() if p not in old_files]
        removed = [p for p in old_files.keys() if p not in new_files]
        modified = []
        renamed: List[Tuple[str, str]] = []

        # detect modified (same path present but different sha)
        for path in set(old_files.keys()).intersection(new_files.keys()):
            if old_files[path].get("sha256") != new_files[path].get("sha256"):
                modified.append(path)

        # detect renames: a removed file whose sha matches a new (added) file's sha
        # Guards:
        #   1. Skip when sha is None — None is not a meaningful content fingerprint
        #      and would cause false positives between any two sha-less files.
        #   2. Each new-path can only be a rename destination once (track used_destinations)
        #      to prevent two removed files with identical content both being matched to
        #      the same new file.
        new_sha_to_path: Dict[str, str] = {}
        for new_path, meta in new_files.items():
            sha = meta.get("sha256")
            if sha is not None and sha not in new_sha_to_path:
                new_sha_to_path[sha] = new_path

        used_destinations: Set[str] = set()
        still_removed: List[str] = []
        for path in removed:
            sha = old_files[path].get("sha256")
            if sha is None:
                still_removed.append(path)
                continue
            new_path = new_sha_to_path.get(sha)
            if new_path and new_path != path and new_path not in used_destinations:
                renamed.append((path, new_path))
                used_destinations.add(new_path)
                if new_path in added:
                    added.remove(new_path)
            else:
                still_removed.append(path)
        removed = still_removed

        # compute per-file line diffs and overall similarity
        root_old = old_manifest.get("root_path", self.session.target_project)
        root_new = new_manifest.get("root_path", self.session.target_project)

        total_added = 0
        total_removed = 0
        similarities: List[float] = []
        file_diffs: Dict[str, Dict[str, Any]] = {}

        for path in modified:
            old_lines = self._read_file_lines(root_old, path)
            new_lines = self._read_file_lines(root_new, path)
            sm = difflib.SequenceMatcher(a=old_lines, b=new_lines)
            similarity = sm.ratio()
            similarities.append(similarity)
            ud = list(difflib.unified_diff(old_lines, new_lines))
            added_count = sum(1 for l in ud if l.startswith('+') and not l.startswith('+++'))
            removed_count = sum(1 for l in ud if l.startswith('-') and not l.startswith('---'))
            total_added += added_count
            total_removed += removed_count
            file_diffs[path] = {"lines_added": added_count, "lines_removed": removed_count, "similarity": similarity}

        # count lines in truly-added and truly-removed files
        for path in added:
            lines = self._read_file_lines(root_new, path)
            total_added += len(lines)

        for path in removed:
            lines = self._read_file_lines(root_old, path)
            total_removed += len(lines)

        overall_similarity = float(sum(similarities) / len(similarities)) if similarities else 1.0

        change_type = "unchanged"
        if added or removed or modified or renamed:
            change_type = "modified"
        payload = {
            "change_id": f"change-{len(self.registry.list_artifacts()) + 1}",
            "old_snapshot": old_snapshot["artifact_id"],
            "new_snapshot": new_snapshot["artifact_id"],
            "change_type": change_type,
            "files_added": added,
            "files_removed": removed,
            "files_modified": modified,
            "files_renamed": renamed,
            "lines_added": total_added,
            "lines_removed": total_removed,
            "similarity": overall_similarity,
            "file_diffs": file_diffs,
        }
        return self.registry.register("diff", payload)
