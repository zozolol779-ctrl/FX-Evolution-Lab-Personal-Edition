---
name: Regression Engine upgrade
description: Production-grade upgrade details — hashing, severity, HashCache key choice
---

# Regression Engine — Key Decisions

## HashCache key
Keyed on `id(artifact)` (Python object identity), NOT `artifact_id`.
**Why:** Two different dict objects can share the same `artifact_id` (common in tests with synthetic artifacts). Identity-based caching avoids false cache hits.

## Two-tier hash system
- `content_hash` — excludes line_start, line_end, file_path, imports, runtime IDs → behavioral fingerprint
- `full_hash` — excludes only runtime IDs (includes line_start, line_end, file_path) → total fingerprint
- `HashCache.get()` returns `(content_hash, full_hash)`
- `compute_diff` short-circuits on `full_hash` match (byte-for-byte identical)

## Severity thresholds
- score 0–1 → "low"
- score 2 → "medium"
- score 3+ → "high"
- Single public removal = score 3 = "high"
- Single private removal = score 1 = "low"
- Signature change = score 2 = "medium"

## regression_analysis.py modules
7 pure, side-effect-free helpers: Normalize Layer, Hashing System, Structured Diff, Severity Scoring, False-Positive Filter, Snapshot Validation, RegressionLogger (JSONL).
