import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.relink_godot_game_assets import relink_game_assets


class RelinkGodotGameAssetsTests(unittest.TestCase):
    def test_relink_game_assets_dry_run_reports_identical_copies(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            optimized = root / "outputs/batch_optimized/demo.glb"
            exported = root / "godot_viewer/game_assets/glb/demo.glb"
            optimized.parent.mkdir(parents=True)
            exported.parent.mkdir(parents=True)
            optimized.write_bytes(b"same")
            exported.write_bytes(b"same")

            report = relink_game_assets(root=root, apply=False)

            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["candidate_count"], 1)
            self.assertEqual(report["linked_count"], 0)
            self.assertEqual(report["dry_run_count"], 1)
            self.assertFalse(optimized.samefile(exported))

    def test_relink_game_assets_applies_hardlink_for_identical_copies(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            optimized = root / "outputs/batch_optimized/demo.glb"
            exported = root / "godot_viewer/game_assets/glb/demo.glb"
            optimized.parent.mkdir(parents=True)
            exported.parent.mkdir(parents=True)
            optimized.write_bytes(b"same")
            exported.write_bytes(b"same")

            report = relink_game_assets(root=root, apply=True)

            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["linked_count"], 1)
            self.assertEqual(report["skipped_count"], 0)
            self.assertTrue(optimized.samefile(exported))

    def test_relink_game_assets_skips_different_bytes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            optimized = root / "outputs/batch_optimized/demo.glb"
            exported = root / "godot_viewer/game_assets/glb/demo.glb"
            optimized.parent.mkdir(parents=True)
            exported.parent.mkdir(parents=True)
            optimized.write_bytes(b"source")
            exported.write_bytes(b"target")

            report = relink_game_assets(root=root, apply=True)

            self.assertEqual(report["linked_count"], 0)
            self.assertEqual(report["skipped_count"], 1)
            self.assertEqual(report["skipped"][0]["reason"], "sha256-mismatch")
            self.assertFalse(optimized.samefile(exported))


if __name__ == "__main__":
    unittest.main()
