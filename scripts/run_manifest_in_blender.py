from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.batch_pipeline import load_manifest, planned_job_environment


def argv_after_separator() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def blender_job_argv(env: dict[str, str]) -> list[str]:
    return [
        "blender",
        "--",
        env["INPUT_MODEL"],
        env["ANIMATION_REPORT_JSON"],
        env["OUTPUT_BLEND"],
        env["OUTPUT_GLB"],
    ]


def workspace_path(path: str) -> Path:
    if path.startswith("/workspace/"):
        return Path("/workspace") / path.removeprefix("/workspace/")
    return Path(path)


def cache_path_for_model(model_path: str, cache_dir: str = "/workspace/cache/base_scenes") -> str:
    source = workspace_path(model_path)
    digest = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:16]
    stem = source.stem.replace(" ", "_")
    return f"{cache_dir.rstrip('/')}/{stem}_{digest}.blend"


def should_cache_model(model_path: str) -> bool:
    return workspace_path(model_path).suffix.lower() in {".vrm", ".glb", ".gltf", ".fbx", ".obj"}


def cached_environment(env: dict[str, str], cache_map: dict[str, str]) -> dict[str, str]:
    cached = dict(env)
    model_path = env.get("INPUT_MODEL", "")
    if model_path in cache_map:
        cached["INPUT_MODEL"] = cache_map[model_path]
        cached["BASE_SCENE_CACHE_SOURCE"] = model_path
    return cached


def reset_blender_state() -> None:
    import bpy

    bpy.ops.object.mode_set(mode="OBJECT") if bpy.ops.object.mode_set.poll() else None
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    for collection in (
        bpy.data.meshes,
        bpy.data.armatures,
        bpy.data.materials,
        bpy.data.images,
        bpy.data.actions,
        bpy.data.cameras,
        bpy.data.lights,
    ):
        for datablock in list(collection):
            if datablock.users == 0:
                collection.remove(datablock)
    for area in getattr(bpy.context.screen, "areas", []):
        if area.type != "VIEW_3D":
            continue
        for space in area.spaces:
            if space.type == "VIEW_3D":
                space.shading.type = "SOLID"


def build_base_scene_cache(model_path: str, cache_path: str) -> dict:
    from scripts import animate_smoke
    import bpy

    start = time.perf_counter()
    destination = Path(cache_path)
    if destination.exists():
        return {
            "source": model_path,
            "cache": cache_path,
            "status": "reused",
            "elapsed_seconds": 0.0,
        }

    destination.parent.mkdir(parents=True, exist_ok=True)
    reset_blender_state()
    errors = animate_smoke.try_import(Path(model_path))
    armature = animate_smoke.find_armature()
    if armature:
        animate_smoke.clear_existing_animation()
    if errors or not armature:
        return {
            "source": model_path,
            "cache": cache_path,
            "status": "error",
            "errors": errors or ["missing armature after cache import"],
            "elapsed_seconds": round(time.perf_counter() - start, 3),
        }
    bpy.ops.wm.save_as_mainfile(filepath=str(destination))
    return {
        "source": model_path,
        "cache": cache_path,
        "status": "ok",
        "elapsed_seconds": round(time.perf_counter() - start, 3),
    }


def build_cache_map(manifest: dict) -> tuple[dict[str, str], list[dict]]:
    if str(manifest.get("defaults", {}).get("cache_base_scenes", "1")) != "1":
        return {}, []
    cache_dir = manifest.get("defaults", {}).get("base_scene_cache_dir", "/workspace/cache/base_scenes")
    model_paths = []
    for job in manifest["jobs"]:
        env = planned_job_environment(manifest, job)
        model_path = env["INPUT_MODEL"]
        if should_cache_model(model_path) and model_path not in model_paths:
            model_paths.append(model_path)
    cache_map = {model_path: cache_path_for_model(model_path, cache_dir) for model_path in model_paths}
    reports = [build_base_scene_cache(model_path, cache_path) for model_path, cache_path in cache_map.items()]
    return cache_map, reports


@contextlib.contextmanager
def temporary_environment(values: dict[str, str]):
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def run_job_in_process(manifest: dict, job: dict, cache_map: dict[str, str] | None = None) -> dict:
    env = cached_environment(planned_job_environment(manifest, job), cache_map or {})
    start = time.perf_counter()
    previous_argv = sys.argv[:]
    result = {
        "id": job["id"],
        "metadata": {
            "display_name": job.get("display_name", job["id"].replace("-", " ").title()),
            "license": job.get("license"),
            "persona": job.get("persona"),
            "source_url": job.get("source_url"),
            "tags": job.get("tags", []),
            "notes": job.get("notes"),
        },
        "environment": env,
        "status": "pending",
    }
    try:
        from scripts import animate_smoke

        with temporary_environment(env):
            reset_blender_state()
            sys.argv = blender_job_argv(env)
            animate_smoke.main()
        result["status"] = "ok"
        result["returncode"] = 0
    except Exception as exc:
        result["status"] = "error"
        result["returncode"] = 1
        result["error"] = str(exc)
    finally:
        sys.argv = previous_argv
        result["elapsed_seconds"] = round(time.perf_counter() - start, 3)
    return result


def main() -> None:
    args = argv_after_separator()
    manifest_path = Path(args[0] if args else "config/person_factory.quick.json")
    output_path = Path(args[1] if len(args) > 1 else "results/batch_person_factory_in_blender_latest.json")
    manifest = load_manifest(manifest_path)
    start = time.perf_counter()
    cache_map, cache_reports = build_cache_map(manifest)
    if any(report["status"] == "error" for report in cache_reports):
        results = []
    else:
        results = [run_job_in_process(manifest, job, cache_map) for job in manifest["jobs"]]
    output = {
        "manifest": str(manifest_path),
        "runner": "in-blender",
        "base_scene_cache": cache_reports,
        "elapsed_seconds": round(time.perf_counter() - start, 3),
        "jobs": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(output, indent=2, sort_keys=True))
    if any(report["status"] == "error" for report in cache_reports) or any(job["status"] == "error" for job in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
