"""Edge case tests for DiffEngine."""
import os
import tempfile
import unittest

from fx_evolution_lab.session import AnalysisSession
from fx_evolution_lab.registry import ArtifactRegistry
from fx_evolution_lab.scanner import ScannerEngine
from fx_evolution_lab.manifest import ManifestEngine
from fx_evolution_lab.snapshot import SnapshotEngine
from fx_evolution_lab.diff_engine import DiffEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _build_snapshot(tmpdir, files: dict, run_id: str):
    """Scan `tmpdir`, build a manifest + snapshot, return (registry, snapshot)."""
    for rel, content in files.items():
        _write(os.path.join(tmpdir, rel), content)
    session = AnalysisSession(
        run_id=run_id,
        target_project=tmpdir,
        target_version="1.0",
        operator="tester",
        schema_version="1.0",
    )
    registry = ArtifactRegistry(session)
    scanner = ScannerEngine(tmpdir)
    manifest = ManifestEngine(session, registry).build(list(scanner.iter_files()))
    snapshot = SnapshotEngine(session, registry).create(manifest)
    return registry, snapshot


def _merged(old_reg, old_snap, new_reg, new_snap, target_dir):
    """Merge two registries into one and return (engine, diff)."""
    merged_session = AnalysisSession(
        run_id="run-merged",
        target_project=target_dir,
        target_version="1.0",
        operator="tester",
        schema_version="1.0",
    )
    merged_registry = ArtifactRegistry(merged_session)
    for a in old_reg.list_artifacts():
        merged_registry.entries.append(a)
    for a in new_reg.list_artifacts():
        merged_registry.entries.append(a)
    engine = DiffEngine(merged_session, merged_registry)
    diff = engine.compare(old_snap, new_snap)
    return engine, diff


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDiffUnchanged(unittest.TestCase):

    def test_identical_snapshots_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            reg, snap = _build_snapshot(d, {"a.py": "x = 1\n"}, "r1")
            engine = DiffEngine(reg.session, reg)
            diff = engine.compare(snap, snap)
            self.assertEqual(diff["change_type"], "unchanged")
            self.assertEqual(diff["files_added"], [])
            self.assertEqual(diff["files_removed"], [])
            self.assertEqual(diff["files_modified"], [])
            self.assertEqual(diff["files_renamed"], [])

    def test_empty_to_empty_unchanged(self):
        with tempfile.TemporaryDirectory() as old_d, tempfile.TemporaryDirectory() as new_d:
            old_reg, old_snap = _build_snapshot(old_d, {}, "r-empty-old")
            new_reg, new_snap = _build_snapshot(new_d, {}, "r-empty-new")
            _, diff = _merged(old_reg, old_snap, new_reg, new_snap, new_d)
            self.assertEqual(diff["change_type"], "unchanged")
            self.assertEqual(diff["similarity"], 1.0)

    def test_similarity_is_1_when_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            reg, snap = _build_snapshot(d, {"f.py": "pass\n"}, "r-sim1")
            engine = DiffEngine(reg.session, reg)
            diff = engine.compare(snap, snap)
            self.assertEqual(diff["similarity"], 1.0)


class TestDiffAdded(unittest.TestCase):

    def test_file_added(self):
        with tempfile.TemporaryDirectory() as old_d, tempfile.TemporaryDirectory() as new_d:
            old_reg, old_snap = _build_snapshot(old_d, {"a.py": "x = 1\n"}, "r-add-old")
            new_reg, new_snap = _build_snapshot(new_d, {"a.py": "x = 1\n", "b.py": "y = 2\n"}, "r-add-new")
            _, diff = _merged(old_reg, old_snap, new_reg, new_snap, new_d)
            self.assertEqual(diff["change_type"], "modified")
            self.assertTrue(any(p.endswith("b.py") for p in diff["files_added"]))
            self.assertEqual(diff["files_modified"], [])
            self.assertEqual(diff["files_removed"], [])

    def test_multiple_files_added(self):
        with tempfile.TemporaryDirectory() as old_d, tempfile.TemporaryDirectory() as new_d:
            old_reg, old_snap = _build_snapshot(old_d, {}, "r-madd-old")
            new_reg, new_snap = _build_snapshot(new_d, {"x.py": "1\n", "y.py": "2\n", "z.py": "3\n"}, "r-madd-new")
            _, diff = _merged(old_reg, old_snap, new_reg, new_snap, new_d)
            self.assertEqual(len(diff["files_added"]), 3)


