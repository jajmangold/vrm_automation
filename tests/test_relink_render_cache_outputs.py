import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.relink_render_cache_outputs import relink_render_cache_outputs


class RelinkRenderCacheOutputsTests(unittest.TestCase):
    def test_relink_render_cache_outputs_dry_run_reports_matches(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            cache = root / "outputs/render_cache/cache-key.glb"
            output = root / "outputs/batch/person.glb"
            cache.parent.mkdir(parents=True)
            output.parent.mkdir(parents=True)
            cache.write_bytes(b"same glb")
            output.write_bytes(b"same glb")

            report = relink_render_cache_outputs(root=root, apply=False)

            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["candidate_count"], 1)
            self.assertEqual(report["dry_run_count"], 1)
            self.assertEqual(report["linked_count"], 0)
            self.assertFalse(cache.samefile(output))

    def test_relink_render_cache_outputs_applies_hardlink_for_identical_output(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            cache = root / "outputs/render_cache/cache-key.glb"
            output = root / "outputs/batch/person.glb"
            cache.parent.mkdir(parents=True)
            output.parent.mkdir(parents=True)
            cache.write_bytes(b"same glb")
            output.write_bytes(b"same glb")

            report = relink_render_cache_outputs(root=root, apply=True)

            self.assertEqual(report["linked_count"], 1)
            self.assertEqual(report["skipped_count"], 0)
            self.assertTrue(cache.samefile(output))

    def test_relink_render_cache_outputs_skips_non_matching_hashes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            cache = root / "outputs/render_cache/cache-key.glb"
            output = root / "outputs/batch/person.glb"
            cache.parent.mkdir(parents=True)
            output.parent.mkdir(parents=True)
            cache.write_bytes(b"source")
            output.write_bytes(b"target")

            report = relink_render_cache_outputs(root=root, apply=True)

            self.assertEqual(report["linked_count"], 0)
            self.assertEqual(report["skipped_count"], 1)
            self.assertEqual(report["skipped"][0]["reason"], "no-matching-cache")
            self.assertFalse(cache.samefile(output))


if __name__ == "__main__":
    unittest.main()
