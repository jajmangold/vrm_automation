import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.rhubarb_adapter import (
    rhubarb_shape_to_viseme,
    rhubarb_to_lipsync_timeline,
    write_lipsync_timeline,
)


class RhubarbAdapterTests(unittest.TestCase):
    def test_rhubarb_shapes_map_to_vrm_visemes(self):
        self.assertEqual(rhubarb_shape_to_viseme("X"), "rest")
        self.assertEqual(rhubarb_shape_to_viseme("A"), "rest")
        self.assertEqual(rhubarb_shape_to_viseme("B"), "ee")
        self.assertEqual(rhubarb_shape_to_viseme("C"), "aa")
        self.assertEqual(rhubarb_shape_to_viseme("D"), "aa")
        self.assertEqual(rhubarb_shape_to_viseme("E"), "oh")
        self.assertEqual(rhubarb_shape_to_viseme("F"), "ou")

    def test_rhubarb_json_converts_to_timed_lipsync_cues(self):
        timeline = rhubarb_to_lipsync_timeline(
            {
                "metadata": {"soundFile": "hello.wav"},
                "mouthCues": [
                    {"start": 0.0, "end": 0.1, "value": "X"},
                    {"start": 0.1, "end": 0.24, "value": "D"},
                    {"start": 0.24, "end": 0.42, "value": "F"},
                ],
            },
            intensity=0.65,
        )

        self.assertEqual(timeline["source"]["mode"], "rhubarb")
        self.assertEqual(timeline["source"]["mouthCue_count"], 3)
        self.assertEqual(timeline["duration"], 0.42)
        self.assertEqual([cue["viseme"] for cue in timeline["cues"]], ["rest", "aa", "ou"])
        self.assertEqual(timeline["cues"][0]["value"], 0.0)
        self.assertEqual(timeline["cues"][1]["value"], 0.65)

    def test_write_lipsync_timeline_outputs_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rhubarb.face.json"
            write_lipsync_timeline(
                path,
                {"metadata": {}, "mouthCues": [{"start": 0.0, "end": 0.2, "value": "E"}]},
            )
            data = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(data["schema"], "vrm-person-factory.face-timeline.v1")
        self.assertEqual(data["cues"][0]["viseme"], "oh")


if __name__ == "__main__":
    unittest.main()