class TestDiffRemoved(unittest.TestCase):

    def test_file_removed(self):
        with tempfile.TemporaryDirectory() as old_d, tempfile.TemporaryDirectory() as new_d:
            old_reg, old_snap = _build_snapshot(old_d, {"a.py": "x\n", "b.py": "y\n"}, "r-rm-old")
            new_reg, new_snap = _build_snapshot(new_d, {"a.py": "x\n"}, "r-rm-new")
            _, diff = _merged(old_reg, old_snap, new_reg, new_snap, new_d)
            self.assertTrue(any(p.endswith("b.py") for p in diff["files_removed"]))
            self.assertEqual(diff["files_added"], [])


class TestDiffModified(unittest.TestCase):

    def test_file_modified(self):
        with tempfile.TemporaryDirectory() as old_d, tempfile.TemporaryDirectory() as new_d:
            old_reg, old_snap = _build_snapshot(old_d, {"a.py": "x = 1\n"}, "r-mod-old")
            new_reg, new_snap = _build_snapshot(new_d, {"a.py": "x = 99\n"}, "r-mod-new")
            _, diff = _merged(old_reg, old_snap, new_reg, new_snap, new_d)
            self.assertTrue(any(p.endswith("a.py") for p in diff["files_modified"]))
            self.assertEqual(diff["files_added"], [])
            self.assertEqual(diff["files_removed"], [])

    def test_modified_file_has_line_counts(self):
        with tempfile.TemporaryDirectory() as old_d, tempfile.TemporaryDirectory() as new_d:
            old_reg, old_snap = _build_snapshot(old_d, {"f.py": "a = 1\n"}, "r-lc-old")
            new_reg, new_snap = _build_snapshot(new_d, {"f.py": "a = 1\nb = 2\n"}, "r-lc-new")
            _, diff = _merged(old_reg, old_snap, new_reg, new_snap, new_d)
            self.assertGreater(diff["lines_added"], 0)

    def test_modified_file_similarity_below_1(self):
        with tempfile.TemporaryDirectory() as old_d, tempfile.TemporaryDirectory() as new_d:
            old_content = "\n".join(f"line_{i}" for i in range(20)) + "\n"
            new_content = "\n".join(f"changed_{i}" for i in range(20)) + "\n"
            old_reg, old_snap = _build_snapshot(old_d, {"f.py": old_content}, "r-sim-old")
            new_reg, new_snap = _build_snapshot(new_d, {"f.py": new_content}, "r-sim-new")
            _, diff = _merged(old_reg, old_snap, new_reg, new_snap, new_d)
            self.assertLess(diff["similarity"], 1.0)

    def test_file_diffs_dict_populated(self):
        with tempfile.TemporaryDirectory() as old_d, tempfile.TemporaryDirectory() as new_d:
            old_reg, old_snap = _build_snapshot(old_d, {"m.py": "a\n"}, "r-fd-old")
            new_reg, new_snap = _build_snapshot(new_d, {"m.py": "b\n"}, "r-fd-new")
            _, diff = _merged(old_reg, old_snap, new_reg, new_snap, new_d)
            self.assertIn("file_diffs", diff)
            key = next(iter(diff["file_diffs"]))
            entry = diff["file_diffs"][key]
            self.assertIn("lines_added", entry)
            self.assertIn("lines_removed", entry)
            self.assertIn("similarity", entry)


