import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.create_talking_person_from_text import (
    auto_text_paths,
    build_create_talking_person_command,
    build_generate_speech_command,
    main,
    should_generate_audio,
    write_text_talking_person_report,
)


class CreateTalkingPersonFromTextTests(unittest.TestCase):
    def test_auto_text_paths_are_stable_for_character_id(self):
        paths = auto_text_paths("talk-host-001", root=ROOT)

        self.assertEqual(paths["audio_wav"], ROOT / "outputs/speech/talk-host-001.wav")
        self.assertEqual(paths["audio_manifest"], ROOT / "results/musetalk/talk-host-001_audio.json")
        self.assertEqual(paths["report"], ROOT / "results/talking_person/talk-host-001.text.json")

    def test_generate_speech_command_carries_voice_seed_and_manifest(self):
        command = build_generate_speech_command(
            text="Hello from a generated host.",
            audio_wav=ROOT / "outputs/speech/talk-host-001.wav",
            audio_manifest=ROOT / "results/musetalk/talk-host-001_audio.json",
            clip_id="talk-host-001",
            service="voice_design",
            voice="warm presenter",
            seed=42,
            language="English",
            services_config="config/speech_services.example.json",
        )

        self.assertEqual(command[:3], ["python3", "scripts/generate_speech.py", "Hello from a generated host."])
        self.assertIn("--voice", command)
        self.assertIn("warm presenter", command)
        self.assertIn("--seed", command)
        self.assertIn("42", command)
        self.assertIn("results/musetalk/talk-host-001_audio.json", command)

    def test_create_talking_person_command_can_enable_render(self):
        command = build_create_talking_person_command(
            audio_wav=ROOT / "outputs/speech/talk-host-001.wav",
            person_id="talk-host-001",
            name="Talk Host",
            base="female",
            accessory="glasses",
            animation="talk_idle",
            render=True,
            normalizer="docker",
            render_profile="fast_lipsync",
            reuse_lipsync=True,
            skip_godot_export=True,
        )

        self.assertEqual(command[:3], ["python3", "scripts/create_talking_person.py", "outputs/speech/talk-host-001.wav"])
        self.assertIn("--render", command)
        self.assertIn("--normalizer", command)
        self.assertIn("docker", command)
        self.assertIn("--render-profile", command)
        self.assertIn("fast_lipsync", command)
        self.assertIn("--reuse-lipsync", command)
        self.assertIn("--skip-godot-export", command)

    def test_create_talking_person_command_can_target_shared_lipsync_cache_paths(self):
        command = build_create_talking_person_command(
            audio_wav=ROOT / "outputs/speech/cache/abc123.wav",
            person_id="talk-host-001",
            name="Talk Host",
            base="female",
            accessory="glasses",
            animation="talk_idle",
            render=False,
            normalizer="local",
            normalized_audio=ROOT / "outputs/speech/cache/abc123_clean.wav",
            rhubarb_json=ROOT / "results/rhubarb/cache/abc123_clean.json",
            lipsync_timeline=ROOT / "outputs/lipsync/cache/abc123.face.json",
            reuse_lipsync=True,
        )

        self.assertIn("--normalized-audio", command)
        self.assertIn("outputs/speech/cache/abc123_clean.wav", command)
        self.assertIn("--rhubarb-json", command)
        self.assertIn("results/rhubarb/cache/abc123_clean.json", command)
        self.assertIn("--timeline", command)
        self.assertIn("outputs/lipsync/cache/abc123.face.json", command)

    def test_write_report_records_text_audio_and_commands(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "report.json"
            report = write_text_talking_person_report(
                path,
                person_id="talk-host-001",
                text="Hello.",
                audio_wav=Path("outputs/speech/talk-host-001.wav"),
                audio_manifest=Path("results/musetalk/talk-host-001_audio.json"),
                generate_speech_command=["python3", "scripts/generate_speech.py"],
                create_talking_person_command=["python3", "scripts/create_talking_person.py"],
                render=True,
                audio_cache_key="abc123",
                cache_paths={
                    "audio_wav": "outputs/speech/cache/abc123.wav",
                    "lipsync_timeline": "outputs/lipsync/cache/abc123.face.json",
                },
            )
            persisted = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(report["schema"], "vrm-person-factory.text-talking-person.v1")
        self.assertEqual(persisted["person_id"], "talk-host-001")
        self.assertEqual(persisted["text"], "Hello.")
        self.assertTrue(persisted["render"])
        self.assertEqual(persisted["audio_cache_key"], "abc123")
        self.assertEqual(persisted["cache_paths"]["lipsync_timeline"], "outputs/lipsync/cache/abc123.face.json")

    def test_should_generate_audio_respects_reuse_flag(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wav = Path(tmp_dir) / "existing.wav"
            wav.write_bytes(b"RIFF" + b"\0" * 4096)

            self.assertFalse(should_generate_audio(wav, reuse_audio=True))
            self.assertTrue(should_generate_audio(wav, reuse_audio=False))
            self.assertTrue(should_generate_audio(Path(tmp_dir) / "missing.wav", reuse_audio=True))

    def test_main_dry_run_accepts_shared_cache_path_options(self):
        output = StringIO()

        with redirect_stdout(output):
            main(
                [
                    "Shared line.",
                    "--id",
                    "cache-host-001",
                    "--audio-wav",
                    "outputs/speech/cache/abc123.wav",
                    "--normalized-audio",
                    "outputs/speech/cache/abc123_clean.wav",
                    "--rhubarb-json",
                    "results/rhubarb/cache/abc123_clean.json",
                    "--lipsync-timeline",
                    "outputs/lipsync/cache/abc123.face.json",
                    "--audio-cache-key",
                    "abc123",
                    "--reuse-audio",
                    "--reuse-lipsync",
                    "--dry-run",
                ]
            )

        report = json.loads(output.getvalue())

        self.assertIn("--timeline", report["create_talking_person_command"])
        self.assertIn("outputs/lipsync/cache/abc123.face.json", report["create_talking_person_command"])
        self.assertIn("--reuse-lipsync", report["create_talking_person_command"])
        self.assertEqual(report["audio_cache_key"], "abc123")
        self.assertEqual(report["cache_paths"]["normalized_audio"], "outputs/speech/cache/abc123_clean.wav")
        self.assertEqual(report["audio_wav"], str(ROOT / "outputs/speech/cache/abc123.wav"))


if __name__ == "__main__":
    unittest.main()
