import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MuseTalkContainerTests(unittest.TestCase):
    def test_compose_declares_optional_musetalk_profile(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("musetalk:", compose)
        self.assertIn("Dockerfile.musetalk", compose)
        self.assertIn('profiles: ["musetalk"]', compose)
        self.assertIn("device_ids:", compose)
        self.assertIn("${MUSE_TALK_GPU_ID:-0}", compose)
        self.assertIn("NVIDIA_VISIBLE_DEVICES: ${MUSE_TALK_GPU_ID:-0}", compose)
        self.assertIn("LOCAL_UID: ${LOCAL_UID:-1000}", compose)
        self.assertIn("LOCAL_GID: ${LOCAL_GID:-1000}", compose)
        self.assertIn("MUSE_TALK_MODELS_DIR", compose)
        self.assertIn("TORCH_HOME", compose)
        self.assertIn("MUSE_TALK_TORCH_CACHE", compose)
        self.assertIn("scripts/run_musetalk_job.sh", compose)

    def test_musetalk_dockerfile_documents_heavy_runtime(self):
        dockerfile = ROOT / "Dockerfile.musetalk"

        self.assertTrue(dockerfile.exists())
        text = dockerfile.read_text(encoding="utf-8")
        self.assertIn("nvidia/cuda", text)
        self.assertIn("python3.10", text)
        self.assertIn("git clone", text)
        self.assertIn("requirements.txt", text)
        self.assertIn("chumpy==0.70", text)
        self.assertIn("--no-build-isolation", text)

    def test_musetalk_runner_writes_saved_coord_for_manual_bbox(self):
        runner = ROOT / "scripts/run_musetalk_job.sh"

        text = runner.read_text(encoding="utf-8")

        self.assertIn("manual_bbox", text)
        self.assertIn("pickle.dump", text)
        self.assertIn("--use_saved_coord", text)
        self.assertIn("--saved_coord", text)
        self.assertIn("--parsing_mode", text)

    def test_musetalk_runner_normalizes_workspace_output_ownership(self):
        runner = ROOT / "scripts/run_musetalk_job.sh"

        text = runner.read_text(encoding="utf-8")

        self.assertIn('LOCAL_UID="${LOCAL_UID:-1000}"', text)
        self.assertIn('LOCAL_GID="${LOCAL_GID:-1000}"', text)
        self.assertIn("chown -R", text)
        self.assertIn("/workspace/outputs/musetalk", text)
        self.assertIn('exit "${status}"', text)


if __name__ == "__main__":
    unittest.main()
