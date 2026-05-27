from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.vrm_metadata import load_glb_json


def workspace_path(path: str | Path, root: Path = ROOT) -> Path:
    text = str(path)
    if text.startswith("/workspace/"):
        return root / text.removeprefix("/workspace/")
    return Path(text)


def to_workspace_path(path: str | Path, root: Path = ROOT) -> str:
    resolved = Path(path).resolve()
    try:
        return "/workspace/" + resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def persistent_optimization_cache_key(
    input_path: Path,
    *,
    texture_size: int,
    texture_compress: str,
    geometry_compress: str,
    densify_sparse: bool,
    profile: str,
) -> str:
    payload = {
        "source_sha256": file_sha256(input_path),
        "texture_size": texture_size,
        "texture_compress": texture_compress,
        "geometry_compress": geometry_compress,
        "densify_sparse_accessors": densify_sparse,
        "profile": profile,
        "schema": "vrm-person-factory.optimized-glb-cache.v1",
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def persistent_optimization_cache_paths(
    input_path: Path,
    *,
    texture_size: int,
    texture_compress: str,
    geometry_compress: str,
    densify_sparse: bool,
    profile: str,
    root: Path = ROOT,
) -> dict[str, Path | str]:
    key = persistent_optimization_cache_key(
        input_path,
        texture_size=texture_size,
        texture_compress=texture_compress,
        geometry_compress=geometry_compress,
        densify_sparse=densify_sparse,
        profile=profile,
    )
    return {
        "key": key,
        "glb": root / "outputs/optimization_cache" / f"{key}.glb",
        "metadata": root / "results/optimization_cache" / f"{key}.json",
    }


def optimizer_command_prefix() -> list[str]:
    if shutil.which("gltf-transform"):
        return ["gltf-transform"]
    return ["npx", "--yes", "@gltf-transform/cli"]


def build_optimization_command(
    input_path: Path,
    output_path: Path,
    *,
    texture_size: int = 1024,
    texture_compress: str = "auto",
    geometry_compress: str = "false",
) -> list[str]:
    return [
        *optimizer_command_prefix(),
        "optimize",
        str(input_path),
        str(output_path),
        "--compress",
        geometry_compress,
        "--texture-compress",
        texture_compress,
        "--texture-size",
        str(texture_size),
        "--flatten",
        "false",
        "--join",
        "false",
        "--instance",
        "false",
        "--palette",
        "false",
        "--simplify",
        "false",
        "--weld",
        "false",
    ]


def sparse_accessor_count(document: dict) -> int:
    return sum(1 for accessor in document.get("accessors", []) if isinstance(accessor, dict) and accessor.get("sparse"))


def build_sparse_densify_command(input_path: Path, output_path: Path) -> list[str]:
    return [
        "node",
        str(ROOT / "scripts" / "densify_gltf_sparse_accessors.cjs"),
        str(input_path),
        str(output_path),
    ]


def gltf_transform_node_env() -> dict[str, str]:
    env = dict(os.environ)
    candidates = [
        env.get("GLTF_TRANSFORM_NODE_PATH", ""),
        "/usr/local/lib/node_modules/@gltf-transform/cli/node_modules",
    ]
    node_paths = [path for path in candidates if path and Path(path).exists()]
    if node_paths:
        existing = env.get("NODE_PATH", "")
        env["NODE_PATH"] = os.pathsep.join([*node_paths, existing] if existing else node_paths)
    return env


def densify_sparse_accessors(path: Path) -> dict:
    before_doc = load_glb_json(path)
    before_count = sparse_accessor_count(before_doc)
    if before_count == 0:
        return {
            "status": "skipped",
            "reason": "no-sparse-accessors",
            "sparse_accessors_before": 0,
            "sparse_accessors_after": 0,
        }

    temp_path = path.with_name(f"{path.stem}.dense{path.suffix}")
    command = build_sparse_densify_command(path, temp_path)
    try:
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=gltf_transform_node_env(),
        )
    except FileNotFoundError as exc:
        return {
            "status": "skipped",
            "reason": f"node-not-installed:{command[0]}",
            "command": command,
            "sparse_accessors_before": before_count,
            "sparse_accessors_after": before_count,
            "log_tail": [str(exc)],
        }

    if completed.returncode != 0:
        temp_path.unlink(missing_ok=True)
        return {
            "status": "error",
            "command": command,
            "returncode": completed.returncode,
            "sparse_accessors_before": before_count,
            "sparse_accessors_after": before_count,
            "log_tail": completed.stdout.splitlines()[-80:],
        }

    after_doc = load_glb_json(temp_path)
    after_count = sparse_accessor_count(after_doc)
    temp_path.replace(path)
    parsed_stdout = {}
    try:
        parsed_stdout = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        parsed_stdout = {}
    return {
        "status": "ok",
        "command": command,
        "returncode": completed.returncode,
        "sparse_accessors_before": before_count,
        "sparse_accessors_after": after_count,
        "sparse_accessors_densified": int(parsed_stdout.get("sparse_accessors_densified", before_count - after_count)),
        "log_tail": completed.stdout.splitlines()[-80:],
    }


