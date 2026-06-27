from __future__ import annotations

import ast
import os
from typing import Any, Dict, List, Tuple


class DependencyEngine:
    def __init__(self, session: Any, registry: Any):
        self.session = session
        self.registry = registry

    def analyze(self, source_module: str, target_module: str) -> Dict[str, Any]:
        # keep backward compatibility: simple pair registration
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
        if import_name in module_map:
            return module_map[import_name]
        if import_name.endswith('.__init__'):
            import_name = import_name[:-9]
        for candidate, rel_path in module_map.items():
            if candidate == import_name or candidate.endswith(import_name) or import_name.endswith(candidate):
                return rel_path
        return None

    def build_graph(self, manifest: Dict[str, Any]) -> Dict[str, Any]:
        """Build dependency graph from a manifest artifact (which contains 'files').

        Returns payload with edges and cycle detection.
        """
        files = manifest.get("files", [])
        root = manifest.get("root_path", self.session.target_project)

        # map candidate module names to relative paths
        module_map = {}
        for f in files:
            rel = f.get("relative_path")
            if not rel:
                continue
            mod_name = rel[:-3] if rel.endswith('.py') else rel
            mod_name = mod_name.replace('/', '.')
            module_map[mod_name] = rel

        # parse each python file for imports
        edges: Dict[str, List[str]] = {}
        for mod, rel in module_map.items():
            path = os.path.join(root, rel)
            imports = []
            try:
                with open(path, 'r', encoding='utf-8') as fh:
                    tree = ast.parse(fh.read(), filename=path)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for n in node.names:
                            imports.append(n.name)
                    elif isinstance(node, ast.ImportFrom):
                        base = node.module if node.module else ''
                        for n in node.names:
                            fq = f"{base}.{n.name}" if base else n.name
                            imports.append(fq)
            except FileNotFoundError:
                imports = []

            # resolve imports to local modules when possible
            resolved_targets = []
            for imp in imports:
                if not imp:
                    continue
                base = imp.split('.')[0]
                for candidate_name in (imp, base):
                    resolved = self._resolve_import(candidate_name, module_map)
                    if resolved and resolved not in resolved_targets:
                        resolved_targets.append(resolved)
                        break

            edges[rel] = sorted(set(resolved_targets))

        # detect cycles using DFS
        visited = set()
        stack = set()
        cycles: List[List[str]] = []

        def dfs(node: str, path: List[str]):
            if node in stack:
                # cycle found
                idx = path.index(node) if node in path else 0
                cycles.append(path[idx:])
                return
            if node in visited:
                return
            visited.add(node)
            stack.add(node)
            for nbr in edges.get(node, []):
                dfs(nbr, path + [nbr])
            stack.remove(node)

        for n in list(edges.keys()):
            if n not in visited:
                dfs(n, [n])

        payload = {
            "dependency_id": f"dependency-{len(self.registry.list_artifacts()) + 1}",
            "edges": edges,
            "modules": list(module_map.values()),
            "cycle_detected": bool(cycles),
            "cycles": cycles,
        }
        return self.registry.register("dependency_graph", payload)
