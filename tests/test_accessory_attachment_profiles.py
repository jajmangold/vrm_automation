import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.accessory_attachment_profiles import load_attachment_profiles
from scripts.asset_classifier import VALID_CATEGORIES


class AccessoryAttachmentProfileTests(unittest.TestCase):
    def test_profiles_load_and_validate(self):
        data = load_attachment_profiles()

        self.assertEqual(data["schema_version"], 1)
        self.assertGreaterEqual(len(data["profiles"]), 4)

    def test_profile_categories_are_classifiable(self):
        data = load_attachment_profiles()
        categories = {profile["category"] for profile in data["profiles"]}

        self.assertTrue(categories <= VALID_CATEGORIES)
        self.assertIn("hand_held", categories)

    def test_profiles_define_anchor_binding_motion_and_validation(self):
        data = load_attachment_profiles()

        for profile in data["profiles"]:
            with self.subTest(profile=profile["id"]):
                self.assertIn("primary", profile["anchors"])
                self.assertIn("asset", profile["anchors"])
                self.assertIn("optimizer", profile["placement"])
                self.assertIn("target_bone_role", profile["binding"])
                self.assertIn("mode", profile["motion"])
                self.assertIn("required_views", profile["validation"])
                self.assertGreater(profile["validation"]["min_mask_iou"], 0.0)

    def test_briefcase_profile_is_hand_socket_with_swing(self):
        data = load_attachment_profiles()
        profiles = {profile["id"]: profile for profile in data["profiles"]}
        briefcase = profiles["hand_held.briefcase"]

        self.assertEqual(briefcase["binding"]["mode"], "rigid_socket")
        self.assertEqual(briefcase["binding"]["target_bone_role"], "right_hand")
        self.assertEqual(briefcase["motion"]["mode"], "socket_swing")
        self.assertIn("handle-center", briefcase["anchors"]["asset"])


if __name__ == "__main__":
    unittest.main()
