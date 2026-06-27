# FX Evolution Lab - Architecture Documentation

## Overview

FX Evolution Lab is a **local-first software evolution analysis tool** designed to analyze code changes across multiple versions of a project and detect regressions, impacts, and root causes without any external dependencies, cloud services, or LLM integrations.

The system is built on a **registry-based artifact pipeline** where each analysis engine produces artifacts that are consumed by downstream engines.

---

## Core Principles

1. **Local-first**: All analysis runs locally; no external APIs or cloud services.
2. **No AI integration**: Pure deterministic analysis based on code structure and imports.
3. **Single-use workflow**: Built for the agreed TextFX analysis workflow only.
4. **Real analysis logic**: No placeholders or mock implementations; all logic performs actual code analysis.
5. **Artifact-driven**: Each engine produces typed artifacts that flow through the pipeline.

---

## System Architecture

### High-Level Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    ANALYSIS PIPELINE                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐                                               │
│  │   Session    │  ◄─ Run context (ID, operator, versions)     │
│  └──────┬───────┘                                               │
│         │                                                       │
│  ┌──────▼──────────┐                                            │
│  │  ArtifactRegistry│  ◄─ Central artifact store                │
│  └──────┬──────────┘                                            │
│         │                                                       │
│  ┌──────▼───────┐     ┌────────────┐     ┌────────────┐        │
│  │   Scanner    │────▶│ Manifest   │────▶│ Snapshot   │        │
│  │   (Files)    │     │ (Metadata) │     │ (Versions) │        │
│  └──────────────┘     └────────────┘     └──────┬─────┘        │
│                                                  │              │
│                                    ┌─────────────▼─────────┐   │
│                                    │   Diff Engine         │   │
│                                    │ (File Changes)        │   │
│                                    └─────────────┬─────────┘   │
│                                                  │              │
│           ┌──────────────────────────────────────┼──────────┐   │
│           │                                      │          │   │
│     ┌─────▼─────────┐                  ┌─────────▼──────┐   │   │
│     │Feature Engine │                  │Dependency      │   │   │
│     │(AST Parsing)  │                  │Graph           │   │   │
│     └─────┬─────────┘                  └─────────┬──────┘   │   │
│           │                                      │          │   │
│           └──────────────┬───────────────────────┘          │   │
│                          │                                  │   │
│           ┌──────────────▼──────────────┐  ┌─────────┐    │   │
│           │   Impact Engine             │  │Regression   │   │
│           │ (Dependency-driven changes) │  │Detection    │   │
│           └──────────────┬──────────────┘  └────┬────┘    │   │
│                          │                       │         │   │
│           ┌──────────────▼───────────────────────┼─────┐   │   │
│           │        Root Cause Engine            │     │   │   │
│           │ (Link regression to diff/deps)      │     │   │   │
│           └──────────────┬─────────────────────┬┘     │   │   │
│                          │                     │       │   │   │
│           ┌──────────────▼─────────────────────▼─────┐ │   │   │
│           │         Report Engine               │   │   │
│           │  (Summarize findings)               │   │   │   │
│           └──────────────┬─────────────────────┘   │   │   │
│                          │                         │   │   │
│                    ┌─────▼─────────────┐           │   │   │
│                    │   Final Report    │           │   │   │
│                    │  (All findings)   │           │   │   │
│                    └───────────────────┘           │   │   │
│                                                    │   │   │
└────────────────────────────────────────────────────┘───┘───┘
```

---

## Core Components

### 1. **AnalysisSession**
**Purpose**: Encapsulates metadata for a single analysis run.

**Attributes**:
- `run_id`: Unique identifier for the analysis
- `target_project`: Project path
- `target_version`: Version identifier
- `operator`: User performing the analysis
- `schema_version`: Data format version
- `started_at`, `finished_at`: Timestamps

**Responsibility**: Provide context to all engines; serve as the source of truth for timestamps and run metadata.

---

### 2. **ArtifactRegistry**
**Purpose**: Central store for all artifacts produced during the analysis.

**Methods**:
- `register(artifact_type, payload)`: Store an artifact and return it with metadata
- `list_artifacts()`: Retrieve all registered artifacts

**Key behavior**: 
- Every registered artifact receives a unique `artifact_id`
- Artifacts are immutable once registered
- Registry is session-scoped

**Responsibility**: Ensure artifact traceability and enable downstream engines to locate dependencies.

---

## Engine Specifications

### Scanner Engine
**File**: `scanner.py`

**Input**: File system root path

**Output**: File metadata (path, SHA-256, size, language, binary flag)

**Logic**:
1. Walk filesystem recursively
2. Compute SHA-256 hash for each file
3. Detect file language by extension
4. Mark binary files (null-byte detection)

**Key method**:
- `iter_files()`: Generator yielding file metadata

**Artifact produced**: None directly (output consumed by Manifest Engine)

---

### Manifest Engine
**File**: `manifest.py`

**Input**: Session, Registry, file list

**Output**: Manifest artifact

**Logic**:
1. Accept scanned files
2. Package with session metadata and schema version

**Key method**:
- `build(files)`: Create manifest artifact

**Artifact produced**: `manifest`
- `schema_version`: Data format version
- `generated_at`: Timestamp
- `root_path`: Project root
- `files`: Array of scanned file metadata

---

### Snapshot Engine
**File**: `snapshot.py`

**Input**: Manifest artifact

**Output**: Snapshot artifact

**Logic**:
1. Create a versioned reference to a manifest
2. Timestamp the snapshot for change tracking

**Key method**:
- `create(manifest)`: Create snapshot artifact

**Artifact produced**: `snapshot`
- `snapshot_id`: Identifier
- `manifest_id`: Reference to manifest artifact
- `timestamp`: When snapshot was created
- `project_version`: Version identifier

---

### Feature Engine
**File**: `feature_engine.py`

**Input**: Python file paths

**Output**: Feature artifacts (functions, classes, methods)

**Logic**:
1. Parse Python files using AST (Abstract Syntax Tree)
2. Extract top-level functions and classes
3. Extract methods from classes
4. Record decorators, signatures, line ranges, parent classes
5. Collect file-level imports

**Key methods**:
- `extract(module_name, name)`: Simple backward-compatible extractor
- `extract_from_file(file_path)`: Real AST-based extraction

**Artifact produced**: `feature` (one per function/class/method)
- `feature_id`: Identifier
- `name`: Symbol name
- `kind`: "function" | "class" | "method"
- `signature`: Function signature with parameters
- `decorators`: List of applied decorators
- `parents`: Parent class(es) for methods
- `line_start`, `line_end`: Source location
- `file_path`: Where feature is defined
- `imports`: File-level imports

**Supported constructs**:
- Functions (including `async def`)
- Classes
- Methods
- Decorators
- Parent classes
- Line ranges

**Limitations**:
- Does not extract nested inner functions as separate features
- Import list is file-scoped, not filtered per feature

---

### Diff Engine
**File**: `diff_engine.py`

**Input**: Two snapshots (old, new)

**Output**: Diff artifact

**Logic**:
1. Locate and load old/new manifests by artifact ID
2. Compare file lists by relative path
3. Detect added, removed, modified files by SHA-256
4. Detect renamed files: match old file SHA to new file with different path
5. For modified files:
   - Read file content
   - Use `difflib.SequenceMatcher` for line similarity
   - Count added/removed lines using unified diff
6. Calculate overall similarity score

**Key methods**:
- `compare(old_snapshot, new_snapshot)`: Perform file comparison

**Artifact produced**: `diff`
- `change_id`: Identifier
- `change_type`: "unchanged" | "modified"
- `files_added`: List of new files
- `files_removed`: List of deleted files
- `files_modified`: List of changed files
- `files_renamed`: List of (old_path, new_path) tuples
- `lines_added`: Total lines added across modified files
- `lines_removed`: Total lines removed
- `similarity`: Overall similarity score (0.0–1.0)
- `file_diffs`: Per-file diff details

**Edge cases**:
- Handles same-content renames via SHA matching
- Falls back to empty line counts when files are unreadable

---

### Dependency Engine
**File**: `dependency_engine.py`

**Input**: Manifest artifact

**Output**: Dependency graph artifact

**Logic**:
1. Build module map: map Python file paths to module names (e.g., `src/utils.py` → `src.utils`)
2. For each Python file in manifest:
   - Parse with AST to extract imports
   - Collect both `import` and `from ... import` statements
3. Resolve imports:
   - Try exact match to module map
   - Try suffix matching for relative imports
4. Build edges: `{source_file: [list of imported files]}`
5. Detect cycles using DFS:
   - Mark visited and stack nodes
   - If a node is in stack, a cycle exists
   - Record cycle paths

**Key methods**:
- `analyze(source, target)`: Simple backward-compatible pair analyzer
- `build_graph(manifest)`: Build full dependency graph

**Artifact produced**: `dependency_graph`
- `dependency_id`: Identifier
- `edges`: Dictionary `{file_path: [target_file_paths]}`
- `modules`: List of all discovered module files
- `cycle_detected`: Boolean
- `cycles`: List of cycle paths (each cycle is a list of file paths)

**Example**:
```
edges: {
  "src/a.py": ["src/b.py"],
  "src/b.py": ["src/c.py"],
  "src/c.py": ["src/a.py"]
}
cycles: [["src/a.py", "src/b.py", "src/c.py", "src/a.py"]]
cycle_detected: true
```

---

### Impact Engine
**File**: `impact_engine.py`

**Input**: Diff artifact ID

**Output**: Impact artifact

**Logic**:
1. Locate diff artifact by artifact_id or change_id
2. Gather affected files from diff (added, removed, modified, renamed)
3. Locate latest dependency graph artifact
4. Build reverse edges from graph: `{target_file: [dependents]}`
5. BFS from affected files through reverse edges to find all impacted modules
6. Find features that correspond to impacted modules (file-path suffix matching)
7. Determine impact level:
   - "high": if any files are removed
   - "medium": if ≥3 affected features exist
   - "low": otherwise

**Key methods**:
- `assess(change_id)`: Compute impact from diff

**Artifact produced**: `impact`
- `impact_id`: Identifier
- `change_id`: Reference to diff artifact
- `affected_features`: List of impacted feature IDs
- `affected_modules`: List of impacted file paths
- `impact_level`: "high" | "medium" | "low"
- `confidence`: Confidence scoring (score 0.0–1.0, level, reasoning, evidence refs)

---

### Regression Engine
**File**: `regression_engine.py`

**Input**: Impacted feature name, impact artifact ID

**Output**: Regression artifact

**Logic**:
1. Locate impact artifact
2. Locate related diff (from impact.change_id)
3. Locate old and new manifests (from diff)
4. Extract features from all Python files in both manifests
5. Compare feature sets using (file_path, name) tuples:
   - If feature exists in old but not new: mark as "removed"
   - If feature exists in both but signature differs: mark as "signature_changed"
6. Assign severity:
   - "high": removed public functions/classes (name doesn't start with `_`)
   - "medium": signature changes
   - "low": removed private functions

**Key methods**:
- `detect(impacted_feature, impact_id)`: Find regressions

**Artifact produced**: `regression`
- `regression_id`: Identifier
- `severity`: "high" | "medium" | "low"
- `impacted_feature`: Feature name passed to detector
- `impact_id`: Reference to impact artifact
- `evidence`: List of regression details
  - Each entry has `type` ("removed" | "signature_changed"), `name`, `file`, `severity`, `evidence` (old/new features)

---

### Root Cause Engine
**File**: `root_cause_engine.py`

**Input**: Regression artifact ID, diff artifact ID

**Output**: Root cause artifact

**Logic**:
1. Locate regression and diff artifacts
2. Locate latest dependency graph
3. For each regression evidence item (removed, signature_changed):
   - Find if file appears in diff (files_removed or files_modified)
   - Build reverse dependency chains: trace who imports the affected file
4. Correlate regression with diff and dependency information

**Key methods**:
- `analyze(regression_id, change_id)`: Link regression to root causes

**Artifact produced**: `root_cause`
- `root_cause_id`: Identifier
- `regression_id`: Reference to regression
- `change_id`: Reference to diff
- `confidence`: Confidence scoring
- `reasoning`: Text explanation
- `evidence`: Detailed analysis with:
  - `regression_item`: The regression evidence
  - `related_diff`: Which diff entries relate to this regression
  - `dependency_chains`: Who depends on the changed file

---

### Report Engine
**File**: `report_engine.py`

**Input**: Session, Registry, summary string, findings list

**Output**: Report artifact

**Logic**:
1. Query registry for all artifacts by type
2. Extract from diffs: files added/removed/modified
3. Extract from features:
   - Functions/classes added in new files
   - Functions/classes removed in deleted files
4. Extract from regressions: removed functions/classes from evidence
5. Extract from dependency graph: circular dependencies
6. Determine risk level:
   - "high": if regressions exist or high-impact findings
   - "medium": if impacts exist
   - "low": otherwise

**Key methods**:
- `build(summary, findings)`: Generate comprehensive report

**Artifact produced**: `report`
- `report_id`: Identifier
- `run_id`: Session run ID
- `summary`: User-provided summary
- `files_added`: List of new file paths
- `files_removed`: List of deleted file paths
- `files_modified`: List of changed file paths
- `functions_added`: Function names added
- `functions_removed`: Function names removed
- `classes_added`: Class names added
- `classes_removed`: Class names removed
- `dependency_changes`: Circular dependency cycles
- `regressions`: List of regression IDs
- `root_cause_findings`: List of root cause IDs
- `overall_risk_level`: "high" | "medium" | "low"
- `findings`: Detailed findings list
- `status`: "complete" | "needs_review"

---

## Artifact Flow

```
Session
   │
   ▼
