import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_manifest_in_blender import (
    blender_job_argv,
    cache_path_for_model,
    cached_environment,
    should_cache_model,
    temporary_environment,
)


class RunManifestInBlenderTests(unittest.TestCase):
    def test_blender_job_argv_uses_planned_paths(self):
        env = {
            "INPUT_MODEL": "/workspace/input/base.vrm",
            "ANIMATION_REPORT_JSON": "/workspace/results/person.json",
            "OUTPUT_BLEND": "/workspace/outputs/person.blend",
            "OUTPUT_GLB": "/workspace/outputs/person.glb",
        }

        self.assertEqual(
            blender_job_argv(env),
            [
                "blender",
                "--",
                "/workspace/input/base.vrm",
                "/workspace/results/person.json",
                "/workspace/outputs/person.blend",
                "/workspace/outputs/person.glb",
            ],
        )

    def test_temporary_environment_restores_values(self):
        import os

        os.environ["PERSON_FACTORY_TEST"] = "before"
        with temporary_environment({"PERSON_FACTORY_TEST": "during", "PERSON_FACTORY_NEW": "1"}):
            self.assertEqual(os.environ["PERSON_FACTORY_TEST"], "during")
            self.assertEqual(os.environ["PERSON_FACTORY_NEW"], "1")

        self.assertEqual(os.environ["PERSON_FACTORY_TEST"], "before")
        self.assertNotIn("PERSON_FACTORY_NEW", os.environ)

    def test_cache_path_is_stable_blend_path(self):
        path = cache_path_for_model("/workspace/input/base_models/model.vrm")

        self.assertTrue(path.startswith("/workspace/cache/base_scenes/model_"))
        self.assertTrue(path.endswith(".blend"))
        self.assertEqual(path, cache_path_for_model("/workspace/input/base_models/model.vrm"))

    def test_should_cache_imported_model_formats_only(self):
        self.assertTrue(should_cache_model("/workspace/input/model.vrm"))
        self.assertTrue(should_cache_model("/workspace/input/model.glb"))
        self.assertFalse(should_cache_model("/workspace/cache/model.blend"))

    def test_cached_environment_rewrites_input_model(self):
        env = {"INPUT_MODEL": "/workspace/input/base.vrm", "OUTPUT_GLB": "/workspace/out.glb"}
        cached = cached_environment(env, {"/workspace/input/base.vrm": "/workspace/cache/base.blend"})

        self.assertEqual(cached["INPUT_MODEL"], "/workspace/cache/base.blend")
        self.assertEqual(cached["BASE_SCENE_CACHE_SOURCE"], "/workspace/input/base.vrm")
        self.assertEqual(env["INPUT_MODEL"], "/workspace/input/base.vrm")

    def test_animate_smoke_writes_face_profile(self):
        source = (ROOT / "scripts/animate_smoke.py").read_text(encoding="utf-8")

        self.assertIn("build_face_profile", source)
        self.assertIn('"face_profile"', source)

    def test_animate_smoke_can_bake_lipsync_timeline(self):
        source = (ROOT / "scripts/animate_smoke.py").read_text(encoding="utf-8")
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("LIPSYNC_TIMELINE_JSON", compose)
        self.assertIn("apply_lipsync_timeline", source)
        self.assertIn('"lipsync_animation"', source)

    def test_animate_smoke_supports_facial_presets(self):
        source = (ROOT / "scripts/animate_smoke.py").read_text(encoding="utf-8")
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("FACIAL_PRESET", compose)
        self.assertIn("plan_facial_animation", source)
        self.assertIn('"expression_animation"', source)

    def test_animate_smoke_portrait_camera_tracks_head_per_frame(self):
        source = (ROOT / "scripts/animate_smoke.py").read_text(encoding="utf-8")

        self.assertIn("def head_focus_point", source)
        self.assertIn('if angle == "portrait":', source)
        self.assertIn("head_focus_point()", source)
        self.assertIn("scene.frame_set(frame)", source)
        self.assertIn("bpy.context.view_layer.update()", source)
        self.assertIn("position_camera(angle)", source)

    def test_animate_smoke_passes_surface_to_fit_check(self):
        source = (ROOT / "scripts/animate_smoke.py").read_text(encoding="utf-8")

        self.assertIn("outfit_fit_check(", source)
        self.assertIn('surface=profile.get("surface", "front")', source)

    def test_animate_smoke_reports_internal_timings(self):
        source = (ROOT / "scripts/animate_smoke.py").read_text(encoding="utf-8")

        self.assertIn('"timings"', source)
        self.assertIn('"import_seconds"', source)
        self.assertIn('"animation_seconds"', source)
        self.assertIn('"outfit_seconds"', source)
        self.assertIn('"pose_render_seconds"', source)
        self.assertIn('"export_seconds"', source)
        self.assertIn('"total_seconds"', source)


if __name__ == "__main__":
    unittest.main()
