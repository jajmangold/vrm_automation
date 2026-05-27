import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_cached_lipsync_batch import (
    batch_paths,
    build_commands,
    resolve_optimization_profile,
    run_pipeline,
    stage_timing_summary,
)


class RunCachedLipSyncBatchTests(unittest.TestCase):
    def test_batch_paths_are_stable(self):
        paths = batch_paths("auto-lip-020")

        self.assertEqual(paths["requests"], Path("config/person_factory.auto-lip-020.requests.json"))
        self.assertEqual(paths["manifest"], Path("config/person_factory.auto-lip-020.json"))
        self.assertEqual(paths["result"], Path("results/batch_person_factory_auto_lip_020_latest.json"))
        self.assertEqual(paths["gallery"], Path("outputs/batch/person_factory_auto-lip-020.html"))
        self.assertEqual(paths["promotion"], Path("results/promote_batch_auto_lip_020_latest.json"))
        self.assertEqual(paths["validation"], Path("results/godot_lipsync_validation_auto_lip_020_latest.json"))
        self.assertEqual(paths["report"], Path("results/run_cached_lipsync_batch_auto_lip_020.json"))

    def test_build_commands_compose_generation_render_validation_and_gallery_refresh(self):
        commands = build_commands(
            batch_id="auto-lip-020",
            count=4,
            accessories="aviator,pirate",
            bases="female,male",
            animations="talk_idle,present_explain",
            text="Cached line.",
            audio_cache_key="abc123",
            lipsync_timeline="outputs/lipsync/cache/abc123.face.json",
            texture_size=768,
            render_profile="fast_lipsync",
            optimization_profile="rough_preview",
        )

        self.assertEqual(commands["generate"][0:2], ["python3", "scripts/build_cached_lipsync_requests.py"])
        self.assertIn("--batch-id", commands["generate"])
        self.assertIn("auto-lip-020", commands["generate"])
        self.assertEqual(commands["render"][0:2], ["python3", "scripts/render_matrix_batch.py"])
        self.assertIn("config/person_factory.auto-lip-020.requests.json", commands["render"])
        self.assertIn("results/finalize_person_factory_auto_lip_020_latest.json", commands["render"])
        self.assertIn("--optimization-profile", commands["render"])
        self.assertIn("rough_preview", commands["render"])
        self.assertIn("--godot-url", commands["render"])
        self.assertIn("http://127.0.0.1:8790", commands["render"])
        self.assertIn("--skip-finalize-review-assets", commands["render"])
        self.assertEqual(commands["validate"][0:2], ["python3", "scripts/validate_godot_lipsync.py"])
        self.assertIn("--id-prefix", commands["validate"])
        self.assertIn("auto-lip-020-", commands["validate"])
        self.assertIn("--batch-result", commands["validate"])
        self.assertIn("results/batch_person_factory_auto_lip_020_latest.json", commands["validate"])
        self.assertIn("--control-url", commands["validate"])
        self.assertIn("http://127.0.0.1:8790", commands["validate"])
        self.assertEqual(commands["batch_gallery"][0:2], ["python3", "scripts/build_batch_gallery.py"])
        self.assertIn("results/batch_person_factory_auto_lip_020_latest.json", commands["batch_gallery"])
        self.assertIn("outputs/batch/person_factory_auto-lip-020.html", commands["batch_gallery"])
        self.assertIn("--godot-lipsync-validation", commands["batch_gallery"])
        self.assertIn("results/godot_lipsync_validation_auto_lip_020_latest.json", commands["batch_gallery"])
        self.assertIn("--detail-mode", commands["batch_gallery"])
        self.assertIn("full", commands["batch_gallery"])
        self.assertEqual(commands["combined"][0:2], ["python3", "scripts/build_combined_gallery.py"])
        self.assertEqual(commands["contact"][0:2], ["python3", "scripts/build_pose_contact_sheet.py"])

    def test_build_commands_can_use_compact_batch_gallery_details(self):
        commands = build_commands(
            batch_id="auto-lip-020",
            count=768,
            accessories="aviator,pirate",
            bases="female,male",
            animations="talk_idle,present_explain",
            text="Cached line.",
            audio_cache_key="abc123",
            lipsync_timeline="outputs/lipsync/cache/abc123.face.json",
            gallery_detail_mode="compact",
        )

        detail_index = commands["batch_gallery"].index("--detail-mode")
        self.assertEqual(commands["batch_gallery"][detail_index + 1], "compact")

    def test_build_commands_can_add_promote_stage(self):
        commands = build_commands(
            batch_id="auto-lip-020",
            count=4,
            accessories="aviator,pirate",
            bases="female,male",
            animations="talk_idle,present_explain",
            text="Cached line.",
            audio_cache_key="abc123",
            lipsync_timeline="outputs/lipsync/cache/abc123.face.json",
            texture_size=768,
            render_profile="control_lipsync",
            promote_after=True,
            two_pass_promote=True,
            godot_url="http://godot-viewer:8790",
        )

        self.assertEqual(commands["promote"][0:2], ["python3", "scripts/promote_batch_assets.py"])
        self.assertIn("results/batch_person_factory_auto_lip_020_latest.json", commands["promote"])
        self.assertIn("--gallery", commands["promote"])
        self.assertIn("outputs/batch/person_factory_auto-lip-020.html", commands["promote"])
        self.assertIn("--summary-json", commands["promote"])
        self.assertIn("results/promote_batch_auto_lip_020_latest.json", commands["promote"])
        self.assertIn("--texture-size", commands["promote"])
        self.assertIn("768", commands["promote"])
        self.assertIn("--godot-url", commands["promote"])
        self.assertIn("http://godot-viewer:8790", commands["promote"])
        self.assertNotIn("--skip-godot-export", commands["promote"])
        self.assertIn("--skip-combined", commands["promote"])

    def test_promote_after_defaults_to_single_standard_render_pass(self):
        commands = build_commands(
            batch_id="auto-lip-020",
            count=4,
            accessories="aviator,pirate",
            bases="female,male",
            animations="talk_idle,present_explain",
            text="Cached line.",
            audio_cache_key="abc123",
            lipsync_timeline="outputs/lipsync/cache/abc123.face.json",
            texture_size=768,
            render_profile="control_lipsync",
            promote_after=True,
            godot_url="http://godot-viewer:8790",
        )

        self.assertNotIn("promote", commands)
        self.assertIn("--optimization-profile", commands["render"])
        profile = commands["render"][commands["render"].index("--optimization-profile") + 1]
        self.assertEqual(profile, "standard")
        self.assertIn("--godot-url", commands["render"])
        self.assertIn("http://godot-viewer:8790", commands["render"])

    def test_build_commands_can_skip_child_godot_export(self):
        commands = build_commands(
            batch_id="auto-lip-030",
            count=4,
            accessories="aviator",
            bases="female",
            animations="talk_idle",
            text="Cached line.",
            audio_cache_key="abc123",
            lipsync_timeline="outputs/lipsync/cache/abc123.face.json",
            texture_size=768,
            render_profile="control_lipsync",
            promote_after=True,
            skip_godot_export=True,
        )

        self.assertIn("--skip-godot-export", commands["render"])
        self.assertIn("--godot-url", commands["render"])

    def test_build_commands_can_route_validation_to_multiple_control_urls(self):
        commands = build_commands(
            batch_id="auto-lip-031",
            count=4,
            accessories="aviator",
            bases="female",
            animations="talk_idle",
            text="Cached line.",
            audio_cache_key="abc123",
            lipsync_timeline="outputs/lipsync/cache/abc123.face.json",
            godot_url="http://godot-primary:8790",
            validation_urls="http://godot-a:8790,http://godot-b:8790",
        )

        self.assertIn("--godot-url", commands["render"])
        self.assertIn("http://godot-primary:8790", commands["render"])
        self.assertNotIn("http://godot-a:8790,http://godot-b:8790", commands["render"])
        self.assertIn("--control-urls", commands["validate"])
        self.assertIn("http://godot-a:8790,http://godot-b:8790", commands["validate"])
        self.assertNotIn("--control-url", commands["validate"])

    def test_build_commands_can_pass_multiple_cache_lines_to_generation(self):
        cache_lines = [
            {"text": "Line one.", "audio_cache_key": "one", "lipsync_timeline": "outputs/lipsync/cache/one.face.json"},
            {"text": "Line two.", "audio_cache_key": "two", "lipsync_timeline": "outputs/lipsync/cache/two.face.json"},
        ]

        commands = build_commands(
            batch_id="auto-lip-026",
            count=4,
            accessories="aviator",
            bases="female",
            animations="talk_idle",
            text="Fallback.",
            audio_cache_key="fallback",
            lipsync_timeline="outputs/lipsync/cache/fallback.face.json",
            cache_lines=cache_lines,
        )

        self.assertIn("--cache-lines-json", commands["generate"])
        encoded = commands["generate"][commands["generate"].index("--cache-lines-json") + 1]
        self.assertEqual(json.loads(encoded), cache_lines)

    def test_rough_lipsync_defaults_to_rough_preview_optimization(self):
        commands = build_commands(
            batch_id="rough-fast",
            count=1,
            accessories="necklace",
            bases="female",
            animations="talk_idle",
            text="Cached line.",
            audio_cache_key="abc123",
            lipsync_timeline="outputs/lipsync/cache/abc123.face.json",
            render_profile="rough_lipsync",
        )

        self.assertEqual(resolve_optimization_profile("auto", "rough_lipsync"), "rough_preview")
        self.assertEqual(resolve_optimization_profile("auto", "thumbnail_lipsync"), "rough_preview")
        self.assertEqual(resolve_optimization_profile("auto", "control_lipsync"), "rough_preview")
        self.assertIn("--optimization-profile", commands["render"])
        self.assertIn("rough_preview", commands["render"])

    def test_run_pipeline_dry_run_writes_report_without_running_commands(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            with mock.patch("scripts.run_cached_lipsync_batch.ROOT", root):
                report = run_pipeline(
                    batch_id="auto-lip-021",
                    count=2,
                    accessories="aviator",
                    bases="female",
                    animations="talk_idle",
                    text="Cached line.",
                    audio_cache_key="abc123",
                    lipsync_timeline="outputs/lipsync/cache/abc123.face.json",
                    dry_run=True,
                )

            report_path = root / "results/run_cached_lipsync_batch_auto_lip_021.json"
            written = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(report["status"], "dry-run")
        self.assertEqual(written["status"], "dry-run")
        self.assertEqual(written["batch_id"], "auto-lip-021")
        self.assertIn("generate", written["commands"])
        self.assertIn("urls", written)

    def test_run_pipeline_records_stage_timings(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            paths = batch_paths("auto-lip-023")
            (root / paths["requests"]).parent.mkdir(parents=True, exist_ok=True)
            (root / paths["summary"]).parent.mkdir(parents=True, exist_ok=True)
            (root / paths["combined_summary"]).parent.mkdir(parents=True, exist_ok=True)
            (root / paths["requests"]).write_text('{"requests":[]}', encoding="utf-8")
            (root / paths["summary"]).write_text('{"status":"ok"}', encoding="utf-8")
            (root / paths["validation"]).write_text('{"status":"ok"}', encoding="utf-8")
            (root / paths["combined_summary"]).write_text('{"jobs":[]}', encoding="utf-8")

            with (
                mock.patch("scripts.run_cached_lipsync_batch.ROOT", root),
                mock.patch("scripts.run_cached_lipsync_batch.subprocess.run") as run,
            ):
                run.return_value.returncode = 0
                report = run_pipeline(
                    batch_id="auto-lip-023",
                    count=2,
                    accessories="aviator",
                    bases="female",
                    animations="talk_idle",
                    text="Cached line.",
                    audio_cache_key="abc123",
                    lipsync_timeline="outputs/lipsync/cache/abc123.face.json",
                )

        self.assertEqual(report["status"], "ok")
        self.assertEqual([stage["name"] for stage in report["stages"]], ["generate", "render", "validate", "batch_gallery", "combined", "contact"])
        self.assertTrue(all(stage["status"] == "ok" for stage in report["stages"]))
        self.assertTrue(all("elapsed_seconds" in stage for stage in report["stages"]))
        self.assertEqual(report["stage_summary"]["stage_count"], 6)
        self.assertEqual(report["stage_summary"]["completed_stage_count"], 6)
        self.assertIn(report["stage_summary"]["slowest_stage"], {"generate", "render", "validate", "batch_gallery", "combined", "contact"})
        self.assertTrue(all("percent" in stage for stage in report["stage_summary"]["stages"]))
        self.assertIn("batch_gallery", report["urls"])

    def test_stage_timing_summary_identifies_slowest_stage(self):
        summary = stage_timing_summary(
            [
                {"name": "generate", "elapsed_seconds": 1.0, "status": "ok"},
                {"name": "render", "elapsed_seconds": 9.0, "status": "ok"},
                {"name": "validate", "elapsed_seconds": 0.5, "status": "ok"},
            ]
        )

        self.assertEqual(summary["stage_count"], 3)
        self.assertEqual(summary["completed_stage_count"], 3)
        self.assertEqual(summary["total_stage_seconds"], 10.5)
        self.assertEqual(summary["slowest_stage"], "render")
        self.assertEqual(summary["slowest_stage_seconds"], 9.0)
        self.assertEqual(summary["stages"][1]["percent"], 85.7)

    def test_run_pipeline_with_promote_after_runs_promote_before_validation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            paths = batch_paths("auto-lip-024")
            for key in ("requests", "summary", "promotion", "validation", "combined_summary"):
                (root / paths[key]).parent.mkdir(parents=True, exist_ok=True)
            (root / paths["requests"]).write_text('{"requests":[]}', encoding="utf-8")
            (root / paths["summary"]).write_text('{"status":"ok"}', encoding="utf-8")
            (root / paths["promotion"]).write_text('{"status":"ok","promoted_count":2}', encoding="utf-8")
            (root / paths["validation"]).write_text('{"status":"ok"}', encoding="utf-8")
            (root / paths["combined_summary"]).write_text('{"jobs":[]}', encoding="utf-8")

            with (
                mock.patch("scripts.run_cached_lipsync_batch.ROOT", root),
                mock.patch("scripts.run_cached_lipsync_batch.subprocess.run") as run,
            ):
                run.return_value.returncode = 0
                report = run_pipeline(
                    batch_id="auto-lip-024",
                    count=2,
                    accessories="aviator",
                    bases="female",
                    animations="talk_idle",
                    text="Cached line.",
                    audio_cache_key="abc123",
                    lipsync_timeline="outputs/lipsync/cache/abc123.face.json",
                    promote_after=True,
                    two_pass_promote=True,
                )

        self.assertEqual(report["status"], "ok")
        self.assertEqual([stage["name"] for stage in report["stages"]], ["generate", "render", "promote", "validate", "batch_gallery", "combined", "contact"])
        self.assertEqual(report["promotion"]["promoted_count"], 2)

    def test_run_pipeline_promote_after_single_pass_skips_promote_stage(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            paths = batch_paths("auto-lip-027")
            for key in ("requests", "summary", "validation", "combined_summary"):
                (root / paths[key]).parent.mkdir(parents=True, exist_ok=True)
            (root / paths["requests"]).write_text('{"requests":[]}', encoding="utf-8")
            (root / paths["summary"]).write_text('{"status":"ok"}', encoding="utf-8")
            (root / paths["validation"]).write_text('{"status":"ok"}', encoding="utf-8")
            (root / paths["combined_summary"]).write_text('{"jobs":[]}', encoding="utf-8")

            with (
                mock.patch("scripts.run_cached_lipsync_batch.ROOT", root),
                mock.patch("scripts.run_cached_lipsync_batch.subprocess.run") as run,
            ):
                run.return_value.returncode = 0
                report = run_pipeline(
                    batch_id="auto-lip-027",
                    count=2,
                    accessories="aviator",
                    bases="female",
                    animations="talk_idle",
                    text="Cached line.",
                    audio_cache_key="abc123",
                    lipsync_timeline="outputs/lipsync/cache/abc123.face.json",
                    promote_after=True,
                )

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["promotion_mode"], "single-pass-standard")
        self.assertEqual([stage["name"] for stage in report["stages"]], ["generate", "render", "validate", "batch_gallery", "combined", "contact"])
        self.assertEqual(report["promotion"], {})

    def test_run_pipeline_can_skip_combined_refresh_for_chunk_children(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            paths = batch_paths("auto-lip-028")
            for key in ("requests", "summary", "validation"):
                (root / paths[key]).parent.mkdir(parents=True, exist_ok=True)
            (root / paths["requests"]).write_text('{"requests":[]}', encoding="utf-8")
            (root / paths["summary"]).write_text('{"status":"ok"}', encoding="utf-8")
            (root / paths["validation"]).write_text('{"status":"ok"}', encoding="utf-8")

            with (
                mock.patch("scripts.run_cached_lipsync_batch.ROOT", root),
                mock.patch("scripts.run_cached_lipsync_batch.subprocess.run") as run,
            ):
                run.return_value.returncode = 0
                report = run_pipeline(
                    batch_id="auto-lip-028",
                    count=2,
                    accessories="aviator",
                    bases="female",
                    animations="talk_idle",
                    text="Cached line.",
                    audio_cache_key="abc123",
                    lipsync_timeline="outputs/lipsync/cache/abc123.face.json",
                    publish_combined=False,
                )

        self.assertEqual(report["status"], "ok")
        self.assertFalse(report["publish_combined"])
        self.assertEqual([stage["name"] for stage in report["stages"]], ["generate", "render", "validate", "batch_gallery"])
        self.assertEqual(report["combined"], {})

    def test_cli_supports_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/run_cached_lipsync_batch.py"),
                    "--batch-id",
                    "auto-lip-022",
                    "--count",
                    "1",
                    "--accessories",
                    "aviator",
                    "--bases",
                    "female",
                    "--animations",
                    "talk_idle",
                    "--text",
                    "Cached line.",
                    "--audio-cache-key",
                    "abc123",
                    "--lipsync-timeline",
                    "outputs/lipsync/cache/abc123.face.json",
                    "--dry-run",
                ],
                cwd=tmp_dir,
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertIn('"status": "dry-run"', completed.stdout)

    def test_cli_supports_skip_combined_refresh_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/run_cached_lipsync_batch.py"),
                    "--batch-id",
                    "auto-lip-029",
                    "--count",
                    "1",
                    "--accessories",
                    "aviator",
                    "--bases",
                    "female",
                    "--animations",
                    "talk_idle",
                    "--text",
                    "Cached line.",
                    "--audio-cache-key",
                    "abc123",
                    "--lipsync-timeline",
                    "outputs/lipsync/cache/abc123.face.json",
                    "--skip-combined-refresh",
                    "--dry-run",
                ],
                cwd=tmp_dir,
                check=True,
                capture_output=True,
                text=True,
        )

        self.assertIn('"publish_combined": false', completed.stdout)
        self.assertIn('"--detail-mode",', completed.stdout)
        self.assertIn('"compact"', completed.stdout)

    def test_cli_supports_promote_after_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/run_cached_lipsync_batch.py"),
                    "--batch-id",
                    "auto-lip-025",
                    "--count",
                    "1",
                    "--accessories",
                    "aviator",
                    "--bases",
                    "female",
                    "--animations",
                    "talk_idle",
                    "--text",
                    "Cached line.",
                    "--audio-cache-key",
                    "abc123",
                    "--lipsync-timeline",
                    "outputs/lipsync/cache/abc123.face.json",
                    "--promote-after",
                    "--dry-run",
                ],
                cwd=tmp_dir,
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertIn('"promote_after": true', completed.stdout)
        self.assertIn('"promotion_mode": "single-pass-standard"', completed.stdout)
        self.assertIn('"--optimization-profile",', completed.stdout)
        self.assertIn('"standard"', completed.stdout)


if __name__ == "__main__":
    unittest.main()
