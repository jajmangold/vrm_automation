import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class FakeGodotClient:
    def __init__(self):
        self.calls = []
        self.active_path = "/workspace/outputs/lipsync/talker.face.json"
        self.active_cue_count = 5

    def get(self, path):
        self.calls.append(("GET", path, None))
        if path == "/assets":
            return {
                "assets": [
                    {
                        "id": "no-timeline",
                        "glb": "/workspace/outputs/batch/no-timeline.glb",
                        "lipsync_timeline": "",
                        "lipsync_summary": {"cue_count": 0},
                    },
                    {
                        "id": "talker",
                        "glb": "/workspace/outputs/batch/talker.glb",
                        "lipsync_timeline": "/workspace/outputs/lipsync/talker.face.json",
                        "lipsync_summary": {
                            "cue_count": 5,
                            "duration": 1.25,
                            "visemes": ["rest", "aa", "ee", "ih", "oh", "ou"],
                        },
                    },
                ]
            }
        if path == "/face-profile":
            return {
                "status": "ok",
                "visemes": {"aa": {}, "ee": {}, "ih": {}, "oh": {}, "ou": {}},
                "quality": {"viseme_count": 5},
            }
        if path == "/lipsync-status":
            return {
                "status": "playing",
                "source": self.active_path,
                "cue_count": self.active_cue_count,
                "cue_index": 1,
                "duration": 1.25,
                "active_viseme": "aa",
                "active_viseme_value": 0.8,
                "active_source_phoneme": "AA1",
                "active_source_index": 2,
            }
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path, payload):
        self.calls.append(("POST", path, payload))
        if path == "/load":
            return {"status": "ok", "id": payload["id"]}
        if path == "/lipsync":
            self.active_path = payload["path"]
            return {
                "status": "ok",
                "path": payload["path"],
                "cue_count": self.active_cue_count,
                "duration": 1.25,
                "playback": {"status": "playing", "cue_count": 5},
            }
        raise AssertionError(f"unexpected POST {path}")


class MissingVisemeClient(FakeGodotClient):
    def get(self, path):
        if path == "/face-profile":
            self.calls.append(("GET", path, None))
            return {
                "status": "ok",
                "visemes": {"aa": {}, "ee": {}, "oh": {}, "ou": {}},
                "quality": {"viseme_count": 4},
            }
        return super().get(path)


class MissingTimelineVisemeClient(FakeGodotClient):
    def get(self, path):
        if path == "/assets":
            payload = super().get(path)
            payload["assets"][1]["lipsync_summary"]["visemes"] = ["aa", "ee", "ou", "zz"]
            payload["assets"][1]["lipsync_summary"]["source_unique_phonemes"] = ["AA1", "ZZ"]
            payload["assets"][1]["lipsync_summary"]["source_phoneme_count"] = 2
            return payload
        return super().get(path)


class FastIdleClient(FakeGodotClient):
    def get(self, path):
        if path == "/lipsync-status":
            self.calls.append(("GET", path, None))
            return {
                "status": "idle",
                "source": "",
                "cue_count": 0,
                "cue_index": 0,
                "duration": 0.0,
            }
        return super().get(path)


class ReviewQualityClient(FakeGodotClient):
    def get(self, path):
        if path == "/assets":
            payload = super().get(path)
            payload["assets"][1]["lipsync_summary"]["quality"] = {
                "status": "review",
                "grade": "D",
                "issues": ["overlapping-cues"],
                "warnings": [],
            }
            return payload
        return super().get(path)


class PrefixFilterClient(FakeGodotClient):
    def get(self, path):
        if path == "/assets":
            self.calls.append(("GET", path, None))
            return {
                "assets": [
                    {
                        "id": "old-batch-001",
                        "glb": "/workspace/outputs/batch/old-batch-001.glb",
                        "lipsync_timeline": "/workspace/outputs/lipsync/old.face.json",
                        "lipsync_summary": {"cue_count": 5},
                    },
                    {
                        "id": "ship-bowtie-live-005-001",
                        "glb": "/workspace/outputs/batch/ship-bowtie-live-005-001.glb",
                        "lipsync_timeline": "/workspace/outputs/lipsync/ship-001.face.json",
                        "lipsync_summary": {"cue_count": 5},
                    },
                    {
                        "id": "ship-bowtie-live-005-002",
                        "glb": "/workspace/outputs/batch/ship-bowtie-live-005-002.glb",
                        "lipsync_timeline": "/workspace/outputs/lipsync/ship-002.face.json",
                        "lipsync_summary": {"cue_count": 5},
                    },
                ]
            }
        return super().get(path)


