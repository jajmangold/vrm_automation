import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.score_batch import score_batch


class ScoreBatchTests(unittest.TestCase):
    def test_score_batch_adds_summary_and_job_qa(self):
        result = score_batch(
            {
                "jobs": [
                    {
                        "id": "missing",
                        "status": "error",
                        "environment": {
                            "OUTPUT_GLB": "/workspace/missing.glb",
                            "EXPORT_GLB": "1",
                            "ANIMATION_REPORT_JSON": "/workspace/missing-report.json",
                        },
                    }
                ]
            }
        )

        self.assertEqual(result["qa_summary"]["review_count"], 1)
        self.assertEqual(result["jobs"][0]["qa"]["qa_grade"], "D")
        self.assertIn("missing-glb", result["jobs"][0]["qa"]["qa_flags"])


if __name__ == "__main__":
    unittest.main()