ScannerEngine
   │ (file metadata)
   ▼
ManifestEngine ──────────────────┐
   │ (manifest artifact)         │
   ▼                             │
SnapshotEngine                   │
   │ (snapshot artifact)         │
   │                             │
   ├─────────────────────────────┤
   │ (old version snapshot)      │ (new version snapshot)
   │                             │
   ▼                             │
DiffEngine ◄────────────────────┘
   │ (diff artifact)
   │
   ├──────────────────────┬──────────────────┐
   │                      │                  │
   ▼                      ▼                  │
FeatureEngine ──▶ DependencyEngine          │
   │ (features)    │ (dep_graph)            │
   │               │                        │
   └───┬───────────┴────┬────────────────────┘
       │                │
       ▼                ▼
   ImpactEngine ◄─────────┘
       │ (impact artifact)
       │
       ▼
   RegressionEngine
       │ (regression artifact)
       │
       ▼
   RootCauseEngine
       │ (root_cause artifact)
       │
       ▼
   ReportEngine
       │
       ▼
   Final Report
```

---

## Key Data Structures

### Manifest
```json
{
  "artifact_id": "artifact-xxxx",
  "artifact_type": "manifest",
  "schema_version": "1.0",
  "generated_at": "2026-06-27T10:00:00+00:00",
  "root_path": "/path/to/project",
  "files": [
    {
      "file_id": "file-xxxx",
      "relative_path": "src/app.py",
      "sha256": "abc123...",
      "size": 1024,
      "language": "python",
      "binary_flag": false
    }
  ]
}
```

### Diff
```json
{
  "artifact_id": "artifact-xxxx",
  "artifact_type": "diff",
  "change_id": "change-1",
  "change_type": "modified",
  "files_added": ["src/new.py"],
  "files_removed": ["src/old.py"],
  "files_modified": ["src/app.py"],
  "files_renamed": [["src/utils.py", "src/helpers.py"]],
  "lines_added": 50,
  "lines_removed": 20,
  "similarity": 0.75
}
```

### Feature
```json
{
  "artifact_id": "artifact-xxxx",
  "artifact_type": "feature",
  "name": "login",
  "kind": "method",
  "signature": "login(self, username, password)",
  "decorators": ["@property"],
  "parents": ["User"],
  "line_start": 42,
  "line_end": 55,
  "file_path": "/path/to/project/src/auth.py",
  "imports": ["os", "sys.path"]
}
```

### Dependency Graph
```json
{
  "artifact_id": "artifact-xxxx",
  "artifact_type": "dependency_graph",
  "edges": {
    "src/app.py": ["src/utils.py", "src/auth.py"],
    "src/utils.py": ["src/config.py"],
    "src/auth.py": []
  },
  "cycle_detected": false,
  "cycles": []
}
```

### Impact
```json
{
  "artifact_id": "artifact-xxxx",
  "artifact_type": "impact",
  "change_id": "artifact-diff-id",
  "affected_modules": ["src/app.py", "src/utils.py"],
  "affected_features": ["feature-1", "feature-2"],
  "impact_level": "medium",
  "confidence": {
    "score": 0.7,
    "level": "medium",
    "reasoning": "Based on dependency propagation"
  }
}
```

---

## Integration Points

### Session-Registry Integration
Every engine receives both `session` and `registry`:
- `session` provides context (timestamps, project paths)
- `registry` stores and retrieves artifacts

### Artifact Linking
Artifacts reference each other by `artifact_id`:
- Snapshot → Manifest (via `manifest_id`)
- Diff → Snapshots (via `old_snapshot`, `new_snapshot`)
- Impact → Diff (via `change_id`)
- Regression → Impact (via `impact_id`)
- Root Cause → Regression, Diff, Dependency Graph

### Error Handling
Engines use explicit exception raising for missing dependencies:
- `KeyError` when a required artifact is not found
- This ensures artifact traceability and prevents silent failures

---

## Design Decisions

### Why Artifact Registry?
- **Traceability**: Every artifact is immutable and timestamped
- **Lineage**: Downstream engines can trace back to source data
- **Testability**: Registry enables unit testing in isolation
- **Extensibility**: New engines can query prior outputs without tight coupling

### Why Local-Only?
- **Privacy**: All code stays on disk
- **Speed**: No network latency
- **Simplicity**: No authentication, API, or telemetry
- **Reliability**: Reproducible results, no dependency on external services

### Why Real Analysis, Not Placeholders?
- **Accuracy**: Actual AST parsing, real diff computation, genuine cycle detection
- **Verifiability**: Outputs can be manually validated against source code
- **Maintainability**: Logic is deterministic and debuggable

---

## Future Extensibility (Out of Scope)

The following are **not** implemented and not planned:
- Graph databases (dependencies stored in JSON dicts)
- Distributed execution (single-threaded, single-machine)
- Microservices (monolithic Python package)
- DAG orchestration (sequential engine execution)
- Plugin ecosystems (fixed engine set)
- Cloud integrations (local-only)
- Machine learning (deterministic rules only)

---

This architecture is designed for the TextFX workflow and not for general extensibility.
