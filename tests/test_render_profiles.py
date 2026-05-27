import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.render_profiles import clear_pose_render_files, render_defaults


class RenderProfilesTests(unittest.TestCase):
    def test_fast_lipsync_profile_keeps_high_signal_portrait_frames(self):
        defaults = render_defaults("fast_lipsync", has_lipsync=True)

        self.assertEqual(defaults["render_angles"], "portrait")
        self.assertEqual(defaults["render_pose_frames"], "3,9,16")
        self.assertEqual(defaults["render_width"], "640")
        self.assertEqual(defaults["render_height"], "960")

    def test_rough_lipsync_profile_uses_one_low_res_portrait_frame(self):
        defaults = render_defaults("rough_lipsync", has_lipsync=True)

        self.assertEqual(defaults["render_angles"], "portrait")
        self.assertEqual(defaults["render_pose_frames"], "9")
        self.assertEqual(defaults["render_width"], "512")
        self.assertEqual(defaults["render_height"], "768")

    def test_thumbnail_lipsync_profile_uses_small_single_review_frame(self):
        defaults = render_defaults("thumbnail_lipsync", has_lipsync=True)

        self.assertEqual(defaults["render_angles"], "portrait")
        self.assertEqual(defaults["render_pose_frames"], "1")
        self.assertEqual(defaults["render_compact_arms"], "1")
        self.assertEqual(defaults["render_portrait_lens"], "135")
        self.assertEqual(defaults["render_review_pose_version"], "3")
        self.assertEqual(defaults["render_width"], "384")
        self.assertEqual(defaults["render_height"], "576")

    def test_control_lipsync_profile_skips_blender_pngs_for_fast_game_assets(self):
        defaults = render_defaults("control_lipsync", has_lipsync=True)

        self.assertEqual(defaults["render_angles"], "portrait")
        self.assertEqual(defaults["render_pose_frames"], "9")
        self.assertEqual(defaults["render_pose_stills"], "0")
        self.assertEqual(defaults["render_width"], "384")
        self.assertEqual(defaults["render_height"], "576")

    def test_auto_lipsync_profile_preserves_full_review_coverage(self):
        defaults = render_defaults("auto", has_lipsync=True)

        self.assertEqual(defaults["render_angles"], "front,portrait")
        self.assertEqual(defaults["render_pose_frames"], "1,3,6,9,12,16,24")

    def test_auto_non_lipsync_profile_uses_standard_fast_frames(self):
        defaults = render_defaults("auto", has_lipsync=False)

        self.assertEqual(defaults["render_angles"], "front,portrait")
        self.assertEqual(defaults["render_pose_frames"], "1,9,24")

    def test_clear_pose_render_files_removes_only_pose_pngs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            stale = tmp / "pose_portrait_0001.png"
            keep = tmp / "notes.txt"
            nested = tmp / "nested"
            nested.mkdir()
            nested_pose = nested / "pose_0001.png"
            stale.write_text("old", encoding="utf-8")
            keep.write_text("keep", encoding="utf-8")
            nested_pose.write_text("nested", encoding="utf-8")

            removed = clear_pose_render_files(tmp)

            self.assertEqual(removed, [stale])
            self.assertFalse(stale.exists())
            self.assertTrue(keep.exists())
            self.assertTrue(nested_pose.exists())


if __name__ == "__main__":
    unittest.main()
