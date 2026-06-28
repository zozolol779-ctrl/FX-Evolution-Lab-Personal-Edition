# Phase 3 — Full Codebase Audit Report
**FX Evolution Lab (Personal Edition)**
**Date:** 2026-06-28
**Scope:** All source files — no files modified, read-only analysis
**Test baseline at time of audit:** 190 / 190 passing

---

## Executive Summary

The codebase is **structurally sound** but carries significant **internal inconsistency** accumulated across seven engines. The core registry/session/artifact contract is solid. The problems are at the engine layer: four different artifact-lookup patterns, a schema layer that has completely drifted from what engines actually produce, one hardcoded bug in a schema class, duplicated AST parsing logic, inconsistent file-path matching, and a false-positive risk in the Report Engine. None of these are crashes — they are integration risks that grow more expensive to fix the longer they are left.

**Risk classification used below:**

| Symbol | Meaning |
|--------|---------|
| 🔴 | Correctness risk — wrong output or silent wrong behavior today |
| 🟠 | Integration risk — engines consuming each other's output could break |
| 🟡 | Maintainability debt — not broken today, costly tomorrow |
| 🔵 | Dead code or stub — present but inert |

---

## 1. `schemas.py` — Effectively Dead Code With Schema Drift

### 1.1 Usage

All 8 schema classes (`ManifestSchema`, `SnapshotSchema`, `DiffSchema`, `FeatureSchema`, `DependencySchema`, `ImpactSchema`, `RegressionSchema`, `RootCauseSchema`, `ReportSchema`) are imported **only** in `tests/test_core_architecture.py`. No engine imports from `schemas.py`.

**Every engine builds its own payload dict inline.**

`schemas.py` was the original contract definition layer. The engines evolved past it without updating it. The schemas are now a documentation artifact describing a schema that no longer exists in practice.

### 1.2 Field-level drift (confirmed by audit)

#### Feature Artifact

| Field | `FeatureSchema` | `FeatureEngine._register_feature` |
|-------|:-:|:-:|
| `feature_id` | ✅ | ✅ |
| `name` | ✅ | ✅ |
| `kind` | ✅ | ✅ |
| `signature` | ✅ | ✅ |
| `line_start` | ✅ | ✅ |
| `line_end` | ✅ | ✅ |
| `module_id` | ✅ | ❌ absent |
| `complexity` | ✅ | ❌ absent |
| `dependencies` | ✅ | ❌ absent |
| `decorators` | ❌ absent | ✅ |
| `parents` | ❌ absent | ✅ |
| `file_path` | ❌ absent | ✅ |
| `imports` | ❌ absent | ✅ |

**Verdict 🟠:** 3 schema fields are gone from the engine. 4 new engine fields are undocumented in the schema.

#### Diff Artifact

| Field | `DiffSchema` | `DiffEngine.compare` |
|-------|:-:|:-:|
| `change_id` | ✅ | ✅ |
| `old_snapshot` | ✅ | ✅ |
| `new_snapshot` | ✅ | ✅ |
| `change_type` | ✅ | ✅ |
| `lines_added` | ✅ | ✅ |
| `lines_removed` | ✅ | ✅ |
| `similarity` | ✅ | ✅ |
| `old_file_id` | ✅ | ❌ absent |
| `new_file_id` | ✅ | ❌ absent |
| `files_added` | ❌ absent | ✅ |
| `files_removed` | ❌ absent | ✅ |
| `files_modified` | ❌ absent | ✅ |
| `files_renamed` | ❌ absent | ✅ |
| `file_diffs` | ❌ absent | ✅ |

**Verdict 🟠:** The schema describes a file-pair diff; the engine produces a directory-level diff. Completely different semantic model.

#### Regression Artifact

| Field | `RegressionSchema` | `RegressionEngine.detect` |
|-------|:-:|:-:|
| `regression_id` | ✅ | ✅ |
| `severity` | ✅ | ✅ |
| `impacted_feature` | ✅ | ✅ |
| `impact_id` | ✅ | ✅ |
| `evidence_ids` | ✅ (list of ID refs) | ❌ absent |
| `evidence` | ❌ absent | ✅ (full dicts) |
| `diff_result` | ❌ absent | ✅ |
| `severity_score` | ❌ absent | ✅ |
| `false_positive_filtered` | ❌ absent | ✅ |
| `validation` | ❌ absent | ✅ |

