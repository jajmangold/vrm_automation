import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.musetalk_run_batch import (
    check_model_cache,
    expected_output_path,
    filter_existing_outputs,
    patch_report_with_talking_video,
    select_best_gpu_id,
    publish_completed_jobs,
    run_status,
)


class MuseTalkRunBatchTests(unittest.TestCase):
    def test_check_model_cache_reports_missing_required_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = check_model_cache(Path(tmp))

        self.assertIn("musetalkV15/unet.pth", missing)
        self.assertIn("whisper/config.json", missing)
        self.assertIn("whisper/pytorch_model.bin", missing)
        self.assertIn("sd-vae/diffusion_pytorch_model.bin", missing)
        self.assertIn("dwpose/dw-ll_ucoco_384.pth", missing)
        self.assertIn("face-parse-bisent/79999_iter.pth", missing)
        self.assertIn("face-parse-bisent/resnet18-5c106cde.pth", missing)

    def test_select_best_gpu_id_prefers_most_free_memory(self):
        smi_output = "\n".join(
            [
                "0, 5081, 16384",
                "7, 16373, 16384",
                "9, 16373, 16384",
                "15, 16105, 16384",
            ]
        )

        self.assertEqual(select_best_gpu_id(smi_output), "7")

    def test_select_best_gpu_id_ignores_malformed_rows(self):
        self.assertEqual(select_best_gpu_id("bad\n2, 4096, 8192\n"), "2")
        self.assertIsNone(select_best_gpu_id("bad\n"))

    def test_expected_output_path_converts_workspace_result_dir_to_local_path(self):
        job = {
            "result_dir": "/workspace/outputs/musetalk",
            "version": "v15",
            "tasks": {"task_0": {"result_name": "person_hello.mp4"}},
        }

        self.assertEqual(expected_output_path(job), ROOT / "outputs/musetalk/v15/person_hello.mp4")

    def test_patch_report_with_talking_video_preserves_existing_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            report_path.write_text(json.dumps({"status": "ok", "pose_renders": []}), encoding="utf-8")

            patch_report_with_talking_video(
                report_path,
                "/workspace/outputs/musetalk/person_hello.mp4",
                {"job": "person_hello.job.json", "audio_path": "/workspace/audio/hello.wav"},
            )

            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["talking_video"], "/workspace/outputs/musetalk/person_hello.mp4")
        self.assertEqual(report["talking_video_backend"], "musetalk")
        self.assertEqual(report["talking_video_quality"], "preview")
        self.assertEqual(report["talking_video_job"]["audio_path"], "/workspace/audio/hello.wav")

    def test_publish_completed_jobs_patches_matching_character_report(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "results") as result_tmp, tempfile.TemporaryDirectory(
            dir=ROOT / "outputs"
        ) as output_tmp:
            result_dir = Path(result_tmp)
            output_dir = Path(output_tmp)
            report_path = result_dir / "person_report.json"
            batch_path = result_dir / "batch.json"
            job_path = result_dir / "person_hello.job.json"
            video_path = output_dir / "v15/person_hello.mp4"
            report_path.write_text(json.dumps({"status": "ok", "pose_renders": []}), encoding="utf-8")
            video_path.parent.mkdir(parents=True, exist_ok=True)
            video_path.write_bytes(b"mp4")
            batch_path.write_text(
                json.dumps(
                    {
                        "jobs": [
                            {
                                "id": "person",
                                "environment": {
                                    "ANIMATION_REPORT_JSON": f"/workspace/results/{result_dir.name}/person_report.json"
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            job_path.write_text(
                json.dumps(
                    {
                        "character_id": "person",
                        "version": "v15",
                        "result_dir": f"/workspace/outputs/{output_dir.name}",
                        "tasks": {
                            "task_0": {
                                "result_name": "person_hello.mp4",
                                "audio_path": "/workspace/outputs/speech/hello.wav",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            summary = publish_completed_jobs([job_path], batch_path)
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(summary["published"], 1)
        self.assertEqual(report["talking_video"], f"/workspace/outputs/{output_dir.name}/v15/person_hello.mp4")

    def test_filter_existing_outputs_skips_completed_musetalk_jobs(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "results") as result_tmp, tempfile.TemporaryDirectory(
            dir=ROOT / "outputs"
        ) as output_tmp:
            result_dir = Path(result_tmp)
            output_dir = Path(output_tmp)
            complete_job = result_dir / "complete.job.json"
            missing_job = result_dir / "missing.job.json"
            video_path = output_dir / "v15/complete.mp4"
            video_path.parent.mkdir(parents=True, exist_ok=True)
            video_path.write_bytes(b"mp4")
            complete_job.write_text(
                json.dumps(
                    {
                        "version": "v15",
                        "result_dir": f"/workspace/outputs/{output_dir.name}",
                        "tasks": {"task_0": {"result_name": "complete.mp4"}},
                    }
                ),
                encoding="utf-8",
            )
            missing_job.write_text(
                json.dumps(
                    {
                        "version": "v15",
                        "result_dir": f"/workspace/outputs/{output_dir.name}",
                        "tasks": {"task_0": {"result_name": "missing.mp4"}},
                    }
                ),
                encoding="utf-8",
            )

            selected, skipped = filter_existing_outputs([complete_job, missing_job])

        self.assertEqual(selected, [missing_job])
        self.assertEqual(skipped, [{"job": str(complete_job), "output": str(video_path)}])

    def test_run_status_marks_failed_returncodes(self):
        self.assertEqual(run_status([], []), "ok")
        self.assertEqual(run_status([], [{"returncode": 0}]), "ok")
        self.assertEqual(run_status([], [{"returncode": 1}]), "failed")
        self.assertEqual(run_status([], [{"returncode": 0}], {"missing_outputs": ["job.json"]}), "failed")
        self.assertEqual(run_status(["missing"], []), "blocked")


if __name__ == "__main__":
    unittest.main()
