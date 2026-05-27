import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.measure_anchor_render_examples import build_measurement_report


def write_render(path: Path, with_red_accessory: bool = True) -> None:
    from PIL import Image

    image = Image.new("RGB", (120, 160), (38, 39, 41))
    pixels = image.load()
    for y in range(20, 145):
        for x in range(30, 95):
            pixels[x, y] = (180, 185, 194)
    if with_red_accessory:
        for y in range(64, 80):
            for x in range(46, 74):
                pixels[x, y] = (210, 28, 22)
    image.save(path)


class MeasureAnchorRenderExamplesTests(unittest.TestCase):
    def test_measures_accessory_box_from_render_example(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            render = tmp_path / "pose_portrait_0009.png"
            write_render(render)
            queue = {
                "work_items": [
                    {
                        "asset_key": "bowtie-jeremy",
                        "target_anchor_name": "neck_chest:collar_center",
                        "sam_prompt": "red bow tie",
                        "render_examples": [
                            {
                                "job_id": "demo-bowtie",
                                "pose_renders": [str(render)],
                            }
                        ],
                    }
                ],
                "all_items": [],
            }

            report = build_measurement_report(
                queue,
                workspace_root=tmp_path,
                image_box_mode="red-accessory",
            )

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["summary"]["measured_count"], 1)
        self.assertEqual(report["summary"]["review_count"], 0)
        measurement = report["measurements"][0]
        self.assertEqual(measurement["status"], "ok")
        self.assertEqual(measurement["asset_key"], "bowtie-jeremy")
        self.assertEqual(measurement["job_id"], "demo-bowtie")
        self.assertEqual(measurement["accessory_box"], [46.0, 64.0, 74.0, 80.0])
        self.assertEqual(measurement["character_box"], [30.0, 20.0, 95.0, 145.0])
        self.assertEqual(measurement["measurement"]["center_ratio"], {"x": 0.4615, "y": 0.416})
        self.assertEqual(measurement["measurement"]["size_ratio"], {"width": 0.4308, "height": 0.128})

    def test_can_include_validated_items_and_filter_by_asset_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bowtie_render = tmp_path / "bowtie.png"
            crown_render = tmp_path / "crown.png"
            write_render(bowtie_render)
            write_render(crown_render)
            queue = {
                "work_items": [],
                "all_items": [
                    {
                        "asset_key": "bowtie-jeremy",
                        "calibration_state": "validated",
                        "target_anchor_name": "neck_chest:collar_center",
                        "sam_prompt": "red bow tie",
                        "render_examples": [{"job_id": "bowtie", "pose_renders": [str(bowtie_render)]}],
                    },
                    {
                        "asset_key": "crown-quaternius",
                        "calibration_state": "validate-existing-fit",
                        "target_anchor_name": "head_face:hat_top",
                        "sam_prompt": "red crown",
                        "render_examples": [{"job_id": "crown", "pose_renders": [str(crown_render)]}],
                    },
                ],
            }

            skipped = build_measurement_report(
                queue,
                workspace_root=tmp_path,
                image_box_mode="red-accessory",
                include_validated=False,
            )
            filtered = build_measurement_report(
                queue,
                workspace_root=tmp_path,
                image_box_mode="red-accessory",
                include_validated=True,
                asset_keys={"bowtie-jeremy"},
            )

        self.assertEqual(skipped["summary"]["measured_count"], 0)
        self.assertEqual(skipped["summary"]["item_count"], 0)
        self.assertEqual(filtered["summary"]["item_count"], 1)
        self.assertEqual(filtered["measurements"][0]["asset_key"], "bowtie-jeremy")

    def test_detection_failures_are_reported_for_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            render = tmp_path / "pose.png"
            write_render(render, with_red_accessory=False)
            queue = {
                "work_items": [
                    {
                        "asset_key": "bowtie-jeremy",
                        "target_anchor_name": "neck_chest:collar_center",
                        "sam_prompt": "red bow tie",
                        "render_examples": [{"job_id": "missing", "pose_renders": [str(render)]}],
                    }
                ],
            }

            report = build_measurement_report(
                queue,
                workspace_root=tmp_path,
                image_box_mode="red-accessory",
            )

        self.assertEqual(report["status"], "review")
        self.assertEqual(report["summary"]["measured_count"], 0)
        self.assertEqual(report["summary"]["review_count"], 1)
        self.assertEqual(report["measurements"][0]["status"], "review")
        self.assertIn("image has no red-accessory pixels", report["measurements"][0]["warning"])
        self.assertEqual(report["review_items"], report["measurements"])

    def test_cli_writes_measurement_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            render = tmp_path / "pose.png"
            queue_path = tmp_path / "queue.json"
            output_path = tmp_path / "measurements.json"
            write_render(render)
            queue_path.write_text(
                json.dumps(
                    {
                        "work_items": [
                            {
                                "asset_key": "bowtie-jeremy",
                                "target_anchor_name": "neck_chest:collar_center",
                                "sam_prompt": "red bow tie",
                                "render_examples": [{"job_id": "demo", "pose_renders": [str(render)]}],
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
                    str(ROOT / "scripts/measure_anchor_render_examples.py"),
                    "--queue-json",
                    str(queue_path),
                    "--workspace-root",
                    str(tmp_path),
                    "--image-box-mode",
                    "red-accessory",
                    "--output-json",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn('"measured_count": 1', completed.stdout)
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8"))["summary"]["measured_count"], 1)


if __name__ == "__main__":
    unittest.main()
