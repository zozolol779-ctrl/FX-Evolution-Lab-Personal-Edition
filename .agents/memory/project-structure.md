---
name: Project structure
description: FX Evolution Lab layout, test command, engine review sequence, key conventions
---

# FX Evolution Lab — Project Structure

## Paths
- Source: `fx-evolution-lab/fx_evolution_lab/`
- Tests: `tests/`
- Test command: `PYTHONPATH=/home/runner/workspace/fx-evolution-lab python3 -m pytest tests/ -v`

## Engine review sequence (completed → pending)
1. ✅ Feature Engine
2. ✅ Diff Engine
3. ✅ Dependency Engine
4. ✅ Impact Engine
5. ✅ Regression Engine (+ production-grade upgrade via regression_analysis.py)
6. ✅ Root Cause Engine
7. ⬜ Report Engine
8. ⬜ Evolution Engine

## Test counts by engine (as of Root Cause Engine completion)
- Total: 229 / 229 passing
- Root Cause: 40 tests (39 edge cases + 1 integration)
- Regression: 75 tests
- Impact: 37, Feature: 37, Dependency: 25, Diff: 25, Core/misc: 9

## Conventions
- Edge case tests: `tests/test_<engine>_edge_cases.py`
- Advanced tests (regression only): `tests/test_regression_engine_advanced.py`
- Python 3.12, pytest via uv, pyproject.toml configures pytest at root
