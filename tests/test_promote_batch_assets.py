import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.promote_batch_assets import (
    batch_id_from_result_path,
    default_paths,
    promote_batch_assets,
)


class PromoteBatchAssetsTests(unittest.TestCase):
    def test_batch_id_from_result_path_handles_person_factory_latest_names(self):
        self.assertEqual(
            batch_id_from_result_path(Path("results/batch_person_factory_control_prod_001_latest.json")),
            "control-prod-001",
        )
        self.assertEqual(
            batch_id_from_result_path(Path("results/batch_person_factory_auto_lip_020_latest.json")),
            "auto-lip-020",
        )

    def test_default_paths_are_stable(self):
        paths = default_paths(Path("results/batch_person_factory_control_prod_001_latest.json"))

        self.assertEqual(paths["batch_id"], "control-prod-001")
        self.assertEqual(paths["gallery"], Path("outputs/batch/person_factory_control-prod-001.html"))
        self.assertEqual(paths["summary"], Path("results/promote_batch_control_prod_001_latest.json"))
        self.assertEqual(paths["combined_gallery"], Path("outputs/batch/person_factory_all.html"))
        self.assertEqual(paths["combined_summary"], Path("results/person_factory_all_latest.json"))

    def test_promote_batch_runs_standard_finalize_and_combined_gallery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            batch_path = root / "results/batch_person_factory_control_prod_001_latest.json"
            batch_path.parent.mkdir(parents=True)
            batch_path.write_text(json.dumps({"jobs": []}), encoding="utf-8")

            with (
                mock.patch("scripts.promote_batch_assets.ROOT", root),
                mock.patch(
                    "scripts.promote_batch_assets.finalize_batch",
                    return_value={
                        "status": "ok",
                        "optimization": {
                            "count": 2,
                            "source_bytes": 1000,
                            "optimized_bytes": 250,
                            "saved_bytes": 750,
                            "size_ratio": 0.25,
                        },
                    },
                ) as finalize,
                mock.patch("scripts.promote_batch_assets.subprocess.run") as run,
            ):
                run.return_value.returncode = 0
                report = promote_batch_assets(
                    batch_path,
                    texture_size=768,
                    export_godot=True,
                )

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["batch_id"], "control-prod-001")
        self.assertEqual(report["optimization"]["saved_bytes"], 750)
        self.assertIn("finalize", report["stages"])
        self.assertIn("combined", report["stages"])
        finalize.assert_called_once()
        _, gallery_path = finalize.call_args.args[:2]
        self.assertEqual(gallery_path, root / "outputs/batch/person_factory_control-prod-001.html")
        self.assertEqual(finalize.call_args.kwargs["optimization_profile"], "standard")
        self.assertEqual(finalize.call_args.kwargs["texture_size"], 768)
        self.assertTrue(finalize.call_args.kwargs["skip_existing_optimized"])
        self.assertTrue(finalize.call_args.kwargs["export_godot"])
        self.assertTrue(finalize.call_args.kwargs["godot_skip_existing"])
        self.assertEqual(
            run.call_args.args[0],
            [
                "python3",
                "scripts/build_combined_gallery.py",
                "outputs/batch/person_factory_all.html",
                "--summary-json",
                "results/person_factory_all_latest.json",
            ],
        )

    def test_promote_batch_dry_run_records_plan_without_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            batch_path = root / "results/batch_person_factory_demo_latest.json"
            batch_path.parent.mkdir(parents=True)
            batch_path.write_text(json.dumps({"jobs": []}), encoding="utf-8")

            with (
                mock.patch("scripts.promote_batch_assets.ROOT", root),
                mock.patch("scripts.promote_batch_assets.finalize_batch") as finalize,
                mock.patch("scripts.promote_batch_assets.subprocess.run") as run,
            ):
                report = promote_batch_assets(batch_path, dry_run=True)

        self.assertEqual(report["status"], "dry-run")
        finalize.assert_not_called()
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
