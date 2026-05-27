import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.animation_presets import animation_preset, preset_value


class AnimationPresetTests(unittest.TestCase):
    def test_default_preset_is_wave(self):
        preset = animation_preset(None)

        self.assertEqual(preset["name"], "wave")
        self.assertEqual(preset["frames"], [1, 24, 48, 72])

    def test_accepts_hyphenated_preset_names(self):
        preset = animation_preset("cheerful-wave")

        self.assertEqual(preset["name"], "cheerful_wave")
        self.assertGreater(max(preset["right_arm"]), 45)

    def test_unknown_preset_falls_back_to_wave(self):
        preset = animation_preset("does-not-exist")

        self.assertEqual(preset["name"], "wave")

    def test_preset_value_clamps_to_last_value(self):
        preset = animation_preset("shy_bounce")

        self.assertEqual(preset_value(preset, "right_arm", 999), preset["right_arm"][-1])
        self.assertEqual(preset_value(preset, "missing", 0, 12), 12)

    def test_control_friendly_presets_exist(self):
        for name in ("confident_point", "talk_idle", "look_around"):
            preset = animation_preset(name)
            self.assertEqual(preset["name"], name)
            self.assertEqual(preset["frames"][-1], 72)
            self.assertEqual(len(preset["frames"]), len(preset["right_arm"]))

    def test_standard_library_presets_have_metadata_and_review_frames(self):
        for name in ("thinking_idle", "listening_nod", "present_explain", "celebrate", "turntable_review"):
            preset = animation_preset(name)

            self.assertEqual(preset["name"], name)
            self.assertEqual(preset["frames"][-1], 72)
            self.assertTrue(preset["tags"])
            self.assertTrue(preset["review_frames"])
            self.assertEqual(len(preset["frames"]), len(preset["right_arm"]))

    def test_optional_pose_tracks_can_be_read_by_index(self):
        preset = animation_preset("present_explain")

        self.assertGreater(preset_value(preset, "right_arm_z", 1), 0)
        self.assertLess(preset_value(preset, "left_arm_z", 1), 0)


if __name__ == "__main__":
    unittest.main()
