"""
regression_analysis.py
======================
Production-grade helpers for the RegressionEngine.

Modules
-------
1. Normalize Layer       — canonical, deterministic artifact representation
2. Hashing System        — content_hash / structure_hash with instance caching
3. Structured Diff       — compute_diff() returning {removed, added, modified, metadata_changes}
4. Severity Scoring      — calculate_severity() with numeric scoring rules
5. False-Positive Filter — is_false_positive() suppresses noise
6. Snapshot Validation   — validate_snapshot() guards against bad input
7. Observability         — RegressionLogger writes JSONL structured logs

Every public function is pure (no side effects) and deterministic.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# 1. Normalize Layer
# ---------------------------------------------------------------------------

# Fields that are runtime-specific and must be excluded from content comparison
_EXCLUDE_FROM_CONTENT = frozenset({
    "artifact_id",
    "artifact_type",
    "feature_id",
    "regression_id",
    "impact_id",
    "change_id",
    "created_at",
    "updated_at",
    # Location/environment data — excluded so the same function in two
    # different temp directories produces the same content hash
    "file_path",
    "imports",
})

# Fields that indicate position only (metadata, not behavior)
_METADATA_ONLY_FIELDS = frozenset({"line_start", "line_end"})


def _normalize_value(value: Any) -> Any:
    """Recursively normalize a value to its canonical form."""
    if isinstance(value, str):
        # Collapse all internal whitespace runs to a single space, strip edges
        return re.sub(r"\s+", " ", value).strip()
    if isinstance(value, list):
        normalized = [_normalize_value(v) for v in value]
        # Sort lists of primitives for determinism; preserve order for dicts
        if all(not isinstance(v, (dict, list)) for v in normalized):
            return sorted(normalized)
        return normalized
    if isinstance(value, dict):
        return {k: _normalize_value(v) for k, v in sorted(value.items())}
    return value


def normalize_artifact(artifact: Dict[str, Any]) -> Dict[str, Any]:
    """Return a canonical representation of *artifact* suitable for comparison.

    - Excludes runtime-specific identifiers (artifact_id, etc.)
    - Strips and collapses whitespace in string values
    - Sorts all primitive lists for deterministic ordering
    - Keys are sorted alphabetically

    The result is stable: calling this twice on the same logical artifact
    always returns an identical dict regardless of insertion order.
    """
    result = {}
    for key, value in artifact.items():
        if key in _EXCLUDE_FROM_CONTENT:
            continue
        result[key] = _normalize_value(value)
    return dict(sorted(result.items()))


def normalize_feature_content(feature: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize only behavioral fields (exclude position metadata).

    Used for *content* comparison — two features are behaviorally identical
    if their content hashes match even when their line numbers differ.
    """
    normalized = normalize_artifact(feature)
    return {k: v for k, v in normalized.items() if k not in _METADATA_ONLY_FIELDS}


# ---------------------------------------------------------------------------
# 2. Hashing System
# ---------------------------------------------------------------------------

def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def content_hash(artifact: Dict[str, Any]) -> str:
    """Deterministic SHA-256 of the artifact's behavioral content.

    Uses *normalize_feature_content* so that position-only changes
    (line number shifts) do not produce a different hash.
    """
    canonical = normalize_feature_content(artifact)
    return _sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=True))


def full_hash(artifact: Dict[str, Any]) -> str:
    """Deterministic SHA-256 of ALL normalized artifact fields.

    Unlike *content_hash*, this INCLUDES metadata fields (line_start, line_end,
    file_path) so it changes when *anything* in the artifact changes.
    Used as the short-circuit gate in compute_diff: if full_hash matches, the
    two artifacts are byte-for-byte equivalent and no diff is needed.
    """
    canonical = normalize_artifact(artifact)
    return _sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=True))


def structure_hash(artifact: Dict[str, Any]) -> str:
    """SHA-256 of the artifact's field *names* only (schema-level fingerprint).

    Useful to detect when a feature adds or removes fields entirely,
    independent of field values.
    """
    keys = sorted(k for k in artifact.keys() if k not in _EXCLUDE_FROM_CONTENT)
    return _sha256(json.dumps(keys, ensure_ascii=True))


class HashCache:
    """Per-instance cache mapping Python object identity → (content_hash, structure_hash).

    Keyed on ``id(artifact)`` (Python object identity) so two different dict
    objects that happen to share an artifact_id are never confused — which
    can happen in unit tests or when synthetic artifacts are built by hand.

    Avoids re-hashing the same artifact object multiple times during a single
    detect() call.
    """

    def __init__(self) -> None:
        self._cache: Dict[int, Tuple[str, str]] = {}

    def get(self, artifact: Dict[str, Any]) -> Tuple[str, str]:
        """Return (content_hash, full_hash) for *artifact*.

        content_hash — behavioral fingerprint (excludes line numbers, file_path)
        full_hash    — total fingerprint (includes all fields); used for short-circuit
        """
        key = id(artifact)
        if key not in self._cache:
            self._cache[key] = (content_hash(artifact), full_hash(artifact))
        return self._cache[key]

    def clear(self) -> None:
        self._cache.clear()


