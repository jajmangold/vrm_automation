import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lipsync_timeline_overrides import (
    apply_lipsync_timeline_override,
    apply_job_lipsync_overrides,
    canonical_lipsync_path,
    load_lipsync_timeline_overrides,
)


class LipSyncTimelineOverrideTests(unittest.TestCase):
    def test_canonical_lipsync_path_normalizes_workspace_and_local_paths(self):
        self.assertEqual(
            canonical_lipsync_path("outputs/lipsync/demo.face.json"),
            "/workspace/outputs/lipsync/demo.face.json",
        )
        self.assertEqual(
            canonical_lipsync_path(ROOT / "outputs/lipsync/demo.face.json"),
            "/workspace/outputs/lipsync/demo.face.json",
        )
        self.assertEqual(
            canonical_lipsync_path("/workspace/outputs/lipsync/demo.face.json"),
            "/workspace/outputs/lipsync/demo.face.json",
        )

    def test_load_and_apply_override(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "overrides.json"
            path.write_text(
                json.dumps(
                    {
                        "overrides": [
                            {
                                "from": "outputs/lipsync/text.face.json",
                                "to": "/workspace/outputs/lipsync/rhubarb.face.json",
                                "reason": "audio-derived replacement",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            overrides = load_lipsync_timeline_overrides(path)
            result = apply_lipsync_timeline_override("outputs/lipsync/text.face.json", overrides)

        self.assertTrue(result["changed"])
        self.assertEqual(result["path"], "/workspace/outputs/lipsync/rhubarb.face.json")
        self.assertEqual(result["source"], "/workspace/outputs/lipsync/text.face.json")
        self.assertEqual(result["reason"], "audio-derived replacement")

    def test_apply_job_override_records_metadata_and_tags(self):
        job = {
            "id": "legacy",
            "environment": {"LIPSYNC_TIMELINE_JSON": "/workspace/outputs/lipsync/text.face.json"},
            "metadata": {"tags": ["generated"]},
        }
        overrides = {
            "/workspace/outputs/lipsync/text.face.json": {
                "from": "/workspace/outputs/lipsync/text.face.json",
                "to": "/workspace/outputs/lipsync/rhubarb.face.json",
                "reason": "audio-derived replacement",
            }
        }

        updated = apply_job_lipsync_overrides(job, overrides)

        self.assertEqual(updated["lipsync_timeline_override"], "/workspace/outputs/lipsync/rhubarb.face.json")
        self.assertEqual(updated["environment"]["LIPSYNC_TIMELINE_JSON"], "/workspace/outputs/lipsync/rhubarb.face.json")
        self.assertIn("lipsync-override:audio-derived", updated["metadata"]["tags"])
        self.assertIn("lipsync-override-from:text", updated["metadata"]["tags"])
        self.assertIn("lipsync-override-to:rhubarb", updated["metadata"]["tags"])


if __name__ == "__main__":
    unittest.main()
