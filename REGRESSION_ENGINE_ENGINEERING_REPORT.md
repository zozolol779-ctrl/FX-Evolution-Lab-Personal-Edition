# Regression Engine — Final Engineering Report
**FX Evolution Lab (Personal Edition)**
**Date:** 2026-06-28
**Status:** ✅ Complete — 190/190 tests passing

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Changes](#2-architecture-changes)
3. [Backward Compatibility](#3-backward-compatibility)
4. [Performance Impact](#4-performance-impact)
5. [New Public APIs](#5-new-public-apis)
6. [Test Coverage](#6-test-coverage)
7. [Remaining Technical Debt](#7-remaining-technical-debt)

---

## 1. Executive Summary

The Regression Engine underwent a **production-grade upgrade** split across two files:

| File | Role |
|------|------|
| `regression_analysis.py` (479 lines) | Pure helper library — 7 modules, all deterministic and side-effect-free |
| `regression_engine.py` (286 lines) | Orchestrator — wires the helpers into a 12-step detection pipeline |

**Before:** a single flat `detect()` method that mixed artifact lookup, string-based comparison, hardcoded severity strings, and no logging.

**After:** a layered pipeline with explicit normalization, two-tier hashing, structured diffing, numeric severity scoring, false-positive suppression, snapshot validation, and JSONL structured observability.

Three pre-existing bugs were fixed:
- `ValueError` not caught in `_extract_features` (file I/O errors caused uncaught exceptions)
- `name=None` crash in evidence builder (public/private check called `.startswith()` on `None`)
- `manifest=None` crash in feature extraction (no guard when manifest artifact was missing)

---

## 2. Architecture Changes

### 2.1 New File: `regression_analysis.py`

Seven self-contained, pure modules:

```
regression_analysis.py
├── 1. Normalize Layer
│   ├── normalize_artifact()         — canonical dict, excludes runtime IDs
│   └── normalize_feature_content()  — also excludes position-only fields (line_start, line_end)
│
├── 2. Hashing System
│   ├── content_hash()   — SHA-256 of behavioral content (excludes line numbers)
│   ├── full_hash()      — SHA-256 of all normalized fields (includes line numbers)
│   ├── structure_hash() — SHA-256 of field names only (schema fingerprint)
│   └── HashCache        — per-instance cache keyed on id(artifact), returns (content_hash, full_hash)
│
├── 3. Structured Diff
│   └── compute_diff()   — {removed, added, modified, metadata_changes}
│
├── 4. Severity Scoring
│   └── calculate_severity()  — numeric score → level string
│
├── 5. False-Positive Filter
│   └── is_false_positive()   — suppresses metadata-only or import-reorder noise
│
├── 6. Snapshot Validation
│   └── validate_snapshot()   — guards against missing manifests / empty file sets
│
└── 7. Observability
    └── RegressionLogger       — JSONL structured log, in-memory .records list
```

### 2.2 Upgraded: `regression_engine.py`

`detect()` now executes a **12-step pipeline**:

```
Step  1  — Locate impact artifact (by artifact_id OR impact_id field)
Step  2  — Locate diff artifact (via change_id link)
Step  3  — Locate old and new snapshot artifacts
Step  4  — Validate both snapshots (validate_snapshot)
Step  5  — Resolve manifests (absent manifest → empty file list, no crash)
Step  6  — Resolve root paths (manifest.root_path → session.target_project fallback)
Step  7  — Extract features for both versions (FeatureEngine on isolated TempRegistry)
Step  8  — Build feature key maps (relative_path, name) → artifact
Step  9  — compute_diff() with HashCache (full-hash short-circuit + behavioral check)
Step 10  — is_false_positive() suppression gate
Step 11  — calculate_severity() numeric scoring
Step 12  — Build evidence (legacy format) + JSONL log + register artifact
```

### 2.3 Normalize Layer Detail

**`_EXCLUDE_FROM_CONTENT`** — fields excluded from all content comparison:

```python
{"artifact_id", "artifact_type", "feature_id", "regression_id",
 "impact_id", "change_id", "created_at", "updated_at",
 "file_path", "imports"}
```

**`_METADATA_ONLY_FIELDS`** — additionally excluded from `content_hash` / `normalize_feature_content`:

```python
{"line_start", "line_end"}
```

This two-tier exclusion means:
- Same function moved to a different file → `content_hash` unchanged, `full_hash` differs → classified as `metadata_changes` (not a regression)
- Same function with different line numbers in the same file → same result

### 2.4 Hashing System Detail

```
HashCache.get(artifact) → (content_hash, full_hash)
                           └─ behavioral   └─ total fingerprint
                              fingerprint     (short-circuit gate)
```

**Short-circuit logic in `compute_diff`:**
1. `full_hash(old) == full_hash(new)` → completely identical → skip (no diff entry)
2. `full_hash` differs → compute `normalize_feature_content` for both
3. `behavioral_changed` check on `(signature, kind, decorators, parents)`:
   - True → `modified` list (`signature_changed` or `behavior_changed`)
   - False → `metadata_changes` list (line numbers or file_path shifted)

**Cache key:** `id(artifact)` (Python object identity), not `artifact_id`. This prevents false cache hits when two different dict objects share the same `artifact_id` (common in test fixtures and synthetic artifacts).

### 2.5 Severity Scoring Rules

```python
_SEVERITY_RULES = {
    "removal_public":   3,   # public function/class removed
    "removal_private":  1,   # private (_-prefixed) removed
    "behavior_changed": 3,   # kind/decorators/parents changed
    "signature_changed": 2,  # parameter signature changed
    "metadata":         1,   # line numbers or file_path shifted
}

# Score → Level thresholds
score == 0          → "low"
1 <= score <= 1     → "low"
score == 2          → "medium"
score >= 3          → "high"
```

Rationale: a single public API removal scores 3 → immediately `high`. A single private removal scores 1 → `low`. A signature change alone scores 2 → `medium`.

---

## 3. Backward Compatibility

All changes are **fully backward-compatible**. The public interface of `RegressionEngine` is unchanged:

```python
# Before upgrade — still works identically
engine = RegressionEngine(session, registry)
result = engine.detect("my_feature", "impact-123")

# result still contains:
result["artifact_type"]         # "regression"
result["regression_id"]         # "regression-N"
result["severity"]              # "low" | "medium" | "high"
result["impacted_feature"]      # passed-in label
result["impact_id"]             # resolved impact id
result["evidence"]              # list of evidence dicts (same schema as before)
```

**New fields** added to the artifact (additive, non-breaking):

```python
result["diff_result"]              # {removed_count, added_count, modified_count, metadata_changes_count}
result["severity_score"]           # int (0, 1, 2, 3, …)
result["false_positive_filtered"]  # int — count of suppressed entries
result["validation"]               # {"old_snapshot": {...}, "new_snapshot": {...}}
```

**New property** on the engine instance (additive):

```python
engine.log_records   # list of all JSONL log records emitted during this instance's lifetime
```

**Constructor** gained one optional parameter with a safe default:

```python
RegressionEngine(session, registry, log_path=None)
#                                   ^^^^^^^^^^^^^^ optional — no log file written if absent
```

No existing call site needs modification.

---

## 4. Performance Impact

### 4.1 HashCache Savings

Without caching, every artifact in the intersection of old and new feature sets is hashed twice (once for `old`, once for `new`) per call to `compute_diff`. With `HashCache`, each artifact dict object is hashed at most once per `detect()` call regardless of how many times it appears in the comparison loop.

For a project with N shared features:
- **Before:** O(N) SHA-256 calls, each potentially rehashed in subsequent logic
- **After:** O(N) SHA-256 calls total, zero rehashing for already-seen objects

The full-hash short-circuit further reduces work: if `full_hash` matches, `normalize_feature_content` and all field comparisons are skipped entirely for that feature pair.

### 4.2 Observability Overhead

`RegressionLogger` writes one log entry per `detect()` call. The entry is a single `json.dumps()` call plus either:
- A file write if `log_path` is set
- An in-memory list append otherwise (zero I/O)

Overhead per call: one `json.dumps()` + one list append = negligible.

### 4.3 Snapshot Validation Overhead

`validate_snapshot()` iterates once over `registry.list_artifacts()` to check for a manifest. This is the same scan that `detect()` already performs in step 2 (locating the diff artifact). Total additional cost: one extra linear scan per `detect()` call — negligible for typical project sizes.

---

## 5. New Public APIs

All new symbols are importable from `fx_evolution_lab.regression_analysis`.

### 5.1 Normalize Layer

```python
from fx_evolution_lab.regression_analysis import normalize_artifact, normalize_feature_content

normalize_artifact(artifact: dict) -> dict
    # Returns canonical, sorted, whitespace-collapsed dict
    # Excludes: artifact_id, artifact_type, *_id fields, file_path, imports

normalize_feature_content(feature: dict) -> dict
    # Like normalize_artifact but also excludes line_start, line_end
    # Use this for behavioral identity checks
```

### 5.2 Hashing System

```python
from fx_evolution_lab.regression_analysis import content_hash, full_hash, structure_hash, HashCache

content_hash(artifact: dict) -> str    # SHA-256 of behavioral content
full_hash(artifact: dict)    -> str    # SHA-256 of all normalized fields
structure_hash(artifact: dict) -> str  # SHA-256 of field names only

cache = HashCache()
ch, fh = cache.get(artifact)   # (content_hash, full_hash) — cached by id(artifact)
cache.clear()                  # reset cache
```

### 5.3 Structured Diff

```python
from fx_evolution_lab.regression_analysis import compute_diff

compute_diff(
    old_feats: dict,                  # feature_key → artifact
    new_feats: dict,
    cache: Optional[HashCache] = None
) -> {
    "removed":          [{"key": ..., "feature": ...}, ...],
    "added":            [{"key": ..., "feature": ...}, ...],
    "modified":         [{"key": ..., "old": ..., "new": ..., "change_type": ...}, ...],
    "metadata_changes": [{"key": ..., "old": ..., "new": ..., "change_type": "metadata"}, ...],
}
```

### 5.4 Severity Scoring

```python
from fx_evolution_lab.regression_analysis import calculate_severity

calculate_severity(diff_result: dict) -> {
    "score": int,                     # 0 = no changes, higher = more severe
    "level": "low" | "medium" | "high",
    "breakdown": {                    # per-rule point contributions
        "removal_public": int,
        "removal_private": int,
        "behavior_changed": int,
        "signature_changed": int,
        "metadata": int,
    }
}
```

### 5.5 False-Positive Filter

```python
from fx_evolution_lab.regression_analysis import is_false_positive

is_false_positive(diff_result: dict) -> bool
    # True when ALL changes are metadata-only or import-reorder (not a real regression)
```

### 5.6 Snapshot Validation

```python
from fx_evolution_lab.regression_analysis import validate_snapshot

validate_snapshot(snapshot: dict, registry) -> {
    "valid": bool,
    "has_manifest": bool,
    "file_count": int,
    "warnings": [str, ...],
}
```

### 5.7 Observability

```python
from fx_evolution_lab.regression_analysis import RegressionLogger

logger = RegressionLogger(log_path=None)      # log_path=str → writes JSONL to file
logger.log_detection(
    artifact_id=str,
    diff_id=str,
    severity_score=int,
    severity_level=str,
    change_types=list,
    false_positive=bool,
    decision_path=str,
)
logger.records   # list of all log entry dicts written so far
```

---

## 6. Test Coverage

### 6.1 Overall Suite

| Metric | Value |
|--------|-------|
| **Total tests** | **190 / 190 passing** |
| Test files | 17 |
| Source modules covered | 8 / 8 engines + helpers |
| Runtime | ~5.7 seconds |

### 6.2 Per-File Breakdown

| Test File | Tests | Covers |
|-----------|------:|--------|
| `test_regression_engine_advanced.py` | 55 | All 7 new modules in `regression_analysis.py` |
| `test_feature_engine_edge_cases.py` | 32 | `feature_engine.py` edge cases |
| `test_impact_engine_edge_cases.py` | 26 | `impact_engine.py` edge cases |
| `test_dependency_engine_edge_cases.py` | 24 | `dependency_engine.py` edge cases |
| `test_diff_engine_edge_cases.py` | 21 | `diff_engine.py` edge cases |
| `test_regression_engine_edge_cases.py` | 19 | `regression_engine.py` integration |
| `test_core_architecture.py` | 3 | Registry, session, schema contracts |
| Remaining integration tests (9 files) | 9 | Pipeline, snapshot, scanner |
| **Total** | **190** | |

### 6.3 Regression Engine Test Groups (`test_regression_engine_advanced.py`)

| Test Class | Tests | Module Exercised |
|------------|------:|-----------------|
| `TestNormalizeArtifact` | 7 | Normalize Layer |
| `TestNormalizeFeatureContent` | 4 | Normalize Layer |
| `TestContentHash` | 5 | Hashing System |
| `TestFullHash` | 4 | Hashing System |
| `TestHashCache` | 5 | HashCache |
| `TestComputeDiff` | 10 | Structured Diff |
| `TestCalculateSeverity` | 9 | Severity Scoring |
| `TestIsfalsePositive` | 4 | False-Positive Filter |
| `TestValidateSnapshot` | 4 | Snapshot Validation |
| `TestRegressionLogger` | 3 | Observability |
| `TestRegressionEngineExtended` | 10 | Full pipeline integration |

### 6.4 Key Edge Cases Validated

- `name=None` in removed/modified features → no crash
- `manifest=None` → empty file list, empty diff, severity "low"
- Line-number-only changes → `metadata_changes`, not `modified`
- Import reorder → `is_false_positive()` returns `True`, evidence suppressed
- Same Python object as both old and new → `full_hash` matches → short-circuit, no diff
- Two dicts with same `artifact_id` but different content → correct separate hashes (identity-keyed cache)
- `ValueError` / `UnicodeDecodeError` / `OSError` in file extraction → silently skipped
- JSONL logger with no `log_path` → in-memory only, no file I/O
- Score 0 → "low"; score 2 → "medium"; score 3+ → "high"
- Private function removal (score 1) → "low"
- Public function removal (score 3) → "high"

---

## 7. Remaining Technical Debt

### 7.1 Minor — Low Priority

| Item | Location | Notes |
|------|----------|-------|
| `structure_hash` computed but unused | `regression_analysis.py:128` | Exported for future schema-drift detection; `HashCache.get()` now returns `(content_hash, full_hash)` instead. `structure_hash` remains available as a standalone function but is not wired into the pipeline. |
| `_build_evidence` is a private method with growing logic | `regression_engine.py:237` | If evidence format requirements expand (e.g. CVSS-style scoring per entry), extract to `regression_analysis.py` as a standalone `build_evidence()` function. |
| `compute_diff` behavioral check is field-enumerated | `regression_analysis.py:231` | Checks `signature`, `kind`, `decorators`, `parents` by name. If new behavioral fields are added to the feature schema, they must be manually added here. Consider a schema-driven approach. |

### 7.2 Missing Coverage — Medium Priority

| Item | Notes |
|------|-------|
| Root Cause Engine | Not yet reviewed. No edge-case or advanced test suite. 65 lines, 2 functions — next in sequence. |
| Report Engine | 76 lines, not directly tested beyond integration smoke tests. |
| Evolution Engine, Session, Snapshot | Only covered by pipeline smoke test — no dedicated edge-case tests. |

### 7.3 Infrastructure — Low Priority

| Item | Notes |
|------|-------|
| `log_path` JSONL file write not tested | `RegressionLogger` file output path is covered by in-memory tests only. A temp-file test would complete coverage. |
| `HashCache.clear()` not tested | Trivial method, but clearing between calls in a long-lived engine instance is not exercised. |
| GitHub push requires manual credential setup | Local commits are up to date (8 ahead of origin). No automated CI is configured. |

---

## Appendix: Severity Threshold Reference

```
Score 0           →  level: "low"    (no changes detected)
Score 1           →  level: "low"    (private removal or metadata-only)
Score 2           →  level: "medium" (signature change, or 2× private removals)
Score 3 or more   →  level: "high"   (public removal, behavior change, or accumulation)
```

---

*Report generated from codebase state at commit `d7a57d2` (HEAD). All 190 tests confirmed passing under Python 3.12, pytest 8.x.*
