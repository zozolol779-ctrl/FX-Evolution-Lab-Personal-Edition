from __future__ import annotations

import ast
import os
from typing import Any, Dict, List, Tuple


class DependencyEngine:
    def __init__(self, session: Any, registry: Any):
        self.session = session
        self.registry = registry

    def analyze(self, source_module: str, target_module: str) -> Dict[str, Any]:
        """Backward-compatible pair registration."""
        resolved = bool(source_module and target_module and source_module != target_module)
        payload = {
            "dependency_id": f"dependency-{len(self.registry.list_artifacts()) + 1}",
            "source_module": source_module,
            "target_module": target_module,
            "dependency_type": "import",
            "resolved": resolved,
        }
        return self.registry.register("dependency", payload)

    def _resolve_import(self, import_name: str, module_map: Dict[str, str]) -> str | None:
        """Resolve an import name to a local relative path.

        Matching rules (in order):
        1. Exact match — ``import_name`` equals a key in ``module_map``.
        2. Package alias — ``import_name + ".__init__"`` is a key (handles
           ``import mypkg`` resolving to ``mypkg/__init__.py``).
        3. Dotted imports — for imports that contain a dot, check whether any
           candidate *starts* the import (``import_name.startswith(candidate + '.')``)
           or whether the candidate *ends* with the import at a dot boundary
           (``candidate.endswith('.' + import_name)``).

        Simple (no-dot) imports are matched only by rules 1 and 2 to avoid
        false positives like ``import b`` matching ``src/ab.py``.
        """
        # Rule 1: exact match
        if import_name in module_map:
            return module_map[import_name]

        # Rule 2: package __init__ alias
        init_key = import_name + ".__init__"
        if init_key in module_map:
            return module_map[init_key]

        # Rule 3: dotted-import fuzzy match (only for dotted names)
        if "." in import_name:
            for candidate, rel_path in module_map.items():
                if (import_name.startswith(candidate + ".") or
                        candidate.endswith("." + import_name)):
                    return rel_path

        return None

    def build_graph(self, manifest: Dict[str, Any]) -> Dict[str, Any]:
        """Build a dependency graph from a manifest artifact.

        Returns a registered ``dependency_graph`` artifact with edges and
        cycle-detection results.
        """
        files = manifest.get("files", [])
        root = manifest.get("root_path", self.session.target_project)

        # Build module_map: dotted-module-name → relative-path
        # For ``pkg/__init__.py`` register *both* ``pkg.__init__`` and ``pkg``
        # so that ``import pkg`` resolves correctly.
        module_map: Dict[str, str] = {}
        for f in files:
            rel = f.get("relative_path")
            if not rel:
                continue
            mod_name = rel[:-3] if rel.endswith(".py") else rel
            mod_name = mod_name.replace("/", ".")
            module_map[mod_name] = rel
            # package alias: mypkg.__init__ → also register as mypkg
            if mod_name.endswith(".__init__"):
                pkg_name = mod_name[: -len(".__init__")]
                if pkg_name not in module_map:
                    module_map[pkg_name] = rel

        # Parse each Python file for imports
        edges: Dict[str, List[str]] = {}
        for mod, rel in list(module_map.items()):
            # Skip the synthetic package aliases (they point to the same file
            # as the __init__ entry; we build edges only for real file keys)
            if not rel.endswith(".py") and "." not in rel:
                continue
            # Each relative path should appear only once in edges
            if rel in edges:
                continue

            path = os.path.join(root, rel)
            imports: List[str] = []
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    source = fh.read()
                tree = ast.parse(source, filename=path)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for n in node.names:
                            imports.append(n.name)
                    elif isinstance(node, ast.ImportFrom):
                        base = node.module if node.module else ""
                        for n in node.names:
                            fq = f"{base}.{n.name}" if base else n.name
                            imports.append(fq)
            except (FileNotFoundError, OSError, SyntaxError):
                imports = []

            # Resolve imports to local relative paths
            resolved_targets: List[str] = []
            for imp in imports:
                if not imp:
                    continue
                base = imp.split(".")[0]
                for candidate_name in (imp, base):
                    resolved = self._resolve_import(candidate_name, module_map)
                    if resolved and resolved not in resolved_targets and resolved != rel:
                        resolved_targets.append(resolved)
                        break

            edges[rel] = sorted(set(resolved_targets))

        # Detect cycles using iterative DFS to avoid recursion limits
        visited: set = set()
        stack_set: set = set()
        cycles: List[List[str]] = []

        def dfs(start: str):
            call_stack = [(start, [start], iter(edges.get(start, [])))]
            stack_set.add(start)
            visited.add(start)
            while call_stack:
                node, path, children = call_stack[-1]
                try:
                    child = next(children)
                    if child in stack_set:
                        idx = path.index(child) if child in path else 0
                        cycles.append(path[idx:])
                    elif child not in visited:
                        visited.add(child)
                        stack_set.add(child)
                        call_stack.append((child, path + [child], iter(edges.get(child, []))))
                except StopIteration:
                    call_stack.pop()
                    stack_set.discard(node)

        for n in list(edges.keys()):
            if n not in visited:
                dfs(n)

        payload = {
            "dependency_id": f"dependency-{len(self.registry.list_artifacts()) + 1}",
            "edges": edges,
            "modules": list(dict.fromkeys(
                f.get("relative_path") for f in files if f.get("relative_path")
            )),
            "cycle_detected": bool(cycles),
            "cycles": cycles,
        }
        return self.registry.register("dependency_graph", payload)
