import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class GodotViewerScaffoldTests(unittest.TestCase):
    def test_project_files_exist(self):
        self.assertTrue((ROOT / "godot_viewer/project.godot").exists())
        self.assertTrue((ROOT / "godot_viewer/scenes/Main.tscn").exists())
        self.assertTrue((ROOT / "godot_viewer/scripts/control_api.gd").exists())

    def test_control_api_routes_are_declared(self):
        source = (ROOT / "godot_viewer/scripts/control_api.gd").read_text(encoding="utf-8")
        for route in (
            "/health",
            "/assets",
            "/load",
            "/animation",
            "/expression",
            "/expression-preset",
            "/viseme",
            "/speak",
            "/face-profile",
            "/lipsync",
            "/validate-lipsync-batch",
            "/lipsync-status",
            "/camera",
            "/render",
            "/reload-assets",
            "/export-game-asset",
            "/export-all-game-assets",
        ):
            self.assertIn(route, source)
        self.assertIn("GLTFDocument.new()", source)
        self.assertIn("referenced-glb", source)
        self.assertIn("res://game_assets/glb/", source)
        self.assertIn("_link_or_copy_glb", source)
        self.assertIn("OS.execute(\"ln\"", source)
        self.assertIn('"glb_materialization": materialization.get("status", "")', source)
        self.assertIn("skip_existing", source)
        self.assertIn("_game_asset_is_current", source)
        self.assertIn("FileAccess.get_modified_time", source)
        self.assertIn("FileAccess.get_size", source)
        self.assertIn('"skipped": skipped', source)
        self.assertIn('payload.get("asset_ids", [])', source)
        self.assertIn('payload.get("scoped", false)', source)
        self.assertIn("_load_assets_from_batch(batch_result, {})", source)
        self.assertIn("allowed_asset_ids", source)
        self.assertIn("DisplayServer.get_name()", source)
        self.assertIn("viewport texture unavailable", source)
        self.assertIn("_set_viseme", source)
        self.assertIn("viseme_plan", source)
        self.assertIn("_load_lipsync_timeline", source)
        self.assertIn("_validate_lipsync_batch", source)
        self.assertIn("_validate_lipsync_asset", source)
        self.assertIn("_load_character_from_glb", source)
        self.assertIn('payload.get("glb", "")', source)
        self.assertIn("_lipsync_playback_status", source)
        self.assertIn("face_timeline", source)
        self.assertIn('"lipsync": _lipsync_playback_status()', source)
        self.assertIn("active_viseme", source)
        self.assertIn("active_source_phoneme", source)
        self.assertIn("active_source_index", source)
        self.assertIn("_read_animation_report", source)
        self.assertIn("_asset_optimization_summary", source)
        self.assertIn("optimized_glb", source)
        self.assertIn("asset_optimization", source)
        self.assertIn("optimized_bytes", source)
        self.assertIn("lipsync_timeline", source)
        self.assertIn('metadata/lipsync_timeline', source)
        self.assertIn("lipsync_summary", source)
        self.assertIn("source_event_count", source)
        self.assertIn("source_phoneme_count", source)
        self.assertIn("source_unique_phonemes", source)
        self.assertIn('metadata/lipsync_source', source)
        self.assertIn('metadata/lipsync_source_event_count', source)
        self.assertIn('metadata/lipsync_cue_count', source)
        self.assertIn('metadata/lipsync_duration', source)
        self.assertIn('metadata/lipsync_visemes', source)
        self.assertIn("GODOT_BATCH_RESULT_PATHS", source)
        self.assertIn("batch_person_factory_now_latest.json", source)
        self.assertIn("person_factory_all_latest.json", source)
        self.assertLess(
            source.index("person_factory_all_latest.json"),
            source.index("batch_person_factory_in_blender_latest.json"),
        )
        self.assertIn('job.get("lipsync_timeline_override", "")', source)
        self.assertIn('"animations": _animation_names(current_character) if current_character else []', source)
        self.assertIn('"current_glb": current_glb_path', source)

    def test_control_api_uses_exact_mouth_viseme_matching(self):
        source = (ROOT / "godot_viewer/scripts/control_api.gd").read_text(encoding="utf-8")

        self.assertIn("_shape_matches_key", source)
        self.assertIn('["mth_a", "mth_i", "mth_u", "mth_e", "mth_o"]', source)
        self.assertIn('normalized.ends_with("_" + normalized_key)', source)


if __name__ == "__main__":
    unittest.main()
