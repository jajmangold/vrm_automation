import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_sparse_densify_batch import build_sparse_batch, sparse_items_by_priority


class BuildSparseDensifyBatchTests(unittest.TestCase):
    def test_sparse_items_by_priority_orders_remaining_sparse_assets(self):
        audit = {
            "items": [
                {"id": "dense", "status": "ok", "needs_sparse_densify": False, "sparse_accessor_count": 0, "bytes": 10},
                {"id": "small", "status": "ok", "needs_sparse_densify": True, "sparse_accessor_count": 4, "bytes": 100},
                {"id": "large", "status": "ok", "needs_sparse_densify": True, "sparse_accessor_count": 9, "bytes": 50},
                {"id": "same-count-larger", "status": "ok", "needs_sparse_densify": True, "sparse_accessor_count": 4, "bytes": 200},
                {"id": "bad", "status": "error", "needs_sparse_densify": True, "sparse_accessor_count": 99, "bytes": 999},
            ]
        }

        ordered = sparse_items_by_priority(audit)

        self.assertEqual([item["id"] for item in ordered], ["large", "same-count-larger", "small"])

    def test_build_sparse_batch_selects_matching_jobs_with_limit_and_offset(self):
        combined = {
            "jobs": [
                {"id": "first", "environment": {"ANIMATION_REPORT_JSON": "/workspace/results/first.json"}},
                {"id": "second", "environment": {"ANIMATION_REPORT_JSON": "/workspace/results/second.json"}},
                {"id": "third", "environment": {"ANIMATION_REPORT_JSON": "/workspace/results/third.json"}},
            ]
        }
        audit = {
            "items": [
                {"id": "first", "status": "ok", "needs_sparse_densify": True, "sparse_accessor_count": 20, "bytes": 100},
                {"id": "missing", "status": "ok", "needs_sparse_densify": True, "sparse_accessor_count": 10, "bytes": 100},
                {"id": "second", "status": "ok", "needs_sparse_densify": True, "sparse_accessor_count": 9, "bytes": 100},
                {"id": "third", "status": "ok", "needs_sparse_densify": True, "sparse_accessor_count": 8, "bytes": 100},
            ]
        }

        batch = build_sparse_batch(combined, audit, limit=2, offset=1, manifest="sparse-next2")

        self.assertEqual(batch["status"], "review")
        self.assertEqual(batch["manifest"], "sparse-next2")
        self.assertEqual(batch["selection"]["selected_ids"], ["second"])
        self.assertEqual(batch["selection"]["missing_ids"], ["missing"])
        self.assertEqual([job["id"] for job in batch["jobs"]], ["second"])


if __name__ == "__main__":
    unittest.main()
