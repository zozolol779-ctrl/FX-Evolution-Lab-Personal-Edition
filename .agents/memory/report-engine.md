---
name: Report Engine review
description: Sprint 4 Task 1 — bug found and fixed in report_engine.py; test count and commit ref
---

# Report Engine — Review Summary

## Bug Fixed: endswith false positive in path matching

`build()` used `file_path.endswith(p)` to match feature paths against diff file lists.
This produced false positives when the diff path was a string suffix of the feature path
without a separator boundary — e.g. `"xsrc/utils.py".endswith("src/utils.py")` → True.

**Fix:** Added module-level `_path_matches(feature_path, diff_path)` helper:
```
feature_path == diff_path or feature_path.endswith("/" + diff_path)
```

**Why:** Aligns with `ImpactEngine._file_path_matches()` (same direction, same boundary rule)
and `RootCauseEngine._file_matches()` (same rule, parameters inverted due to call context).

**How to apply:** Any new path-comparison in ReportEngine must use `_path_matches()`,
not raw `endswith()`. Future cleanup: extract one shared helper across all three engines.

## Known gap (not fixed here)
Path normalization is slash-specific. Mixed `\`/`/` separators and Windows-style paths
are not handled. Non-string entries in diff file lists could cause TypeErrors.

## Test count
56 Report Engine edge-case tests (54 pre-existing + 2 new reversed-suffix tests).

## Commit
92d4c15 — "Sprint 4: Task 1 - Report Engine review and bug fixes"