def summarize_gltf_document(document: dict) -> dict:
    morph_target_count = 0
    for mesh in document.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            if primitive.get("targets"):
                morph_target_count += 1
    return {
        "extensions_used": sorted(document.get("extensionsUsed", [])),
        "extensions_required": sorted(document.get("extensionsRequired", [])),
        "mesh_count": len(document.get("meshes", [])),
        "skin_count": len(document.get("skins", [])),
        "animation_count": len(document.get("animations", [])),
        "image_count": len(document.get("images", [])),
        "material_count": len(document.get("materials", [])),
        "morph_target_primitive_count": morph_target_count,
        "sparse_accessor_count": sparse_accessor_count(document),
    }


def compare_gltf_documents(before: dict, after: dict) -> dict:
    before_summary = summarize_gltf_document(before)
    after_summary = summarize_gltf_document(after)
    warnings = []

    before_required = set(before_summary["extensions_required"])
    after_required = set(after_summary["extensions_required"])
    for extension in sorted(after_required - before_required):
        warnings.append(f"required-extension-added:{extension}")

    for key in (
        "mesh_count",
        "skin_count",
        "animation_count",
        "material_count",
        "morph_target_primitive_count",
    ):
        if after_summary[key] < before_summary[key]:
            warnings.append(f"{key.replace('_', '-')}-decreased")

    return {
        "status": "review" if warnings else "ok",
        "warnings": warnings,
        "before": before_summary,
        "after": after_summary,
    }


def patch_animation_report(report_path: Path, optimization: dict, *, root: Path = ROOT) -> None:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    patched = {key: value for key, value in optimization.items() if key not in {"log_tail"}}
    if patched.get("output"):
        patched["output"] = to_workspace_path(patched["output"], root)
    if patched.get("input"):
        patched["input"] = to_workspace_path(patched["input"], root)
    report["optimized_glb"] = patched["output"]
    report["asset_optimization"] = patched
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def cached_optimization_result(
    report: dict,
    input_path: Path,
    output_path: Path,
    *,
    texture_size: int,
    texture_compress: str,
    geometry_compress: str,
    densify_sparse: bool,
    profile: str,
) -> dict | None:
    optimization = report.get("asset_optimization", {})
    if not isinstance(optimization, dict) or optimization.get("status") != "ok":
        return None
    if not input_path.exists() or not output_path.exists():
        return None
    if output_path.stat().st_mtime_ns < input_path.stat().st_mtime_ns:
        return None

    expected = {
        "profile": profile,
        "texture_size": texture_size,
        "texture_compress": texture_compress,
        "geometry_compress": geometry_compress,
        "densify_sparse_accessors": densify_sparse,
    }
    for key, value in expected.items():
        if optimization.get(key) != value:
            return None

    source_bytes = input_path.stat().st_size
    optimized_bytes = output_path.stat().st_size
    if int(optimization.get("source_bytes", -1) or -1) != source_bytes:
        return None
    if int(optimization.get("optimized_bytes", -1) or -1) != optimized_bytes:
        return None

    result = {key: value for key, value in optimization.items()}
    result.update(
        {
            "status": "ok",
            "profile": profile,
            "optimization_strategy": f"cached-{profile}-optimization",
            "cache_status": "hit",
            "input": str(input_path),
            "output": str(output_path),
            "source_bytes": source_bytes,
            "optimized_bytes": optimized_bytes,
            "saved_bytes": source_bytes - optimized_bytes,
            "size_ratio": round(optimized_bytes / source_bytes, 4) if source_bytes else None,
            "warnings": list(optimization.get("warnings", [])),
            "log_tail": [],
        }
    )
    return result


