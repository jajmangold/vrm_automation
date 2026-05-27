import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_combined_gallery import (
    DEFAULT_BATCH_RESULTS,
    batch_result_run_report_path,
    combine_batch_results,
    discover_godot_lipsync_validation_results,
    discover_batch_results,
    is_publishable_batch_result,
    merge_godot_lipsync_validations,
    publishable_batch_results,
)


class BuildCombinedGalleryTests(unittest.TestCase):
    def test_default_sources_include_standard_animation_validation(self):
        self.assertIn(
            Path("results/batch_person_factory_standard_anim5_latest.json"),
            DEFAULT_BATCH_RESULTS,
        )
        self.assertIn(
            Path("results/batch_person_factory_lipsync_stt1_latest.json"),
            DEFAULT_BATCH_RESULTS,
        )
        self.assertIn(
            Path("results/batch_person_factory_lipsync_rhubarb1_latest.json"),
            DEFAULT_BATCH_RESULTS,
        )

    def test_discovers_dynamic_talking_person_batches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "results"
            results.mkdir()
            fixed = results / "batch_person_factory_now_latest.json"
            dynamic = results / "batch_person_factory_lip-new_latest.json"
            text_dynamic = results / "batch_person_factory_text-host_latest.json"
            web_dynamic = results / "batch_person_factory_web-render-001_latest.json"
            auto_dynamic = results / "batch_person_factory_auto-lip-001-001_latest.json"
            arbitrary_dynamic = results / "batch_person_factory_ship_bowtie_live_005_latest.json"
            batch_dynamic = results / "batch_person_factory_batch_render_live_001_latest.json"
            chunked_dynamic = results / "batch_person_factory_chunked_live_004_chunk_001_latest.json"
            rerender_dynamic = results / "batch_bowtie_rerender_latest.json"
            probe_dynamic = results / "batch_headwear_orientation_probe_latest.json"
            validation_dynamic = results / "batch_headwear_multibase_validation_latest.json"
            refresh_dynamic = results / "batch_headwear_refresh_latest.json"
            ignored = results / "batch_person_factory_cached_latest.json"
            for path in (
                fixed,
                dynamic,
                text_dynamic,
                web_dynamic,
                auto_dynamic,
                arbitrary_dynamic,
                batch_dynamic,
                chunked_dynamic,
                rerender_dynamic,
                probe_dynamic,
                validation_dynamic,
                refresh_dynamic,
                ignored,
            ):
                path.write_text(json.dumps({"jobs": []}), encoding="utf-8")

            paths = discover_batch_results(root=root, defaults=[Path("results/batch_person_factory_now_latest.json")])

        self.assertEqual(paths[0], Path("results/batch_person_factory_now_latest.json"))
        self.assertIn(Path("results/batch_person_factory_lip-new_latest.json"), paths)
        self.assertIn(Path("results/batch_person_factory_text-host_latest.json"), paths)
        self.assertIn(Path("results/batch_person_factory_web-render-001_latest.json"), paths)
        self.assertIn(Path("results/batch_person_factory_auto-lip-001-001_latest.json"), paths)
        self.assertIn(Path("results/batch_person_factory_ship_bowtie_live_005_latest.json"), paths)
        self.assertIn(Path("results/batch_person_factory_batch_render_live_001_latest.json"), paths)
        self.assertIn(Path("results/batch_person_factory_chunked_live_004_chunk_001_latest.json"), paths)
        self.assertIn(Path("results/batch_bowtie_rerender_latest.json"), paths)
        self.assertIn(Path("results/batch_headwear_orientation_probe_latest.json"), paths)
        self.assertIn(Path("results/batch_headwear_multibase_validation_latest.json"), paths)
        self.assertIn(Path("results/batch_headwear_refresh_latest.json"), paths)
        self.assertNotIn(Path("results/batch_person_factory_cached_latest.json"), paths)

    def test_discovers_godot_lipsync_validation_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "results"
            results.mkdir()
            latest = results / "godot_lipsync_validation_latest.json"
            batch = results / "godot_lipsync_validation_batch_latest.json"
            ignored = results / "godot_lipsync_validation_batch_draft.json"
            for path in (latest, batch, ignored):
                path.write_text(json.dumps({"checked": []}), encoding="utf-8")

            paths = discover_godot_lipsync_validation_results(root=root)

        self.assertEqual(
            paths,
            [
                Path("results/godot_lipsync_validation_latest.json"),
                Path("results/godot_lipsync_validation_batch_latest.json"),
            ],
        )

    def test_batch_result_run_report_path_matches_cached_lipsync_runner(self):
        self.assertEqual(
            batch_result_run_report_path(Path("results/batch_person_factory_fast768_skipreview_124521_latest.json")),
            Path("results/run_cached_lipsync_batch_fast768_skipreview_124521.json"),
        )
        self.assertIsNone(batch_result_run_report_path(Path("results/other.json")))

    def test_publishable_batch_results_skip_failed_cached_lipsync_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "results"
            results.mkdir()
            ok_batch = Path("results/batch_person_factory_ok_run_latest.json")
            failed_batch = Path("results/batch_person_factory_failed_run_latest.json")
            legacy_batch = Path("results/batch_person_factory_legacy_latest.json")
            for path in (ok_batch, failed_batch, legacy_batch):
                (root / path).write_text(json.dumps({"jobs": []}), encoding="utf-8")
            (results / "run_cached_lipsync_batch_ok_run.json").write_text('{"status":"ok"}', encoding="utf-8")
            (results / "run_cached_lipsync_batch_failed_run.json").write_text('{"status":"running"}', encoding="utf-8")

            kept = publishable_batch_results([failed_batch, ok_batch, legacy_batch], root=root)

        self.assertEqual(kept, [ok_batch, legacy_batch])

    def test_is_publishable_batch_result_rejects_malformed_existing_run_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            batch = Path("results/batch_person_factory_bad_report_latest.json")
            (root / "results").mkdir()
            (root / batch).write_text(json.dumps({"jobs": []}), encoding="utf-8")
            (root / "results/run_cached_lipsync_batch_bad_report.json").write_text("{bad", encoding="utf-8")

            publishable = is_publishable_batch_result(batch, root=root)

        self.assertFalse(publishable)

    def test_cli_can_write_summary_without_static_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            batch = root / "batch.json"
            summary = root / "summary.json"
            output = root / "gallery.html"
            batch.write_text(
                json.dumps({"jobs": [{"id": "person-001", "metadata": {"tags": ["generated"]}}]}),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/build_combined_gallery.py"),
                    str(output),
                    str(batch),
                    "--summary-json",
                    str(summary),
                    "--summary-only",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            summary_exists = summary.exists()
            output_exists = output.exists()

        self.assertTrue(summary_exists)
        self.assertFalse(output_exists)
        self.assertIn(str(summary), completed.stdout)

    def test_cli_can_write_character_index_with_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            batch = root / "batch.json"
            summary = root / "summary.json"
            index = root / "character_index.json"
            output = root / "gallery.html"
            batch.write_text(
                json.dumps(
                    {
                        "jobs": [
                            {
                                "id": "person-001",
                                "status": "ok",
                                "metadata": {"display_name": "Person One", "tags": ["generated"]},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/build_combined_gallery.py"),
                    str(output),
                    str(batch),
                    "--summary-json",
                    str(summary),
                    "--character-index-json",
                    str(index),
                    "--summary-only",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            summary_mtime = summary.stat().st_mtime
            index_data = json.loads(index.read_text(encoding="utf-8"))

        self.assertEqual(index_data["status"], "ok")
        self.assertEqual(index_data["source_mtime"], summary_mtime)
        self.assertEqual(index_data["payload"]["characters"][0]["id"], "person-001")
        self.assertEqual(index_data["payload"]["summary"]["character_count"], 1)

    def test_combines_sources_and_tags_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first_batch.json"
            second = Path(tmp) / "second_batch.json"
            first.write_text(
                json.dumps({"elapsed_seconds": 1.5, "jobs": [{"id": "a", "metadata": {"tags": ["alpha"]}}]}),
                encoding="utf-8",
            )
            second.write_text(
                json.dumps({"elapsed_seconds": 2.5, "jobs": [{"id": "b", "metadata": {"tags": ["beta"]}}]}),
                encoding="utf-8",
            )

            result = combine_batch_results([first, second])

        self.assertEqual(result["manifest"], "combined:2-sources")
        self.assertEqual(result["elapsed_seconds"], 4.0)
        self.assertEqual([job["id"] for job in result["jobs"]], ["a", "b"])
        self.assertIn("source:first-batch", result["jobs"][0]["metadata"]["tags"])
        self.assertIn("source:second-batch", result["jobs"][1]["metadata"]["tags"])
        self.assertEqual(result["batch_sources"][0]["job_count"], 1)

    def test_later_sources_replace_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "old_batch.json"
            second = Path(tmp) / "new_batch.json"
            first.write_text(json.dumps({"jobs": [{"id": "same", "metadata": {"tags": ["old"]}}]}), encoding="utf-8")
            second.write_text(json.dumps({"jobs": [{"id": "same", "metadata": {"tags": ["new"]}}]}), encoding="utf-8")

            result = combine_batch_results([first, second])

        self.assertEqual(len(result["jobs"]), 1)
        self.assertIn("new", result["jobs"][0]["metadata"]["tags"])
        self.assertIn("source:new-batch", result["jobs"][0]["metadata"]["tags"])
        self.assertEqual(result["deduped_job_count"], 1)

    def test_combined_gallery_skips_rejected_asset_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp) / "batch.json"
            batch.write_text(
                json.dumps(
                    {
                        "jobs": [
                            {"id": "bad", "metadata": {"tags": ["generated", "bowtie-jeremy"]}},
                            {"id": "good", "metadata": {"tags": ["generated", "necktie-jeremy"]}},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = combine_batch_results([batch], rejected_asset_keys={"bowtie-jeremy"})

        self.assertEqual([job["id"] for job in result["jobs"]], ["good"])
        self.assertEqual(result["filtered_job_count"], 1)

    def test_combined_gallery_keeps_validated_lipsync_rejected_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp) / "batch.json"
            batch.write_text(
                json.dumps(
                    {
                        "jobs": [
                            {"id": "phoneme", "metadata": {"tags": ["generated", "pixel-glasses-ipoly3d"]}},
                            {"id": "bad", "metadata": {"tags": ["generated", "pixel-glasses-ipoly3d"]}},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            validation = {
                "checked": [
                    {
                        "id": "phoneme",
                        "status": "ok",
                        "cue_count": 18,
                        "timeline": "/workspace/outputs/lipsync/hello_phonemes.face.json",
                        "lipsync_quality": {
                            "status": "ok",
                            "grade": "A",
                            "source_mode": "phoneme-events",
                            "alignment": "audio-derived",
                            "issues": [],
                            "warnings": [],
                        },
                    }
                ]
            }

            result = combine_batch_results(
                [batch],
                rejected_asset_keys={"pixel-glasses-ipoly3d"},
                godot_lipsync_validation=validation,
            )

        self.assertEqual([job["id"] for job in result["jobs"]], ["phoneme"])
        self.assertEqual(result["filtered_job_count"], 1)
        self.assertIn("rejected-asset-kept:lipsync-validation", result["jobs"][0]["metadata"]["tags"])
        self.assertIn("godot-lipsync-ok", result["jobs"][0]["metadata"]["tags"])

    def test_merge_godot_lipsync_validations_compacts_checked_payloads(self):
        merged = merge_godot_lipsync_validations(
            [
                {
                    "candidate_count": 1,
                    "checked": [
                        {
                            "id": "person-001",
                            "status": "ok",
                            "cue_count": 18,
                            "timeline": "/workspace/outputs/lipsync/cache/demo.face.json",
                            "playback_status": {
                                "status": "playing",
                                "active_viseme": "aa",
                                "source": "/workspace/outputs/lipsync/cache/demo.face.json",
                            },
                            "load": {"path": "/workspace/outputs/batch/demo.glb"},
                            "validation_cache": {"key": "large-cache-key", "status": "hit"},
                            "lipsync_quality": {
                                "status": "ok",
                                "grade": "A",
                                "cue_count": 18,
                                "expression_count": 2,
                                "active_visemes": ["aa", "ee", "ih", "oh", "ou"],
                                "missing_expected_active_visemes": [],
                                "source_mode": "phoneme-events",
                                "source_phoneme_counts": {"P": 2},
                            },
                        }
                    ],
                }
            ]
        )

        checked = merged["checked"][0]
        self.assertEqual(checked["id"], "person-001")
        self.assertEqual(checked["playback"]["active_viseme"], "aa")
        self.assertEqual(merged["summary"]["grade_counts"], {"A": 1})
        self.assertEqual(merged["summary"]["expression_count_max"], 2)
        self.assertNotIn("load", checked)
        self.assertNotIn("validation_cache", checked)
        self.assertNotIn("playback_status", checked)
        self.assertNotIn("source_phoneme_counts", checked["lipsync_quality"])

    def test_combined_gallery_refreshes_anchor_tags_from_asset_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp) / "batch.json"
            batch.write_text(
                json.dumps(
                    {
                        "jobs": [
                            {
                                "id": "bowtie-job",
                                "metadata": {
                                    "tags": [
                                        "generated",
                                        "bowtie-jeremy",
                                        "calibration:image-guided-anchor",
                                        "anchor:old-anchor",
                                        "anchor-validation:review",
                                    ]
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = combine_batch_results(
                [batch],
                asset_anchor_tag_overlays={
                    "bowtie-jeremy": [
                        "calibration:image-guided-anchor",
                        "anchor:neck-chest-collar-center",
                        "anchor-validation:ok",
                    ]
                },
            )

        tags = result["jobs"][0]["metadata"]["tags"]
        self.assertIn("anchor-validation:ok", tags)
        self.assertIn("anchor:neck-chest-collar-center", tags)
        self.assertNotIn("anchor-validation:review", tags)
        self.assertNotIn("anchor:old-anchor", tags)

    def test_combined_gallery_refreshes_quality_tags_from_asset_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp) / "batch.json"
            batch.write_text(
                json.dumps(
                    {
                        "jobs": [
                            {
                                "id": "bowtie-job",
                                "metadata": {
                                    "tags": [
                                        "generated",
                                        "bowtie-jeremy",
                                        "quality:review",
                                    ]
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = combine_batch_results(
                [batch],
                asset_anchor_tag_overlays={"bowtie-jeremy": ["quality:ship"]},
            )

        tags = result["jobs"][0]["metadata"]["tags"]
        self.assertIn("quality:ship", tags)
        self.assertNotIn("quality:review", tags)

    def test_combined_result_can_carry_godot_lipsync_validation_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp) / "batch.json"
            batch.write_text(
                json.dumps({"jobs": [{"id": "ready", "metadata": {"tags": ["generated"]}}]}),
                encoding="utf-8",
            )
            validation = {
                "status": "ok",
                "checked": [
                    {
                        "id": "ready",
                        "status": "ok",
                        "issues": [],
                        "lipsync_quality": {
                            "status": "ok",
                            "grade": "A",
                            "source_mode": "rhubarb",
                            "alignment": "audio-derived",
                            "issues": [],
                            "warnings": ["missing-active-viseme:ih"],
                        },
                    }
                ],
            }

            result = combine_batch_results([batch], godot_lipsync_validation=validation)

        self.assertEqual(result["godot_lipsync_validation"], validation)
        self.assertIn("godot-lipsync:ok", result["jobs"][0]["metadata"]["tags"])
        self.assertIn("godot-lipsync-ok", result["jobs"][0]["metadata"]["tags"])
        self.assertIn("lipsync-quality:ok", result["jobs"][0]["metadata"]["tags"])
        self.assertIn("lipsync-source:rhubarb", result["jobs"][0]["metadata"]["tags"])
        self.assertIn("lipsync-warning:missing-active-viseme:ih", result["jobs"][0]["metadata"]["tags"])
        self.assertEqual(result["godot_lipsync_summary"]["checked_count"], 1)
        self.assertEqual(result["godot_lipsync_summary"]["grade_counts"], {"A": 1})
        self.assertEqual(result["godot_lipsync_summary"]["warning_counts"], {"missing-active-viseme:ih": 1})

    def test_merges_multiple_godot_lipsync_validation_reports_by_asset_id(self):
        first = {
            "status": "ok",
            "candidate_count": 2,
            "checked_count": 1,
            "validation_transport": {
                "mode": "batch-endpoint-pool",
                "batch_request_count": 2,
                "control_client_count": 2,
                "fallback": False,
            },
            "checked": [
                {
                    "id": "old",
                    "status": "ok",
                    "cue_count": 5,
                    "timeline": "/workspace/outputs/lipsync/old.face.json",
                }
            ],
        }
        second = {
            "status": "ok",
            "candidate_count": 1,
            "checked_count": 1,
            "validation_transport": {
                "mode": "batch-endpoint",
                "batch_request_count": 1,
                "control_client_count": 1,
                "fallback": False,
            },
            "checked": [
                {
                    "id": "phoneme",
                    "status": "ok",
                    "cue_count": 18,
                    "timeline": "/workspace/outputs/lipsync/phoneme.face.json",
                }
            ],
        }
        replacement = {
            "status": "review",
            "candidate_count": 1,
            "checked_count": 1,
            "issues": ["asset-review"],
            "checked": [
                {
                    "id": "old",
                    "status": "review",
                    "cue_count": 5,
                    "timeline": "/workspace/outputs/lipsync/old-rerun.face.json",
                }
            ],
        }

        merged = merge_godot_lipsync_validations([first, second, replacement])

        self.assertEqual(merged["status"], "review")
        self.assertEqual(merged["candidate_count"], 4)
        self.assertEqual(merged["checked_count"], 2)
        self.assertEqual(merged["issues"], ["asset-review"])
        self.assertEqual(merged["summary"]["checked_count"], 2)
        self.assertEqual(merged["summary"]["review_count"], 1)
        self.assertEqual(merged["validation_transport"]["mode"], "mixed")
        self.assertEqual(merged["validation_transport"]["batch_request_count"], 3)
        self.assertEqual(merged["validation_transport"]["report_count"], 2)
        self.assertFalse(merged["validation_transport"]["fallback"])
        self.assertEqual([item["id"] for item in merged["checked"]], ["old", "phoneme"])
        self.assertEqual(merged["checked"][0]["status"], "review")
        self.assertEqual(merged["checked"][0]["timeline"], "/workspace/outputs/lipsync/old-rerun.face.json")

    def test_combined_result_applies_lipsync_timeline_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp) / "batch.json"
            batch.write_text(
                json.dumps(
                    {
                        "jobs": [
                            {
                                "id": "legacy",
                                "metadata": {"tags": ["generated"]},
                                "environment": {
                                    "LIPSYNC_TIMELINE_JSON": "/workspace/outputs/lipsync/text.face.json"
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            overrides = {
                "/workspace/outputs/lipsync/text.face.json": {
                    "from": "/workspace/outputs/lipsync/text.face.json",
                    "to": "/workspace/outputs/lipsync/rhubarb.face.json",
                    "reason": "audio-derived replacement",
                }
            }

            result = combine_batch_results([batch], lipsync_timeline_overrides=overrides)

        job = result["jobs"][0]
        self.assertEqual(job["lipsync_timeline_override"], "/workspace/outputs/lipsync/rhubarb.face.json")
        self.assertEqual(job["environment"]["LIPSYNC_TIMELINE_JSON"], "/workspace/outputs/lipsync/rhubarb.face.json")
        self.assertIn("lipsync-override:audio-derived", job["metadata"]["tags"])

    def test_combined_result_applies_overrides_from_animation_report_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "legacy_animation.json"
            report.write_text(
                json.dumps(
                    {
                        "lipsync_animation": {
                            "timeline": "/workspace/outputs/lipsync/text.face.json",
                        }
                    }
                ),
                encoding="utf-8",
            )
            batch = Path(tmp) / "batch.json"
            batch.write_text(
                json.dumps(
                    {
                        "jobs": [
                            {
                                "id": "report-only-legacy",
                                "metadata": {"tags": ["generated"]},
                                "environment": {
                                    "ANIMATION_REPORT_JSON": str(report),
                                    "OUTPUT_GLB": "/workspace/outputs/batch/report-only.glb",
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            overrides = {
                "/workspace/outputs/lipsync/text.face.json": {
                    "from": "/workspace/outputs/lipsync/text.face.json",
                    "to": "/workspace/outputs/lipsync/rhubarb.face.json",
                    "reason": "audio-derived replacement",
                }
            }

            result = combine_batch_results([batch], lipsync_timeline_overrides=overrides)

        job = result["jobs"][0]
        self.assertEqual(job["lipsync_timeline_override"], "/workspace/outputs/lipsync/rhubarb.face.json")
        self.assertEqual(job["environment"]["LIPSYNC_TIMELINE_JSON"], "/workspace/outputs/lipsync/rhubarb.face.json")
        self.assertEqual(
            job["lipsync_timeline_override_source"],
            "/workspace/outputs/lipsync/text.face.json",
        )
        self.assertIn("lipsync-override:audio-derived", job["metadata"]["tags"])

    def test_combined_result_can_apply_override_from_godot_validation_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp) / "batch.json"
            batch.write_text(
                json.dumps(
                    {
                        "jobs": [
                            {
                                "id": "legacy",
                                "metadata": {"tags": ["generated"]},
                                "environment": {"ANIMATION_REPORT_JSON": "/workspace/results/legacy.json"},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            validation = {
                "checked": [
                    {
                        "id": "legacy",
                        "status": "ok",
                        "timeline": "/workspace/outputs/lipsync/text.face.json",
                    }
                ]
            }
            overrides = {
                "/workspace/outputs/lipsync/text.face.json": {
                    "from": "/workspace/outputs/lipsync/text.face.json",
                    "to": "/workspace/outputs/lipsync/rhubarb.face.json",
                    "reason": "audio-derived replacement",
                }
            }

            result = combine_batch_results(
                [batch],
                godot_lipsync_validation=validation,
                lipsync_timeline_overrides=overrides,
            )

        job = result["jobs"][0]
        self.assertEqual(job["lipsync_timeline_override"], "/workspace/outputs/lipsync/rhubarb.face.json")
        self.assertEqual(job["environment"]["LIPSYNC_TIMELINE_JSON"], "/workspace/outputs/lipsync/rhubarb.face.json")
        self.assertIn("lipsync-override-from:validation", job["metadata"]["tags"])


if __name__ == "__main__":
    unittest.main()
