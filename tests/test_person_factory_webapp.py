import json
import os
import sys
import tempfile
import threading
import time
import unittest
from io import BytesIO
from unittest import mock
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class PersonFactoryWebappTests(unittest.TestCase):
    def test_json_response_uses_compact_encoding_for_polling_endpoints(self):
        from scripts.person_factory_webapp import json_response

        class FakeHandler:
            def __init__(self):
                self.wfile = BytesIO()
                self.status = None
                self.headers = []

            def send_response(self, status):
                self.status = status

            def send_header(self, key, value):
                self.headers.append((key, value))

            def end_headers(self):
                pass

        handler = FakeHandler()
        json_response(handler, 200, {"b": 1, "a": [2, 3]})

        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.wfile.getvalue(), b'{"b":1,"a":[2,3]}')
        self.assertIn(("Content-Length", "17"), handler.headers)

    def test_webapp_declares_job_api_routes(self):
        source = (ROOT / "scripts/person_factory_webapp.py").read_text(encoding="utf-8")

        self.assertIn("/api/jobs", source)
        self.assertIn("/api/batch-jobs", source)
        self.assertIn("/api/matrix-jobs", source)
        self.assertIn("/api/matrix-plan", source)
        self.assertIn("/api/matrix-cache-warm", source)
        self.assertIn("/api/matrix-warm-render", source)
        self.assertIn("/api/promote-batch", source)
        self.assertIn("/api/cached-lipsync-batch", source)
        self.assertIn("/api/cached-lipsync-estimate", source)
        self.assertIn("/api/refresh-combined-gallery", source)
        self.assertIn("/api/placement/assets", source)
        self.assertIn("/api/placement/plan", source)
        self.assertIn("/api/placement/suggest", source)
        self.assertIn("/api/options", source)
        self.assertIn("/api/storage", source)
        self.assertIn("/api/characters", source)
        self.assertIn("/api/lipsync-cache", source)
        self.assertIn("/api/godot/sync", source)
        self.assertIn("/api/godot/load", source)
        self.assertIn("/api/godot/lipsync", source)
        self.assertIn("/api/godot/lipsync-status", source)
        self.assertIn("/api/godot/camera", source)
        self.assertIn("/api/godot/expression-preset", source)
        self.assertIn("/api/godot/viseme", source)
        self.assertIn("/api/godot/animation", source)
        self.assertIn("/api/godot/health", source)
        self.assertIn("/api/godot/assets", source)
        self.assertIn("/api/godot/face-profile", source)
        self.assertIn("GODOT_CONTROL_URL", source)
        self.assertIn("proxy_godot_post", source)
        self.assertIn("ThreadingHTTPServer", source)
        self.assertIn("build_text_person_command", source)
        self.assertIn("normalize_matrix_job_requests", source)
        self.assertIn("matrix_cache_preflight_plan", source)
        self.assertIn("build_matrix_cache_warm_jobs", source)
        self.assertIn("build_matrix_warm_render_pipeline", source)
        self.assertIn("placement_assets", source)
        self.assertIn("placement_plan", source)
        self.assertIn("placement_suggestion", source)
        self.assertIn("run_matrix_warm_render_pipeline", source)
        self.assertIn("validate_catalog_choices(payload)", source)
        self.assertIn("JOB_STORE.stats", source)
        self.assertIn("load_accessories", source)
        self.assertIn("ANIMATIONS", source)
        self.assertIn("max_batch_jobs", source)
        self.assertIn("BoundedSemaphore", source)
        self.assertIn("WEBAPP_MAX_CONCURRENT_JOBS", source)
        self.assertIn("PERSON_FACTORY_CHUNK_WORKERS", source)
        self.assertIn("ThreadPoolExecutor", source)
        self.assertIn("scripts/build_combined_gallery.py", source)
        self.assertIn("scripts/promote_batch_assets.py", source)

    def test_compose_defaults_to_four_cached_lipsync_chunk_workers(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("WEBAPP_MAX_CONCURRENT_JOBS: ${WEBAPP_MAX_CONCURRENT_JOBS:-4}", compose)
        self.assertIn("PERSON_FACTORY_CHUNK_WORKERS: ${PERSON_FACTORY_CHUNK_WORKERS:-4}", compose)
        self.assertIn("PERSON_FACTORY_RENDER_CHUNK_WORKERS: ${PERSON_FACTORY_RENDER_CHUNK_WORKERS:-2}", compose)
        self.assertIn("PERSON_FACTORY_MAX_CHUNKED_MATRIX_JOBS: ${PERSON_FACTORY_MAX_CHUNKED_MATRIX_JOBS:-768}", compose)

    def test_character_catalog_page_filters_and_paginates_combined_outputs(self):
        import scripts.person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_output = webapp.OUTPUT_DIR
            original_cache = dict(webapp.CHARACTER_CATALOG_CACHE)
            webapp.ROOT = tmp
            webapp.OUTPUT_DIR = tmp / "outputs/batch"
            webapp.CHARACTER_CATALOG_CACHE.clear()
            webapp.CHARACTER_CATALOG_CACHE.update({"mtime": None, "payload": None})
            (tmp / "results").mkdir(parents=True)
            (tmp / "outputs/batch").mkdir(parents=True)
            (tmp / "outputs/batch_optimized").mkdir(parents=True)
            (tmp / "godot_viewer/game_assets/glb").mkdir(parents=True)
            (tmp / "outputs/batch/ship-001.glb").write_bytes(b"s" * 1000)
            (tmp / "outputs/batch_optimized/old-ready.glb").write_text("glb", encoding="utf-8")
            (tmp / "godot_viewer/game_assets/glb/old-ready.glb").write_text("glb", encoding="utf-8")
            (tmp / "outputs/batch_optimized/ship-001.glb").write_bytes(b"o" * 400)
            (tmp / "godot_viewer/game_assets/glb/ship-001.glb").write_bytes(b"g" * 400)
            ship_mtime = time.time()
            old_mtime = ship_mtime - 120
            os.utime(tmp / "outputs/batch_optimized/old-ready.glb", (old_mtime, old_mtime))
            os.utime(tmp / "godot_viewer/game_assets/glb/old-ready.glb", (old_mtime, old_mtime))
            os.utime(tmp / "outputs/batch_optimized/ship-001.glb", (ship_mtime, ship_mtime))
            os.utime(tmp / "godot_viewer/game_assets/glb/ship-001.glb", (ship_mtime, ship_mtime))
            (tmp / "results/person_factory_all_latest.json").write_text(
                json.dumps(
                    {
                        "source_job_count": 4,
                        "filtered_job_count": 1,
                        "deduped_job_count": 0,
                        "godot_lipsync_summary": {"checked_count": 2, "grade_counts": {"A": 2}},
                        "godot_lipsync_validation": {
                            "checked": [
                                {
                                    "id": "old-ready",
                                    "status": "ok",
                                    "cue_count": 43,
                                    "timeline": "/workspace/outputs/lipsync/cache/older.face.json",
                                    "lipsync_quality": {
                                        "grade": "A",
                                        "duration": 4.3,
                                        "active_visemes": ["aa", "ee", "ih", "oh", "ou"],
                                        "source_mode": "phoneme-events",
                                    },
                                },
                                {
                                    "id": "ship-001",
                                    "status": "ok",
                                    "cue_count": 18,
                                    "timeline": "/workspace/outputs/lipsync/cache/demo.face.json",
                                    "lipsync_quality": {
                                        "grade": "A",
                                        "duration": 1.86,
                                        "active_visemes": ["aa", "ee"],
                                        "source_mode": "phoneme-events",
                                    },
                                }
                            ]
                        },
                        "jobs": [
                            {
                                "id": "old-unchecked",
                                "status": "ok",
                                "metadata": {"display_name": "Old Unchecked", "tags": ["source:test"]},
                                "qa": {"qa_grade": "A", "qa_score": 90, "review_priority": "ship"},
                                "environment": {"ANIMATION_PRESET": "idle", "OUTFIT_CATEGORY": "head_face"},
                            },
                            {
                                "id": "old-ready",
                                "status": "ok",
                                "metadata": {
                                    "display_name": "Old Ready",
                                    "tags": ["ship", "source:test", "animation:talk"],
                                },
                                "qa": {"qa_grade": "A", "qa_score": 100, "review_priority": "ship"},
                                "environment": {
                                    "ANIMATION_PRESET": "talk_idle",
                                    "OUTFIT_CATEGORY": "neck_chest",
                                    "OUTPUT_GLB": "/workspace/outputs/batch/old-ready.glb",
                                    "ANIMATION_REPORT_JSON": "/workspace/results/old-ready.json",
                                },
                            },
                            {
                                "id": "ship-001",
                                "status": "ok",
                                "metadata": {
                                    "display_name": "Ship One",
                                    "persona": "Presenter",
                                    "tags": ["ship", "source:test", "animation:talk"],
                                },
                                "qa": {"qa_grade": "A", "qa_score": 100, "review_priority": "ship"},
                                "environment": {
                                    "ANIMATION_PRESET": "talk_idle",
                                    "OUTFIT_CATEGORY": "neck_chest",
                                    "OUTPUT_GLB": "/workspace/outputs/batch/ship-001.glb",
                                    "ANIMATION_REPORT_JSON": "/workspace/results/ship-001.json",
                                },
                            },
                            {
                                "id": "review-001",
                                "status": "ok",
                                "metadata": {"display_name": "Review One", "tags": ["review", "source:test"]},
                                "qa": {"qa_grade": "B", "qa_score": 82, "review_priority": "review"},
                                "environment": {"ANIMATION_PRESET": "look_around", "OUTFIT_CATEGORY": "head_face"},
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            try:
                default_page = webapp.character_catalog_page({"per_page": ["2"]})
                newest_page = webapp.character_catalog_page({"per_page": ["2"], "sort": ["newest"]})
                id_page = webapp.character_catalog_page({"per_page": ["2"], "sort": ["id"]})
                smallest_page = webapp.character_catalog_page({"per_page": ["2"], "sort": ["smallest"]})
                largest_page = webapp.character_catalog_page({"per_page": ["2"], "sort": ["largest"]})
                fallback_page = webapp.character_catalog_page({"per_page": ["2"], "sort": ["unknown"]})
                page = webapp.character_catalog_page({"q": ["Ship One"], "per_page": ["1"]})
                tagged = webapp.character_catalog_page({"tag": ["review"]})
                priority = webapp.character_catalog_page({"priority": ["ship"]})
            finally:
                webapp.ROOT = original_root
                webapp.OUTPUT_DIR = original_output
                webapp.CHARACTER_CATALOG_CACHE.clear()
                webapp.CHARACTER_CATALOG_CACHE.update(original_cache)

        self.assertEqual(default_page["characters"][0]["id"], "ship-001")
        self.assertEqual(default_page["filters"]["sort"], "ready")
        self.assertGreater(default_page["characters"][0]["updated_at"], 0)
        self.assertEqual(default_page["characters"][1]["id"], "old-ready")
        self.assertEqual(newest_page["filters"]["sort"], "newest")
        self.assertEqual(newest_page["characters"][0]["id"], "ship-001")
        self.assertEqual(id_page["filters"]["sort"], "id")
        self.assertEqual(id_page["characters"][0]["id"], "old-ready")
        self.assertEqual(smallest_page["filters"]["sort"], "smallest")
        self.assertEqual(smallest_page["characters"][0]["id"], "old-ready")
        self.assertEqual(largest_page["filters"]["sort"], "largest")
        self.assertEqual(largest_page["characters"][0]["id"], "ship-001")
        self.assertEqual(fallback_page["filters"]["sort"], "ready")
        self.assertEqual(page["pagination"]["total"], 1)
        self.assertEqual(page["characters"][0]["id"], "ship-001")
        self.assertTrue(page["characters"][0]["has_game_asset"])
        self.assertEqual(page["characters"][0]["lipsync"]["grade"], "A")
        self.assertEqual(page["characters"][0]["asset_size"]["source_bytes"], 1000)
        self.assertEqual(page["characters"][0]["asset_size"]["optimized_bytes"], 400)
        self.assertEqual(page["characters"][0]["asset_size"]["game_bytes"], 400)
        self.assertEqual(page["characters"][0]["asset_size"]["saved_pct"], 60)
        self.assertEqual(page["summary"]["character_count"], 4)
        self.assertEqual(tagged["characters"][0]["id"], "review-001")
        self.assertEqual(priority["characters"][0]["qa"]["priority"], "ship")

    def test_load_character_catalog_prefers_fresh_prebuilt_index(self):
        import scripts.person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_cache = dict(webapp.CHARACTER_CATALOG_CACHE)
            webapp.ROOT = tmp
            webapp.CHARACTER_CATALOG_CACHE.clear()
            webapp.CHARACTER_CATALOG_CACHE.update({"mtime": None, "payload": None})
            summary = tmp / "results/person_factory_all_latest.json"
            index = tmp / "results/person_factory_character_catalog_latest.json"
            summary.parent.mkdir(parents=True)
            summary.write_text(json.dumps({"jobs": [{"id": "slow"}]}), encoding="utf-8")
            summary_mtime = summary.stat().st_mtime
            index.write_text(
                json.dumps(
                    {
                        "source_mtime": summary_mtime,
                        "schema_version": webapp.CHARACTER_CATALOG_SCHEMA_VERSION,
                        "payload": {
                            "status": "ok",
                            "source": "results/person_factory_all_latest.json",
                            "summary": {"character_count": 1},
                            "characters": [{"id": "indexed", "tags": [], "updated_at": 123}],
                        },
                    }
                ),
                encoding="utf-8",
            )

            try:
                catalog = webapp.load_character_catalog()
            finally:
                webapp.ROOT = original_root
                webapp.CHARACTER_CATALOG_CACHE.clear()
                webapp.CHARACTER_CATALOG_CACHE.update(original_cache)

        self.assertEqual(catalog["characters"][0]["id"], "indexed")

    def test_load_character_catalog_rebuilds_when_prebuilt_index_is_stale(self):
        import scripts.person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_cache = dict(webapp.CHARACTER_CATALOG_CACHE)
            webapp.ROOT = tmp
            webapp.CHARACTER_CATALOG_CACHE.clear()
            webapp.CHARACTER_CATALOG_CACHE.update({"mtime": None, "payload": None})
            summary = tmp / "results/person_factory_all_latest.json"
            index = tmp / "results/person_factory_character_catalog_latest.json"
            summary.parent.mkdir(parents=True)
            summary.write_text(
                json.dumps({"jobs": [{"id": "rebuilt", "status": "ok", "metadata": {"tags": ["generated"]}}]}),
                encoding="utf-8",
            )
            index.write_text(
                json.dumps(
                    {
                        "source_mtime": 1,
                        "payload": {
                            "status": "ok",
                            "characters": [{"id": "stale", "tags": []}],
                        },
                    }
                ),
                encoding="utf-8",
            )

            try:
                catalog = webapp.load_character_catalog()
            finally:
                webapp.ROOT = original_root
                webapp.CHARACTER_CATALOG_CACHE.clear()
                webapp.CHARACTER_CATALOG_CACHE.update(original_cache)

        self.assertEqual(catalog["characters"][0]["id"], "rebuilt")

    def test_load_character_catalog_rebuilds_when_prebuilt_index_schema_is_stale(self):
        import scripts.person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_cache = dict(webapp.CHARACTER_CATALOG_CACHE)
            webapp.ROOT = tmp
            webapp.CHARACTER_CATALOG_CACHE.clear()
            webapp.CHARACTER_CATALOG_CACHE.update({"mtime": None, "payload": None})
            summary = tmp / "results/person_factory_all_latest.json"
            index = tmp / "results/person_factory_character_catalog_latest.json"
            summary.parent.mkdir(parents=True)
            summary.write_text(
                json.dumps({"jobs": [{"id": "rebuilt", "status": "ok", "metadata": {"tags": ["generated"]}}]}),
                encoding="utf-8",
            )
            summary_mtime = summary.stat().st_mtime
            index.write_text(
                json.dumps(
                    {
                        "source_mtime": summary_mtime,
                        "payload": {
                            "status": "ok",
                            "characters": [{"id": "stale", "tags": []}],
                        },
                    }
                ),
                encoding="utf-8",
            )

            try:
                catalog = webapp.load_character_catalog()
                rewritten = json.loads(index.read_text(encoding="utf-8"))
            finally:
                webapp.ROOT = original_root
                webapp.CHARACTER_CATALOG_CACHE.clear()
                webapp.CHARACTER_CATALOG_CACHE.update(original_cache)

        self.assertEqual(catalog["characters"][0]["id"], "rebuilt")
        self.assertIn("updated_at", catalog["characters"][0])
        self.assertEqual(rewritten["schema_version"], webapp.CHARACTER_CATALOG_SCHEMA_VERSION)

    def test_factory_page_posts_jobs_and_embeds_gallery(self):
        html = (ROOT / "webapp/factory.html").read_text(encoding="utf-8")
        js = (ROOT / "webapp/factory.js").read_text(encoding="utf-8")

        self.assertIn('src="/index.html"', html)
        self.assertIn('id="job-form"', html)
        self.assertIn('id="queue-batch"', html)
        self.assertIn('id="queue-matrix"', html)
        self.assertIn('id="preview-matrix"', html)
        self.assertIn('id="warm-matrix-cache"', html)
        self.assertIn('id="warm-render-matrix"', html)
        self.assertIn('id="queue-cached-lipsync"', html)
        self.assertIn('id="queue-phrasebank-thumbnails"', html)
        self.assertIn('id="refresh-combined-gallery"', html)
        self.assertIn('id="promote-batch"', html)
        self.assertIn('id="cached-lipsync-batch-id"', html)
        self.assertIn('id="cached-lipsync-timeline"', html)
        self.assertIn('id="cached-lipsync-cache-select" multiple', html)
        self.assertIn('id="cached-lipsync-auto-cache-lines"', html)
        self.assertIn('id="cached-lipsync-cache-line-count"', html)
        self.assertIn('id="cached-lipsync-chunked"', html)
        self.assertIn('id="cached-lipsync-fast-publish"', html)
        self.assertIn('id="cached-lipsync-estimate"', html)
        self.assertIn('value="683aff4ae080c56e"', html)
        self.assertIn('value="outputs/lipsync/cache/683aff4ae080c56e.face.json"', html)
        self.assertIn('>Pat met Tim. Go put food.</textarea>', html)
        self.assertIn('id="matrix-count"', html)
        self.assertIn('id="matrix-plan"', html)
        self.assertIn('name="matrix_chunked"', html)
        self.assertIn('id="job-stats"', html)
        self.assertIn('id="storage-stats"', html)
        self.assertIn('id="recent-galleries"', html)
        self.assertIn('id="refresh-galleries"', html)
        self.assertIn('id="character-browser"', html)
        self.assertIn('id="character-results"', html)
        self.assertIn('id="character-search"', html)
        self.assertIn('id="character-sort"', html)
        self.assertIn('id="job-filters"', html)
        self.assertIn('id="godot-stage-controls"', html)
        self.assertIn('id="godot-stage-status"', html)
        self.assertIn('id="godot-animation-controls"', html)
        self.assertIn('class="placement-panel"', html)
        self.assertIn('id="placement-asset"', html)
        self.assertIn('id="placement-profile"', html)
        self.assertIn('id="placement-plan"', html)
        self.assertIn('id="placement-suggest"', html)
        self.assertIn('id="placement-current-box"', html)
        self.assertIn('id="placement-output"', html)
        self.assertIn('value="rough_lipsync"', html)
        self.assertIn('value="thumbnail_lipsync"', html)
        self.assertIn('value="control_lipsync"', html)
        self.assertIn('data-godot-stage-action="camera"', html)
        self.assertIn('data-godot-stage-action="expression-preset"', html)
        self.assertIn('data-godot-stage-action="viseme"', html)
        self.assertIn('data-godot-stage-action="animation"', html)
        self.assertIn('data-job-filter="game-ready"', html)
        self.assertIn('data-job-filter="cache-only"', html)
        self.assertIn('data-job-filter="lip-ready"', html)
        self.assertIn('data-job-filter="needs-lip-fix"', html)
        self.assertIn('data-job-filter="pipelines"', html)
        self.assertIn('data-job-filter="errors"', html)
        self.assertIn('aria-pressed="true"', html)
        self.assertIn('name="batch_lines"', html)
        self.assertIn('name="matrix_accessories"', html)
        self.assertIn('name="matrix_animations"', html)
        self.assertIn('name="cache_line_audio"', html)
        self.assertIn('id="sync-godot"', html)
        self.assertIn('<option value="necklace" selected>', html)
        self.assertNotIn('value="monocle"', html)
        self.assertIn('fetch(url', js)
        self.assertIn('/api/jobs', js)
        self.assertIn('/api/jobs?compact=1&limit=40&summary=0&logs=0', js)
        self.assertIn('/api/galleries', js)
        self.assertIn('/api/batch-jobs', js)
        self.assertIn('/api/matrix-jobs', js)
        self.assertIn('/api/matrix-plan', js)
        self.assertIn('/api/matrix-cache-warm', js)
        self.assertIn('/api/matrix-warm-render', js)
        self.assertIn('/api/promote-batch', js)
        self.assertIn('/api/cached-lipsync-batch', js)
        self.assertIn('/api/phrasebank-thumbnail-batch', js)
        self.assertIn('/api/cached-lipsync-estimate', js)
        self.assertIn('/api/options', js)
        self.assertIn('/api/storage', js)
        self.assertIn('/api/characters', js)
        self.assertIn('refreshCharacters', js)
        self.assertIn('renderCharacterBrowser', js)
        self.assertIn('characterPage', js)
        self.assertIn('characterSortSelect', js)
        self.assertIn('formatCharacterUpdated', js)
        self.assertIn('formatBytes', js)
        self.assertIn('asset_size', js)
        self.assertIn('GLB ${escapeHtml(formatBytes(assetSize.optimized_bytes))}', js)
        self.assertIn('% saved', js)
        self.assertIn('/api/lipsync-cache', js)
        self.assertIn('/api/placement/assets', js)
        self.assertIn('/api/placement/plan', js)
        self.assertIn('/api/placement/suggest', js)
        self.assertIn('/api/godot/sync', js)

        html = (ROOT / "webapp/factory.html").read_text(encoding="utf-8")
        self.assertIn('<option value="smallest">Smallest GLB</option>', html)
        self.assertIn('<option value="largest">Largest GLB</option>', html)
        self.assertIn('/api/godot/load', js)
        self.assertIn('/api/godot/lipsync', js)
        self.assertIn('/api/godot/lipsync-status', js)
        self.assertIn('/api/godot/camera', js)
        self.assertIn('/api/godot/expression-preset', js)
        self.assertIn('/api/godot/viseme', js)
        self.assertIn('/api/godot/animation', js)
        self.assertIn('/api/godot/health', js)
        self.assertIn('/api/godot/face-profile', js)
        self.assertIn('populateSelect', js)
        self.assertIn('refreshPlacementAssets', js)
        self.assertIn('buildPlacementPlan', js)
        self.assertIn('suggestPlacementOverrides', js)
        self.assertIn('parseBoxInput', js)
        self.assertIn('matrixPayload', js)
        self.assertIn('productionMatrixPayload', js)
        self.assertIn('renderMatrixPlan', js)
        self.assertIn('matrixJobLimit', js)
        self.assertIn('payload.limits?.matrix_jobs', js)
        self.assertIn('payload.limits?.chunked_matrix_jobs', js)
        self.assertIn('payload.chunked = data.has("matrix_chunked")', js)
        self.assertIn('warmMatrixCache', js)
        self.assertIn('warmRenderMatrix', js)
        self.assertIn('payload.render = true', js)
        self.assertIn('payload.dry_run = false', js)
        self.assertIn('payload.cache_line_audio = true', js)
        self.assertIn('cachedLipSyncPayload', js)
        self.assertIn('renderCachedLipSyncEstimate', js)
        self.assertIn('refreshCachedLipSyncEstimate', js)
        self.assertIn('scheduleCachedLipSyncEstimate', js)
        self.assertIn('renderEstimateNotices', js)
        self.assertIn('enable-parallel-chunks', js)
        self.assertIn('worker_options', js)
        self.assertIn('faster est', js)
        self.assertIn('updateCachedLipSyncCountLimit', js)
        self.assertIn('cachedLipSyncCountInput.max', js)
        self.assertIn('refreshLipSyncCache', js)
        self.assertIn('await refreshCachedLipSyncEstimate()', js)
        self.assertIn('refreshCachedLipSyncEstimate();', js)
        self.assertIn('applyLipSyncCacheSelection', js)
        self.assertIn('selectedLipSyncCacheEntries', js)
        self.assertIn('payload.cache_lines', js)
        self.assertIn('payload.chunked_cached_lipsync', js)
        self.assertIn('payload.skip_combined_refresh', js)
        self.assertIn('cachedLipSyncFastPublishInput?.checked', js)
        self.assertIn('fastPublish ? "fast max"', js)
        self.assertIn('payload.promote_after', js)
        self.assertIn('queueCachedLipSyncBatch', js)
        self.assertIn('queuePhrasebankThumbnailBatch', js)
        self.assertIn('payload.pipeline_job?.id || payload.job?.id', js)
        self.assertIn('refreshCombinedGallery', js)
        self.assertIn('/api/refresh-combined-gallery', js)
        self.assertIn('payload.chunked ? ` · ${payload.chunk_count} chunks`', js)
        self.assertIn('renderStats', js)
        self.assertIn('refreshGalleries', js)
        self.assertIn('renderRecentGalleries', js)
        self.assertIn('activeGalleryFilter', js)
        self.assertIn('data-gallery-filter', js)
        self.assertIn('recent-gallery-badges', js)
        self.assertIn('summary.qa_grades', js)
        self.assertIn('summary.lipsync_grades', js)
        self.assertIn('summary.lipsync_quality', js)
        self.assertIn('Visemes', js)
        self.assertIn('Missing visemes', js)
        self.assertIn('summary.render_cache', js)
        self.assertIn('summary.elapsed_seconds', js)
        self.assertIn('summary.slowest_stage', js)
        self.assertIn('renderStorageStats', js)
        self.assertIn('Hardlink saved', js)
        self.assertIn('activeJobFilter', js)
        self.assertIn('latestJobsPayload', js)
        self.assertIn('renderJobFilters', js)
        self.assertIn('jobMatchesFilter', js)
        self.assertIn('jobFilterCounts', js)
        self.assertIn('data-job-filter', js)
        self.assertIn('game-ready', js)
        self.assertIn('cache-only', js)
        self.assertIn('lip-ready', js)
        self.assertIn('needs-lip-fix', js)
        self.assertIn('Boolean(summary.has_game_asset) && summary.lip_sync_readiness?.status === "ready"', js)
        self.assertIn('Boolean(summary.has_game_asset) && summary.lip_sync_readiness?.status === "review"', js)
        self.assertIn('pipelines', js)
        self.assertIn('errors', js)
        self.assertIn('renderJobLinks', js)
        self.assertIn('renderPublishStatus', js)
        self.assertIn('renderBatchTiming', js)
        self.assertIn('stage_summary', js)
        self.assertIn('renderOutputSummary', js)
        self.assertIn('renderGodotActions', js)
        self.assertIn('renderVisemeDiagnostics', js)
        self.assertIn('renderLipSyncReadiness', js)
        self.assertIn('renderLipSyncQuality', js)
        self.assertIn('readinessReasonLabel', js)
        self.assertIn('viseme_counts', js)
        self.assertIn('missing_visemes', js)
        self.assertIn('lip_sync_readiness', js)
        self.assertIn('Lip-ready', js)
        self.assertIn('Needs lip fix', js)
        self.assertIn('Lip quality', js)
        self.assertIn('expression_count', js)

        self.assertIn('job-visemes', js)
        self.assertIn('Missing visemes', js)
        self.assertIn('data-godot-action', js)
        self.assertIn('data-godot-stage-action', js)
        self.assertIn('godotStageAction', js)
        self.assertIn('stagePayload', js)
        self.assertIn('refreshGodotStageStatus', js)
        self.assertIn('renderGodotStageStatus', js)
        self.assertIn('renderGodotAnimationControls', js)
        self.assertIn('godot-stage-status', js)
        self.assertIn('godot-animation-controls', js)
        self.assertIn('viseme_count', js)
        self.assertIn('expression_count', js)
        self.assertIn('health.animations', js)
        self.assertIn('health.lipsync', js)
        self.assertIn('active_viseme', js)
        self.assertIn('godotAction', js)
        self.assertIn('has_game_asset', js)
        self.assertIn('review_image', js)
        self.assertIn('job-review-image', js)
        self.assertIn('child_job_ids', js)
        self.assertIn('publish_result', js)
        self.assertIn('pipeline_timing', js)
        self.assertIn('renderPipelineTiming', js)
        self.assertIn('renderEstimateAccuracy', js)
        self.assertIn('Parallel efficiency', js)
        self.assertIn('output_summary', js)
        self.assertIn('job-outputs', js)
        self.assertIn('QA ', js)
        self.assertIn('Lip sync ', js)
        self.assertIn('Load in Godot', js)
        self.assertIn('Talk in Godot', js)
        self.assertIn('Send timeline to Godot', js)
        self.assertIn('timeline-only', js)
        self.assertIn('data-timeline', js)
        self.assertIn('publish-status', js)
        self.assertIn('gallery return', js)
        self.assertIn('Godot assets', js)
        self.assertIn('exported', js)
        self.assertIn('skipped', js)
        self.assertIn('failed', js)
        self.assertIn('<details class="job-log">', js)
        self.assertIn('<summary>Log tail', js)
        self.assertIn('cache_line_audio', js)
        self.assertIn('auto_cache_lines', js)
        self.assertIn('cache_line_count', js)
        css = (ROOT / "webapp/factory.css").read_text(encoding="utf-8")
        self.assertIn(".job-filters", css)
        self.assertIn(".recent-galleries", css)
        self.assertIn(".recent-gallery-filters", css)
        self.assertIn(".recent-gallery-badges", css)
        self.assertIn(".godot-stage-panel", css)
        self.assertIn(".placement-panel", css)
        self.assertIn(".placement-output", css)
        self.assertIn(".stage-row", css)
        self.assertIn(".job-lip-ready", css)
        self.assertIn(".job-lip-review", css)
        self.assertIn(".job-lip-quality", css)
        self.assertIn(".job-visemes", css)
        self.assertIn(".job-viseme-missing", css)
        self.assertIn("aria-pressed", js)

    def test_recent_batch_galleries_returns_newest_html_links(self):
        import scripts.person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_output = webapp.OUTPUT_DIR
            webapp.OUTPUT_DIR = tmp / "outputs/batch"
            webapp.OUTPUT_DIR.mkdir(parents=True)
            older = webapp.OUTPUT_DIR / "person_factory_old-batch.html"
            newer = webapp.OUTPUT_DIR / "person_factory_new-batch.html"
            ignored = webapp.OUTPUT_DIR / "index.html"
            results = tmp / "results"
            results.mkdir()
            older.write_text("<html>old</html>", encoding="utf-8")
            newer.write_text("<html>new</html>", encoding="utf-8")
            ignored.write_text("<html>index</html>", encoding="utf-8")
            (results / "batch_person_factory_new_batch_latest.json").write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "jobs": [
                            {
                                "id": "one",
                                "environment": {
                                    "INPUT_MODEL": "/workspace/base/female.blend",
                                    "OUTFIT_MODEL": "/workspace/input/outfits/hat.glb",
                                    "OUTFIT_CATEGORY": "head_face",
                                    "ANIMATION_PRESET": "talk_idle",
                                },
                            },
                            {
                                "id": "two",
                                "environment": {
                                    "INPUT_MODEL": "/workspace/base/male.blend",
                                    "OUTFIT_MODEL": "/workspace/input/outfits/tie.glb",
                                    "OUTFIT_CATEGORY": "neck_chest",
                                    "ANIMATION_PRESET": "present_explain",
                                },
                            },
                        ],
                        "qa_summary": {
                            "grades": {"A": 2},
                            "priorities": {"ship": 2},
                            "review_count": 0,
                            "ship_count": 2,
                        },
                        "render_cache": {"hit_count": 2, "miss_count": 0},
                        "render_dedupe": {
                            "requested_job_count": 2,
                            "source_job_count": 1,
                            "materialized_duplicate_count": 1,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (results / "godot_lipsync_validation_new_batch_latest.json").write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "checked_count": 2,
                        "grade_counts": {"A": 2},
                        "source_counts": {"phoneme-events": 2},
                        "active_visemes": ["aa", "ee", "ih", "oh", "ou"],
                        "missing_active_viseme_counts": {},
                        "cue_count_min": 22,
                        "cue_count_max": 33,
                        "expression_count_min": 2,
                        "expression_count_max": 2,
                    }
                ),
                encoding="utf-8",
            )
            (results / "run_cached_lipsync_batch_new_batch.json").write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "elapsed_seconds": 1.23,
                        "stage_summary": {
                            "slowest_stage": "render",
                            "slowest_stage_seconds": 0.71,
                            "stages": [
                                {"name": "generate", "elapsed_seconds": 0.1, "status": "ok"},
                                {"name": "render", "elapsed_seconds": 0.71, "status": "ok"},
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            now = time.time()
            os.utime(older, (now - 20, now - 20))
            os.utime(newer, (now, now))
            os.utime(ignored, (now + 20, now + 20))

            try:
                original_root = webapp.ROOT
                webapp.ROOT = tmp
                payload = webapp.recent_batch_galleries(limit=2)
            finally:
                webapp.ROOT = original_root
                webapp.OUTPUT_DIR = original_output

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(
            [item["href"] for item in payload["galleries"]],
            ["person_factory_new-batch.html", "person_factory_old-batch.html"],
        )
        self.assertEqual(payload["galleries"][0]["batch_id"], "new-batch")
        self.assertGreater(payload["galleries"][0]["size_bytes"], 0)
        self.assertEqual(payload["galleries"][0]["summary"]["character_count"], 2)
        self.assertEqual(payload["galleries"][0]["summary"]["qa_grades"], {"A": 2})
        self.assertEqual(payload["galleries"][0]["summary"]["review_count"], 0)
        self.assertEqual(payload["galleries"][0]["summary"]["lipsync_grades"], {"A": 2})
        self.assertEqual(payload["galleries"][0]["summary"]["lipsync_sources"], {"phoneme-events": 2})
        self.assertEqual(
            payload["galleries"][0]["summary"]["lipsync_quality"],
            {
                "active_visemes": ["aa", "ee", "ih", "oh", "ou"],
                "missing_active_viseme_counts": {},
                "cue_count_min": 22,
                "cue_count_max": 33,
                "expression_count_min": 2,
                "expression_count_max": 2,
            },
        )
        self.assertEqual(payload["galleries"][0]["summary"]["render_cache"], {"hit_count": 2, "miss_count": 0})
        self.assertEqual(
            payload["galleries"][0]["summary"]["render_dedupe"],
            {
                "requested_job_count": 2,
                "source_job_count": 1,
                "materialized_duplicate_count": 1,
            },
        )
        self.assertEqual(
            payload["galleries"][0]["summary"]["variation"],
            {
                "base_count": 2,
                "accessory_count": 2,
                "animation_count": 2,
                "category_count": 2,
                "categories": ["head_face", "neck_chest"],
            },
        )
        self.assertEqual(payload["galleries"][0]["summary"]["elapsed_seconds"], 1.23)
        self.assertEqual(payload["galleries"][0]["summary"]["slowest_stage"], "render")
        self.assertEqual(payload["galleries"][0]["summary"]["slowest_stage_seconds"], 0.71)
        self.assertAlmostEqual(payload["galleries"][0]["summary"]["characters_per_second"], 1.626, places=3)
        self.assertEqual(payload["galleries"][0]["summary"]["render_cache_hit_rate"], 1.0)
        self.assertEqual(payload["galleries"][0]["summary"]["validation_cache_hit_rate"], 0.0)
        self.assertEqual(
            payload["galleries"][0]["batch_result"],
            "results/batch_person_factory_new_batch_latest.json",
        )
        self.assertEqual(
            payload["galleries"][0]["validation_result"],
            "results/godot_lipsync_validation_new_batch_latest.json",
        )
        self.assertEqual(
            payload["galleries"][0]["run_result"],
            "results/run_cached_lipsync_batch_new_batch.json",
        )
        self.assertEqual(payload["benchmark"]["best_throughput"]["batch_id"], "new-batch")
        self.assertAlmostEqual(payload["benchmark"]["best_throughput"]["characters_per_second"], 1.626, places=3)
        self.assertEqual(payload["benchmark"]["best_throughput"]["mode"], "fast-preview")
        self.assertEqual(payload["benchmark"]["latest"]["batch_id"], "new-batch")
        self.assertEqual(payload["benchmark"]["review_batches"], [])
        self.assertEqual(payload["benchmark"]["recommendation"]["batch_id"], "new-batch-next")
        self.assertEqual(payload["benchmark"]["recommendation"]["count"], 2)
        self.assertFalse(payload["benchmark"]["recommendation"]["chunked"])
        self.assertTrue(payload["benchmark"]["recommendation"]["fast_publish"])
        self.assertFalse(payload["benchmark"]["recommendation"]["queue_chunked"])
        self.assertEqual(payload["benchmark"]["recommendation"]["queue_chunk_count"], 1)
        self.assertEqual(payload["benchmark"]["recommendation"]["queue_chunk_size"], 2)
        self.assertFalse(payload["benchmark"]["recommendation"]["queue_fast_publish"])
        self.assertTrue(payload["benchmark"]["recommendation"]["queue_publish_combined"])
        self.assertEqual(payload["benchmark"]["recommendation"]["queue_mode"], "published-catalog")
        self.assertEqual(payload["benchmark"]["recommendation"]["queue_estimated_wall_seconds"], 1.23)
        self.assertEqual(payload["benchmark"]["recommendation"]["queue_reference_batch_id"], "new-batch")
        self.assertEqual(payload["benchmark"]["recommendation"]["queue_reference_elapsed_seconds"], 1.23)
        self.assertTrue(payload["benchmark"]["recommendation"]["cache_ready"])
        self.assertEqual(payload["benchmark"]["recommendation"]["cache_hit_count"], 2)
        self.assertEqual(payload["benchmark"]["recommendation"]["source_job_count"], 1)

    def test_recent_batch_galleries_benchmark_uses_more_than_display_limit(self):
        import scripts.person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            output_dir = tmp / "outputs/batch"
            results = tmp / "results"
            output_dir.mkdir(parents=True)
            results.mkdir()
            original_root = webapp.ROOT
            original_output = webapp.OUTPUT_DIR
            webapp.ROOT = tmp
            webapp.OUTPUT_DIR = output_dir
            webapp.RECENT_GALLERY_SUMMARY_CACHE.clear()
            try:
                now = time.time()
                for index, elapsed in enumerate([47.0, 49.0, 51.0, 53.0, 55.0], start=1):
                    batch_id = f"ship-next-{index:03d}"
                    html = output_dir / f"person_factory_{batch_id}.html"
                    html.write_text("<html></html>", encoding="utf-8")
                    os.utime(html, (now + index, now + index))
                    slug_id = webapp.batch_result_slug(batch_id)
                    (results / f"batch_person_factory_{slug_id}_latest.json").write_text(
                        json.dumps(
                            {
                                "status": "ok",
                                "jobs": [{"qa": {"grade": "A", "decision": "ship"}} for _ in range(256)],
                                "qa_summary": {
                                    "grades": {"A": 256},
                                    "review_count": 0,
                                    "ship_count": 256,
                                },
                                "chunked_parent": {"pipeline": {"type": "phrasebank-thumbnail-batch"}},
                                "pipeline_timing": {
                                    "wall_elapsed_seconds": elapsed,
                                    "chunk_wall_elapsed_seconds": 37.0,
                                    "orchestration_overhead_seconds": elapsed - 37.0,
                                },
                                "render_dedupe": {"source_job_count": 256},
                            }
                        ),
                        encoding="utf-8",
                    )

                payload = webapp.recent_batch_galleries(limit=2)
            finally:
                webapp.ROOT = original_root
                webapp.OUTPUT_DIR = original_output
                webapp.RECENT_GALLERY_SUMMARY_CACHE.clear()

        self.assertEqual(len(payload["galleries"]), 2)
        self.assertEqual(payload["galleries"][0]["batch_id"], "ship-next-005")
        recommendation = payload["benchmark"]["recommendation"]
        self.assertEqual(recommendation["queue_estimate_sample_count"], 5)
        self.assertEqual(recommendation["queue_estimated_wall_seconds"], 51.0)
        self.assertEqual(recommendation["queue_reference_batch_id"], "ship-next-005")

    def test_selected_gallery_fallback_prefers_newest_html(self):
        import scripts.person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            output_dir = tmp / "outputs/batch"
            output_dir.mkdir(parents=True)
            older = output_dir / "person_factory_aaa_older.html"
            newer = output_dir / "person_factory_zzz_newer.html"
            older.write_text("<html>older</html>", encoding="utf-8")
            newer.write_text("<html>newer</html>", encoding="utf-8")
            now = time.time()
            os.utime(older, (now - 30, now - 30))
            os.utime(newer, (now, now))

            original_output = webapp.OUTPUT_DIR
            try:
                webapp.OUTPUT_DIR = output_dir
                selected = webapp.selected_gallery()
            finally:
                webapp.OUTPUT_DIR = original_output

        self.assertEqual(selected.name, "person_factory_zzz_newer.html")

    def test_recent_batch_galleries_omits_child_chunk_galleries(self):
        import scripts.person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_output = webapp.OUTPUT_DIR
            webapp.ROOT = tmp
            webapp.OUTPUT_DIR = tmp / "outputs/batch"
            webapp.OUTPUT_DIR.mkdir(parents=True)
            (tmp / "results").mkdir()
            parent = webapp.OUTPUT_DIR / "person_factory_parent.html"
            child = webapp.OUTPUT_DIR / "person_factory_parent-chunk-001.html"
            parent.write_text("<html>parent</html>", encoding="utf-8")
            child.write_text("<html>child</html>", encoding="utf-8")
            now = time.time()
            os.utime(parent, (now - 10, now - 10))
            os.utime(child, (now, now))

            try:
                payload = webapp.recent_batch_galleries(limit=10)
            finally:
                webapp.ROOT = original_root
                webapp.OUTPUT_DIR = original_output

        self.assertEqual([item["batch_id"] for item in payload["galleries"]], ["parent"])

    def test_recent_batch_galleries_summarizes_display_and_benchmark_items(self):
        import scripts.person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_output = webapp.OUTPUT_DIR
            original_summary = webapp.recent_gallery_summary
            webapp.ROOT = tmp
            webapp.OUTPUT_DIR = tmp / "outputs/batch"
            webapp.OUTPUT_DIR.mkdir(parents=True)
            (tmp / "results").mkdir()
            now = time.time()
            for index in range(20):
                path = webapp.OUTPUT_DIR / f"person_factory_batch-{index:03d}.html"
                path.write_text("<html>batch</html>", encoding="utf-8")
                os.utime(path, (now - index, now - index))
            summarized = []

            def fake_summary(batch_id):
                summarized.append(batch_id)
                return {"status": "ok", "character_count": 1}

            webapp.recent_gallery_summary = fake_summary
            try:
                payload = webapp.recent_batch_galleries(limit=3)
            finally:
                webapp.ROOT = original_root
                webapp.OUTPUT_DIR = original_output
                webapp.recent_gallery_summary = original_summary

        self.assertEqual([item["batch_id"] for item in payload["galleries"]], ["batch-000", "batch-001", "batch-002"])
        self.assertEqual(summarized, [f"batch-{index:03d}" for index in range(20)])

    def test_recent_gallery_summary_cache_reuses_until_source_changes(self):
        import scripts.person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_cache = dict(webapp.RECENT_GALLERY_SUMMARY_CACHE)
            original_read_json = webapp.read_json_if_exists
            webapp.ROOT = tmp
            webapp.RECENT_GALLERY_SUMMARY_CACHE.clear()
            (tmp / "results").mkdir()
            (tmp / "config").mkdir()
            result_path = tmp / "results/batch_person_factory_cache_test_latest.json"
            validation_path = tmp / "results/godot_lipsync_validation_cache_test_latest.json"
            run_path = tmp / "results/run_cached_lipsync_batch_cache_test.json"
            outfit_path = tmp / "config/poly_pizza_assets.json"
            result_path.write_text(
                json.dumps({"status": "ok", "jobs": [{"id": "one", "environment": {"OUTFIT_MODEL": "ship.glb"}}]}),
                encoding="utf-8",
            )
            validation_path.write_text(json.dumps({"status": "ok", "checked": []}), encoding="utf-8")
            run_path.write_text(json.dumps({"elapsed_seconds": 2.0}), encoding="utf-8")
            outfit_path.write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "id": "poly-pizza-ship",
                                "title": "Ship",
                                "output_path": "ship.glb",
                                "outfit_model": "ship.glb",
                                "license": "CC0 1.0",
                                "creator": "Test",
                                "source_url": "https://example.test/ship",
                                "quality": "ship",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            reads = []

            def counted_read(path):
                reads.append(Path(path).name)
                return original_read_json(path)

            webapp.read_json_if_exists = counted_read
            try:
                first = webapp.recent_gallery_summary("cache-test")
                second = webapp.recent_gallery_summary("cache-test")
                result_path.write_text(
                    json.dumps(
                        {
                            "status": "ok",
                            "jobs": [
                                {"id": "one", "environment": {"OUTFIT_MODEL": "ship.glb"}},
                                {"id": "two", "environment": {"OUTFIT_MODEL": "ship.glb"}},
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                third = webapp.recent_gallery_summary("cache-test")
            finally:
                webapp.ROOT = original_root
                webapp.RECENT_GALLERY_SUMMARY_CACHE.clear()
                webapp.RECENT_GALLERY_SUMMARY_CACHE.update(original_cache)
                webapp.read_json_if_exists = original_read_json

        self.assertEqual(first["character_count"], 1)
        self.assertEqual(second["character_count"], 1)
        self.assertEqual(third["character_count"], 2)
        self.assertEqual(reads.count("batch_person_factory_cache_test_latest.json"), 2)

    def test_gallery_benchmark_recommendation_uses_available_next_id(self):
        import scripts.person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_output = webapp.OUTPUT_DIR
            webapp.ROOT = tmp
            webapp.OUTPUT_DIR = tmp / "outputs/batch"
            webapp.OUTPUT_DIR.mkdir(parents=True)
            (tmp / "results").mkdir()
            (webapp.OUTPUT_DIR / "person_factory_fast.html").write_text("<html></html>", encoding="utf-8")
            (webapp.OUTPUT_DIR / "person_factory_fast-next.html").write_text("<html></html>", encoding="utf-8")

            try:
                benchmark = webapp.gallery_benchmark(
                    [
                        {
                            "batch_id": "fast",
                            "href": "person_factory_fast.html",
                            "summary": {
                        "character_count": 64,
                        "characters_per_second": 42.0,
                        "chunked": False,
                        "status": "ok",
                        "lipsync_status": "ok",
                        "review_count": 0,
                        "render_cache": {"hit_count": 4, "miss_count": 0},
                        "render_dedupe": {"source_job_count": 4},
                    },
                }
            ]
                )
            finally:
                webapp.ROOT = original_root
                webapp.OUTPUT_DIR = original_output

        self.assertEqual(benchmark["recommendation"]["batch_id"], "fast-next-002")
        self.assertTrue(benchmark["recommendation"]["cache_ready"])

    def test_gallery_benchmark_recommendation_exposes_queue_chunk_plan(self):
        import scripts.person_factory_webapp as webapp

        original_max_batch = webapp.max_batch_jobs
        original_max_chunked = webapp.max_chunked_matrix_jobs
        webapp.max_batch_jobs = lambda: 24
        webapp.max_chunked_matrix_jobs = lambda: 256
        try:
            benchmark = webapp.gallery_benchmark(
                [
                    {
                        "batch_id": "ship-published",
                        "mtime": 20,
                        "href": "person_factory_ship-published.html",
                        "summary": {
                            "character_count": 256,
                            "characters_per_second": 2.25,
                            "elapsed_seconds": 113.6,
                            "chunked": True,
                            "status": "ok",
                            "lipsync_status": "ok",
                            "review_count": 0,
                            "ship_compatible": True,
                        },
                    },
                    {
                        "batch_id": "ship-fast",
                        "mtime": 10,
                        "href": "person_factory_ship-fast.html",
                        "summary": {
                            "character_count": 256,
                            "characters_per_second": 37.0,
                            "chunked": False,
                            "status": "ok",
                            "lipsync_status": "ok",
                            "review_count": 0,
                            "render_cache": {"hit_count": 40, "miss_count": 0},
                            "render_dedupe": {"source_job_count": 40},
                        },
                    }
                ]
            )
        finally:
            webapp.max_batch_jobs = original_max_batch
            webapp.max_chunked_matrix_jobs = original_max_chunked

        recommendation = benchmark["recommendation"]
        self.assertFalse(recommendation["chunked"])
        self.assertTrue(recommendation["fast_publish"])
        self.assertTrue(recommendation["queue_chunked"])
        self.assertEqual(recommendation["queue_chunk_count"], 11)
        self.assertEqual(recommendation["queue_chunk_size"], 24)
        self.assertFalse(recommendation["queue_fast_publish"])
        self.assertTrue(recommendation["queue_publish_combined"])
        self.assertEqual(recommendation["queue_reference_batch_id"], "ship-published")
        self.assertEqual(recommendation["queue_reference_elapsed_seconds"], 113.6)
        self.assertEqual(recommendation["queue_reference_characters_per_second"], 2.25)
        self.assertEqual(recommendation["queue_mode"], "published-catalog")
        self.assertEqual(recommendation["queue_estimated_wall_seconds"], 113.6)
        self.assertEqual(recommendation["queue_estimate_sample_count"], 1)
        self.assertEqual(recommendation["queue_reference_orchestration_overhead_seconds"], 0)
        self.assertEqual(recommendation["queue_estimate_orchestration_overhead_seconds"], 0)

    def test_gallery_benchmark_smooths_queue_estimate_from_recent_comparable_runs(self):
        import scripts.person_factory_webapp as webapp

        original_max_batch = webapp.max_batch_jobs
        original_max_chunked = webapp.max_chunked_matrix_jobs
        webapp.max_batch_jobs = lambda: 24
        webapp.max_chunked_matrix_jobs = lambda: 256
        try:
            benchmark = webapp.gallery_benchmark(
                [
                    {
                        "batch_id": "ship-next-004",
                        "mtime": 40,
                        "href": "person_factory_ship-next-004.html",
                        "summary": {
                            "character_count": 256,
                            "characters_per_second": 5.358,
                            "elapsed_seconds": 47.781,
                            "chunked": True,
                            "status": "ok",
                            "lipsync_status": "ok",
                            "review_count": 0,
                            "ship_compatible": True,
                            "pipeline_timing": {
                                "chunk_wall_elapsed_seconds": 37.519,
                                "orchestration_overhead_seconds": 15.2,
                                "wall_elapsed_seconds": 52.719,
                            },
                        },
                    },
                    {
                        "batch_id": "ship-next-005",
                        "mtime": 50,
                        "href": "person_factory_ship-next-005.html",
                        "summary": {
                            "character_count": 256,
                            "characters_per_second": 5.132,
                            "elapsed_seconds": 49.886,
                            "chunked": True,
                            "status": "ok",
                            "lipsync_status": "ok",
                            "review_count": 0,
                            "ship_compatible": True,
                        },
                    },
                    {
                        "batch_id": "ship-next-006",
                        "mtime": 60,
                        "href": "person_factory_ship-next-006.html",
                        "summary": {
                            "character_count": 256,
                            "characters_per_second": 5.025,
                            "elapsed_seconds": 50.944,
                            "chunked": True,
                            "status": "ok",
                            "lipsync_status": "ok",
                            "review_count": 0,
                            "ship_compatible": True,
                        },
                    },
                    {
                        "batch_id": "ship-next-007",
                        "mtime": 70,
                        "href": "person_factory_ship-next-007.html",
                        "summary": {
                            "character_count": 256,
                            "characters_per_second": 4.856,
                            "elapsed_seconds": 52.719,
                            "chunked": True,
                            "status": "ok",
                            "lipsync_status": "ok",
                            "review_count": 0,
                            "ship_compatible": True,
                            "pipeline_timing": {
                                "chunk_wall_elapsed_seconds": 37.519,
                                "orchestration_overhead_seconds": 15.2,
                                "wall_elapsed_seconds": 52.719,
                            },
                        },
                    },
                    {
                        "batch_id": "ship-fast-preview",
                        "mtime": 80,
                        "href": "person_factory_ship-fast-preview.html",
                        "summary": {
                            "character_count": 256,
                            "characters_per_second": 37.0,
                            "chunked": False,
                            "status": "ok",
                            "lipsync_status": "ok",
                            "review_count": 0,
                            "ship_compatible": True,
                            "render_cache": {"hit_count": 256, "miss_count": 0},
                            "render_dedupe": {"source_job_count": 256},
                        },
                    },
                ]
            )
        finally:
            webapp.max_batch_jobs = original_max_batch
            webapp.max_chunked_matrix_jobs = original_max_chunked

        recommendation = benchmark["recommendation"]
        self.assertEqual(recommendation["queue_reference_batch_id"], "ship-next-007")
        self.assertEqual(recommendation["queue_reference_elapsed_seconds"], 52.719)
        self.assertEqual(recommendation["queue_estimate_sample_count"], 4)
        self.assertEqual(
            recommendation["queue_estimate_reference_batch_ids"],
            ["ship-next-007", "ship-next-006", "ship-next-005", "ship-next-004"],
        )
        self.assertEqual(recommendation["queue_estimated_wall_seconds"], 50.415)
        self.assertEqual(recommendation["queue_estimate_mode"], "median")
        self.assertEqual(recommendation["queue_reference_orchestration_overhead_seconds"], 15.2)
        self.assertEqual(recommendation["queue_estimate_orchestration_overhead_seconds"], 15.2)
        self.assertEqual(recommendation["queue_reference_chunk_wall_seconds"], 37.519)

    def test_gallery_benchmark_uses_latest_estimate_after_runtime_regime_change(self):
        import scripts.person_factory_webapp as webapp

        original_max_batch = webapp.max_batch_jobs
        original_max_chunked = webapp.max_chunked_matrix_jobs
        webapp.max_batch_jobs = lambda: 24
        webapp.max_chunked_matrix_jobs = lambda: 256
        galleries = [
            {
                "batch_id": "ship-next-010",
                "mtime": 100,
                "href": "person_factory_ship-next-010.html",
                "summary": {
                    "character_count": 256,
                    "characters_per_second": 6.197,
                    "elapsed_seconds": 41.308,
                    "chunked": True,
                    "status": "ok",
                    "lipsync_status": "ok",
                    "review_count": 0,
                    "ship_compatible": True,
                    "pipeline_timing": {
                        "chunk_wall_elapsed_seconds": 38.344,
                        "orchestration_overhead_seconds": 2.964,
                        "pre_chunk_overhead_seconds": 2.965,
                        "wall_elapsed_seconds": 41.308,
                    },
                },
            }
        ]
        for index, elapsed in enumerate([50.944, 52.719, 53.789, 54.301], start=6):
            galleries.append(
                {
                    "batch_id": f"ship-next-{index:03d}",
                    "mtime": index,
                    "href": f"person_factory_ship-next-{index:03d}.html",
                    "summary": {
                        "character_count": 256,
                        "characters_per_second": 4.9,
                        "elapsed_seconds": elapsed,
                        "chunked": True,
                        "status": "ok",
                        "lipsync_status": "ok",
                        "review_count": 0,
                        "ship_compatible": True,
                        "pipeline_timing": {
                            "chunk_wall_elapsed_seconds": 38.0,
                            "orchestration_overhead_seconds": 16.0,
                            "wall_elapsed_seconds": elapsed,
                        },
                    },
                }
            )
        try:
            benchmark = webapp.gallery_benchmark(galleries)
        finally:
            webapp.max_batch_jobs = original_max_batch
            webapp.max_chunked_matrix_jobs = original_max_chunked

        recommendation = benchmark["recommendation"]
        self.assertEqual(recommendation["queue_reference_batch_id"], "ship-next-010")
        self.assertEqual(recommendation["queue_estimated_wall_seconds"], 41.308)
        self.assertEqual(recommendation["queue_estimate_mode"], "latest-runtime-regime")

    def test_recent_gallery_summary_includes_pipeline_timing(self):
        import scripts.person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            webapp.ROOT = tmp
            (tmp / "results").mkdir()
            result = {
                "status": "ok",
                "jobs": [{"qa": {"grade": "A", "decision": "ship"}}],
                "pipeline_timing": {
                    "wall_elapsed_seconds": 12.0,
                    "chunk_wall_elapsed_seconds": 8.0,
                    "orchestration_overhead_seconds": 4.0,
                    "parallel_efficiency": 1.2,
                    "child_reports": [{"elapsed_seconds": 8.0, "slowest_stage": "render"}],
                },
            }
            (tmp / "results" / "batch_person_factory_ship_latest.json").write_text(
                json.dumps(result),
                encoding="utf-8",
            )
            try:
                summary = webapp.recent_gallery_summary("ship")
            finally:
                webapp.ROOT = original_root

        self.assertEqual(summary["elapsed_seconds"], 12.0)
        self.assertEqual(summary["pipeline_timing"]["chunk_wall_elapsed_seconds"], 8.0)
        self.assertEqual(summary["pipeline_timing"]["orchestration_overhead_seconds"], 4.0)

    def test_gallery_benchmark_recommendation_does_not_chain_next_suffixes(self):
        import scripts.person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_output = webapp.OUTPUT_DIR
            webapp.ROOT = tmp
            webapp.OUTPUT_DIR = tmp / "outputs/batch"
            webapp.OUTPUT_DIR.mkdir(parents=True)
            (tmp / "results").mkdir()
            (webapp.OUTPUT_DIR / "person_factory_ship-next.html").write_text("<html></html>", encoding="utf-8")

            try:
                benchmark = webapp.gallery_benchmark(
                    [
                        {
                            "batch_id": "ship-next",
                            "href": "person_factory_ship-next.html",
                            "summary": {
                                "character_count": 256,
                                "characters_per_second": 37.0,
                                "chunked": False,
                                "status": "ok",
                                "lipsync_status": "ok",
                                "review_count": 0,
                            },
                        }
                    ]
                )
            finally:
                webapp.ROOT = original_root
                webapp.OUTPUT_DIR = original_output

        self.assertEqual(benchmark["recommendation"]["batch_id"], "ship-next-002")

    def test_gallery_benchmark_ranks_newest_comparable_run(self):
        import scripts.person_factory_webapp as webapp

        benchmark = webapp.gallery_benchmark(
            [
                {
                    "batch_id": "fast-next",
                    "href": "person_factory_fast-next.html",
                    "summary": {
                        "character_count": 64,
                        "characters_per_second": 18.0,
                        "chunked": False,
                        "status": "ok",
                        "lipsync_status": "ok",
                        "review_count": 0,
                    },
                },
                {
                    "batch_id": "wide",
                    "href": "person_factory_wide.html",
                    "summary": {
                        "character_count": 256,
                        "characters_per_second": 37.0,
                        "chunked": False,
                        "status": "ok",
                        "lipsync_status": "ok",
                        "review_count": 0,
                    },
                },
                {
                    "batch_id": "fast",
                    "href": "person_factory_fast.html",
                    "summary": {
                        "character_count": 64,
                        "characters_per_second": 42.0,
                        "chunked": False,
                        "status": "ok",
                        "lipsync_status": "ok",
                        "review_count": 0,
                    },
                },
            ]
        )

        self.assertEqual(benchmark["best_throughput"]["batch_id"], "wide")
        self.assertEqual(benchmark["benchmark_sample_count"], 2)

    def test_gallery_benchmark_ignores_review_or_non_ship_sources(self):
        import scripts.person_factory_webapp as webapp

        benchmark = webapp.gallery_benchmark(
            [
                {
                    "batch_id": "old-fast",
                    "href": "person_factory_old-fast.html",
                    "summary": {
                        "character_count": 256,
                        "characters_per_second": 50.0,
                        "chunked": False,
                        "status": "ok",
                        "lipsync_status": "ok",
                        "review_count": 0,
                        "ship_compatible": False,
                    },
                },
                {
                    "batch_id": "wide-review",
                    "href": "person_factory_wide-review.html",
                    "summary": {
                        "character_count": 384,
                        "characters_per_second": 45.0,
                        "chunked": False,
                        "status": "ok",
                        "lipsync_status": "ok",
                        "review_count": 12,
                        "ship_compatible": True,
                    },
                },
                {
                    "batch_id": "clean-ship",
                    "href": "person_factory_clean-ship.html",
                    "summary": {
                        "character_count": 256,
                        "characters_per_second": 37.0,
                        "chunked": False,
                        "status": "ok",
                        "lipsync_status": "ok",
                        "review_count": 0,
                        "ship_compatible": True,
                    },
                },
            ]
        )

        self.assertEqual(benchmark["best_throughput"]["batch_id"], "clean-ship")
        self.assertEqual(benchmark["review_batches"], ["wide-review"])
        self.assertEqual(benchmark["benchmark_sample_count"], 1)

    def test_recent_gallery_summary_derives_chunked_parent_counts(self):
        import scripts.person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            results = tmp / "results"
            results.mkdir()
            (results / "batch_person_factory_parent_batch_latest.json").write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "jobs": [
                            {
                                "id": "one",
                                "qa": {"qa_grade": "A", "review_priority": "ship"},
                                "render_cache": {"status": "hit"},
                            },
                            {
                                "id": "two",
                                "qa": {"qa_grade": "B", "review_priority": "review"},
                                "render_cache": {"status": "miss"},
                            },
                            {
                                "id": "three",
                                "qa": {"qa_grade": "A", "review_priority": "ship"},
                                "render_cache": {"status": "stored"},
                            },
                        ],
                        "chunked_parent": {
                            "child_batch_ids": ["child-one", "child-two"],
                            "pipeline_timing": {
                                "wall_elapsed_seconds": 42.5,
                                "child_reports": [
                                    {"batch_id": "child-one", "elapsed_seconds": 10.0, "slowest_stage": "render"},
                                    {"batch_id": "child-two", "elapsed_seconds": 25.0, "slowest_stage": "validate"},
                                ],
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            (results / "godot_lipsync_validation_parent_batch_latest.json").write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "checked_count": 3,
                        "summary": {
                            "active_visemes": ["aa", "ee", "ih", "oh", "ou"],
                            "cue_count_min": 3,
                            "cue_count_max": 8,
                            "expression_count_min": 1,
                            "expression_count_max": 2,
                            "missing_active_viseme_counts": {},
                        },
                        "checked": [
                            {
                                "status": "ok",
                                "lipsync_quality": {"grade": "A", "source_mode": "phoneme-events"},
                            },
                            {
                                "status": "review",
                                "lipsync_quality": {"grade": "B", "source_mode": "text-fallback"},
                            },
                            {
                                "status": "ok",
                                "lipsync_quality": {"grade": "A", "source_mode": "phoneme-events"},
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (results / "godot_lipsync_validation_child_one_latest.json").write_text(
                json.dumps({"validation_cache": {"hit_count": 2, "miss_count": 1}}),
                encoding="utf-8",
            )
            (results / "godot_lipsync_validation_child_two_latest.json").write_text(
                json.dumps({"validation_cache": {"hit_count": 3, "miss_count": 4}}),
                encoding="utf-8",
            )
            (results / "render_matrix_batch_child_one.json").write_text(
                json.dumps({"render_cache": {"hit_count": 2, "miss_count": 1}}),
                encoding="utf-8",
            )
            (results / "render_matrix_batch_child_two.json").write_text(
                json.dumps({"render_cache": {"hit_count": 3, "miss_count": 4}}),
                encoding="utf-8",
            )

            original_root = webapp.ROOT
            try:
                webapp.ROOT = tmp
                summary = webapp.recent_gallery_summary("parent-batch")
            finally:
                webapp.ROOT = original_root

        self.assertEqual(summary["character_count"], 3)
        self.assertEqual(summary["qa_grades"], {"A": 2, "B": 1})
        self.assertEqual(summary["review_count"], 1)
        self.assertEqual(summary["ship_count"], 2)
        self.assertEqual(summary["lipsync_checked_count"], 3)
        self.assertEqual(summary["lipsync_grades"], {"A": 2, "B": 1})
        self.assertEqual(summary["lipsync_sources"], {"phoneme-events": 2, "text-fallback": 1})
        self.assertEqual(summary["lipsync_quality"]["active_visemes"], ["aa", "ee", "ih", "oh", "ou"])
        self.assertEqual(summary["lipsync_quality"]["cue_count_min"], 3)
        self.assertEqual(summary["lipsync_quality"]["cue_count_max"], 8)
        self.assertEqual(summary["lipsync_quality"]["expression_count_min"], 1)
        self.assertEqual(summary["lipsync_quality"]["expression_count_max"], 2)
        self.assertEqual(summary["render_cache"], {"hit_count": 5, "miss_count": 5})
        self.assertEqual(summary["elapsed_seconds"], 42.5)
        self.assertEqual(summary["slowest_stage"], "validate")
        self.assertEqual(summary["slowest_stage_seconds"], 25.0)
        self.assertEqual(summary["validation_cache"], {"hit_count": 5, "miss_count": 5})

    def test_build_phrasebank_thumbnail_batch_command_uses_current_fast_preset(self):
        from scripts.person_factory_webapp import build_phrasebank_thumbnail_batch_command

        command = build_phrasebank_thumbnail_batch_command({"batch_id": "web-thumb-016", "count": 16})

        self.assertEqual(command[:2], ["python3", "scripts/run_cached_lipsync_batch.py"])
        self.assertIn("--batch-id", command)
        self.assertIn("web-thumb-016", command)
        self.assertIn("--count", command)
        self.assertIn("16", command)
        self.assertIn("--cache-lines-json", command)
        self.assertIn("--skip-combined-refresh", command)
        self.assertIn("--gallery-detail-mode", command)
        self.assertIn("compact", command)
        self.assertNotIn("--publish-combined", command)
        self.assertNotIn("--promote-after", command)

    def test_build_phrasebank_thumbnail_batch_command_can_publish_combined(self):
        from scripts.person_factory_webapp import build_phrasebank_thumbnail_batch_command

        command = build_phrasebank_thumbnail_batch_command(
            {"batch_id": "web-thumb-008", "count": 8, "publish_combined": True}
        )

        self.assertNotIn("--skip-combined-refresh", command)
        self.assertNotIn("--gallery-detail-mode", command)

    def test_build_phrasebank_thumbnail_batch_command_can_promote_after_when_requested(self):
        from scripts.person_factory_webapp import build_phrasebank_thumbnail_batch_command

        command = build_phrasebank_thumbnail_batch_command(
            {"batch_id": "web-thumb-promote", "count": 8, "promote_after": True}
        )

        self.assertIn("--promote-after", command)

    def test_build_phrasebank_thumbnail_batch_command_allows_large_single_cached_batches(self):
        import scripts.person_factory_webapp as webapp

        original_max_batch = webapp.max_batch_jobs
        original_max_chunked = webapp.max_chunked_matrix_jobs
        webapp.max_batch_jobs = lambda: 2
        webapp.max_chunked_matrix_jobs = lambda: 6
        try:
            command = webapp.build_phrasebank_thumbnail_batch_command(
                {"batch_id": "web-thumb-large", "count": 5}
            )
        finally:
            webapp.max_batch_jobs = original_max_batch
            webapp.max_chunked_matrix_jobs = original_max_chunked

        self.assertEqual(command[:2], ["python3", "scripts/run_cached_lipsync_batch.py"])
        self.assertIn("web-thumb-large", command)
        self.assertIn("5", command)
        self.assertIn("--skip-combined-refresh", command)

    def test_build_phrasebank_thumbnail_pipeline_chunks_large_requests(self):
        import scripts.person_factory_webapp as webapp

        original_max_batch = webapp.max_batch_jobs
        original_max_chunked = webapp.max_chunked_matrix_jobs
        original_chunk_workers = webapp.cached_lipsync_chunk_workers
        original_render_workers = webapp.render_chunk_workers
        webapp.max_batch_jobs = lambda: 2
        webapp.max_chunked_matrix_jobs = lambda: 6
        webapp.cached_lipsync_chunk_workers = lambda: 4
        webapp.render_chunk_workers = lambda: 2
        try:
            pipeline = webapp.build_phrasebank_thumbnail_batch_pipeline(
                {"batch_id": "web-thumb-large", "count": 5, "chunked": True}
            )
        finally:
            webapp.max_batch_jobs = original_max_batch
            webapp.max_chunked_matrix_jobs = original_max_chunked
            webapp.cached_lipsync_chunk_workers = original_chunk_workers
            webapp.render_chunk_workers = original_render_workers

        self.assertTrue(pipeline["chunked"])
        self.assertEqual(pipeline["batch_id"], "web-thumb-large")
        self.assertEqual(pipeline["chunk_count"], 3)
        self.assertEqual([job["count"] for job in pipeline["jobs"]], [2, 2, 1])
        self.assertEqual(
            [job["batch_id"] for job in pipeline["jobs"]],
            ["web-thumb-large-chunk-001", "web-thumb-large-chunk-002", "web-thumb-large-chunk-003"],
        )
        self.assertEqual(pipeline["chunk_workers"], 2)
        self.assertTrue(all("--skip-combined-refresh" in job["command"] for job in pipeline["jobs"]))
        self.assertTrue(all("--render-profile" in job["command"] for job in pipeline["jobs"]))
        self.assertTrue(all("thumbnail_lipsync" in job["command"] for job in pipeline["jobs"]))

    def test_phrasebank_pipeline_estimate_snapshot_uses_queue_estimate(self):
        import scripts.person_factory_webapp as webapp

        original_max_batch = webapp.max_batch_jobs
        original_max_chunked = webapp.max_chunked_matrix_jobs
        webapp.max_batch_jobs = lambda: 2
        webapp.max_chunked_matrix_jobs = lambda: 6
        try:
            pipeline = webapp.build_phrasebank_thumbnail_batch_pipeline(
                {"batch_id": "web-thumb-large", "count": 5, "chunked": True}
            )
            snapshot = webapp.phrasebank_pipeline_estimate_snapshot(
                {"estimated_wall_seconds": 30.0},
                pipeline,
                worker_count=2,
            )
        finally:
            webapp.max_batch_jobs = original_max_batch
            webapp.max_chunked_matrix_jobs = original_max_chunked

        self.assertEqual(snapshot["estimated_wall_seconds"], 30.0)
        self.assertEqual(snapshot["chunk_workers"], 2)
        self.assertEqual(snapshot["chunk_size"], 2)
        self.assertEqual(snapshot["confidence"], "queue-reference")
        self.assertEqual(snapshot["warnings"], [])
        self.assertEqual([chunk["estimated_seconds"] for chunk in snapshot["chunks"]], [10.0, 10.0, 10.0])

    def test_build_phrasebank_thumbnail_pipeline_uses_full_workers_when_render_cache_ready(self):
        import scripts.person_factory_webapp as webapp

        original_max_batch = webapp.max_batch_jobs
        original_max_chunked = webapp.max_chunked_matrix_jobs
        original_chunk_workers = webapp.cached_lipsync_chunk_workers
        original_render_workers = webapp.render_chunk_workers
        webapp.max_batch_jobs = lambda: 2
        webapp.max_chunked_matrix_jobs = lambda: 6
        webapp.cached_lipsync_chunk_workers = lambda: 4
        webapp.render_chunk_workers = lambda: 2
        try:
            pipeline = webapp.build_phrasebank_thumbnail_batch_pipeline(
                {
                    "batch_id": "web-thumb-large",
                    "count": 5,
                    "chunked": True,
                    "render_cache_ready": True,
                }
            )
        finally:
            webapp.max_batch_jobs = original_max_batch
            webapp.max_chunked_matrix_jobs = original_max_chunked
            webapp.cached_lipsync_chunk_workers = original_chunk_workers
            webapp.render_chunk_workers = original_render_workers

        self.assertTrue(pipeline["chunked"])
        self.assertEqual(pipeline["chunk_workers"], 4)
        self.assertEqual(pipeline["worker_policy"], "cache-ready")

    def test_cached_lipsync_pipeline_worker_count_honors_pipeline_cap(self):
        import scripts.person_factory_webapp as webapp

        original_chunk_workers = webapp.cached_lipsync_chunk_workers
        webapp.cached_lipsync_chunk_workers = lambda: 4
        try:
            self.assertEqual(
                webapp.cached_lipsync_pipeline_worker_count({"chunk_workers": 2}, [{"id": "a"}, {"id": "b"}, {"id": "c"}]),
                2,
            )
            self.assertEqual(
                webapp.cached_lipsync_pipeline_worker_count({"chunk_workers": 99}, [{"id": "a"}, {"id": "b"}, {"id": "c"}]),
                3,
            )
            self.assertEqual(
                webapp.cached_lipsync_pipeline_worker_count({"chunk_workers": "bad"}, [{"id": "a"}, {"id": "b"}]),
                2,
            )
        finally:
            webapp.cached_lipsync_chunk_workers = original_chunk_workers

    def test_build_cached_lipsync_batch_command_uses_promoted_control_defaults(self):
        from scripts.person_factory_webapp import build_cached_lipsync_batch_command

        command = build_cached_lipsync_batch_command(
            {
                "batch_id": "web-control-001",
                "count": 2,
                "accessories": ["bowtie", "necklace"],
                "bases": ["female", "male"],
                "animations": ["talk_idle", "confident_point"],
                "text": "Cached line.",
                "audio_cache_key": "284e7c965239a326",
                "lipsync_timeline": "outputs/lipsync/cache/284e7c965239a326.face.json",
                "render_profile": "control_lipsync",
                "texture_size": 768,
                "promote_after": True,
            }
        )

        self.assertEqual(command[:2], ["python3", "scripts/run_cached_lipsync_batch.py"])
        self.assertIn("--batch-id", command)
        self.assertIn("web-control-001", command)
        self.assertIn("--accessories", command)
        self.assertIn("bowtie,necklace", command)
        self.assertIn("--render-profile", command)
        self.assertIn("control_lipsync", command)
        self.assertIn("--promote-after", command)
        self.assertIn("--godot-url", command)
        self.assertIn("http://127.0.0.1:8790", command)

    def test_build_cached_lipsync_batch_command_uses_compact_gallery_for_fast_publish(self):
        from scripts.person_factory_webapp import build_cached_lipsync_batch_command

        command = build_cached_lipsync_batch_command(
            {
                "batch_id": "web-control-fast",
                "count": 48,
                "text": "Cached line.",
                "audio_cache_key": "284e7c965239a326",
                "lipsync_timeline": "outputs/lipsync/cache/284e7c965239a326.face.json",
                "skip_combined_refresh": True,
            }
        )

        self.assertIn("--skip-combined-refresh", command)
        detail_index = command.index("--gallery-detail-mode")
        self.assertEqual(command[detail_index + 1], "compact")

    def test_build_cached_lipsync_batch_command_can_use_validation_url_pool(self):
        from scripts import person_factory_webapp as webapp

        original_environ = dict(webapp.os.environ)
        webapp.os.environ["GODOT_CONTROL_URL"] = "http://godot-primary:8790"
        webapp.os.environ["GODOT_VALIDATION_URLS"] = "http://godot-a:8790,http://godot-b:8790"
        try:
            command = webapp.build_cached_lipsync_batch_command(
                {
                    "batch_id": "web-control-validate-pool",
                    "count": 2,
                    "text": "Cached line.",
                    "audio_cache_key": "284e7c965239a326",
                    "lipsync_timeline": "outputs/lipsync/cache/284e7c965239a326.face.json",
                }
            )
        finally:
            webapp.os.environ.clear()
            webapp.os.environ.update(original_environ)

        self.assertIn("--godot-url", command)
        self.assertIn("http://godot-primary:8790", command)
        self.assertIn("--validation-urls", command)
        self.assertIn("http://godot-a:8790,http://godot-b:8790", command)

    def test_build_cached_lipsync_batch_command_rejects_timeline_outside_outputs(self):
        from scripts.person_factory_webapp import build_cached_lipsync_batch_command

        with self.assertRaises(ValueError):
            build_cached_lipsync_batch_command(
                {
                    "batch_id": "bad",
                    "count": 1,
                    "text": "Line.",
                    "audio_cache_key": "abc",
                    "lipsync_timeline": "../secret.face.json",
                }
            )

    def test_build_cached_lipsync_batch_command_accepts_multiple_cache_lines(self):
        from scripts.person_factory_webapp import build_cached_lipsync_batch_command

        cache_lines = [
            {"text": "Line one.", "audio_cache_key": "one", "timeline": "outputs/lipsync/cache/one.face.json"},
            {"text": "Line two.", "audio_cache_key": "two", "lipsync_timeline": "outputs/lipsync/cache/two.face.json"},
        ]

        command = build_cached_lipsync_batch_command(
            {
                "batch_id": "web-varied-001",
                "count": 4,
                "accessories": ["bowtie"],
                "bases": ["female"],
                "animations": ["talk_idle"],
                "text": "Fallback.",
                "audio_cache_key": "fallback",
                "lipsync_timeline": "outputs/lipsync/cache/fallback.face.json",
                "cache_lines": cache_lines,
            }
        )

        self.assertIn("--cache-lines-json", command)
        encoded = command[command.index("--cache-lines-json") + 1]
        decoded = json.loads(encoded)
        self.assertEqual(decoded[0]["audio_cache_key"], "one")
        self.assertEqual(decoded[0]["lipsync_timeline"], "outputs/lipsync/cache/one.face.json")
        self.assertEqual(decoded[1]["audio_cache_key"], "two")

    def test_best_lipsync_cache_lines_prefers_full_viseme_a_grade_entries(self):
        from scripts import person_factory_webapp as webapp

        entries = [
            {
                "text": "Missing.",
                "audio_cache_key": "missing",
                "timeline": "outputs/lipsync/cache/missing.face.json",
                "quality_grade": "A",
                "missing_active_visemes": ["ih"],
                "duration": 9.0,
            },
            {
                "text": "Timeline only.",
                "audio_cache_key": "timeline-only",
                "timeline": "outputs/lipsync/cache/timeline-only.face.json",
                "quality_grade": "A",
                "missing_active_visemes": [],
                "audio_exists": False,
                "duration": 3.0,
            },
            {
                "text": "Full.",
                "audio_cache_key": "full",
                "timeline": "outputs/lipsync/cache/full.face.json",
                "quality_grade": "A",
                "missing_active_visemes": [],
                "audio_exists": True,
                "duration": 1.5,
            },
            {
                "text": "Review.",
                "audio_cache_key": "review",
                "timeline": "outputs/lipsync/cache/review.face.json",
                "quality_grade": "C",
                "missing_active_visemes": [],
                "duration": 2.0,
            },
        ]

        selected = webapp.best_lipsync_cache_lines(entries, limit=2)

        self.assertEqual([line["audio_cache_key"] for line in selected], ["full"])
        self.assertEqual(selected[0]["lipsync_timeline"], "outputs/lipsync/cache/full.face.json")

    def test_build_cached_lipsync_batch_command_can_auto_select_cache_lines(self):
        from scripts import person_factory_webapp as webapp

        original_entries = webapp.lipsync_cache_entries
        webapp.lipsync_cache_entries = lambda: [
            {
                "text": "Full.",
                "audio_cache_key": "full",
                "timeline": "outputs/lipsync/cache/full.face.json",
                "quality_grade": "A",
                "missing_active_visemes": [],
                "duration": 1.5,
            }
        ]
        try:
            command = webapp.build_cached_lipsync_batch_command(
                {
                    "batch_id": "web-auto-lines",
                    "count": 4,
                    "text": "Fallback.",
                    "audio_cache_key": "fallback",
                    "lipsync_timeline": "outputs/lipsync/cache/fallback.face.json",
                    "auto_cache_lines": True,
                    "cache_line_count": 2,
                }
            )
        finally:
            webapp.lipsync_cache_entries = original_entries

        encoded = command[command.index("--cache-lines-json") + 1]
        decoded = json.loads(encoded)
        self.assertEqual(decoded, [{"text": "Full.", "audio_cache_key": "full", "lipsync_timeline": "outputs/lipsync/cache/full.face.json"}])

    def test_build_cached_lipsync_batch_pipeline_chunks_large_requests(self):
        import scripts.person_factory_webapp as webapp

        original_max_batch = webapp.max_batch_jobs
        original_max_chunked = webapp.max_chunked_matrix_jobs
        webapp.max_batch_jobs = lambda: 2
        webapp.max_chunked_matrix_jobs = lambda: 6
        try:
            pipeline = webapp.build_cached_lipsync_batch_pipeline(
                {
                    "batch_id": "web-chunked",
                    "count": 5,
                    "chunked_cached_lipsync": True,
                    "accessories": ["bowtie"],
                    "bases": ["female"],
                    "animations": ["talk_idle"],
                    "text": "Fallback.",
                    "audio_cache_key": "fallback",
                    "lipsync_timeline": "outputs/lipsync/cache/fallback.face.json",
                    "cache_lines": [
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
                }
            )
        finally:
            webapp.max_batch_jobs = original_max_batch
            webapp.max_chunked_matrix_jobs = original_max_chunked

        self.assertTrue(pipeline["chunked"])
        self.assertEqual(pipeline["batch_id"], "web-chunked")
        self.assertEqual([job["count"] for job in pipeline["jobs"]], [2, 2, 1])
        self.assertEqual(
            [job["batch_id"] for job in pipeline["jobs"]],
            ["web-chunked-chunk-001", "web-chunked-chunk-002", "web-chunked-chunk-003"],
        )
        self.assertIn("--start-index", pipeline["jobs"][1]["command"])
        self.assertIn("3", pipeline["jobs"][1]["command"])
        self.assertTrue(all("--skip-combined-refresh" in job["command"] for job in pipeline["jobs"]))
        self.assertTrue(all("--skip-godot-export" not in job["command"] for job in pipeline["jobs"]))

    def test_build_cached_lipsync_batch_pipeline_can_defer_child_godot_export(self):
        import scripts.person_factory_webapp as webapp

        original_max_batch = webapp.max_batch_jobs
        original_max_chunked = webapp.max_chunked_matrix_jobs
        webapp.max_batch_jobs = lambda: 2
        webapp.max_chunked_matrix_jobs = lambda: 6
        try:
            pipeline = webapp.build_cached_lipsync_batch_pipeline(
                {
                    "batch_id": "web-defer",
                    "count": 3,
                    "chunked_cached_lipsync": True,
                    "defer_godot_export": True,
                    "accessories": ["bowtie"],
                    "bases": ["female"],
                    "animations": ["talk_idle"],
                    "text": "Fallback.",
                    "audio_cache_key": "fallback",
                    "lipsync_timeline": "outputs/lipsync/cache/fallback.face.json",
                }
            )
        finally:
            webapp.max_batch_jobs = original_max_batch
            webapp.max_chunked_matrix_jobs = original_max_chunked

        self.assertTrue(all("--skip-godot-export" in job["command"] for job in pipeline["jobs"]))

    def test_build_cached_lipsync_batch_pipeline_balances_large_chunks(self):
        import scripts.person_factory_webapp as webapp

        original_max_batch = webapp.max_batch_jobs
        original_max_chunked = webapp.max_chunked_matrix_jobs
        webapp.max_batch_jobs = lambda: 24
        webapp.max_chunked_matrix_jobs = lambda: 96
        try:
            pipeline = webapp.build_cached_lipsync_batch_pipeline(
                {
                    "batch_id": "balanced",
                    "count": 25,
                    "chunked_cached_lipsync": True,
                    "accessories": ["bowtie"],
                    "bases": ["female"],
                    "animations": ["talk_idle"],
                    "text": "Fallback.",
                    "audio_cache_key": "fallback",
                    "lipsync_timeline": "outputs/lipsync/cache/fallback.face.json",
                }
            )
        finally:
            webapp.max_batch_jobs = original_max_batch
            webapp.max_chunked_matrix_jobs = original_max_chunked

        self.assertEqual(pipeline["chunk_size"], 13)
        self.assertEqual(pipeline["chunk_count"], 2)
        self.assertEqual([job["count"] for job in pipeline["jobs"]], [13, 12])
        self.assertTrue(all(job["count"] <= 24 for job in pipeline["jobs"]))

    def test_non_chunked_cached_lipsync_batch_keeps_combined_refresh(self):
        import scripts.person_factory_webapp as webapp

        pipeline = webapp.build_cached_lipsync_batch_pipeline(
            {
                "batch_id": "web-single",
                "count": 1,
                "accessories": ["bowtie"],
                "bases": ["female"],
                "animations": ["talk_idle"],
                "text": "Fallback.",
                "audio_cache_key": "fallback",
                "lipsync_timeline": "outputs/lipsync/cache/fallback.face.json",
                "chunked_cached_lipsync": False,
            }
        )

        self.assertFalse(pipeline["chunked"])
        self.assertNotIn("--skip-combined-refresh", pipeline["jobs"][0]["command"])
        self.assertNotIn("--skip-godot-export", pipeline["jobs"][0]["command"])

    def test_non_chunked_cached_lipsync_batch_can_use_fast_publish_large_limit(self):
        import scripts.person_factory_webapp as webapp

        original_max_batch = webapp.max_batch_jobs
        original_max_chunked = webapp.max_chunked_matrix_jobs
        webapp.max_batch_jobs = lambda: 2
        webapp.max_chunked_matrix_jobs = lambda: 6
        try:
            pipeline = webapp.build_cached_lipsync_batch_pipeline(
                {
                    "batch_id": "web-fast-single",
                    "count": 5,
                    "accessories": ["bowtie"],
                    "bases": ["female"],
                    "animations": ["talk_idle"],
                    "text": "Fallback.",
                    "audio_cache_key": "fallback",
                    "lipsync_timeline": "outputs/lipsync/cache/fallback.face.json",
                    "chunked_cached_lipsync": False,
                    "skip_combined_refresh": True,
                }
            )
        finally:
            webapp.max_batch_jobs = original_max_batch
            webapp.max_chunked_matrix_jobs = original_max_chunked

        self.assertFalse(pipeline["chunked"])
        self.assertEqual(pipeline["chunk_size"], 5)
        self.assertEqual(pipeline["chunk_count"], 1)
        self.assertEqual(pipeline["jobs"][0]["count"], 5)
        self.assertIn("--skip-combined-refresh", pipeline["jobs"][0]["command"])
        self.assertNotIn("--skip-godot-export", pipeline["jobs"][0]["command"])

    def test_estimate_cached_lipsync_batch_uses_recent_run_reports(self):
        import scripts.person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_max_batch = webapp.max_batch_jobs
            original_max_chunked = webapp.max_chunked_matrix_jobs
            original_chunk_workers = webapp.cached_lipsync_chunk_workers
            webapp.ROOT = tmp
            webapp.max_batch_jobs = lambda: 2
            webapp.max_chunked_matrix_jobs = lambda: 6
            webapp.cached_lipsync_chunk_workers = lambda: 2
            (tmp / "results").mkdir(parents=True)
            (tmp / "outputs/lipsync/cache").mkdir(parents=True)
            (tmp / "outputs/lipsync/cache/fallback.face.json").write_text("{}", encoding="utf-8")
            for name, count, elapsed in (("one", 1, 12.0), ("two", 2, 18.0)):
                (tmp / "results" / f"run_cached_lipsync_batch_{name}.json").write_text(
                    json.dumps(
                        {
                            "batch_id": name,
                            "elapsed_seconds": elapsed,
                            "publish_combined": False,
                            "validation": {"checked_count": count},
                            "stage_summary": {"slowest_stage": "render"},
                        }
                    ),
                    encoding="utf-8",
                )
            try:
                estimate = webapp.estimate_cached_lipsync_batch(
                    {
                        "batch_id": "web-estimate",
                        "count": 5,
                        "chunked_cached_lipsync": True,
                        "accessories": ["bowtie"],
                        "bases": ["female"],
                        "animations": ["talk_idle"],
                        "text": "Fallback.",
                        "audio_cache_key": "fallback",
                        "lipsync_timeline": "outputs/lipsync/cache/fallback.face.json",
                    }
                )
            finally:
                webapp.ROOT = original_root
                webapp.max_batch_jobs = original_max_batch
                webapp.max_chunked_matrix_jobs = original_max_chunked
                webapp.cached_lipsync_chunk_workers = original_chunk_workers

        self.assertEqual(estimate["status"], "ok")
        self.assertEqual(estimate["count"], 5)
        self.assertEqual(estimate["chunk_count"], 3)
        self.assertEqual(estimate["chunk_workers"], 2)
        self.assertEqual([chunk["count"] for chunk in estimate["chunks"]], [2, 2, 1])
        self.assertEqual([chunk["estimated_seconds"] for chunk in estimate["chunks"]], [18.0, 18.0, 12.0])
        self.assertEqual(estimate["estimated_serial_seconds"], 48.0)
        self.assertEqual(estimate["estimated_wall_seconds"], 30.0)
        self.assertEqual(estimate["estimated_parallel_efficiency"], 1.6)
        self.assertEqual(
            [(option["workers"], option["estimated_wall_seconds"]) for option in estimate["worker_options"]],
            [(1, 48.0), (2, 30.0), (3, 18.0)],
        )
        self.assertEqual(estimate["confidence"], "sampled")
        self.assertEqual(estimate["warnings"], [])

    def test_estimate_cached_lipsync_batch_prefers_deduped_timing_samples(self):
        import scripts.person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_max_batch = webapp.max_batch_jobs
            original_max_chunked = webapp.max_chunked_matrix_jobs
            original_chunk_workers = webapp.cached_lipsync_chunk_workers
            webapp.ROOT = tmp
            webapp.max_batch_jobs = lambda: 24
            webapp.max_chunked_matrix_jobs = lambda: 192
            webapp.cached_lipsync_chunk_workers = lambda: 4
            (tmp / "results").mkdir(parents=True)
            (tmp / "outputs/lipsync/cache").mkdir(parents=True)
            (tmp / "outputs/lipsync/cache/fallback.face.json").write_text("{}", encoding="utf-8")
            (tmp / "results/run_cached_lipsync_batch_old.json").write_text(
                json.dumps(
                    {
                        "batch_id": "old",
                        "elapsed_seconds": 170.0,
                        "validation": {"checked_count": 24},
                    }
                ),
                encoding="utf-8",
            )
            (tmp / "results/run_cached_lipsync_batch_new.json").write_text(
                json.dumps(
                    {
                        "batch_id": "new",
                        "elapsed_seconds": 50.0,
                        "validation": {"checked_count": 24},
                        "paths": {"matrix_report": "results/render_matrix_batch_new.json"},
                    }
                ),
                encoding="utf-8",
            )
            (tmp / "results/render_matrix_batch_new.json").write_text(
                json.dumps(
                    {
                        "render_dedupe": {
                            "status": "materialized",
                            "materialized_duplicate_count": 18,
                        }
                    }
                ),
                encoding="utf-8",
            )
            try:
                estimate = webapp.estimate_cached_lipsync_batch(
                    {
                        "batch_id": "web-dedupe-estimate",
                        "count": 96,
                        "chunked_cached_lipsync": True,
                        "accessories": ["bowtie"],
                        "bases": ["female"],
                        "animations": ["talk_idle"],
                        "text": "Fallback.",
                        "audio_cache_key": "fallback",
                        "lipsync_timeline": "outputs/lipsync/cache/fallback.face.json",
                    }
                )
            finally:
                webapp.ROOT = original_root
                webapp.max_batch_jobs = original_max_batch
                webapp.max_chunked_matrix_jobs = original_max_chunked
                webapp.cached_lipsync_chunk_workers = original_chunk_workers

        self.assertEqual(estimate["timing_model"], "render-deduped")
        self.assertEqual(estimate["chunks"][0]["estimated_seconds"], 50.0)
        self.assertEqual(estimate["chunks"][0]["sample_count"], 1)
        self.assertEqual(estimate["estimated_wall_seconds"], 50.0)

    def test_estimate_cached_lipsync_batch_scales_from_nearest_deduped_large_sample(self):
        import scripts.person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_max_batch = webapp.max_batch_jobs
            original_max_chunked = webapp.max_chunked_matrix_jobs
            original_chunk_workers = webapp.cached_lipsync_chunk_workers
            webapp.ROOT = tmp
            webapp.max_batch_jobs = lambda: 24
            webapp.max_chunked_matrix_jobs = lambda: 192
            webapp.cached_lipsync_chunk_workers = lambda: 4
            (tmp / "results").mkdir(parents=True)
            (tmp / "outputs/lipsync/cache").mkdir(parents=True)
            (tmp / "outputs/lipsync/cache/fallback.face.json").write_text("{}", encoding="utf-8")
            (tmp / "results/run_cached_lipsync_batch_small_old.json").write_text(
                json.dumps(
                    {
                        "batch_id": "small-old",
                        "elapsed_seconds": 120.0,
                        "validation": {"checked_count": 24},
                    }
                ),
                encoding="utf-8",
            )
            (tmp / "results/run_cached_lipsync_batch_dedupe096.json").write_text(
                json.dumps(
                    {
                        "batch_id": "dedupe096",
                        "elapsed_seconds": 5.5,
                        "validation": {"checked_count": 96},
                        "paths": {"matrix_report": "results/render_matrix_batch_dedupe096.json"},
                    }
                ),
                encoding="utf-8",
            )
            (tmp / "results/render_matrix_batch_dedupe096.json").write_text(
                json.dumps(
                    {
                        "render_dedupe": {
                            "status": "materialized",
                            "materialized_duplicate_count": 90,
                            "source_request_count": 6,
                        }
                    }
                ),
                encoding="utf-8",
            )
            try:
                estimate = webapp.estimate_cached_lipsync_batch(
                    {
                        "batch_id": "web-dedupe-scale-estimate",
                        "count": 192,
                        "chunked_cached_lipsync": False,
                        "skip_combined_refresh": True,
                        "accessories": ["bowtie"],
                        "bases": ["female"],
                        "animations": ["talk_idle"],
                        "text": "Fallback.",
                        "audio_cache_key": "fallback",
                        "lipsync_timeline": "outputs/lipsync/cache/fallback.face.json",
                    }
                )
            finally:
                webapp.ROOT = original_root
                webapp.max_batch_jobs = original_max_batch
                webapp.max_chunked_matrix_jobs = original_max_chunked
                webapp.cached_lipsync_chunk_workers = original_chunk_workers

        self.assertFalse(estimate["chunked"])
        self.assertEqual(estimate["timing_model"], "render-deduped")
        self.assertEqual(estimate["warnings"], ["deduped-count-scaled"])
        self.assertEqual(estimate["estimated_wall_seconds"], 11.0)
        self.assertEqual(estimate["chunks"][0]["count"], 192)
        self.assertEqual(estimate["chunks"][0]["estimated_seconds"], 11.0)
        self.assertEqual(estimate["chunks"][0]["confidence"], "scaled-deduped-sample")
        self.assertEqual(estimate["chunks"][0]["source_sample_count"], 96)
        self.assertEqual(estimate["chunks"][0]["sample_count"], 0)

    def test_estimate_cached_lipsync_batch_warns_on_extrapolated_large_chunks(self):
        import scripts.person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_max_batch = webapp.max_batch_jobs
            original_max_chunked = webapp.max_chunked_matrix_jobs
            original_chunk_workers = webapp.cached_lipsync_chunk_workers
            webapp.ROOT = tmp
            webapp.max_batch_jobs = lambda: 24
            webapp.max_chunked_matrix_jobs = lambda: 96
            webapp.cached_lipsync_chunk_workers = lambda: 1
            (tmp / "results").mkdir(parents=True)
            (tmp / "outputs/lipsync/cache").mkdir(parents=True)
            (tmp / "outputs/lipsync/cache/fallback.face.json").write_text("{}", encoding="utf-8")
            (tmp / "results/run_cached_lipsync_batch_one.json").write_text(
                json.dumps(
                    {
                        "batch_id": "one",
                        "elapsed_seconds": 12.0,
                        "validation": {"checked_count": 1},
                    }
                ),
                encoding="utf-8",
            )
            try:
                estimate = webapp.estimate_cached_lipsync_batch(
                    {
                        "batch_id": "web-estimate-large",
                        "count": 25,
                        "chunked_cached_lipsync": True,
                        "accessories": ["bowtie"],
                        "bases": ["female"],
                        "animations": ["talk_idle"],
                        "text": "Fallback.",
                        "audio_cache_key": "fallback",
                        "lipsync_timeline": "outputs/lipsync/cache/fallback.face.json",
                    }
                )
            finally:
                webapp.ROOT = original_root
                webapp.max_batch_jobs = original_max_batch
                webapp.max_chunked_matrix_jobs = original_max_chunked
                webapp.cached_lipsync_chunk_workers = original_chunk_workers

        self.assertEqual(estimate["chunk_count"], 2)
        self.assertEqual(estimate["chunk_workers"], 1)
        self.assertEqual(estimate["confidence"], "extrapolated")
        self.assertIn("chunk-count-extrapolated", estimate["warnings"])
        self.assertEqual(estimate["recommendations"][0]["type"], "enable-parallel-chunks")
        self.assertIn("WEBAPP_MAX_CONCURRENT_JOBS=2", estimate["recommendations"][0]["command"])
        self.assertEqual(estimate["chunk_size"], 13)
        self.assertEqual([chunk["count"] for chunk in estimate["chunks"]], [13, 12])
        self.assertEqual(estimate["recommendations"][0]["estimated_wall_seconds"], 156.0)
        self.assertEqual(estimate["recommendations"][0]["estimated_saved_seconds"], 144.0)
        self.assertEqual(estimate["worker_options"][1]["workers"], 2)
        self.assertEqual(estimate["worker_options"][1]["estimated_wall_seconds"], 156.0)

    def test_estimate_cached_lipsync_batch_omits_parallel_recommendation_when_workers_active(self):
        import scripts.person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_max_batch = webapp.max_batch_jobs
            original_max_chunked = webapp.max_chunked_matrix_jobs
            original_chunk_workers = webapp.cached_lipsync_chunk_workers
            webapp.ROOT = tmp
            webapp.max_batch_jobs = lambda: 24
            webapp.max_chunked_matrix_jobs = lambda: 96
            webapp.cached_lipsync_chunk_workers = lambda: 2
            (tmp / "results").mkdir(parents=True)
            (tmp / "outputs/lipsync/cache").mkdir(parents=True)
            (tmp / "outputs/lipsync/cache/fallback.face.json").write_text("{}", encoding="utf-8")
            try:
                estimate = webapp.estimate_cached_lipsync_batch(
                    {
                        "batch_id": "web-estimate-parallel-active",
                        "count": 25,
                        "chunked_cached_lipsync": True,
                        "accessories": ["bowtie"],
                        "bases": ["female"],
                        "animations": ["talk_idle"],
                        "text": "Fallback.",
                        "audio_cache_key": "fallback",
                        "lipsync_timeline": "outputs/lipsync/cache/fallback.face.json",
                    }
                )
            finally:
                webapp.ROOT = original_root
                webapp.max_batch_jobs = original_max_batch
                webapp.max_chunked_matrix_jobs = original_max_chunked
                webapp.cached_lipsync_chunk_workers = original_chunk_workers

        self.assertEqual(estimate["chunk_workers"], 2)
        self.assertEqual(estimate["recommendations"], [])
        self.assertEqual([chunk["count"] for chunk in estimate["chunks"]], [13, 12])
        self.assertEqual(estimate["estimated_wall_seconds"], 170.0)
        self.assertEqual(estimate["chunks"][0]["confidence"], "extrapolated")

    def test_cached_lipsync_batch_pipeline_runner_runs_child_chunks(self):
        from scripts import person_factory_webapp as webapp
        from scripts.person_factory_jobs import JobStore

        with tempfile.TemporaryDirectory() as tmp_dir:
            original_store = webapp.JOB_STORE
            original_log_dir = webapp.LOG_DIR
            original_run_job = webapp.run_job
            webapp.JOB_STORE = JobStore(Path(tmp_dir) / "jobs.json")
            webapp.LOG_DIR = Path(tmp_dir) / "logs"
            ran = []

            def pass_child(job_id, _command):
                ran.append(job_id)
                webapp.JOB_STORE.update_job(job_id, status="ok", returncode=0)

            webapp.run_job = pass_child
            try:
                webapp.JOB_STORE.create_job(
                    {"id": "pipeline-test", "text": "pipeline", "name": "pipeline"},
                    ["pipeline"],
                )
                pipeline = {
                    "jobs": [
                        {"request": {"id": "chunk-001", "text": "chunk"}, "command": ["true"]},
                        {"request": {"id": "chunk-002", "text": "chunk"}, "command": ["true"]},
                    ],
                }

                webapp.run_cached_lipsync_batch_pipeline("pipeline-test", pipeline)

                parent = webapp.JOB_STORE.get_job("pipeline-test")
            finally:
                webapp.JOB_STORE = original_store
                webapp.LOG_DIR = original_log_dir
                webapp.run_job = original_run_job

        self.assertEqual(parent["status"], "ok")
        self.assertEqual(parent["child_job_ids"], ["chunk-001", "chunk-002"])
        self.assertEqual(ran, ["chunk-001", "chunk-002"])

    def test_cached_lipsync_batch_pipeline_can_run_child_chunks_in_parallel(self):
        from scripts import person_factory_webapp as webapp
        from scripts.person_factory_jobs import JobStore

        with tempfile.TemporaryDirectory() as tmp_dir:
            original_store = webapp.JOB_STORE
            original_log_dir = webapp.LOG_DIR
            original_run_job = webapp.run_job
            original_chunk_workers = webapp.cached_lipsync_chunk_workers
            webapp.JOB_STORE = JobStore(Path(tmp_dir) / "jobs.json")
            webapp.LOG_DIR = Path(tmp_dir) / "logs"
            webapp.cached_lipsync_chunk_workers = lambda: 2
            lock = threading.Lock()
            active = 0
            max_active = 0

            def pass_child(job_id, _command):
                nonlocal active, max_active
                with lock:
                    active += 1
                    max_active = max(max_active, active)
                time.sleep(0.04)
                with lock:
                    active -= 1
                webapp.JOB_STORE.update_job(job_id, status="ok", returncode=0)

            webapp.run_job = pass_child
            try:
                webapp.JOB_STORE.create_job(
                    {"id": "pipeline-parallel", "text": "pipeline", "name": "pipeline"},
                    ["pipeline"],
                )
                pipeline = {
                    "jobs": [
                        {"request": {"id": "chunk-a", "text": "chunk"}, "command": ["true"]},
                        {"request": {"id": "chunk-b", "text": "chunk"}, "command": ["true"]},
                        {"request": {"id": "chunk-c", "text": "chunk"}, "command": ["true"]},
                    ],
                }

                webapp.run_cached_lipsync_batch_pipeline("pipeline-parallel", pipeline)

                parent = webapp.JOB_STORE.get_job("pipeline-parallel")
            finally:
                webapp.JOB_STORE = original_store
                webapp.LOG_DIR = original_log_dir
                webapp.run_job = original_run_job
                webapp.cached_lipsync_chunk_workers = original_chunk_workers

        self.assertEqual(parent["status"], "ok")
        self.assertEqual(parent["child_job_ids"], ["chunk-a", "chunk-b", "chunk-c"])
        self.assertEqual(parent["chunk_workers"], 2)
        self.assertGreaterEqual(max_active, 2)

    def test_cached_lipsync_batch_pipeline_records_parent_timing_summary(self):
        from scripts import person_factory_webapp as webapp
        from scripts.person_factory_jobs import JobStore

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_store = webapp.JOB_STORE
            original_log_dir = webapp.LOG_DIR
            original_run_job = webapp.run_job
            original_chunk_workers = webapp.cached_lipsync_chunk_workers
            webapp.ROOT = tmp
            webapp.JOB_STORE = JobStore(tmp / "jobs.json")
            webapp.LOG_DIR = tmp / "logs"
            webapp.cached_lipsync_chunk_workers = lambda: 1
            (tmp / "results").mkdir(parents=True)

            def pass_child(job_id, _command):
                batch_id = job_id.removesuffix("-cached-lipsync")
                report_path = tmp / "results" / f"run_cached_lipsync_batch_{batch_id.replace('-', '_')}.json"
                report_path.write_text(
                    json.dumps(
                        {
                            "batch_id": batch_id,
                            "elapsed_seconds": 3.5,
                            "publish_combined": False,
                            "stage_summary": {"slowest_stage": "render"},
                        }
                    ),
                    encoding="utf-8",
                )
                webapp.JOB_STORE.update_job(job_id, status="ok", returncode=0)

            webapp.run_job = pass_child
            try:
                webapp.JOB_STORE.create_job(
                    {"id": "pipeline-timing", "text": "pipeline", "name": "pipeline"},
                    ["pipeline"],
                )
                pipeline = {
                    "jobs": [
                        {"batch_id": "demo-chunk-001", "request": {"id": "demo-chunk-001-cached-lipsync", "text": "chunk"}, "command": ["true"]},
                        {"batch_id": "demo-chunk-002", "request": {"id": "demo-chunk-002-cached-lipsync", "text": "chunk"}, "command": ["true"]},
                    ],
                }

                webapp.run_cached_lipsync_batch_pipeline("pipeline-timing", pipeline)

                parent = webapp.JOB_STORE.get_job("pipeline-timing")
            finally:
                webapp.ROOT = original_root
                webapp.JOB_STORE = original_store
                webapp.LOG_DIR = original_log_dir
                webapp.run_job = original_run_job
                webapp.cached_lipsync_chunk_workers = original_chunk_workers

        timing = parent["pipeline_timing"]
        self.assertEqual(parent["status"], "ok")
        self.assertEqual(timing["child_elapsed_seconds"], 7.0)
        self.assertEqual(timing["child_report_count"], 2)
        self.assertGreaterEqual(timing["wall_elapsed_seconds"], 0)
        self.assertGreaterEqual(timing["chunk_wall_elapsed_seconds"], 0)
        self.assertIn("orchestration_overhead_seconds", timing)
        self.assertIn("pre_chunk_overhead_seconds", timing)
        self.assertIn("timing_summary_seconds", timing)
        self.assertEqual(timing["child_reports"][0]["batch_id"], "demo-chunk-001")
        self.assertEqual(timing["child_reports"][0]["slowest_stage"], "render")

    def test_cached_lipsync_batch_pipeline_records_estimate_accuracy(self):
        from scripts import person_factory_webapp as webapp
        from scripts.person_factory_jobs import JobStore

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_store = webapp.JOB_STORE
            original_log_dir = webapp.LOG_DIR
            original_run_job = webapp.run_job
            original_chunk_workers = webapp.cached_lipsync_chunk_workers
            webapp.ROOT = tmp
            webapp.JOB_STORE = JobStore(tmp / "jobs.json")
            webapp.LOG_DIR = tmp / "logs"
            webapp.cached_lipsync_chunk_workers = lambda: 2
            (tmp / "results").mkdir(parents=True)

            def pass_child(job_id, _command):
                batch_id = job_id.removesuffix("-cached-lipsync")
                report_path = tmp / "results" / f"run_cached_lipsync_batch_{batch_id.replace('-', '_')}.json"
                report_path.write_text(
                    json.dumps(
                        {
                            "batch_id": batch_id,
                            "elapsed_seconds": 40.0,
                            "publish_combined": False,
                            "validation": {"status": "ok", "checked_count": 4},
                        }
                    ),
                    encoding="utf-8",
                )
                webapp.JOB_STORE.update_job(job_id, status="ok", returncode=0)

            webapp.run_job = pass_child
            try:
                webapp.JOB_STORE.create_job(
                    {"id": "pipeline-estimate", "text": "pipeline", "name": "pipeline"},
                    ["pipeline"],
                )
                pipeline = {
                    "estimate_snapshot": {"estimated_wall_seconds": 100.0},
                    "jobs": [
                        {
                            "batch_id": "estimate-parent-chunk-001",
                            "request": {"id": "estimate-parent-chunk-001-cached-lipsync", "text": "chunk"},
                            "command": ["true"],
                        },
                        {
                            "batch_id": "estimate-parent-chunk-002",
                            "request": {"id": "estimate-parent-chunk-002-cached-lipsync", "text": "chunk"},
                            "command": ["true"],
                        },
                    ],
                }

                webapp.run_cached_lipsync_batch_pipeline("pipeline-estimate", pipeline)

                parent = webapp.JOB_STORE.get_job("pipeline-estimate")
            finally:
                webapp.ROOT = original_root
                webapp.JOB_STORE = original_store
                webapp.LOG_DIR = original_log_dir
                webapp.run_job = original_run_job
                webapp.cached_lipsync_chunk_workers = original_chunk_workers

        accuracy = parent["estimate_accuracy"]
        self.assertEqual(accuracy["estimated_wall_seconds"], 100.0)
        self.assertLess(accuracy["actual_wall_seconds"], 100.0)
        self.assertLess(accuracy["actual_to_estimate_ratio"], 0.8)
        self.assertEqual(accuracy["estimate_status"], "fast")

    def test_run_job_skips_auto_combined_refresh_for_chunk_children(self):
        from scripts import person_factory_webapp as webapp
        from scripts.person_factory_jobs import JobStore

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_store = webapp.JOB_STORE
            original_log_dir = webapp.LOG_DIR
            original_root = webapp.ROOT
            webapp.JOB_STORE = JobStore(tmp / "jobs.json")
            webapp.LOG_DIR = tmp / "logs"
            webapp.ROOT = tmp
            webapp.JOB_STORE.create_job({"id": "chunk-job", "text": "chunk"}, ["python3"])
            calls = []

            def fake_run(command, **_kwargs):
                calls.append(command)
                return mock.Mock(returncode=0)

            try:
                with mock.patch("scripts.person_factory_webapp.subprocess.run", side_effect=fake_run):
                    webapp.run_job("chunk-job", ["python3", "scripts/run_cached_lipsync_batch.py", "--skip-combined-refresh"])
                job = webapp.JOB_STORE.get_job("chunk-job")
            finally:
                webapp.JOB_STORE = original_store
                webapp.LOG_DIR = original_log_dir
                webapp.ROOT = original_root

        self.assertEqual(job["status"], "ok")
        self.assertEqual(calls, [["python3", "scripts/run_cached_lipsync_batch.py", "--skip-combined-refresh"]])

    def test_run_job_skips_auto_combined_refresh_for_cached_lipsync_runner(self):
        from scripts import person_factory_webapp as webapp
        from scripts.person_factory_jobs import JobStore

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_store = webapp.JOB_STORE
            original_log_dir = webapp.LOG_DIR
            original_root = webapp.ROOT
            webapp.JOB_STORE = JobStore(tmp / "jobs.json")
            webapp.LOG_DIR = tmp / "logs"
            webapp.ROOT = tmp
            webapp.JOB_STORE.create_job({"id": "cached-job", "text": "cached"}, ["python3"])
            calls = []

            def fake_run(command, **_kwargs):
                calls.append(command)
                return mock.Mock(returncode=0)

            try:
                with mock.patch("scripts.person_factory_webapp.subprocess.run", side_effect=fake_run):
                    webapp.run_job("cached-job", ["python3", "scripts/run_cached_lipsync_batch.py"])
                job = webapp.JOB_STORE.get_job("cached-job")
            finally:
                webapp.JOB_STORE = original_store
                webapp.LOG_DIR = original_log_dir
                webapp.ROOT = original_root

        self.assertEqual(job["status"], "ok")
        self.assertEqual(calls, [["python3", "scripts/run_cached_lipsync_batch.py"]])

    def test_run_job_refreshes_combined_gallery_for_regular_jobs(self):
        from scripts import person_factory_webapp as webapp
        from scripts.person_factory_jobs import JobStore

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_store = webapp.JOB_STORE
            original_log_dir = webapp.LOG_DIR
            original_root = webapp.ROOT
            webapp.JOB_STORE = JobStore(tmp / "jobs.json")
            webapp.LOG_DIR = tmp / "logs"
            webapp.ROOT = tmp
            webapp.JOB_STORE.create_job({"id": "regular-job", "text": "regular"}, ["python3"])
            calls = []

            def fake_run(command, **_kwargs):
                calls.append(command)
                return mock.Mock(returncode=0)

            try:
                with mock.patch("scripts.person_factory_webapp.subprocess.run", side_effect=fake_run):
                    webapp.run_job("regular-job", ["python3", "scripts/create_person_now.py"])
                job = webapp.JOB_STORE.get_job("regular-job")
            finally:
                webapp.JOB_STORE = original_store
                webapp.LOG_DIR = original_log_dir
                webapp.ROOT = original_root

        self.assertEqual(job["status"], "ok")
        self.assertEqual(calls[-1], ["python3", "scripts/refresh_combined_gallery.py", "--summary-only"])

    def test_build_refresh_combined_gallery_command_updates_catalog_summary(self):
        from scripts.person_factory_webapp import build_refresh_combined_gallery_command

        command = build_refresh_combined_gallery_command()

        self.assertEqual(command, ["python3", "scripts/refresh_combined_gallery.py", "--summary-only"])

    def test_build_refresh_combined_gallery_command_can_run_gallery_and_contact(self):
        from scripts.person_factory_webapp import build_refresh_combined_gallery_command

        command = build_refresh_combined_gallery_command(summary_only=False)

        self.assertEqual(command, ["python3", "scripts/refresh_combined_gallery.py"])

    def test_cached_lipsync_batch_pipeline_runner_writes_parent_gallery(self):
        from scripts import person_factory_webapp as webapp
        from scripts.person_factory_jobs import JobStore

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_output_dir = webapp.OUTPUT_DIR
            original_store = webapp.JOB_STORE
            original_log_dir = webapp.LOG_DIR
            original_run_job = webapp.run_job
            original_subprocess_run = webapp.subprocess.run
            original_post_json = webapp.post_json
            refresh_calls = []
            godot_calls = []
            webapp.ROOT = tmp
            webapp.OUTPUT_DIR = tmp / "outputs/batch"
            webapp.JOB_STORE = JobStore(tmp / "jobs.json")
            webapp.LOG_DIR = tmp / "logs"
            (tmp / "results").mkdir(parents=True)
            (tmp / "outputs/batch").mkdir(parents=True)

            def pass_child(job_id, _command):
                batch_id = job_id.removesuffix("-cached-lipsync")
                result_slug = batch_id.replace("-", "_")
                item_id = f"{batch_id}-person"
                (tmp / "results" / f"batch_person_factory_{result_slug}_latest.json").write_text(
                    json.dumps(
                        {
                            "jobs": [{"id": item_id, "status": "ok", "metadata": {"tags": []}}],
                            "elapsed_seconds": 1.0,
                        }
                    ),
                    encoding="utf-8",
                )
                (tmp / "results" / f"godot_lipsync_validation_{result_slug}_latest.json").write_text(
                    json.dumps(
                        {
                            "status": "ok",
                            "checked": [
                                {
                                    "id": item_id,
                                    "status": "ok",
                                    "cue_count": 3,
                                    "timeline": "/workspace/outputs/lipsync/cache/demo.face.json",
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                webapp.JOB_STORE.update_job(job_id, status="ok", returncode=0)

            webapp.run_job = pass_child
            webapp.subprocess.run = lambda command, cwd=None, check=False: refresh_calls.append(
                {"command": command, "cwd": cwd, "check": check}
            )
            webapp.post_json = lambda url, payload, timeout=120: godot_calls.append(
                {"url": url, "payload": payload, "timeout": timeout}
            ) or {"status": "ok", "asset_count": 2, "exported": [], "failed": []}
            try:
                webapp.JOB_STORE.create_job(
                    {"id": "pipeline-test", "text": "pipeline", "name": "pipeline"},
                    ["pipeline"],
                )
                pipeline = {
                    "batch_id": "demo",
                    "publish_combined": True,
                    "jobs": [
                        {
                            "batch_id": "demo-chunk-001",
                            "request": {"id": "demo-chunk-001-cached-lipsync", "text": "chunk"},
                            "command": ["true"],
                        },
                        {
                            "batch_id": "demo-chunk-002",
                            "request": {"id": "demo-chunk-002-cached-lipsync", "text": "chunk"},
                            "command": ["true"],
                        },
                    ],
                }

                webapp.run_cached_lipsync_batch_pipeline("pipeline-test", pipeline)

                parent = webapp.JOB_STORE.get_job("pipeline-test")
                parent_result = json.loads((tmp / "results/batch_person_factory_demo_latest.json").read_text())
                parent_gallery_exists = (tmp / "outputs/batch/person_factory_demo.html").exists()
            finally:
                webapp.ROOT = original_root
                webapp.OUTPUT_DIR = original_output_dir
                webapp.JOB_STORE = original_store
                webapp.LOG_DIR = original_log_dir
                webapp.run_job = original_run_job
                webapp.subprocess.run = original_subprocess_run
                webapp.post_json = original_post_json

        self.assertEqual(parent["status"], "ok")
        self.assertEqual(parent["parent_gallery"]["job_count"], 2)
        self.assertEqual(parent_result["source_job_count"], 2)
        self.assertTrue(parent_gallery_exists)
        self.assertEqual(refresh_calls[0]["command"], ["python3", "scripts/refresh_combined_gallery.py", "--summary-only"])
        self.assertTrue(any(call["url"].endswith("/reload-assets") for call in godot_calls))
        self.assertTrue(any(call["url"].endswith("/export-all-game-assets") for call in godot_calls))

    def test_cached_lipsync_parent_gallery_merges_chunk_results(self):
        from scripts import person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_output_dir = webapp.OUTPUT_DIR
            try:
                webapp.ROOT = tmp
                webapp.OUTPUT_DIR = tmp / "outputs/batch"
                (tmp / "results").mkdir(parents=True)
                (tmp / "outputs/batch").mkdir(parents=True)
                (tmp / "results/batch_person_factory_demo_chunk_001_latest.json").write_text(
                    '{"jobs":[{"id":"demo-001","status":"ok","metadata":{"tags":[]}}],"elapsed_seconds":1.5}',
                    encoding="utf-8",
                )
                (tmp / "results/batch_person_factory_demo_chunk_002_latest.json").write_text(
                    '{"jobs":[{"id":"demo-002","status":"ok","metadata":{"tags":[]}}],"elapsed_seconds":2.0}',
                    encoding="utf-8",
                )
                (tmp / "results/godot_lipsync_validation_demo_chunk_001_latest.json").write_text(
                    '{"status":"ok","checked":[{"id":"demo-001","status":"ok","cue_count":3,"timeline":"/workspace/outputs/lipsync/a.face.json"}]}',
                    encoding="utf-8",
                )
                (tmp / "results/godot_lipsync_validation_demo_chunk_002_latest.json").write_text(
                    '{"status":"ok","checked":[{"id":"demo-002","status":"ok","cue_count":4,"timeline":"/workspace/outputs/lipsync/b.face.json"}]}',
                    encoding="utf-8",
                )

                result = webapp.build_cached_lipsync_parent_gallery(
                    "demo",
                    ["demo-chunk-001", "demo-chunk-002"],
                    pipeline_timing={
                        "wall_elapsed_seconds": 4.0,
                        "child_elapsed_seconds": 8.0,
                        "parallel_efficiency": 2.0,
                    },
                    estimate_accuracy={
                        "estimated_wall_seconds": 5.0,
                        "actual_wall_seconds": 4.0,
                        "estimate_status": "close",
                    },
                )
                parent_result_exists = (tmp / "results/batch_person_factory_demo_latest.json").exists()
                parent_result = json.loads((tmp / "results/batch_person_factory_demo_latest.json").read_text())
                parent_gallery_exists = (tmp / "outputs/batch/person_factory_demo.html").exists()
            finally:
                webapp.ROOT = original_root
                webapp.OUTPUT_DIR = original_output_dir

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["job_count"], 2)
        self.assertEqual(result["validation"]["checked_count"], 2)
        self.assertEqual(parent_result["pipeline_timing"]["wall_elapsed_seconds"], 4.0)
        self.assertEqual(parent_result["estimate_accuracy"]["estimate_status"], "close")
        self.assertEqual(parent_result["chunked_parent"]["pipeline_timing"]["parallel_efficiency"], 2.0)
        self.assertTrue(parent_result_exists)
        self.assertTrue(parent_gallery_exists)

    def test_cached_lipsync_parent_gallery_can_export_parent_batch_to_godot(self):
        from scripts import person_factory_webapp as webapp

        calls = []
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_output_dir = webapp.OUTPUT_DIR
            original_post_json = webapp.post_json

            def fake_post_json(url, payload, timeout=120):
                calls.append((url, payload, timeout))
                return {"status": "ok", "url": url, "payload": payload}

            try:
                webapp.ROOT = tmp
                webapp.OUTPUT_DIR = tmp / "outputs/batch"
                webapp.post_json = fake_post_json
                (tmp / "results").mkdir(parents=True)
                (tmp / "outputs/batch").mkdir(parents=True)
                (tmp / "results/batch_person_factory_demo_chunk_001_latest.json").write_text(
                    '{"jobs":[{"id":"demo-001","status":"ok","metadata":{"tags":[]}},{"id":"demo-002","status":"ok","metadata":{"tags":[]}}]}',
                    encoding="utf-8",
                )
                (tmp / "results/godot_lipsync_validation_demo_chunk_001_latest.json").write_text(
                    '{"status":"ok","checked":[{"id":"demo-001","status":"ok"},{"id":"demo-002","status":"ok"}]}',
                    encoding="utf-8",
                )

                result = webapp.build_cached_lipsync_parent_gallery(
                    "demo",
                    ["demo-chunk-001"],
                    export_godot=True,
                    godot_url="http://godot.local:8790",
                )
            finally:
                webapp.ROOT = original_root
                webapp.OUTPUT_DIR = original_output_dir
                webapp.post_json = original_post_json

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["godot_export"]["status"], "ok")
        self.assertEqual(calls[0][0], "http://godot.local:8790/reload-assets")
        self.assertEqual(calls[0][1]["batch_result"], "/workspace/results/batch_person_factory_demo_latest.json")
        self.assertEqual(calls[1][0], "http://godot.local:8790/export-all-game-assets")
        self.assertEqual(calls[1][1]["asset_ids"], ["demo-001", "demo-002"])

    def test_lipsync_cache_index_discovers_text_and_timeline_entries(self):
        import scripts.person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            try:
                webapp.ROOT = tmp
                (tmp / "outputs/lipsync/cache").mkdir(parents=True)
                (tmp / "outputs/speech/cache").mkdir(parents=True)
                (tmp / "results/talking_person").mkdir(parents=True)
                (tmp / "outputs/lipsync/cache/abc123.face.json").write_text(
                    '{"duration":1.5,"cues":[{"time":0.0,"duration":0.1,"viseme":"aa"},{"time":0.1,"duration":0.1,"viseme":"ee"},{"time":0.2,"duration":0.1,"viseme":"ih"},{"time":0.3,"duration":0.1,"viseme":"oh"},{"time":0.4,"duration":0.1,"viseme":"ou"}],"expressions":[{}]}',
                    encoding="utf-8",
                )
                (tmp / "outputs/speech/cache/abc123.wav").write_bytes(b"wav")
                (tmp / "results/talking_person/cache-warm-abc.text.json").write_text(
                    '{"audio_cache_key":"abc123","text":"Cached hello","cache_paths":{"lipsync_timeline":"outputs/lipsync/cache/abc123.face.json","audio_wav":"outputs/speech/cache/abc123.wav"}}',
                    encoding="utf-8",
                )

                entries = webapp.lipsync_cache_entries()
            finally:
                webapp.ROOT = original_root

        self.assertEqual(entries[0]["audio_cache_key"], "abc123")
        self.assertEqual(entries[0]["text"], "Cached hello")
        self.assertEqual(entries[0]["cue_count"], 5)
        self.assertEqual(entries[0]["active_visemes"], ["aa", "ee", "ih", "oh", "ou"])
        self.assertEqual(entries[0]["missing_active_visemes"], [])
        self.assertEqual(entries[0]["quality_status"], "ok")
        self.assertEqual(entries[0]["quality"]["status"], "ok")
        self.assertEqual(entries[0]["quality"]["grade"], "A")
        self.assertEqual(entries[0]["quality"]["active_visemes"], ["aa", "ee", "ih", "oh", "ou"])
        self.assertEqual(entries[0]["timeline"], "outputs/lipsync/cache/abc123.face.json")

    def test_lipsync_cache_response_includes_status_and_summary(self):
        import scripts.person_factory_webapp as webapp

        entries = [
            {"audio_cache_key": "full", "quality_status": "ok", "quality_grade": "A", "missing_active_visemes": []},
            {"audio_cache_key": "review", "quality_status": "review", "quality_grade": "C", "missing_active_visemes": ["ih"]},
        ]

        response = webapp.lipsync_cache_response(entries)

        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["summary"]["entry_count"], 2)
        self.assertEqual(response["summary"]["full_viseme_count"], 1)
        self.assertEqual(response["summary"]["quality_status_counts"], {"ok": 1, "review": 1})
        self.assertEqual(response["summary"]["quality_grade_counts"], {"A": 1, "C": 1})

    def test_lipsync_cache_index_sorts_full_viseme_coverage_first(self):
        import scripts.person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            try:
                webapp.ROOT = tmp
                (tmp / "outputs/lipsync/cache").mkdir(parents=True)
                (tmp / "results/talking_person").mkdir(parents=True)
                (tmp / "outputs/lipsync/cache/full.face.json").write_text(
                    json.dumps(
                        {
                            "duration": 1.0,
                            "cues": [
                                {"time": 0.0, "duration": 0.1, "viseme": "aa"},
                                {"time": 0.1, "duration": 0.1, "viseme": "ee"},
                                {"time": 0.2, "duration": 0.1, "viseme": "ih"},
                                {"time": 0.3, "duration": 0.1, "viseme": "oh"},
                                {"time": 0.4, "duration": 0.1, "viseme": "ou"},
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                (tmp / "outputs/lipsync/cache/missing.face.json").write_text(
                    json.dumps(
                        {
                            "duration": 9.0,
                            "cues": [
                                {"time": 0.0, "duration": 0.1, "viseme": "aa"},
                                {"time": 0.1, "duration": 0.1, "viseme": "ee"},
                                {"time": 0.2, "duration": 0.1, "viseme": "oh"},
                                {"time": 0.3, "duration": 0.1, "viseme": "ou"},
                            ],
                        }
                    ),
                    encoding="utf-8",
                )

                entries = webapp.lipsync_cache_entries()
            finally:
                webapp.ROOT = original_root

        self.assertEqual(entries[0]["audio_cache_key"], "full")
        self.assertEqual(entries[0]["missing_active_visemes"], [])
        self.assertEqual(entries[1]["audio_cache_key"], "missing")
        self.assertEqual(entries[1]["missing_active_visemes"], ["ih"])

    def test_serve_gallery_uses_webapp_server(self):
        script = (ROOT / "scripts/serve_gallery.sh").read_text(encoding="utf-8")

        self.assertIn("scripts/person_factory_webapp.py", script)
        self.assertIn("WEBAPP_ROOT", script)
        self.assertNotIn("cd /workspace", script)
        self.assertNotIn("python3 -m http.server", script)

    def test_build_promote_batch_command_uses_standard_promotion_defaults(self):
        from scripts.person_factory_webapp import build_promote_batch_command

        command = build_promote_batch_command(
            {
                "batch_result": "results/batch_person_factory_control_prod_001_latest.json",
                "texture_size": 768,
            }
        )

        self.assertEqual(command[:2], ["python3", "scripts/promote_batch_assets.py"])
        self.assertIn("results/batch_person_factory_control_prod_001_latest.json", command)
        self.assertIn("--texture-size", command)
        self.assertIn("768", command)

    def test_build_promote_batch_command_rejects_paths_outside_results(self):
        from scripts.person_factory_webapp import build_promote_batch_command

        with self.assertRaises(ValueError):
            build_promote_batch_command({"batch_result": "../secret.json"})

    def test_prepare_static_links_exposes_lipsync_and_speech_outputs(self):
        source = (ROOT / "scripts/person_factory_webapp.py").read_text(encoding="utf-8")

        self.assertIn('"lipsync": "../lipsync"', source)
        self.assertIn('"speech": "../speech"', source)

    def test_catalog_options_default_to_ship_quality_accessories(self):
        from scripts import person_factory_webapp as webapp

        with patch.dict("os.environ", {}, clear=True):
            options = webapp.catalog_options()

        values = {item["value"] for item in options["accessories"]}
        self.assertIn("necklace-quaternius", values)
        self.assertNotIn("bowtie-jeremy", values)
        self.assertNotIn("heart-glasses-j-toastie", values)
        self.assertEqual(options["quality_filter"], ["ship"])

    def test_catalog_options_can_include_review_assets_for_qa(self):
        from scripts import person_factory_webapp as webapp

        with patch.dict("os.environ", {"PERSON_FACTORY_ACCESSORY_QUALITIES": "ship,review"}):
            options = webapp.catalog_options()

        values = {item["value"] for item in options["accessories"]}
        self.assertIn("bowtie-jeremy", values)
        self.assertNotIn("heart-glasses-j-toastie", values)
        self.assertEqual(options["quality_filter"], ["review", "ship"])

    def test_job_with_log_includes_generated_output_summary(self):
        from scripts import person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_output_dir = webapp.OUTPUT_DIR
            original_log_dir = webapp.LOG_DIR
            webapp.ROOT = tmp
            webapp.OUTPUT_DIR = tmp / "outputs/batch"
            webapp.LOG_DIR = tmp / "logs"

            try:
                (tmp / "results/batch").mkdir(parents=True)
                (tmp / "results/talking_person").mkdir(parents=True)
                (tmp / "outputs/batch/demo_pose_renders").mkdir(parents=True)
                (tmp / "outputs/batch_optimized").mkdir(parents=True)
                (tmp / "outputs/lipsync").mkdir(parents=True)
                (tmp / "outputs/speech").mkdir(parents=True)
                (tmp / "logs").mkdir()
                (tmp / "logs/demo.log").write_text("done\n", encoding="utf-8")

                (tmp / "outputs/batch/person_factory_demo.html").write_text("<html></html>", encoding="utf-8")
                (tmp / "outputs/batch/demo.glb").write_bytes(b"glb")
                (tmp / "outputs/batch_optimized/demo.glb").write_bytes(b"optimized")
                (tmp / "outputs/batch/demo_pose_renders/pose_portrait_0009.png").write_bytes(b"png")
                (tmp / "outputs/lipsync/demo.face.json").write_text(
                    """
                    {
                      "source": {
                        "mode": "phoneme-events",
                        "input_mode": "manual-arpabet",
                        "text": "Hello",
                        "source_schema": "vrm-person-factory.phoneme-events.v1",
                        "source_path": "config/lipsync_hello_phonemes.json",
                        "event_count": 4,
                        "phoneme_count": 4,
                        "unique_phonemes": ["AA1", "EH1", "AA1", "SIL"],
                        "phoneme_counts": {"AA1": 2, "EH1": 1, "SIL": 1}
                      },
                      "duration": 1.5,
                      "cues": [
                        {"time": 0.0, "duration": 0.1, "viseme": "aa", "value": 0.8, "source_phoneme": "AA1"},
                        {"time": 0.1, "duration": 0.1, "viseme": "ee", "value": 0.7, "source_phoneme": "EH1"},
                        {"time": 0.2, "duration": 0.1, "viseme": "aa", "value": 0.5, "source_phoneme": "AA1"},
                        {"time": 0.3, "duration": 0.1, "viseme": "rest", "value": 0.0, "source_phoneme": "SIL"}
                      ],
                      "expressions": [
                        {"time": 0.0, "duration": 0.2, "name": "happy", "value": 0.3}
                      ]
                    }
                    """,
                    encoding="utf-8",
                )
                (tmp / "outputs/speech/demo.wav").write_bytes(b"wav")
                (tmp / "results/batch/demo_animation.json").write_text(
                    """
                    {
                      "status": "ok",
                      "face_profile": {
                        "quality": {
                          "grade": "A",
                          "viseme_count": 5,
                          "expression_count": 5,
                          "missing_visemes": []
                        },
                        "visemes": {
                          "aa": {}, "ee": {}, "ih": {}, "oh": {}, "ou": {}
                        }
                      },
                      "lipsync_animation": {
                        "enabled": true,
                        "keyed_visemes": ["aa", "ee"],
                        "missing_visemes": []
                      }
                    }
                    """,
                    encoding="utf-8",
                )
                (tmp / "results/batch_person_factory_demo_latest.json").write_text(
                    """
                    {
                      "jobs": [
                        {
                          "id": "demo",
                          "status": "ok",
                          "environment": {
                            "LIPSYNC_TIMELINE_JSON": "/workspace/outputs/lipsync/demo.face.json",
                            "OUTPUT_GLB": "/workspace/outputs/batch/demo.glb"
                          },
                          "qa": {
                            "qa_grade": "A",
                            "qa_score": 100,
                            "review_priority": "ship",
                            "preferred_review_frame": "pose_portrait_0009.png"
                          }
                        }
                      ]
                    }
                    """,
                    encoding="utf-8",
                )
                (tmp / "results/run_cached_lipsync_batch_demo.json").write_text(
                    """
                    {
                      "elapsed_seconds": 12.5,
                      "stage_summary": {
                        "slowest_stage": "render",
                        "slowest_stage_seconds": 7.25,
                        "total_stage_seconds": 12.0
                      }
                    }
                    """,
                    encoding="utf-8",
                )

                enriched = webapp.job_with_log(
                    {
                        "id": "demo",
                        "status": "ok",
                        "request": {
                            "audio_wav": "outputs/speech/demo.wav",
                            "lipsync_timeline": "outputs/lipsync/demo.face.json",
                        },
                    }
                )
            finally:
                webapp.ROOT = original_root
                webapp.OUTPUT_DIR = original_output_dir
                webapp.LOG_DIR = original_log_dir

        summary = enriched["output_summary"]
        labels = {link["label"]: link["href"] for link in summary["links"]}
        self.assertTrue(summary["has_game_asset"])
        self.assertTrue(summary["has_timeline"])
        self.assertEqual(summary["review_image"], "demo_pose_renders/pose_portrait_0009.png")
        self.assertEqual(summary["qa"], {"grade": "A", "score": 100, "priority": "ship"})
        self.assertEqual(summary["lipsync"]["cue_count"], 4)
        self.assertEqual(summary["lipsync"]["duration"], 1.5)
        self.assertEqual(summary["lipsync"]["path"], "/workspace/outputs/lipsync/demo.face.json")
        self.assertEqual(summary["lipsync"]["expression_count"], 1)
        self.assertEqual(summary["lipsync"]["visemes"], ["aa", "ee", "rest"])
        self.assertEqual(summary["lipsync"]["viseme_counts"], {"aa": 2, "ee": 1, "rest": 1})
        self.assertEqual(summary["lipsync"]["missing_visemes"], [])
        self.assertEqual(summary["lipsync"]["quality"]["status"], "ok")
        self.assertEqual(summary["lipsync"]["quality"]["cue_count"], 4)
        self.assertEqual(summary["lipsync"]["source_mode"], "phoneme-events")
        self.assertEqual(summary["lipsync"]["source_event_count"], 4)
        self.assertEqual(summary["lipsync"]["source_phoneme_count"], 4)
        self.assertEqual(summary["lipsync"]["source_input_mode"], "manual-arpabet")
        self.assertEqual(summary["lipsync"]["source_text"], "Hello")
        self.assertEqual(summary["lipsync"]["source_unique_phonemes"], ["AA1", "EH1", "SIL"])
        self.assertEqual(summary["lipsync"]["quality"]["alignment"], "audio-derived")
        self.assertEqual(summary["lip_sync_readiness"]["status"], "ready")
        self.assertEqual(summary["lip_sync_readiness"]["label"], "Lip-ready")
        self.assertEqual(summary["lip_sync_readiness"]["missing_visemes"], [])
        self.assertEqual(summary["lip_sync_readiness"]["supported_visemes"], ["aa", "ee", "ih", "oh", "ou"])
        self.assertEqual(summary["batch_run"]["elapsed_seconds"], 12.5)
        self.assertEqual(summary["batch_run"]["stage_summary"]["slowest_stage"], "render")
        self.assertEqual(labels["Gallery"], "person_factory_demo.html")
        self.assertEqual(labels["Result JSON"], "results/batch_person_factory_demo_latest.json")
        self.assertEqual(labels["Animation JSON"], "results/batch/demo_animation.json")
        self.assertEqual(labels["Optimized GLB"], "batch_optimized/demo.glb")
        self.assertEqual(labels["GLB"], "demo.glb")
        self.assertEqual(labels["Review PNG"], "demo_pose_renders/pose_portrait_0009.png")
        self.assertEqual(labels["Timeline JSON"], "lipsync/demo.face.json")
        self.assertEqual(labels["Speech WAV"], "speech/demo.wav")

    def test_cache_only_output_summary_does_not_mark_game_asset(self):
        from scripts import person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_output_dir = webapp.OUTPUT_DIR
            original_log_dir = webapp.LOG_DIR
            webapp.ROOT = tmp
            webapp.OUTPUT_DIR = tmp / "outputs/batch"
            webapp.LOG_DIR = tmp / "logs"

            try:
                (tmp / "outputs/batch").mkdir(parents=True)
                (tmp / "outputs/lipsync/cache").mkdir(parents=True)
                (tmp / "outputs/speech/cache").mkdir(parents=True)
                (tmp / "logs").mkdir()
                (tmp / "outputs/lipsync/cache/line.face.json").write_text(
                    '{"duration": 2.0, "cues": [{"viseme":"oh"}, {"viseme":"ou"}], "expressions": []}',
                    encoding="utf-8",
                )
                (tmp / "outputs/speech/cache/line.wav").write_bytes(b"wav")

                enriched = webapp.job_with_log(
                    {
                        "id": "cache-only",
                        "status": "ok",
                        "request": {
                            "audio_wav": "outputs/speech/cache/line.wav",
                            "lipsync_timeline": "outputs/lipsync/cache/line.face.json",
                        },
                    }
                )
            finally:
                webapp.ROOT = original_root
                webapp.OUTPUT_DIR = original_output_dir
                webapp.LOG_DIR = original_log_dir

        summary = enriched["output_summary"]
        labels = {link["label"]: link["href"] for link in summary["links"]}
        self.assertFalse(summary["has_game_asset"])
        self.assertTrue(summary["has_timeline"])
        self.assertEqual(summary["review_image"], "")
        self.assertEqual(summary["lip_sync_readiness"]["status"], "review")
        self.assertEqual(summary["lip_sync_readiness"]["label"], "Needs lip fix")
        self.assertIn("missing-game-asset", summary["lip_sync_readiness"]["reasons"])
        self.assertEqual(summary["lipsync"]["viseme_counts"], {"oh": 1, "ou": 1})
        self.assertEqual(summary["lipsync"]["quality"]["status"], "review")
        self.assertIn("non-positive-cue-duration", summary["lipsync"]["quality"]["issues"])
        self.assertIn("aa", summary["lipsync"]["missing_visemes"])
        self.assertEqual(labels["Timeline JSON"], "lipsync/cache/line.face.json")
        self.assertEqual(labels["Speech WAV"], "speech/cache/line.wav")
        self.assertNotIn("GLB", labels)
        self.assertNotIn("Optimized GLB", labels)

    def test_pipeline_output_summary_links_parent_gallery(self):
        from scripts import person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_output_dir = webapp.OUTPUT_DIR
            original_log_dir = webapp.LOG_DIR
            webapp.ROOT = tmp
            webapp.OUTPUT_DIR = tmp / "outputs/batch"
            webapp.LOG_DIR = tmp / "logs"

            try:
                (tmp / "outputs/batch").mkdir(parents=True)
                (tmp / "results").mkdir(parents=True)
                (tmp / "logs").mkdir()
                (tmp / "outputs/batch/person_factory_demo.html").write_text("<html></html>", encoding="utf-8")
                (tmp / "results/batch_person_factory_demo_latest.json").write_text("{}", encoding="utf-8")
                (tmp / "results/godot_lipsync_validation_demo_latest.json").write_text("{}", encoding="utf-8")

                enriched = webapp.job_with_log(
                    {
                        "id": "demo-pipeline",
                        "status": "ok",
                        "request": {"name": "Chunked pipeline"},
                        "parent_gallery": {
                            "status": "ok",
                            "gallery": "outputs/batch/person_factory_demo.html",
                            "batch_result": "results/batch_person_factory_demo_latest.json",
                            "validation_result": "results/godot_lipsync_validation_demo_latest.json",
                        },
                    }
                )
            finally:
                webapp.ROOT = original_root
                webapp.OUTPUT_DIR = original_output_dir
                webapp.LOG_DIR = original_log_dir

        labels = {link["label"]: link["href"] for link in enriched["output_summary"]["links"]}
        self.assertEqual(labels["Parent Gallery"], "person_factory_demo.html")
        self.assertEqual(labels["Parent Result JSON"], "results/batch_person_factory_demo_latest.json")
        self.assertEqual(labels["Parent Lip Validation"], "results/godot_lipsync_validation_demo_latest.json")

    def test_pipeline_output_summary_includes_timing(self):
        from scripts import person_factory_webapp as webapp

        enriched = webapp.job_with_log(
            {
                "id": "demo-pipeline",
                "status": "ok",
                "request": {"name": "Chunked pipeline"},
                "pipeline_timing": {
                    "wall_elapsed_seconds": 19.2,
                    "child_elapsed_seconds": 31.7,
                    "child_report_count": 2,
                    "chunk_workers": 2,
                    "parallel_efficiency": 1.651,
                    "child_reports": [
                        {
                            "batch_id": "demo-chunk-001",
                            "elapsed_seconds": 18.6,
                            "publish_combined": False,
                            "slowest_stage": "render",
                        }
                    ],
                },
            }
        )

        timing = enriched["output_summary"]["pipeline_timing"]
        self.assertEqual(timing["wall_elapsed_seconds"], 19.2)
        self.assertEqual(timing["child_elapsed_seconds"], 31.7)
        self.assertEqual(timing["chunk_workers"], 2)
        self.assertEqual(timing["parallel_efficiency"], 1.651)
        self.assertEqual(timing["child_reports"][0]["batch_id"], "demo-chunk-001")

    def test_pipeline_output_summary_includes_estimate_accuracy(self):
        from scripts import person_factory_webapp as webapp

        enriched = webapp.job_with_log(
            {
                "id": "demo-pipeline",
                "status": "ok",
                "request": {"name": "Chunked pipeline"},
                "estimate_accuracy": {
                    "estimated_wall_seconds": 100.0,
                    "actual_wall_seconds": 90.0,
                    "error_seconds": -10.0,
                    "actual_to_estimate_ratio": 0.9,
                    "estimate_status": "close",
                },
            }
        )

        accuracy = enriched["output_summary"]["estimate_accuracy"]
        self.assertEqual(accuracy["estimated_wall_seconds"], 100.0)
        self.assertEqual(accuracy["actual_wall_seconds"], 90.0)
        self.assertEqual(accuracy["estimate_status"], "close")

    def test_pipeline_output_summary_infers_cached_lipsync_parent_gallery(self):
        from scripts import person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_output_dir = webapp.OUTPUT_DIR
            original_log_dir = webapp.LOG_DIR
            webapp.ROOT = tmp
            webapp.OUTPUT_DIR = tmp / "outputs/batch"
            webapp.LOG_DIR = tmp / "logs"

            try:
                (tmp / "outputs/batch").mkdir(parents=True)
                (tmp / "results").mkdir(parents=True)
                (tmp / "logs").mkdir()
                (tmp / "outputs/batch/person_factory_demo.html").write_text("<html></html>", encoding="utf-8")
                (tmp / "results/batch_person_factory_demo_latest.json").write_text("{}", encoding="utf-8")

                enriched = webapp.job_with_log(
                    {
                        "id": "demo-cached-lipsync-pipeline-123",
                        "status": "ok",
                        "request": {
                            "name": "Chunked pipeline",
                            "pipeline": {"type": "cached-lipsync-batch", "chunked": True},
                        },
                    }
                )
            finally:
                webapp.ROOT = original_root
                webapp.OUTPUT_DIR = original_output_dir
                webapp.LOG_DIR = original_log_dir

        labels = {link["label"]: link["href"] for link in enriched["output_summary"]["links"]}
        self.assertEqual(labels["Parent Gallery"], "person_factory_demo.html")
        self.assertEqual(labels["Parent Result JSON"], "results/batch_person_factory_demo_latest.json")

    def test_cached_lipsync_chunk_job_summary_uses_batch_id_outputs(self):
        from scripts import person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_output_dir = webapp.OUTPUT_DIR
            original_log_dir = webapp.LOG_DIR
            webapp.ROOT = tmp
            webapp.OUTPUT_DIR = tmp / "outputs/batch"
            webapp.LOG_DIR = tmp / "logs"

            try:
                (tmp / "outputs/batch").mkdir(parents=True)
                (tmp / "results").mkdir(parents=True)
                (tmp / "logs").mkdir()
                (tmp / "outputs/batch/person_factory_demo.html").write_text("<html></html>", encoding="utf-8")
                (tmp / "results/batch_person_factory_demo_latest.json").write_text('{"jobs":[]}', encoding="utf-8")

                enriched = webapp.job_with_log(
                    {
                        "id": "demo-cached-lipsync",
                        "status": "ok",
                        "request": {
                            "name": "Cached Lip-Sync Batch",
                            "batch_id": "demo",
                            "pipeline": {"type": "cached-lipsync-batch-chunk"},
                        },
                    }
                )
            finally:
                webapp.ROOT = original_root
                webapp.OUTPUT_DIR = original_output_dir
                webapp.LOG_DIR = original_log_dir

        labels = {link["label"]: link["href"] for link in enriched["output_summary"]["links"]}
        self.assertEqual(labels["Gallery"], "person_factory_demo.html")
        self.assertEqual(labels["Result JSON"], "results/batch_person_factory_demo_latest.json")

    def test_output_summary_backfills_batch_stage_summary_from_stages(self):
        from scripts import person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_output_dir = webapp.OUTPUT_DIR
            original_log_dir = webapp.LOG_DIR
            webapp.ROOT = tmp
            webapp.OUTPUT_DIR = tmp / "outputs/batch"
            webapp.LOG_DIR = tmp / "logs"

            try:
                (tmp / "outputs/batch").mkdir(parents=True)
                (tmp / "results").mkdir(parents=True)
                (tmp / "logs").mkdir()
                (tmp / "outputs/batch/person_factory_demo.html").write_text("<html></html>", encoding="utf-8")
                (tmp / "results/batch_person_factory_demo_latest.json").write_text('{"jobs":[]}', encoding="utf-8")
                (tmp / "results/run_cached_lipsync_batch_demo.json").write_text(
                    json.dumps(
                        {
                            "elapsed_seconds": 13.0,
                            "stages": [
                                {"name": "generate", "elapsed_seconds": 1.0, "status": "ok"},
                                {"name": "render", "elapsed_seconds": 10.0, "status": "ok"},
                            ],
                        }
                    ),
                    encoding="utf-8",
                )

                enriched = webapp.job_with_log(
                    {
                        "id": "demo-cached-lipsync",
                        "status": "ok",
                        "request": {"batch_id": "demo"},
                    }
                )
            finally:
                webapp.ROOT = original_root
                webapp.OUTPUT_DIR = original_output_dir
                webapp.LOG_DIR = original_log_dir

        summary = enriched["output_summary"]["batch_run"]["stage_summary"]
        self.assertEqual(summary["slowest_stage"], "render")
        self.assertEqual(summary["total_stage_seconds"], 11.0)

    def test_cached_lipsync_batch_summary_uses_batch_validation_and_finalize(self):
        from scripts import person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            original_root = webapp.ROOT
            original_output_dir = webapp.OUTPUT_DIR
            original_log_dir = webapp.LOG_DIR
            webapp.ROOT = tmp
            webapp.OUTPUT_DIR = tmp / "outputs/batch"
            webapp.LOG_DIR = tmp / "logs"

            try:
                (tmp / "outputs/batch").mkdir(parents=True)
                (tmp / "results").mkdir(parents=True)
                (tmp / "logs").mkdir()
                (tmp / "outputs/batch/person_factory_demo.html").write_text("<html></html>", encoding="utf-8")
                (tmp / "results/batch_person_factory_demo_latest.json").write_text('{"jobs":[]}', encoding="utf-8")
                (tmp / "results/finalize_person_factory_demo_latest.json").write_text(
                    json.dumps(
                        {
                            "status": "ok",
                            "godot_reload": {"asset_count": 96, "status": "ok"},
                            "godot_export": {"exported": [{"status": "ok"} for _ in range(96)]},
                        }
                    ),
                    encoding="utf-8",
                )
                (tmp / "results/run_cached_lipsync_batch_demo.json").write_text(
                    json.dumps(
                        {
                            "elapsed_seconds": 6.7,
                            "validation": {
                                "checked_count": 96,
                                "summary": {
                                    "active_visemes": ["aa", "ee", "ih", "oh", "ou"],
                                    "grade_counts": {"A": 96},
                                    "ok_count": 96,
                                    "review_count": 0,
                                    "cue_count_min": 18,
                                    "cue_count_max": 18,
                                    "duration_min": 1.86,
                                    "duration_max": 1.86,
                                    "expression_count_min": 2,
                                    "expression_count_max": 2,
                                    "missing_active_viseme_counts": {},
                                    "source_counts": {"phoneme-events": 96},
                                },
                                "validation_cache": {"enabled": True, "hit_count": 6, "miss_count": 0},
                                "validation_transport": {"mode": "persistent-cache"},
                            },
                        }
                    ),
                    encoding="utf-8",
                )

                enriched = webapp.job_with_log(
                    {
                        "id": "demo-cached-lipsync",
                        "status": "ok",
                        "request": {"batch_id": "demo"},
                    }
                )
            finally:
                webapp.ROOT = original_root
                webapp.OUTPUT_DIR = original_output_dir
                webapp.LOG_DIR = original_log_dir

        summary = enriched["output_summary"]
        self.assertTrue(summary["has_game_asset"])
        self.assertTrue(summary["has_timeline"])
        self.assertEqual(summary["lipsync"]["cue_count"], 18)
        self.assertEqual(summary["lipsync"]["duration"], 1.86)
        self.assertEqual(summary["lipsync"]["visemes"], ["aa", "ee", "ih", "oh", "ou"])
        self.assertEqual(summary["lipsync"]["missing_visemes"], [])
        self.assertEqual(summary["lip_sync_readiness"]["status"], "ready")
        self.assertEqual(summary["batch_run"]["validation"]["checked_count"], 96)
        self.assertEqual(summary["batch_run"]["validation"]["grade_counts"], {"A": 96})
        self.assertEqual(summary["batch_run"]["validation_cache"]["hit_count"], 6)
        self.assertEqual(summary["batch_run"]["validation_transport"]["mode"], "persistent-cache")

    def test_godot_proxy_posts_to_configured_control_url(self):
        from scripts import person_factory_webapp as webapp

        calls = []
        original_post_json = webapp.post_json
        original_environ = dict(webapp.os.environ)

        def fake_post_json(url, payload, timeout=120):
            calls.append((url, payload, timeout))
            return {"status": "ok", "url": url, "payload": payload}

        webapp.post_json = fake_post_json
        webapp.os.environ["GODOT_CONTROL_URL"] = "http://godot.local:8790/"
        try:
            load = webapp.proxy_godot_post("/load", {"id": "generated-job-id"})
            lipsync = webapp.proxy_godot_post(
                "/lipsync",
                {"path": "/workspace/outputs/lipsync/cache/example.face.json"},
            )
        finally:
            webapp.post_json = original_post_json
            webapp.os.environ.clear()
            webapp.os.environ.update(original_environ)

        self.assertEqual(load["status"], "ok")
        self.assertEqual(lipsync["status"], "ok")
        self.assertEqual(calls[0][0], "http://godot.local:8790/load")
        self.assertEqual(calls[0][1], {"id": "generated-job-id"})
        self.assertEqual(calls[1][0], "http://godot.local:8790/lipsync")

    def test_godot_get_proxy_uses_configured_control_url(self):
        from scripts import person_factory_webapp as webapp

        calls = []
        original_get_json = webapp.get_json
        original_environ = dict(webapp.os.environ)

        def fake_get_json(url, timeout=120):
            calls.append((url, timeout))
            return {"status": "ok", "url": url}

        webapp.get_json = fake_get_json
        webapp.os.environ["GODOT_CONTROL_URL"] = "http://godot.local:8790/"
        try:
            health = webapp.proxy_godot_get("/health")
            profile = webapp.proxy_godot_get("/face-profile")
            lipsync = webapp.proxy_godot_get("/lipsync-status")
        finally:
            webapp.get_json = original_get_json
            webapp.os.environ.clear()
            webapp.os.environ.update(original_environ)

        self.assertEqual(health["status"], "ok")
        self.assertEqual(profile["status"], "ok")
        self.assertEqual(lipsync["status"], "ok")
        self.assertEqual(calls[0][0], "http://godot.local:8790/health")
        self.assertEqual(calls[1][0], "http://godot.local:8790/face-profile")
        self.assertEqual(calls[2][0], "http://godot.local:8790/lipsync-status")

    def test_sync_godot_assets_skips_existing_exports_by_default(self):
        from scripts import person_factory_webapp as webapp

        calls = []
        original_post_json = webapp.post_json
        original_environ = dict(webapp.os.environ)

        def fake_post_json(url, payload, timeout=120):
            calls.append((url, payload, timeout))
            return {"status": "ok", "asset_count": 2, "exported": [], "skipped": [{"id": "ready"}]}

        webapp.post_json = fake_post_json
        webapp.os.environ["GODOT_CONTROL_URL"] = "http://godot.local:8790/"
        try:
            result = webapp.sync_godot_assets()
        finally:
            webapp.post_json = original_post_json
            webapp.os.environ.clear()
            webapp.os.environ.update(original_environ)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(calls[1][0], "http://godot.local:8790/export-all-game-assets")
        self.assertEqual(calls[1][1], {"skip_existing": True})

    def test_sync_godot_assets_accepts_explicit_batch_result(self):
        from scripts import person_factory_webapp as webapp

        calls = []
        original_post_json = webapp.post_json
        original_environ = dict(webapp.os.environ)
        original_root = webapp.ROOT

        def fake_post_json(url, payload, timeout=120):
            calls.append((url, payload, timeout))
            return {"status": "ok"}

        webapp.post_json = fake_post_json
        webapp.os.environ["GODOT_CONTROL_URL"] = "http://godot.local:8790/"
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            webapp.ROOT = tmp
            (tmp / "results").mkdir(parents=True)
            (tmp / "results/batch_person_factory_new_batch_latest.json").write_text(
                json.dumps(
                    {
                        "jobs": [
                            {"id": "asset-001", "status": "ok"},
                            {"id": "asset-002", "status": "ok"},
                            {"id": "asset-001", "status": "ok"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            try:
                result = webapp.sync_godot_assets(
                    batch_result="results/batch_person_factory_new_batch_latest.json"
                )
            finally:
                webapp.post_json = original_post_json
                webapp.os.environ.clear()
                webapp.os.environ.update(original_environ)
                webapp.ROOT = original_root

        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            calls[0][1],
            {"batch_result": "/workspace/results/batch_person_factory_new_batch_latest.json", "scoped": True},
        )
        self.assertEqual(calls[1][1], {"skip_existing": True, "asset_ids": ["asset-001", "asset-002"]})
        self.assertEqual(
            result["batch_result"],
            "/workspace/results/batch_person_factory_new_batch_latest.json",
        )
        self.assertEqual(result["asset_ids"], ["asset-001", "asset-002"])

    def test_recent_gallery_ui_can_use_and_sync_batch_outputs(self):
        js = (ROOT / "webapp/factory.js").read_text(encoding="utf-8")

        self.assertIn('data-gallery-action="use"', js)
        self.assertIn('data-gallery-action="sync"', js)
        self.assertIn('gallery.batch_result', js)
        self.assertIn('/api/godot/sync', js)
        self.assertIn('chars/s', js)
        self.assertIn('Render cache', js)
        self.assertIn('best_throughput', js)
        self.assertIn('recent-gallery-benchmark', js)
        self.assertIn('data-gallery-action="use-benchmark"', js)
        self.assertIn('data-gallery-action="queue-benchmark"', js)
        self.assertIn('key: "ship"', js)
        self.assertIn('key: "review"', js)
        self.assertIn('key: "nonship"', js)
        self.assertIn('data-gallery-filter="${escapeHtml(filter.key)}"', js)
        self.assertIn('ship_compatible', js)
        self.assertIn('benchmark.recommendation', js)
        self.assertIn('Cache ready', js)
        self.assertIn('Queue plan:', js)
        self.assertIn('Published sample:', js)
        self.assertIn('Queue overhead:', js)
        self.assertIn('Best ${escapeHtml(bestMode)} throughput:', js)
        self.assertIn('recommendation.queue_estimated_wall_seconds', js)
        self.assertIn('recommendation.queue_reference_orchestration_overhead_seconds', js)
        self.assertIn('recommendation.queue_estimate_sample_count', js)
        self.assertIn('recommendation.queue_chunked', js)
        self.assertIn('recommendation.queue_fast_publish', js)
        self.assertIn('recommendation.queue_reference_elapsed_seconds', js)
        self.assertIn('recommendation.cache_hit_count', js)
        self.assertIn('data-cache-ready', js)
        self.assertIn('data-estimated-wall', js)
        self.assertIn('chunked: Boolean(cachedLipSyncChunkedInput?.checked)', js)
        self.assertIn('render_cache_ready: Boolean(options.renderCacheReady)', js)
        self.assertIn('estimated_wall_seconds: Number(options.estimatedWallSeconds || 0)', js)
        self.assertIn('estimatedWallSeconds: Number(button.dataset.estimatedWall || 0)', js)
        self.assertIn('cachedLipSyncFastPublishInput) cachedLipSyncFastPublishInput.checked = false', js)
        self.assertIn('Number(cachedLipSyncCountInput?.value || 0) > matrixJobLimit', js)
        self.assertIn('await queuePhrasebankThumbnailBatch({', js)

    def test_webapp_image_has_local_render_prerequisites(self):
        dockerfile = (ROOT / "Dockerfile.webapp").read_text(encoding="utf-8")

        self.assertIn("ffmpeg", dockerfile)
        self.assertIn("docker-cli", dockerfile)
        self.assertIn("docker-compose", dockerfile)
        self.assertIn("nodejs", dockerfile)
        self.assertIn("npm", dockerfile)
        self.assertIn("@gltf-transform/cli", dockerfile)

    def test_webapp_compose_can_reach_host_docker_for_render_worker(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("PROJECT_CONTAINER_PATH", compose)
        self.assertIn("/var/run/docker.sock:/var/run/docker.sock", compose)
        self.assertIn("WEBAPP_ROOT", compose)

    def test_jobs_response_can_limit_and_compact_large_job_payloads(self):
        from scripts import person_factory_webapp as webapp
        from scripts.person_factory_jobs import JobStore

        with tempfile.TemporaryDirectory() as tmp_dir:
            original_store = webapp.JOB_STORE
            original_log_dir = webapp.LOG_DIR
            webapp.JOB_STORE = JobStore(Path(tmp_dir) / "jobs.json")
            webapp.LOG_DIR = Path(tmp_dir) / "logs"
            try:
                webapp.LOG_DIR.mkdir(parents=True)
                for index in range(3):
                    job = webapp.JOB_STORE.create_job(
                        {
                            "id": f"job-{index}",
                            "name": "Large Job",
                            "text": "x" * 500,
                            "batch_id": "batch",
                            "pipeline": {"type": "test"},
                            "large": "y" * 1000,
                        },
                        ["python3", "large", "command"],
                    )
                    (webapp.LOG_DIR / f"{job['id']}.log").write_text(
                        "\n".join(f"line-{line}" for line in range(30)),
                        encoding="utf-8",
                    )

                jobs, compact, include_summary, include_logs = webapp.limited_jobs_for_response(
                    {"compact": ["1"], "limit": ["2"]}
                )
                compacted = [webapp.compact_job_for_list(job) for job in jobs]
            finally:
                webapp.JOB_STORE = original_store
                webapp.LOG_DIR = original_log_dir

        self.assertTrue(compact)
        self.assertTrue(include_summary)
        self.assertTrue(include_logs)
        self.assertEqual([job["id"] for job in compacted], ["job-1", "job-2"])
        self.assertNotIn("command", compacted[0])
        self.assertNotIn("large", compacted[0]["request"])
        self.assertEqual(compacted[0]["request"]["pipeline"], {"type": "test"})
        self.assertEqual(len(compacted[0]["log_tail"]), 20)

    def test_jobs_response_can_skip_summaries_and_logs_for_fast_polling(self):
        from scripts import person_factory_webapp as webapp
        from scripts.person_factory_jobs import JobStore

        with tempfile.TemporaryDirectory() as tmp_dir:
            original_store = webapp.JOB_STORE
            original_log_dir = webapp.LOG_DIR
            original_job_output_summary = webapp.job_output_summary
            webapp.JOB_STORE = JobStore(Path(tmp_dir) / "jobs.json")
            webapp.LOG_DIR = Path(tmp_dir) / "logs"
            webapp.LOG_DIR.mkdir(parents=True)
            summary_calls = []

            def counted_summary(job):
                summary_calls.append(job["id"])
                return {"links": [{"label": "Report", "href": "results/demo.json"}]}

            webapp.job_output_summary = counted_summary
            try:
                job = webapp.JOB_STORE.create_job(
                    {"id": "poll-job", "name": "Poll Job", "text": "status", "pipeline": {"type": "test"}},
                    ["python3", "large", "command"],
                )
                (webapp.LOG_DIR / "poll-job.log").write_text("line\n" * 30, encoding="utf-8")
                jobs, compact, include_summary, include_logs = webapp.limited_jobs_for_response(
                    {"compact": ["1"], "limit": ["1"], "summary": ["0"], "logs": ["0"]}
                )
                compacted = [
                    webapp.compact_job_for_list(job, include_summary=include_summary, include_logs=include_logs)
                    for job in jobs
                ]
            finally:
                webapp.JOB_STORE = original_store
                webapp.LOG_DIR = original_log_dir
                webapp.job_output_summary = original_job_output_summary

        self.assertTrue(compact)
        self.assertFalse(include_summary)
        self.assertFalse(include_logs)
        self.assertEqual(compacted[0]["id"], job["id"])
        self.assertNotIn("output_summary", compacted[0])
        self.assertNotIn("log_tail", compacted[0])
        self.assertEqual(summary_calls, [])

    def test_fast_jobs_polling_uses_recent_job_store_slice(self):
        from scripts import person_factory_webapp as webapp

        class FakeJobStore:
            def __init__(self):
                self.list_jobs_called = False
                self.recent_limit = None

            def list_jobs(self):
                self.list_jobs_called = True
                return []

            def list_recent_jobs(self, limit):
                self.recent_limit = limit
                return [{"id": "recent-job", "request": {"id": "recent-job"}, "status": "running"}]

        original_store = webapp.JOB_STORE
        fake_store = FakeJobStore()
        webapp.JOB_STORE = fake_store
        try:
            jobs, compact, include_summary, include_logs = webapp.limited_jobs_for_response(
                {"compact": ["1"], "limit": ["40"], "summary": ["0"], "logs": ["0"]}
            )
        finally:
            webapp.JOB_STORE = original_store

        self.assertTrue(compact)
        self.assertFalse(include_summary)
        self.assertFalse(include_logs)
        self.assertEqual(jobs[0]["id"], "recent-job")
        self.assertEqual(fake_store.recent_limit, 40)
        self.assertFalse(fake_store.list_jobs_called)

    def test_compact_job_output_summary_keeps_actions_without_bulky_links(self):
        from scripts import person_factory_webapp as webapp

        summary = webapp.compact_output_summary(
            {
                "links": [{"label": "Report", "href": "results/demo.json"}],
                "has_game_asset": True,
                "has_timeline": True,
                "review_image": "outputs/review.png",
                "lipsync": {
                    "path": "outputs/lipsync/demo.face.json",
                    "cue_count": 12,
                    "duration": 2.0,
                    "quality": {"status": "ok", "grade": "A"},
                    "viseme_counts": {"aa": 10},
                },
                "pipeline_timing": {"wall_elapsed_seconds": 5.0},
                "batch_run": {
                    "stage_summary": {"slowest_stage": "render"},
                    "large": "x" * 1000,
                },
            }
        )

        self.assertTrue(summary["has_game_asset"])
        self.assertEqual(summary["lipsync"]["path"], "outputs/lipsync/demo.face.json")
        self.assertEqual(summary["lipsync"]["quality"]["grade"], "A")
        self.assertNotIn("links", summary)
        self.assertNotIn("review_image", summary)
        self.assertNotIn("viseme_counts", summary["lipsync"])
        self.assertEqual(summary["batch_run"], {"stage_summary": {"slowest_stage": "render"}})

    def test_warm_render_pipeline_does_not_leave_later_children_queued_after_failure(self):
        from scripts import person_factory_webapp as webapp
        from scripts.person_factory_jobs import JobStore

        with tempfile.TemporaryDirectory() as tmp_dir:
            original_store = webapp.JOB_STORE
            original_log_dir = webapp.LOG_DIR
            original_run_job = webapp.run_job
            webapp.JOB_STORE = JobStore(Path(tmp_dir) / "jobs.json")
            webapp.LOG_DIR = Path(tmp_dir) / "logs"

            def fail_first_child(job_id, _command):
                webapp.JOB_STORE.update_job(job_id, status="error", returncode=1)

            webapp.run_job = fail_first_child
            try:
                webapp.JOB_STORE.create_job(
                    {"id": "pipeline-test", "text": "pipeline", "name": "pipeline"},
                    ["pipeline"],
                )
                pipeline = {
                    "warm_job_count": 0,
                    "skipped_group_count": 0,
                    "render_job_count": 2,
                    "warm_jobs": [],
                    "render_jobs": [
                        {"request": {"id": "render-test-001"}, "command": ["false"]},
                        {"request": {"id": "render-test-002"}, "command": ["true"]},
                    ],
                }

                webapp.run_matrix_warm_render_pipeline("pipeline-test", pipeline)

                parent = webapp.JOB_STORE.get_job("pipeline-test")
                first = webapp.JOB_STORE.get_job("render-test-001")
                with self.assertRaises(KeyError):
                    webapp.JOB_STORE.get_job("render-test-002")
            finally:
                webapp.JOB_STORE = original_store
                webapp.LOG_DIR = original_log_dir
                webapp.run_job = original_run_job

        self.assertEqual(parent["status"], "error")
        self.assertEqual(first["status"], "error")
        self.assertEqual(parent["child_job_ids"], ["render-test-001"])

    def test_warm_render_pipeline_records_publish_result_after_success(self):
        from scripts import person_factory_webapp as webapp
        from scripts.person_factory_jobs import JobStore

        with tempfile.TemporaryDirectory() as tmp_dir:
            original_store = webapp.JOB_STORE
            original_log_dir = webapp.LOG_DIR
            original_run_job = webapp.run_job
            original_publish = webapp.publish_pipeline_outputs
            webapp.JOB_STORE = JobStore(Path(tmp_dir) / "jobs.json")
            webapp.LOG_DIR = Path(tmp_dir) / "logs"

            def pass_child(job_id, _command):
                webapp.JOB_STORE.update_job(job_id, status="ok", returncode=0)

            webapp.run_job = pass_child
            webapp.publish_pipeline_outputs = lambda: {
                "status": "ok",
                "gallery": {"returncode": 0},
                "godot": {"status": "ok"},
            }
            try:
                webapp.JOB_STORE.create_job(
                    {"id": "pipeline-test", "text": "pipeline", "name": "pipeline"},
                    ["pipeline"],
                )
                pipeline = {
                    "warm_job_count": 0,
                    "skipped_group_count": 0,
                    "render_job_count": 1,
                    "warm_jobs": [],
                    "render_jobs": [
                        {"request": {"id": "render-test-001"}, "command": ["true"]},
                    ],
                }

                webapp.run_matrix_warm_render_pipeline("pipeline-test", pipeline)

                parent = webapp.JOB_STORE.get_job("pipeline-test")
            finally:
                webapp.JOB_STORE = original_store
                webapp.LOG_DIR = original_log_dir
                webapp.run_job = original_run_job
                webapp.publish_pipeline_outputs = original_publish

        self.assertEqual(parent["status"], "ok")
        self.assertEqual(parent["publish_result"]["status"], "ok")
        self.assertEqual(parent["render_job_ids"], ["render-test-001"])

    def test_warm_render_pipeline_runs_multiple_render_batch_chunks(self):
        from scripts import person_factory_webapp as webapp
        from scripts.person_factory_jobs import JobStore

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            original_store = webapp.JOB_STORE
            original_root = webapp.ROOT
            original_log_dir = webapp.LOG_DIR
            original_run_job = webapp.run_job
            original_publish = webapp.publish_pipeline_outputs
            webapp.JOB_STORE = JobStore(tmp_path / "jobs.json")
            webapp.ROOT = tmp_path
            webapp.LOG_DIR = tmp_path / "logs"
            ran = []

            def pass_child(job_id, _command):
                ran.append(job_id)
                webapp.JOB_STORE.update_job(job_id, status="ok", returncode=0)

            webapp.run_job = pass_child
            webapp.publish_pipeline_outputs = lambda: {"status": "ok"}
            try:
                webapp.JOB_STORE.create_job(
                    {"id": "pipeline-test", "text": "pipeline", "name": "pipeline"},
                    ["pipeline"],
                )
                pipeline = {
                    "warm_job_count": 0,
                    "skipped_group_count": 0,
                    "render_job_count": 3,
                    "warm_jobs": [],
                    "render_jobs": [
                        {"request": {"id": "render-test-001"}, "command": ["true"]},
                        {"request": {"id": "render-test-002"}, "command": ["true"]},
                        {"request": {"id": "render-test-003"}, "command": ["true"]},
                    ],
                    "render_batch_jobs": [
                        {
                            "request": {"id": "chunk-001", "text": "chunk"},
                            "command": ["true"],
                            "requests": [{"id": "render-test-001"}, {"id": "render-test-002"}],
                            "requests_json": "config/person_factory.chunk-001.requests.json",
                        },
                        {
                            "request": {"id": "chunk-002", "text": "chunk"},
                            "command": ["true"],
                            "requests": [{"id": "render-test-003"}],
                            "requests_json": "config/person_factory.chunk-002.requests.json",
                        },
                    ],
                }

                webapp.run_matrix_warm_render_pipeline("pipeline-test", pipeline)

                parent = webapp.JOB_STORE.get_job("pipeline-test")
                chunk_001_requests = (tmp_path / "config/person_factory.chunk-001.requests.json").read_text(
                    encoding="utf-8"
                )
                chunk_002_requests = (tmp_path / "config/person_factory.chunk-002.requests.json").read_text(
                    encoding="utf-8"
                )
            finally:
                webapp.JOB_STORE = original_store
                webapp.ROOT = original_root
                webapp.LOG_DIR = original_log_dir
                webapp.run_job = original_run_job
                webapp.publish_pipeline_outputs = original_publish

        self.assertEqual(parent["status"], "ok")
        self.assertEqual(parent["render_job_ids"], ["chunk-001", "chunk-002"])
        self.assertEqual(parent["render_item_ids"], ["render-test-001", "render-test-002", "render-test-003"])
        self.assertEqual(ran, ["chunk-001", "chunk-002"])
        self.assertEqual(chunk_001_requests.count("render-test"), 2)
        self.assertEqual(chunk_002_requests.count("render-test"), 1)

    def test_warm_render_pipeline_publish_review_does_not_fail_successful_renders(self):
        from scripts import person_factory_webapp as webapp
        from scripts.person_factory_jobs import JobStore

        with tempfile.TemporaryDirectory() as tmp_dir:
            original_store = webapp.JOB_STORE
            original_log_dir = webapp.LOG_DIR
            original_run_job = webapp.run_job
            original_publish = webapp.publish_pipeline_outputs
            webapp.JOB_STORE = JobStore(Path(tmp_dir) / "jobs.json")
            webapp.LOG_DIR = Path(tmp_dir) / "logs"

            def pass_child(job_id, _command):
                webapp.JOB_STORE.update_job(job_id, status="ok", returncode=0)

            webapp.run_job = pass_child
            webapp.publish_pipeline_outputs = lambda: {
                "status": "review",
                "gallery": {"returncode": 0},
                "godot": {"status": "review", "error": "temporary"},
            }
            try:
                webapp.JOB_STORE.create_job(
                    {"id": "pipeline-test", "text": "pipeline", "name": "pipeline"},
                    ["pipeline"],
                )
                pipeline = {
                    "warm_job_count": 0,
                    "skipped_group_count": 0,
                    "render_job_count": 1,
                    "warm_jobs": [],
                    "render_jobs": [
                        {"request": {"id": "render-test-001"}, "command": ["true"]},
                    ],
                }

                webapp.run_matrix_warm_render_pipeline("pipeline-test", pipeline)

                parent = webapp.JOB_STORE.get_job("pipeline-test")
            finally:
                webapp.JOB_STORE = original_store
                webapp.LOG_DIR = original_log_dir
                webapp.run_job = original_run_job
                webapp.publish_pipeline_outputs = original_publish

        self.assertEqual(parent["status"], "ok")
        self.assertEqual(parent["publish_result"]["status"], "review")
        self.assertEqual(parent["returncode"], 0)

    def test_warm_render_pipeline_passes_validation_prefix_to_publish(self):
        from scripts import person_factory_webapp as webapp
        from scripts.person_factory_jobs import JobStore

        with tempfile.TemporaryDirectory() as tmp_dir:
            original_store = webapp.JOB_STORE
            original_log_dir = webapp.LOG_DIR
            original_run_job = webapp.run_job
            original_publish = webapp.publish_pipeline_outputs
            webapp.JOB_STORE = JobStore(Path(tmp_dir) / "jobs.json")
            webapp.LOG_DIR = Path(tmp_dir) / "logs"
            publish_args = []

            def pass_child(job_id, _command):
                webapp.JOB_STORE.update_job(job_id, status="ok", returncode=0)

            def fake_publish(validation_id_prefix=""):
                publish_args.append(validation_id_prefix)
                return {"status": "ok", "gallery": {"returncode": 0}, "godot": {"status": "ok"}}

            webapp.run_job = pass_child
            webapp.publish_pipeline_outputs = fake_publish
            try:
                webapp.JOB_STORE.create_job(
                    {"id": "pipeline-test", "text": "pipeline", "name": "pipeline"},
                    ["pipeline"],
                )
                pipeline = {
                    "warm_job_count": 0,
                    "skipped_group_count": 0,
                    "render_job_count": 1,
                    "warm_jobs": [],
                    "render_jobs": [
                        {"request": {"id": "ship-bowtie-live-005-001"}, "command": ["true"]},
                    ],
                    "validation_id_prefix": "ship-bowtie-live-005-",
                }

                webapp.run_matrix_warm_render_pipeline("pipeline-test", pipeline)
            finally:
                webapp.JOB_STORE = original_store
                webapp.LOG_DIR = original_log_dir
                webapp.run_job = original_run_job
                webapp.publish_pipeline_outputs = original_publish

        self.assertEqual(publish_args, ["ship-bowtie-live-005-"])

    def test_publish_pipeline_runs_godot_lipsync_validation_and_rebuilds_gallery(self):
        from scripts import person_factory_webapp as webapp

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            (tmp / "results").mkdir()
            original_root = webapp.ROOT
            original_run = webapp.subprocess.run
            original_sync = webapp.sync_godot_assets
            original_environ = dict(webapp.os.environ)
            calls = []

            def fake_run(command, cwd, text, capture_output, check=False):
                calls.append(command)
                if any("validate_godot_lipsync.py" in part for part in command):
                    (tmp / "results/godot_lipsync_validation_latest.json").write_text(
                        '{"status":"ok","candidate_count":2,"checked_count":2,"checked":[]}',
                        encoding="utf-8",
                    )
                return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

            webapp.ROOT = tmp
            webapp.subprocess.run = fake_run
            webapp.sync_godot_assets = lambda: {"status": "ok", "export": {"exported": [{"id": "a"}]}}
            webapp.os.environ["GODOT_CONTROL_URL"] = "http://godot.local:8790"
            webapp.os.environ["GODOT_LIPSYNC_VALIDATION_MAX_ASSETS"] = "12"
            try:
                result = webapp.publish_pipeline_outputs(validation_id_prefix="ship-bowtie-live-005-")
            finally:
                webapp.ROOT = original_root
                webapp.subprocess.run = original_run
                webapp.sync_godot_assets = original_sync
                webapp.os.environ.clear()
                webapp.os.environ.update(original_environ)

        gallery_calls = [call for call in calls if call == ["python3", "scripts/build_combined_gallery.py"]]
        validation_calls = [call for call in calls if any("validate_godot_lipsync.py" in part for part in call)]
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(gallery_calls), 2)
        self.assertEqual(len(validation_calls), 1)
        self.assertIn("--control-url", validation_calls[0])
        self.assertIn("http://godot.local:8790", validation_calls[0])
        self.assertIn("--max-assets", validation_calls[0])
        self.assertIn("12", validation_calls[0])
        self.assertIn("--id-prefix", validation_calls[0])
        self.assertIn("ship-bowtie-live-005-", validation_calls[0])
        self.assertEqual(result["godot_lipsync_validation"]["report"]["checked_count"], 2)

    def test_validate_catalog_choices_accepts_aliases_and_rejects_unknown_accessories(self):
        from scripts.person_factory_webapp import validate_catalog_choices

        validate_catalog_choices(
            {
                "base": "female",
                "accessory": "cowboy hat",
                "animation": "talk_idle",
            }
        )
        with patch.dict("os.environ", {"PERSON_FACTORY_ACCESSORY_QUALITIES": "ship,review"}):
            validate_catalog_choices(
                {
                    "bases": ["female"],
                    "accessories": ["bowtie-jeremy", "necktie"],
                    "animations": ["talk_idle"],
                }
            )
        with self.assertRaises(ValueError) as context:
            validate_catalog_choices(
                {
                    "bases": ["female"],
                    "accessories": ["bowtie-pixel"],
                    "animations": ["talk_idle"],
                }
            )

        self.assertIn("unknown accessory", str(context.exception))


if __name__ == "__main__":
    unittest.main()