class DuplicateBatchClient(FakeGodotClient):
    def get(self, path):
        if path == "/assets":
            raise AssertionError("batch-result validation should not query /assets")
        return super().get(path)


class BatchValidationClient(DuplicateBatchClient):
    def post(self, path, payload):
        if path == "/validate-lipsync-batch":
            self.calls.append(("POST", path, payload))
            return {
                "status": "ok",
                "checked": [
                    {
                        "id": item["id"],
                        "status": "ok",
                        "issues": [],
                        "timeline": item["timeline"],
                        "cue_count": item["expected_cues"],
                        "missing_visemes": [],
                        "missing_timeline_visemes": [],
                        "load": {"status": "ok", "id": item["id"]},
                        "lipsync": {
                            "status": "ok",
                            "path": item["timeline"],
                            "cue_count": item["expected_cues"],
                            "playback": {"status": "playing", "cue_count": item["expected_cues"]},
                        },
                        "playback_status": {
                            "status": "playing",
                            "source": item["timeline"],
                            "cue_count": item["expected_cues"],
                            "active_viseme": "aa",
                        },
                    }
                    for item in payload["assets"]
                ],
            }
        return super().post(path, payload)


class NamedBatchValidationClient(BatchValidationClient):
    def __init__(self, name):
        super().__init__()
        self.name = name


