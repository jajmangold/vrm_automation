import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.person_factory_jobs import (
    JobStore,
    build_matrix_batch_render_jobs,
    build_matrix_cache_warm_jobs,
    build_matrix_warm_render_pipeline,
    build_text_person_command,
    cached_line_paths,
    line_cache_key,
    max_batch_jobs,
    max_chunked_matrix_jobs,
    matrix_cache_preflight_plan,
    normalize_matrix_job_requests,
    normalize_batch_job_requests,
    normalize_job_request,
    tail_lines,
)


class PersonFactoryJobsTests(unittest.TestCase):
    def test_normalize_job_request_defaults_to_fast_safe_preview(self):
        request = normalize_job_request({"text": "Hello from the browser."})

        self.assertTrue(request["id"].startswith("web-"))
        self.assertEqual(request["base"], "female")
        self.assertEqual(request["accessory"], "necklace")
        self.assertEqual(request["animation"], "talk_idle")
        self.assertEqual(request["render_profile"], "fast_lipsync")
        self.assertEqual(request["normalizer"], "local")
        self.assertTrue(request["dry_run"])
        self.assertFalse(request["render"])
        self.assertTrue(request["skip_godot_export"])

    def test_normalize_job_request_rejects_missing_text_and_bad_ids(self):
        with self.assertRaises(ValueError):
            normalize_job_request({})
        with self.assertRaises(ValueError):
            normalize_job_request({"text": "Hello", "id": "../bad"})

    def test_build_text_person_command_is_constrained_to_known_script(self):
        request = normalize_job_request(
            {
                "id": "web-test-001",
                "text": "Hello.",
                "name": "Web Test",
                "render": True,
                "dry_run": False,
                "reuse_audio": True,
                "reuse_lipsync": True,
            }
        )

        command = build_text_person_command(request)

        self.assertEqual(command[:3], ["python3", "scripts/create_talking_person_from_text.py", "Hello."])
        self.assertIn("--id", command)
        self.assertIn("web-test-001", command)
        self.assertIn("--render", command)
        self.assertIn("--reuse-audio", command)
        self.assertIn("--reuse-lipsync", command)
        self.assertIn("--normalizer", command)
        self.assertIn("local", command)
        self.assertIn("--skip-godot-export", command)
        self.assertNotIn("--dry-run", command)

    def test_build_text_person_command_includes_dry_run_by_default(self):
        command = build_text_person_command(normalize_job_request({"text": "Hello."}))

        self.assertIn("--dry-run", command)
        self.assertNotIn("--render", command)

    def test_job_store_persists_status_updates(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = JobStore(Path(tmp_dir) / "jobs.json")
            job = store.create_job({"id": "web-test-001", "text": "Hello."}, command=["python3", "--version"])
            store.update_job(job["id"], status="running", returncode=None)
            store.update_job(job["id"], status="ok", returncode=0)
            reloaded = JobStore(Path(tmp_dir) / "jobs.json")

            data = reloaded.get_job("web-test-001")

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["returncode"], 0)
        self.assertEqual(data["command"], ["python3", "--version"])

    def test_job_store_reuses_cached_data_between_reads(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = JobStore(Path(tmp_dir) / "jobs.json")
            store.create_job({"id": "web-test-001", "text": "Hello."}, command=["python3", "--version"])

            first = store.list_jobs()
            store.path.write_text("not json", encoding="utf-8")
            second = store.list_jobs()

        self.assertEqual(first[0]["id"], "web-test-001")
        self.assertEqual(second[0]["id"], "web-test-001")

    def test_job_store_reload_picks_up_external_file_change_for_new_instance(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "jobs.json"
            store = JobStore(path)
            store.create_job({"id": "web-test-001", "text": "Hello."}, command=["python3", "--version"])
            path.write_text(
                json.dumps({"jobs": [{"id": "external", "status": "ok", "request": {}, "command": []}]}),
                encoding="utf-8",
            )

            reloaded = JobStore(path)
            jobs = reloaded.list_jobs()

        self.assertEqual([job["id"] for job in jobs], ["external"])

    def test_job_store_list_recent_jobs_avoids_full_deepcopy(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = JobStore(Path(tmp_dir) / "jobs.json")
            store.create_jobs(
                [
                    (
                        {
                            "id": f"job-{index}",
                            "text": "Hello.",
                            "payload": {"large": "x" * 1000},
                        },
                        ["python3", "--version"],
                    )
                    for index in range(10)
                ]
            )

            recent = store.list_recent_jobs(3)
            recent[0]["request"]["payload"]["large"] = "mutated"
            full = store.list_jobs()

        self.assertEqual([job["id"] for job in recent], ["job-7", "job-8", "job-9"])
        self.assertEqual(full[-3]["request"]["payload"]["large"], "x" * 1000)

    def test_job_store_uses_process_local_lock_and_atomic_replace(self):
        source = (ROOT / "scripts/person_factory_jobs.py").read_text(encoding="utf-8")

        self.assertIn("threading.RLock", source)
        self.assertIn("tmp_path.replace(self.path)", source)
        self.assertIn("_data_cache", source)
        self.assertIn("list_recent_jobs", source)

    def test_tail_lines_reads_last_lines(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log = Path(tmp_dir) / "job.log"
            log.write_text("\n".join(str(index) for index in range(10)), encoding="utf-8")

            self.assertEqual(tail_lines(log, count=3), ["7", "8", "9"])
            self.assertEqual(tail_lines(Path(tmp_dir) / "missing.log"), [])

    def test_normalize_batch_job_requests_splits_lines_and_assigns_ids(self):
        requests = normalize_batch_job_requests(
            {
                "id_prefix": "web-batch-test",
                "lines": "First line.\n\nSecond line.",
                "render": True,
                "dry_run": False,
            }
        )

        self.assertEqual([request["id"] for request in requests], ["web-batch-test-001", "web-batch-test-002"])
        self.assertEqual([request["text"] for request in requests], ["First line.", "Second line."])
        self.assertTrue(all(request["render"] for request in requests))
        self.assertTrue(all(request["skip_godot_export"] for request in requests))

    def test_normalize_batch_job_requests_limits_batch_size(self):
        with patch.dict(os.environ, {"PERSON_FACTORY_MAX_BATCH_JOBS": "3"}):
            with self.assertRaises(ValueError) as context:
                normalize_batch_job_requests({"lines": "\n".join(f"Line {index}" for index in range(4))})

        self.assertIn("limit is 3", str(context.exception))

    def test_max_batch_jobs_is_env_configurable(self):
        with patch.dict(os.environ, {"PERSON_FACTORY_MAX_BATCH_JOBS": "18"}):
            self.assertEqual(max_batch_jobs(), 18)
        with patch.dict(os.environ, {"PERSON_FACTORY_MAX_BATCH_JOBS": "0"}):
            self.assertEqual(max_batch_jobs(), 1)
        with patch.dict(os.environ, {"PERSON_FACTORY_MAX_BATCH_JOBS": "bad"}):
            self.assertEqual(max_batch_jobs(), 24)

    def test_max_chunked_matrix_jobs_is_env_configurable_and_not_below_batch_limit(self):
        with patch.dict(os.environ, {"PERSON_FACTORY_MAX_BATCH_JOBS": "24", "PERSON_FACTORY_MAX_CHUNKED_MATRIX_JOBS": "72"}):
            self.assertEqual(max_chunked_matrix_jobs(), 72)
        with patch.dict(os.environ, {"PERSON_FACTORY_MAX_BATCH_JOBS": "24", "PERSON_FACTORY_MAX_CHUNKED_MATRIX_JOBS": "12"}):
            self.assertEqual(max_chunked_matrix_jobs(), 24)
        with patch.dict(os.environ, {"PERSON_FACTORY_MAX_BATCH_JOBS": "24", "PERSON_FACTORY_MAX_CHUNKED_MATRIX_JOBS": "bad"}):
            self.assertEqual(max_chunked_matrix_jobs(), 768)

    def test_normalize_matrix_job_requests_expands_safe_combinations(self):
        requests = normalize_matrix_job_requests(
            {
                "id_prefix": "web-matrix-test",
                "lines": "First line.\nSecond line.",
                "bases": ["female"],
                "accessories": ["necklace-quaternius", "cowboy-hat-google"],
                "animations": ["talk_idle", "present_explain"],
                "render": True,
                "dry_run": False,
            }
        )

        self.assertEqual(len(requests), 8)
        self.assertEqual(requests[0]["id"], "web-matrix-test-001")
        self.assertEqual(requests[-1]["id"], "web-matrix-test-008")
        self.assertEqual({request["base"] for request in requests}, {"female"})
        self.assertEqual(
            {request["accessory"] for request in requests},
            {"necklace-quaternius", "cowboy-hat-google"},
        )
        self.assertEqual({request["animation"] for request in requests}, {"talk_idle", "present_explain"})
        self.assertTrue(all(request["render"] for request in requests))
        self.assertTrue(all(request["skip_godot_export"] for request in requests))

    def test_matrix_jobs_can_share_line_audio_and_lipsync_cache(self):
        requests = normalize_matrix_job_requests(
            {
                "id_prefix": "web-cache-test",
                "lines": "Shared line.",
                "bases": ["female"],
                "accessories": ["necklace-quaternius", "cowboy-hat-google"],
                "animations": ["talk_idle"],
                "cache_line_audio": True,
                "render": True,
                "dry_run": False,
            }
        )

        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0]["audio_wav"], requests[1]["audio_wav"])
        self.assertEqual(requests[0]["lipsync_timeline"], requests[1]["lipsync_timeline"])
        self.assertTrue(all(request["reuse_audio"] for request in requests))
        self.assertTrue(all(request["reuse_lipsync"] for request in requests))
        self.assertIn("outputs/speech/cache/", requests[0]["audio_wav"])
        self.assertIn("outputs/lipsync/cache/", requests[0]["lipsync_timeline"])
        self.assertEqual(requests[0]["audio_cache_key"], line_cache_key(requests[0]))

    def test_matrix_cache_preflight_groups_lines_and_detects_cache_hits(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payload = {
                "id_prefix": "web-cache-plan",
                "lines": "Already cached.\nNeeds prep.",
                "bases": ["female"],
                "accessories": ["necklace-quaternius", "cowboy-hat-google"],
                "animations": ["talk_idle"],
                "cache_line_audio": True,
                "render": True,
                "dry_run": False,
            }
            first_request = normalize_matrix_job_requests(payload)[0]
            first_key = first_request["audio_cache_key"]
            for relative in (
                cached_line_paths(first_key)["audio_wav"],
                cached_line_paths(first_key)["normalized_audio"],
                cached_line_paths(first_key)["rhubarb_json"],
                cached_line_paths(first_key)["lipsync_timeline"],
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"cached")

            plan = matrix_cache_preflight_plan(payload, root=root)

        self.assertEqual(plan["job_count"], 4)
        self.assertTrue(plan["cache_enabled"])
        self.assertEqual(plan["cache_group_count"], 2)
        self.assertEqual(plan["cache_reuse_jobs"], 2)
        self.assertEqual(plan["estimated_tts_jobs"], 1)
        self.assertEqual(plan["estimated_lipsync_jobs"], 1)
        by_text = {group["text"]: group for group in plan["cache_groups"]}
        self.assertEqual(by_text["Already cached."]["job_count"], 2)
        self.assertEqual(by_text["Already cached."]["audio_cache"], "hit")
        self.assertEqual(by_text["Already cached."]["lipsync_cache"], "hit")
        self.assertEqual(by_text["Needs prep."]["audio_cache"], "miss")
        self.assertEqual(by_text["Needs prep."]["lipsync_cache"], "miss")

    def test_matrix_cache_warm_jobs_skip_warm_groups_and_plan_missing_groups(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payload = {
                "id_prefix": "web-cache-plan",
                "lines": "Already cached.\nNeeds prep.",
                "bases": ["female"],
                "accessories": ["necklace-quaternius", "cowboy-hat-google"],
                "animations": ["talk_idle"],
                "cache_line_audio": True,
                "render": True,
                "dry_run": False,
            }
            first_request = normalize_matrix_job_requests(payload)[0]
            first_key = first_request["audio_cache_key"]
            for relative in cached_line_paths(first_key).values():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"cached")

            warm = build_matrix_cache_warm_jobs(payload, root=root, dry_run=True)

        self.assertEqual(warm["status"], "ok")
        self.assertEqual(warm["skipped_group_count"], 1)
        self.assertEqual(warm["warm_job_count"], 1)
        job = warm["warm_jobs"][0]
        self.assertIn("cache-warm", job["id"])
        self.assertEqual(job["request"]["text"], "Needs prep.")
        self.assertFalse(job["request"]["render"])
        self.assertTrue(job["request"]["dry_run"])
        self.assertTrue(job["request"]["reuse_audio"])
        self.assertTrue(job["request"]["reuse_lipsync"])
        self.assertIn("--audio-cache-key", job["command"])
        self.assertIn("--dry-run", job["command"])
        self.assertIn("outputs/lipsync/cache/", " ".join(job["command"]))

    def test_matrix_warm_render_pipeline_plans_warm_stage_before_render_stage(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payload = {
                "id_prefix": "web-warm-render",
                "lines": "Already cached.\nNeeds prep.",
                "bases": ["female"],
                "accessories": ["necklace-quaternius", "cowboy-hat-google"],
                "animations": ["talk_idle"],
                "cache_line_audio": True,
                "render": True,
                "dry_run": False,
            }
            first_request = normalize_matrix_job_requests(payload)[0]
            first_key = first_request["audio_cache_key"]
            for relative in cached_line_paths(first_key).values():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"cached")

            pipeline = build_matrix_warm_render_pipeline(payload, root=root)

        self.assertEqual(pipeline["status"], "ok")
        self.assertFalse(pipeline["dry_run"])
        self.assertEqual(pipeline["warm_job_count"], 1)
        self.assertEqual(pipeline["skipped_group_count"], 1)
        self.assertEqual(pipeline["render_job_count"], 4)
        self.assertEqual(pipeline["render_child_job_count"], 1)
        self.assertEqual(pipeline["planned_child_job_count"], 2)
        self.assertEqual(pipeline["stage_order"], ["warm-cache", "render-batch"])
        self.assertEqual(pipeline["validation_id_prefix"], "web-warm-render-")
        warm_job = pipeline["warm_jobs"][0]
        self.assertFalse(warm_job["request"]["render"])
        self.assertFalse(warm_job["request"]["dry_run"])
        self.assertIn("--reuse-lipsync", warm_job["command"])
        self.assertNotIn("--render", warm_job["command"])
        batch_job = pipeline["render_batch_job"]
        self.assertEqual(batch_job["request_count"], 4)
        self.assertEqual(batch_job["request"]["id"], "web-warm-render-render-batch")
        self.assertIn("scripts/render_matrix_batch.py", batch_job["command"])
        self.assertIn("--requests-json", batch_job["command"])
        self.assertIn("config/person_factory.web-warm-render.requests.json", batch_job["command"])
        self.assertIn("--skip-godot-export", batch_job["command"])
        self.assertTrue(all(job["request"]["render"] for job in pipeline["render_jobs"]))
        self.assertTrue(all(job["request"]["reuse_audio"] for job in pipeline["render_jobs"]))
        self.assertTrue(all(job["request"]["reuse_lipsync"] for job in pipeline["render_jobs"]))
        self.assertEqual(
            {job["request"]["audio_cache_key"] for job in pipeline["render_jobs"]},
            {group["audio_cache_key"] for group in pipeline["plan"]["cache_groups"]},
        )

    def test_matrix_warm_render_pipeline_can_use_legacy_per_item_render_jobs(self):
        pipeline = build_matrix_warm_render_pipeline(
            {
                "id_prefix": "web-legacy-render",
                "lines": "Line.",
                "bases": ["female"],
                "accessories": ["necklace-quaternius", "cowboy-hat-google"],
                "animations": ["talk_idle"],
                "cache_line_audio": True,
                "batch_render": False,
                "render": True,
                "dry_run": True,
            }
        )

        self.assertEqual(pipeline["stage_order"], ["warm-cache", "render-matrix"])
        self.assertEqual(pipeline["render_job_count"], 2)
        self.assertEqual(pipeline["render_child_job_count"], 2)
        self.assertEqual(pipeline["planned_child_job_count"], pipeline["warm_job_count"] + 2)
        self.assertIsNone(pipeline["render_batch_job"])
        self.assertEqual(pipeline["validation_id_prefix"], "web-legacy-render-")
        self.assertTrue(all("--render" in job["command"] for job in pipeline["render_jobs"]))

    def test_text_person_command_passes_cached_audio_and_lipsync_paths(self):
        request = normalize_job_request(
            {
                "id": "web-cache-test-001",
                "text": "Shared line.",
                "audio_wav": "outputs/speech/cache/abc123.wav",
                "audio_manifest": "results/musetalk/cache/abc123_audio.json",
                "normalized_audio": "outputs/speech/cache/abc123_clean.wav",
                "rhubarb_json": "results/rhubarb/cache/abc123_clean.json",
                "lipsync_timeline": "outputs/lipsync/cache/abc123.face.json",
                "reuse_audio": True,
                "reuse_lipsync": True,
            }
        )

        command = build_text_person_command(request)

        self.assertIn("--audio-wav", command)
        self.assertIn("outputs/speech/cache/abc123.wav", command)
        self.assertIn("--audio-manifest", command)
        self.assertIn("results/musetalk/cache/abc123_audio.json", command)
        self.assertIn("--normalized-audio", command)
        self.assertIn("outputs/speech/cache/abc123_clean.wav", command)
        self.assertIn("--rhubarb-json", command)
        self.assertIn("results/rhubarb/cache/abc123_clean.json", command)
        self.assertIn("--lipsync-timeline", command)
        self.assertIn("outputs/lipsync/cache/abc123.face.json", command)
        self.assertIn("--audio-cache-key", command)
        self.assertIn("abc123", command)
        self.assertIn("--reuse-audio", command)
        self.assertIn("--reuse-lipsync", command)

    def test_normalize_matrix_job_requests_limits_total_jobs(self):
        with patch.dict(os.environ, {"PERSON_FACTORY_MAX_BATCH_JOBS": "12"}):
            with self.assertRaises(ValueError) as context:
                normalize_matrix_job_requests(
                    {
                        "lines": "One.\nTwo.",
                        "bases": ["female", "male"],
                        "accessories": ["a", "b", "c", "d"],
                        "animations": ["talk_idle", "present_explain"],
                    }
                )

        self.assertIn("limit is 12", str(context.exception))

    def test_chunked_matrix_is_opt_in_for_larger_batches(self):
        payload = {
            "id_prefix": "chunked-matrix",
            "lines": "One.\nTwo.\nThree.",
            "bases": ["female", "male"],
            "accessories": ["a", "b", "c"],
            "animations": ["talk_idle", "present_explain"],
            "render": True,
            "dry_run": False,
        }
        with patch.dict(
            os.environ,
            {"PERSON_FACTORY_MAX_BATCH_JOBS": "24", "PERSON_FACTORY_MAX_CHUNKED_MATRIX_JOBS": "48"},
        ):
            with self.assertRaises(ValueError) as context:
                normalize_matrix_job_requests(payload)
            self.assertIn("limit is 24", str(context.exception))

            requests = normalize_matrix_job_requests({**payload, "chunked": True})

        self.assertEqual(len(requests), 36)
        self.assertEqual(requests[0]["id"], "chunked-matrix-001")
        self.assertEqual(requests[-1]["id"], "chunked-matrix-036")

    def test_chunked_matrix_respects_separate_total_limit(self):
        with patch.dict(
            os.environ,
            {"PERSON_FACTORY_MAX_BATCH_JOBS": "24", "PERSON_FACTORY_MAX_CHUNKED_MATRIX_JOBS": "30"},
        ):
            with self.assertRaises(ValueError) as context:
                normalize_matrix_job_requests(
                    {
                        "lines": "One.\nTwo.\nThree.",
                        "bases": ["female", "male"],
                        "accessories": ["a", "b", "c"],
                        "animations": ["talk_idle", "present_explain"],
                        "chunked": True,
                    }
                )

        self.assertIn("limit is 30", str(context.exception))

    def test_matrix_batch_render_jobs_split_chunked_requests_by_batch_limit(self):
        payload = {
            "id_prefix": "chunked-matrix",
            "lines": "One.\nTwo.\nThree.",
            "bases": ["female", "male"],
            "accessories": ["a", "b", "c"],
            "animations": ["talk_idle", "present_explain"],
            "chunked": True,
            "render": True,
            "dry_run": False,
        }
        with patch.dict(
            os.environ,
            {"PERSON_FACTORY_MAX_BATCH_JOBS": "24", "PERSON_FACTORY_MAX_CHUNKED_MATRIX_JOBS": "48"},
        ):
            requests = normalize_matrix_job_requests(payload)
            batch_jobs = build_matrix_batch_render_jobs(payload, requests, dry_run=False)

        self.assertEqual(len(batch_jobs), 2)
        self.assertEqual([job["request_count"] for job in batch_jobs], [24, 12])
        self.assertEqual(batch_jobs[0]["request"]["id"], "chunked-matrix-chunk-001-render-batch")
        self.assertEqual(batch_jobs[1]["request"]["id"], "chunked-matrix-chunk-002-render-batch")
        self.assertIn("config/person_factory.chunked-matrix-chunk-001.requests.json", batch_jobs[0]["command"])
        self.assertIn("config/person_factory.chunked-matrix-chunk-002.requests.json", batch_jobs[1]["command"])

    def test_matrix_cache_preflight_reports_configured_limit(self):
        with patch.dict(os.environ, {"PERSON_FACTORY_MAX_BATCH_JOBS": "18"}):
            plan = matrix_cache_preflight_plan(
                {
                    "id_prefix": "limit-plan",
                    "lines": "One.",
                    "bases": ["female"],
                    "accessories": ["necklace"],
                    "animations": ["talk_idle"],
                }
            )

        self.assertEqual(plan["limit"], 18)

    def test_matrix_cache_preflight_reports_chunked_limit_and_chunks(self):
        with patch.dict(
            os.environ,
            {"PERSON_FACTORY_MAX_BATCH_JOBS": "24", "PERSON_FACTORY_MAX_CHUNKED_MATRIX_JOBS": "48"},
        ):
            plan = matrix_cache_preflight_plan(
                {
                    "id_prefix": "chunked-plan",
                    "lines": "One.\nTwo.\nThree.",
                    "bases": ["female", "male"],
                    "accessories": ["a", "b", "c"],
                    "animations": ["talk_idle", "present_explain"],
                    "chunked": True,
                    "cache_line_audio": True,
                }
            )

        self.assertEqual(plan["job_count"], 36)
        self.assertEqual(plan["limit"], 48)
        self.assertEqual(plan["single_batch_limit"], 24)
        self.assertTrue(plan["chunked"])
        self.assertEqual(plan["chunk_count"], 2)
        self.assertEqual(plan["chunk_size"], 24)

    def test_chunked_matrix_warm_render_pipeline_uses_multiple_render_batch_children(self):
        payload = {
            "id_prefix": "chunked-warm-render",
            "lines": "One.\nTwo.\nThree.",
            "bases": ["female", "male"],
            "accessories": ["a", "b", "c"],
            "animations": ["talk_idle", "present_explain"],
            "chunked": True,
            "cache_line_audio": True,
            "render": True,
            "dry_run": False,
        }
        with patch.dict(
            os.environ,
            {"PERSON_FACTORY_MAX_BATCH_JOBS": "24", "PERSON_FACTORY_MAX_CHUNKED_MATRIX_JOBS": "48"},
        ):
            pipeline = build_matrix_warm_render_pipeline(payload)

        self.assertEqual(pipeline["status"], "ok")
        self.assertEqual(pipeline["render_job_count"], 36)
        self.assertEqual(pipeline["render_child_job_count"], 2)
        self.assertEqual(pipeline["stage_order"], ["warm-cache", "render-batch"])
        self.assertIsNone(pipeline["render_batch_job"])
        self.assertEqual(len(pipeline["render_batch_jobs"]), 2)
        self.assertEqual([job["request_count"] for job in pipeline["render_batch_jobs"]], [24, 12])

    def test_job_store_reports_status_stats(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = JobStore(Path(tmp_dir) / "jobs.json")
            jobs = store.create_jobs(
                [
                    ({"id": "web-stat-001", "text": "Queued."}, ["python3", "--version"]),
                    ({"id": "web-stat-002", "text": "Running."}, ["python3", "--version"]),
                    ({"id": "web-stat-003", "text": "Done."}, ["python3", "--version"]),
                    ({"id": "web-stat-004", "text": "Failed."}, ["python3", "--version"]),
                ]
            )
            store.update_job(jobs[1]["id"], status="running")
            store.update_job(jobs[2]["id"], status="ok", returncode=0)
            store.update_job(jobs[3]["id"], status="error", returncode=1)

            stats = store.stats(max_concurrent=2)

        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["queued"], 1)
        self.assertEqual(stats["running"], 1)
        self.assertEqual(stats["ok"], 1)
        self.assertEqual(stats["error"], 1)
        self.assertEqual(stats["pending"], 2)
        self.assertEqual(stats["max_concurrent"], 2)


if __name__ == "__main__":
    unittest.main()
