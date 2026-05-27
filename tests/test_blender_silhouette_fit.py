import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.blender_silhouette_fit import (
    load_mask,
    load_union_target_mask,
    mask_quality,
    parse_args,
    parse_vector,
    resize_mask,
    save_mask_pgm,
    union_masks,
)


class BlenderSilhouetteFitTests(unittest.TestCase):
    def test_parse_vector_requires_expected_size(self):
        self.assertEqual(parse_vector("1,2,3", 3), [1.0, 2.0, 3.0])
        with self.assertRaises(Exception):
            parse_vector("1,2", 3)

    def test_cli_contract_exposes_pose_optimizer_controls(self):
        args = parse_args(
            [
                "--object-name",
                "necktie",
                "--target-mask",
                "target.json",
                "--initial-pose",
                "0,0,0,0,0,0,1",
                "--population-size",
                "12",
                "--generations",
                "4",
                "--apply",
            ]
        )

        self.assertEqual(args.object_name, "necktie")
        self.assertEqual(args.target_mask, ["target.json"])
        self.assertEqual(args.initial_pose, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0])
        self.assertEqual(args.population_size, 12)
        self.assertEqual(args.generations, 4)
        self.assertTrue(args.apply)
        self.assertEqual(args.lower_bounds, [-1.0, -1.0, -1.0, -3.14159, -3.14159, -3.14159, 0.05])

    def test_parse_args_uses_blender_script_separator(self):
        old_argv = sys.argv
        sys.argv = [
            "blender",
            "--background",
            "scene.blend",
            "--python",
            "scripts/blender_silhouette_fit.py",
            "--",
            "--object-name",
            "tie",
            "--target-mask",
            "mask.png",
        ]
        try:
            args = parse_args()
        finally:
            sys.argv = old_argv

        self.assertEqual(args.object_name, "tie")
        self.assertEqual(args.target_mask, ["mask.png"])

    def test_load_mask_accepts_json_mask_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mask.json"
            path.write_text(json.dumps({"mask": [[0, 1], [1, 0]]}), encoding="utf-8")

            mask = load_mask(path)

        self.assertEqual(mask, [[False, True], [True, False]])

    def test_resize_mask_uses_full_target_extent(self):
        mask = [
            [False, False, True, True],
            [False, False, True, True],
            [True, True, False, False],
            [True, True, False, False],
        ]

        self.assertEqual(resize_mask(mask, 2, 2), [[False, True], [True, False]])

    def test_union_masks_combines_multiple_sam_targets(self):
        union = union_masks([[[False, True], [False, False]], [[False, False], [True, False]]])

        self.assertEqual(union, [[False, True], [True, False]])

    def test_load_union_target_mask_resizes_mixed_viewports(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.json"
            second = Path(tmp) / "second.json"
            first.write_text(json.dumps([[0, 1], [0, 0]]), encoding="utf-8")
            second.write_text(json.dumps([[0, 0, 0, 0], [0, 0, 0, 0], [1, 1, 0, 0], [1, 1, 0, 0]]), encoding="utf-8")

            union = load_union_target_mask([first, second], 2, 2)

        self.assertEqual(union, [[False, True], [True, False]])

    def test_mask_quality_flags_empty_and_reports_bbox(self):
        self.assertIn("empty-target-mask", mask_quality([[False]])["warnings"])
        quality = mask_quality([[False, True], [False, True]])
        self.assertEqual(quality["foreground_pixels"], 2)
        self.assertEqual(quality["bbox"], [1, 0, 2, 2])
        slender = mask_quality([[False, True, False], [False, True, False], [False, True, False]], expected_min_bbox_aspect=0.5)
        self.assertIn("target-mask-too-slender-for-object", slender["warnings"])

    def test_save_mask_pgm_writes_reviewable_mask(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mask.pgm"
            save_mask_pgm(path, [[False, True], [True, False]])

            data = path.read_bytes()

        self.assertTrue(data.startswith(b"P5\n2 2\n255\n"))
        self.assertEqual(data[-4:], bytes([0, 255, 255, 0]))

    def test_blender_script_uses_rendered_alpha_mask_as_optimizer_objective(self):
        source = (ROOT / "scripts/blender_silhouette_fit.py").read_text(encoding="utf-8")

        self.assertIn("bpy.ops.render.render(write_still=True)", source)
        self.assertIn("scene.render.film_transparent = True", source)
        self.assertIn("bpy.data.images.load", source)
        self.assertIn("use_alpha = bool(alpha_values) and min(alpha_values) < 0.99", source)
        self.assertIn("silhouette_score(rendered_mask, target_mask", source)
        self.assertIn("optimize_pose(", source)
        self.assertIn("obj.location", source)
        self.assertIn("obj.rotation_euler", source)
        self.assertIn("obj.scale", source)
        self.assertIn("sys.path.insert(0, str(ROOT))", source)
        self.assertIn("bpy.ops.wm.save_as_mainfile", source)
        self.assertIn("best_rendered_mask.pgm", source)
        self.assertIn("scale_prior_penalty", source)
        self.assertIn("area_prior_penalty", source)
        self.assertIn("target-mask-smaller-than-initial-object", source)
        self.assertIn("target-mask-too-slender-for-object", source)
        self.assertIn("lock-scale-on-small-target", source)
        self.assertIn("scale_locked", source)


if __name__ == "__main__":
    unittest.main()
