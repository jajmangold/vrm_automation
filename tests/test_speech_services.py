import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.speech_services import load_speech_services, speech_health_urls, tts_payload


class SpeechServicesTests(unittest.TestCase):
    def test_load_speech_services_indexes_configured_services(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "speech.json"
            path.write_text(
                json.dumps(
                    {
                        "services": {
                            "tts": {
                                "voice_design": {
                                    "base_url": "http://amd1:8102",
                                    "endpoint": "/v1/audio/speech",
                                }
                            },
                            "stt": {
                                "fast": {
                                    "base_url": "http://amd0:8098",
                                    "endpoint": "/v1/audio/transcriptions",
                                }
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            services = load_speech_services(path)

        self.assertEqual(services["tts"]["voice_design"]["url"], "http://amd1:8102/v1/audio/speech")
        self.assertEqual(services["stt"]["fast"]["url"], "http://amd0:8098/v1/audio/transcriptions")

    def test_speech_health_urls_use_health_endpoint(self):
        services = {
            "tts": {"voice_design": {"base_url": "http://amd1:8102"}},
            "stt": {"fast": {"base_url": "http://amd0:8098"}},
        }

        self.assertEqual(
            speech_health_urls(services),
            {
                "tts.voice_design": "http://amd1:8102/health",
                "stt.fast": "http://amd0:8098/health",
            },
        )

    def test_tts_payload_uses_qwen_server_shape(self):
        payload = tts_payload("Hello there", voice="calm narrator", seed=123)

        self.assertEqual(payload["input"], "Hello there")
        self.assertEqual(payload["instruct"], "calm narrator")
        self.assertEqual(payload["seed"], 123)
        self.assertEqual(payload["language"], "English")


if __name__ == "__main__":
    unittest.main()
