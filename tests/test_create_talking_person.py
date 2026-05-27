import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.create_talking_person import (
    build_ffmpeg_normalize_command,
    build_rhubarb_command,
    local_path,
    should_run_lipsync_alignment,
    workspace_path,
    write_talking_person_artifacts_from_timeline,
    write_talking_person_artifacts,
)


class CreateTalkingPersonTests(unittest.TestCase):
    def test_workspace_and_local_paths_round_trip_repo_paths(self):
        local = ROOT / "outputs/speech/hello.wav"

        self.assertEqual(workspace_path(local), "/workspace/outputs/speech/hello.wav")
        self.assertEqual(local_path("/workspace/outputs/speech/hello.wav"), local)

    def test_ffmpeg_normalize_command_uses_musetalk_container_by_default(self):
        command = build_ffmpeg_normalize_command(
            ROOT / "outputs/speech/input.wav",
            ROOT / "outputs/speech/input_clean.wav",
            mode="docker",
        )

        self.assertEqual(command[:8], ["docker", "compose", "--profile", "musetalk", "run", "--rm", "--entrypoint", "ffmpeg"])
        self.assertEqual(command[8], "musetalk")
        self.assertIn("/workspace/outputs/speech/input.wav", command)
        self.assertEqual(command[-1], "/workspace/outputs/speech/input_clean.wav")
        self.assertIn("pcm_s16le", command)

    def test_rhubarb_command_writes_json_mouth_cues(self):
        command = build_rhubarb_command(
            ROOT / "input/rhubarb/Rhubarb-Lip-Sync-1.14.0-Linux/rhubarb",
            ROOT / "outputs/speech/hello_clean.wav",
            ROOT / "results/rhubarb/hello.json",
        )

        self.assertEqual(command[1:4], ["-f", "json", "-o"])
        self.assertTrue(command[0].endswith("rhubarb"))
        self.assertTrue(command[-1].endswith("outputs/speech/hello_clean.wav"))

    def test_write_artifacts_creates_timeline_and_one_person_manifest(self):
        accessories = [
            {
                "key": "pixel-glasses",
                "title": "Pixel Glasses",
                "role": "pixel glasses",
                "tags": ["glasses", "head-face"],
                "outfit_model": "/workspace/input/assets/pixel_glasses.glb",
                "category": "head_face",
                "license": "CC0",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            timeline_path = tmp / "outputs/lipsync/hello.face.json"
            manifest_path = tmp / "config/person_factory.hello.json"
            report_path = tmp / "results/talking_person/hello.prepare.json"

            report = write_talking_person_artifacts(
                rhubarb_data={
                    "metadata": {"soundFile": "hello_clean.wav"},
                    "mouthCues": [
                        {"start": 0.0, "end": 0.12, "value": "C"},
                        {"start": 0.12, "end": 0.22, "value": "X"},
                    ],
                },
                timeline_path=timeline_path,
                manifest_path=manifest_path,
                report_path=report_path,
                person_id="talk-001",
                display_name="Talk 001",
                base_key="female",
                accessory_query="glasses",
                animation_preset="talk_idle",
                accessories=accessories,
                root=tmp,
            )

            timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            persisted_report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(timeline["source"]["mode"], "rhubarb")
        self.assertEqual(timeline["cues"][0]["viseme"], "aa")
        self.assertEqual(manifest["jobs"][0]["id"], "talk-001")
        self.assertEqual(manifest["jobs"][0]["lipsync_timeline_json"], "/workspace/outputs/lipsync/hello.face.json")
        self.assertEqual(report["cue_count"], 2)
        self.assertEqual(persisted_report["manifest"], str(manifest_path))

    def test_should_run_lipsync_alignment_respects_reuse_flag(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            timeline = Path(tmp_dir) / "hello.face.json"
            timeline.write_text("{}", encoding="utf-8")

            self.assertFalse(should_run_lipsync_alignment(timeline, reuse_lipsync=True))
            self.assertTrue(should_run_lipsync_alignment(timeline, reuse_lipsync=False))
            self.assertTrue(should_run_lipsync_alignment(Path(tmp_dir) / "missing.face.json", reuse_lipsync=True))

    def test_write_artifacts_from_existing_timeline_reuses_cues(self):
        accessories = [
            {
                "key": "pixel-glasses",
                "title": "Pixel Glasses",
                "role": "pixel glasses",
                "tags": ["glasses", "head-face"],
                "outfit_model": "/workspace/input/assets/pixel_glasses.glb",
                "category": "head_face",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            timeline_path = tmp / "outputs/lipsync/hello.face.json"
            manifest_path = tmp / "config/person_factory.hello.json"
            report_path = tmp / "results/talking_person/hello.prepare.json"
            timeline_path.parent.mkdir(parents=True)
            timeline_path.write_text(
                json.dumps({"duration": 1.2, "cues": [{"viseme": "aa"}, {"viseme": "rest"}]}),
                encoding="utf-8",
            )

            report = write_talking_person_artifacts_from_timeline(
                timeline_path=timeline_path,
                manifest_path=manifest_path,
                report_path=report_path,
                person_id="talk-001",
                display_name="Talk 001",
                base_key="female",
                accessory_query="glasses",
                animation_preset="talk_idle",
                accessories=accessories,
                root=tmp,
                reused_lipsync=True,
            )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertTrue(report["reused_lipsync"])
        self.assertEqual(report["cue_count"], 2)
        self.assertEqual(manifest["jobs"][0]["lipsync_timeline_json"], "/workspace/outputs/lipsync/hello.face.json")

    def test_cache_timeline_report_exposes_cache_key_and_hit_status(self):
        accessories = [
            {
                "key": "pixel-glasses",
                "title": "Pixel Glasses",
                "role": "pixel glasses",
                "tags": ["glasses", "head-face"],
                "outfit_model": "/workspace/input/assets/pixel_glasses.glb",
                "category": "head_face",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            timeline_path = tmp / "outputs/lipsync/cache/abc123.face.json"
            manifest_path = tmp / "config/person_factory.hello.json"
            report_path = tmp / "results/talking_person/hello.prepare.json"
            timeline_path.parent.mkdir(parents=True)
            timeline_path.write_text(json.dumps({"duration": 0.5, "cues": []}), encoding="utf-8")

            report = write_talking_person_artifacts_from_timeline(
                timeline_path=timeline_path,
                manifest_path=manifest_path,
                report_path=report_path,
                person_id="talk-001",
                display_name="Talk 001",
                base_key="female",
                accessory_query="glasses",
                animation_preset="talk_idle",
                accessories=accessories,
                root=tmp,
                reused_lipsync=True,
            )

        self.assertEqual(report["cache"]["audio_cache_key"], "abc123")
        self.assertTrue(report["cache"]["reused_lipsync"])
        self.assertEqual(report["cache"]["lipsync_timeline"], "/workspace/outputs/lipsync/cache/abc123.face.json")


if __name__ == "__main__":
    unittest.main()