**Verdict 🟠:** The schema uses ID references (`evidence_ids`). The engine stores full evidence dicts (`evidence`). Any code that reads `evidence_ids` from a real regression artifact gets `None`.

#### Root Cause Artifact

| Field | `RootCauseSchema` | `RootCauseEngine.analyze` |
|-------|:-:|:-:|
| `root_cause_id` | ✅ | ✅ |
| `regression_id` | ✅ | ✅ |
| `change_id` | ✅ | ✅ |
| `confidence` | ✅ | ✅ |
| `reasoning` | ✅ | ✅ |
| `evidence` | ❌ absent | ✅ |

**Verdict 🟡:** One field undocumented.

### 1.3 `SnapshotSchema` — hardcoded bug

```python
# schemas.py line 22
"manifest_id": "manifest-1",   # ← HARDCODED literal
```

```python
# snapshot.py line 14
"manifest_id": manifest["artifact_id"],   # ← correct
```

**Verdict 🔴:** Any test that uses `SnapshotSchema.create()` and then tries to look up the manifest via `snapshot["manifest_id"]` will fail — the artifact_id is a UUID-derived string, never the literal `"manifest-1"`. Currently this bug is contained because only `test_core_architecture.py` uses `SnapshotSchema`.

---

## 2. Four Incompatible Artifact Lookup Patterns

Every engine that needs to find another engine's artifact implements the lookup differently. There is no shared utility.

### Pattern A — `DiffEngine._find_artifact(artifact_id)`
```python
def _find_artifact(self, artifact_id: str) -> Dict[str, Any]:
    for a in self.registry.list_artifacts():
        if a["artifact_id"] == artifact_id:   # ← bare key access, no .get()
            return a
    raise KeyError(f"artifact {artifact_id} not found")
```
- Searches by **global `artifact_id`** only (the UUID assigned by the registry)
- Does NOT accept the payload-level `change_id`, `snapshot_id`, etc.
- Raises `KeyError` on miss
- Uses `a["artifact_id"]` (raises `KeyError` if field absent) not `a.get("artifact_id")`

### Pattern B — `ImpactEngine.assess` (inline loop)
```python
for a in self.registry.list_artifacts():
    if a.get("artifact_type") == "diff" and (
        a.get("artifact_id") == change_id or a.get("change_id") == change_id
    ):
```
- Type-scoped search
- Accepts **both** `artifact_id` AND payload-level `change_id` field
- Returns `None` on miss (falls back to lightweight impact)

### Pattern C — `RegressionEngine._find_artifact(artifact_type, lookup_id)` ← best
```python
def _find_artifact(self, artifact_type: str, lookup_id: str) -> Optional[Dict]:
    id_field = f"{artifact_type}_id"
    for a in self.registry.list_artifacts():
        if a.get("artifact_type") == artifact_type and (
            a.get("artifact_id") == lookup_id
            or a.get(id_field) == lookup_id
            or a.get("change_id") == lookup_id
        ):
            return a
    return None
```
- Type-scoped, dual-ID, returns `None` on miss
- Most robust pattern in the codebase

### Pattern D — `RootCauseEngine` (inline `next()` on long expressions)
```python
regression = next((a for a in self.registry.list_artifacts()
    if a.get("artifact_type") == "regression" and (
        a.get("artifact_id") == regression_id
        or a.get("regression_id") == regression_id
    )), None)
```
- Same logic as Pattern C, but inlined as 150-character one-liners
- Not reusable; three separate `next()` expressions in one method

**Verdict 🟠:** The same lookup semantics are implemented 4 ways. Pattern A (DiffEngine) is the weakest — it cannot accept payload-level IDs, which is how several callers pass arguments.

---

## 3. Fragile Sequential ID Generation

Every engine generates its payload-level ID using:

```python
f"<type>-{len(self.registry.list_artifacts()) + 1}"
```

