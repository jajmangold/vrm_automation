import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.transcribe_speech import (
    build_stt_request,
    normalize_transcript_response,
    parse_args,
    write_transcript_manifest,
)


class TranscribeSpeechTests(unittest.TestCase):
    def test_build_stt_request_uses_configured_service_url(self):
        services = {"stt": {"fast": {"url": "http://amd0:8098/v1/audio/transcriptions"}}}

        url, fields = build_stt_request(services, "fast", model="granite-fast")

        self.assertEqual(url, "http://amd0:8098/v1/audio/transcriptions")
        self.assertEqual(fields["model"], "granite-fast")

    def test_normalize_transcript_response_accepts_openai_shape(self):
        transcript = normalize_transcript_response({"text": "hello world"})

        self.assertEqual(transcript["text"], "hello world")
        self.assertEqual(transcript["segments"], [])

    def test_write_transcript_manifest_records_audio_and_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "transcript.json"
            write_transcript_manifest(
                output,
                audio_path="/workspace/outputs/speech/hello.wav",
                service="fast",
                transcript={"text": "hello world", "segments": []},
            )
            data = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(data["schema"], "vrm-person-factory.transcript.v1")
        self.assertEqual(data["audio_path"], "/workspace/outputs/speech/hello.wav")
        self.assertEqual(data["service"], "fast")
        self.assertEqual(data["text"], "hello world")

    def test_cli_can_request_lipsync_output(self):
        args = parse_args(["outputs/speech/hello.wav", "--lipsync-output", "outputs/lipsync/hello.face.json"])

        self.assertEqual(args.audio_wav, "outputs/speech/hello.wav")
        self.assertEqual(args.lipsync_output, "outputs/lipsync/hello.face.json")


if __name__ == "__main__":
    unittest.main()
