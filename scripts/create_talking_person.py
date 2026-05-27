from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.create_person_now import build_single_person_manifest
from scripts.make_person_manifest import BASE_MODELS, load_accessories, slug
from scripts.rhubarb_adapter import write_lipsync_timeline


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RHUBARB_BIN = ROOT / "input/rhubarb/Rhubarb-Lip-Sync-1.14.0-Linux/rhubarb"


def local_path(path: str | Path, root: Path = ROOT) -> Path:
    path_text = str(path)
    if path_text.startswith("/workspace/"):
        return root / path_text.removeprefix("/workspace/")
    candidate = Path(path_text)
    if candidate.is_absolute():
        return candidate
    return root / candidate


def workspace_path(path: str | Path, root: Path = ROOT) -> str:
    path_text = str(path)
    if path_text.startswith("/workspace/"):
        return path_text
    candidate = Path(path_text)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        relative = candidate.resolve().relative_to(root.resolve())
    except ValueError:
        return candidate.as_posix()
    return f"/workspace/{relative.as_posix()}"


def build_ffmpeg_normalize_command(
    input_wav: str | Path,
    output_wav: str | Path,
    *,
    mode: str = "auto",
    root: Path = ROOT,
) -> list[str]:
    selected_mode = resolve_normalizer_mode(mode)
    input_arg = workspace_path(input_wav, root=root) if selected_mode == "docker" else str(local_path(input_wav, root=root))
    output_arg = workspace_path(output_wav, root=root) if selected_mode == "docker" else str(local_path(output_wav, root=root))
    ffmpeg_args = [
        "-y",
        "-v",
        "warning",
        "-i",
        input_arg,
        "-ar",
        "16000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        output_arg,
    ]
    if selected_mode == "docker":
        return [
            "docker",
            "compose",
            "--profile",
            "musetalk",
            "run",
            "--rm",
            "--entrypoint",
            "ffmpeg",
            "musetalk",
            *ffmpeg_args,
        ]
    return ["ffmpeg", *ffmpeg_args]


def resolve_normalizer_mode(mode: str) -> str:
    if mode == "auto":
        return "local" if shutil.which("ffmpeg") else "docker"
    if mode not in {"docker", "local"}:
        raise ValueError(f"unknown normalizer mode: {mode}")
    return mode


def build_rhubarb_command(
    rhubarb_bin: str | Path,
    normalized_wav: str | Path,
    output_json: str | Path,
    *,
    root: Path = ROOT,
) -> list[str]:
    return [
        str(local_path(rhubarb_bin, root=root)),
        "-f",
        "json",
        "-o",
        str(local_path(output_json, root=root)),
        str(local_path(normalized_wav, root=root)),
    ]


def should_run_lipsync_alignment(timeline_path: Path, *, reuse_lipsync: bool = False) -> bool:
    return not (reuse_lipsync and timeline_path.exists())


def lipsync_cache_key(timeline_path: Path, root: Path = ROOT) -> str:
    try:
        relative = timeline_path.resolve().relative_to((root / "outputs/lipsync/cache").resolve())
    except ValueError:
        return ""
    name = relative.name
    if name.endswith(".face.json"):
        return name.removesuffix(".face.json")
    return relative.stem


def cache_report(timeline_path: Path, *, reused_lipsync: bool, root: Path = ROOT) -> dict:
    key = lipsync_cache_key(timeline_path, root=root)
    if not key:
        return {}
    return {
        "audio_cache_key": key,
        "lipsync_timeline": workspace_path(timeline_path, root=root),
        "reused_lipsync": reused_lipsync,
    }


def run_checked(command: list[str]) -> None:
    completed = subprocess.run(command, cwd=ROOT, text=True)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def auto_paths(audio_wav: Path, person_id: str, root: Path = ROOT) -> dict[str, Path]:
    stem = slug(audio_wav.stem) or "speech"
    person_slug = slug(person_id) or "talking-person"
    return {
        "normalized_audio": root / "outputs/speech" / f"{stem}_clean.wav",
        "rhubarb_json": root / "results/rhubarb" / f"{stem}_clean.json",
        "timeline": root / "outputs/lipsync" / f"{person_slug}_rhubarb.face.json",
        "manifest": root / "config" / f"person_factory.{person_slug}.json",
        "prepare_report": root / "results/talking_person" / f"{person_slug}.prepare.json",
        "batch_result": root / "results" / f"batch_person_factory_{person_slug}_latest.json",
        "gallery": root / "outputs/batch" / f"person_factory_{person_slug}.html",
        "finalize_summary": root / "results" / f"finalize_person_factory_{person_slug}_latest.json",
    }


