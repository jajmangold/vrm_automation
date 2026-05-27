import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.review_quality import assess_review_quality


class ReviewQualityTests(unittest.TestCase):
    def test_known_weak_hat_asset_adds_actionable_flags(self):
        result = assess_review_quality(
            {
                "id": "gen-051-female-fedora-google-look-around",
                "metadata": {"tags": ["fedora-google", "head-face"]},
                "environment": {"OUTFIT_CATEGORY": "head_face"},
            },
            {"external_outfit": {"classification": {"category": "head_face"}}},
        )

        self.assertIn("known-weak-asset", result["qa_flags"])
        self.assertIn("hat-low", result["qa_flags"])
        self.assertIn("asset:weak", result["review_tags"])
        self.assertIn("issue:hat-low", result["review_tags"])
        self.assertTrue(any("fedora" in note.lower() for note in result["review_notes"]))

    def test_monocle_requests_open_eye_review_frame(self):
        result = assess_review_quality(
            {
                "id": "gen-054-female-monocle-google-look-around",
                "metadata": {"tags": ["monocle-google", "head-face"]},
                "environment": {"OUTFIT_CATEGORY": "head_face"},
            },
            {
                "external_outfit": {"classification": {"category": "head_face"}},
                "pose_renders": [
                    "/workspace/outputs/person_pose_portrait_0024.png",
                    "/workspace/outputs/person_pose_portrait_0072.png",
                ],
            },
        )

        self.assertIn("needs-open-eye-review", result["qa_flags"])
        self.assertIn("issue:open-eye-review", result["review_tags"])
        self.assertIn("frame:portrait-0072", result["review_tags"])
        self.assertEqual(result["preferred_review_frame"], "pose_portrait_0072.png")

    def test_lipsync_prefers_active_mouth_review_frame(self):
        result = assess_review_quality(
            {
                "id": "lip-phoneme-001-pixel-talk",
                "metadata": {"tags": ["lip-sync", "head-face"]},
                "environment": {"OUTFIT_CATEGORY": "head_face"},
            },
            {
                "external_outfit": {"classification": {"category": "head_face"}},
                "lipsync_animation": {"enabled": True},
                "pose_renders": [
                    "/workspace/outputs/person_pose_portrait_0001.png",
                    "/workspace/outputs/person_pose_portrait_0003.png",
                    "/workspace/outputs/person_pose_portrait_0009.png",
                    "/workspace/outputs/person_pose_portrait_0024.png",
                ],
            },
        )

        self.assertEqual(result["preferred_review_frame"], "pose_portrait_0009.png")
        self.assertIn("frame:portrait-0009", result["review_tags"])

    def test_large_low_glasses_asset_adds_actionable_flags(self):
        result = assess_review_quality(
            {
                "id": "gen-023-male-glasses-jeremy-talk-idle",
                "metadata": {"tags": ["glasses-jeremy", "head-face"]},
                "environment": {"OUTFIT_CATEGORY": "head_face"},
            },
            {"external_outfit": {"classification": {"category": "head_face"}}},
        )

        self.assertIn("glasses-large-low", result["qa_flags"])
        self.assertIn("issue:glasses-large-low", result["review_tags"])
        self.assertTrue(any("glasses" in note.lower() for note in result["review_notes"]))

    def test_wizard_hat_candidate_stays_review_when_tiny_or_hidden(self):
        result = assess_review_quality(
            {
                "id": "anchor-candidate-next-001-005",
                "metadata": {"tags": ["wizard-hat-google", "head-face"]},
                "environment": {"OUTFIT_CATEGORY": "head_face"},
            },
            {"external_outfit": {"classification": {"category": "head_face"}}},
        )

        self.assertIn("hat-tiny-hidden", result["qa_flags"])
        self.assertIn("issue:hat-tiny-hidden", result["review_tags"])
        self.assertTrue(any("wizard" in note.lower() for note in result["review_notes"]))

    def test_necktie_on_head_candidate_requires_fix(self):
        result = assess_review_quality(
            {
                "id": "anchor-review-category-007",
                "metadata": {"tags": ["necktie-jeremy", "neck-chest"]},
                "environment": {"OUTFIT_CATEGORY": "neck_chest"},
            },
            {
                "external_outfit": {
                    "classification": {"category": "neck_chest"},
                    "fit_check": {"metrics": {"vertical_center_ratio": 0.9445}},
                }
            },
        )

        self.assertIn("necktie-head-placement", result["qa_flags"])
        self.assertIn("issue:necktie-head-placement", result["review_tags"])
        self.assertTrue(any("forehead" in note.lower() for note in result["review_notes"]))

    def test_necktie_at_collar_does_not_trigger_head_placement_flag(self):
        result = assess_review_quality(
            {
                "id": "necktie-low-001",
                "metadata": {"tags": ["necktie-jeremy", "neck-chest"]},
                "environment": {"OUTFIT_CATEGORY": "neck_chest"},
            },
            {
                "external_outfit": {
                    "classification": {"category": "neck_chest"},
                    "fit_check": {"metrics": {"vertical_center_ratio": 0.74}},
                }
            },
        )

        self.assertNotIn("necktie-head-placement", result["qa_flags"])
        self.assertNotIn("issue:necktie-head-placement", result["review_tags"])

    def test_face_occluding_mask_requires_manual_review(self):
        result = assess_review_quality(
            {
                "id": "anchor-candidate-sam-001-001",
                "metadata": {"tags": ["anon-mask-scott-marshall", "head-face"]},
                "environment": {"OUTFIT_CATEGORY": "head_face"},
            },
            {"external_outfit": {"classification": {"category": "head_face"}}},
        )

        self.assertIn("face-occluding-mask", result["qa_flags"])
        self.assertIn("issue:face-occlusion", result["review_tags"])
        self.assertTrue(any("identity" in note.lower() for note in result["review_notes"]))

    def test_low_neck_loop_candidate_requires_review(self):
        result = assess_review_quality(
            {
                "id": "anchor-candidate-sam-001-003",
                "metadata": {"tags": ["necklace-quaternius", "anchor:neck-chest-neck-loop"]},
                "environment": {"OUTFIT_CATEGORY": "neck_chest"},
            },
            {
                "external_outfit": {
                    "classification": {"category": "neck_chest"},
                    "fit_check": {
                        "metrics": {
                            "vertical_center_ratio": 0.777,
                            "height_ratio": 0.1538,
                        }
                    },
                }
            },
        )

        self.assertIn("neck-loop-low", result["qa_flags"])
        self.assertIn("issue:neck-loop-low", result["review_tags"])
        self.assertTrue(any("pendant" in note.lower() for note in result["review_notes"]))

    def test_high_neck_loop_candidate_does_not_trigger_low_flag(self):
        result = assess_review_quality(
            {
                "id": "necklace-high-001",
                "metadata": {"tags": ["necklace-quaternius", "anchor:neck-chest-neck-loop"]},
                "environment": {"OUTFIT_CATEGORY": "neck_chest"},
            },
            {
                "external_outfit": {
                    "classification": {"category": "neck_chest"},
                    "fit_check": {"metrics": {"vertical_center_ratio": 0.84, "height_ratio": 0.1538}},
                }
            },
        )

        self.assertNotIn("neck-loop-low", result["qa_flags"])
        self.assertNotIn("issue:neck-loop-low", result["review_tags"])

    def test_unknown_asset_has_no_manual_quality_flags(self):
        result = assess_review_quality(
            {
                "id": "gen-001-female-backpack-cheerful-wave",
                "metadata": {"tags": ["backpack-quaternius", "full-body"]},
                "environment": {"OUTFIT_CATEGORY": "torso_back"},
            },
            {"external_outfit": {"classification": {"category": "torso_back"}}},
        )

        self.assertEqual(result["qa_flags"], [])
        self.assertNotIn("asset:weak", result["review_tags"])


if __name__ == "__main__":
    unittest.main()
