import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.musetalk_batch import (
    build_batch_jobs,
    estimate_manual_bbox,
    load_audio_manifest,
    pick_source_media,
    png_dimensions,
)


PNG_640X960 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x02\x80"
    b"\x00\x00\x03\xc0"
    b"\x08\x06\x00\x00\x00"
)


class MuseTalkBatchTests(unittest.TestCase):
    def test_pick_source_media_prefers_portrait_then_front_render(self):
        self.assertEqual(
            pick_source_media(
                {
                    "pose_renders": [
                        "/workspace/outputs/batch/person_pose_front_0024.png",
                        "/workspace/outputs/batch/person_pose_portrait_0024.png",
                        "/workspace/outputs/batch/person_pose_portrait_0072.png",
                    ]
                }
            ),
            "/workspace/outputs/batch/person_pose_portrait_0072.png",
        )
        self.assertEqual(
            pick_source_media({"pose_renders": ["/workspace/outputs/batch/person_pose_front_0024.png"]}),
            "/workspace/outputs/batch/person_pose_front_0024.png",
        )

    def test_pick_source_media_uses_existing_portrait_sibling_for_talking_video_quality(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as tmp:
            render_dir = Path(tmp)
            side = render_dir / "pose_side_0024.png"
            portrait = render_dir / "pose_portrait_0024.png"
            neutral_portrait = render_dir / "pose_portrait_0072.png"
            side.write_bytes(b"side")
            portrait.write_bytes(b"portrait")
            neutral_portrait.write_bytes(b"neutral")

            picked = pick_source_media({"pose_renders": [f"/workspace/outputs/{render_dir.name}/pose_side_0024.png"]})

        self.assertEqual(picked, f"/workspace/outputs/{render_dir.name}/pose_portrait_0072.png")

    def test_pick_source_media_prefers_lipsync_active_mouth_review_frame(self):
        self.assertEqual(
            pick_source_media(
                {
                    "pose_renders": [
                        "/workspace/outputs/batch/person_pose_portrait_0001.png",
                        "/workspace/outputs/batch/person_pose_portrait_0009.png",
                        "/workspace/outputs/batch/person_pose_portrait_0072.png",
                    ],
                    "lipsync_animation": {"enabled": True},
                    "qa": {"preferred_review_frame": "pose_portrait_0009.png"},
                }
            ),
            "/workspace/outputs/batch/person_pose_portrait_0009.png",
        )

    def test_load_audio_manifest_rejects_missing_audio_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "audio.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "clips": [
                            {
                                "id": "missing",
                                "path": "/workspace/outputs/speech/does_not_exist.wav",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "audio clip path does not exist"):
                load_audio_manifest(manifest_path)

    def test_estimate_manual_bbox_uses_png_dimensions(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as tmp:
            render_path = Path(tmp) / "pose_portrait_0072.png"
            render_path.write_bytes(PNG_640X960)

            self.assertEqual(png_dimensions(render_path), (640, 960))
            self.assertEqual(
                estimate_manual_bbox(f"/workspace/outputs/{Path(tmp).name}/pose_portrait_0072.png"),
                [204, 364, 435, 633],
            )

    def test_build_batch_jobs_pairs_each_ok_character_with_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = ROOT / "results/test_musetalk_batch_report.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            render_path = ROOT / "outputs/test_musetalk_batch_pose_portrait_0072.png"
            render_path.parent.mkdir(parents=True, exist_ok=True)
            render_path.write_bytes(PNG_640X960)
            report_path.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "pose_renders": ["/workspace/outputs/test_musetalk_batch_pose_portrait_0072.png"],
                    }
                ),
                encoding="utf-8",
            )
            try:
                jobs = build_batch_jobs(
                    {
                        "jobs": [
                            {
                                "id": "person",
                                "status": "ok",
                                "environment": {
                                    "ANIMATION_REPORT_JSON": "/workspace/results/test_musetalk_batch_report.json"
                                },
                            }
                        ]
                    },
                    [{"id": "hello", "path": "/workspace/input/audio/hello.wav"}],
                    Path(tmp),
                )
            finally:
                report_path.unlink(missing_ok=True)
                render_path.unlink(missing_ok=True)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["character_id"], "person")
        self.assertEqual(jobs[0]["tasks"]["task_0"]["audio_path"], "/workspace/input/audio/hello.wav")
        self.assertEqual(jobs[0]["tasks"]["task_0"]["result_name"], "person_hello.mp4")
        self.assertEqual(jobs[0]["tasks"]["task_0"]["manual_bbox"], [204, 364, 435, 633])
        self.assertEqual(jobs[0]["parsing_mode"], "jaw")
        self.assertTrue(jobs[0]["inference_config"].endswith("person_hello.yaml"))

    def test_build_batch_jobs_allows_parsing_mode_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = ROOT / "results/test_musetalk_batch_report_override.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            render_path = ROOT / "outputs/test_musetalk_batch_pose_portrait_override_0072.png"
            render_path.parent.mkdir(parents=True, exist_ok=True)
            render_path.write_bytes(PNG_640X960)
            report_path.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "pose_renders": ["/workspace/outputs/test_musetalk_batch_pose_portrait_override_0072.png"],
                    }
                ),
                encoding="utf-8",
            )
            try:
                jobs = build_batch_jobs(
                    {
                        "jobs": [
                            {
                                "id": "person",
                                "status": "ok",
                                "environment": {
                                    "ANIMATION_REPORT_JSON": "/workspace/results/test_musetalk_batch_report_override.json"
                                },
                            }
                        ]
                    },
                    [{"id": "hello", "path": "/workspace/input/audio/hello.wav", "parsing_mode": "raw"}],
                    Path(tmp),
                )
            finally:
                report_path.unlink(missing_ok=True)
                render_path.unlink(missing_ok=True)

        self.assertEqual(jobs[0]["parsing_mode"], "raw")


if __name__ == "__main__":
    unittest.main()