def write_talking_person_artifacts(
    *,
    rhubarb_data: dict,
    timeline_path: Path,
    manifest_path: Path,
    report_path: Path,
    person_id: str,
    display_name: str,
    base_key: str,
    accessory_query: str,
    animation_preset: str,
    accessories: list[dict],
    root: Path = ROOT,
    intensity: float = 0.9,
    render_profile: str = "auto",
) -> dict:
    timeline = write_lipsync_timeline(timeline_path, rhubarb_data, intensity=intensity)
    return write_talking_person_artifacts_from_timeline(
        timeline_path=timeline_path,
        manifest_path=manifest_path,
        report_path=report_path,
        person_id=person_id,
        display_name=display_name,
        base_key=base_key,
        accessory_query=accessory_query,
        animation_preset=animation_preset,
        accessories=accessories,
        root=root,
        render_profile=render_profile,
        timeline=timeline,
        reused_lipsync=False,
        rhubarb_shape_count=timeline["source"]["mouthCue_count"],
    )


def write_talking_person_artifacts_from_timeline(
    *,
    timeline_path: Path,
    manifest_path: Path,
    report_path: Path,
    person_id: str,
    display_name: str,
    base_key: str,
    accessory_query: str,
    animation_preset: str,
    accessories: list[dict],
    root: Path = ROOT,
    render_profile: str = "auto",
    timeline: dict | None = None,
    reused_lipsync: bool = False,
    rhubarb_shape_count: int | None = None,
) -> dict:
    timeline = timeline or json.loads(timeline_path.read_text(encoding="utf-8"))
    manifest = build_single_person_manifest(
        person_id=person_id,
        display_name=display_name,
        base_key=base_key,
        accessory_query=accessory_query,
        animation_preset=animation_preset,
        lipsync_timeline_json=workspace_path(timeline_path, root=root),
        render_profile=render_profile,
        accessories=accessories,
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    report = {
        "schema": "vrm-person-factory.talking-person-prepare.v1",
        "person_id": person_id,
        "display_name": display_name,
        "manifest": str(manifest_path),
        "lipsync_timeline": str(timeline_path),
        "lipsync_timeline_json": workspace_path(timeline_path, root=root),
        "duration": timeline.get("duration", 0.0),
        "cue_count": len(timeline.get("cues", [])),
        "rhubarb_shape_count": rhubarb_shape_count,
        "reused_lipsync": reused_lipsync,
    }
    cache = cache_report(timeline_path, reused_lipsync=reused_lipsync, root=root)
    if cache:
        report["cache"] = cache
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def run_render_pipeline(args: argparse.Namespace, manifest_path: Path, paths: dict[str, Path]) -> None:
    run_checked(
        [
            "docker",
            "compose",
            "run",
            "--rm",
            "blender-vrm",
            "blender",
            "--background",
            "--python",
            "scripts/install_addons.py",
            "--python",
            "scripts/run_manifest_in_blender.py",
            "--",
            str(manifest_path.relative_to(ROOT) if manifest_path.is_relative_to(ROOT) else manifest_path),
            str(paths["batch_result"].relative_to(ROOT) if paths["batch_result"].is_relative_to(ROOT) else paths["batch_result"]),
        ]
    )
    finalize = [
        "python3",
        "scripts/finalize_batch.py",
        str(paths["batch_result"].relative_to(ROOT) if paths["batch_result"].is_relative_to(ROOT) else paths["batch_result"]),
        str(paths["gallery"].relative_to(ROOT) if paths["gallery"].is_relative_to(ROOT) else paths["gallery"]),
        "--summary-json",
        str(paths["finalize_summary"].relative_to(ROOT) if paths["finalize_summary"].is_relative_to(ROOT) else paths["finalize_summary"]),
        "--texture-size",
        str(args.texture_size),
    ]
    if not args.skip_godot_export:
        finalize.append("--export-godot")
    run_checked(finalize)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a talking-person manifest from speech audio via Rhubarb mouth cues.")
    parser.add_argument("audio_wav")
    parser.add_argument("--id", default="talking-person")
    parser.add_argument("--name", default="")
    parser.add_argument("--base", choices=[item["key"] for item in BASE_MODELS], default="female")
    parser.add_argument("--accessory", default="glasses")
    parser.add_argument("--animation", default="talk_idle")
    parser.add_argument("--asset-config", default="config/poly_pizza_assets.json")
    parser.add_argument("--rhubarb-bin", default=str(DEFAULT_RHUBARB_BIN.relative_to(ROOT)))
    parser.add_argument("--normalizer", choices=["auto", "docker", "local"], default="auto")
    parser.add_argument("--normalized-audio")
    parser.add_argument("--rhubarb-json")
    parser.add_argument("--timeline")
    parser.add_argument("--manifest")
    parser.add_argument("--prepare-report")
    parser.add_argument("--intensity", type=float, default=0.9)
    parser.add_argument("--render-profile", default="auto")
    parser.add_argument("--reuse-lipsync", action="store_true", help="Skip ffmpeg/Rhubarb when the target face timeline already exists.")
    parser.add_argument("--render", action="store_true", help="Run the existing Blender/finalize pipeline after preparing artifacts.")
    parser.add_argument("--texture-size", type=int, default=1024)
    parser.add_argument("--skip-godot-export", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Print planned commands and paths without running external tools.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    audio_path = local_path(args.audio_wav)
    paths = auto_paths(audio_path, args.id)
    if args.normalized_audio:
        paths["normalized_audio"] = local_path(args.normalized_audio)
    if args.rhubarb_json:
        paths["rhubarb_json"] = local_path(args.rhubarb_json)
    if args.timeline:
        paths["timeline"] = local_path(args.timeline)
    if args.manifest:
        paths["manifest"] = local_path(args.manifest)
    if args.prepare_report:
        paths["prepare_report"] = local_path(args.prepare_report)

    normalize_command = build_ffmpeg_normalize_command(audio_path, paths["normalized_audio"], mode=args.normalizer)
    rhubarb_command = build_rhubarb_command(args.rhubarb_bin, paths["normalized_audio"], paths["rhubarb_json"])
    plan = {
        "audio_wav": str(audio_path),
        "normalized_audio": str(paths["normalized_audio"]),
        "rhubarb_json": str(paths["rhubarb_json"]),
        "timeline": str(paths["timeline"]),
        "manifest": str(paths["manifest"]),
        "prepare_report": str(paths["prepare_report"]),
        "normalize_command": normalize_command,
        "rhubarb_command": rhubarb_command,
        "reuse_lipsync": args.reuse_lipsync,
        "render": args.render,
        "dry_run": args.dry_run,
    }
    if args.dry_run:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return

    accessories = load_accessories(local_path(args.asset_config))
    if should_run_lipsync_alignment(paths["timeline"], reuse_lipsync=args.reuse_lipsync):
        paths["normalized_audio"].parent.mkdir(parents=True, exist_ok=True)
        paths["rhubarb_json"].parent.mkdir(parents=True, exist_ok=True)
        run_checked(normalize_command)
        run_checked(rhubarb_command)
        rhubarb_data = json.loads(paths["rhubarb_json"].read_text(encoding="utf-8"))
        report = write_talking_person_artifacts(
            rhubarb_data=rhubarb_data,
            timeline_path=paths["timeline"],
            manifest_path=paths["manifest"],
            report_path=paths["prepare_report"],
            person_id=args.id,
            display_name=args.name or args.id.replace("-", " ").title(),
            base_key=args.base,
            accessory_query=args.accessory,
            animation_preset=args.animation,
            accessories=accessories,
            intensity=args.intensity,
            render_profile=args.render_profile,
        )
    else:
        report = write_talking_person_artifacts_from_timeline(
            timeline_path=paths["timeline"],
            manifest_path=paths["manifest"],
            report_path=paths["prepare_report"],
            person_id=args.id,
            display_name=args.name or args.id.replace("-", " ").title(),
            base_key=args.base,
            accessory_query=args.accessory,
            animation_preset=args.animation,
            accessories=accessories,
            render_profile=args.render_profile,
            reused_lipsync=True,
        )
    if args.render:
        run_render_pipeline(args, paths["manifest"], paths)
    print(json.dumps({**plan, **report}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
