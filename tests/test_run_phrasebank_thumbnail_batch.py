import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_phrasebank_thumbnail_batch import (
    DEFAULT_ACCESSORIES,
    DEFAULT_ANIMATIONS,
    build_phrasebank_thumbnail_command,
    load_phrasebank_cache_lines,
)


class RunPhrasebankThumbnailBatchTests(unittest.TestCase):
    def test_load_phrasebank_cache_lines_reads_cache_lines(self):
        lines = load_phrasebank_cache_lines(ROOT / "config/lipsync_phrase_bank.full_viseme.json")

        self.assertGreaterEqual(len(lines), 8)
        self.assertEqual(lines[0]["audio_cache_key"], "683aff4ae080c56e")
        self.assertEqual(lines[0]["lipsync_timeline"], "outputs/lipsync/cache/683aff4ae080c56e.face.json")

    def test_build_phrasebank_thumbnail_command_uses_fast_thumbnail_defaults(self):
        cache_lines = [
            {
                "text": "Line one.",
                "audio_cache_key": "one",
                "lipsync_timeline": "outputs/lipsync/cache/one.face.json",
            }
        ]

        command = build_phrasebank_thumbnail_command(
            batch_id="thumb-prod-032-001",
            count=32,
            cache_lines=cache_lines,
        )

        self.assertEqual(command[:2], ["python3", "scripts/run_cached_lipsync_batch.py"])
        self.assertIn("--batch-id", command)
        self.assertIn("thumb-prod-032-001", command)
        self.assertIn("--count", command)
        self.assertIn("32", command)
        self.assertIn("--accessories", command)
        self.assertIn(DEFAULT_ACCESSORIES, command)
        self.assertIn("--animations", command)
        self.assertIn(DEFAULT_ANIMATIONS, command)
        self.assertIn("--render-profile", command)
        self.assertIn("thumbnail_lipsync", command)
        self.assertIn("--optimization-profile", command)
        self.assertIn("auto", command)
        self.assertIn("--skip-combined-refresh", command)
        self.assertIn("--gallery-detail-mode", command)
        self.assertIn("compact", command)
        encoded = command[command.index("--cache-lines-json") + 1]
        self.assertEqual(json.loads(encoded), cache_lines)

    def test_build_phrasebank_thumbnail_command_can_publish_combined(self):
        command = build_phrasebank_thumbnail_command(
            batch_id="thumb-prod-008-001",
            count=8,
            cache_lines=[
                {
                    "text": "Line one.",
                    "audio_cache_key": "one",
                    "lipsync_timeline": "outputs/lipsync/cache/one.face.json",
                }
            ],
            skip_combined_refresh=False,
        )

        self.assertNotIn("--skip-combined-refresh", command)
        detail_index = command.index("--gallery-detail-mode")
        self.assertEqual(command[detail_index + 1], "full")


if __name__ == "__main__":
    unittest.main()
