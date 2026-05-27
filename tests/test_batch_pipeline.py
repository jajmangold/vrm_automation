import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.batch_pipeline import load_manifest, planned_job_environment
from scripts.batch_pipeline import run_jobs


class BatchPipelineTests(unittest.TestCase):
    def test_load_manifest_requires_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text(json.dumps({"jobs": []}), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_manifest(path)

    def test_planned_job_environment_includes_paths_and_metadata(self):
        manifest = {
            "defaults": {
                "model_path": "/workspace/input/base_models/base.vrm",
                "render_angles": "front,back",
                "render_pose_frames": "24,48",
                "animation_preset": "cheerful_wave",
                "export_vrm": "0",
                "export_blend": "0",
                "render_engine": "BLENDER_WORKBENCH",
                "render_compact_arms": "1",
                "render_portrait_lens": "95",
                "render_width": "640",
                "render_height": "960",
                "lipsync_timeline_json": "/workspace/outputs/lipsync/hello.face.json",
                "facial_preset": "happy",
            },
            "jobs": [
                {
                    "id": "sample",
                    "outfit_model": "/workspace/input/outfits/sample.glb",
                    "category": "head_face",
                    "display_name": "Sample Persona",
                    "persona": "playful reviewer",
                    "tags": ["glasses", "review"],
                    "license": "CC0",
                    "source_url": "file:///workspace/input/outfits/sample.glb",
                }
            ],
        }

        env = planned_job_environment(manifest, manifest["jobs"][0])

        self.assertEqual(env["INPUT_MODEL"], "/workspace/input/base_models/base.vrm")
        self.assertEqual(env["OUTFIT_MODEL"], "/workspace/input/outfits/sample.glb")
        self.assertEqual(env["OUTFIT_CATEGORY"], "head_face")
        self.assertEqual(env["RENDER_ANGLES"], "front,back")
        self.assertEqual(env["RENDER_POSE_FRAMES"], "24,48")
        self.assertEqual(env["RENDER_ENGINE"], "BLENDER_WORKBENCH")
        self.assertEqual(env["RENDER_COMPACT_ARMS"], "1")
        self.assertEqual(env["RENDER_PORTRAIT_LENS"], "95")
        self.assertEqual(env["RENDER_WIDTH"], "640")
        self.assertEqual(env["RENDER_HEIGHT"], "960")
        self.assertEqual(env["ANIMATION_PRESET"], "cheerful_wave")
        self.assertEqual(env["FACIAL_PRESET"], "happy")
        self.assertEqual(env["LIPSYNC_TIMELINE_JSON"], "/workspace/outputs/lipsync/hello.face.json")
        self.assertEqual(env["EXPORT_BLEND"], "0")
        self.assertEqual(env["ADD_OUTFIT_PROBE"], "0")
        self.assertEqual(env["ANIMATION_REPORT_JSON"], "/workspace/results/batch/sample_animation.json")
        self.assertEqual(env["OUTPUT_VRM"], "")

    def test_run_job_dry_run_carries_display_metadata(self):
        manifest = {"jobs": [{"id": "sample", "display_name": "Sample Persona", "tags": ["fast"]}]}

        from scripts.batch_pipeline import run_job

        result = run_job(manifest, manifest["jobs"][0], dry_run=True)

        self.assertEqual(result["metadata"]["display_name"], "Sample Persona")
        self.assertEqual(result["metadata"]["tags"], ["fast"])

    def test_planned_job_environment_carries_outfit_fit_overrides(self):
        manifest = {
            "jobs": [
                {
                    "id": "sample",
                    "outfit_model": "/workspace/input/outfits/headphones.glb",
                    "category": "head_face",
                    "outfit_scale_axis": "height",
                    "outfit_target_size_ratio": 0.2,
                    "outfit_vertical_center_ratio": 0.88,
                    "outfit_horizontal_center_offset_ratio": -0.04,
                    "outfit_surface_offset_ratio": 0.05,
                    "outfit_anchor_z_percentile": 0.25,
                    "outfit_rotation_x_degrees": -12,
                    "outfit_rotation_y_degrees": 6,
                    "outfit_rotation_z_degrees": 90,
                    "outfit_surface_conformer": "surface-curve",
                    "outfit_surface_conform_ratio": 0.08,
                    "outfit_surface_conform_exponent": 1.4,
                    "outfit_surface_conform_pin_top_ratio": 0.22,
                    "outfit_surface_snap": "surface-gap",
                    "outfit_surface_snap_gap_ratio": 0.02,
                    "outfit_anchor_offset": [0.01, -0.02, -0.04],
                    "outfit_exclude_materials": ["02___Default"],
                    "front_offset_ratio": 0.24,
                    "outfit_fit_scope": "headwear",
                }
            ]
        }

        env = planned_job_environment(manifest, manifest["jobs"][0])

        self.assertEqual(env["OUTFIT_SCALE_AXIS"], "height")
        self.assertEqual(env["OUTFIT_TARGET_SIZE_RATIO"], "0.2")
        self.assertEqual(env["OUTFIT_VERTICAL_CENTER_RATIO"], "0.88")
        self.assertEqual(env["OUTFIT_HORIZONTAL_CENTER_OFFSET_RATIO"], "-0.04")
        self.assertEqual(env["OUTFIT_SURFACE_OFFSET_RATIO"], "0.05")
        self.assertEqual(env["OUTFIT_ANCHOR_Z_PERCENTILE"], "0.25")
        self.assertEqual(env["OUTFIT_ROTATION_X_DEGREES"], "-12")
        self.assertEqual(env["OUTFIT_ROTATION_Y_DEGREES"], "6")
        self.assertEqual(env["OUTFIT_ROTATION_Z_DEGREES"], "90")
        self.assertEqual(env["OUTFIT_SURFACE_CONFORMER"], "surface-curve")
        self.assertEqual(env["OUTFIT_SURFACE_CONFORM_RATIO"], "0.08")
        self.assertEqual(env["OUTFIT_SURFACE_CONFORM_EXPONENT"], "1.4")
        self.assertEqual(env["OUTFIT_SURFACE_CONFORM_PIN_TOP_RATIO"], "0.22")
        self.assertEqual(env["OUTFIT_SURFACE_SNAP"], "surface-gap")
        self.assertEqual(env["OUTFIT_SURFACE_SNAP_GAP_RATIO"], "0.02")
        self.assertEqual(env["OUTFIT_ANCHOR_OFFSET_X"], "0.01")
        self.assertEqual(env["OUTFIT_ANCHOR_OFFSET_Y"], "-0.02")
        self.assertEqual(env["OUTFIT_ANCHOR_OFFSET_Z"], "-0.04")
        self.assertEqual(env["OUTFIT_EXCLUDE_MATERIALS"], "02___Default")
        self.assertEqual(env["OUTFIT_FRONT_OFFSET_RATIO"], "0.24")
        self.assertEqual(env["OUTFIT_FIT_SCOPE"], "headwear")

    def test_planned_job_environment_applies_catalog_fit_overrides(self):
        manifest = {
            "jobs": [
                {
                    "id": "bowtie",
                    "outfit_model": "/workspace/input/outfits/poly_pizza/bowtie_jeremy.glb",
                    "category": "neck_chest",
                }
            ]
        }

        env = planned_job_environment(manifest, manifest["jobs"][0])

        self.assertEqual(env["OUTFIT_SCALE_AXIS"], "width")
        self.assertEqual(env["OUTFIT_TARGET_SIZE_RATIO"], "0.082")
        self.assertEqual(env["OUTFIT_VERTICAL_CENTER_RATIO"], "0.805")
        self.assertEqual(env["OUTFIT_HORIZONTAL_CENTER_OFFSET_RATIO"], "-0.0022")
        self.assertEqual(env["OUTFIT_FIT_SCOPE"], "neck-chest")

    def test_planned_job_environment_job_overrides_catalog_fit(self):
        manifest = {
            "jobs": [
                {
                    "id": "bowtie",
                    "outfit_model": "/workspace/input/outfits/poly_pizza/bowtie_jeremy.glb",
                    "category": "neck_chest",
                    "outfit_target_size_ratio": 0.14,
                    "outfit_vertical_center_ratio": 0.7,
                }
            ]
        }

        env = planned_job_environment(manifest, manifest["jobs"][0])

        self.assertEqual(env["OUTFIT_TARGET_SIZE_RATIO"], "0.14")
        self.assertEqual(env["OUTFIT_VERTICAL_CENTER_RATIO"], "0.7")
        self.assertEqual(env["OUTFIT_HORIZONTAL_CENTER_OFFSET_RATIO"], "-0.0022")

    def test_cli_accepts_named_output_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest_path = tmp_path / "manifest.json"
            output_path = tmp_path / "batch.json"
            manifest_path.write_text(
                json.dumps({"jobs": [{"id": "sample", "export_vrm": "0"}]}),
                encoding="utf-8",
            )

            import subprocess

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/batch_pipeline.py"),
                    str(manifest_path),
                    "--dry-run",
                    "--output-json",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn('"dry_run": true', completed.stdout)
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8"))["jobs"][0]["status"], "planned")
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8"))["workers"], 1)

    def test_run_jobs_rejects_invalid_worker_count(self):
        with self.assertRaises(ValueError):
            run_jobs({"jobs": [{"id": "sample"}]}, workers=0)

    def test_run_jobs_preserves_manifest_order_when_parallel(self):
        manifest = {"jobs": [{"id": "slow"}, {"id": "fast"}, {"id": "middle"}]}

        def fake_run_job(_manifest, job, dry_run=False):
            return {"id": job["id"], "status": "ok", "dry_run": dry_run}

        with mock.patch("scripts.batch_pipeline.run_job", side_effect=fake_run_job) as run_job:
            results = run_jobs(manifest, dry_run=False, workers=3)

        self.assertEqual([result["id"] for result in results], ["slow", "fast", "middle"])
        self.assertEqual(run_job.call_count, 3)

    def test_run_job_marks_traceback_as_error_even_with_zero_returncode(self):
        from scripts.batch_pipeline import run_job

        manifest = {"jobs": [{"id": "sample", "report_prefix": "results/test_traceback"}]}
        report = ROOT / "results/test_traceback_animation.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({"status": "ok"}), encoding="utf-8")
        completed = subprocess.CompletedProcess(
            args=["docker"],
            returncode=0,
            stdout="starting\nTraceback (most recent call last):\nboom\n",
        )

        try:
            with mock.patch("scripts.batch_pipeline.subprocess.run", return_value=completed):
                result = run_job(manifest, manifest["jobs"][0])
        finally:
            report.unlink(missing_ok=True)

        self.assertEqual(result["status"], "error")
        self.assertIn("fatal-log-marker:Traceback (most recent call last):", result["validation_errors"])

    def test_run_job_requires_animation_report(self):
        from scripts.batch_pipeline import run_job

        manifest = {"jobs": [{"id": "missing-report", "report_prefix": "results/does_not_exist_for_batch_test"}]}
        completed = subprocess.CompletedProcess(args=["docker"], returncode=0, stdout="ok\n")

        with mock.patch("scripts.batch_pipeline.subprocess.run", return_value=completed):
            result = run_job(manifest, manifest["jobs"][0])

        self.assertEqual(result["status"], "error")
        self.assertTrue(any(error.startswith("missing-animation-report:") for error in result["validation_errors"]))

    def test_cli_accepts_worker_count_for_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest_path = tmp_path / "manifest.json"
            output_path = tmp_path / "batch.json"
            manifest_path.write_text(
                json.dumps({"jobs": [{"id": "one"}, {"id": "two"}]}),
                encoding="utf-8",
            )

            import subprocess

            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/batch_pipeline.py"),
                    str(manifest_path),
                    "--dry-run",
                    "--workers",
                    "2",
                    "--output-json",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            output = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(output["workers"], 2)
            self.assertEqual([job["id"] for job in output["jobs"]], ["one", "two"])


if __name__ == "__main__":
    unittest.main()
