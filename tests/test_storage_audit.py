import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.storage_audit import audit_storage, summarize_glbs


class StorageAuditTests(unittest.TestCase):
    def test_summarize_glbs_reports_actual_and_apparent_bytes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            one = root / "one.glb"
            two = root / "two.glb"
            one.write_bytes(b"1234")
            two.hardlink_to(one)

            summary = summarize_glbs(root)

            self.assertEqual(summary["file_count"], 2)
            self.assertEqual(summary["apparent_bytes"], 8)
            self.assertEqual(summary["unique_inode_count"], 1)
            self.assertGreater(summary["hardlink_saved_bytes"], 0)

    def test_audit_storage_includes_factory_directories_and_cleanup_reports(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "outputs/batch").mkdir(parents=True)
            (root / "outputs/render_cache").mkdir(parents=True)
            (root / "outputs/batch_optimized").mkdir(parents=True)
            (root / "godot_viewer/game_assets/glb").mkdir(parents=True)
            (root / "outputs/batch/person.glb").write_bytes(b"raw")
            (root / "outputs/render_cache/cache.glb").write_bytes(b"raw")
            (root / "results").mkdir()
            (root / "results/relink_render_cache_outputs_latest.json").write_text(
                '{"linked_count": 2, "linked_bytes": 20}',
                encoding="utf-8",
            )

            report = audit_storage(root=root)

            self.assertEqual(report["status"], "ok")
            self.assertIn("outputs/batch", report["directories"])
            self.assertIn("outputs/render_cache", report["directories"])
            self.assertEqual(report["cleanup_reports"]["render_cache_outputs"]["linked_count"], 2)
            self.assertGreaterEqual(report["totals"]["glb_file_count"], 2)

    def test_audit_storage_totals_deduplicate_cross_directory_hardlinks(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            raw = root / "outputs/batch/person.glb"
            cache = root / "outputs/render_cache/cache.glb"
            raw.parent.mkdir(parents=True)
            cache.parent.mkdir(parents=True)
            raw.write_bytes(b"shared")
            cache.hardlink_to(raw)

            report = audit_storage(root=root)

            self.assertEqual(report["totals"]["glb_file_count"], 2)
            self.assertEqual(report["totals"]["unique_inode_count"], 1)
            self.assertEqual(report["totals"]["apparent_bytes"], 12)
            self.assertEqual(report["totals"]["actual_bytes"], 6)
            self.assertEqual(report["totals"]["hardlink_saved_bytes"], 6)


if __name__ == "__main__":
    unittest.main()