class TestDiffRenamed(unittest.TestCase):

    def test_rename_detected(self):
        with tempfile.TemporaryDirectory() as old_d, tempfile.TemporaryDirectory() as new_d:
            content = "def helper():\n    return 1\n"
            old_reg, old_snap = _build_snapshot(old_d, {"utils.py": content}, "r-ren-old")
            new_reg, new_snap = _build_snapshot(new_d, {"helpers.py": content}, "r-ren-new")
            _, diff = _merged(old_reg, old_snap, new_reg, new_snap, new_d)
            renames = diff["files_renamed"]
            self.assertTrue(
                any(r[0].endswith("utils.py") and r[1].endswith("helpers.py") for r in renames),
                f"Expected rename utils→helpers, got: {renames}",
            )
            # renamed file must NOT appear in added or removed
            self.assertFalse(any(p.endswith("helpers.py") for p in diff["files_added"]))
            self.assertFalse(any(p.endswith("utils.py") for p in diff["files_removed"]))

    def test_rename_not_triggered_by_none_sha(self):
        """Two files with sha256=None must NOT be falsely detected as renamed."""
        session = AnalysisSession(
            run_id="r-none-sha", target_project="x", target_version="1.0",
            operator="t", schema_version="1.0",
        )
        registry = ArtifactRegistry(session)
        old_man = ManifestEngine(session, registry).build([
            {"file_id": "f1", "relative_path": "old.py", "sha256": None}
        ])
        old_snap = SnapshotEngine(session, registry).create(old_man)
        new_man = ManifestEngine(session, registry).build([
            {"file_id": "f2", "relative_path": "new.py", "sha256": None}
        ])
        new_snap = SnapshotEngine(session, registry).create(new_man)
        engine = DiffEngine(session, registry)
        diff = engine.compare(old_snap, new_snap)
        # old.py removed, new.py added — they share sha256=None but must NOT be renamed
        self.assertEqual(diff["files_renamed"], [],
                         f"False rename with None sha: {diff['files_renamed']}")
        self.assertTrue(any(p.endswith("new.py") for p in diff["files_added"]))
        self.assertTrue(any(p.endswith("old.py") for p in diff["files_removed"]))

    def test_two_identical_new_files_no_wrong_rename(self):
        """Two new files with the same content — only one can be a rename target."""
        with tempfile.TemporaryDirectory() as old_d, tempfile.TemporaryDirectory() as new_d:
            content = "shared content\n"
            old_reg, old_snap = _build_snapshot(old_d, {"orig.py": content}, "r-dup-old")
            new_reg, new_snap = _build_snapshot(
                new_d, {"copy1.py": content, "copy2.py": content}, "r-dup-new"
            )
            _, diff = _merged(old_reg, old_snap, new_reg, new_snap, new_d)
            # orig.py was removed; there are two identical new files
            # At most ONE rename should be detected; there should be no duplicate destinations
            renames = diff["files_renamed"]
            destinations = [r[1] for r in renames]
            self.assertEqual(len(destinations), len(set(destinations)),
                             f"Duplicate rename destinations: {renames}")

    def test_two_removed_same_sha_no_duplicate_destination(self):
        """Two old files with the same sha and one new file → max one rename, one remains removed."""
        session = AnalysisSession(
            run_id="r-2rm", target_project="p", target_version="1.0",
            operator="t", schema_version="1.0",
        )
        registry = ArtifactRegistry(session)
        old_man = ManifestEngine(session, registry).build([
            {"file_id": "fa", "relative_path": "a.py", "sha256": "deadbeef"},
            {"file_id": "fb", "relative_path": "b.py", "sha256": "deadbeef"},
        ])
        old_snap = SnapshotEngine(session, registry).create(old_man)
        new_man = ManifestEngine(session, registry).build([
            {"file_id": "fc", "relative_path": "c.py", "sha256": "deadbeef"},
        ])
        new_snap = SnapshotEngine(session, registry).create(new_man)
        engine = DiffEngine(session, registry)
        diff = engine.compare(old_snap, new_snap)
        renames = diff["files_renamed"]
        destinations = [r[1] for r in renames]
        # Must have no duplicate destinations
        self.assertEqual(len(destinations), len(set(destinations)),
                         f"Duplicate rename destinations: {renames}")
        # Total: 2 removed + 1 new ≡ 1 rename + 1 still-removed (or 0 renames + 1 still-removed)
        total_removed_and_renamed = len(diff["files_removed"]) + len(renames)
        self.assertEqual(total_removed_and_renamed, 2,
                         "Lost track of a removed file during rename detection")


