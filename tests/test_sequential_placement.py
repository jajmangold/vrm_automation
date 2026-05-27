import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.sequential_placement import (  # noqa: E402
    apply_sequential_observation,
    initial_sequential_state,
    next_render_request,
    parse_view_sequence,
)


class SequentialPlacementTests(unittest.TestCase):
    def test_parse_view_sequence_rejects_empty_values(self):
        with self.assertRaises(ValueError):
            parse_view_sequence("")

    def test_next_view_uses_overrides_from_previous_solve(self):
        state = initial_sequential_state(
            {
                "asset_key": "necktie-jeremy",
                "category": "neck_chest",
                "view_sequence": "front,side",
                "current_overrides": {
                    "scale_axis": "height",
                    "target_size_ratio": 0.14,
                    "vertical_center_ratio": 0.76,
                    "front_offset_ratio": 0.26,
                },
            }
        )

        first_request = next_render_request(state)
        self.assertEqual(first_request["view"], "front")
        self.assertEqual(first_request["current_overrides"]["front_offset_ratio"], 0.26)

        state = apply_sequential_observation(
            state,
            {
                "view": "front",
                "current_box": [300, 360, 340, 500],
                "target_box": [300, 340, 340, 480],
                "character_box": [0, 0, 640, 960],
            },
        )
        second_request = next_render_request(state)

        self.assertEqual(second_request["view"], "side")
        self.assertGreater(second_request["current_overrides"]["vertical_center_ratio"], 0.76)
        self.assertEqual(len(state["observations"]), 1)

    def test_side_step_uses_fresh_front_solved_overrides(self):
        state = initial_sequential_state(
            {
                "asset_key": "necktie-jeremy",
                "category": "neck_chest",
                "view_sequence": ["front", "side"],
                "current_overrides": {
                    "scale_axis": "height",
                    "target_size_ratio": 0.14,
                    "vertical_center_ratio": 0.76,
                    "front_offset_ratio": 0.26,
                },
            }
        )
        state = apply_sequential_observation(
            state,
            {
                "view": "front",
                "current_box": [300, 360, 340, 500],
                "target_box": [300, 360, 340, 500],
                "character_box": [0, 0, 640, 960],
            },
        )
        state = apply_sequential_observation(
            state,
            {
                "view": "side",
                "current_box": [300, 360, 340, 500],
                "target_box": [620, 360, 660, 500],
                "character_box": [0, 0, 640, 960],
            },
        )

        self.assertTrue(state["complete"])
        self.assertIsNone(next_render_request(state))
        self.assertEqual(state["current_overrides"]["front_offset_ratio"], -0.05)
        self.assertEqual(state["current_overrides"]["target_size_ratio"], 0.14)
        self.assertEqual(state["current_overrides"]["vertical_center_ratio"], 0.76)
        self.assertEqual(len(state["iterations"]), 2)

    def test_side_step_does_not_reapply_previous_front_delta(self):
        state = initial_sequential_state(
            {
                "asset_key": "necktie-jeremy",
                "category": "neck_chest",
                "view_sequence": ["front", "side"],
                "current_overrides": {
                    "scale_axis": "height",
                    "target_size_ratio": 0.14,
                    "vertical_center_ratio": 0.76,
                    "front_offset_ratio": 0.26,
                },
            }
        )
        state = apply_sequential_observation(
            state,
            {
                "view": "front",
                "current_box": [300, 360, 340, 500],
                "target_box": [300, 340, 340, 480],
                "character_box": [0, 0, 640, 960],
            },
            center_correction_gain=0.42,
        )
        front_overrides = dict(state["current_overrides"])
        state = apply_sequential_observation(
            state,
            {
                "view": "side",
                "current_box": [300, 360, 340, 500],
                "target_box": [620, 360, 660, 500],
                "character_box": [0, 0, 640, 960],
            },
            center_correction_gain=0.42,
        )

        self.assertEqual(state["current_overrides"]["target_size_ratio"], front_overrides["target_size_ratio"])
        self.assertEqual(state["current_overrides"]["vertical_center_ratio"], front_overrides["vertical_center_ratio"])
        self.assertEqual(state["current_overrides"]["front_offset_ratio"], 0.05)


if __name__ == "__main__":
    unittest.main()