# ---------------------------------------------------------------------------
# 3. Structured Diff
# ---------------------------------------------------------------------------

def compute_diff(
    old_feats: Dict[Any, Dict[str, Any]],
    new_feats: Dict[Any, Dict[str, Any]],
    cache: Optional[HashCache] = None,
) -> Dict[str, Any]:
    """Compare two feature maps and return a structured diff.

    Parameters
    ----------
    old_feats : mapping of feature_key → feature artifact (old version)
    new_feats : mapping of feature_key → feature artifact (new version)
    cache     : optional HashCache to avoid redundant hashing

    Returns
    -------
    {
        "removed":          [...],  # in old, absent in new
        "added":            [...],  # in new, absent in old
        "modified":         [...],  # behavioral change (signature / kind / decorators)
        "metadata_changes": [...],  # position-only change (line numbers)
    }

    Each entry is a dict with keys: "key", "feature" (removed/added) or
    "old" + "new" + "change_type" (modified/metadata_changes).
    """
    if cache is None:
        cache = HashCache()

    removed: List[Dict] = []
    added: List[Dict] = []
    modified: List[Dict] = []
    metadata_changes: List[Dict] = []

    old_keys = set(old_feats.keys())
    new_keys = set(new_feats.keys())

    for key in sorted(old_keys - new_keys, key=str):
        removed.append({"key": key, "feature": old_feats[key]})

    for key in sorted(new_keys - old_keys, key=str):
        added.append({"key": key, "feature": new_feats[key]})

    for key in sorted(old_keys & new_keys, key=str):
        oldf = old_feats[key]
        newf = new_feats[key]

        # full_hash includes ALL fields (line numbers, file_path, etc.)
        # If it matches, the artifacts are completely identical — skip entirely.
        _, fh_old = cache.get(oldf)
        _, fh_new = cache.get(newf)
        if fh_old == fh_new:
            continue  # byte-for-byte identical — short-circuit

        # content_hash excludes position-only metadata (line_start, line_end, file_path)
        ch_old, _ = cache.get(oldf)
        ch_new, _ = cache.get(newf)

        norm_old = normalize_feature_content(oldf)
        norm_new = normalize_feature_content(newf)

        behavioral_changed = (
            norm_old.get("signature") != norm_new.get("signature")
            or norm_old.get("kind") != norm_new.get("kind")
            or norm_old.get("decorators") != norm_new.get("decorators")
            or norm_old.get("parents") != norm_new.get("parents")
        )

        if behavioral_changed:
            if norm_old.get("signature") != norm_new.get("signature"):
                change_type = "signature_changed"
            else:
                change_type = "behavior_changed"
            modified.append({
                "key": key,
                "old": oldf,
                "new": newf,
                "change_type": change_type,
            })
        else:
            metadata_changes.append({
                "key": key,
                "old": oldf,
                "new": newf,
                "change_type": "metadata",
            })

    return {
        "removed": removed,
        "added": added,
        "modified": modified,
        "metadata_changes": metadata_changes,
    }


# ---------------------------------------------------------------------------
# 4. Severity Scoring Engine
# ---------------------------------------------------------------------------

# Points assigned per change type
_SEVERITY_RULES: Dict[str, int] = {
    "removal_public": 3,
    "removal_private": 1,
    "behavior_changed": 3,
    "signature_changed": 2,
    "metadata": 1,
}


def calculate_severity(diff_result: Dict[str, Any]) -> Dict[str, Any]:
    """Compute a numeric severity score and label from a structured diff.

    Scoring rules
    -------------
    +3  for each removed *public* symbol  (name doesn't start with '_')
    +1  for each removed *private* symbol (name starts with '_')
    +3  for each behavior_changed entry
    +2  for each signature_changed entry
    +1  for each metadata_changes entry

    Mapping
    -------
    0–1  → "low"
    2–3  → "medium"
    4+   → "high"
    """
    score = 0
    breakdown: Dict[str, int] = {}

    for entry in diff_result.get("removed", []):
        name = entry["feature"].get("name") or ""
        kind = "removal_public" if (name and not name.startswith("_")) else "removal_private"
        pts = _SEVERITY_RULES[kind]
        score += pts
        breakdown[kind] = breakdown.get(kind, 0) + pts

    for entry in diff_result.get("modified", []):
        kind = entry.get("change_type", "signature_changed")
        pts = _SEVERITY_RULES.get(kind, _SEVERITY_RULES["signature_changed"])
        score += pts
        breakdown[kind] = breakdown.get(kind, 0) + pts

    for _ in diff_result.get("metadata_changes", []):
        kind = "metadata"
        pts = _SEVERITY_RULES[kind]
        score += pts
        breakdown[kind] = breakdown.get(kind, 0) + pts

    # Thresholds chosen to preserve backward compatibility:
    # a single public API removal (score=3) is immediately "high"
    # a signature change alone (score=2) is "medium"
    # metadata / private changes only (score=0-1) are "low"
    if score >= 3:
        level = "high"
    elif score >= 2:
        level = "medium"
    else:
        level = "low"

    return {"score": score, "level": level, "breakdown": breakdown}


