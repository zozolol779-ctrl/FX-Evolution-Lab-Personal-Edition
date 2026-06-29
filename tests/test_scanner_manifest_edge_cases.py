"""
Edge-case tests for ScannerEngine and ManifestEngine.

ScannerEngine covers:
- Empty directory yields no files
- File fields: file_id, relative_path, sha256, size, binary_flag, language
- Language detection for all supported extensions + unknown
- Binary file detection (null-byte heuristic)
- relative_path uses forward slashes regardless of OS
- Nested directory traversal
- Ignore rules: by directory name, by full path, for individual files
- Sorted filename output

ManifestEngine covers:
- artifact_type is "manifest"
- Required payload fields present
- files list reflected correctly
- Empty files list
- None files argument guarded (no None stored)
- Multiple files
- session fields (schema_version, root_path) reflected
- Registered in registry
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from typing import Any, Dict

from fx_evolution_lab.registry import ArtifactRegistry
from fx_evolution_lab.manifest import ManifestEngine
from fx_evolution_lab.scanner import ScannerEngine
from fx_evolution_lab.session import AnalysisSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _session(tmpdir: str = "/proj") -> AnalysisSession:
    return AnalysisSession(
        run_id="run-scanner-test",
        target_project=tmpdir,
        target_version="1.0",
        operator="tester",
        schema_version="1.0",
    )


def _registry(tmpdir: str = "/proj") -> ArtifactRegistry:
    return ArtifactRegistry(_session(tmpdir))


def _write(directory: str, name: str, content: str = "hello\n") -> str:
    path = os.path.join(directory, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


def _write_binary(directory: str, name: str, data: bytes = b"\x00\x01\x02") -> str:
    path = os.path.join(directory, name)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


# ---------------------------------------------------------------------------
# ScannerEngine tests
# ---------------------------------------------------------------------------

class TestScannerEmpty(unittest.TestCase):
    def test_empty_directory_yields_nothing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            files = list(ScannerEngine(tmpdir).iter_files())
            self.assertEqual(files, [])


class TestScannerFileFields(unittest.TestCase):
    """Each scanned file dict has required fields with correct values."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        content = "print('hi')\n"
        self.content_bytes = content.encode("utf-8")
        _write(self.tmpdir, "hello.py", content)
        self.files = list(ScannerEngine(self.tmpdir).iter_files())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_required_keys_present(self):
        f = self.files[0]
        for key in ("file_id", "relative_path", "sha256", "size", "binary_flag", "language"):
            self.assertIn(key, f, f"Missing key: {key}")

    def test_file_id_format(self):
        f = self.files[0]
        self.assertTrue(f["file_id"].startswith("file-"))

    def test_sha256_correct(self):
        expected = hashlib.sha256(self.content_bytes).hexdigest()
        self.assertEqual(self.files[0]["sha256"], expected)

    def test_size_correct(self):
        self.assertEqual(self.files[0]["size"], len(self.content_bytes))

    def test_binary_flag_false_for_text(self):
        self.assertFalse(self.files[0]["binary_flag"])

    def test_language_python(self):
        self.assertEqual(self.files[0]["language"], "python")

    def test_relative_path_uses_forward_slash(self):
        self.assertNotIn("\\", self.files[0]["relative_path"])

    def test_relative_path_matches_filename(self):
        self.assertEqual(self.files[0]["relative_path"], "hello.py")


