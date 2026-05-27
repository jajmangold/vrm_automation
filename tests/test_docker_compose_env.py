import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DockerComposeEnvTests(unittest.TestCase):
    def test_animate_smoke_passes_outfit_fit_override_environment(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        for key in (
            "OUTFIT_SCALE_AXIS",
            "OUTFIT_TARGET_SIZE_RATIO",
            "OUTFIT_VERTICAL_CENTER_RATIO",
            "OUTFIT_HORIZONTAL_CENTER_OFFSET_RATIO",
            "OUTFIT_SURFACE_OFFSET_RATIO",
            "OUTFIT_ANCHOR_Z_PERCENTILE",
            "OUTFIT_ANCHOR_OFFSET_X",
            "OUTFIT_ANCHOR_OFFSET_Y",
            "OUTFIT_ANCHOR_OFFSET_Z",
            "OUTFIT_EXCLUDE_MATERIALS",
            "OUTFIT_ANCHOR",
            "OUTFIT_FIT_SCOPE",
            "OUTFIT_GEOMETRY_CONDITIONER",
            "OUTFIT_ROTATION_X_DEGREES",
            "OUTFIT_ROTATION_Y_DEGREES",
            "OUTFIT_ROTATION_Z_DEGREES",
            "OUTFIT_SURFACE_CONFORMER",
            "OUTFIT_SURFACE_CONFORM_RATIO",
            "OUTFIT_SURFACE_CONFORM_EXPONENT",
            "OUTFIT_SURFACE_CONFORM_PIN_TOP_RATIO",
            "OUTFIT_SURFACE_SNAP",
            "OUTFIT_SURFACE_SNAP_GAP_RATIO",
        ):
            with self.subTest(key=key):
                self.assertIn(f"{key}:", compose)

    def test_blender_silhouette_fit_service_runs_optimizer_script(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("blender-silhouette-fit:", compose)
        self.assertIn("scripts/blender_silhouette_fit.py", compose)
        self.assertIn("SILHOUETTE_TARGET_MASK:", compose)
        self.assertIn("SILHOUETTE_POPULATION_SIZE:", compose)
        self.assertIn("SILHOUETTE_SCALE_PRIOR_WEIGHT:", compose)
        self.assertIn("SILHOUETTE_AREA_PRIOR_WEIGHT:", compose)
        self.assertIn("SILHOUETTE_EXPECTED_MIN_BBOX_ASPECT:", compose)
        self.assertIn("SILHOUETTE_LOCK_SCALE_ON_SMALL_TARGET:", compose)
        self.assertIn("SILHOUETTE_OUTPUT_BLEND:", compose)
        self.assertIn("SILHOUETTE_DEBUG_DIR:", compose)
        self.assertIn("--population-size", compose)
        self.assertIn("--scale-prior-weight", compose)
        self.assertIn("--area-prior-weight", compose)
        self.assertIn("--lock-scale-on-small-target", compose)
        self.assertIn("--apply", compose)


if __name__ == "__main__":
    unittest.main()