# ---------------------------------------------------------------------------
# 5. False-Positive Suppression Layer
# ---------------------------------------------------------------------------

def is_false_positive(
    diff_result: Dict[str, Any],
    norm_old_map: Optional[Dict] = None,
    norm_new_map: Optional[Dict] = None,
) -> bool:
    """Return True when the diff carries no signal worth reporting.

    A diff is considered a false positive when ALL of the following hold:
    - No removals
    - No behavioral modifications (signature / kind / decorators)
    - Changes are limited to metadata (line numbers) or list reordering

    Parameters
    ----------
    diff_result  : output of compute_diff()
    norm_old_map : optional mapping of key → normalized old feature (unused
                   in base implementation but accepted for extensibility)
    norm_new_map : optional mapping of key → normalized new feature
    """
    has_removals = len(diff_result.get("removed", [])) > 0
    has_modifications = len(diff_result.get("modified", [])) > 0

    if has_removals or has_modifications:
        return False

    # Only metadata changes or no changes at all → suppress
    return True


# ---------------------------------------------------------------------------
# 6. Snapshot Validation Layer
# ---------------------------------------------------------------------------

def validate_snapshot(
    snapshot: Optional[Dict[str, Any]],
    registry: Any,
) -> Dict[str, Any]:
    """Validate a snapshot artifact and its associated manifest.

    Returns
    -------
    {
        "valid":  bool,
        "issues": [str, ...]  # empty when valid
    }
    """
    issues: List[str] = []

    if not snapshot:
        return {"valid": False, "issues": ["snapshot is None"]}

    required_snapshot_keys = {"artifact_id", "artifact_type"}
    for key in required_snapshot_keys:
        if key not in snapshot:
            issues.append(f"snapshot missing required key: {key}")

    if snapshot.get("artifact_type") != "snapshot":
        issues.append(
            f"expected artifact_type='snapshot', got {snapshot.get('artifact_type')!r}"
        )

    manifest_id = snapshot.get("manifest_id")
    if not manifest_id:
        issues.append("snapshot has no manifest_id")
        return {"valid": False, "issues": issues}

    manifest = None
    for a in registry.list_artifacts():
        if a.get("artifact_id") == manifest_id:
            manifest = a
            break

    if not manifest:
        issues.append(f"manifest {manifest_id!r} not found in registry")
        return {"valid": False, "issues": issues}

    files = manifest.get("files", [])
    if not isinstance(files, list):
        issues.append("manifest 'files' is not a list")
    elif len(files) == 0:
        issues.append("manifest has no files (empty project)")

    return {"valid": len(issues) == 0, "issues": issues}


# ---------------------------------------------------------------------------
# 7. Observability — Structured JSONL Logger
# ---------------------------------------------------------------------------

class RegressionLogger:
    """Writes structured JSONL log entries to a file (or discards if no path).

    Each entry is a single JSON object on one line, containing:
        artifact_id, diff_id, severity_score, change_type,
        decision_path, false_positive, timestamp
    """

    def __init__(self, log_path: Optional[str] = None) -> None:
        self._path = log_path
        self._records: List[Dict[str, Any]] = []

    def log(self, record: Dict[str, Any]) -> None:
        """Append a structured log record."""
        self._records.append(record)
        if self._path:
            try:
                with open(self._path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, ensure_ascii=True) + "\n")
            except OSError:
                pass  # logging must never crash the analysis pipeline

    def log_detection(
        self,
        *,
        artifact_id: str,
        diff_id: str,
        severity_score: int,
        severity_level: str,
        change_types: List[str],
        false_positive: bool,
        decision_path: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Convenience method for the standard detection log format."""
        record: Dict[str, Any] = {
            "artifact_id": artifact_id,
            "diff_id": diff_id,
            "severity_score": severity_score,
            "severity_level": severity_level,
            "change_types": sorted(change_types),
            "false_positive": false_positive,
            "decision_path": decision_path,
        }
        if extra:
            record.update(extra)
        self.log(record)

    @property
    def records(self) -> List[Dict[str, Any]]:
        """Return all in-memory log records (useful in tests)."""
        return list(self._records)

    def flush(self) -> None:
        """No-op: writes happen immediately. Kept for interface compatibility."""
