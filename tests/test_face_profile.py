import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.face_profile import build_face_profile, viseme_payload


class FaceProfileTests(unittest.TestCase):
    def test_maps_vroid_shape_keys_to_canonical_visemes_and_expressions(self):
        shape_keys = {
            "Face": [
                "Basis",
                "Face.M_F00_000_00_Fcl_ALL_Joy",
                "Face.M_F00_000_00_Fcl_ALL_Angry",
                "Face.M_F00_000_00_Fcl_EYE_Close",
                "Face.M_F00_000_00_Fcl_EYE_Close_L",
                "Face.M_F00_000_00_Fcl_EYE_Close_R",
                "Face.M_F00_000_00_Fcl_MTH_A",
                "Face.M_F00_000_00_Fcl_MTH_I",
                "Face.M_F00_000_00_Fcl_MTH_U",
                "Face.M_F00_000_00_Fcl_MTH_E",
                "Face.M_F00_000_00_Fcl_MTH_O",
            ]
        }

        profile = build_face_profile("sample", shape_keys)

        self.assertEqual(profile["quality"]["viseme_count"], 5)
        self.assertGreaterEqual(profile["quality"]["expression_count"], 3)
        self.assertEqual(profile["visemes"]["aa"]["shape"], "Face.M_F00_000_00_Fcl_MTH_A")
        self.assertEqual(profile["expressions"]["blink"]["shape"], "Face.M_F00_000_00_Fcl_EYE_Close")
        self.assertEqual(profile["quality"]["grade"], "A")

    def test_viseme_payload_resets_other_mouth_shapes(self):
        profile = build_face_profile(
            "sample",
            {"Face": ["Face.M_F00_000_00_Fcl_MTH_A", "Face.M_F00_000_00_Fcl_MTH_I"]},
        )

        payload = viseme_payload(profile, "aa", 0.75)

        self.assertEqual(payload["Face.M_F00_000_00_Fcl_MTH_A"], 0.75)
        self.assertEqual(payload["Face.M_F00_000_00_Fcl_MTH_I"], 0.0)


if __name__ == "__main__":
    unittest.main()
