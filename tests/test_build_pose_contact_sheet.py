import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_pose_contact_sheet import build_contact_sheet, job_filter_tags, job_render_paths, workspace_path


class BuildPoseContactSheetTests(unittest.TestCase):
    def test_workspace_path_maps_workspace_prefix_to_root(self):
        self.assertEqual(
            workspace_path("/workspace/outputs/batch/demo.png", Path("/tmp/project")),
            Path("/tmp/project/outputs/batch/demo.png"),
        )

    def test_job_render_paths_returns_sorted_pngs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            render_dir = root / "outputs/batch/demo_pose_renders"
            render_dir.mkdir(parents=True)
            (render_dir / "pose_0072.png").write_bytes(b"png")
            (render_dir / "pose_0024.png").write_bytes(b"png")
            (render_dir / "ignore.txt").write_text("no", encoding="utf-8")

            paths = job_render_paths(
                {"environment": {"RENDER_DIR": "/workspace/outputs/batch/demo_pose_renders"}},
                root,
            )

        self.assertEqual([path.name for path in paths], ["pose_0024.png", "pose_0072.png"])

    def test_build_contact_sheet_embeds_job_metadata_and_relative_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            render_dir = root / "outputs/batch/demo_pose_renders"
            render_dir.mkdir(parents=True)
            (render_dir / "pose_0024.png").write_bytes(b"png")
            output = root / "outputs/batch/contact.html"
            batch = {
                "manifest": "demo-manifest",
                "jobs": [
                    {
                        "id": "demo",
                        "status": "ok",
                        "metadata": {"display_name": "Demo Person", "tags": ["generated", "qa"]},
                        "environment": {"RENDER_DIR": "/workspace/outputs/batch/demo_pose_renders"},
                    },
                    {"id": "bad", "status": "error"},
                ],
            }

            html = build_contact_sheet(batch, output, root)

        self.assertIn("demo-manifest", html)
        self.assertIn("Demo Person", html)
        self.assertIn("demo_pose_renders/pose_0024.png", html)
        self.assertNotIn(">bad<", html)

    def test_job_filter_tags_include_lipsync_report_and_qa(self):
        job = {
            "id": "demo",
            "status": "ok",
            "qa": {"qa_grade": "A", "review_priority": "ship"},
            "metadata": {"tags": ["generated", "demo"]},
            "environment": {"ANIMATION_PRESET": "talk_idle"},
        }
        report = {
            "animation": "talk_idle",
            "lipsync_animation": {"enabled": True, "cue_count": 7},
            "expression_animation": {"preset": "talking_soft"},
            "talking_video": "/workspace/outputs/musetalk/v15/demo.mp4",
            "talking_video_backend": "musetalk",
        }

        tags = job_filter_tags(job, report)

        self.assertIn("generated", tags)
        self.assertIn("status:ok", tags)
        self.assertIn("qa:A", tags)
        self.assertIn("priority:ship", tags)
        self.assertIn("animation:talk-idle", tags)
        self.assertIn("lipsync:enabled", tags)
        self.assertIn("face-preset:talking-soft", tags)
        self.assertIn("talking-video:available", tags)
        self.assertIn("talking-video-backend:musetalk", tags)
        self.assertIn("talking-video-quality:preview", tags)

    def test_contact_sheet_has_search_and_filter_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            render_dir = root / "outputs/batch/demo_pose_renders"
            report_path = root / "results/demo_animation.json"
            render_dir.mkdir(parents=True)
            report_path.parent.mkdir(parents=True)
            (render_dir / "pose_0024.png").write_bytes(b"png")
            report_path.write_text(
                json.dumps(
                    {
                        "animation": "talk_idle",
                        "lipsync_animation": {
                            "enabled": True,
                            "cue_count": 5,
                            "timeline": "/workspace/outputs/lipsync/demo.face.json",
                        },
                        "expression_animation": {"preset": "talking_soft"},
                        "talking_video": "/workspace/outputs/musetalk/v15/demo.mp4",
                        "talking_video_backend": "musetalk",
                    }
                ),
                encoding="utf-8",
            )
            timeline_path = root / "outputs/lipsync/demo.face.json"
            timeline_path.parent.mkdir(parents=True)
            timeline_path.write_text(
                json.dumps(
                    {
                        "source": {
                            "mode": "phoneme-events",
                            "event_count": 2,
                            "phoneme_count": 2,
                            "unique_phonemes": ["EH1", "OW1"],
                        },
                        "duration": 0.3,
                        "cues": [
                            {"time": 0.0, "duration": 0.1, "viseme": "ee", "value": 1.0, "source_phoneme": "EH1"},
                            {"time": 0.1, "duration": 0.2, "viseme": "oh", "value": 1.0, "source_phoneme": "OW1"},
                        ],
                        "expressions": [{"time": 0, "duration": 0.3, "name": "happy", "value": 0.1}],
                    }
                ),
                encoding="utf-8",
            )
            output = root / "outputs/batch/contact.html"
            batch = {
                "manifest": "demo-manifest",
                "jobs": [
                    {
                        "id": "demo",
                        "status": "ok",
                        "qa": {"qa_grade": "A", "review_priority": "ship"},
                        "metadata": {"display_name": "Demo Person", "tags": ["generated"]},
                        "environment": {
                            "RENDER_DIR": "/workspace/outputs/batch/demo_pose_renders",
                            "ANIMATION_REPORT_JSON": "/workspace/results/demo_animation.json",
                        },
                    }
                ],
            }

            html = build_contact_sheet(batch, output, root)

        self.assertIn('id="contact-search"', html)
        self.assertIn('data-filter="lipsync:enabled"', html)
        self.assertIn('data-tags="animation:talk-idle', html)
        self.assertIn("Lip sync", html)
        self.assertIn("5 cues", html)
        self.assertIn("phoneme-events", html)
        self.assertIn("2 phonemes", html)
        self.assertIn("EH1, OW1", html)
        self.assertIn('data-filter="lipsync-source:phoneme-events"', html)
        self.assertIn('data-filter="lipsync-phonemes:2"', html)
        self.assertIn("Video", html)
        self.assertIn("musetalk / preview", html)
        self.assertIn('data-filter="talking-video-quality:preview"', html)


if __name__ == "__main__":
    unittest.main()
