import sys
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.accessory_visual_calibration import (
    anchor_calibration_from_boxes,
    apply_anchor_validation_to_asset_config,
    apply_calibration_to_asset_config,
    bbox_from_color_image,
    bbox_from_foreground_image,
    bbox_from_mask_image,
    best_detection_box,
    comfy_output_image_path,
    comfy_saved_images,
    calibrated_fit_overrides,
    discover_qwen_edit_workflows,
    load_asset_fit_overrides,
    mask_registered_fit_overrides,
    multi_view_anchor_calibration_from_boxes,
    poll_comfy_history,
    parse_box,
    parse_device_map,
    parse_named_value,
    prepare_qwen_edit_workflow,
    resolve_box,
    similarity_transform_from_masks,
    stage_comfy_input,
    submit_comfy_workflow,
    validate_anchor_measurement,
    validate_anchor_measurements,
)


class AccessoryVisualCalibrationTests(unittest.TestCase):
    def test_anchor_calibration_records_reusable_qwen_target(self):
        result = anchor_calibration_from_boxes(
            current_box=[150, 420, 500, 520],
            target_box=[260, 390, 390, 450],
            character_box=[100, 140, 540, 900],
            asset_key="bowtie-jeremy",
            category="neck_chest",
            source="qwen-image-edit+sam31",
        )

        self.assertEqual(result["asset_key"], "bowtie-jeremy")
        self.assertEqual(result["category"], "neck_chest")
        self.assertEqual(result["anchor_name"], "neck_chest:collar_center")
        self.assertEqual(result["source"], "qwen-image-edit+sam31")
        self.assertEqual(result["coordinate_space"], "character_render_box_ratio")
        self.assertEqual(result["target_center_ratio"], {"x": 0.5114, "y": 0.3684})
        self.assertEqual(result["target_size_ratio"], {"width": 0.2955, "height": 0.0789})
        self.assertEqual(result["correction_delta_ratio"], {"x": 0.0, "y": -0.0658})

    def test_multi_view_anchor_calibration_records_per_view_qwen_targets(self):
        result = multi_view_anchor_calibration_from_boxes(
            [
                {
                    "view": "front",
                    "current_box": [180, 420, 340, 500],
                    "target_box": [180, 360, 340, 420],
                    "character_box": [100, 100, 500, 900],
                },
                {
                    "view": "right45",
                    "current_box": [200, 440, 330, 500],
                    "target_box": [210, 370, 320, 430],
                    "character_box": [100, 100, 500, 900],
                },
            ],
            asset_key="bowtie-jeremy",
            category="neck_chest",
            source="qwen-image-edit+sam31+multi-angle",
            primary_view="front",
        )

        self.assertEqual(result["asset_key"], "bowtie-jeremy")
        self.assertEqual(result["anchor_name"], "neck_chest:collar_center")
        self.assertEqual(result["source"], "qwen-image-edit+sam31+multi-angle")
        self.assertEqual(result["primary_view"], "front")
        self.assertEqual(result["view_count"], 2)
        self.assertEqual(result["target_center_ratio"], {"x": 0.4, "y": 0.3625})
        self.assertEqual(result["target_size_ratio"], {"width": 0.4, "height": 0.075})
        self.assertEqual(result["views"]["front"]["correction_delta_ratio"], {"x": 0.0, "y": -0.0875})
        self.assertEqual(result["views"]["right45"]["target_center_ratio"], {"x": 0.4125, "y": 0.375})
        self.assertEqual(result["views"]["right45"]["target_size_ratio"], {"width": 0.275, "height": 0.075})

    def test_multi_view_anchor_calibration_validates_against_view_specific_targets(self):
        calibration = multi_view_anchor_calibration_from_boxes(
            [
                {
                    "view": "front",
                    "current_box": [180, 420, 340, 500],
                    "target_box": [180, 360, 340, 420],
                    "character_box": [100, 100, 500, 900],
                },
                {
                    "view": "right45",
                    "current_box": [200, 440, 330, 500],
                    "target_box": [210, 370, 320, 430],
                    "character_box": [100, 100, 500, 900],
                },
            ],
            asset_key="bowtie-jeremy",
            category="neck_chest",
            primary_view="front",
        )

        result = validate_anchor_measurements(
            views=[
                {"view": "front", "box": [180, 360, 340, 420], "character_box": [100, 100, 500, 900]},
                {"view": "right45", "box": [210, 370, 320, 430], "character_box": [100, 100, 500, 900]},
            ],
            anchor_calibration=calibration,
            center_tolerance=0.01,
            size_tolerance=0.01,
            minimum_views=2,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["ok_view_count"], 2)
        self.assertEqual(result["warnings"], [])

    def test_validate_anchor_measurement_accepts_close_view(self):
        calibration = {
            "anchor_name": "neck_chest:collar_center",
            "target_center_ratio": {"x": 0.5, "y": 0.36},
            "target_size_ratio": {"width": 0.2, "height": 0.08},
        }

        result = validate_anchor_measurement(
            view="portrait",
            box=[160, 260, 240, 300],
            character_box=[0, 100, 400, 600],
            anchor_calibration=calibration,
            center_tolerance=0.04,
            size_tolerance=0.04,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["measurement"]["center_ratio"], {"x": 0.5, "y": 0.36})
        self.assertEqual(result["warnings"], [])

    def test_validate_anchor_measurement_flags_drift(self):
        calibration = {
            "anchor_name": "neck_chest:collar_center",
            "target_center_ratio": {"x": 0.5, "y": 0.36},
            "target_size_ratio": {"width": 0.2, "height": 0.08},
        }

        result = validate_anchor_measurement(
            view="front",
            box=[300, 430, 390, 540],
            character_box=[0, 100, 400, 600],
            anchor_calibration=calibration,
            center_tolerance=0.04,
            size_tolerance=0.04,
        )

        self.assertEqual(result["status"], "review")
        self.assertIn("center-x-drift", result["warnings"])
        self.assertIn("center-y-drift", result["warnings"])
        self.assertIn("height-drift", result["warnings"])

    def test_validate_anchor_measurements_aggregates_missing_views(self):
        calibration = {
            "anchor_name": "neck_chest:collar_center",
            "target_center_ratio": {"x": 0.5, "y": 0.36},
            "target_size_ratio": {"width": 0.2, "height": 0.08},
        }

        result = validate_anchor_measurements(
            views=[
                {"view": "portrait", "box": [160, 160, 240, 200], "character_box": [0, 0, 400, 500]},
                {"view": "side", "box": None, "character_box": [0, 0, 400, 500]},
            ],
            anchor_calibration=calibration,
        )

        self.assertEqual(result["status"], "review")
        self.assertEqual(result["view_count"], 2)
        self.assertEqual(result["ok_view_count"], 1)
        self.assertIn("missing-detection:side", result["warnings"])

    def test_validate_anchor_measurements_requires_minimum_views(self):
        calibration = {
            "anchor_name": "neck_chest:collar_center",
            "target_center_ratio": {"x": 0.5, "y": 0.36},
            "target_size_ratio": {"width": 0.2, "height": 0.08},
        }

        result = validate_anchor_measurements(
            views=[
                {"view": "portrait", "box": [160, 160, 240, 200], "character_box": [0, 0, 400, 500]},
            ],
            anchor_calibration=calibration,
            minimum_views=2,
        )

        self.assertEqual(result["status"], "review")
        self.assertIn("insufficient-views:1<2", result["warnings"])

    def test_calibrated_fit_overrides_measures_qwen_target_delta(self):
        current = [150, 420, 500, 520]
        target = [260, 390, 390, 450]
        character = [100, 140, 540, 900]

        result = calibrated_fit_overrides(
            current_box=current,
            target_box=target,
            character_box=character,
            current_overrides={
                "scale_axis": "width",
                "target_size_ratio": 0.22,
                "vertical_center_ratio": 0.72,
            },
            asset_key="bowtie-jeremy",
            category="neck_chest",
        )

        self.assertEqual(result["pixel_delta"], {"x": 0.0, "y": -50.0})
        self.assertAlmostEqual(result["scale"]["width"], 130 / 350)
        self.assertEqual(
            result["image_measurement"]["target"],
            {
                "center_ratio": {"x": 0.5114, "y": 0.3684},
                "size_ratio": {"width": 0.2955, "height": 0.0789},
            },
        )
        self.assertEqual(result["image_measurement"]["delta_ratio"], {"x": 0.0, "y": -0.0658})
        self.assertAlmostEqual(result["fit_overrides"]["target_size_ratio"], 0.0817, places=4)
        self.assertAlmostEqual(result["fit_overrides"]["vertical_center_ratio"], 0.7858, places=4)
        self.assertNotIn("horizontal_center_offset_ratio", result["fit_overrides"])
        self.assertEqual(result["anchor_calibration"]["asset_key"], "bowtie-jeremy")
        self.assertEqual(result["anchor_calibration"]["anchor_name"], "neck_chest:collar_center")

    def test_calibrated_fit_overrides_emits_horizontal_anchor_offset_ratio(self):
        result = calibrated_fit_overrides(
            current_box=[160, 420, 360, 520],
            target_box=[230, 420, 430, 520],
            character_box=[100, 140, 540, 900],
            current_overrides={
                "scale_axis": "width",
                "target_size_ratio": 0.2,
                "vertical_center_ratio": 0.7,
                "horizontal_center_offset_ratio": 0.02,
            },
        )

        self.assertAlmostEqual(result["fit_overrides"]["horizontal_center_offset_ratio"], 0.1791, places=4)

    def test_calibrated_fit_overrides_can_apply_damped_corrections(self):
        result = calibrated_fit_overrides(
            current_box=[150, 420, 350, 520],
            target_box=[250, 360, 450, 500],
            character_box=[100, 140, 540, 900],
            current_overrides={
                "scale_axis": "height",
                "target_size_ratio": 0.2,
                "vertical_center_ratio": 0.7,
                "horizontal_center_offset_ratio": 0.0,
            },
            center_correction_gain=0.5,
            size_correction_gain=0.5,
        )

        self.assertEqual(result["image_measurement"]["delta_ratio"], {"x": 0.2273, "y": -0.0526})
        self.assertAlmostEqual(result["fit_overrides"]["horizontal_center_offset_ratio"], 0.1136, places=4)
        self.assertAlmostEqual(result["fit_overrides"]["vertical_center_ratio"], 0.7263, places=4)
        self.assertAlmostEqual(result["fit_overrides"]["target_size_ratio"], 0.24, places=4)

    def test_load_asset_fit_overrides_matches_catalog_key_or_asset_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "assets.json"
            config_path.write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "id": "poly-pizza-bowtie-jeremy",
                                "title": "Bowtie",
                                "creator": "jeremy",
                                "fit_overrides": {
                                    "scale_axis": "width",
                                    "target_size_ratio": 0.0972,
                                    "vertical_center_ratio": 0.7998,
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            by_catalog_key = load_asset_fit_overrides(config_path, "bowtie-jeremy")
            by_asset_id = load_asset_fit_overrides(config_path, "poly-pizza-bowtie-jeremy")

            self.assertEqual(by_catalog_key["target_size_ratio"], 0.0972)
            self.assertEqual(by_asset_id["vertical_center_ratio"], 0.7998)

    def test_apply_calibration_to_asset_config_updates_fit_anchor_and_review_status(self):
        result = calibrated_fit_overrides(
            current_box=[150, 420, 500, 520],
            target_box=[260, 390, 390, 450],
            character_box=[100, 140, 540, 900],
            current_overrides={
                "scale_axis": "width",
                "target_size_ratio": 0.22,
                "vertical_center_ratio": 0.72,
            },
            asset_key="bowtie-jeremy",
            category="neck_chest",
            source="qwen-image-edit-2509+sam31",
        )

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "assets.json"
            config_path.write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "id": "poly-pizza-bowtie-jeremy",
                                "title": "Bowtie",
                                "creator": "jeremy",
                                "fit_overrides": {"target_size_ratio": 0.22},
                                "anchor_calibration": {
                                    "validation": {
                                        "status": "ok",
                                        "reports": ["old.json"],
                                    }
                                },
                            }
                        ]
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            update = apply_calibration_to_asset_config(
                config_path=config_path,
                asset_key="bowtie-jeremy",
                calibration_result=result,
                calibration_source="outputs/calibration/bowtie_anchor_calibration.json",
                method="qwen-image-edit-2509+sam31",
            )
            updated = json.loads(config_path.read_text(encoding="utf-8"))["assets"][0]

            self.assertEqual(update["asset_id"], "poly-pizza-bowtie-jeremy")
            self.assertEqual(updated["fit_overrides"]["target_size_ratio"], 0.0817)
            self.assertEqual(updated["anchor_calibration"]["source"], "outputs/calibration/bowtie_anchor_calibration.json")
            self.assertEqual(updated["anchor_calibration"]["method"], "qwen-image-edit-2509+sam31")
            self.assertEqual(updated["anchor_calibration"]["target_center_ratio"], {"x": 0.5114, "y": 0.3684})
            self.assertEqual(updated["anchor_calibration"]["validation"]["status"], "review")
            self.assertIn("old.json", updated["anchor_calibration"]["validation"]["previous_reports"])

    def test_apply_anchor_validation_to_asset_config_promotes_ok_validation(self):
        validation = {
            "status": "ok",
            "anchor_name": "neck_chest:collar_center",
            "view_count": 4,
            "minimum_views": 4,
            "ok_view_count": 4,
            "warnings": [],
        }

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "assets.json"
            config_path.write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "id": "poly-pizza-bowtie-jeremy",
                                "title": "Bowtie",
                                "creator": "jeremy",
                                "anchor_calibration": {
                                    "anchor_name": "neck_chest:collar_center",
                                    "validation": {
                                        "status": "review",
                                        "reports": ["old.json"],
                                        "notes": ["needs a second view"],
                                    },
                                },
                            }
                        ]
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            update = apply_anchor_validation_to_asset_config(
                config_path=config_path,
                asset_key="bowtie-jeremy",
                validation_result=validation,
                validation_source="outputs/calibration/bowtie_rerender_anchor_validation.json",
                notes=["multi-view SAM validation passed"],
            )
            updated = json.loads(config_path.read_text(encoding="utf-8"))["assets"][0]

        self.assertEqual(update["status"], "updated")
        self.assertEqual(updated["anchor_calibration"]["validation"]["status"], "ok")
        self.assertEqual(updated["anchor_calibration"]["validation"]["view_count"], 4)
        self.assertEqual(updated["anchor_calibration"]["validation"]["ok_view_count"], 4)
        self.assertEqual(
            updated["anchor_calibration"]["validation"]["reports"],
            ["old.json", "outputs/calibration/bowtie_rerender_anchor_validation.json"],
        )
        self.assertEqual(updated["anchor_calibration"]["validation"]["previous_status"], "review")
        self.assertIn("needs a second view", updated["anchor_calibration"]["validation"]["previous_notes"])
        self.assertIn("multi-view SAM validation passed", updated["anchor_calibration"]["validation"]["notes"])

    def test_bbox_from_mask_image_uses_nonzero_pixels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mask.png"
            from PIL import Image

            image = Image.new("L", (10, 8), 0)
            pixels = image.load()
            for y in range(2, 6):
                for x in range(3, 8):
                    pixels[x, y] = 255
            image.save(path)

            self.assertEqual(bbox_from_mask_image(path), [3, 2, 8, 6])

    def test_bbox_from_color_image_detects_red_accessory_pixels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "render.png"
            from PIL import Image

            image = Image.new("RGB", (12, 10), (40, 42, 45))
            pixels = image.load()
            for y in range(3, 8):
                for x in range(2, 9):
                    pixels[x, y] = (190, 35, 28)
            pixels[10, 1] = (120, 115, 115)
            pixels[11, 0] = (210, 120, 20)
            image.save(path)

            self.assertEqual(bbox_from_color_image(path, "red-accessory"), [2, 3, 9, 8])

    def test_resolve_box_can_fallback_from_sam_to_red_accessory_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "render.png"
            from PIL import Image

            image = Image.new("RGB", (12, 10), (40, 42, 45))
            pixels = image.load()
            for y in range(3, 8):
                for x in range(2, 9):
                    pixels[x, y] = (190, 35, 28)
            image.save(path)

            self.assertEqual(
                resolve_box(
                    explicit_box=None,
                    mask_path=None,
                    image_path=str(path),
                    prompt="red bow tie",
                    sam_endpoint="http://127.0.0.1:1",
                    image_box_mode="sam-red-fallback",
                ),
                [2, 3, 9, 8],
            )

    def test_bbox_from_foreground_image_detects_character_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "render.png"
            from PIL import Image

            image = Image.new("RGB", (24, 20), (38, 39, 41))
            pixels = image.load()
            for y in range(4, 17):
                for x in range(7, 19):
                    pixels[x, y] = (175, 180, 190)
            for y in range(8, 11):
                for x in range(10, 16):
                    pixels[x, y] = (210, 28, 22)
            image.save(path)

            self.assertEqual(bbox_from_foreground_image(path), [7, 4, 19, 17])

    def test_best_detection_box_can_union_split_accessory_detections(self):
        response = {
            "results": [
                {
                    "results": [
                        {
                            "detections": [
                                {"box_xyxy": [140, 680, 220, 780], "score": 0.93},
                                {"box_xyxy": [282, 700, 298, 708], "score": 0.71},
                                {"box_xyxy": [382, 690, 431, 790], "score": 0.92},
                            ]
                        }
                    ]
                }
            ]
        }

        self.assertEqual(best_detection_box(response, combine=True), [140.0, 680.0, 431.0, 790.0])

    def test_similarity_transform_from_masks_aligns_geometry(self):
        import numpy as np

        current = np.zeros((120, 120), dtype=bool)
        target = np.zeros((120, 120), dtype=bool)
        current[30:80, 48:58] = True
        current[25:35, 42:64] = True
        target[38:98, 64:76] = True
        target[32:44, 56:84] = True

        result = similarity_transform_from_masks(current, target, [0, 0, 120, 120])

        self.assertAlmostEqual(result["centroid_delta_pixels"]["x"], 17.0, places=1)
        self.assertAlmostEqual(result["centroid_delta_pixels"]["y"], 11.3, places=1)
        self.assertGreater(result["scale"]["height"], 1.1)
        self.assertGreater(result["scale"]["area"], 1.1)

    def test_mask_registered_fit_overrides_uses_mask_similarity(self):
        import numpy as np

        current = np.zeros((120, 120), dtype=bool)
        target = np.zeros((120, 120), dtype=bool)
        current[30:80, 48:58] = True
        target[40:100, 58:70] = True

        result = mask_registered_fit_overrides(
            current,
            target,
            [0, 0, 120, 120],
            current_overrides={
                "scale_axis": "height",
                "target_size_ratio": 0.1,
                "vertical_center_ratio": 0.7,
            },
            asset_key="necktie-jeremy",
            category="neck_chest",
        )

        self.assertIn("mask_registration", result)
        self.assertEqual(result["anchor_calibration"]["source"], "qwen-image-edit+sam31-mask-registration")
        self.assertGreater(result["fit_overrides"]["target_size_ratio"], 0.1)
        self.assertLess(result["fit_overrides"]["vertical_center_ratio"], 0.7)

    def test_parse_box_requires_four_ordered_numbers(self):
        self.assertEqual(parse_box("1,2,3,4"), [1.0, 2.0, 3.0, 4.0])
        with self.assertRaises(ValueError):
            parse_box("1,2,3")
        with self.assertRaises(ValueError):
            parse_box("3,2,1,4")

    def test_parse_named_value_requires_name_equals_value(self):
        self.assertEqual(parse_named_value("portrait=1,2,3,4"), ("portrait", "1,2,3,4"))
        with self.assertRaises(ValueError):
            parse_named_value("portrait")

    def test_parse_device_map_uses_class_equals_device_pairs(self):
        self.assertEqual(
            parse_device_map(["UnetLoaderGGUFMultiGPU=cuda:0", "VAELoaderMultiGPU=cuda:1"]),
            {"UnetLoaderGGUFMultiGPU": "cuda:0", "VAELoaderMultiGPU": "cuda:1"},
        )
        with self.assertRaises(ValueError):
            parse_device_map(["UnetLoaderGGUFMultiGPU"])

    def test_stage_comfy_input_copies_source_into_relative_input_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "source.png"
            source.write_bytes(b"not really a png")
            input_root = tmp_path / "comfy_input"

            staged = stage_comfy_input(source, input_root, "vrm_calibration")

            self.assertEqual(staged, "vrm_calibration/source.png")
            self.assertEqual((input_root / staged).read_bytes(), b"not really a png")

    def test_stage_comfy_input_reuses_existing_comfy_relative_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_root = Path(tmp) / "input"
            source = input_root / "already" / "source.png"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"image")

            self.assertEqual(stage_comfy_input(source, input_root), "already/source.png")

    def test_comfy_output_image_path_resolves_subfolder(self):
        path = comfy_output_image_path(
            {"filename": "bowtie_00001_.png", "subfolder": "vrm_calibration", "type": "output"},
            Path("/tmp/comfy/output"),
        )

        self.assertEqual(path, Path("/tmp/comfy/output/vrm_calibration/bowtie_00001_.png"))

    def test_cli_validates_anchor_calibration_views(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            calibration_path = tmp_path / "anchor.json"
            output_path = tmp_path / "validation.json"
            calibration_path.write_text(
                json.dumps(
                    {
                        "anchor_name": "neck_chest:collar_center",
                        "target_center_ratio": {"x": 0.5, "y": 0.36},
                        "target_size_ratio": {"width": 0.2, "height": 0.08},
                    }
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/accessory_visual_calibration.py"),
                    "--anchor-calibration-json",
                    str(calibration_path),
                    "--view-box",
                    "portrait=160,160,240,200",
                    "--character-box",
                    "0,0,400,500",
                    "--output-json",
                    str(output_path),
                    "--minimum-views",
                    "1",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn('"status": "ok"', completed.stdout)
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8"))["status"], "ok")

    def test_cli_validates_anchor_calibration_view_image_with_red_accessory_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            calibration_path = tmp_path / "anchor.json"
            image_path = tmp_path / "view.png"
            output_path = tmp_path / "validation.json"
            calibration_path.write_text(
                json.dumps(
                    {
                        "anchor_name": "neck_chest:collar_center",
                        "target_center_ratio": {"x": 0.5, "y": 0.36},
                        "target_size_ratio": {"width": 0.2, "height": 0.08},
                    }
                ),
                encoding="utf-8",
            )
            from PIL import Image

            image = Image.new("RGB", (400, 500), (35, 35, 38))
            pixels = image.load()
            for y in range(160, 200):
                for x in range(160, 240):
                    pixels[x, y] = (210, 28, 22)
            image.save(image_path)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/accessory_visual_calibration.py"),
                    "--anchor-calibration-json",
                    str(calibration_path),
                    "--view-image",
                    f"portrait={image_path}",
                    "--image-box-mode",
                    "red-accessory",
                    "--character-box",
                    "0,0,400,500",
                    "--output-json",
                    str(output_path),
                    "--minimum-views",
                    "1",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn('"status": "ok"', completed.stdout)
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8"))["status"], "ok")

    def test_cli_builds_multi_view_anchor_calibration_from_named_boxes(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "multi_view_anchor.json"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/accessory_visual_calibration.py"),
                    "--current-view-box",
                    "front=180,420,340,500",
                    "--target-view-box",
                    "front=180,360,340,420",
                    "--current-view-box",
                    "right45=200,440,330,500",
                    "--target-view-box",
                    "right45=210,370,320,430",
                    "--character-box",
                    "100,100,500,900",
                    "--asset-key",
                    "bowtie-jeremy",
                    "--category",
                    "neck_chest",
                    "--source",
                    "qwen-image-edit+sam31+multi-angle",
                    "--primary-view",
                    "front",
                    "--output-json",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn('"view_count": 2', completed.stdout)
            result = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(result["primary_view"], "front")
            self.assertEqual(result["views"]["right45"]["target_center_ratio"], {"x": 0.4125, "y": 0.375})

    def test_cli_measures_qwen_target_with_auto_character_image_box(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            current_path = tmp_path / "current.png"
            target_path = tmp_path / "qwen_target.png"
            output_path = tmp_path / "calibration.json"
            from PIL import Image

            current = Image.new("RGB", (120, 160), (38, 39, 41))
            target = Image.new("RGB", (120, 160), (38, 39, 41))
            for image in (current, target):
                pixels = image.load()
                for y in range(20, 145):
                    for x in range(30, 95):
                        pixels[x, y] = (180, 185, 194)

            current_pixels = current.load()
            for y in range(82, 98):
                for x in range(35, 79):
                    current_pixels[x, y] = (210, 28, 22)

            target_pixels = target.load()
            for y in range(64, 80):
                for x in range(46, 74):
                    target_pixels[x, y] = (210, 28, 22)

            current.save(current_path)
            target.save(target_path)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/accessory_visual_calibration.py"),
                    "--current-image",
                    str(current_path),
                    "--target-image",
                    str(target_path),
                    "--image-box-mode",
                    "red-accessory",
                    "--character-image",
                    str(current_path),
                    "--asset-key",
                    "bowtie-jeremy",
                    "--category",
                    "neck_chest",
                    "--output-json",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn('"character_box"', completed.stdout)
            result = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(result["character_box"], [30.0, 20.0, 95.0, 145.0])
            self.assertEqual(result["pixel_delta"], {"x": 3.0, "y": -18.0})
            self.assertEqual(result["anchor_calibration"]["target_center_ratio"], {"x": 0.4615, "y": 0.416})

    def test_prepare_qwen_edit_workflow_rewrites_io_prompt_seed_and_devices(self):
        workflow = {
            "1": {"class_type": "UnetLoaderGGUFMultiGPU", "inputs": {"device": "cuda:5"}},
            "6": {"class_type": "CLIPLoaderMultiGPU", "inputs": {"device": "cuda:6"}},
            "7": {"class_type": "VAELoaderMultiGPU", "inputs": {"device": "cuda:7"}},
            "8": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
            "11": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"prompt": "old positive"}},
            "12": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"prompt": ""}},
            "13": {"class_type": "KSampler", "inputs": {"seed": 1, "denoise": 1.0}},
            "14": {"class_type": "ImageScaleToTotalPixels", "inputs": {"megapixels": 0.52}},
            "15": {"class_type": "SaveImage", "inputs": {"filename_prefix": "old"}},
        }

        prepared = prepare_qwen_edit_workflow(
            workflow,
            source_image="vrm_calibration/bowtie.png",
            prompt="Move the bow tie to the collar and make it compact.",
            filename_prefix="vrm_calibration/bowtie_corrected",
            seed=42,
            steps=3,
            denoise=0.62,
            megapixels=0.18,
            negative_prompt="extra bow ties",
            device_map={
                "UnetLoaderGGUFMultiGPU": "cuda:0",
                "CLIPLoaderMultiGPU": "cuda:0",
                "VAELoaderMultiGPU": "cuda:1",
            },
        )

        self.assertEqual(prepared["8"]["inputs"]["image"], "vrm_calibration/bowtie.png")
        self.assertEqual(prepared["11"]["inputs"]["prompt"], "Move the bow tie to the collar and make it compact.")
        self.assertEqual(prepared["12"]["inputs"]["prompt"], "extra bow ties")
        self.assertEqual(prepared["13"]["inputs"]["seed"], 42)
        self.assertEqual(prepared["13"]["inputs"]["steps"], 3)
        self.assertEqual(prepared["13"]["inputs"]["denoise"], 0.62)
        self.assertEqual(prepared["14"]["inputs"]["megapixels"], 0.18)
        self.assertEqual(prepared["15"]["inputs"]["filename_prefix"], "vrm_calibration/bowtie_corrected")
        self.assertEqual(prepared["1"]["inputs"]["device"], "cuda:0")
        self.assertEqual(prepared["6"]["inputs"]["device"], "cuda:0")
        self.assertEqual(prepared["7"]["inputs"]["device"], "cuda:1")

    def test_discover_qwen_edit_workflows_finds_api_workflow_and_loras(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ignored = tmp_path / "plain.json"
            ignored.write_text(json.dumps({"1": {"class_type": "LoadImage", "inputs": {}}}), encoding="utf-8")
            workflow_path = tmp_path / "qwen-image-edit-2509-nextscene-q3ks-4step-multigpu-fast.api.json"
            workflow_path.write_text(
                json.dumps(
                    {
                        "1": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
                        "2": {
                            "class_type": "LoraLoaderModelOnly",
                            "inputs": {"lora_name": "Qwen Image/next-scene_lora-v2-3000.safetensors"},
                        },
                        "3": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"prompt": "old"}},
                        "4": {"class_type": "KSampler", "inputs": {"seed": 1}},
                        "5": {"class_type": "SaveImage", "inputs": {"filename_prefix": "old"}},
                    }
                ),
                encoding="utf-8",
            )

            workflows = discover_qwen_edit_workflows([tmp_path])

            self.assertEqual([workflow["path"] for workflow in workflows], [str(workflow_path)])
            self.assertEqual(workflows[0]["lora_names"], ["Qwen Image/next-scene_lora-v2-3000.safetensors"])
            self.assertGreater(workflows[0]["score"], 0)

    def test_comfy_submission_posts_prompt_and_returns_prompt_id(self):
        calls = []

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"prompt_id":"abc-123"}'

        def fake_urlopen(request, timeout):
            calls.append((request.full_url, request.data, timeout))
            return FakeResponse()

        prompt_id = submit_comfy_workflow(
            {"1": {"class_type": "LoadImage", "inputs": {}}},
            endpoint="http://127.0.0.1:8190",
            client_id="calibrator",
            urlopen=fake_urlopen,
        )

        self.assertEqual(prompt_id, "abc-123")
        self.assertEqual(calls[0][0], "http://127.0.0.1:8190/prompt")
        self.assertIn(b'"client_id": "calibrator"', calls[0][1])
        self.assertIn(b'"prompt"', calls[0][1])

    def test_poll_comfy_history_extracts_saved_images(self):
        responses = [
            b"{}",
            b"""{
              "abc-123": {
                "outputs": {
                  "15": {
                    "images": [
                      {"filename": "bowtie_00001_.png", "subfolder": "vrm_calibration", "type": "output"}
                    ]
                  }
                }
              }
            }""",
        ]

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return self.payload

        def fake_urlopen(request, timeout):
            return FakeResponse(responses.pop(0))

        history = poll_comfy_history(
            "abc-123",
            endpoint="http://127.0.0.1:8190",
            poll_interval_seconds=0,
            timeout_seconds=2,
            urlopen=fake_urlopen,
            sleep=lambda _seconds: None,
        )

        self.assertEqual(
            comfy_saved_images(history, "abc-123"),
            [
                {
                    "node_id": "15",
                    "filename": "bowtie_00001_.png",
                    "subfolder": "vrm_calibration",
                    "type": "output",
                }
            ],
        )

    def test_cli_prepares_qwen_edit_and_measures_supplied_target(self):
        workflow = {
            "8": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
            "11": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"prompt": "old positive"}},
            "12": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"prompt": ""}},
            "13": {"class_type": "KSampler", "inputs": {"seed": 1, "denoise": 1.0}},
            "15": {"class_type": "SaveImage", "inputs": {"filename_prefix": "old"}},
        }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workflow_path = tmp_path / "workflow.json"
            workflow_path.write_text(json.dumps(workflow), encoding="utf-8")
            source_image = tmp_path / "pose.png"
            source_image.write_bytes(b"source")
            input_root = tmp_path / "comfy_input"
            prepared_path = tmp_path / "prepared.json"
            output_path = tmp_path / "calibration.json"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/accessory_visual_calibration.py"),
                    "--current-box",
                    "150,420,500,520",
                    "--target-box",
                    "260,390,390,450",
                    "--character-box",
                    "100,140,540,900",
                    "--qwen-workflow-json",
                    str(workflow_path),
                    "--qwen-source-image",
                    str(source_image),
                    "--qwen-prompt",
                    "Move the bow tie to the collar.",
                    "--qwen-filename-prefix",
                    "vrm_calibration/bowtie_corrected",
                    "--qwen-seed",
                    "77",
                    "--qwen-denoise",
                    "0.65",
                    "--qwen-prepared-workflow-json",
                    str(prepared_path),
                    "--comfy-input-root",
                    str(input_root),
                    "--asset-key",
                    "poly-pizza-bowtie-jeremy",
                    "--category",
                    "neck_chest",
                    "--output-json",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn('"qwen_edit"', completed.stdout)
            result = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(result["qwen_edit"]["status"], "prepared")
            self.assertEqual(result["qwen_edit"]["staged_source_image"], "vrm_calibration/pose.png")
            self.assertEqual(result["qwen_edit"]["seed"], 77)
            self.assertEqual(result["fit_overrides"]["target_size_ratio"], 0.0817)
            prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
            self.assertEqual(prepared["8"]["inputs"]["image"], "vrm_calibration/pose.png")
            self.assertEqual(prepared["11"]["inputs"]["prompt"], "Move the bow tie to the collar.")

    def test_cli_auto_discovers_qwen_workflow_and_records_loras(self):
        workflow = {
            "2": {
                "class_type": "LoraLoaderModelOnly",
                "inputs": {"lora_name": "Qwen Image/next-scene_lora-v2-3000.safetensors"},
            },
            "8": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
            "11": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"prompt": "old positive"}},
            "12": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"prompt": ""}},
            "13": {"class_type": "KSampler", "inputs": {"seed": 1, "denoise": 1.0}},
            "15": {"class_type": "SaveImage", "inputs": {"filename_prefix": "old"}},
        }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workflows_root = tmp_path / "workflows"
            workflows_root.mkdir()
            workflow_path = workflows_root / "qwen-image-edit-2509-nextscene-q3ks-4step-multigpu-fast.api.json"
            workflow_path.write_text(json.dumps(workflow), encoding="utf-8")
            source_image = tmp_path / "pose.png"
            source_image.write_bytes(b"source")
            input_root = tmp_path / "comfy_input"
            output_path = tmp_path / "calibration.json"

            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/accessory_visual_calibration.py"),
                    "--current-box",
                    "150,420,500,520",
                    "--target-box",
                    "260,390,390,450",
                    "--character-box",
                    "100,140,540,900",
                    "--qwen-workflow-json",
                    "auto",
                    "--qwen-workflow-search-root",
                    str(workflows_root),
                    "--qwen-source-image",
                    str(source_image),
                    "--comfy-input-root",
                    str(input_root),
                    "--asset-key",
                    "poly-pizza-bowtie-jeremy",
                    "--category",
                    "neck_chest",
                    "--output-json",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            result = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(result["qwen_edit"]["workflow_template"], str(workflow_path))
            self.assertEqual(
                result["qwen_edit"]["workflow_discovery"]["lora_names"],
                ["Qwen Image/next-scene_lora-v2-3000.safetensors"],
            )
            self.assertEqual(result["anchor_calibration"]["source"], "qwen-image-edit+sam31")

    def test_cli_can_load_current_overrides_and_apply_qwen_measurement_to_asset_config(self):
        workflow = {
            "8": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
            "11": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"prompt": "old positive"}},
            "12": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"prompt": ""}},
            "13": {"class_type": "KSampler", "inputs": {"seed": 1, "denoise": 1.0}},
            "15": {"class_type": "SaveImage", "inputs": {"filename_prefix": "old"}},
        }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workflow_path = tmp_path / "workflow.json"
            workflow_path.write_text(json.dumps(workflow), encoding="utf-8")
            source_image = tmp_path / "pose.png"
            source_image.write_bytes(b"source")
            config_path = tmp_path / "assets.json"
            config_path.write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "id": "poly-pizza-bowtie-jeremy",
                                "title": "Bowtie",
                                "creator": "jeremy",
                                "fit_overrides": {
                                    "scale_axis": "width",
                                    "target_size_ratio": 0.22,
                                    "vertical_center_ratio": 0.72,
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            output_path = tmp_path / "calibration.json"

            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/accessory_visual_calibration.py"),
                    "--current-box",
                    "150,420,500,520",
                    "--target-box",
                    "260,390,390,450",
                    "--character-box",
                    "100,140,540,900",
                    "--qwen-workflow-json",
                    str(workflow_path),
                    "--qwen-source-image",
                    str(source_image),
                    "--asset-key",
                    "bowtie-jeremy",
                    "--category",
                    "neck_chest",
                    "--asset-config-json",
                    str(config_path),
                    "--current-overrides-from-asset-config",
                    "--apply-to-asset-config",
                    "--output-json",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            result = json.loads(output_path.read_text(encoding="utf-8"))
            updated_asset = json.loads(config_path.read_text(encoding="utf-8"))["assets"][0]

            self.assertEqual(result["fit_overrides"]["target_size_ratio"], 0.0817)
            self.assertEqual(result["asset_config_update"]["asset_id"], "poly-pizza-bowtie-jeremy")
            self.assertEqual(updated_asset["fit_overrides"]["vertical_center_ratio"], 0.7858)
            self.assertEqual(updated_asset["anchor_calibration"]["validation"]["status"], "review")


if __name__ == "__main__":
    unittest.main()