class TestDiffArtifact(unittest.TestCase):

    def test_artifact_type_is_diff(self):
        with tempfile.TemporaryDirectory() as d:
            reg, snap = _build_snapshot(d, {"a.py": "x\n"}, "r-art")
            engine = DiffEngine(reg.session, reg)
            diff = engine.compare(snap, snap)
            self.assertEqual(diff["artifact_type"], "diff")

    def test_required_keys_present(self):
        required = {
            "artifact_id", "artifact_type", "change_type",
            "files_added", "files_removed", "files_modified", "files_renamed",
            "lines_added", "lines_removed", "similarity", "file_diffs",
            "old_snapshot", "new_snapshot",
        }
        with tempfile.TemporaryDirectory() as d:
            reg, snap = _build_snapshot(d, {"a.py": "x\n"}, "r-keys")
            engine = DiffEngine(reg.session, reg)
            diff = engine.compare(snap, snap)
            for key in required:
                self.assertIn(key, diff, f"Missing key: {key}")

    def test_missing_artifact_raises_key_error(self):
        session = AnalysisSession(
            run_id="r-miss", target_project="p", target_version="1.0",
            operator="t", schema_version="1.0",
        )
        registry = ArtifactRegistry(session)
        engine = DiffEngine(session, registry)
        fake_snap = {"artifact_id": "snap-fake", "manifest_id": "nonexistent-id"}
        with self.assertRaises(KeyError):
            engine.compare(fake_snap, fake_snap)


class TestDiffReadFileLinesRobustness(unittest.TestCase):

    def test_missing_file_on_disk_does_not_crash(self):
        """If a modified file is missing from disk, compare() must still complete."""
        session = AnalysisSession(
            run_id="r-miss-disk", target_project="/nonexistent/root",
            target_version="1.0", operator="t", schema_version="1.0",
        )
        registry = ArtifactRegistry(session)
        old_man = ManifestEngine(session, registry).build([
            {"file_id": "fx", "relative_path": "gone.py", "sha256": "aaa"}
        ])
        old_snap = SnapshotEngine(session, registry).create(old_man)
        new_man = ManifestEngine(session, registry).build([
            {"file_id": "fy", "relative_path": "gone.py", "sha256": "bbb"}
        ])
        new_snap = SnapshotEngine(session, registry).create(new_man)
        engine = DiffEngine(session, registry)
        # Should not raise; missing file treated as empty
        diff = engine.compare(old_snap, new_snap)
        self.assertIsNotNone(diff)
        self.assertIn("gone.py", diff["files_modified"])


class TestDiffLineCounting(unittest.TestCase):

    def test_no_lines_added_when_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            reg, snap = _build_snapshot(d, {"f.py": "a = 1\n"}, "r-lc0")
            engine = DiffEngine(reg.session, reg)
            diff = engine.compare(snap, snap)
            self.assertEqual(diff["lines_added"], 0)
            self.assertEqual(diff["lines_removed"], 0)

    def test_lines_added_and_removed_symmetry(self):
        with tempfile.TemporaryDirectory() as old_d, tempfile.TemporaryDirectory() as new_d:
            old_reg, old_snap = _build_snapshot(old_d, {"f.py": "old_line\n"}, "r-sym-old")
            new_reg, new_snap = _build_snapshot(new_d, {"f.py": "new_line\n"}, "r-sym-new")
            _, diff = _merged(old_reg, old_snap, new_reg, new_snap, new_d)
            self.assertEqual(diff["lines_added"], 1)
            self.assertEqual(diff["lines_removed"], 1)

    def test_lines_added_for_added_file(self):
        """A newly-added file's lines should be counted in lines_added."""
        with tempfile.TemporaryDirectory() as old_d, tempfile.TemporaryDirectory() as new_d:
            old_reg, old_snap = _build_snapshot(old_d, {}, "r-af-old")
            new_reg, new_snap = _build_snapshot(
                new_d, {"brand_new.py": "line1\nline2\nline3\n"}, "r-af-new"
            )
            _, diff = _merged(old_reg, old_snap, new_reg, new_snap, new_d)
            self.assertGreater(diff["lines_added"], 0,
                               "lines_added should count lines in newly added files")


if __name__ == "__main__":
    unittest.main()
