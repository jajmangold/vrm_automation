import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.vrm_metadata import summarize_vrm_document, compare_vrm_summaries


class VrmMetadataTests(unittest.TestCase):
    def test_summarizes_vrm0_secondary_animation(self):
        summary = summarize_vrm_document(
            {
                "extensions": {
                    "VRM": {
                        "specVersion": "0.0",
                        "humanoid": {"humanBones": [{"bone": "hips"}, {"bone": "head"}]},
                        "blendShapeMaster": {"blendShapeGroups": [{"name": "Joy"}]},
                        "materialProperties": [{}, {}],
                        "secondaryAnimation": {
                            "boneGroups": [{"comment": "hair"}, {"comment": "skirt"}],
                            "colliderGroups": [{}, {}, {}],
                        },
                        "meta": {"title": "sample"},
                    }
                },
                "extensionsUsed": ["VRM"],
            }
        )

        self.assertEqual(summary["vrm_extension"], "VRM")
        self.assertEqual(summary["spec_version"], "0.0")
        self.assertEqual(summary["humanoid_bone_count"], 2)
        self.assertEqual(summary["expression_count"], 1)
        self.assertEqual(summary["material_property_count"], 2)
        self.assertEqual(summary["spring_bone_group_count"], 2)
        self.assertEqual(summary["collider_group_count"], 3)

    def test_summarizes_vrm1_spring_bone_extension(self):
        summary = summarize_vrm_document(
            {
                "extensions": {
                    "VRMC_vrm": {
                        "humanoid": {"humanBones": {"hips": {}, "head": {}}},
                        "expressions": {"preset": {"happy": {}}, "custom": {"wink": {}}},
                        "meta": {"name": "sample"},
                    },
                    "VRMC_springBone": {
                        "springs": [{}, {}, {}],
                        "colliders": [{}, {}],
                        "colliderGroups": [{}],
                    },
                },
                "extensionsUsed": ["VRMC_vrm", "VRMC_springBone"],
            }
        )

        self.assertEqual(summary["vrm_extension"], "VRMC_vrm")
        self.assertEqual(summary["spring_extension"], "VRMC_springBone")
        self.assertEqual(summary["humanoid_bone_count"], 2)
        self.assertEqual(summary["expression_count"], 2)
        self.assertEqual(summary["spring_bone_group_count"], 3)
        self.assertEqual(summary["collider_count"], 2)
        self.assertEqual(summary["collider_group_count"], 1)

    def test_compare_flags_missing_spring_groups(self):
        before = {"spring_bone_group_count": 2, "collider_group_count": 3, "expression_count": 4}
        after = {"spring_bone_group_count": 1, "collider_group_count": 3, "expression_count": 4}

        result = compare_vrm_summaries(before, after)

        self.assertEqual(result["status"], "review")
        self.assertIn("spring-groups-decreased", result["warnings"])


if __name__ == "__main__":
    unittest.main()
