import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_complete_target_mask import slug, union_mask


class BuildCompleteTargetMaskTests(unittest.TestCase):
    def test_slug_normalizes_prompt(self):
        self.assertEqual(slug("Tie knot / neck loop"), "tie-knot---neck-loop")

    def test_union_mask_combines_prompt_masks(self):
        first = np.array([[False, True], [False, False]])
        second = np.array([[False, False], [True, False]])

        combined = union_mask([first, second])

        self.assertEqual(combined.tolist(), [[False, True], [True, False]])

    def test_union_mask_rejects_mismatched_shapes(self):
        with self.assertRaises(ValueError):
            union_mask([np.zeros((2, 2), dtype=bool), np.zeros((3, 2), dtype=bool)])

    def test_script_bootstraps_repo_imports_for_direct_execution(self):
        source = (ROOT / "scripts/build_complete_target_mask.py").read_text(encoding="utf-8")

        self.assertIn("sys.path.insert(0, str(ROOT))", source)
        self.assertIn("every prompt is an independent target-mask attempt", source)
        self.assertIn("selected_for_union", source)
        self.assertIn("target_bbox_aspect", source)


if __name__ == "__main__":
    unittest.main()
