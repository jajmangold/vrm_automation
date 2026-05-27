import sys
import unittest
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.download_poly_pizza_assets import find_glb_url
from scripts.download_poly_pizza_assets import validate_asset_metadata


class PolyPizzaDownloadTests(unittest.TestCase):
    def test_find_glb_url_decodes_first_static_model_url(self):
        html = 'poster="x.jpg" src=https://static.poly.pizza/example-id.glb&amp;poster=y'

        self.assertEqual(find_glb_url(html), "https://static.poly.pizza/example-id.glb")

    def test_find_glb_url_requires_model_url(self):
        with self.assertRaises(ValueError):
            find_glb_url("<html></html>")

    def test_asset_config_has_vetted_license_and_category_metadata(self):
        config = json.loads((ROOT / "config/poly_pizza_assets.json").read_text(encoding="utf-8"))
        assets = config["assets"]

        self.assertEqual(len(assets), 20)
        for asset in assets:
            validate_asset_metadata(asset)
            self.assertIn(asset["category"], {"head_face", "neck_chest", "torso_back", "torso_front"})
            self.assertIn(asset["license"], {"CC0 1.0", "Creative Commons Attribution 3.0"})
            self.assertTrue(asset["license_url"].startswith("https://creativecommons.org/"))


if __name__ == "__main__":
    unittest.main()
