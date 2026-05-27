import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from scripts.optimize_glb import (
    build_optimization_command,
    build_sparse_densify_command,
    cached_optimization_result,
    compare_gltf_documents,
    materialize_persistent_optimization_cache,
    optimize_batch,
    optimize_one,
    optimizer_command_prefix,
    patch_animation_report,
    persistent_optimization_cache_paths,
    store_persistent_optimization_cache,
    summarize_gltf_document,
    to_workspace_path,
)


class OptimizeGlbTests(unittest.TestCase):
    def test_build_optimization_command_uses_godot_safe_defaults(self):
        with mock.patch("scripts.optimize_glb.shutil.which", return_value="/usr/local/bin/gltf-transform"):
            command = build_optimization_command(
                Path("in.glb"),
                Path("out.glb"),
                texture_size=1024,
                texture_compress="auto",
            )

        self.assertEqual(command[:2], ["gltf-transform", "optimize"])
        self.assertIn("--compress", command)
        self.assertIn("false", command)
        self.assertIn("--texture-compress", command)
        self.assertIn("auto", command)
        self.assertIn("--texture-size", command)
        self.assertIn("1024", command)
        self.assertIn("--flatten", command)
        self.assertIn("--join", command)
        self.assertIn("--simplify", command)

    def test_optimizer_command_prefix_falls_back_to_npx(self):
        with mock.patch("scripts.optimize_glb.shutil.which", return_value=None):
            self.assertEqual(optimizer_command_prefix(), ["npx", "--yes", "@gltf-transform/cli"])

    def test_summarize_gltf_document_counts_runtime_contract(self):
        summary = summarize_gltf_document(
            {
                "extensionsUsed": ["KHR_materials_unlit"],
                "extensionsRequired": [],
                "meshes": [{"primitives": [{"targets": [{"POSITION": 1}]}]}],
                "skins": [{}],
                "animations": [{}, {}],
                "images": [{}, {}],
                "materials": [{}],
                "accessors": [{"sparse": {"count": 3}}, {}],
            }
        )

        self.assertEqual(summary["mesh_count"], 1)
        self.assertEqual(summary["skin_count"], 1)
        self.assertEqual(summary["animation_count"], 2)
        self.assertEqual(summary["morph_target_primitive_count"], 1)
        self.assertEqual(summary["extensions_used"], ["KHR_materials_unlit"])
        self.assertEqual(summary["sparse_accessor_count"], 1)

    def test_build_sparse_densify_command_uses_project_script(self):
        command = build_sparse_densify_command(Path("in.glb"), Path("out.glb"))

        self.assertEqual(command[0], "node")
        self.assertIn("densify_gltf_sparse_accessors.cjs", command[1])
        self.assertEqual(command[-2:], ["in.glb", "out.glb"])

    def test_densify_helper_can_resolve_npx_gltf_transform_cache(self):
        helper = (ROOT / "scripts/densify_gltf_sparse_accessors.cjs").read_text(encoding="utf-8")

        self.assertIn(".npm/_npx", helper)
        self.assertIn("Module.createRequire", helper)
        self.assertIn("Module.globalPaths.push", helper)

    def test_compare_gltf_documents_flags_added_required_extensions(self):
        comparison = compare_gltf_documents(
            {"extensionsRequired": [], "animations": [{}], "skins": [{}], "meshes": []},
            {
                "extensionsRequired": ["EXT_meshopt_compression"],
                "animations": [],
                "skins": [{}],
                "meshes": [],
            },
        )

        self.assertEqual(comparison["status"], "review")
        self.assertIn("required-extension-added:EXT_meshopt_compression", comparison["warnings"])
        self.assertIn("animation-count-decreased", comparison["warnings"])

    def test_compare_gltf_documents_allows_image_pruning(self):
        comparison = compare_gltf_documents(
            {"extensionsRequired": [], "animations": [{}], "skins": [{}], "meshes": [], "images": [{}, {}]},
            {"extensionsRequired": [], "animations": [{}], "skins": [{}], "meshes": [], "images": [{}]},
        )

        self.assertEqual(comparison["status"], "ok")
        self.assertNotIn("image-count-decreased", comparison["warnings"])

    def test_patch_animation_report_prefers_workspace_optimized_glb(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "results/person_animation.json"
            output_path = root / "outputs/optimized/person.glb"
            report_path.parent.mkdir(parents=True)
            output_path.parent.mkdir(parents=True)
            report_path.write_text(json.dumps({"status": "ok", "output_glb": "/workspace/outputs/person.glb"}))

            patch_animation_report(
                report_path,
                {
                    "status": "ok",
                    "input": "/workspace/outputs/person.glb",
                    "output": str(output_path),
                    "optimized_bytes": 123,
                    "source_bytes": 456,
                    "log_tail": ["\u001b[2mnoisy\u001b[0m"],
                },
                root=root,
            )

            patched = json.loads(report_path.read_text())
            self.assertEqual(patched["optimized_glb"], "/workspace/outputs/optimized/person.glb")
            self.assertEqual(patched["asset_optimization"]["optimized_bytes"], 123)
            self.assertNotIn("log_tail", patched["asset_optimization"])

    def test_to_workspace_path_converts_paths_under_root(self):
        root = Path("/tmp/project")
        self.assertEqual(to_workspace_path(root / "outputs/a.glb", root), "/workspace/outputs/a.glb")

    def test_optimize_one_skips_cleanly_when_npx_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "person.glb"
            output_path = root / "optimized/person.glb"
            input_path.write_bytes(b"not a real glb; parser is mocked")

            with (
                mock.patch("scripts.optimize_glb.load_glb_json", return_value={"meshes": [], "skins": []}),
                mock.patch("scripts.optimize_glb.subprocess.run", side_effect=FileNotFoundError("npx")),
            ):
                result = optimize_one(input_path, output_path)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "optimizer-not-installed:npx")
        self.assertIn("npx", result["command"])

    def test_optimize_one_densifies_sparse_accessors_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "person.glb"
            output_path = root / "optimized/person.glb"
            dense_path = output_path.with_name("person.dense.glb")
            input_path.write_bytes(b"source")

            docs = [
                {"meshes": [{"primitives": [{"targets": [{"POSITION": 1}]}]}], "skins": [{}], "animations": [{}]},
                {"accessors": [{"sparse": {"count": 2}}, {}]},
                {"accessors": []},
                {"meshes": [{"primitives": [{"targets": [{"POSITION": 1}]}]}], "skins": [{}], "animations": [{}], "accessors": []},
            ]

            def fake_run(command, **_kwargs):
                if any("densify_gltf_sparse_accessors.cjs" in str(part) for part in command):
                    dense_path.write_bytes(b"dense")
                    return mock.Mock(returncode=0, stdout='{"sparse_accessors_densified": 2}\\n')
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"optimized")
                return mock.Mock(returncode=0, stdout="optimized\n")

            with (
                mock.patch("scripts.optimize_glb.load_glb_json", side_effect=docs),
                mock.patch("scripts.optimize_glb.subprocess.run", side_effect=fake_run),
            ):
                result = optimize_one(input_path, output_path)

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["densify_sparse_accessors"])
        self.assertEqual(result["sparse_densify"]["status"], "ok")
        self.assertEqual(result["sparse_densify"]["sparse_accessors_before"], 1)
        self.assertEqual(result["sparse_densify"]["sparse_accessors_after"], 0)
        self.assertEqual(result["sparse_densify"]["sparse_accessors_densified"], 1)
        self.assertEqual(result["optimized_bytes"], 5)
        self.assertEqual(result["comparison"]["after"]["sparse_accessor_count"], 0)
        self.assertNotIn("sparse-accessors-present", " ".join(result["warnings"]))

    def test_optimize_one_rough_preview_hardlinks_without_running_optimizer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "person.glb"
            output_path = root / "optimized/person.glb"
            input_path.write_bytes(b"preview glb")

            with mock.patch("scripts.optimize_glb.subprocess.run") as run:
                result = optimize_one(input_path, output_path, profile="rough_preview")

            self.assertEqual(output_path.read_bytes(), b"preview glb")
            self.assertTrue(input_path.samefile(output_path))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["profile"], "rough_preview")
        self.assertEqual(result["optimization_strategy"], "linked-original-for-preview")
        self.assertEqual(result["materialization"], "linked")
        self.assertEqual(result["source_bytes"], result["optimized_bytes"])
        self.assertEqual(result["size_ratio"], 1.0)
        self.assertEqual(result["warnings"], [])
        run.assert_not_called()

    def test_optimize_report_rough_preview_links_without_persistent_hash_lookup(self):
        from scripts.optimize_glb import optimize_report

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "outputs/person.glb"
            report_path = root / "results/person_animation.json"
            input_path.parent.mkdir(parents=True)
            report_path.parent.mkdir(parents=True)
            input_path.write_bytes(b"source glb")
            report_path.write_text(json.dumps({"output_glb": str(input_path)}), encoding="utf-8")
            args = mock.Mock(
                texture_size=768,
                texture_compress="auto",
                geometry_compress="false",
                preserve_sparse_accessors=False,
                profile="rough_preview",
                skip_existing=False,
            )

            with (
                mock.patch("scripts.optimize_glb.persistent_optimization_cache_paths") as cache_paths,
                mock.patch("scripts.optimize_glb.file_sha256") as file_sha,
            ):
                result = optimize_report(report_path, root / "optimized", args)

            output_path = root / "optimized/person.glb"
            same_file = input_path.samefile(output_path)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["optimization_strategy"], "linked-original-for-preview")
        self.assertEqual(result["materialization"], "linked")
        self.assertTrue(same_file)
        cache_paths.assert_not_called()
        file_sha.assert_not_called()

    def test_cached_optimization_result_reuses_matching_up_to_date_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "person.glb"
            output_path = root / "optimized/person.glb"
            input_path.write_bytes(b"source glb")
            output_path.parent.mkdir()
            output_path.write_bytes(b"optimized")
            report = {
                "asset_optimization": {
                    "status": "ok",
                    "profile": "standard",
                    "input": str(input_path),
                    "output": str(output_path),
                    "source_bytes": len(b"source glb"),
                    "optimized_bytes": len(b"optimized"),
                    "saved_bytes": len(b"source glb") - len(b"optimized"),
                    "size_ratio": round(len(b"optimized") / len(b"source glb"), 4),
                    "texture_size": 768,
                    "texture_compress": "auto",
                    "geometry_compress": "false",
                    "densify_sparse_accessors": True,
                    "warnings": [],
                }
            }

            result = cached_optimization_result(
                report,
                input_path,
                output_path,
                texture_size=768,
                texture_compress="auto",
                geometry_compress="false",
                densify_sparse=True,
                profile="standard",
            )

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["optimization_strategy"], "cached-standard-optimization")
        self.assertEqual(result["cache_status"], "hit")
        self.assertEqual(result["source_bytes"], len(b"source glb"))

    def test_optimize_report_skips_existing_when_cache_matches(self):
        from scripts.optimize_glb import optimize_report

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "outputs/person.glb"
            output_path = root / "optimized/person.glb"
            report_path = root / "results/person_animation.json"
            input_path.parent.mkdir(parents=True)
            output_path.parent.mkdir(parents=True)
            report_path.parent.mkdir(parents=True)
            input_path.write_bytes(b"source glb")
            output_path.write_bytes(b"optimized")
            report_path.write_text(
                json.dumps(
                    {
                        "output_glb": str(input_path),
                        "optimized_glb": str(output_path),
                        "asset_optimization": {
                            "status": "ok",
                            "profile": "standard",
                            "input": str(input_path),
                            "output": str(output_path),
                            "source_bytes": len(b"source glb"),
                            "optimized_bytes": len(b"optimized"),
                            "saved_bytes": len(b"source glb") - len(b"optimized"),
                            "size_ratio": round(len(b"optimized") / len(b"source glb"), 4),
                            "texture_size": 768,
                            "texture_compress": "auto",
                            "geometry_compress": "false",
                            "densify_sparse_accessors": True,
                            "warnings": [],
                        },
                    }
                ),
                encoding="utf-8",
            )
            args = mock.Mock(
                texture_size=768,
                texture_compress="auto",
                geometry_compress="false",
                preserve_sparse_accessors=False,
                profile="standard",
                skip_existing=True,
            )

            with mock.patch("scripts.optimize_glb.optimize_one") as optimize:
                result = optimize_report(report_path, root / "optimized", args)

        self.assertEqual(result["cache_status"], "hit")
        self.assertEqual(result["optimization_strategy"], "cached-standard-optimization")
        optimize.assert_not_called()

    def test_persistent_optimization_cache_materializes_matching_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "outputs/person.glb"
            output_path = root / "optimized/person.glb"
            report_path = root / "results/person_animation.json"
            input_path.parent.mkdir(parents=True)
            output_path.parent.mkdir(parents=True)
            report_path.parent.mkdir(parents=True)
            input_path.write_bytes(b"source glb")
            output_path.write_bytes(b"optimized")
            result = {
                "status": "ok",
                "profile": "standard",
                "input": str(input_path),
                "output": str(output_path),
                "source_bytes": len(b"source glb"),
                "optimized_bytes": len(b"optimized"),
                "saved_bytes": len(b"source glb") - len(b"optimized"),
                "size_ratio": round(len(b"optimized") / len(b"source glb"), 4),
                "texture_size": 768,
                "texture_compress": "auto",
                "geometry_compress": "false",
                "densify_sparse_accessors": True,
                "warnings": [],
                "log_tail": ["noisy"],
            }

            stored = store_persistent_optimization_cache(
                input_path,
                output_path,
                result,
                texture_size=768,
                texture_compress="auto",
                geometry_compress="false",
                densify_sparse=True,
                profile="standard",
                root=root,
            )
            paths = persistent_optimization_cache_paths(
                input_path,
                texture_size=768,
                texture_compress="auto",
                geometry_compress="false",
                densify_sparse=True,
                profile="standard",
                root=root,
            )
            target_output = root / "optimized/person-copy.glb"
            materialized = materialize_persistent_optimization_cache(
                input_path,
                target_output,
                paths,
                texture_size=768,
                texture_compress="auto",
                geometry_compress="false",
                densify_sparse=True,
                profile="standard",
                root=root,
            )
            target_output_bytes = target_output.read_bytes()
            cache_output = Path(paths["glb"])
            same_file = cache_output.samefile(target_output)

        self.assertEqual(stored["status"], "stored")
        self.assertEqual(materialized["status"], "ok")
        self.assertEqual(materialized["optimization_strategy"], "persistent-standard-optimization-cache")
        self.assertEqual(materialized["cache_status"], "hit")
        self.assertEqual(materialized["materialization"], "linked")
        self.assertEqual(target_output_bytes, b"optimized")
        self.assertTrue(same_file)

    def test_optimize_batch_copies_render_dedup_outputs_without_reoptimizing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_glb = root / "outputs/person-001.glb"
            duplicate_glb = root / "outputs/person-002.glb"
            source_report = root / "results/person-001_animation.json"
            duplicate_report = root / "results/person-002_animation.json"
            batch_path = root / "results/batch.json"
            source_glb.parent.mkdir(parents=True)
            source_report.parent.mkdir(parents=True)
            source_glb.write_bytes(b"source glb")
            duplicate_glb.write_bytes(b"source glb")
            source_report.write_text(json.dumps({"output_glb": str(source_glb)}), encoding="utf-8")
            duplicate_report.write_text(json.dumps({"output_glb": str(duplicate_glb)}), encoding="utf-8")
            batch_path.write_text(
                json.dumps(
                    {
                        "jobs": [
                            {
                                "id": "person-001",
                                "status": "ok",
                                "environment": {"ANIMATION_REPORT_JSON": str(source_report)},
                            },
                            {
                                "id": "person-002",
                                "status": "ok",
                                "environment": {"ANIMATION_REPORT_JSON": str(duplicate_report)},
                                "render_dedup": {"source_job_id": "person-001"},
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            args = mock.Mock(
                texture_size=768,
                texture_compress="auto",
                geometry_compress="false",
                preserve_sparse_accessors=False,
                profile="standard",
                skip_existing=False,
            )

            def fake_optimize_report(report_path, output_dir, _args):
                output = output_dir / "person-001.glb"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"optimized")
                patch_animation_report(
                    report_path,
                    {
                        "status": "ok",
                        "profile": "standard",
                        "input": str(source_glb),
                        "output": str(output),
                        "source_bytes": len(b"source glb"),
                        "optimized_bytes": len(b"optimized"),
                        "saved_bytes": len(b"source glb") - len(b"optimized"),
                        "size_ratio": round(len(b"optimized") / len(b"source glb"), 4),
                    },
                    root=root,
                )
                return {
                    "status": "ok",
                    "profile": "standard",
                    "input": str(source_glb),
                    "output": str(output),
                    "source_bytes": len(b"source glb"),
                    "optimized_bytes": len(b"optimized"),
                    "saved_bytes": len(b"source glb") - len(b"optimized"),
                    "size_ratio": round(len(b"optimized") / len(b"source glb"), 4),
                }

            with mock.patch("scripts.optimize_glb.optimize_report", side_effect=fake_optimize_report) as optimize:
                summary = optimize_batch(batch_path, root / "optimized", args)

            duplicate_optimized = root / "optimized/person-002.glb"
            duplicate_optimized_exists = duplicate_optimized.exists()
            duplicate_optimized_is_link = (root / "optimized/person-001.glb").samefile(duplicate_optimized)

        self.assertEqual(optimize.call_count, 1)
        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["deduped_count"], 1)
        self.assertEqual(summary["results"][1]["optimization_strategy"], "linked-render-dedup-optimization")
        self.assertTrue(duplicate_optimized_exists)
        self.assertTrue(duplicate_optimized_is_link)


if __name__ == "__main__":
    unittest.main()
