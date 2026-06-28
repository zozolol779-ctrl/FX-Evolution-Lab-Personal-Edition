---
name: Root Cause Engine fixes
description: 4 bugs fixed in root_cause_engine.py during Phase 3 review
---

# Root Cause Engine — Fixed Bugs

## Bug 1: Raw endswith() — false positive file matching
`str(f).endswith(file)` matched `old_src/utils.py` against evidence file `src/utils.py`.
Fixed with `_file_matches(evidence_file, diff_path)` — boundary guard: `dp == ef or dp.endswith("/" + ef)`.
**Why:** Same pattern already in ImpactEngine._file_path_matches. Should eventually share one impl.

## Bug 2: "behavior_changed" silently ignored
Original filter: `{"removed", "signature_changed"}`. Added "behavior_changed".
**Why:** RegressionEngine produces 3 evidence types. Ignoring the third gave high-severity regressions with zero root-cause evidence.

## Bug 3: evidence_refs contains None
When diff or dep_graph absent, `None` was inserted into the list.
Fixed by building refs list conditionally — only append non-None artifact_ids.

## Bug 4: regression_id output can be None
`regression.get("regression_id")` returns None if payload field absent.
Fixed: `regression.get("regression_id") or regression_id` — falls back to lookup key.

## Refactor
Extracted 3 private helpers: `_find_regression`, `_find_diff`, `_latest_dep_graph`.
Extracted `_build_evidence` from inline `analyze()` body.
Module-level constant `_ANALYSED_EVIDENCE_TYPES` (frozenset).
