import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.generate_lipsync import (
    build_lipsync_timeline,
    build_lipsync_timeline_from_phonemes,
    phoneme_to_viseme,
    text_to_visemes,
)


class GenerateLipSyncTests(unittest.TestCase):
    def test_text_to_visemes_maps_text_to_canonical_mouth_shapes(self):
        self.assertEqual(text_to_visemes("Hello world"), ["eh", "oh", "oh"])
        self.assertEqual(text_to_visemes(""), ["rest"])

    def test_build_lipsync_timeline_contains_cues_and_expression_overlays(self):
        timeline = build_lipsync_timeline("Hi!", seconds_per_viseme=0.08, intensity=0.8)

        self.assertEqual(timeline["schema"], "vrm-person-factory.face-timeline.v1")
        self.assertGreater(timeline["duration"], 0)
        self.assertEqual(timeline["cues"][0]["viseme"], "ih")
        self.assertEqual(timeline["cues"][0]["value"], 0.8)
        self.assertIn("blink", [expression["name"] for expression in timeline["expressions"]])

    def test_arpabet_phonemes_map_to_canonical_visemes(self):
        self.assertEqual(phoneme_to_viseme("AA1"), "aa")
        self.assertEqual(phoneme_to_viseme("EH0"), "ee")
        self.assertEqual(phoneme_to_viseme("UW"), "ou")
        self.assertEqual(phoneme_to_viseme("SIL"), "rest")

    def test_build_lipsync_timeline_from_timed_phonemes(self):
        timeline = build_lipsync_timeline_from_phonemes(
            [
                {"time": 0.0, "duration": 0.1, "phoneme": "HH"},
                {"time": 0.1, "duration": 0.12, "phoneme": "EH1"},
                {"time": 0.22, "duration": 0.08, "phoneme": "L"},
                {"time": 0.3, "duration": 0.16, "phoneme": "OW1"},
                {"time": 0.46, "duration": 0.1, "phoneme": "SIL"},
            ],
            intensity=0.7,
        )

        self.assertEqual(timeline["source"]["mode"], "phoneme-events")
        self.assertEqual([cue["viseme"] for cue in timeline["cues"]], ["rest", "ee", "rest", "oh", "rest"])
        self.assertEqual(timeline["cues"][1]["value"], 0.7)
        self.assertEqual(timeline["duration"], 0.56)

    def test_phoneme_timeline_preserves_event_provenance(self):
        timeline = build_lipsync_timeline_from_phonemes(
            [
                {"time": 0.0, "duration": 0.1, "phoneme": "HH"},
                {"time": 0.1, "duration": 0.12, "phoneme": "EH1"},
                {"time": 0.22, "duration": 0.14, "phoneme": "OW1"},
            ],
            source_metadata={"mode": "manual-arpabet", "text": "Hello"},
            source_schema="vrm-person-factory.phoneme-events.v1",
            source_path="config/lipsync_hello_phonemes.json",
        )

        self.assertEqual(timeline["source"]["mode"], "phoneme-events")
        self.assertEqual(timeline["source"]["input_mode"], "manual-arpabet")
        self.assertEqual(timeline["source"]["text"], "Hello")
        self.assertEqual(timeline["source"]["source_schema"], "vrm-person-factory.phoneme-events.v1")
        self.assertEqual(timeline["source"]["source_path"], "config/lipsync_hello_phonemes.json")
        self.assertEqual(timeline["source"]["event_count"], 3)
        self.assertEqual(timeline["source"]["phoneme_count"], 3)
        self.assertEqual(timeline["source"]["unique_phonemes"], ["HH", "EH1", "OW1"])
        self.assertEqual(timeline["source"]["phoneme_counts"], {"HH": 1, "EH1": 1, "OW1": 1})
        self.assertEqual(timeline["cues"][1]["source_index"], 1)
        self.assertEqual(timeline["cues"][1]["source_phoneme"], "EH1")


if __name__ == "__main__":
    unittest.main()
