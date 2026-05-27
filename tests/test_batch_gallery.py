import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_batch_gallery import (
    build_gallery,
    compact_godot_lipsync_validation,
    compact_lipsync_summary,
    godot_lipsync_validation_index,
    load_batch_result,
    render_angle,
)


class BatchGalleryTests(unittest.TestCase):
    def test_render_angle_detects_named_review_angles(self):
        self.assertEqual(render_angle("pose_back_0072.png"), "back")
        self.assertEqual(render_angle("pose_side_0072.png"), "side")
        self.assertEqual(render_angle("pose_portrait_0072.png"), "portrait")
        self.assertEqual(render_angle("pose_0072.png"), "front")

    def test_godot_lipsync_validation_index_uses_checked_assets(self):
        report = {
            "checked": [
                {"id": "ready", "status": "ok", "issues": []},
                {"id": "review", "status": "review", "issues": ["missing-visemes"]},
                {"status": "ok"},
            ]
        }

        index = godot_lipsync_validation_index(report)

        self.assertEqual(sorted(index), ["ready", "review"])
        self.assertEqual(index["review"]["issues"], ["missing-visemes"])

    def test_compact_godot_lipsync_validation_keeps_qa_fields_without_heavy_payloads(self):
        compact = compact_godot_lipsync_validation(
            {
                "id": "person-001",
                "status": "ok",
                "issues": [],
                "cue_count": 18,
                "timeline": "/workspace/outputs/lipsync/cache/demo.face.json",
                "timeline_visemes": ["rest", "aa"],
                "playback_status": {
                    "status": "playing",
                    "active_viseme": "aa",
                    "cue_index": 2,
                    "cue_count": 18,
                    "source": "/workspace/outputs/lipsync/cache/demo.face.json",
                },
                "load": {"animations": ["talk_idle_Armature"], "path": "/workspace/outputs/batch/demo.glb"},
                "validation_cache": {"key": "very-large-cache-key", "status": "hit"},
                "lipsync_quality": {
                    "status": "ok",
                    "grade": "A",
                    "score": 100,
                    "active_visemes": ["aa", "ee"],
                    "source_text": "Pat met Tim.",
                    "source_phoneme_counts": {"AE1": 1, "EH1": 1},
                },
            }
        )

        self.assertEqual(compact["id"], "person-001")
        self.assertEqual(compact["playback"]["active_viseme"], "aa")
        self.assertEqual(compact["lipsync_quality"]["grade"], "A")
        self.assertNotIn("load", compact)
        self.assertNotIn("validation_cache", compact)
        self.assertNotIn("source", compact["playback"])
        self.assertNotIn("source_phoneme_counts", compact["lipsync_quality"])

    def test_compact_lipsync_summary_keeps_display_fields_without_repeated_count_maps(self):
        compact = compact_lipsync_summary(
            {
                "cue_count": 18,
                "duration": 1.86,
                "visemes": ["rest", "aa"],
                "source_unique_phonemes": ["P", "AE1"],
                "source_phoneme_counts": {"P": 2, "AE1": 1},
                "quality": {
                    "status": "ok",
                    "grade": "A",
                    "score": 100,
                    "source_text": "Pat met Tim.",
                    "source_phoneme_counts": {"P": 2, "AE1": 1},
                    "viseme_counts": {"rest": 12, "aa": 1},
                },
            }
        )

        self.assertEqual(compact["cue_count"], 18)
        self.assertEqual(compact["source_unique_phonemes"], ["P", "AE1"])
        self.assertEqual(compact["quality"]["grade"], "A")
        self.assertNotIn("source_phoneme_counts", compact)
        self.assertNotIn("source_phoneme_counts", compact["quality"])
        self.assertNotIn("viseme_counts", compact["quality"])

    def test_load_batch_result_can_merge_godot_lipsync_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch_path = Path(tmp) / "batch.json"
            validation_path = Path(tmp) / "validation.json"
            batch_path.write_text(json.dumps({"jobs": [{"id": "person-001"}]}), encoding="utf-8")
            validation_path.write_text(
                json.dumps({"status": "ok", "checked": [{"id": "person-001", "status": "ok"}]}),
                encoding="utf-8",
            )

            batch = load_batch_result(batch_path, validation_path)

        self.assertEqual(batch["godot_lipsync_validation"]["checked"][0]["id"], "person-001")
        self.assertEqual(batch["godot_lipsync_summary"]["checked_count"], 1)

    def test_build_gallery_includes_job_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "gallery.html"
            report_path = ROOT / "results/test_gallery_report.json"
            prepare_path = ROOT / "results/talking_person/test-person.prepare.json"
            text_path = ROOT / "results/talking_person/test-person.text.json"
            timeline_path = ROOT / "outputs/lipsync/test-person.face.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            prepare_path.parent.mkdir(parents=True, exist_ok=True)
            timeline_path.parent.mkdir(parents=True, exist_ok=True)
            timeline_path.write_text(
                json.dumps(
                    {
                        "schema": "vrm-person-factory.face-timeline.v1",
                        "duration": 1.25,
                        "cues": [
                            {"time": 0.0, "duration": 0.1, "viseme": "aa", "value": 0.8},
                            {"time": 0.1, "duration": 0.1, "viseme": "ee", "value": 0.7},
                            {"time": 0.2, "duration": 0.1, "viseme": "rest", "value": 0.0},
                        ],
                        "expressions": [{"time": 0.0, "duration": 0.2, "name": "happy", "value": 0.3}],
                    }
                ),
                encoding="utf-8",
            )
            report_path.write_text(
                json.dumps(
                    {
                        "animation": "cheerful_wave",
                        "exports": {"glb": True},
                        "timings": {
                            "pose_render_seconds": 15.228,
                            "export_seconds": 1.758,
                        },
                        "output_glb": "/workspace/outputs/batch/test-person_lipsync.glb",
                        "optimized_glb": "/workspace/outputs/batch_optimized/test-person_lipsync.glb",
                        "asset_optimization": {
                            "status": "ok",
                            "profile": "standard",
                            "optimization_strategy": "gltf-transform-optimize",
                            "source_bytes": 1000,
                            "optimized_bytes": 600,
                            "saved_bytes": 400,
                            "size_ratio": 0.6,
                        },
                        "pose_renders": ["/workspace/outputs/test-person_pose_portrait_0072.png"],
                        "lipsync_animation": {
                            "enabled": True,
                            "cue_count": 48,
                            "keyed_visemes": ["aa", "ih", "ou", "ee", "oh"],
                            "timeline": "/workspace/outputs/lipsync/test-person.face.json",
                        },
                        "expression_animation": {
                            "preset": "talking_soft",
                            "keyed": ["happy", "smile", "blink"],
                            "keyed_visemes": ["aa", "ih"],
                        },
                        "face_profile": {
                            "quality": {
                                "grade": "A",
                                "viseme_count": 5,
                                "missing_visemes": [],
                            },
                            "visemes": {
                                "aa": {},
                                "ee": {},
                                "ih": {},
                                "oh": {},
                                "ou": {},
                            },
                        },
                        "talking_video": "/workspace/outputs/musetalk/test-person_hello.mp4",
                        "talking_video_backend": "musetalk",
                        "external_outfit": {
                            "classification": {"category": "head_face"},
                            "fit_check": {"status": "ok", "warnings": []},
                        },
                    }
                ),
                encoding="utf-8",
            )
            prepare_path.write_text(
                json.dumps(
                    {
                        "cache": {
                            "audio_cache_key": "abc123",
                            "lipsync_timeline": "/workspace/outputs/lipsync/cache/abc123.face.json",
                            "reused_lipsync": True,
                        }
                    }
                ),
                encoding="utf-8",
            )
            text_path.write_text(
                json.dumps(
                    {
                        "audio_cache_key": "abc123",
                        "cache_paths": {
                            "audio_wav": "outputs/speech/cache/abc123.wav",
                            "lipsync_timeline": "outputs/lipsync/cache/abc123.face.json",
                        },
                        "reused_audio": True,
                    }
                ),
                encoding="utf-8",
            )
            try:
                html = build_gallery(
                    {
                    "manifest": "config/person_factory.quick.json",
                    "godot_lipsync_validation": {
                        "status": "ok",
                        "checked": [
                            {
                                "id": "test-person",
                                "status": "ok",
                                "issues": [],
                                "cue_count": 3,
                                "missing_visemes": [],
                                "playback_status": {
                                    "status": "playing",
                                    "cue_index": 2,
                                    "cue_count": 3,
                                    "active_viseme": "ee",
                                },
                            }
                        ],
                    },
                    "jobs": [
                            {
                                "id": "test-person",
                                "status": "ok",
                                "metadata": {
                                    "display_name": "Test Persona",
                                    "persona": "calm QA subject",
                                    "tags": ["fast-review", "face", "monocle-google"],
                                },
                                "environment": {
                                    "ANIMATION_REPORT_JSON": "/workspace/results/test_gallery_report.json"
                                },
                            }
                        ],
                    },
                    output_path,
                )
            finally:
                report_path.unlink(missing_ok=True)
                prepare_path.unlink(missing_ok=True)
                text_path.unlink(missing_ok=True)
                timeline_path.unlink(missing_ok=True)

        self.assertIn("Test Persona", html)
        self.assertIn("Rendered preview", html)
        self.assertIn("MuseTalk / preview", html)
        self.assertIn("talking-video:available", html)
        self.assertIn("talking-video-backend:musetalk", html)
        self.assertIn("talking-video-quality:preview", html)
        self.assertIn("Lip sync", html)
        self.assertIn("lip ok", html)
        self.assertIn("Missing active: none", html)
        self.assertIn("Lip quality", html)
        self.assertIn("3 cues / 1.25s", html)
        self.assertIn("aa, ee, rest", html)
        self.assertIn("viseme:aa", html)
        self.assertIn("viseme:ee", html)
        self.assertIn("lipsync-cues:3", html)
        self.assertIn("data-lipsync-cues=\"3\"", html)
        self.assertIn("data-lipsync-duration=\"1.25\"", html)
        self.assertIn("lipsync:enabled", html)
        self.assertIn("lip-ready", html)
        self.assertIn("Lip-ready", html)
        self.assertIn("data-lipsync-readiness=\"ready\"", html)
        self.assertIn("data-lipsync-quality=\"ok\"", html)
        self.assertIn("lipsync-quality:ok", html)
        self.assertIn("lipsync-source:unknown", html)
        self.assertIn("lipsync-warning:unknown-lipsync-source", html)
        self.assertIn("Timeline JSON", html)
        self.assertIn('href="lipsync/test-person.face.json"', html)
        self.assertIn('data-lipsync-timeline="/workspace/outputs/lipsync/test-person.face.json"', html)
        self.assertIn("cache:line", html)
        self.assertIn("cache-key:abc123", html)
        self.assertIn("audio-cache:hit", html)
        self.assertIn("lipsync-cache:hit", html)
        self.assertIn("godot-lipsync:ok", html)
        self.assertIn("godot-lipsync-ok", html)
        self.assertIn("data-godot-lipsync-validation=\"ok\"", html)
        self.assertIn("<b>Godot lip</b><span>ok · 3 cues</span>", html)
        self.assertIn("&quot;playback&quot;", html)
        self.assertNotIn("&quot;playback_status&quot;", html)
        self.assertNotIn("&quot;source_phoneme_counts&quot;", html)
        self.assertIn("<b>Cache</b>", html)
        self.assertIn("&quot;audio_cache_key&quot;: &quot;abc123&quot;", html)
        self.assertIn("face-preset:talking-soft", html)
        self.assertIn("facial-visemes", html)
        self.assertIn("glb:optimized", html)
        self.assertIn("glb-profile:standard", html)
        self.assertIn("glb-saved:40pct", html)
        self.assertIn("<b>GLB</b><span>optimized · 40% saved · 600 B</span>", html)
        self.assertIn('data-glb-optimized="ok"', html)
        self.assertIn('data-glb-profile="standard"', html)
        self.assertIn('data-glb-size-ratio="0.6"', html)
        self.assertIn('data-glb-saved-pct="40"', html)
        self.assertIn("&quot;pose_render_seconds&quot;: 15.228", html)
        self.assertIn("&quot;export_seconds&quot;: 1.758", html)
        self.assertIn("issue:open-eye-review", html)
        self.assertIn("frame:portrait-0072", html)
        self.assertIn("test-person_lipsync.glb", html)
        self.assertIn('href="batch_optimized/test-person_lipsync.glb"', html)
        self.assertIn('href="results/test_gallery_report.json"', html)
        self.assertNotIn(str(ROOT), html)
        self.assertIn("test-person_hello.mp4", html)
        self.assertIn("cheerful_wave", html)
        self.assertIn("head_face", html)
        self.assertIn("data-filter=\"animation:cheerful_wave\"", html)
        self.assertIn("data-filter=\"category:head_face\"", html)
        self.assertIn("id=\"search\"", html)
        self.assertIn("id=\"clearFilters\"", html)
        self.assertIn("data-action=\"load\"", html)

    def test_build_gallery_compact_detail_mode_keeps_links_and_omits_heavy_debug_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "gallery.html"
            report_path = ROOT / "results/test_gallery_compact_report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "animation": "talk_idle",
                        "output_glb": "/workspace/outputs/batch/test-compact.glb",
                        "timings": {"pose_render_seconds": 15.228},
                        "frames": [{"frame": 1, "detail": "heavy"}],
                        "lipsync_animation": {"enabled": True, "timeline": "/workspace/outputs/lipsync/test.face.json"},
                    }
                ),
                encoding="utf-8",
            )
            try:
                html = build_gallery(
                    {
                        "manifest": "combined:test",
                        "jobs": [
                            {
                                "id": "test-compact",
                                "status": "ok",
                                "metadata": {"display_name": "Compact Test"},
                                "environment": {
                                    "ANIMATION_REPORT_JSON": "/workspace/results/test_gallery_compact_report.json"
                                },
                            }
                        ],
                    },
                    output_path,
                    detail_mode="compact",
                )
            finally:
                report_path.unlink(missing_ok=True)

        self.assertIn("Compact Test", html)
        self.assertIn('href="results/test_gallery_compact_report.json"', html)
        self.assertIn("Full debug JSON is available", html)
        self.assertNotIn("&quot;lipsync_summary&quot;", html)
        self.assertNotIn("&quot;frames&quot;", html)
        self.assertNotIn("&quot;pose_render_seconds&quot;", html)
        self.assertIn("data-action=\"play\"", html)
        self.assertIn("data-action=\"talk\"", html)
        self.assertIn("data-action=\"smile\"", html)
        self.assertIn("data-action=\"export\"", html)
        self.assertIn("/lipsync", html)
        self.assertIn("data-review-priority=", html)
        self.assertIn("reviewOnly", html)
        self.assertIn("http://127.0.0.1:8790", html)
        self.assertIn("GLB", html)

    def test_build_gallery_marks_control_only_renderless_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "gallery.html"
            report_path = ROOT / "results/test_gallery_control_report.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "animation": "talk_idle",
                        "exports": {"glb": True},
                        "output_glb": "/workspace/outputs/batch/control-only.glb",
                        "optimized_glb": "/workspace/outputs/batch_optimized/control-only.glb",
                        "pose_renders": [],
                        "lipsync_animation": {
                            "enabled": True,
                            "cue_count": 12,
                            "timeline": "/workspace/outputs/lipsync/control.face.json",
                        },
                        "external_outfit": {
                            "classification": {"category": "neck_chest"},
                            "fit_check": {"status": "ok", "warnings": []},
                        },
                    }
                ),
                encoding="utf-8",
            )
            try:
                html = build_gallery(
                    {
                        "jobs": [
                            {
                                "id": "control-only",
                                "status": "ok",
                                "metadata": {
                                    "display_name": "Control Only",
                                    "persona": "game-ready test subject",
                                    "tags": ["controllable"],
                                },
                                "environment": {
                                    "ANIMATION_REPORT_JSON": "/workspace/results/test_gallery_control_report.json",
                                    "RENDER_POSE_STILLS": "0",
                                    "OUTPUT_GLB": "/workspace/outputs/batch/control-only.glb",
                                },
                            }
                        ],
                        "godot_lipsync_validation": {
                            "checked": [{"id": "control-only", "status": "ok", "cue_count": 12, "issues": []}]
                        },
                    },
                    output_path,
                )
            finally:
                report_path.unlink(missing_ok=True)

        self.assertIn("control-only", html)
        self.assertIn("renderless-preview", html)
        self.assertIn("control-ready", html)
        self.assertIn("No Blender PNG", html)
        self.assertIn("Optimized GLB", html)
        self.assertIn("Timeline JSON", html)
        self.assertIn('data-renders="0"', html)
        self.assertIn('data-render-mode="control-only"', html)

    def test_build_gallery_prefers_lipsync_timeline_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "gallery.html"
            report_path = ROOT / "results/test_gallery_override_report.json"
            old_timeline = ROOT / "outputs/lipsync/test-old.face.json"
            override_timeline = ROOT / "outputs/lipsync/test-rhubarb.face.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            old_timeline.parent.mkdir(parents=True, exist_ok=True)
            old_timeline.write_text(
                json.dumps(
                    {
                        "source": {"mode": "text"},
                        "duration": 0.2,
                        "cues": [{"time": 0.0, "duration": 0.2, "viseme": "aa", "value": 1.0}],
                    }
                ),
                encoding="utf-8",
            )
            override_timeline.write_text(
                json.dumps(
                    {
                        "source": {"mode": "rhubarb"},
                        "duration": 0.4,
                        "cues": [
                            {"time": 0.0, "duration": 0.2, "viseme": "aa", "value": 0.9},
                            {"time": 0.2, "duration": 0.2, "viseme": "ee", "value": 0.9},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            report_path.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "exports": {"glb": True},
                        "output_glb": "/workspace/outputs/batch/override.glb",
                        "lipsync_animation": {
                            "enabled": True,
                            "cue_count": 1,
                            "timeline": "/workspace/outputs/lipsync/test-old.face.json",
                        },
                        "face_profile": {
                            "quality": {"viseme_count": 5, "missing_visemes": []},
                            "visemes": {"aa": {}, "ee": {}, "ih": {}, "oh": {}, "ou": {}},
                        },
                    }
                ),
                encoding="utf-8",
            )
            try:
                html = build_gallery(
                    {
                        "jobs": [
                            {
                                "id": "override-demo",
                                "status": "ok",
                                "lipsync_timeline_override": "/workspace/outputs/lipsync/test-rhubarb.face.json",
                                "metadata": {"tags": ["generated"]},
                                "environment": {
                                    "ANIMATION_REPORT_JSON": "/workspace/results/test_gallery_override_report.json",
                                    "OUTPUT_GLB": "/workspace/outputs/batch/override.glb",
                                },
                            }
                        ]
                    },
                    output_path,
                )
            finally:
                report_path.unlink(missing_ok=True)
                old_timeline.unlink(missing_ok=True)
                override_timeline.unlink(missing_ok=True)

        self.assertIn('href="lipsync/test-rhubarb.face.json"', html)
        self.assertIn('data-lipsync-timeline="/workspace/outputs/lipsync/test-rhubarb.face.json"', html)
        self.assertIn("lipsync-source:rhubarb", html)
        self.assertNotIn('href="lipsync/test-old.face.json"', html)

    def test_build_gallery_reuses_timeline_analysis_for_duplicate_timelines(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "gallery.html"
            timeline_path = ROOT / "outputs/lipsync/test-reused.face.json"
            timeline_path.parent.mkdir(parents=True, exist_ok=True)
            timeline_path.write_text(
                json.dumps(
                    {
                        "source": {"mode": "phoneme-events"},
                        "duration": 0.4,
                        "cues": [
                            {"time": 0.0, "duration": 0.2, "viseme": "aa", "value": 1.0},
                            {"time": 0.2, "duration": 0.2, "viseme": "ee", "value": 1.0},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            calls = []

            def fake_analyze(timeline):
                calls.append(timeline)
                return {"source_mode": "phoneme-events", "status": "ok", "grade": "A"}

            try:
                with mock.patch("scripts.build_batch_gallery.analyze_lipsync_timeline", side_effect=fake_analyze):
                    html = build_gallery(
                        {
                            "jobs": [
                                {
                                    "id": "reuse-001",
                                    "status": "ok",
                                    "metadata": {"tags": ["generated"]},
                                    "environment": {
                                        "ANIMATION_REPORT_JSON": "/workspace/results/reuse-001-missing.json",
                                        "LIPSYNC_TIMELINE_JSON": "/workspace/outputs/lipsync/test-reused.face.json",
                                        "OUTPUT_GLB": "/workspace/outputs/batch/reuse-001.glb",
                                    },
                                },
                                {
                                    "id": "reuse-002",
                                    "status": "ok",
                                    "metadata": {"tags": ["generated"]},
                                    "environment": {
                                        "ANIMATION_REPORT_JSON": "/workspace/results/reuse-002-missing.json",
                                        "LIPSYNC_TIMELINE_JSON": "/workspace/outputs/lipsync/test-reused.face.json",
                                        "OUTPUT_GLB": "/workspace/outputs/batch/reuse-002.glb",
                                    },
                                },
                            ]
                        },
                        output_path,
                        detail_mode="compact",
                    )
            finally:
                timeline_path.unlink(missing_ok=True)

        self.assertIn("reuse-001", html)
        self.assertIn("reuse-002", html)
        self.assertEqual(len(calls), 1)

    def test_build_gallery_includes_pagination_controls_for_large_batches(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "gallery.html"
            html = build_gallery(
                {
                    "jobs": [
                        {
                            "id": f"paged-{index:03d}",
                            "status": "ok",
                            "metadata": {"tags": ["generated"]},
                            "environment": {
                                "ANIMATION_REPORT_JSON": f"/workspace/results/paged-{index:03d}-missing.json",
                                "OUTPUT_GLB": f"/workspace/outputs/batch/paged-{index:03d}.glb",
                            },
                        }
                        for index in range(1, 65)
                    ]
                },
                output_path,
                detail_mode="compact",
            )

        self.assertIn('id="pageSize"', html)
        self.assertIn('id="prevPage"', html)
        self.assertIn('id="nextPage"', html)
        self.assertIn('id="pageInfo"', html)
        self.assertIn("currentPage", html)

    def test_build_gallery_exposes_phoneme_source_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "gallery.html"
            report_path = ROOT / "results/test_gallery_phoneme_report.json"
            timeline_path = ROOT / "outputs/lipsync/test-phonemes.face.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            timeline_path.parent.mkdir(parents=True, exist_ok=True)
            timeline_path.write_text(
                json.dumps(
                    {
                        "schema": "vrm-person-factory.face-timeline.v1",
                        "source": {
                            "mode": "phoneme-events",
                            "input_mode": "manual-arpabet",
                            "text": "Hello",
                            "source_schema": "vrm-person-factory.phoneme-events.v1",
                            "source_path": "config/lipsync_hello_phonemes.json",
                            "event_count": 3,
                            "phoneme_count": 3,
                            "unique_phonemes": ["HH", "EH1", "OW1"],
                            "phoneme_counts": {"HH": 1, "EH1": 1, "OW1": 1},
                        },
                        "duration": 0.36,
                        "cues": [
                            {"time": 0.0, "duration": 0.1, "viseme": "rest", "value": 0.0, "source_index": 0, "source_phoneme": "HH"},
                            {"time": 0.1, "duration": 0.12, "viseme": "ee", "value": 0.8, "source_index": 1, "source_phoneme": "EH1"},
                            {"time": 0.22, "duration": 0.14, "viseme": "oh", "value": 0.8, "source_index": 2, "source_phoneme": "OW1"},
                        ],
                        "expressions": [{"time": 0.0, "duration": 0.36, "name": "happy", "value": 0.2}],
                    }
                ),
                encoding="utf-8",
            )
            report_path.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "exports": {"glb": True},
                        "output_glb": "/workspace/outputs/batch/phoneme.glb",
                        "lipsync_animation": {
                            "enabled": True,
                            "timeline": "/workspace/outputs/lipsync/test-phonemes.face.json",
                        },
                        "face_profile": {
                            "quality": {"viseme_count": 5, "missing_visemes": []},
                            "visemes": {"aa": {}, "ee": {}, "ih": {}, "oh": {}, "ou": {}},
                        },
                    }
                ),
                encoding="utf-8",
            )
            try:
                html = build_gallery(
                    {
                        "jobs": [
                            {
                                "id": "phoneme-demo",
                                "status": "ok",
                                "metadata": {"tags": ["lip-sync", "vrm-visemes"]},
                                "environment": {
                                    "ANIMATION_REPORT_JSON": "/workspace/results/test_gallery_phoneme_report.json",
                                    "OUTPUT_GLB": "/workspace/outputs/batch/phoneme.glb",
                                },
                            }
                        ]
                    },
                    output_path,
                )
            finally:
                report_path.unlink(missing_ok=True)
                timeline_path.unlink(missing_ok=True)

        self.assertIn('data-lipsync-source="phoneme-events"', html)
        self.assertIn('data-lipsync-source-events="3"', html)
        self.assertIn('data-lipsync-phonemes="HH EH1 OW1"', html)
        self.assertIn('<div class="phoneme-strip">', html)
        self.assertIn('<b>Phonemes</b><span>3 · HH, EH1, OW1</span>', html)
        self.assertIn('<b>Source</b><span>phoneme-events / manual-arpabet</span>', html)
        self.assertIn("lipsync-source:phoneme-events", html)
        self.assertIn("lipsync-source-events:3", html)
        self.assertIn("&quot;source_event_count&quot;: 3", html)
        self.assertIn("&quot;source_input_mode&quot;: &quot;manual-arpabet&quot;", html)
        self.assertIn("&quot;source_unique_phonemes&quot;: [", html)
        self.assertIn("&quot;EH1&quot;", html)


if __name__ == "__main__":
    unittest.main()