class GodotLipSyncValidationTests(unittest.TestCase):
    def test_lip_ready_assets_filter_assets_with_timeline_and_cues(self):
        from scripts.validate_godot_lipsync import lip_ready_assets

        assets = [
            {"id": "missing-glb", "lipsync_timeline": "/workspace/a.face.json", "lipsync_summary": {"cue_count": 3}},
            {"id": "missing-timeline", "glb": "/workspace/a.glb", "lipsync_summary": {"cue_count": 3}},
            {"id": "empty", "glb": "/workspace/b.glb", "lipsync_timeline": "/workspace/b.face.json", "lipsync_summary": {"cue_count": 0}},
            {"id": "ready", "glb": "/workspace/c.glb", "lipsync_timeline": "/workspace/c.face.json", "lipsync_summary": {"cue_count": 7}},
        ]

        self.assertEqual([asset["id"] for asset in lip_ready_assets(assets)], ["ready"])

    def test_run_validation_loads_asset_sends_timeline_and_checks_playback_status(self):
        from scripts.validate_godot_lipsync import run_validation

        client = FakeGodotClient()
        report = run_validation(client, max_assets=1, wait_seconds=0.0)

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["checked_count"], 1)
        self.assertEqual(report["review_count"], 0)
        self.assertEqual(report["grade_counts"], {"n/a": 1})
        self.assertEqual(report["source_counts"], {"unknown": 1})
        self.assertEqual(report["checked"][0]["id"], "talker")
        self.assertEqual(report["checked"][0]["status"], "ok")
        self.assertEqual(report["checked"][0]["cue_count"], 5)
        self.assertEqual(report["checked"][0]["lipsync_quality"]["status"], "unknown")
        self.assertEqual(report["checked"][0]["playback_status"]["active_viseme"], "aa")
        self.assertEqual(report["checked"][0]["playback_status"]["active_source_phoneme"], "AA1")
        self.assertIn(("POST", "/load", {"id": "talker"}), client.calls)
        self.assertIn(("POST", "/lipsync", {"path": "/workspace/outputs/lipsync/talker.face.json"}), client.calls)
        self.assertIn(("GET", "/lipsync-status", None), client.calls)

    def test_run_validation_marks_missing_face_viseme_for_review(self):
        from scripts.validate_godot_lipsync import run_validation

        report = run_validation(MissingVisemeClient(), max_assets=1, wait_seconds=0.0)

        self.assertEqual(report["status"], "review")
        self.assertEqual(report["checked"][0]["status"], "review")
        self.assertIn("ih", report["checked"][0]["missing_visemes"])
        self.assertIn("missing-visemes", report["checked"][0]["issues"])

    def test_run_validation_marks_timeline_visemes_missing_from_face_profile(self):
        from scripts.validate_godot_lipsync import run_validation

        report = run_validation(MissingTimelineVisemeClient(), max_assets=1, wait_seconds=0.0)

        self.assertEqual(report["status"], "review")
        checked = report["checked"][0]
        self.assertEqual(checked["status"], "review")
        self.assertEqual(checked["timeline_visemes"], ["aa", "ee", "ou", "zz"])
        self.assertEqual(checked["timeline_source_phonemes"], ["AA1", "ZZ"])
        self.assertEqual(checked["source_phoneme_count"], 2)
        self.assertEqual(checked["missing_timeline_visemes"], ["zz"])
        self.assertIn("missing-timeline-visemes", checked["issues"])

    def test_run_validation_accepts_start_response_when_fast_playback_is_already_idle(self):
        from scripts.validate_godot_lipsync import run_validation

        report = run_validation(FastIdleClient(), max_assets=1, wait_seconds=0.0)

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["checked"][0]["status"], "ok")
        self.assertEqual(report["checked"][0]["playback_status"]["status"], "idle")
        self.assertEqual(report["checked"][0]["lipsync"]["playback"]["cue_count"], 5)

    def test_run_validation_propagates_lipsync_quality_review(self):
        from scripts.validate_godot_lipsync import run_validation

        report = run_validation(ReviewQualityClient(), max_assets=1, wait_seconds=0.0)

        self.assertEqual(report["status"], "review")
        self.assertEqual(report["review_count"], 1)
        self.assertEqual(report["quality_review_count"], 1)
        self.assertEqual(report["grade_counts"], {"D": 1})
        self.assertEqual(report["issue_counts"], {"lipsync-quality-review": 1, "overlapping-cues": 1})
        self.assertEqual(report["checked"][0]["lipsync_quality"]["status"], "review")
        self.assertIn("lipsync-quality-review", report["checked"][0]["issues"])

    def test_run_validation_filters_assets_by_id_prefix(self):
        from scripts.validate_godot_lipsync import run_validation

        client = PrefixFilterClient()
        report = run_validation(
            client,
            max_assets=10,
            wait_seconds=0.0,
            id_prefix="ship-bowtie-live-005-",
        )

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["candidate_count"], 2)
        self.assertEqual(report["checked_count"], 2)
        self.assertEqual(
            [item["id"] for item in report["checked"]],
            ["ship-bowtie-live-005-001", "ship-bowtie-live-005-002"],
        )
        self.assertNotIn(("POST", "/load", {"id": "old-batch-001"}), client.calls)

    def test_run_validation_can_read_candidates_from_batch_result(self):
        from scripts.validate_godot_lipsync import run_validation

        with tempfile.TemporaryDirectory() as tmp_dir:
            batch_result = Path(tmp_dir) / "batch.json"
            batch_result.write_text(
                """
                {
                  "jobs": [
                    {
                      "id": "chunk-002-003",
                      "environment": {
                        "OUTPUT_GLB": "/workspace/outputs/batch/chunk-002-003.glb",
                        "LIPSYNC_TIMELINE_JSON": "/workspace/outputs/lipsync/chunk-002-003.face.json"
                      },
                      "lipsync_summary": {"cue_count": 5, "visemes": ["aa", "ee"]}
                    }
                  ]
                }
                """,
                encoding="utf-8",
            )
            client = FakeGodotClient()
            report = run_validation(
                client,
                max_assets=10,
                wait_seconds=0.0,
                id_prefix="chunk-002-",
                batch_result=batch_result,
            )

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["candidate_count"], 1)
        self.assertEqual(report["checked"][0]["id"], "chunk-002-003")
        self.assertEqual(report["checked"][0]["timeline"], "/workspace/outputs/lipsync/chunk-002-003.face.json")
        self.assertNotIn(("GET", "/assets", None), client.calls)
        self.assertIn(("POST", "/load", {"id": "chunk-002-003"}), client.calls)

    def test_run_validation_dedupes_identical_render_cache_candidates(self):
        from scripts.validate_godot_lipsync import run_validation

        with tempfile.TemporaryDirectory() as tmp_dir:
            batch_result = Path(tmp_dir) / "batch.json"
            batch_result.write_text(
                """
                {
                  "jobs": [
                    {
                      "id": "chunk-001-001",
                      "optimized_glb": "/workspace/outputs/batch_optimized/chunk-001-001.glb",
                      "lipsync_timeline_json": "/workspace/outputs/lipsync/shared.face.json",
                      "lipsync_summary": {"cue_count": 5, "visemes": ["aa", "ee", "ih", "oh", "ou"]},
                      "render_cache": {"key": "shared-render-key", "status": "hit"}
                    },
                    {
                      "id": "chunk-001-007",
                      "optimized_glb": "/workspace/outputs/batch_optimized/chunk-001-007.glb",
                      "lipsync_timeline_json": "/workspace/outputs/lipsync/shared.face.json",
                      "lipsync_summary": {"cue_count": 5, "visemes": ["aa", "ee", "ih", "oh", "ou"]},
                      "render_cache": {"key": "shared-render-key", "status": "hit"},
                      "render_dedup": {"source_job_id": "chunk-001-001", "status": "materialized-copy"}
                    }
                  ]
                }
                """,
                encoding="utf-8",
            )
            client = DuplicateBatchClient()
            report = run_validation(
                client,
                max_assets=10,
                wait_seconds=0.0,
                id_prefix="chunk-001-",
                batch_result=batch_result,
            )

        load_calls = [call for call in client.calls if call[0] == "POST" and call[1] == "/load"]
        lipsync_calls = [call for call in client.calls if call[0] == "POST" and call[1] == "/lipsync"]
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["candidate_count"], 2)
        self.assertEqual(report["checked_count"], 2)
        self.assertEqual(report["validation_dedupe"]["source_checked_count"], 1)
        self.assertEqual(report["validation_dedupe"]["materialized_duplicate_count"], 1)
        self.assertEqual([item["id"] for item in report["checked"]], ["chunk-001-001", "chunk-001-007"])
        self.assertEqual(report["checked"][1]["validation_dedup"]["source_asset_id"], "chunk-001-001")
        self.assertEqual(load_calls, [("POST", "/load", {"id": "chunk-001-001"})])
        self.assertEqual(lipsync_calls, [("POST", "/lipsync", {"path": "/workspace/outputs/lipsync/shared.face.json"})])

    def test_run_validation_can_batch_validate_representatives(self):
        from scripts.validate_godot_lipsync import run_validation

        with tempfile.TemporaryDirectory() as tmp_dir:
            batch_result = Path(tmp_dir) / "batch.json"
            batch_result.write_text(
                """
                {
                  "jobs": [
                    {
                      "id": "chunk-001-001",
                      "optimized_glb": "/workspace/outputs/batch_optimized/chunk-001-001.glb",
                      "lipsync_timeline_json": "/workspace/outputs/lipsync/shared.face.json",
                      "lipsync_summary": {"cue_count": 5, "visemes": ["aa", "ee", "ih", "oh", "ou"]},
                      "render_cache": {"key": "shared-render-key", "status": "hit"}
                    },
                    {
                      "id": "chunk-001-007",
                      "optimized_glb": "/workspace/outputs/batch_optimized/chunk-001-007.glb",
                      "lipsync_timeline_json": "/workspace/outputs/lipsync/shared.face.json",
                      "lipsync_summary": {"cue_count": 5, "visemes": ["aa", "ee", "ih", "oh", "ou"]},
                      "render_cache": {"key": "shared-render-key", "status": "hit"},
                      "render_dedup": {"source_job_id": "chunk-001-001", "status": "materialized-copy"}
                    }
                  ]
                }
                """,
                encoding="utf-8",
            )
            client = BatchValidationClient()
            report = run_validation(
                client,
                max_assets=10,
                wait_seconds=0.0,
                id_prefix="chunk-001-",
                batch_result=batch_result,
                use_batch_endpoint=True,
            )

        batch_calls = [call for call in client.calls if call[0] == "POST" and call[1] == "/validate-lipsync-batch"]
        load_calls = [call for call in client.calls if call[0] == "POST" and call[1] == "/load"]
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["checked_count"], 2)
        self.assertEqual(report["validation_dedupe"]["source_checked_count"], 1)
        self.assertEqual(report["validation_transport"]["mode"], "batch-endpoint")
        self.assertEqual(report["validation_transport"]["batch_request_count"], 1)
        self.assertEqual(len(batch_calls), 1)
        self.assertEqual(batch_calls[0][2]["assets"][0]["id"], "chunk-001-001")
        self.assertEqual(batch_calls[0][2]["assets"][0]["glb"], "/workspace/outputs/batch_optimized/chunk-001-001.glb")
        self.assertEqual(batch_calls[0][2]["assets"][0]["expected_cues"], 5)
        self.assertEqual(load_calls, [])

    def test_run_validation_can_reuse_persistent_validation_cache(self):
        from scripts.validate_godot_lipsync import run_validation

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            batch_result = root / "batch.json"
            batch_result.write_text(
                """
                {
                  "jobs": [
                    {
                      "id": "chunk-001-001",
                      "optimized_glb": "/workspace/outputs/batch_optimized/chunk-001-001.glb",
                      "lipsync_timeline_json": "/workspace/outputs/lipsync/shared.face.json",
                      "lipsync_summary": {"cue_count": 5, "visemes": ["aa", "ee", "ih", "oh", "ou"]},
                      "render_cache": {"key": "shared-render-key", "status": "hit"}
                    }
                  ]
                }
                """,
                encoding="utf-8",
            )
            first_client = BatchValidationClient()
            first = run_validation(
                first_client,
                max_assets=10,
                wait_seconds=0.0,
                id_prefix="chunk-001-",
                batch_result=batch_result,
                use_batch_endpoint=True,
                validation_cache_dir=root / "validation-cache",
            )
            second_client = BatchValidationClient()
            second = run_validation(
                second_client,
                max_assets=10,
                wait_seconds=0.0,
                id_prefix="chunk-001-",
                batch_result=batch_result,
                use_batch_endpoint=True,
                validation_cache_dir=root / "validation-cache",
            )

        first_batch_calls = [call for call in first_client.calls if call[0] == "POST" and call[1] == "/validate-lipsync-batch"]
        second_batch_calls = [call for call in second_client.calls if call[0] == "POST" and call[1] == "/validate-lipsync-batch"]
        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "ok")
        self.assertEqual(len(first_batch_calls), 1)
        self.assertEqual(second_batch_calls, [])
        self.assertEqual(first["validation_cache"]["miss_count"], 1)
        self.assertEqual(first["validation_cache"]["stored_count"], 1)
        self.assertEqual(second["validation_cache"]["hit_count"], 1)
        self.assertEqual(second["validation_cache"]["source_checked_count"], 0)
        self.assertEqual(second["validation_transport"]["mode"], "persistent-cache")
        self.assertEqual(second["checked"][0]["validation_cache"]["status"], "hit")

    def test_run_validation_can_shard_batch_validation_across_clients(self):
        from scripts.validate_godot_lipsync import run_validation

        with tempfile.TemporaryDirectory() as tmp_dir:
            batch_result = Path(tmp_dir) / "batch.json"
            jobs = []
            for index in range(1, 5):
                jobs.append(
                    {
                        "id": f"chunk-001-{index:03d}",
                        "optimized_glb": f"/workspace/outputs/batch_optimized/chunk-001-{index:03d}.glb",
                        "lipsync_timeline_json": f"/workspace/outputs/lipsync/chunk-001-{index:03d}.face.json",
                        "lipsync_summary": {"cue_count": 5, "visemes": ["aa", "ee", "ih", "oh", "ou"]},
                        "render_cache": {"key": f"render-key-{index}", "status": "miss"},
                    }
                )
            batch_result.write_text(
                '{"jobs": ' + __import__("json").dumps(jobs) + "}",
                encoding="utf-8",
            )
            clients = [NamedBatchValidationClient("a"), NamedBatchValidationClient("b")]
            report = run_validation(
                clients,
                max_assets=10,
                wait_seconds=0.0,
                id_prefix="chunk-001-",
                batch_result=batch_result,
                use_batch_endpoint=True,
            )

        calls_a = [call for call in clients[0].calls if call[0] == "POST" and call[1] == "/validate-lipsync-batch"]
        calls_b = [call for call in clients[1].calls if call[0] == "POST" and call[1] == "/validate-lipsync-batch"]
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["checked_count"], 4)
        self.assertEqual(report["validation_transport"]["mode"], "batch-endpoint-pool")
        self.assertEqual(report["validation_transport"]["control_client_count"], 2)
        self.assertEqual(report["validation_transport"]["batch_request_count"], 2)
        self.assertEqual([item["id"] for item in calls_a[0][2]["assets"]], ["chunk-001-001", "chunk-001-003"])
        self.assertEqual([item["id"] for item in calls_b[0][2]["assets"]], ["chunk-001-002", "chunk-001-004"])
        self.assertEqual([item["id"] for item in report["checked"]], [
            "chunk-001-001",
            "chunk-001-002",
            "chunk-001-003",
            "chunk-001-004",
        ])

    def test_run_validation_reports_empty_filtered_prefix(self):
        from scripts.validate_godot_lipsync import run_validation

        report = run_validation(
            PrefixFilterClient(),
            max_assets=10,
            wait_seconds=0.0,
            id_prefix="missing-batch-",
        )

        self.assertEqual(report["status"], "review")
        self.assertEqual(report["candidate_count"], 0)
        self.assertEqual(report["checked_count"], 0)
        self.assertIn("no-lip-ready-assets", report["issues"])


if __name__ == "__main__":
    unittest.main()