**The ID depends on the registry state at the moment of registration.** If two artifacts of the same type are registered in sequence but other artifact types are registered in between, the IDs are non-sequential and unpredictable.

Example: registering a manifest (→ 1 artifact), then a snapshot (→ 2 artifacts), then a feature produces `feature-3`, not `feature-1`. This is fine for uniqueness purposes (since the registry also assigns a UUID-based `artifact_id`) but creates:

- Misleading ID values (`feature-37` when it is the 5th feature)
- Tests that assert specific ID values will be order-sensitive

The `registry.register()` separately produces a proper `artifact_id` (`artifact-{uuid8}`). But engines look each other up using the payload IDs (`change_id`, `impact_id`, etc.), not the registry UUID. This means the fragile counter-based IDs are part of the lookup contract.

**Verdict 🟡:** Not broken today. Would break silently if any engine were made concurrent or if registration order changed.

---

## 4. Import Parsing Logic — Duplicated in Two Engines

Both `FeatureEngine.extract_from_file` and `DependencyEngine.build_graph` implement the same AST walk to collect imports. The code is nearly character-for-character identical:

**FeatureEngine (lines 86–94):**
```python
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        for n in node.names:
            imports.append(n.name)
    elif isinstance(node, ast.ImportFrom):
        mod = node.module if node.module else ""
        for n in node.names:
            fq = f"{mod}.{n.name}" if mod else n.name
            imports.append(fq)
```

**DependencyEngine (lines 101–109):**
```python
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        for n in node.names:
            imports.append(n.name)
    elif isinstance(node, ast.ImportFrom):
        base = node.module if node.module else ""
        for n in node.names:
            fq = f"{base}.{n.name}" if base else n.name
            imports.append(fq)
```

Only the variable name differs (`mod` vs `base`).

**Verdict 🟡:** Any bug fix or extension (e.g. handling relative imports `from . import x`) must be applied in two places.

---

## 5. File-Path Matching — Inconsistent Boundary Guard

`ImpactEngine` has a correct boundary-guarded helper:
```python
def _file_path_matches(file_path: Any, rel_path: str) -> bool:
    return fp == rel_path or fp.endswith("/" + rel_path)
```
This prevents `old_src/utils.py` from falsely matching `src/utils.py`.

**`ReportEngine.build`** does NOT use this helper. It uses raw `endswith`:
```python
if any(file_path.endswith(p) for p in files_added):
    functions_added.append(feature.get("name"))
```

**`RootCauseEngine.analyze`** also uses raw `endswith` for file matching:
```python
if file and any(str(f).endswith(file) for f in diff.get("files_removed", [])):
```

**Verdict 🔴 (Report Engine), 🟠 (Root Cause Engine):** Projects with path prefixes like `old_src/` vs `src/` will produce wrong function-added/removed counts in the report, and wrong root-cause evidence in the root cause output.

---

## 6. `confidence` Field — Inconsistent Structure

Both `ImpactEngine` and `RootCauseEngine` produce a `confidence` dict, but with different contracts:

### ImpactEngine
```python
"confidence": {
    "score": float,           # 0.1 / 0.2 / 0.6 / 0.9
    "level": "low" | "medium" | "high",
    "reasoning": str,
    "evidence_refs": [str],   # list of artifact_ids, never None
}
```

### RootCauseEngine
```python
"confidence": {
    "score": float,           # 0.3 or 0.8
    "level": "high" | "low",  # ← no "medium" level
    "reasoning": str,
    "evidence_refs": [         # ← can contain None values
        diff.get("artifact_id") if diff else None,
        dep_graph.get("artifact_id") if dep_graph else None,
    ],
}
```

**Verdict 🟠:** Two problems:
1. `level` is `"low" | "medium" | "high"` in ImpactEngine but `"low" | "high"` only in RootCauseEngine (threshold is `>= 0.7 → "high"`, else `"low"`).
2. `evidence_refs` can contain `None` values in RootCauseEngine output. JSON serialisation works, but any consumer filtering `evidence_refs` for valid artifact IDs would silently include `null`.

---

## 7. `dependency` vs `dependency_graph` — Two Types, One `dependency_id` Field

`DependencyEngine` registers two completely different artifact types:

