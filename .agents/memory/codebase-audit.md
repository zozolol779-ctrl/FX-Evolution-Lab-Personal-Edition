---
name: Codebase audit findings
description: Cross-engine consistency audit — schemas.py drift, lookup patterns, endswith false positives
---

# Phase 3 Codebase Audit — Key Findings

## schemas.py — dead code
All 8 schema classes are ONLY used in test_core_architecture.py (3 tests). No engine imports schemas.py.
Fields have drifted significantly from what engines actually produce. See PHASE3_CODEBASE_AUDIT_REPORT.md for full table.
SnapshotSchema hardcodes `manifest_id = "manifest-1"` — broken (SnapshotEngine correctly uses `manifest["artifact_id"]`).

## 4 different artifact lookup patterns
- DiffEngine._find_artifact(artifact_id) — by UUID only, raises KeyError, bare key access
- ImpactEngine — inline loop, dual-ID (artifact_id OR change_id field), returns None on miss
- RegressionEngine._find_artifact(type, id) — BEST: type-scoped, dual-ID, returns None
- RootCauseEngine — inline next() one-liners (fixed to 3 helper methods)

## Fragile ID generation
`f"<type>-{len(registry.list_artifacts()) + 1}"` — IDs depend on registry state at registration time. Not broken but non-deterministic ordering is a risk.

## endswith false positives
ReportEngine.build() uses raw endswith() for file_path matching. old_src/utils.py matches src/utils.py.
ImpactEngine has the correct _file_path_matches() helper — not shared.
RootCauseEngine had the same bug — FIXED.

## dependency vs dependency_graph
Two artifact types: "dependency" (pair) and "dependency_graph" (full graph).
Only "dependency_graph" is ever searched by downstream engines. "dependency" artifacts are registered but never consumed.

## Registered but never searched artifact types
report, manifest, snapshot, evolution, dependency (non-graph) — all registered, never searched by type.

## confidence.level inconsistency
ImpactEngine: low/medium/high. RootCauseEngine was low/high only — FIXED to low/medium/high.

## Import parsing duplication
FeatureEngine and DependencyEngine both implement identical AST import parsing. Should extract to shared utility.