def store_persistent_optimization_cache(
    input_path: Path,
    output_path: Path,
    result: dict,
    *,
    texture_size: int,
    texture_compress: str,
    geometry_compress: str,
    densify_sparse: bool,
    profile: str,
    root: Path = ROOT,
) -> dict:
    if result.get("status") != "ok" or not input_path.exists() or not output_path.exists():
        return {"status": "skipped", "reason": "not-cacheable"}
    paths = persistent_optimization_cache_paths(
        input_path,
        texture_size=texture_size,
        texture_compress=texture_compress,
        geometry_compress=geometry_compress,
        densify_sparse=densify_sparse,
        profile=profile,
        root=root,
    )
    paths["glb"].parent.mkdir(parents=True, exist_ok=True)
    paths["metadata"].parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output_path, paths["glb"])
    metadata = {key: value for key, value in result.items() if key != "log_tail"}
    metadata.update(
        {
            "cache_key": paths["key"],
            "source_sha256": file_sha256(input_path),
            "profile": profile,
            "texture_size": texture_size,
            "texture_compress": texture_compress,
            "geometry_compress": geometry_compress,
            "densify_sparse_accessors": densify_sparse,
        }
    )
    paths["metadata"].write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "stored", "key": paths["key"], "output": str(paths["glb"])}


