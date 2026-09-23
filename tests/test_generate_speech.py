import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.generate_speech import build_audio_clip, build_tts_request, parse_args, validate_wav_bytes, write_audio_manifest


class GenerateSpeechTests(unittest.TestCase):
    def test_build_tts_request_uses_configured_service_url(self):
        services = {
            "tts": {
                "base_clone": {
                    "url": "http://tts-host:8103/v1/audio/speech",
                }
            }
        }

        url, payload = build_tts_request(services, "base_clone", "Hello", voice="warm host", seed=7)

        self.assertEqual(url, "http://tts-host:8103/v1/audio/speech")
        self.assertEqual(payload["input"], "Hello")
        self.assertEqual(payload["instruct"], "warm host")
        self.assertEqual(payload["seed"], 7)

    def test_build_audio_clip_records_tts_source_metadata(self):
        clip = build_audio_clip(
            clip_id="hello",
            path="/workspace/outputs/speech/hello.wav",
            text="Hello",
            service="base_clone",
            voice="warm host",
        )

        self.assertEqual(clip["id"], "hello")
        self.assertEqual(clip["path"], "/workspace/outputs/speech/hello.wav")
        self.assertEqual(clip["source"]["service"], "tts.base_clone")
        self.assertEqual(clip["source"]["text"], "Hello")

    def test_write_audio_manifest_outputs_musetalk_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audio.json"
            write_audio_manifest(
                [
                    build_audio_clip(
                        clip_id="hello",
                        path="/workspace/outputs/speech/hello.wav",
                        text="Hello",
                        service="base_clone",
                        voice="warm host",
                    )
                ],
                path,
            )
            manifest = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["schema"], "vrm-person-factory.musetalk-audio-batch.v1")
        self.assertEqual(manifest["clips"][0]["id"], "hello")

    def test_validate_wav_bytes_rejects_header_only_audio(self):
        with self.assertRaises(ValueError):
            validate_wav_bytes(b"RIFF" + b"\0" * 40)

    def test_cli_defaults_to_voice_design_service(self):
        args = parse_args(["Hello"])

        self.assertEqual(args.service, "voice_design")


if __name__ == "__main__":
    unittest.main()
