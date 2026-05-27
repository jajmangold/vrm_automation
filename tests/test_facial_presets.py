import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.face_profile import build_face_profile
from scripts.facial_presets import facial_preset_for_animation, plan_facial_animation


class FacialPresetTests(unittest.TestCase):
    def test_talk_idle_defaults_to_talking_soft(self):
        self.assertEqual(facial_preset_for_animation("talk_idle"), "talking_soft")
        self.assertEqual(facial_preset_for_animation("shy_bounce"), "shy")
        self.assertEqual(facial_preset_for_animation("confident_point"), "happy")
        self.assertEqual(facial_preset_for_animation("present_explain"), "talking_soft")
        self.assertEqual(facial_preset_for_animation("celebrate"), "happy")
        self.assertEqual(facial_preset_for_animation("thinking_idle"), "neutral")

    def test_happy_preset_keys_happy_and_blink_with_smile_alias(self):
        profile = build_face_profile(
            "sample",
            {
                "Face": [
                    "Face.M_F00_000_00_Fcl_ALL_Joy",
                    "Face.M_F00_000_00_Fcl_EYE_Close",
                    "Face.M_F00_000_00_Fcl_MTH_A",
                    "Face.M_F00_000_00_Fcl_MTH_I",
                    "Face.M_F00_000_00_Fcl_MTH_U",
                    "Face.M_F00_000_00_Fcl_MTH_E",
                    "Face.M_F00_000_00_Fcl_MTH_O",
                ]
            },
        )

        plan = plan_facial_animation(profile, "happy", frame_end=72)

        self.assertEqual(plan["preset"], "happy")
        self.assertIn("happy", plan["keyed"])
        self.assertIn("smile", plan["keyed"])
        self.assertIn("blink", plan["keyed"])
        self.assertEqual(plan["missing"], [])
        self.assertGreaterEqual(plan["keyframe_count"], 8)

    def test_talking_preset_uses_vrm_viseme_names(self):
        profile = build_face_profile(
            "sample",
            {
                "Face": [
                    "Face.M_F00_000_00_Fcl_ALL_Joy",
                    "Face.M_F00_000_00_Fcl_EYE_Close",
                    "Face.M_F00_000_00_Fcl_MTH_A",
                    "Face.M_F00_000_00_Fcl_MTH_I",
                    "Face.M_F00_000_00_Fcl_MTH_U",
                    "Face.M_F00_000_00_Fcl_MTH_E",
                    "Face.M_F00_000_00_Fcl_MTH_O",
                ]
            },
        )

        plan = plan_facial_animation(profile, "talking_wide", frame_end=72)

        self.assertEqual(plan["preset"], "talking_wide")
        self.assertTrue({"aa", "ih", "ou", "ee", "oh"}.issubset(set(plan["keyed_visemes"])))
        self.assertIn("happy", plan["keyed"])
        self.assertEqual(plan["missing"], [])

    def test_missing_shapes_are_reported(self):
        profile = build_face_profile("sample", {"Face": ["Face.M_F00_000_00_Fcl_ALL_Joy"]})

        plan = plan_facial_animation(profile, "surprised", frame_end=72)

        self.assertIn("surprised", plan["missing"])
        self.assertIn("oh", plan["missing_visemes"])


if __name__ == "__main__":
    unittest.main()
