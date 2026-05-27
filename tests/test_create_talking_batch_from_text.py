import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.create_talking_batch_from_text import (
    auto_batch_paths,
    build_finalize_command,
    build_manifest_render_command,
    build_prepare_person_command,
    combine_person_manifests,
    merge_person_spec,
)


class CreateTalkingBatchFromTextTests(unittest.TestCase):
    def test_merge_person_spec_applies_defaults(self):
        merged = merge_person_spec(
            {"base": "female", "accessory": "glasses", "animation": "talk_idle", "voice": "warm", "render_profile": "fast_lipsync"},
            {"id": "batch-host-001", "text": "Hello"},
        )

        self.assertEqual(merged["id"], "batch-host-001")
        self.assertEqual(merged["base"], "female")
        self.assertEqual(merged["voice"], "warm")
        self.assertEqual(merged["render_profile"], "fast_lipsync")
        self.assertFalse(merged["reuse_audio"])
        self.assertEqual(merged["name"], "Batch Host 001")

    def test_prepare_person_command_uses_text_wrapper_without_render(self):
        spec = merge_person_spec(
            {"base": "female", "accessory": "glasses", "animation": "talk_idle"},
            {"id": "batch-host-001", "text": "Hello", "seed": 11},
        )
        command = build_prepare_person_command(spec, services_config="config/speech_services.example.json")

        self.assertEqual(command[:3], ["python3", "scripts/create_talking_person_from_text.py", "Hello"])
        self.assertIn("--id", command)
        self.assertIn("batch-host-001", command)
        self.assertIn("--seed", command)
        self.assertIn("11", command)
        self.assertIn("--render-profile", command)
        self.assertNotIn("--reuse-audio", command)
        self.assertNotIn("--render", command)

    def test_prepare_person_command_can_reuse_existing_audio(self):
        spec = merge_person_spec({}, {"id": "batch-host-001", "text": "Hello", "reuse_audio": True, "reuse_lipsync": True})
        command = build_prepare_person_command(spec, services_config="config/speech_services.example.json")

        self.assertIn("--reuse-audio", command)
        self.assertIn("--reuse-lipsync", command)

    def test_combine_person_manifests_merges_jobs_and_batch_defaults(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            first = tmp / "one.json"
            second = tmp / "two.json"
            first.write_text(
                json.dumps(
                    {
                        "defaults": {"render_angles": "front,portrait", "cache_base_scenes": "1"},
                        "jobs": [{"id": "one", "lipsync_timeline_json": "/workspace/one.face.json"}],
                    }
                ),
                encoding="utf-8",
            )
            second.write_text(
                json.dumps(
                    {
                        "defaults": {"render_angles": "front,portrait"},
                        "jobs": [{"id": "two", "lipsync_timeline_json": "/workspace/two.face.json"}],
                    }
                ),
                encoding="utf-8",
            )
            combined = combine_person_manifests([first, second], batch_defaults={"render_width": "640"})

        self.assertEqual([job["id"] for job in combined["jobs"]], ["one", "two"])
        self.assertEqual(combined["defaults"]["cache_base_scenes"], "1")
        self.assertEqual(combined["defaults"]["render_width"], "640")

    def test_render_and_finalize_commands_target_one_batch_result(self):
        paths = auto_batch_paths("talking_text_batch2", root=ROOT)

        render = build_manifest_render_command(paths["manifest"], paths["batch_result"])
        finalize = build_finalize_command(paths["batch_result"], paths["gallery"], paths["finalize_summary"], texture_size=768)

        self.assertEqual(render[:5], ["docker", "compose", "run", "--rm", "blender-vrm"])
        self.assertIn("config/person_factory.talking-text-batch2.json", render)
        self.assertIn("results/batch_person_factory_talking-text-batch2_latest.json", render)
        self.assertEqual(finalize[:2], ["python3", "scripts/finalize_batch.py"])
        self.assertIn("--texture-size", finalize)
        self.assertIn("768", finalize)


if __name__ == "__main__":
    unittest.main()
