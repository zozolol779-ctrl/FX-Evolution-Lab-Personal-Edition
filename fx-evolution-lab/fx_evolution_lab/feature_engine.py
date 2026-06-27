from __future__ import annotations

import ast
import os
from typing import Any, Dict, List, Optional, Union


def _get_signature(node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> str:
    """Build a human-readable signature string from a function/method AST node.

    Handles all argument categories in the correct order:
      positional-only (a, b, /)  →  posonlyargs
      regular                    →  args
      var-positional              →  *vararg
      keyword-only               →  kwonlyargs
      var-keyword                →  **kwarg
    """
    parts = []
    for arg in node.args.posonlyargs:
        parts.append(arg.arg)
    for arg in node.args.args:
        parts.append(arg.arg)
    if node.args.vararg:
        parts.append(f"*{node.args.vararg.arg}")
    for kw in node.args.kwonlyargs:
        parts.append(kw.arg)
    if node.args.kwarg:
        parts.append(f"**{node.args.kwarg.arg}")
    return f"{node.name}({', '.join(parts)})"


class FeatureEngine:
    def __init__(self, session: Any, registry: Any):
        self.session = session
        self.registry = registry

    def extract(self, module_name: str, name: str) -> Dict[str, Any]:
        """Backwards-compatible simple extractor (kept for tests that call it directly)."""
        payload = {
            "feature_id": f"feature-{len(self.registry.list_artifacts()) + 1}",
            "module_id": f"module-{module_name}",
            "name": name,
            "kind": "function",
            "signature": f"{name}()",
            "complexity": 1,
            "line_start": 1,
            "line_end": 1,
            "dependencies": [],
            "file_path": None,
        }
        return self.registry.register("feature", payload)

    def extract_from_file(self, file_path: str, root_path: Optional[str] = None) -> List[Dict[str, Any]]:
        """Parse a Python file using AST and register features found.

        Args:
            file_path:  Absolute (or relative) path to the Python source file.
            root_path:  When provided, ``file_path`` stored in each artifact is
                        made relative to this directory instead of stored as-is.

        Returns:
            List of registered feature artifacts (one per top-level function,
            async function, class, or method found).

        Raises:
            FileNotFoundError: If ``file_path`` does not exist.
            ValueError:        If the file cannot be parsed (e.g. syntax error).
        """
        with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
            source = fh.read()

        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError as exc:
            raise ValueError(
                f"Could not parse '{file_path}': {exc}"
            ) from exc

        stored_path = (
            os.path.relpath(file_path, root_path) if root_path is not None else file_path
        )

        features: List[Dict[str, Any]] = []

        imports: List[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    imports.append(n.name)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module if node.module else ""
                for n in node.names:
                    fq = f"{mod}.{n.name}" if mod else n.name
                    imports.append(fq)

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                sig = _get_signature(node)
                payload = self._register_feature(
                    name=node.name,
                    kind="function",
                    signature=sig,
                    decorators=[ast.unparse(d) for d in node.decorator_list] if node.decorator_list else [],
                    parents=[],
                    line_start=node.lineno,
                    line_end=getattr(node, "end_lineno", node.lineno),
                    file_path=stored_path,
                    imports=imports,
                )
                features.append(payload)
            elif isinstance(node, ast.ClassDef):
                bases = [ast.unparse(b) for b in node.bases] if node.bases else []
                class_payload = self._register_feature(
                    name=node.name,
                    kind="class",
                    signature=None,
                    decorators=[ast.unparse(d) for d in node.decorator_list] if node.decorator_list else [],
                    parents=bases,
                    line_start=node.lineno,
                    line_end=getattr(node, "end_lineno", node.lineno),
                    file_path=stored_path,
                    imports=imports,
                )
                features.append(class_payload)

                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        sig = _get_signature(item)
                        method_payload = self._register_feature(
                            name=item.name,
                            kind="method",
                            signature=sig,
                            decorators=[ast.unparse(d) for d in item.decorator_list] if item.decorator_list else [],
                            parents=[node.name],
                            line_start=item.lineno,
                            line_end=getattr(item, "end_lineno", item.lineno),
                            file_path=stored_path,
                            imports=imports,
                        )
                        features.append(method_payload)

        return features

    def _register_feature(
        self,
        name: str,
        kind: str,
        signature: Optional[str],
        decorators: List[str],
        parents: List[str],
        line_start: int,
        line_end: int,
        file_path: str,
        imports: List[str],
    ) -> Dict[str, Any]:
        payload = {
            "feature_id": f"feature-{len(self.registry.list_artifacts()) + 1}",
            "name": name,
            "kind": kind,
            "signature": signature,
            "decorators": decorators,
            "parents": parents,
            "line_start": line_start,
            "line_end": line_end,
            "file_path": file_path,
            "imports": imports,
        }
        return self.registry.register("feature", payload)
