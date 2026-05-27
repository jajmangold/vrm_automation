import unittest
from unittest import mock

from scripts.refresh_combined_gallery import refresh_combined_gallery


class RefreshCombinedGalleryTests(unittest.TestCase):
    def test_summary_only_refresh_skips_static_gallery_and_contact_sheet(self):
        calls = []

        def fake_run(command):
            calls.append(command)
            return {"command": command, "elapsed_seconds": 0.1, "returncode": 0, "status": "ok"}

        with mock.patch("scripts.refresh_combined_gallery.run_checked", side_effect=fake_run):
            report = refresh_combined_gallery(summary_only=True)

        self.assertEqual(report["status"], "ok")
        self.assertIsNone(report["gallery"])
        self.assertIsNone(report["contact_sheet"])
        self.assertEqual([stage["name"] for stage in report["stages"]], ["combined_summary"])
        self.assertIn("--summary-only", calls[0])
        self.assertIn("--character-index-json", calls[0])

    def test_full_refresh_runs_static_gallery_and_contact_sheet(self):
        calls = []

        def fake_run(command):
            calls.append(command)
            return {"command": command, "elapsed_seconds": 0.1, "returncode": 0, "status": "ok"}

        with mock.patch("scripts.refresh_combined_gallery.run_checked", side_effect=fake_run):
            report = refresh_combined_gallery(summary_only=False)

        self.assertEqual(report["status"], "ok")
        self.assertEqual([stage["name"] for stage in report["stages"]], ["combined_gallery", "contact_sheet"])
        self.assertEqual(calls[0][0:2], ["python3", "scripts/build_combined_gallery.py"])
        self.assertNotIn("--summary-only", calls[0])
        self.assertEqual(calls[1][0:2], ["python3", "scripts/build_pose_contact_sheet.py"])


if __name__ == "__main__":
    unittest.main()
