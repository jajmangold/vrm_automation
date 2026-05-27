from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_MODEL_FILES = (
    "musetalkV15/unet.pth",
    "musetalkV15/musetalk.json",
    "whisper/config.json",
    "whisper/pytorch_model.bin",
    "whisper/preprocessor_config.json",
    "sd-vae/config.json",
    "sd-vae/diffusion_pytorch_model.bin",
    "dwpose/dw-ll_ucoco_384.pth",
    "face-parse-bisent/79999_iter.pth",
    "face-parse-bisent/resnet18-5c106cde.pth",
)


def workspace_path(path: str) -> Path:
    if path.startswith("/workspace/"):
        return ROOT / path.removeprefix("/workspace/")
    return Path(path)


def as_workspace_path(path: Path) -> str:
    try:
        return f"/workspace/{path.resolve().relative_to(ROOT.resolve()).as_posix()}"
    except ValueError:
        return str(path)


def check_model_cache(model_dir: Path) -> list[str]:
    return [relative for relative in REQUIRED_MODEL_FILES if not (model_dir / relative).exists()]


def select_best_gpu_id(nvidia_smi_csv: str) -> str | None:
    candidates = []
    for line in nvidia_smi_csv.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            gpu_id = int(parts[0])
            free_mib = int(parts[1])
        except ValueError:
            continue
        candidates.append((free_mib, -gpu_id, str(gpu_id)))
    if not candidates:
        return None
    return max(candidates)[2]


def detect_best_gpu_id() -> str | None:
    try:
        output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=index,memory.free,memory.total",
                "--format=csv,noheader,nounits",
            ],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return select_best_gpu_id(output)


def resolve_gpu_id(requested_gpu_id: str | None) -> str | None:
    if requested_gpu_id and requested_gpu_id != "auto":
        return requested_gpu_id
    env_gpu_id = os.environ.get("MUSE_TALK_GPU_ID")
    if env_gpu_id:
        return env_gpu_id
    return detect_best_gpu_id()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def expected_output_path(job: dict) -> Path:
    tasks = job.get("tasks") or {}
    if not tasks:
        raise ValueError("MuseTalk job has no tasks")
    task = next(iter(tasks.values()))
    result_dir = job.get("result_dir", "/workspace/outputs/musetalk")
    version = job.get("version", "v15")
    return workspace_path(f"{result_dir}/{version}/{task['result_name']}")


def task_audio_path(job: dict) -> str:
    task = next(iter((job.get("tasks") or {}).values()))
    return task.get("audio_path", "")


def batch_report_paths(batch_result: dict) -> dict[str, Path]:
    report_paths = {}
    for batch_job in batch_result.get("jobs", []):
        env = batch_job.get("environment") or {}
        report_json = env.get("ANIMATION_REPORT_JSON")
        if batch_job.get("id") and report_json:
            report_paths[batch_job["id"]] = workspace_path(report_json)
    return report_paths


def patch_report_with_talking_video(report_path: Path, talking_video: str, metadata: dict) -> None:
    report = load_json(report_path) if report_path.exists() else {"status": "missing-before-publish"}
    report["talking_video"] = talking_video
    report["talking_video_backend"] = "musetalk"
    report["talking_video_quality"] = "preview"
    report["talking_video_job"] = metadata
    write_json(report_path, report)


def publish_completed_jobs(job_paths: list[Path], batch_result_path: Path) -> dict:
    batch_result = load_json(batch_result_path)
    reports = batch_report_paths(batch_result)
    published = []
    missing_outputs = []
    missing_reports = []
    for job_path in job_paths:
        job = load_json(job_path)
        video_path = expected_output_path(job)
        character_id = job.get("character_id")
        report_path = reports.get(character_id)
        if not video_path.exists():
            missing_outputs.append(str(job_path))
            continue
        if not report_path:
            missing_reports.append(str(job_path))
            continue
        talking_video = as_workspace_path(video_path)
        patch_report_with_talking_video(
            report_path,
            talking_video,
            {
                "job": as_workspace_path(job_path),
                "audio_path": task_audio_path(job),
                "output": talking_video,
            },
        )
        published.append({"character_id": character_id, "report": as_workspace_path(report_path), "video": talking_video})
    return {
        "published": len(published),
        "published_jobs": published,
        "missing_outputs": missing_outputs,
        "missing_reports": missing_reports,
    }


