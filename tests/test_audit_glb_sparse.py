import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.audit_glb_sparse import audit_jobs, report_glb_path


class AuditGlbSparseTests(unittest.TestCase):
    def test_report_glb_path_prefers_optimized_report_glb(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            report = root / "results/person.json"
            report.parent.mkdir(parents=True)
            report.write_text(
                json.dumps(
                    {
                        "output_glb": "/workspace/outputs/batch/raw.glb",
                        "optimized_glb": "/workspace/outputs/batch_optimized/person.glb",
                    }
                ),
                encoding="utf-8",
            )

            path = report_glb_path(
                {"environment": {"ANIMATION_REPORT_JSON": "/workspace/results/person.json"}},
                root=root,
            )

        self.assertEqual(path, root / "outputs/batch_optimized/person.glb")

    def test_audit_jobs_counts_sparse_dense_and_missing_glbs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "outputs").mkdir()
            sparse_glb = root / "outputs/sparse.glb"
            dense_glb = root / "outputs/dense.glb"
            sparse_glb.write_bytes(b"sparse")
            dense_glb.write_bytes(b"dense")
            combined = {
                "jobs": [
                    {"id": "sparse", "environment": {"OUTPUT_GLB": "/workspace/outputs/sparse.glb"}},
                    {"id": "dense", "environment": {"OUTPUT_GLB": "/workspace/outputs/dense.glb"}},
                    {"id": "missing", "environment": {"OUTPUT_GLB": "/workspace/outputs/missing.glb"}},
                ]
            }
            docs = [
                {"accessors": [{"sparse": {"count": 1}}], "meshes": [], "skins": [], "animations": []},
                {"accessors": [], "meshes": [], "skins": [], "animations": []},
            ]

            with mock.patch("scripts.audit_glb_sparse.load_glb_json", side_effect=docs):
                summary = audit_jobs(combined, root=root)

        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["glb_count"], 3)
        self.assertEqual(summary["sparse_glb_count"], 1)
        self.assertEqual(summary["dense_glb_count"], 1)
        self.assertEqual(summary["missing_count"], 1)
        self.assertEqual(summary["top_sparse"][0]["id"], "sparse")
        self.assertTrue(summary["items"][0]["needs_sparse_densify"])


if __name__ == "__main__":
    unittest.main()
