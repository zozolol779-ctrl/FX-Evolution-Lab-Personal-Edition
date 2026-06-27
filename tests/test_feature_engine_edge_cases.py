"""Edge case tests for FeatureEngine."""
import os
import tempfile
import unittest

from fx_evolution_lab.session import AnalysisSession
from fx_evolution_lab.registry import ArtifactRegistry
from fx_evolution_lab.feature_engine import FeatureEngine, _get_signature
import ast


def _make_engine():
    session = AnalysisSession(
        run_id="run-edge-001",
        target_project="test",
        target_version="1.0",
        operator="tester",
        schema_version="1.0",
    )
    registry = ArtifactRegistry(session)
    return FeatureEngine(session, registry)


def _write(tmpdir, filename, content):
    path = os.path.join(tmpdir, filename)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


class TestGetSignature(unittest.TestCase):
    """Unit tests for the _get_signature helper."""

    def _fn(self, src):
        tree = ast.parse(src)
        return tree.body[0]

    def test_simple_args(self):
        node = self._fn("def f(a, b, c): pass")
        self.assertEqual(_get_signature(node), "f(a, b, c)")

    def test_no_args(self):
        node = self._fn("def f(): pass")
        self.assertEqual(_get_signature(node), "f()")

    def test_vararg(self):
        node = self._fn("def f(*args): pass")
        self.assertEqual(_get_signature(node), "f(*args)")

    def test_kwarg(self):
        node = self._fn("def f(**kwargs): pass")
        self.assertEqual(_get_signature(node), "f(**kwargs)")

    def test_mixed_args_vararg_kwarg(self):
        node = self._fn("def f(a, b, *args, **kwargs): pass")
        self.assertEqual(_get_signature(node), "f(a, b, *args, **kwargs)")

    def test_kwonly_args(self):
        node = self._fn("def f(a, *, b, c): pass")
        self.assertEqual(_get_signature(node), "f(a, b, c)")

    def test_positional_only_args(self):
        """posonlyargs (def f(a, b, /, c)) must appear in the signature."""
        node = self._fn("def f(a, b, /, c): pass")
        sig = _get_signature(node)
        self.assertIn("a", sig)
        self.assertIn("b", sig)
        self.assertIn("c", sig)

    def test_async_function(self):
        """_get_signature must work on AsyncFunctionDef nodes too."""
        tree = ast.parse("async def run(x, y): pass")
        node = tree.body[0]
        self.assertIsInstance(node, ast.AsyncFunctionDef)
        sig = _get_signature(node)
        self.assertEqual(sig, "run(x, y)")


