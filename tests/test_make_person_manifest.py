import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.make_person_manifest import build_manifest
from scripts.make_person_manifest import job_for_index
from scripts.make_person_manifest import load_accessories


class MakePersonManifestTests(unittest.TestCase):
    def test_builds_requested_number_of_controllable_jobs(self):
        manifest = build_manifest(10)

        self.assertEqual(len(manifest["jobs"]), 10)
        self.assertEqual(manifest["defaults"]["render_angles"], "front,portrait")
        self.assertEqual(manifest["defaults"]["render_pose_frames"], "24,72")
        self.assertTrue(all("controllable" in job["tags"] for job in manifest["jobs"]))
        self.assertTrue(all(job["facial_preset"] for job in manifest["jobs"]))
        self.assertTrue(all(any(tag.startswith("face:") for tag in job["tags"]) for job in manifest["jobs"]))
        self.assertTrue(all(job["model_path"].endswith(".vrm") for job in manifest["jobs"]))

    def test_build_manifest_can_start_at_later_index(self):
        manifest = build_manifest(3, start_index=41)
        ids = [job["id"] for job in manifest["jobs"]]

        self.assertEqual(ids[0].split("-")[:2], ["gen", "042"])
        self.assertEqual(ids[1].split("-")[:2], ["gen", "043"])
        self.assertEqual(ids[2].split("-")[:2], ["gen", "044"])

    def test_jobs_have_unique_ids_and_animation_presets(self):
        manifest = build_manifest(16)
        ids = [job["id"] for job in manifest["jobs"]]
        presets = {job["animation_preset"] for job in manifest["jobs"]}

        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("talk_idle", presets)
        self.assertIn("confident_point", presets)

    def test_generated_manifest_includes_standard_animation_library(self):
        manifest = build_manifest(120)
        presets = {job["animation_preset"] for job in manifest["jobs"]}

        self.assertIn("thinking_idle", presets)
        self.assertIn("listening_nod", presets)
        self.assertIn("present_explain", presets)
        self.assertIn("celebrate", presets)
        self.assertIn("turntable_review", presets)

    def test_large_batches_alternate_base_models(self):
        manifest = build_manifest(32)
        model_paths = {job["model_path"] for job in manifest["jobs"]}

        self.assertIn("/workspace/input/base_models/vroid_hairsample_female_cc0.vrm", model_paths)
        self.assertIn("/workspace/input/base_models/vroid_hairsample_male_cc0.vrm", model_paths)

    def test_can_build_jobs_from_asset_config(self):
        accessories = load_accessories(ROOT / "config/poly_pizza_assets.json")
        manifest = build_manifest(12, accessories=accessories)
        ids = [job["id"] for job in manifest["jobs"]]

        self.assertEqual(len(accessories), 7)
        self.assertNotIn("fedora-google", {accessory["key"] for accessory in accessories})
        self.assertNotIn("heart-glasses-j-toastie", {accessory["key"] for accessory in accessories})
        self.assertNotIn("monocle-google", {accessory["key"] for accessory in accessories})
        self.assertNotIn("glasses-jeremy", {accessory["key"] for accessory in accessories})
        self.assertNotIn("wizard-hat-google", {accessory["key"] for accessory in accessories})
        self.assertNotIn("crown-quaternius", {accessory["key"] for accessory in accessories})
        self.assertNotIn("hard-hat-google", {accessory["key"] for accessory in accessories})
        self.assertNotIn("bowtie-jeremy", {accessory["key"] for accessory in accessories})
        self.assertEqual(len({accessory["key"] for accessory in accessories}), len(accessories))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(job["outfit_model"].startswith("/workspace/") for job in manifest["jobs"]))
        self.assertTrue(all(job["source_url"].startswith("https://poly.pizza/m/") for job in manifest["jobs"]))
        self.assertTrue(all(job["license"] for job in manifest["jobs"]))
        self.assertTrue(all("license:" in " ".join(job["tags"]) for job in manifest["jobs"]))
        self.assertTrue(all("quality:" in " ".join(job["tags"]) for job in manifest["jobs"]))
        self.assertGreaterEqual(len({job["category"] for job in manifest["jobs"]}), 3)

    def test_rejected_assets_can_be_included_explicitly(self):
        accessories = load_accessories(
            ROOT / "config/poly_pizza_assets.json",
            include_qualities={"ship", "review", "fix", "reject"},
        )
        by_key = {accessory["key"]: accessory for accessory in accessories}

        self.assertEqual(len(accessories), 20)
        self.assertEqual(by_key["fedora-google"]["quality"], "reject")
        self.assertEqual(by_key["heart-glasses-j-toastie"]["quality"], "reject")
        self.assertEqual(by_key["monocle-google"]["quality"], "reject")
        self.assertEqual(by_key["bowtie-jeremy"]["quality"], "review")
        self.assertIn("quality:reject", by_key["fedora-google"]["tags"])
        self.assertIn("quality:reject", by_key["heart-glasses-j-toastie"]["tags"])
        self.assertIn("quality:review", by_key["bowtie-jeremy"]["tags"])
        self.assertEqual(
            by_key["bowtie-jeremy"]["anchor_calibration"]["anchor_name"],
            "neck_chest:collar_center",
        )
        self.assertIn("calibration:image-guided-anchor", by_key["bowtie-jeremy"]["tags"])
        self.assertIn("anchor:neck-chest-collar-center", by_key["bowtie-jeremy"]["tags"])
        self.assertIn("anchor-validation:ok", by_key["bowtie-jeremy"]["tags"])

    def test_neck_accessories_have_visual_qa_fit_overrides(self):
        accessories = load_accessories(ROOT / "config/poly_pizza_assets.json", include_qualities={"ship", "review"})
        by_key = {accessory["key"]: accessory for accessory in accessories}

        bowtie = by_key["bowtie-jeremy"]["fit_overrides"]
        necktie = by_key["necktie-jeremy"]["fit_overrides"]

        self.assertEqual(bowtie["fit_scope"], "neck-chest")
        self.assertEqual(bowtie["scale_axis"], "width")
        self.assertLessEqual(bowtie["target_size_ratio"], 0.085)
        self.assertLess(bowtie["vertical_center_ratio"], 0.82)
        self.assertEqual(necktie["fit_scope"], "neck-chest")
        self.assertEqual(necktie["scale_axis"], "height")
        self.assertGreaterEqual(necktie["target_size_ratio"], 0.075)
        self.assertGreaterEqual(necktie["surface_offset_ratio"], 0.24)

    def test_render_angles_are_category_aware(self):
        accessories = load_accessories(ROOT / "config/poly_pizza_assets.json")
        by_key = {accessory["key"]: index for index, accessory in enumerate(accessories)}

        backpack = job_for_index(by_key["backpack-quaternius"], accessories=accessories)
        necktie = job_for_index(by_key["necktie-jeremy"], accessories=accessories)
        glasses = job_for_index(by_key["aviator-sunglasses-google"], accessories=accessories)

        self.assertEqual(backpack["render_angles"], "front,side,back,portrait")
        self.assertEqual(necktie["render_angles"], "front,portrait")
        self.assertEqual(glasses["render_angles"], "front,portrait")

    def test_render_frames_include_facial_review_moments(self):
        accessories = load_accessories(ROOT / "config/poly_pizza_assets.json")
        first_talk_idle_index = len(accessories)
        talk_job = job_for_index(first_talk_idle_index, accessories=accessories)
        happy_job = job_for_index(0, accessories=accessories)

        self.assertEqual(talk_job["facial_preset"], "talking_soft")
        self.assertEqual(talk_job["render_pose_frames"], "8,18,29,40,72")
        self.assertEqual(happy_job["facial_preset"], "happy")
        self.assertEqual(happy_job["render_pose_frames"], "24,36,72")

    def test_config_backed_large_batches_alternate_base_models(self):
        accessories = load_accessories(ROOT / "config/poly_pizza_assets.json")
        manifest = build_manifest(40, accessories=accessories)
        model_paths = {job["model_path"] for job in manifest["jobs"]}

        self.assertIn("/workspace/input/base_models/vroid_hairsample_female_cc0.vrm", model_paths)
        self.assertIn("/workspace/input/base_models/vroid_hairsample_male_cc0.vrm", model_paths)

    def test_review_quality_assets_are_opt_in(self):
        default_accessories = load_accessories(ROOT / "config/poly_pizza_assets.json")
        review_accessories = load_accessories(
            ROOT / "config/poly_pizza_assets.json",
            include_qualities={"ship", "review"},
        )

        self.assertEqual(len(default_accessories), 7)
        self.assertEqual(len(review_accessories), 10)
        self.assertNotIn("quality:review", " ".join(tag for accessory in default_accessories for tag in accessory["tags"]))
        self.assertIn("bowtie-jeremy", {accessory["key"] for accessory in review_accessories})
        self.assertIn("crown-quaternius", {accessory["key"] for accessory in review_accessories})
        self.assertIn("hard-hat-google", {accessory["key"] for accessory in review_accessories})

    def test_asset_fit_overrides_flow_into_jobs(self):
        accessories = load_accessories(ROOT / "config/poly_pizza_assets.json")
        all_accessories = load_accessories(
            ROOT / "config/poly_pizza_assets.json",
            include_qualities={"ship", "review", "fix", "reject"},
        )
        by_key = {accessory["key"]: index for index, accessory in enumerate(accessories)}
        all_by_key = {accessory["key"]: index for index, accessory in enumerate(all_accessories)}
        monocle = job_for_index(all_by_key["monocle-google"], accessories=all_accessories)
        pirate_hat = job_for_index(by_key["pirate-hat-google"], accessories=accessories)
        hard_hat = job_for_index(all_by_key["hard-hat-google"], accessories=all_accessories)
        crown = job_for_index(all_by_key["crown-quaternius"], accessories=all_accessories)
        bowtie = job_for_index(all_by_key["bowtie-jeremy"], accessories=all_accessories)

        self.assertEqual(monocle["outfit_scale_axis"], "height")
        self.assertLess(monocle["outfit_target_size_ratio"], 0.1)
        self.assertEqual(bowtie["outfit_scale_axis"], "width")
        self.assertLessEqual(bowtie["outfit_target_size_ratio"], 0.24)
        self.assertEqual(pirate_hat["outfit_anchor"], "hat_top")
        self.assertGreater(pirate_hat["outfit_vertical_center_ratio"], 0.94)
        self.assertLess(pirate_hat["outfit_surface_offset_ratio"], 0.1)
        self.assertGreater(pirate_hat["outfit_anchor_z_percentile"], 0.1)
        self.assertLess(pirate_hat["outfit_anchor_offset"][2], 0)
        self.assertIn("02___Default", hard_hat["outfit_exclude_materials"])
        self.assertEqual(hard_hat["outfit_rotation_z_degrees"], 90)
        self.assertIn("anchor-validation:ok", hard_hat["tags"])
        self.assertIn("anchor-validation:ok", crown["tags"])

    def test_problematic_hats_use_smaller_fit_profile(self):
        accessories = load_accessories(
            ROOT / "config/poly_pizza_assets.json",
            include_qualities={"ship", "review", "fix", "reject"},
        )
        by_key = {accessory["key"]: accessory for accessory in accessories}

        cowboy = by_key["cowboy-hat-google"]
        self.assertEqual(cowboy["quality"], "ship")
        self.assertEqual(cowboy["anchor_calibration"]["validation"]["status"], "ok")
        self.assertIn("anchor-validation:ok", cowboy["tags"])
        self.assertLessEqual(cowboy["fit_overrides"]["target_size_ratio"], 0.105)
        self.assertGreater(cowboy["fit_overrides"]["vertical_center_ratio"], 0.94)

        for key in ("wizard-hat-google", "fedora-google", "hard-hat-google", "crown-quaternius"):
            overrides = by_key[key]["fit_overrides"]
            self.assertLessEqual(overrides["target_size_ratio"], 0.105)
            if key != "crown-quaternius":
                self.assertLessEqual(overrides["vertical_center_ratio"], 0.94)


if __name__ == "__main__":
    unittest.main()
