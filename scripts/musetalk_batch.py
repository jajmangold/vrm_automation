from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_batch_gallery import read_report
from scripts.musetalk_adapter import build_musetalk_job, write_musetalk_inference_config


def workspace_path(path: str) -> Path:
    if path.startswith("/workspace/"):
        return ROOT / path.removeprefix("/workspace/")
    return Path(path)


def as_workspace_path(path: Path) -> str:
    try:
        return f"/workspace/{path.resolve().relative_to(ROOT.resolve()).as_posix()}"
    except ValueError:
        return str(path)


def source_media_score(path: str) -> tuple[int, str]:
    name = Path(path).name
    score = 0
    for value, token in ((100, "portrait"), (70, "front"), (50, "three_quarter"), (10, "side")):
        if token in name:
            score += value
            break
    for value, token in ((40, "0072"), (35, "0001"), (25, "0048"), (5, "0024")):
        if token in name:
            score += value
            break
    return score, name


def sibling_portrait_candidates(path: str) -> list[str]:
    render_path = workspace_path(path)
    candidates = []
    for frame in ("0072", "0001", "0048", "0024"):
        sibling = render_path.with_name(f"pose_portrait_{frame}.png")
        if sibling.exists():
            candidates.append(as_workspace_path(sibling))
    return candidates


def png_dimensions(path: Path) -> tuple[int, int] | None:
    if not path.exists():
        return None
    header = path.read_bytes()[:24]
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", header[16:24])
    return int(width), int(height)


def estimate_manual_bbox(source_media: str) -> list[int] | None:
    dimensions = png_dimensions(workspace_path(source_media))
    if not dimensions:
        return None
    width, height = dimensions
    # MuseTalk V1.5 works better on stylized VRM portraits when the saved crop
    # is constrained to the mouth/chin region instead of replacing the full face.
    return [
        int(width * 0.32),
        int(height * 0.38),
        int(width * 0.68),
        int(height * 0.66),
    ]


def pick_source_media(report: dict) -> str:
    renders = report.get("pose_renders") or []
    if not renders:
        raise ValueError("report has no pose_renders for MuseTalk source media")
    candidates = []
    for path in renders:
        candidates.append(path)
        candidates.extend(sibling_portrait_candidates(path))
    preferred_frame = (report.get("qa") or {}).get("preferred_review_frame")
    if report.get("lipsync_animation", {}).get("enabled") and preferred_frame:
        for candidate in sorted(set(candidates)):
            if Path(candidate).name == preferred_frame or Path(candidate).name.endswith(f"_{preferred_frame}"):
                return candidate
    unique_candidates = sorted(set(candidates), key=lambda item: source_media_score(item), reverse=True)
    return unique_candidates[0]


def load_audio_manifest(path: Path) -> list[dict]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    clips = manifest.get("clips")
    if not clips:
        raise ValueError("audio manifest must contain at least one clip")
    for clip in clips:
        if not clip.get("id") or not clip.get("path"):
            raise ValueError("each audio clip requires id and path")
        path = str(clip["path"])
        if not path.startswith(("http://", "https://")) and not workspace_path(path).exists():
            raise ValueError(f"audio clip path does not exist: {path}")
    return clips


def build_batch_jobs(batch_result: dict, audio_clips: list[dict], output_dir: Path) -> list[dict]:
    jobs = []
    for batch_job in batch_result.get("jobs", []):
        if batch_job.get("status") not in (None, "ok", "planned"):
            continue
        env = batch_job.get("environment", {})
        if not env:
            continue
        report = read_report(env)
        if report.get("status") not in (None, "ok"):
            continue
        if batch_job.get("qa"):
            report = {**report, "qa": batch_job["qa"]}
        source_media = pick_source_media(report)
        manual_bbox = estimate_manual_bbox(source_media)
        character_id = batch_job["id"]
        for clip in audio_clips:
            job_id = f"{character_id}_{clip['id']}"
            jobs.append(
                build_musetalk_job(
                    character_id=character_id,
                    source_media=source_media,
                    audio_path=clip["path"],
                    result_name=f"{job_id}.mp4",
                    inference_config=f"/workspace/{output_dir.as_posix()}/{job_id}.yaml",
                    result_dir="/workspace/outputs/musetalk",
                    use_float16=bool(clip.get("use_float16", True)),
                    bbox_shift=clip.get("bbox_shift"),
                    manual_bbox=manual_bbox,
                    parsing_mode=clip.get("parsing_mode", "jaw"),
                )
            )
    return jobs


def write_jobs(jobs: list[dict], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for job in jobs:
        task = job["tasks"]["task_0"]
        job_id = Path(task["result_name"]).stem
        (output_dir / f"{job_id}.job.json").write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")
        write_musetalk_inference_config(job, output_dir / f"{job_id}.yaml")


def parse_args(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create MuseTalk jobs from a person-factory batch result.")
    parser.add_argument("batch_result", nargs="?", default="results/batch_person_factory_in_blender_latest.json")
    parser.add_argument("audio_manifest", nargs="?", default="config/musetalk_audio.example.json")
    parser.add_argument("output_dir", nargs="?", default="results/musetalk/batch")
    return parser.parse_args(args)


def main(args: list[str] | None = None) -> None:
    parsed = parse_args(sys.argv[1:] if args is None else args)
    batch_result = json.loads(Path(parsed.batch_result).read_text(encoding="utf-8"))
    audio_clips = load_audio_manifest(Path(parsed.audio_manifest))
    output_dir = Path(parsed.output_dir)
    jobs = build_batch_jobs(batch_result, audio_clips, output_dir)
    write_jobs(jobs, output_dir)
    print(json.dumps({"output_dir": str(output_dir), "jobs": len(jobs)}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