class TestExtractFromFile(unittest.TestCase):

    def setUp(self):
        self.engine = _make_engine()

    def test_empty_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "empty.py", "")
            features = self.engine.extract_from_file(path)
            self.assertEqual(features, [])

    def test_only_imports(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "imports_only.py", "import os\nfrom sys import path\n")
            features = self.engine.extract_from_file(path)
            self.assertEqual(features, [])

    def test_top_level_function(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "func.py", "def hello(name): return name\n")
            features = self.engine.extract_from_file(path)
            self.assertEqual(len(features), 1)
            self.assertEqual(features[0]["name"], "hello")
            self.assertEqual(features[0]["kind"], "function")
            self.assertIn("name", features[0]["signature"])

    def test_async_function(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "async_func.py", "async def fetch(url): pass\n")
            features = self.engine.extract_from_file(path)
            self.assertEqual(len(features), 1)
            self.assertEqual(features[0]["name"], "fetch")
            self.assertEqual(features[0]["kind"], "function")

    def test_class_with_methods(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "cls.py", (
                "class Animal:\n"
                "    def speak(self): pass\n"
                "    def eat(self, food): pass\n"
            ))
            features = self.engine.extract_from_file(path)
            names = {f["name"]: f for f in features}
            self.assertIn("Animal", names)
            self.assertIn("speak", names)
            self.assertIn("eat", names)
            self.assertEqual(names["Animal"]["kind"], "class")
            self.assertEqual(names["speak"]["kind"], "method")
            self.assertIn("Animal", names["speak"]["parents"])
            self.assertIn("Animal", names["eat"]["parents"])

    def test_class_no_methods(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "empty_class.py", "class Empty:\n    pass\n")
            features = self.engine.extract_from_file(path)
            self.assertEqual(len(features), 1)
            self.assertEqual(features[0]["name"], "Empty")
            self.assertEqual(features[0]["kind"], "class")

    def test_class_multiple_inheritance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "multi.py", "class C(A, B): pass\n")
            features = self.engine.extract_from_file(path)
            self.assertEqual(len(features), 1)
            self.assertIn("A", features[0]["parents"])
            self.assertIn("B", features[0]["parents"])

    def test_decorated_function(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "deco.py", (
                "@staticmethod\n"
                "def compute(x): return x\n"
            ))
            features = self.engine.extract_from_file(path)
            self.assertEqual(len(features), 1)
            self.assertIn("staticmethod", features[0]["decorators"])

    def test_decorated_class(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "deco_cls.py", "@dataclass\nclass Point:\n    x: int\n")
            features = self.engine.extract_from_file(path)
            self.assertEqual(len(features), 1)
            self.assertIn("dataclass", features[0]["decorators"])

    def test_function_with_positional_only_args(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "posonly.py", "def divide(a, b, /, *, rounding=True): pass\n")
            features = self.engine.extract_from_file(path)
            self.assertEqual(len(features), 1)
            sig = features[0]["signature"]
            self.assertIn("a", sig)
            self.assertIn("b", sig)

    def test_function_with_all_arg_types(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "allargs.py", "def f(a, b, /, c, *args, d, **kwargs): pass\n")
            features = self.engine.extract_from_file(path)
            self.assertEqual(len(features), 1)
            sig = features[0]["signature"]
            self.assertIn("a", sig)
            self.assertIn("b", sig)
            self.assertIn("c", sig)
            self.assertIn("*args", sig)
            self.assertIn("d", sig)
            self.assertIn("**kwargs", sig)

    def test_imports_captured(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "imports.py", (
                "import os\n"
                "from collections import OrderedDict\n"
                "def fn(): pass\n"
            ))
            features = self.engine.extract_from_file(path)
            self.assertEqual(len(features), 1)
            self.assertIn("os", features[0]["imports"])
            self.assertIn("collections.OrderedDict", features[0]["imports"])

    def test_line_numbers_are_correct(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "lines.py", (
                "\n"
                "def first(): pass\n"
                "\n"
                "def second(): pass\n"
            ))
            features = self.engine.extract_from_file(path)
            names = {f["name"]: f for f in features}
            self.assertEqual(names["first"]["line_start"], 2)
            self.assertEqual(names["second"]["line_start"], 4)

    def test_file_path_stored_in_artifact(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "stored.py", "def g(): pass\n")
            features = self.engine.extract_from_file(path)
            self.assertEqual(features[0]["file_path"], path)

    def test_root_path_makes_file_path_relative(self):
        """When root_path is provided, file_path in artifact should be relative."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "rel.py", "def h(): pass\n")
            features = self.engine.extract_from_file(path, root_path=tmpdir)
            self.assertEqual(features[0]["file_path"], "rel.py")

    def test_syntax_error_raises_value_error(self):
        """A file with a SyntaxError should raise ValueError, not SyntaxError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "broken.py", "def broken(:\n    pass\n")
            with self.assertRaises(ValueError):
                self.engine.extract_from_file(path)

    def test_nonexistent_file_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            self.engine.extract_from_file("/tmp/does_not_exist_xyz.py")

    def test_multiple_artifacts_registered(self):
        """Each feature must be a separate artifact in the registry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "multi.py", (
                "def alpha(): pass\n"
                "def beta(): pass\n"
                "def gamma(): pass\n"
            ))
            before = len(self.engine.registry.list_artifacts())
            features = self.engine.extract_from_file(path)
            after = len(self.engine.registry.list_artifacts())
            self.assertEqual(len(features), 3)
            self.assertEqual(after - before, 3)

    def test_nested_function_not_extracted(self):
        """Functions nested inside other functions are not top-level features."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "nested.py", (
                "def outer():\n"
                "    def inner(): pass\n"
                "    return inner\n"
            ))
            features = self.engine.extract_from_file(path)
            names = [f["name"] for f in features]
            self.assertIn("outer", names)
            self.assertNotIn("inner", names)

    def test_lambda_not_extracted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "lam.py", "square = lambda x: x * x\n")
            features = self.engine.extract_from_file(path)
            self.assertEqual(features, [])

    def test_artifact_type_is_feature(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "art.py", "def fn(): pass\n")
            features = self.engine.extract_from_file(path)
            self.assertEqual(features[0]["artifact_type"], "feature")

    def test_artifact_has_required_keys(self):
        required = {"artifact_id", "artifact_type", "name", "kind", "signature",
                    "decorators", "parents", "line_start", "line_end",
                    "file_path", "imports"}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "keys.py", "def fn(a, b): pass\n")
            features = self.engine.extract_from_file(path)
            for key in required:
                self.assertIn(key, features[0], msg=f"Missing key: {key}")


class TestExtractBackwardCompat(unittest.TestCase):

    def test_extract_returns_feature_artifact(self):
        engine = _make_engine()
        result = engine.extract("mymodule", "my_func")
        self.assertEqual(result["artifact_type"], "feature")
        self.assertEqual(result["name"], "my_func")

    def test_extract_multiple_calls_unique_ids(self):
        engine = _make_engine()
        r1 = engine.extract("mod", "f1")
        r2 = engine.extract("mod", "f2")
        self.assertNotEqual(r1["artifact_id"], r2["artifact_id"])


if __name__ == "__main__":
    unittest.main()