| Method | Registers type | Payload |
|--------|---------------|---------|
| `analyze(source, target)` | `"dependency"` | `{dependency_id, source_module, target_module, dependency_type, resolved}` |
| `build_graph(manifest)` | `"dependency_graph"` | `{dependency_id, edges, modules, cycle_detected, cycles}` |

Both use `dependency_id` as the payload-level ID field, but they describe fundamentally different things:
- `"dependency"` is a directed pair (source → target)
- `"dependency_graph"` is a full adjacency graph

**Lookup impact:**
- `ImpactEngine`, `ReportEngine`, `RootCauseEngine` all search for `"dependency_graph"` — they use `build_graph()` output
- `"dependency"` artifacts produced by `analyze()` are **registered but never searched** by any engine

**Verdict 🔵 (dependency type):** `DependencyEngine.analyze()` output is dead from the perspective of the downstream pipeline. Only `build_graph()` output is consumed.

---

## 8. Registered Artifact Types Never Searched by Any Engine

| Artifact Type | Registered by | Searched by |
|---------------|--------------|-------------|
| `manifest` | `ManifestEngine` | ❌ nobody |
| `snapshot` | `SnapshotEngine` | ❌ nobody |
| `evolution` | `EvolutionEngine` | ❌ nobody |
| `dependency` | `DependencyEngine.analyze` | ❌ nobody |
| `report` | `ReportEngine` | ❌ nobody |

`manifest` and `snapshot` artifacts ARE referenced by `artifact_id` (e.g. `snapshot.manifest_id` → `DiffEngine._find_artifact(manifest_id)`) — they are not searched by type but are looked up by ID. This is fine.

`evolution`, `dependency` (non-graph), and `report` artifacts are truly orphaned — registered but their `artifact_id` is never stored anywhere or used by any other engine.

**Verdict 🔵:** Not harmful. But `EvolutionEngine` and `DependencyEngine.analyze()` produce artifacts that go nowhere in the current pipeline.

---

## 9. `RootCauseEngine` — Code Quality Issues

### 9.1 Evidence type filter is too narrow and undocumented

```python
if item.get("type") in {"removed", "signature_changed"}:
```

`RegressionEngine._build_evidence` produces evidence items with type values from `{"removed", "signature_changed", "behavior_changed"}`. The `"behavior_changed"` type is silently ignored by `RootCauseEngine` — it produces no root-cause evidence for behavioral regressions. This may be intentional but is completely undocumented.

**Verdict 🟠:** A function whose kind/decorator/parent changed produces a regression with severity "high" but generates zero root-cause evidence.

### 9.2 `regression.get("regression_id")` can silently produce `None`

```python
"regression_id": regression.get("regression_id"),
```

If a regression artifact was registered without a `regression_id` payload field (e.g., from an older version of the engine), the output `root_cause_id` links to `None`. No crash, but a broken graph reference.

**Verdict 🟡:** Low probability. Easy to guard with `or regression_id`.

### 9.3 One-liner lookup expressions (readability)

```python
regression = next((a for a in self.registry.list_artifacts() if a.get("artifact_type") == "regression" and (a.get("artifact_id") == regression_id or a.get("regression_id") == regression_id)), None)
```

This is ~150 characters on one logical line. The same lookup logic exists in Pattern C (`RegressionEngine._find_artifact`) as a named, documented, reusable method. `RootCauseEngine` duplicates it as inline one-liners.

**Verdict 🟡:** Readability and maintainability.

---

## 10. Scanner — Two Always-Stub Fields

```python
"mtime": None,      # never populated — os.path.getmtime() not called
"entropy": 0.0,     # never computed — Shannon entropy not calculated
```

Both fields are declared in every file entry produced by `ScannerEngine` but never given real values. Any downstream consumer reading these fields gets meaningless data.

**Verdict 🔵:** Dead stub values. Either populate them or remove them from the schema.

---

## 11. Unused Import

`dependency_engine.py`:
```python
from typing import Any, Dict, List, Tuple
```

`Tuple` is imported but not used in any function signature or type annotation in the file.

**Verdict 🟡:** Minor. Static analysers (mypy, ruff) will flag this.

