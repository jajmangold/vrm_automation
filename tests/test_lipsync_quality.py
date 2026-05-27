import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lipsync_quality import (
    analyze_lipsync_timeline,
    analyze_lipsync_timeline_path,
    lipsync_quality_tags,
    summarize_lipsync_validation,
)


class LipSyncQualityTests(unittest.TestCase):
    def test_audio_aligned_rhubarb_timeline_is_ok_with_viseme_coverage_warning(self):
        timeline = {
            "schema": "vrm-person-factory.face-timeline.v1",
            "source": {"mode": "rhubarb"},
            "duration": 0.56,
            "cues": [
                {"time": 0.0, "duration": 0.08, "viseme": "rest", "value": 0.0},
                {"time": 0.08, "duration": 0.12, "viseme": "aa", "value": 0.9},
                {"time": 0.2, "duration": 0.1, "viseme": "ee", "value": 0.8},
                {"time": 0.3, "duration": 0.12, "viseme": "oh", "value": 0.8},
                {"time": 0.42, "duration": 0.14, "viseme": "ou", "value": 0.8},
            ],
            "expressions": [{"time": 0.0, "duration": 0.56, "name": "happy", "value": 0.15}],
        }

        quality = analyze_lipsync_timeline(timeline)

        self.assertEqual(quality["status"], "ok")
        self.assertEqual(quality["source_mode"], "rhubarb")
        self.assertEqual(quality["alignment"], "audio-derived")
        self.assertEqual(quality["cue_count"], 5)
        self.assertEqual(quality["active_visemes"], ["aa", "ee", "oh", "ou"])
        self.assertEqual(quality["missing_expected_active_visemes"], ["ih"])
        self.assertIn("missing-active-viseme:ih", quality["warnings"])
        self.assertEqual(quality["issues"], [])
        self.assertIn("lipsync-quality:ok", lipsync_quality_tags(quality))
        self.assertIn("lipsync-source:rhubarb", lipsync_quality_tags(quality))

    def test_text_estimate_source_is_a_warning_not_a_playback_blocker(self):
        quality = analyze_lipsync_timeline(
            {
                "source": {"mode": "text"},
                "duration": 0.23,
                "cues": [
                    {"time": 0.0, "duration": 0.09, "viseme": "ee", "value": 1.0},
                    {"time": 0.09, "duration": 0.025, "viseme": "rest", "value": 0.0},
                    {"time": 0.115, "duration": 0.09, "viseme": "oh", "value": 1.0},
                ],
            }
        )

        self.assertEqual(quality["status"], "ok")
        self.assertEqual(quality["alignment"], "text-estimate")
        self.assertIn("text-estimate-source", quality["warnings"])

    def test_stt_text_source_is_treated_as_text_estimate(self):
        quality = analyze_lipsync_timeline(
            {
                "source": {"mode": "stt-text"},
                "duration": 0.12,
                "cues": [{"time": 0.0, "duration": 0.12, "viseme": "aa", "value": 1.0}],
            }
        )

        self.assertEqual(quality["alignment"], "text-estimate")
        self.assertIn("text-estimate-source", quality["warnings"])

    def test_timing_errors_mark_timeline_for_review(self):
        quality = analyze_lipsync_timeline(
            {
                "source": {"mode": "rhubarb"},
                "duration": 0.28,
                "cues": [
                    {"time": 0.0, "duration": 0.2, "viseme": "aa", "value": 0.8},
                    {"time": 0.12, "duration": -0.1, "viseme": "ee", "value": 0.8},
                    {"time": 0.7, "duration": 0.1, "viseme": "oh", "value": 0.8},
                ],
            }
        )

        self.assertEqual(quality["status"], "review")
        self.assertIn("overlapping-cues", quality["issues"])
        self.assertIn("non-positive-cue-duration", quality["issues"])
        self.assertIn("cue-outside-duration", quality["issues"])
        self.assertGreaterEqual(quality["score"], 0)
        self.assertLess(quality["score"], 80)

    def test_path_loader_handles_workspace_paths(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            timeline_path = root / "outputs/lipsync/demo.face.json"
            timeline_path.parent.mkdir(parents=True)
            timeline_path.write_text(
                json.dumps(
                    {
                        "source": {"mode": "phoneme-events"},
                        "duration": 0.2,
                        "cues": [{"time": 0.0, "duration": 0.2, "viseme": "aa", "value": 0.9}],
                    }
                ),
                encoding="utf-8",
            )

            quality = analyze_lipsync_timeline_path("/workspace/outputs/lipsync/demo.face.json", root=root)

        self.assertEqual(quality["status"], "ok")
        self.assertEqual(quality["path"], "/workspace/outputs/lipsync/demo.face.json")

    def test_phoneme_source_metadata_is_reported(self):
        quality = analyze_lipsync_timeline(
            {
                "source": {
                    "mode": "phoneme-events",
                    "input_mode": "manual-arpabet",
                    "text": "Hello",
                    "source_schema": "vrm-person-factory.phoneme-events.v1",
                    "source_path": "config/lipsync_hello_phonemes.json",
                    "event_count": 3,
                    "phoneme_count": 3,
                    "unique_phonemes": ["HH", "EH1", "OW1"],
                    "phoneme_counts": {"HH": 1, "EH1": 1, "OW1": 1},
                },
                "duration": 0.36,
                "cues": [
                    {"time": 0.0, "duration": 0.1, "viseme": "rest", "value": 0.0, "source_phoneme": "HH"},
                    {"time": 0.1, "duration": 0.12, "viseme": "ee", "value": 0.8, "source_phoneme": "EH1"},
                    {"time": 0.22, "duration": 0.14, "viseme": "oh", "value": 0.8, "source_phoneme": "OW1"},
                ],
            }
        )

        self.assertEqual(quality["source_mode"], "phoneme-events")
        self.assertEqual(quality["source_event_count"], 3)
        self.assertEqual(quality["source_phoneme_count"], 3)
        self.assertEqual(quality["source_input_mode"], "manual-arpabet")
        self.assertEqual(quality["source_text"], "Hello")
        self.assertEqual(quality["source_schema"], "vrm-person-factory.phoneme-events.v1")
        self.assertEqual(quality["source_path"], "config/lipsync_hello_phonemes.json")
        self.assertEqual(quality["source_unique_phonemes"], ["HH", "EH1", "OW1"])
        self.assertEqual(quality["source_phoneme_counts"], {"HH": 1, "EH1": 1, "OW1": 1})
        self.assertIn("lipsync-source-events:3", lipsync_quality_tags(quality))
        self.assertIn("lipsync-phonemes:3", lipsync_quality_tags(quality))

    def test_summarize_lipsync_validation_rolls_up_batch_quality(self):
        summary = summarize_lipsync_validation(
            {
                "quality_review_count": 1,
                "checked": [
                    {
                        "id": "one",
                        "status": "ok",
                        "lipsync_quality": {
                            "grade": "A",
                            "source_mode": "rhubarb",
                            "cue_count": 43,
                            "duration": 6.72,
                            "expression_count": 2,
                            "active_visemes": ["aa", "ee", "oh", "ou"],
                            "missing_expected_active_visemes": ["ih"],
                            "warnings": ["missing-active-viseme:ih"],
                        },
                    },
                    {
                        "id": "two",
                        "status": "review",
                        "issues": ["asset-review"],
                        "lipsync_quality": {
                            "grade": "C",
                            "source_mode": "phoneme-events",
                            "cue_count": 8,
                            "duration": 1.2,
                            "expression_count": 0,
                            "active_visemes": ["aa"],
                            "missing_expected_active_visemes": ["ee", "ih"],
                            "issues": ["low-cue-density"],
                        },
                    },
                ],
            }
        )

        self.assertEqual(summary["checked_count"], 2)
        self.assertEqual(summary["ok_count"], 1)
        self.assertEqual(summary["review_count"], 1)
        self.assertEqual(summary["grade_counts"], {"A": 1, "C": 1})
        self.assertEqual(summary["source_counts"], {"phoneme-events": 1, "rhubarb": 1})
        self.assertEqual(summary["missing_active_viseme_counts"], {"ee": 1, "ih": 2})
        self.assertEqual(summary["active_visemes"], ["aa", "ee", "oh", "ou"])
        self.assertEqual(summary["cue_count_min"], 8)
        self.assertEqual(summary["cue_count_max"], 43)
        self.assertEqual(summary["expression_count_min"], 0)
        self.assertEqual(summary["expression_count_max"], 2)


if __name__ == "__main__":
    unittest.main()
