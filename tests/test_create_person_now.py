import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.create_person_now import (
    OutputLockError,
    acquire_output_lock,
    build_single_person_manifest,
    choose_accessory,
    choose_animation,
    main,
    output_lock_path,
)
from scripts.make_person_manifest import load_accessories


class CreatePersonNowTests(unittest.TestCase):
    def test_choose_accessory_matches_key_or_title(self):
        accessories = load_accessories(ROOT / "config/poly_pizza_assets.json")

        backpack = choose_accessory(accessories, "backpack")
        pirate = choose_accessory(accessories, "pirate-hat")

        self.assertIn("backpack", backpack["key"])
        self.assertIn("pirate", pirate["key"])

    def test_choose_animation_requires_known_preset(self):
        self.assertEqual(choose_animation("talk_idle")["preset"], "talk_idle")
        with self.assertRaises(ValueError):
            choose_animation("unknown")

    def test_build_single_person_manifest_carries_lipsync_and_fast_defaults(self):
        accessories = load_accessories(ROOT / "config/poly_pizza_assets.json")
        manifest = build_single_person_manifest(
            person_id="now-test",
            display_name="Now Test",
            base_key="female",
            accessory_query="glasses",
            animation_preset="talk_idle",
            lipsync_timeline_json="/workspace/outputs/lipsync/person_factory_hello.face.json",
            render_profile="fast_lipsync",
            accessories=accessories,
        )

        self.assertEqual(len(manifest["jobs"]), 1)
        job = manifest["jobs"][0]
        self.assertEqual(job["id"], "now-test")
        self.assertEqual(job["display_name"], "Now Test")
        self.assertEqual(job["animation_preset"], "talk_idle")
        self.assertEqual(job["facial_preset"], "talking_soft")
        self.assertEqual(job["lipsync_timeline_json"], "/workspace/outputs/lipsync/person_factory_hello.face.json")
        self.assertIn("instant", job["tags"])
        self.assertIn("face:talking-soft", job["tags"])
        self.assertIn("glasses", " ".join(job["tags"]))
        self.assertEqual(manifest["defaults"]["render_angles"], "portrait")
        self.assertEqual(manifest["defaults"]["render_pose_frames"], "3,9,16")
        self.assertEqual(manifest["defaults"]["export_blend"], "0")

    def test_control_lipsync_manifest_keeps_pose_renders_disabled(self):
        accessories = load_accessories(ROOT / "config/poly_pizza_assets.json")
        manifest = build_single_person_manifest(
            person_id="control-test",
            display_name="Control Test",
            base_key="female",
            accessory_query="necklace",
            animation_preset="talk_idle",
            lipsync_timeline_json="/workspace/outputs/lipsync/person_factory_hello.face.json",
            render_profile="control_lipsync",
            accessories=accessories,
        )

        self.assertEqual(manifest["defaults"]["render_pose_stills"], "0")
        self.assertEqual(manifest["defaults"]["render_pose_frames"], "9")
        self.assertEqual(manifest["defaults"]["render_width"], "384")
        self.assertEqual(manifest["defaults"]["render_height"], "576")

    def test_single_person_torso_back_accessory_overrides_fast_portrait_only_render(self):
        accessories = load_accessories(ROOT / "config/poly_pizza_assets.json")
        manifest = build_single_person_manifest(
            person_id="backpack-qa-test",
            display_name="Backpack QA Test",
            base_key="female",
            accessory_query="backpack",
            animation_preset="celebrate",
            lipsync_timeline_json="/workspace/outputs/lipsync/person_factory_hello.face.json",
            render_profile="fast_lipsync",
            accessories=accessories,
        )

        job = manifest["jobs"][0]

        self.assertEqual(manifest["defaults"]["render_angles"], "portrait")
        self.assertEqual(job["category"], "torso_back")
        self.assertEqual(job["render_angles"], "front,side,back,portrait")

    def test_output_lock_prevents_same_id_concurrent_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_dir = Path(tmp) / "locks"
            lock_path = output_lock_path(lock_dir, "Auto Bowtie Anchor 002")

            self.assertEqual(lock_path.name, "auto-bowtie-anchor-002.lock")
            with acquire_output_lock(lock_path, "Auto Bowtie Anchor 002"):
                with self.assertRaises(OutputLockError):
                    with acquire_output_lock(lock_path, "Auto Bowtie Anchor 002"):
                        pass

            with acquire_output_lock(lock_path, "Auto Bowtie Anchor 002"):
                self.assertTrue(lock_path.exists())

    def test_main_exits_before_generation_when_same_id_is_locked(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = output_lock_path(Path(tmp), "locked-person")
            with acquire_output_lock(lock_path, "locked-person"):
                with mock.patch.object(
                    sys,
                    "argv",
                    [
                        "create_person_now.py",
                        "--id",
                        "locked-person",
                        "--lock-dir",
                        tmp,
                        "--dry-run",
                    ],
                ):
                    with mock.patch("scripts.create_person_now.create_person") as create_person:
                        with self.assertRaises(SystemExit) as raised:
                            main()

            self.assertEqual(raised.exception.code, 75)
            create_person.assert_not_called()


if __name__ == "__main__":
    unittest.main()