def discover_jobs(jobs_dir: Path, limit: int | None = None) -> list[Path]:
    jobs = sorted(jobs_dir.glob("*.job.json"))
    return jobs[:limit] if limit else jobs


def filter_existing_outputs(job_paths: list[Path]) -> tuple[list[Path], list[dict]]:
    selected = []
    skipped = []
    for job_path in job_paths:
        job = load_json(job_path)
        output = expected_output_path(job)
        if output.exists():
            skipped.append({"job": str(job_path), "output": str(output)})
        else:
            selected.append(job_path)
    return selected, skipped


def run_job(job_path: Path, gpu_id: str | None = None) -> int:
    workspace_job = as_workspace_path(job_path)
    command = [
        "docker",
        "compose",
        "--profile",
        "musetalk",
        "run",
        "--rm",
        "-e",
        f"MUSE_TALK_JOB_JSON={workspace_job}",
        "musetalk",
    ]
    env = os.environ.copy()
    if gpu_id:
        env["MUSE_TALK_GPU_ID"] = gpu_id
    return subprocess.call(command, cwd=ROOT, env=env)


def run_status(missing_models: list[str], run_results: list[dict], publish_summary: dict | None = None) -> str:
    if missing_models:
        return "blocked"
    if any(result.get("returncode", 0) != 0 for result in run_results):
        return "failed"
    if run_results and publish_summary and publish_summary.get("missing_outputs"):
        return "failed"
    return "ok"


def parse_args(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run or publish MuseTalk batch jobs.")
    parser.add_argument("jobs_dir", nargs="?", default="results/musetalk/person_factory_hello_batch")
    parser.add_argument("--batch-result", default="results/batch_asset_pool_first20.json")
    parser.add_argument("--model-dir", default="input/musetalk_models")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--run", action="store_true", help="Run jobs through the musetalk compose profile before publishing.")
    parser.add_argument("--publish", action="store_true", help="Patch animation reports for completed MP4 outputs.")
    parser.add_argument("--skip-existing", action="store_true", help="When running, skip jobs whose expected MP4 already exists.")
    parser.add_argument(
        "--gpu-id",
        default="auto",
        help="GPU id for MuseTalk runs. Defaults to auto; an explicit MUSE_TALK_GPU_ID environment value is respected.",
    )
    parser.add_argument("--status-output", default="results/musetalk/run_status.json")
    return parser.parse_args(args)


def main(args: list[str] | None = None) -> None:
    parsed = parse_args(sys.argv[1:] if args is None else args)
    discovered_job_paths = discover_jobs(Path(parsed.jobs_dir), parsed.limit)
    skipped_existing = []
    job_paths = discovered_job_paths
    if parsed.run and parsed.skip_existing:
        job_paths, skipped_existing = filter_existing_outputs(discovered_job_paths)
    missing_models = check_model_cache(Path(parsed.model_dir))
    gpu_id = resolve_gpu_id(parsed.gpu_id) if parsed.run else None
    run_results = []
    if parsed.run and missing_models:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": "missing-musetalk-model-files",
                    "missing_models": missing_models,
                    "jobs": len(job_paths),
                },
                indent=2,
                sort_keys=True,
            )
        )
    elif parsed.run:
        for job_path in job_paths:
            run_results.append({"job": str(job_path), "returncode": run_job(job_path, gpu_id)})
    publish_summary = publish_completed_jobs(job_paths, Path(parsed.batch_result)) if parsed.publish else {}
    summary = {
        "status": run_status(missing_models, run_results, publish_summary),
        "jobs": len(job_paths),
        "discovered_jobs": len(discovered_job_paths),
        "skipped_existing": skipped_existing,
        "skipped_existing_count": len(skipped_existing),
        "gpu_id": gpu_id,
        "missing_models": missing_models,
        "run_results": run_results,
        "publish": publish_summary,
    }
    write_json(Path(parsed.status_output), summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