def materialize_persistent_optimization_cache(
    input_path: Path,
    output_path: Path,
    paths: dict,
    *,
    texture_size: int,
    texture_compress: str,
    geometry_compress: str,
    densify_sparse: bool,
    profile: str,
    root: Path = ROOT,
) -> dict | None:
    cache_glb = Path(paths["glb"])
    cache_metadata = Path(paths["metadata"])
    if not input_path.exists() or not cache_glb.exists() or not cache_metadata.exists():
        return None
    metadata = json.loads(cache_metadata.read_text(encoding="utf-8"))
    expected = {
        "source_sha256": file_sha256(input_path),
        "profile": profile,
        "texture_size": texture_size,
        "texture_compress": texture_compress,
        "geometry_compress": geometry_compress,
        "densify_sparse_accessors": densify_sparse,
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            return None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    materialization = link_or_copy_file(cache_glb, output_path)
    source_bytes = input_path.stat().st_size
    optimized_bytes = output_path.stat().st_size
    result = {key: value for key, value in metadata.items() if key not in {"input", "output"}}
    result.update(
        {
            "status": "ok",
            "profile": profile,
            "optimization_strategy": f"persistent-{profile}-optimization-cache",
            "cache_status": "hit",
            "cache_key": paths["key"],
            "materialization": materialization,
            "input": str(input_path),
            "output": str(output_path),
            "source_bytes": source_bytes,
            "optimized_bytes": optimized_bytes,
            "saved_bytes": source_bytes - optimized_bytes,
            "size_ratio": round(optimized_bytes / source_bytes, 4) if source_bytes else None,
            "warnings": list(metadata.get("warnings", [])),
            "log_tail": [],
        }
    )
    return result


def optimize_one(
    input_path: Path,
    output_path: Path,
    *,
    texture_size: int = 1024,
    texture_compress: str = "auto",
    geometry_compress: str = "false",
    densify_sparse: bool = True,
    profile: str = "standard",
) -> dict:
    if profile not in {"standard", "rough_preview"}:
        raise ValueError(f"unsupported optimization profile: {profile}")

    if profile == "rough_preview":
        output_path.parent.mkdir(parents=True, exist_ok=True)
        materialization = link_or_copy_file(input_path, output_path)
        source_bytes = input_path.stat().st_size
        optimized_bytes = output_path.stat().st_size
        return {
            "status": "ok",
            "profile": profile,
            "optimization_strategy": f"{materialization}-original-for-preview",
            "materialization": materialization,
            "input": str(input_path),
            "output": str(output_path),
            "source_bytes": source_bytes,
            "optimized_bytes": optimized_bytes,
            "saved_bytes": source_bytes - optimized_bytes,
            "size_ratio": round(optimized_bytes / source_bytes, 4) if source_bytes else None,
            "texture_size": texture_size,
            "texture_compress": texture_compress,
            "geometry_compress": geometry_compress,
            "densify_sparse_accessors": False,
            "sparse_densify": {"status": "disabled", "reason": "rough-preview-profile"},
            "command": [],
            "comparison": None,
            "warnings": [],
            "returncode": None,
            "log_tail": [],
        }

    before_doc = load_glb_json(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = build_optimization_command(
        input_path,
        output_path,
        texture_size=texture_size,
        texture_compress=texture_compress,
        geometry_compress=geometry_compress,
    )
    try:
        completed = subprocess.run(command, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except FileNotFoundError as exc:
        missing = command[0]
        return {
            "status": "skipped",
            "reason": f"optimizer-not-installed:{missing}",
            "input": str(input_path),
            "output": str(output_path),
            "command": command,
            "returncode": None,
            "log_tail": [str(exc)],
        }
    if completed.returncode != 0:
        return {
            "status": "error",
            "input": str(input_path),
            "output": str(output_path),
            "command": command,
            "returncode": completed.returncode,
            "log_tail": completed.stdout.splitlines()[-80:],
        }

    sparse_densify = {"status": "disabled"} if not densify_sparse else densify_sparse_accessors(output_path)
    after_doc = load_glb_json(output_path)
    comparison = compare_gltf_documents(before_doc, after_doc)
    source_bytes = input_path.stat().st_size
    optimized_bytes = output_path.stat().st_size
    warnings = list(comparison["warnings"])
    if sparse_densify.get("status") == "error":
        warnings.append("sparse-accessor-densify-error")
    elif densify_sparse and sparse_densify.get("status") == "skipped" and sparse_densify.get("reason") != "no-sparse-accessors":
        warnings.append(str(sparse_densify.get("reason", "sparse-accessor-densify-skipped")))
    if sparse_accessor_count(after_doc):
        warnings.append(f"sparse-accessors-present:{sparse_accessor_count(after_doc)}")
    if optimized_bytes >= source_bytes:
        warnings.append("optimized-file-not-smaller")

    return {
        "status": "review" if warnings else "ok",
        "profile": profile,
        "optimization_strategy": "gltf-transform-optimize",
        "input": str(input_path),
        "output": str(output_path),
        "source_bytes": source_bytes,
        "optimized_bytes": optimized_bytes,
        "saved_bytes": source_bytes - optimized_bytes,
        "size_ratio": round(optimized_bytes / source_bytes, 4) if source_bytes else None,
        "texture_size": texture_size,
        "texture_compress": texture_compress,
        "geometry_compress": geometry_compress,
        "densify_sparse_accessors": densify_sparse,
        "sparse_densify": sparse_densify,
        "command": command,
        "comparison": comparison,
        "warnings": warnings,
        "returncode": completed.returncode,
        "log_tail": completed.stdout.splitlines()[-80:],
    }


def report_input_path(report: dict) -> Path:
    value = report.get("output_glb") or report.get("optimized_glb")
    if not value:
        raise ValueError("report has no output_glb")
    return workspace_path(value)


def optimize_report(report_path: Path, output_dir: Path, args: argparse.Namespace) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    input_path = report_input_path(report)
    output_path = output_dir / input_path.name
    densify_sparse = not args.preserve_sparse_accessors
    profile = getattr(args, "profile", "standard")
    if profile == "rough_preview" and not getattr(args, "skip_existing", False):
        result = optimize_one(
            input_path,
            output_path,
            texture_size=args.texture_size,
            texture_compress=args.texture_compress,
            geometry_compress=args.geometry_compress,
            densify_sparse=densify_sparse,
            profile=profile,
        )
        if result["status"] in {"ok", "review"}:
            patch_animation_report(report_path, result)
        return result
    if getattr(args, "skip_existing", False):
        cached = cached_optimization_result(
            report,
            input_path,
            output_path,
            texture_size=args.texture_size,
            texture_compress=args.texture_compress,
            geometry_compress=args.geometry_compress,
            densify_sparse=densify_sparse,
            profile=profile,
        )
        if cached:
            patch_animation_report(report_path, cached)
            return cached
    persistent_paths = persistent_optimization_cache_paths(
        input_path,
        texture_size=args.texture_size,
        texture_compress=args.texture_compress,
        geometry_compress=args.geometry_compress,
        densify_sparse=densify_sparse,
        profile=profile,
    )
    persistent_cached = materialize_persistent_optimization_cache(
        input_path,
        output_path,
        persistent_paths,
        texture_size=args.texture_size,
        texture_compress=args.texture_compress,
        geometry_compress=args.geometry_compress,
        densify_sparse=densify_sparse,
        profile=profile,
    )
    if persistent_cached:
        patch_animation_report(report_path, persistent_cached)
        return persistent_cached
    result = optimize_one(
        input_path,
        output_path,
        texture_size=args.texture_size,
        texture_compress=args.texture_compress,
        geometry_compress=args.geometry_compress,
        densify_sparse=densify_sparse,
        profile=profile,
    )
    if result["status"] in {"ok", "review"}:
        patch_animation_report(report_path, result)
    if result["status"] == "ok":
        result["persistent_optimization_cache"] = store_persistent_optimization_cache(
            input_path,
            output_path,
            result,
            texture_size=args.texture_size,
            texture_compress=args.texture_compress,
            geometry_compress=args.geometry_compress,
            densify_sparse=densify_sparse,
            profile=profile,
        )
    return result


def report_path_for_job(job: dict) -> Path | None:
    env = job.get("environment", {})
    report_value = env.get("ANIMATION_REPORT_JSON")
    if not report_value:
        return None
    path = workspace_path(report_value)
    return path if path.exists() else None


def link_or_copy_file(source: Path, target: Path) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    try:
        os.link(source, target)
        return "linked"
    except OSError:
        shutil.copy2(source, target)
        return "copied"


def copy_render_dedup_optimization(
    job: dict,
    source_result: dict,
    report_path: Path,
    output_dir: Path,
    *,
    root: Path = ROOT,
) -> dict | None:
    source_output = source_result.get("output")
    if not source_output:
        return None
    source_output_path = workspace_path(source_output, root)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    input_path = report_input_path(report)
    output_path = output_dir / input_path.name
    if not source_output_path.exists() or not input_path.exists():
        return None
    materialize_mode = link_or_copy_file(source_output_path, output_path)
    source_bytes = input_path.stat().st_size
    optimized_bytes = output_path.stat().st_size
    result = {
        **{key: value for key, value in source_result.items() if key not in {"job_id", "log_tail"}},
        "status": "ok",
        "optimization_strategy": f"{materialize_mode}-render-dedup-optimization",
        "render_dedup_source_job_id": job.get("render_dedup", {}).get("source_job_id"),
        "input": str(input_path),
        "output": str(output_path),
        "source_bytes": source_bytes,
        "optimized_bytes": optimized_bytes,
        "saved_bytes": source_bytes - optimized_bytes,
        "size_ratio": round(optimized_bytes / source_bytes, 4) if source_bytes else None,
        "warnings": list(source_result.get("warnings", [])),
        "log_tail": [],
    }
    patch_animation_report(report_path, result, root=root)
    return result


def optimize_batch(batch_result_path: Path, output_dir: Path, args: argparse.Namespace) -> dict:
    batch = json.loads(batch_result_path.read_text(encoding="utf-8"))
    results = []
    results_by_job_id = {}
    deduped_count = 0
    for job in batch.get("jobs", []):
        if job.get("status") != "ok":
            continue
        report_path = report_path_for_job(job)
        if not report_path:
            continue
        dedup_source = job.get("render_dedup", {}).get("source_job_id")
        result = None
        if dedup_source and dedup_source in results_by_job_id:
            result = copy_render_dedup_optimization(job, results_by_job_id[dedup_source], report_path, output_dir)
            if result:
                deduped_count += 1
        if not result:
            result = optimize_report(report_path, output_dir, args)
        result["job_id"] = job.get("id")
        results.append(result)
        results_by_job_id[str(job.get("id"))] = result
    summary = {
        "status": "ok" if all(item["status"] == "ok" for item in results) else "review",
        "profile": getattr(args, "profile", "standard"),
        "batch_result": str(batch_result_path),
        "output_dir": str(output_dir),
        "count": len(results),
        "deduped_count": deduped_count,
        "source_bytes": sum(item.get("source_bytes", 0) for item in results),
        "optimized_bytes": sum(item.get("optimized_bytes", 0) for item in results),
        "saved_bytes": sum(item.get("saved_bytes", 0) for item in results),
        "results": results,
    }
    if summary["source_bytes"]:
        summary["size_ratio"] = round(summary["optimized_bytes"] / summary["source_bytes"], 4)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Optimize generated GLB assets without overwriting originals.")
    parser.add_argument("input", nargs="?", help="Input GLB path, or omit when using --batch-result.")
    parser.add_argument("output", nargs="?", help="Output GLB path for a single input.")
    parser.add_argument("--report-json", help="Patch an animation report after a single optimization.")
    parser.add_argument("--batch-result", help="Optimize all ok jobs in a batch result JSON.")
    parser.add_argument("--output-dir", default="outputs/batch_optimized")
    parser.add_argument("--summary-json", default="results/glb_optimization_latest.json")
    parser.add_argument("--texture-size", type=int, default=1024)
    parser.add_argument("--texture-compress", default="auto")
    parser.add_argument("--geometry-compress", default="false")
    parser.add_argument(
        "--profile",
        choices=["standard", "rough_preview"],
        default="standard",
        help="Optimization behavior. rough_preview copies GLBs for fast QA while keeping optimized paths stable.",
    )
    parser.add_argument(
        "--preserve-sparse-accessors",
        action="store_true",
        help="Skip sparse accessor densification. Faster/smaller, but Godot may log sparse import warnings.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Reuse an up-to-date optimized GLB when the animation report metadata matches this optimization request.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    if args.batch_result:
        summary = optimize_batch(Path(args.batch_result), output_dir, args)
    else:
        if not args.input or not args.output:
            raise SystemExit("input and output are required unless --batch-result is used")
        result = optimize_one(
            workspace_path(args.input),
            workspace_path(args.output),
            texture_size=args.texture_size,
            texture_compress=args.texture_compress,
            geometry_compress=args.geometry_compress,
            densify_sparse=not args.preserve_sparse_accessors,
            profile=args.profile,
        )
        if args.report_json and result["status"] in {"ok", "review"}:
            patch_animation_report(workspace_path(args.report_json), result)
        summary = result

    summary_path = Path(args.summary_json)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    if summary["status"] == "error":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
