import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_cached_lipsync_requests import build_requests, matching_accessories, parse_csv
from scripts.make_person_manifest import load_accessories


class BuildCachedLipSyncRequestsTests(unittest.TestCase):
    def test_parse_csv_strips_empty_items(self):
        self.assertEqual(parse_csv(" female, male ,, "), ["female", "male"])

    def test_matching_accessories_uses_ship_only_pool_by_default(self):
        accessories = load_accessories(ROOT / "config/poly_pizza_assets.json")
        matched = matching_accessories(accessories, ["aviator", "pirate", "crown"])

        self.assertEqual([item["key"] for item in matched], ["aviator-sunglasses-google", "pirate-hat-google"])
        self.assertTrue(all(item["quality"] == "ship" for item in matched))

    def test_build_requests_cycles_bases_accessories_and_animations(self):
        accessories = load_accessories(ROOT / "config/poly_pizza_assets.json")
        requests = build_requests(
            batch_id="auto-lip-009",
            count=5,
            accessories=accessories,
            accessory_queries=["aviator", "pirate"],
            bases=["female", "male"],
            animations=["talk_idle", "present_explain"],
            text="Cached line.",
            audio_cache_key="abc123",
            lipsync_timeline="outputs/lipsync/cache/abc123.face.json",
            render_profile="fast_lipsync",
            start_index=3,
        )

        self.assertEqual([item["id"] for item in requests], [f"auto-lip-009-{index:03d}" for index in range(3, 8)])
        self.assertEqual([item["base"] for item in requests], ["female", "female", "male", "male", "female"])
        self.assertEqual([item["accessory"] for item in requests], ["aviator-sunglasses-google", "pirate-hat-google", "aviator-sunglasses-google", "pirate-hat-google", "aviator-sunglasses-google"])
        self.assertEqual([item["animation"] for item in requests], ["talk_idle", "present_explain", "talk_idle", "present_explain", "talk_idle"])
        self.assertTrue(all(item["text"] == "Cached line." for item in requests))
        self.assertTrue(all(item["audio_cache_key"] == "abc123" for item in requests))
        self.assertTrue(all(item["lipsync_timeline"] == "outputs/lipsync/cache/abc123.face.json" for item in requests))
        self.assertTrue(all(item["render_profile"] == "fast_lipsync" for item in requests))
        self.assertIn("Female Aviator Sunglasses Google Talk Idle", requests[0]["name"])

    def test_build_requests_can_cycle_cached_lines(self):
        accessories = load_accessories(ROOT / "config/poly_pizza_assets.json")
        requests = build_requests(
            batch_id="auto-lip-011",
            count=4,
            accessories=accessories,
            accessory_queries=["aviator"],
            bases=["female"],
            animations=["talk_idle"],
            text="Fallback.",
            audio_cache_key="fallback",
            lipsync_timeline="outputs/lipsync/cache/fallback.face.json",
            render_profile="control_lipsync",
            cache_lines=[
                {
                    "text": "Line one.",
                    "audio_cache_key": "one",
                    "lipsync_timeline": "outputs/lipsync/cache/one.face.json",
                },
                {
                    "text": "Line two.",
                    "audio_cache_key": "two",
                    "lipsync_timeline": "outputs/lipsync/cache/two.face.json",
                },
            ],
        )

        self.assertEqual([item["text"] for item in requests], ["Line one.", "Line two.", "Line one.", "Line two."])
        self.assertEqual([item["audio_cache_key"] for item in requests], ["one", "two", "one", "two"])
        self.assertEqual(
            [item["lipsync_timeline"] for item in requests],
            [
                "outputs/lipsync/cache/one.face.json",
                "outputs/lipsync/cache/two.face.json",
                "outputs/lipsync/cache/one.face.json",
                "outputs/lipsync/cache/two.face.json",
            ],
        )

    def test_cli_writes_requests_json(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "requests.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/build_cached_lipsync_requests.py"),
                    "--batch-id",
                    "auto-lip-010",
                    "--count",
                    "2",
                    "--accessories",
                    "aviator,pirate",
                    "--bases",
                    "female",
                    "--animations",
                    "talk_idle,present_explain",
                    "--text",
                    "Cached line.",
                    "--audio-cache-key",
                    "abc123",
                    "--lipsync-timeline",
                    "outputs/lipsync/cache/abc123.face.json",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            data = json.loads(output.read_text(encoding="utf-8"))

        self.assertIn('"request_count": 2', completed.stdout)
        self.assertEqual(len(data["requests"]), 2)
        self.assertEqual(data["requests"][0]["id"], "auto-lip-010-001")
        self.assertEqual(data["requests"][1]["animation"], "present_explain")


if __name__ == "__main__":
    unittest.main()
