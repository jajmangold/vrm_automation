import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.finalize_batch import (
    batch_asset_ids,
    default_contact_sheet_path,
    finalize_batch,
    post_godot_export_all,
    post_godot_reload_assets,
)


class FinalizeBatchTests(unittest.TestCase):
    def test_finalize_batch_runs_optimize_score_and_gallery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            batch_path = root / "results/batch.json"
            gallery_path = root / "outputs/gallery.html"
            summary_path = root / "results/finalize.json"
            batch_path.parent.mkdir(parents=True)
            batch_path.write_text(
                json.dumps(
                    {
                        "jobs": [
                            {
                                "id": "person",
                                "status": "ok",
                                "environment": {
                                    "ANIMATION_REPORT_JSON": "/workspace/results/person_animation.json"
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with (
                mock.patch(
                    "scripts.finalize_batch.optimize_batch",
                    return_value={"status": "ok", "count": 1, "saved_bytes": 123},
                ) as optimize,
                mock.patch(
                    "scripts.finalize_batch.score_batch",
                    return_value={
                        "jobs": [{"id": "person", "status": "ok", "qa": {"qa_grade": "A"}}],
                        "qa_summary": {"grades": {"A": 1}},
                    },
                ) as score,
                mock.patch("scripts.finalize_batch.build_gallery", return_value="<html>gallery</html>") as gallery,
                mock.patch("scripts.finalize_batch.build_contact_sheet", return_value="<html>contact</html>") as contact,
            ):
                summary = finalize_batch(
                    batch_path,
                    gallery_path,
                    optimized_dir=root / "optimized",
                    summary_path=summary_path,
                    export_godot=False,
                )

            self.assertEqual(summary["status"], "ok")
            self.assertEqual(summary["optimization"]["saved_bytes"], 123)
            self.assertEqual(summary["qa_summary"], {"grades": {"A": 1}})
            self.assertEqual(gallery_path.read_text(encoding="utf-8"), "<html>gallery</html>")
            self.assertEqual((root / "outputs/gallery_contact_sheet.html").read_text(encoding="utf-8"), "<html>contact</html>")
            self.assertEqual(summary["contact_sheet"], str(root / "outputs/gallery_contact_sheet.html"))
            self.assertIn("elapsed_seconds", summary)
            self.assertIn("optimize_seconds", summary["timings"])
            self.assertIn("score_seconds", summary["timings"])
            self.assertIn("gallery_seconds", summary["timings"])
            self.assertIn("contact_sheet_seconds", summary["timings"])
            self.assertTrue(summary_path.exists())
            optimize.assert_called_once()
            optimize_args = optimize.call_args.args[2]
            self.assertFalse(optimize_args.preserve_sparse_accessors)
            self.assertEqual(optimize_args.profile, "standard")
            self.assertFalse(optimize_args.skip_existing)
            score.assert_called_once()
            gallery.assert_called_once()
            contact.assert_called_once()

    def test_finalize_batch_passes_rough_preview_optimization_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            batch_path = root / "results/batch.json"
            gallery_path = root / "outputs/gallery.html"
            summary_path = root / "results/finalize.json"
            batch_path.parent.mkdir(parents=True)
            batch_path.write_text(json.dumps({"jobs": []}), encoding="utf-8")

            with (
                mock.patch(
                    "scripts.finalize_batch.optimize_batch",
                    return_value={"status": "ok", "profile": "rough_preview"},
                ) as optimize,
                mock.patch("scripts.finalize_batch.score_batch", return_value={"jobs": []}),
                mock.patch("scripts.finalize_batch.build_gallery", return_value="<html>gallery</html>"),
                mock.patch("scripts.finalize_batch.build_contact_sheet", return_value="<html>contact</html>"),
            ):
                summary = finalize_batch(
                    batch_path,
                    gallery_path,
                    optimized_dir=root / "optimized",
                    summary_path=summary_path,
                    optimization_profile="rough_preview",
                    skip_existing_optimized=True,
                )

        self.assertEqual(summary["optimization"]["profile"], "rough_preview")
        self.assertEqual(optimize.call_args.args[2].profile, "rough_preview")
        self.assertTrue(optimize.call_args.args[2].skip_existing)

    def test_default_contact_sheet_path_is_derived_from_gallery_path(self):
        self.assertEqual(
            default_contact_sheet_path(Path("outputs/batch/person_factory_demo.html")),
            Path("outputs/batch/person_factory_demo_contact_sheet.html"),
        )

    def test_finalize_batch_can_skip_contact_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            batch_path = root / "results/batch.json"
            gallery_path = root / "outputs/gallery.html"
            summary_path = root / "results/finalize.json"
            batch_path.parent.mkdir(parents=True)
            batch_path.write_text(json.dumps({"jobs": []}), encoding="utf-8")

            with (
                mock.patch("scripts.finalize_batch.optimize_batch", return_value={"status": "ok"}),
                mock.patch("scripts.finalize_batch.score_batch", return_value={"jobs": []}),
                mock.patch("scripts.finalize_batch.build_gallery", return_value="<html>gallery</html>"),
                mock.patch("scripts.finalize_batch.build_contact_sheet") as contact,
            ):
                summary = finalize_batch(
                    batch_path,
                    gallery_path,
                    optimized_dir=root / "optimized",
                    summary_path=summary_path,
                    build_contact_sheet_assets=False,
                )

        self.assertIsNone(summary["contact_sheet"])
        self.assertNotIn("contact_sheet_seconds", summary["timings"])
        contact.assert_not_called()

    def test_finalize_batch_can_skip_review_gallery_and_contact_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            batch_path = root / "results/batch.json"
            gallery_path = root / "outputs/gallery.html"
            summary_path = root / "results/finalize.json"
            batch_path.parent.mkdir(parents=True)
            batch_path.write_text(json.dumps({"jobs": []}), encoding="utf-8")

            with (
                mock.patch("scripts.finalize_batch.optimize_batch", return_value={"status": "ok"}),
                mock.patch("scripts.finalize_batch.score_batch", return_value={"jobs": []}),
                mock.patch("scripts.finalize_batch.build_gallery") as gallery,
                mock.patch("scripts.finalize_batch.build_contact_sheet") as contact,
            ):
                summary = finalize_batch(
                    batch_path,
                    gallery_path,
                    optimized_dir=root / "optimized",
                    summary_path=summary_path,
                    build_gallery_asset=False,
                    build_contact_sheet_assets=False,
                )

        self.assertIsNone(summary["gallery"])
        self.assertIsNone(summary["contact_sheet"])
        self.assertFalse(gallery_path.exists())
        self.assertNotIn("gallery_seconds", summary["timings"])
        self.assertNotIn("contact_sheet_seconds", summary["timings"])
        gallery.assert_not_called()
        contact.assert_not_called()

    def test_post_godot_export_all_skips_existing_assets_by_default(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"status":"ok","exported":[],"failed":[]}'

        with mock.patch("urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
            result = post_godot_export_all("http://127.0.0.1:8790", timeout=10)

        self.assertEqual(result["status"], "ok")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:8790/export-all-game-assets")
        self.assertEqual(request.get_method(), "POST")
        self.assertIn(b'"skip_existing": true', request.data)

    def test_post_godot_export_all_can_filter_to_current_asset_ids(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"status":"ok","exported":[],"failed":[]}'

        with mock.patch("urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
            result = post_godot_export_all(
                "http://127.0.0.1:8790",
                timeout=10,
                asset_ids=["person-001", "person-002"],
            )

        self.assertEqual(result["status"], "ok")
        request = urlopen.call_args.args[0]
        self.assertIn(b'"asset_ids": ["person-001", "person-002"]', request.data)

    def test_batch_asset_ids_reads_job_ids_in_order(self):
        self.assertEqual(
            batch_asset_ids(
                {
                    "jobs": [
                        {"id": "person-001"},
                        {"id": ""},
                        {"id": "person-002"},
                        {"id": "person-001"},
                    ]
                }
            ),
            ["person-001", "person-002"],
        )

    def test_finalize_batch_exports_only_current_batch_asset_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            batch_path = root / "results/batch.json"
            gallery_path = root / "outputs/gallery.html"
            summary_path = root / "results/finalize.json"
            batch_path.parent.mkdir(parents=True)
            batch_path.write_text(
                json.dumps({"jobs": [{"id": "person-001"}, {"id": "person-002"}]}),
                encoding="utf-8",
            )

            with (
                mock.patch("scripts.finalize_batch.optimize_batch", return_value={"status": "ok"}),
                mock.patch("scripts.finalize_batch.score_batch", return_value={"jobs": [{"id": "person-001"}, {"id": "person-002"}]}),
                mock.patch("scripts.finalize_batch.build_gallery", return_value="<html>gallery</html>"),
                mock.patch("scripts.finalize_batch.build_contact_sheet", return_value="<html>contact</html>"),
                mock.patch("scripts.finalize_batch.post_godot_reload_assets", return_value={"status": "ok"}),
                mock.patch("scripts.finalize_batch.post_godot_export_all", return_value={"status": "ok"}) as export,
            ):
                finalize_batch(
                    batch_path,
                    gallery_path,
                    optimized_dir=root / "optimized",
                    summary_path=summary_path,
                    export_godot=True,
                )

        self.assertEqual(export.call_args.kwargs["asset_ids"], ["person-001", "person-002"])

    def test_post_godot_export_all_can_force_refresh(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"status":"ok","exported":[],"failed":[]}'

        with mock.patch("urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
            result = post_godot_export_all("http://127.0.0.1:8790", timeout=10, skip_existing=False)

        self.assertEqual(result["status"], "ok")
        request = urlopen.call_args.args[0]
        self.assertIn(b'"skip_existing": false', request.data)

    def test_post_godot_reload_assets_can_send_batch_result_path(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"status":"ok","asset_count":1}'

        with mock.patch("urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
            result = post_godot_reload_assets(
                "http://127.0.0.1:8790",
                Path("/srv/nvme-data/containers/projects/vrm_automation/results/now.json"),
                timeout=10,
            )

        self.assertEqual(result["status"], "ok")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:8790/reload-assets")
        self.assertEqual(request.get_method(), "POST")
        self.assertIn(b"/workspace/results/now.json", request.data)
        self.assertIn(b'"scoped": true', request.data)

    def test_post_godot_reload_assets_can_disable_scoped_reload(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"status":"ok","asset_count":1}'

        with mock.patch("urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
            post_godot_reload_assets(
                "http://127.0.0.1:8790",
                Path("/srv/nvme-data/containers/projects/vrm_automation/results/now.json"),
                timeout=10,
                scoped=False,
            )

        request = urlopen.call_args.args[0]
        self.assertIn(b'"scoped": false', request.data)


if __name__ == "__main__":
    unittest.main()
