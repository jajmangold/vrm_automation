import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_anchor_probe_manifest import build_probe_manifest


class BuildAnchorProbeManifestTests(unittest.TestCase):
    def test_builds_probe_jobs_from_candidate_suggestions(self):
        suggestions = {
            "suggestions": [
                {
                    "asset_key": "aviator-sunglasses-google",
                    "status": "candidate",
                    "target_anchor_name": "head_face:eye_line",
                    "suggested_fit_overrides": {
                        "scale_axis": "width",
                        "target_size_ratio": 0.1495,
                        "vertical_center_ratio": 0.9053,
                        "surface_offset_ratio": 0.18,
                        "fit_scope": "head-face",
                    },
                },
                {
                    "asset_key": "backpack-quaternius",
                    "status": "review",
                    "target_anchor_name": "torso_back:back_center",
                    "suggested_fit_overrides": {"target_size_ratio": 0.478},
                },
            ]
        }
        asset_config = {
            "assets": [
                {
                    "id": "poly-pizza-aviator-sunglasses-google",
                    "title": "Aviator sunglasses",
                    "creator": "Poly by Google",
                    "license": "Creative Commons Attribution 3.0",
                    "source_url": "https://example.test/aviator",
                    "category": "head_face",
                    "output_path": "input/outfits/poly_pizza/aviator_sunglasses_google.glb",
                },
                {
                    "id": "poly-pizza-backpack-quaternius",
                    "title": "Backpack",
                    "category": "torso_back",
                    "output_path": "input/outfits/poly_pizza/backpack.glb",
                },
            ]
        }

        manifest = build_probe_manifest(
            suggestions,
            asset_config,
            id_prefix="anchor-candidate-test",
            bases=["female"],
            limit=0,
        )

        self.assertEqual(len(manifest["jobs"]), 1)
        job = manifest["jobs"][0]
        self.assertEqual(job["id"], "anchor-candidate-test-001")
        self.assertEqual(job["outfit_model"], "/workspace/input/outfits/poly_pizza/aviator_sunglasses_google.glb")
        self.assertEqual(job["category"], "head_face")
        self.assertEqual(job["outfit_scale_axis"], "width")
        self.assertEqual(job["outfit_target_size_ratio"], 0.1495)
        self.assertEqual(job["outfit_vertical_center_ratio"], 0.9053)
        self.assertEqual(job["outfit_surface_offset_ratio"], 0.18)
        self.assertEqual(job["outfit_fit_scope"], "head-face")
        self.assertIn("anchor-candidate", job["tags"])
        self.assertIn("aviator-sunglasses-google", job["tags"])
        self.assertIn("anchor:head-face-eye-line", job["tags"])
        self.assertIn("source:anchor-fit-suggestion", job["tags"])

    def test_can_include_review_suggestions_and_multiple_bases(self):
        suggestions = {
            "suggestions": [
                {
                    "asset_key": "necklace-quaternius",
                    "status": "review",
                    "target_anchor_name": "neck_chest:neck_loop",
                    "suggested_fit_overrides": {
                        "scale_axis": "height",
                        "target_size_ratio": 0.1538,
                        "vertical_center_ratio": 0.777,
                    },
                }
            ]
        }
        asset_config = {
            "assets": [
                {
                    "id": "poly-pizza-necklace-quaternius",
                    "title": "Necklace",
                    "category": "neck_chest",
                    "output_path": "input/outfits/poly_pizza/necklace_quaternius.glb",
                }
            ]
        }

        manifest = build_probe_manifest(
            suggestions,
            asset_config,
            include_review=True,
            id_prefix="probe",
            bases=["female", "male"],
            limit=0,
        )

        self.assertEqual([job["id"] for job in manifest["jobs"]], ["probe-001", "probe-002"])
        self.assertIn("base:female-hairsample", manifest["jobs"][0]["tags"])
        self.assertIn("base:male-hairsample", manifest["jobs"][1]["tags"])
        self.assertTrue(manifest["jobs"][1]["model_path"].endswith("vroid_hairsample_male_cc0.vrm"))

    def test_can_filter_suggestions_by_asset_key(self):
        suggestions = {
            "suggestions": [
                {
                    "asset_key": "anon-mask-scott-marshall",
                    "status": "candidate",
                    "target_anchor_name": "head_face:face_center",
                    "suggested_fit_overrides": {"target_size_ratio": 0.1406},
                },
                {
                    "asset_key": "aviator-sunglasses-google",
                    "status": "candidate",
                    "target_anchor_name": "head_face:eye_line",
                    "suggested_fit_overrides": {"target_size_ratio": 0.1495},
                },
            ]
        }
        asset_config = {
            "assets": [
                {
                    "id": "poly-pizza-anon-mask-scott-marshall",
                    "title": "Mask",
                    "category": "head_face",
                    "output_path": "input/outfits/poly_pizza/mask.glb",
                },
                {
                    "id": "poly-pizza-aviator-sunglasses-google",
                    "title": "Aviator",
                    "category": "head_face",
                    "output_path": "input/outfits/poly_pizza/aviator.glb",
                },
            ]
        }

        manifest = build_probe_manifest(
            suggestions,
            asset_config,
            asset_keys={"aviator-sunglasses-google"},
            id_prefix="aviator-probe",
        )

        self.assertEqual(len(manifest["jobs"]), 1)
        self.assertEqual(manifest["jobs"][0]["id"], "aviator-probe-001")
        self.assertEqual(manifest["jobs"][0]["outfit_model"], "/workspace/input/outfits/poly_pizza/aviator.glb")

    def test_category_aware_rendering_uses_back_views_for_torso_back_assets(self):
        suggestions = {
            "suggestions": [
                {
                    "asset_key": "backpack-quaternius",
                    "status": "review",
                    "target_anchor_name": "torso_back:back_center",
                    "suggested_fit_overrides": {"target_size_ratio": 0.42},
                },
                {
                    "asset_key": "necktie-jeremy",
                    "status": "review",
                    "target_anchor_name": "neck_chest:collar_center",
                    "suggested_fit_overrides": {"target_size_ratio": 0.12},
                },
            ]
        }
        asset_config = {
            "assets": [
                {
                    "id": "poly-pizza-backpack-quaternius",
                    "title": "Backpack",
                    "category": "torso_back",
                    "output_path": "input/outfits/poly_pizza/backpack.glb",
                },
                {
                    "id": "poly-pizza-necktie-jeremy",
                    "title": "Necktie",
                    "category": "neck_chest",
                    "output_path": "input/outfits/poly_pizza/necktie.glb",
                },
            ]
        }

        manifest = build_probe_manifest(
            suggestions,
            asset_config,
            include_review=True,
            category_aware_rendering=True,
            id_prefix="category-probe",
        )

        backpack, necktie = manifest["jobs"]
        self.assertEqual(backpack["render_angles"], "front,portrait,back")
        self.assertEqual(backpack["render_pose_frames"], "24,72")
        self.assertIn("review:torso-back", backpack["tags"])
        self.assertEqual(necktie["render_angles"], "front,portrait")
        self.assertEqual(necktie["render_pose_frames"], "24,72")
        self.assertIn("review:neck-chest", necktie["tags"])

    def test_cli_writes_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            suggestions_path = tmp_path / "suggestions.json"
            assets_path = tmp_path / "assets.json"
            output_path = tmp_path / "manifest.json"
            suggestions_path.write_text(
                json.dumps(
                    {
                        "suggestions": [
                            {
                                "asset_key": "mask",
                                "status": "candidate",
                                "target_anchor_name": "head_face:face_center",
                                "suggested_fit_overrides": {"target_size_ratio": 0.14},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            assets_path.write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "id": "poly-pizza-mask",
                                "title": "Mask",
                                "category": "head_face",
                                "output_path": "input/outfits/poly_pizza/mask.glb",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            import subprocess

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/build_anchor_probe_manifest.py"),
                    "--suggestions-json",
                    str(suggestions_path),
                    "--asset-config-json",
                    str(assets_path),
                    "--output-json",
                    str(output_path),
                    "--id-prefix",
                    "cli-probe",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn('"id": "cli-probe-001"', completed.stdout)
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8"))["jobs"][0]["id"], "cli-probe-001")


if __name__ == "__main__":
    unittest.main()