---

## 12. `EvolutionEngine` — Stub Implementation

19 lines total. `build_timeline()` simply collects snapshot artifact_ids and stores them with a count string. No analysis, no diff integration, no trend detection.

**Verdict 🔵:** Scaffolding only. Not harmful.

---

## 13. `ReportEngine` — `dependency_changes` Field is Misleading

```python
for dep in dependencies:
    dependency_changes.extend(dep.get("cycles", []))
```

`cycles` in a `dependency_graph` artifact is a `List[List[str]]` (each cycle is a list of node paths). `dependency_changes` in the report therefore becomes a list of lists — not a list of human-readable change descriptions. Any consumer expecting strings gets nested lists.

**Verdict 🟠:** The field name `dependency_changes` implies module-level dependency additions/removals. The actual content is detected import cycles. These are different concepts mixed under one name.

---

## Summary Table

| # | Finding | Severity | Engine(s) Affected |
|---|---------|----------|--------------------|
| 1 | `schemas.py` fields diverged from engines | 🟠 Integration | All |
| 2 | `SnapshotSchema.manifest_id` hardcoded to `"manifest-1"` | 🔴 Correctness | schemas.py |
| 3 | 4 different artifact lookup patterns | 🟠 Integration | Diff, Impact, Regression, RootCause |
| 4 | Raw `endswith()` in ReportEngine (no boundary guard) | 🔴 Correctness | ReportEngine |
| 5 | Raw `endswith()` in RootCauseEngine (no boundary guard) | 🟠 Integration | RootCauseEngine |
| 6 | `confidence.level` has no "medium" in RootCauseEngine | 🟠 Integration | RootCauseEngine |
| 7 | `confidence.evidence_refs` contains `None` values | 🟠 Integration | RootCauseEngine |
| 8 | `"behavior_changed"` evidence silently ignored | 🟠 Integration | RootCauseEngine |
| 9 | Import parsing duplicated in FeatureEngine + DependencyEngine | 🟡 Debt | Feature, Dependency |
| 10 | `dependency` artifacts registered but never consumed | 🔵 Dead code | DependencyEngine.analyze |
| 11 | `evolution` artifacts registered but never consumed | 🔵 Dead code | EvolutionEngine |
| 12 | `mtime` and `entropy` are always stub values | 🔵 Dead stubs | Scanner |
| 13 | Fragile `len(registry) + 1` ID generation | 🟡 Debt | All engines |
| 14 | `dependency_changes` in report mixes cycles with changes | 🟠 Integration | ReportEngine |
| 15 | `Tuple` imported but unused | 🟡 Debt | DependencyEngine |
| 16 | RootCauseEngine one-liner lookups (readability) | 🟡 Debt | RootCauseEngine |

---

## Recommended Fix Priorities Before Phase 4

### Fix immediately (before Root Cause Engine review)

1. **`SnapshotSchema` hardcoded `manifest_id`** — single line fix, no engine changes needed
2. **ReportEngine `endswith` → `_file_path_matches`** — move the existing helper to a shared module and use it

### Fix during Root Cause Engine review (Phase 3 engine work)

3. **RootCauseEngine boundary guard** — same fix as #2
4. **RootCauseEngine `confidence.level`** — add "medium" tier at threshold 0.5
5. **RootCauseEngine `evidence_refs` `None` values** — filter Nones before storing
6. **RootCauseEngine `"behavior_changed"` filter** — document or fix the evidence type set
7. **RootCauseEngine one-liner lookups** — extract to helper method

### Planned future work

8. **Shared `_find_artifact` utility** — extract `RegressionEngine._find_artifact` to registry or a shared helpers module; all engines use it
9. **Shared import parser** — extract the AST import walk to a module-level function in `feature_engine.py` or a new `ast_utils.py`; `DependencyEngine` imports and reuses it
10. **`schemas.py` — either sync or deprecate** — either update all schema classes to match current engine output (and add tests that compare schema vs engine), or remove the file and replace with dataclasses/TypedDicts used by the engines

---

*No files were modified to produce this report. All findings are based on static analysis of the source code as of commit `c62383b`.*
