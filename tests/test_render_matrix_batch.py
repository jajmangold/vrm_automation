import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.render_matrix_batch import (
    ROOT as RENDER_ROOT,
    build_finalize_command,
    cache_paths_for_request,
    copy_output_path,
    dedupe_requests,
    expand_deduped_batch_result,
    materialize_cached_request,
    render_dedupe_key,
    resolve_optimization_profile,
    run_checked,
    store_render_cache,
    write_report,
)


class RenderMatrixBatchTests(unittest.TestCase):
    def test_run_checked_returns_timing_report(self):
        with mock.patch("scripts.render_matrix_batch.subprocess.run") as run:
            run.return_value.returncode = 0

            result = run_checked(["python3", "--version"])

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["command"], ["python3", "--version"])
        self.assertIn("elapsed_seconds", result)

    def test_run_checked_exits_on_failure(self):
        with mock.patch("scripts.render_matrix_batch.subprocess.run") as run:
            run.return_value.returncode = 7

            with self.assertRaises(SystemExit) as context:
                run_checked(["bad"])

        self.assertEqual(context.exception.code, 7)

    def test_write_report_persists_stage_shape(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "report.json"
            report = {
                "status": "ok",
                "stages": [
                    {"name": "blender_manifest", "status": "ok", "elapsed_seconds": 1.2},
                    {"name": "finalize", "status": "ok", "elapsed_seconds": 0.3},
                ],
            }

            write_report(path, report)

            written = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual([stage["name"] for stage in written["stages"]], ["blender_manifest", "finalize"])

    def test_build_finalize_command_includes_optimization_profile(self):
        command = build_finalize_command(
            Path("results/batch.json"),
            Path("outputs/batch/gallery.html"),
            Path("results/finalize.json"),
            texture_size=512,
            optimization_profile="rough_preview",
            export_godot=True,
            godot_url="http://godot-viewer:8790",
        )

        self.assertEqual(command[:2], ["python3", "scripts/finalize_batch.py"])
        self.assertIn("--optimization-profile", command)
        self.assertIn("rough_preview", command)
        self.assertIn("--export-godot", command)
        self.assertIn("--godot-url", command)
        self.assertIn("http://godot-viewer:8790", command)

    def test_build_finalize_command_can_defer_review_assets(self):
        command = build_finalize_command(
            Path("results/batch.json"),
            Path("outputs/batch/gallery.html"),
            Path("results/finalize.json"),
            texture_size=512,
            optimization_profile="standard",
            export_godot=False,
            build_review_assets=False,
        )

        self.assertIn("--skip-gallery", command)
        self.assertIn("--skip-contact-sheet", command)

    def test_resolve_optimization_profile_uses_rough_preview_for_rough_lipsync(self):
        self.assertEqual(
            resolve_optimization_profile(
                "auto",
                [{"render_profile": "rough_lipsync"}, {"render_profile": "control_lipsync"}],
            ),
            "rough_preview",
        )
        self.assertEqual(resolve_optimization_profile("auto", [{"render_profile": "fast_lipsync"}]), "standard")
        self.assertEqual(resolve_optimization_profile("standard", [{"render_profile": "rough_lipsync"}]), "standard")

    def test_dedupe_requests_keeps_unique_specs_and_aliases_repeats(self):
        requests = [
            {"id": "person-001", "name": "One", "base": "female", "accessory": "bowtie", "animation": "talk_idle"},
            {"id": "person-002", "name": "Two", "base": "female", "accessory": "bowtie", "animation": "talk_idle"},
            {"id": "person-003", "name": "Three", "base": "male", "accessory": "bowtie", "animation": "talk_idle"},
        ]

        unique, aliases = dedupe_requests(requests)

        self.assertEqual([request["id"] for request in unique], ["person-001", "person-003"])
        self.assertEqual(aliases, {"person-002": "person-001"})

    def test_dedupe_requests_ignores_dialogue_metadata_when_timeline_matches(self):
        requests = [
            {
                "id": "person-001",
                "base": "female",
                "accessory": "bowtie",
                "animation": "talk_idle",
                "text": "Line one.",
                "audio_cache_key": "line-one",
                "lipsync_timeline": "outputs/lipsync/cache/shared.face.json",
            },
            {
                "id": "person-002",
                "base": "female",
                "accessory": "bowtie",
                "animation": "talk_idle",
                "text": "Different display text.",
                "audio_cache_key": "line-two",
                "lipsync_timeline": "outputs/lipsync/cache/shared.face.json",
            },
        ]

        unique, aliases = dedupe_requests(requests)

        self.assertEqual([request["id"] for request in unique], ["person-001"])
        self.assertEqual(aliases, {"person-002": "person-001"})

    def test_expand_deduped_batch_result_copies_outputs_and_marks_duplicate_jobs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            result_path = root / "results/batch.json"
            source_glb = root / "outputs/batch/person-001.glb"
            source_report = root / "results/batch/person-001_animation.json"
            source_glb.parent.mkdir(parents=True)
            source_report.parent.mkdir(parents=True)
            source_glb.write_bytes(b"glb")
            source_report.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "output_glb": "/workspace/outputs/batch/person-001.glb",
                        "optimized_glb": "/workspace/outputs/batch_optimized/person-001.glb",
                    }
                ),
                encoding="utf-8",
            )
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "jobs": [
                            {
                                "id": "person-001",
                                "status": "ok",
                                "environment": {
                                    "OUTPUT_GLB": "/workspace/outputs/batch/person-001.glb",
                                    "ANIMATION_REPORT_JSON": "/workspace/results/batch/person-001_animation.json",
                                },
                                "metadata": {"display_name": "One", "tags": []},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            requests = [
                {"id": "person-001", "name": "One"},
                {"id": "person-002", "name": "Two"},
            ]

            expanded = expand_deduped_batch_result(
                result_path,
                requests,
                {"person-002": "person-001"},
                root=root,
            )

            copied_report = root / "results/batch/person-002_animation.json"
            copied_glb = root / "outputs/batch/person-002.glb"
            copied_report_exists = copied_report.exists()
            copied_glb_exists = copied_glb.exists()
            copied_report_text = copied_report.read_text(encoding="utf-8")

        self.assertEqual(expanded["render_dedupe"]["source_job_count"], 1)
        self.assertEqual(expanded["render_dedupe"]["materialized_duplicate_count"], 1)
        self.assertEqual([job["id"] for job in expanded["jobs"]], ["person-001", "person-002"])
        self.assertEqual(expanded["jobs"][1]["render_dedup"]["source_job_id"], "person-001")
        self.assertEqual(expanded["jobs"][1]["metadata"]["display_name"], "Two")
        self.assertTrue(copied_report_exists)
        self.assertTrue(copied_glb_exists)
        self.assertIn("person-002.glb", copied_report_text)

    def test_copy_output_path_hardlinks_files_when_possible(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "outputs/batch/person-001.glb"
            target = root / "outputs/batch/person-002.glb"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"shared glb")

            result = copy_output_path(
                "/workspace/outputs/batch/person-001.glb",
                "/workspace/outputs/batch/person-002.glb",
                root=root,
            )

            target_exists = target.exists()
            same_file = source.samefile(target) if target_exists else False

        self.assertEqual(result["status"], "linked")
        self.assertTrue(target_exists)
        self.assertTrue(same_file)

    def test_copy_output_path_hardlinks_directory_files_when_possible(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "outputs/batch/person-001_pose_renders"
            target = root / "outputs/batch/person-002_pose_renders"
            source.mkdir(parents=True)
            source_png = source / "pose_portrait_0001.png"
            source_png.write_bytes(b"png")

            result = copy_output_path(
                "/workspace/outputs/batch/person-001_pose_renders",
                "/workspace/outputs/batch/person-002_pose_renders",
                root=root,
            )

            target_png = target / "pose_portrait_0001.png"
            target_exists = target_png.exists()
            same_file = source_png.samefile(target_png) if target_exists else False

        self.assertEqual(result["status"], "linked-dir")
        self.assertTrue(target_exists)
        self.assertTrue(same_file)

    def test_render_cache_stores_and_materializes_request_outputs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            request = {"id": "person-001", "name": "One", "base": "female", "accessory": "bowtie"}
            glb = root / "outputs/batch/person-001.glb"
            render_dir = root / "outputs/batch/person-001_pose_renders"
            report = root / "results/batch/person-001_animation.json"
            glb.parent.mkdir(parents=True)
            render_dir.mkdir(parents=True)
            report.parent.mkdir(parents=True)
            glb.write_bytes(b"glb")
            (render_dir / "pose_portrait_0001.png").write_bytes(b"png")
            report.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "output_glb": "/workspace/outputs/batch/person-001.glb",
                        "pose_renders": ["/workspace/outputs/batch/person-001_pose_renders/pose_portrait_0001.png"],
                    }
                ),
                encoding="utf-8",
            )
            job = {
                "id": "person-001",
                "status": "ok",
                "environment": {
                    "OUTPUT_GLB": "/workspace/outputs/batch/person-001.glb",
                    "RENDER_DIR": "/workspace/outputs/batch/person-001_pose_renders",
                    "ANIMATION_REPORT_JSON": "/workspace/results/batch/person-001_animation.json",
                },
                "metadata": {"display_name": "One", "tags": []},
            }

            stored = store_render_cache(request, job, root=root)
            paths = cache_paths_for_request(request, root=root)
            cached = materialize_cached_request(
                {**request, "id": "person-002", "name": "Two"},
                paths,
                root=root,
            )
            cached_glb = root / "outputs/batch/person-002.glb"
            cached_render = root / "outputs/batch/person-002_pose_renders/pose_portrait_0001.png"
            cached_report = root / "results/batch/person-002_animation.json"
            cached_glb_exists = cached_glb.exists()
            cached_render_exists = cached_render.exists()
            cached_report_text = cached_report.read_text(encoding="utf-8")

        self.assertEqual(stored["status"], "stored")
        self.assertEqual(job["render_cache"], {"status": "stored", "key": paths["key"]})
        self.assertEqual(cached["render_cache"]["status"], "hit")
        self.assertEqual(cached["metadata"]["display_name"], "Two")
        self.assertTrue(cached_glb_exists)
        self.assertTrue(cached_render_exists)
        self.assertIn("person-002.glb", cached_report_text)
        self.assertIn("person-002_pose_renders", cached_report_text)

    def test_render_cache_key_includes_profile_render_defaults(self):
        key_text = render_dedupe_key(
            {
                "id": "person-001",
                "name": "One",
                "base": "female",
                "accessory": "bowtie",
                "render_profile": "thumbnail_lipsync",
                "lipsync_timeline": "outputs/lipsync/cache/demo.face.json",
            }
        )

        self.assertIn('"render_compact_arms":"1"', key_text)
        self.assertIn('"render_pose_frames":"1"', key_text)


if __name__ == "__main__":
    unittest.main()
