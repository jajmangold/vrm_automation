from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


MUSE_TALK_V15 = {
    "version": "v15",
    "unet_model_path": "models/musetalkV15/unet.pth",
    "unet_config": "models/musetalkV15/musetalk.json",
}


def _require_non_empty(name: str, value: str) -> str:
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _normalize_manual_bbox(manual_bbox: list[int] | tuple[int, ...] | None) -> list[int] | None:
    if manual_bbox is None:
        return None
    if len(manual_bbox) != 4:
        raise ValueError("manual_bbox must contain four values: x1, y1, x2, y2")
    bbox = [int(value) for value in manual_bbox]
    x1, y1, x2, y2 = bbox
    if x2 <= x1 or y2 <= y1 or x1 < 0 or y1 < 0:
        raise ValueError("manual_bbox must be a positive x1,y1,x2,y2 crop")
    return bbox


def build_musetalk_job(
    *,
    character_id: str,
    source_media: str,
    audio_path: str,
    result_name: str,
    inference_config: str | None = None,
    result_dir: str = "/workspace/outputs/musetalk",
    bbox_shift: int | None = None,
    manual_bbox: list[int] | tuple[int, ...] | None = None,
    parsing_mode: str | None = None,
    fps: int = 25,
    version: str = "v15",
    use_float16: bool = False,
) -> dict:
    if version != "v15":
        raise ValueError("only MuseTalk v15 is supported by this adapter")
    task = {
        "video_path": _require_non_empty("source_media", source_media),
        "audio_path": _require_non_empty("audio_path", audio_path),
        "result_name": _require_non_empty("result_name", result_name),
    }
    if bbox_shift is not None:
        task["bbox_shift"] = int(bbox_shift)
    normalized_bbox = _normalize_manual_bbox(manual_bbox)
    if normalized_bbox:
        task["manual_bbox"] = normalized_bbox
    character_id = _require_non_empty("character_id", character_id)
    inference_config = inference_config or f"/workspace/results/musetalk/{character_id}.yaml"
    job = {
        "schema": "vrm-person-factory.musetalk-job.v1",
        "backend": "musetalk",
        "mode": "talking-video",
        "character_id": character_id,
        "version": version,
        "fps": int(fps),
        "result_dir": result_dir,
        "inference_config": inference_config,
        "use_float16": bool(use_float16),
        "tasks": {"task_0": task},
    }
    if parsing_mode:
        job["parsing_mode"] = str(parsing_mode)
    return job


def _yaml_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def write_musetalk_inference_config(job: dict, output_path: Path) -> None:
    tasks = job.get("tasks") or {}
    if not tasks:
        raise ValueError("MuseTalk job requires at least one task")
    lines = []
    for task_id, task in tasks.items():
        lines.append(f"{task_id}:")
        for key in ("video_path", "audio_path", "result_name", "bbox_shift"):
            if key in task:
                lines.append(f"  {key}: {_yaml_scalar(task[key])}")
        lines.append("")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def build_musetalk_command(job: dict) -> list[str]:
    if job.get("version", "v15") != "v15":
        raise ValueError("only MuseTalk v15 is supported by this adapter")
    command = [
        "python3",
        "-m",
        "scripts.inference",
        "--inference_config",
        job["inference_config"],
        "--result_dir",
        job.get("result_dir", "/workspace/outputs/musetalk"),
        "--unet_model_path",
        MUSE_TALK_V15["unet_model_path"],
        "--unet_config",
        MUSE_TALK_V15["unet_config"],
        "--version",
        MUSE_TALK_V15["version"],
        "--fps",
        str(job.get("fps", 25)),
    ]
    if job.get("use_float16"):
        command.append("--use_float16")
    if job.get("parsing_mode"):
        command.extend(["--parsing_mode", str(job["parsing_mode"])])
    return command


def parse_args(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a MuseTalk talking-video job manifest.")
    parser.add_argument("--character-id", required=True)
    parser.add_argument("--source-media", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--result-name", required=True)
    parser.add_argument("--output", default="results/musetalk/latest_job.json")
    parser.add_argument("--inference-config")
    parser.add_argument("--result-dir", default="/workspace/outputs/musetalk")
    parser.add_argument("--bbox-shift", type=int)
    parser.add_argument("--parsing-mode")
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument("--use-float16", action="store_true")
    parser.add_argument("--write-config", action="store_true")
    return parser.parse_args(args)


def main(args: list[str] | None = None) -> None:
    parsed = parse_args(sys.argv[1:] if args is None else args)
    job = build_musetalk_job(
        character_id=parsed.character_id,
        source_media=parsed.source_media,
        audio_path=parsed.audio,
        result_name=parsed.result_name,
        inference_config=parsed.inference_config,
        result_dir=parsed.result_dir,
        bbox_shift=parsed.bbox_shift,
        parsing_mode=parsed.parsing_mode,
        fps=parsed.fps,
        use_float16=parsed.use_float16,
    )
    output_path = Path(parsed.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")
    if parsed.write_config:
        write_musetalk_inference_config(job, Path(job["inference_config"]))
    print(json.dumps({"job": str(output_path), "command": build_musetalk_command(job)}, indent=2))


if __name__ == "__main__":
    main()