class TestScannerLanguageDetection(unittest.TestCase):
    """_detect_language returns correct language for each extension."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _scan_one(self, filename: str) -> Dict[str, Any]:
        _write(self.tmpdir, filename)
        return list(ScannerEngine(self.tmpdir).iter_files())[-1]

    def test_py_detected_as_python(self):
        f = self._scan_one("script.py")
        self.assertEqual(f["language"], "python")

    def test_md_detected_as_markdown(self):
        f = self._scan_one("README.md")
        self.assertEqual(f["language"], "markdown")

    def test_json_detected_as_json(self):
        f = self._scan_one("config.json")
        self.assertEqual(f["language"], "json")

    def test_txt_detected_as_text(self):
        f = self._scan_one("notes.txt")
        self.assertEqual(f["language"], "text")

    def test_unknown_extension_detected_as_unknown(self):
        f = self._scan_one("data.csv")
        self.assertEqual(f["language"], "unknown")

    def test_no_extension_detected_as_unknown(self):
        f = self._scan_one("Makefile")
        self.assertEqual(f["language"], "unknown")


class TestScannerBinaryDetection(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_binary_flag_true_for_null_byte_file(self):
        _write_binary(self.tmpdir, "binary.bin", b"\x00\x01\x02")
        files = list(ScannerEngine(self.tmpdir).iter_files())
        self.assertTrue(files[0]["binary_flag"])

    def test_binary_flag_false_for_empty_file(self):
        _write_binary(self.tmpdir, "empty.txt", b"")
        files = list(ScannerEngine(self.tmpdir).iter_files())
        self.assertFalse(files[0]["binary_flag"])


class TestScannerNestedDirectories(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        _write(self.tmpdir, "top.py")
        _write(self.tmpdir, os.path.join("sub", "nested.py"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_nested_files_discovered(self):
        paths = [f["relative_path"] for f in ScannerEngine(self.tmpdir).iter_files()]
        self.assertIn("sub/nested.py", paths)
        self.assertIn("top.py", paths)

    def test_total_count(self):
        files = list(ScannerEngine(self.tmpdir).iter_files())
        self.assertEqual(len(files), 2)


class TestScannerIgnoreRules(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        _write(self.tmpdir, "keep.py")
        _write(self.tmpdir, os.path.join("__pycache__", "cached.pyc"))
        _write(self.tmpdir, "skip_me.txt")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_ignore_directory_by_name(self):
        scanner = ScannerEngine(self.tmpdir, ignore_rules={"__pycache__"})
        paths = [f["relative_path"] for f in scanner.iter_files()]
        self.assertNotIn("__pycache__/cached.pyc", paths)

    def test_ignore_file_by_full_path(self):
        skip_path = os.path.join(self.tmpdir, "skip_me.txt")
        scanner = ScannerEngine(self.tmpdir, ignore_rules={skip_path})
        paths = [f["relative_path"] for f in scanner.iter_files()]
        self.assertNotIn("skip_me.txt", paths)

    def test_non_ignored_file_still_scanned(self):
        scanner = ScannerEngine(self.tmpdir, ignore_rules={"__pycache__"})
        paths = [f["relative_path"] for f in scanner.iter_files()]
        self.assertIn("keep.py", paths)

    def test_no_ignore_rules_scans_everything(self):
        scanner = ScannerEngine(self.tmpdir)
        files = list(scanner.iter_files())
        self.assertEqual(len(files), 3)


class TestScannerSortedOutput(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        for name in ("zebra.py", "alpha.py", "mango.py"):
            _write(self.tmpdir, name)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_filenames_sorted_within_directory(self):
        names = [f["relative_path"] for f in ScannerEngine(self.tmpdir).iter_files()]
        self.assertEqual(names, sorted(names))


# ---------------------------------------------------------------------------
# ManifestEngine tests
# ---------------------------------------------------------------------------

class TestManifestSchema(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reg = _registry(self.tmpdir)
        self.engine = ManifestEngine(self.reg.session, self.reg)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_artifact_type_is_manifest(self):
        result = self.engine.build([])
        self.assertEqual(result["artifact_type"], "manifest")

    def test_required_fields_present(self):
        result = self.engine.build([])
        for key in ("schema_version", "generated_at", "root_path", "files"):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_schema_version_matches_session(self):
        result = self.engine.build([])
        self.assertEqual(result["schema_version"], self.reg.session.schema_version)

    def test_root_path_matches_session(self):
        result = self.engine.build([])
        self.assertEqual(result["root_path"], self.reg.session.target_project)

    def test_registered_in_registry(self):
        before = len(self.reg.list_artifacts())
        self.engine.build([])
        self.assertEqual(len(self.reg.list_artifacts()), before + 1)


class TestManifestFiles(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reg = _registry(self.tmpdir)
        self.engine = ManifestEngine(self.reg.session, self.reg)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_files_list(self):
        result = self.engine.build([])
        self.assertEqual(result["files"], [])

    def test_files_stored_correctly(self):
        fake_files = [{"file_id": "file-abc", "relative_path": "src/main.py"}]
        result = self.engine.build(fake_files)
        self.assertEqual(result["files"], fake_files)

    def test_multiple_files(self):
        fake_files = [
            {"file_id": "file-001", "relative_path": "a.py"},
            {"file_id": "file-002", "relative_path": "b.py"},
        ]
        result = self.engine.build(fake_files)
        self.assertEqual(len(result["files"]), 2)

    def test_none_files_gives_empty_list(self):
        """build(None) must not store None — must store []."""
        result = self.engine.build(None)
        self.assertIsInstance(result["files"], list)
        self.assertEqual(result["files"], [])


class TestManifestScannerIntegration(unittest.TestCase):
    """Scanner output feeds directly into ManifestEngine."""

    def test_scanner_to_manifest_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, "main.py")
            _write(tmpdir, "utils.md")
            session = _session(tmpdir)
            reg = ArtifactRegistry(session)
            files = list(ScannerEngine(tmpdir).iter_files())
            result = ManifestEngine(session, reg).build(files)
            self.assertEqual(result["artifact_type"], "manifest")
            self.assertEqual(len(result["files"]), 2)
            languages = {f["language"] for f in result["files"]}
            self.assertIn("python", languages)
            self.assertIn("markdown", languages)


if __name__ == "__main__":
    unittest.main()
