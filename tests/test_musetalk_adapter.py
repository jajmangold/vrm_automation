import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.musetalk_adapter import (
    build_musetalk_command,
    build_musetalk_job,
    write_musetalk_inference_config,
)


class MuseTalkAdapterTests(unittest.TestCase):
    def test_build_musetalk_job_validates_inputs_and_sets_defaults(self):
        job = build_musetalk_job(
            character_id="gen-004-female-glasses-cheerful-wave",
            source_media="/workspace/outputs/batch/gen-004_portrait.mp4",
            audio_path="/workspace/input/audio/hello.wav",
            result_name="gen-004_hello.mp4",
        )

        self.assertEqual(job["backend"], "musetalk")
        self.assertEqual(job["version"], "v15")
        self.assertEqual(job["fps"], 25)
        self.assertEqual(job["tasks"]["task_0"]["video_path"], "/workspace/outputs/batch/gen-004_portrait.mp4")
        self.assertEqual(job["tasks"]["task_0"]["audio_path"], "/workspace/input/audio/hello.wav")
        self.assertEqual(job["tasks"]["task_0"]["result_name"], "gen-004_hello.mp4")

    def test_write_musetalk_inference_config_outputs_yaml_shape(self):
        job = build_musetalk_job(
            character_id="gen-004",
            source_media="/workspace/outputs/batch/gen-004_portrait.png",
            audio_path="/workspace/input/audio/hello.wav",
            result_name="gen-004_hello.mp4",
            bbox_shift=-3,
            manual_bbox=[160, 270, 480, 750],
            parsing_mode="raw",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "musetalk.yaml"
            write_musetalk_inference_config(job, path)
            text = path.read_text(encoding="utf-8")

        self.assertIn("task_0:", text)
        self.assertIn('video_path: "/workspace/outputs/batch/gen-004_portrait.png"', text)
        self.assertIn('audio_path: "/workspace/input/audio/hello.wav"', text)
        self.assertIn('result_name: "gen-004_hello.mp4"', text)
        self.assertIn("bbox_shift: -3", text)
        self.assertNotIn("manual_bbox", text)
        self.assertNotIn("parsing_mode", text)

    def test_build_musetalk_job_can_carry_manual_bbox_for_saved_coordinates(self):
        job = build_musetalk_job(
            character_id="gen-004",
            source_media="/workspace/outputs/batch/gen-004_portrait.png",
            audio_path="/workspace/input/audio/hello.wav",
            result_name="gen-004_hello.mp4",
            manual_bbox=[160, 270, 480, 750],
        )

        self.assertEqual(job["tasks"]["task_0"]["manual_bbox"], [160, 270, 480, 750])

    def test_build_musetalk_job_rejects_malformed_manual_bbox(self):
        with self.assertRaises(ValueError):
            build_musetalk_job(
                character_id="gen-004",
                source_media="/workspace/outputs/batch/gen-004_portrait.png",
                audio_path="/workspace/input/audio/hello.wav",
                result_name="gen-004_hello.mp4",
                manual_bbox=[160, 270, 480],
            )

    def test_build_musetalk_command_targets_v15_normal_inference(self):
        job = build_musetalk_job(
            character_id="gen-004",
            source_media="/workspace/outputs/batch/gen-004_portrait.png",
            audio_path="/workspace/input/audio/hello.wav",
            result_name="gen-004_hello.mp4",
            inference_config="/workspace/results/musetalk/gen-004.yaml",
            result_dir="/workspace/outputs/musetalk",
            use_float16=True,
            parsing_mode="raw",
        )

        command = build_musetalk_command(job)

        self.assertEqual(command[:3], ["python3", "-m", "scripts.inference"])
        self.assertIn("--inference_config", command)
        self.assertIn("/workspace/results/musetalk/gen-004.yaml", command)
        self.assertIn("--unet_model_path", command)
        self.assertIn("models/musetalkV15/unet.pth", command)
        self.assertIn("--version", command)
        self.assertIn("v15", command)
        self.assertIn("--use_float16", command)
        self.assertIn("--parsing_mode", command)
        self.assertIn("raw", command)

    def test_cli_writes_job_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "job.json"
            from scripts.musetalk_adapter import main

            main(
                [
                    "--character-id",
                    "gen-004",
                    "--source-media",
                    "/workspace/outputs/batch/gen-004_portrait.png",
                    "--audio",
                    "/workspace/input/audio/hello.wav",
                    "--result-name",
                    "gen-004_hello.mp4",
                    "--output",
                    str(output_path),
                ]
            )
            job = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(job["character_id"], "gen-004")
        self.assertEqual(job["tasks"]["task_0"]["result_name"], "gen-004_hello.mp4")


if __name__ == "__main__":
    unittest.main()
