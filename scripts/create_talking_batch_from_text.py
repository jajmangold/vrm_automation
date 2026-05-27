from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.create_talking_person import ROOT
from scripts.create_talking_person_from_text import repo_arg
from scripts.make_person_manifest import slug


DEFAULT_PERSON = {
    "base": "female",
    "accessory": "glasses",
    "animation": "talk_idle",
    "tts_service": "voice_design",
    "voice": "warm clear presenter voice",
    "seed": -1,
    "language": "English",
    "normalizer": "auto",
    "intensity": 0.9,
    "render_profile": "auto",
    "reuse_audio": False,
    "reuse_lipsync": False,
}


def title_from_id(person_id: str) -> str:
    return person_id.replace("-", " ").replace("_", " ").title()


def merge_person_spec(defaults: dict, person: dict) -> dict:
    merged = {**DEFAULT_PERSON, **defaults, **person}
    if not merged.get("id"):
        raise ValueError("each person requires an id")
    if not merged.get("text"):
        raise ValueError(f"{merged['id']} requires text")
    merged["name"] = merged.get("name") or title_from_id(merged["id"])
    return merged


def auto_batch_paths(batch_id: str, root: Path = ROOT) -> dict[str, Path]:
    batch_slug = slug(batch_id) or "text-batch"
    return {
        "manifest": root / "config" / f"person_factory.{batch_slug}.json",
        "batch_result": root / "results" / f"batch_person_factory_{batch_slug}_latest.json",
        "gallery": root / "outputs/batch" / f"person_factory_{batch_slug}.html",
        "finalize_summary": root / "results" / f"finalize_person_factory_{batch_slug}_latest.json",
        "report": root / "results/talking_person" / f"{batch_slug}.batch_text.json",
    }


def person_manifest_path(person_id: str, root: Path = ROOT) -> Path:
    return root / "config" / f"person_factory.{slug(person_id)}.json"


def build_prepare_person_command(spec: dict, *, services_config: str) -> list[str]:
    command = [
        "python3",
        "scripts/create_talking_person_from_text.py",
        spec["text"],
        "--id",
        spec["id"],
        "--name",
        spec["name"],
        "--base",
        spec["base"],
        "--accessory",
        spec["accessory"],
        "--animation",
        spec["animation"],
        "--services",
        services_config,
        "--tts-service",
        spec["tts_service"],
        "--seed",
        str(spec["seed"]),
        "--language",
        spec["language"],
        "--normalizer",
        spec["normalizer"],
        "--intensity",
        str(spec["intensity"]),
        "--render-profile",
        spec["render_profile"],
    ]
    if spec.get("voice"):
        command.extend(["--voice", spec["voice"]])
    if spec.get("reuse_audio"):
        command.append("--reuse-audio")
    if spec.get("reuse_lipsync"):
        command.append("--reuse-lipsync")
    return command


def combine_person_manifests(manifest_paths: list[Path], *, batch_defaults: dict | None = None) -> dict:
    if not manifest_paths:
        raise ValueError("at least one person manifest is required")
    jobs = []
    combined_defaults = {}
    for index, path in enumerate(manifest_paths):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if index == 0:
            combined_defaults.update(manifest.get("defaults", {}))
        jobs.extend(manifest.get("jobs", []))
    combined_defaults.setdefault("cache_base_scenes", "1")
    combined_defaults.update(batch_defaults or {})
    return {"defaults": combined_defaults, "jobs": jobs}


def build_manifest_render_command(manifest_path: Path, batch_result_path: Path) -> list[str]:
    return [
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
        repo_arg(manifest_path),
        repo_arg(batch_result_path),
    ]


def build_finalize_command(
    batch_result_path: Path,
    gallery_path: Path,
    summary_path: Path,
    *,
    texture_size: int = 1024,
    export_godot: bool = True,
) -> list[str]:
    command = [
        "python3",
        "scripts/finalize_batch.py",
        repo_arg(batch_result_path),
        repo_arg(gallery_path),
        "--summary-json",
        repo_arg(summary_path),
        "--texture-size",
        str(texture_size),
    ]
    if export_godot:
        command.append("--export-godot")
    return command


def run_checked(command: list[str]) -> None:
    completed = subprocess.run(command, cwd=ROOT, text=True)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def load_batch_config(path: Path) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    people = config.get("people", config.get("persons", []))
    if not people:
        raise ValueError("batch config requires a people array")
    return {"defaults": config.get("defaults", {}), "people": people}


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a batched set of talking generated people from text prompts.")
    parser.add_argument("config")
    parser.add_argument("--batch-id", default="")
    parser.add_argument("--services", default="config/speech_services.example.json")
    parser.add_argument("--texture-size", type=int, default=1024)
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--skip-godot-export", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    config_path = Path(args.config)
    batch = load_batch_config(config_path)
    batch_id = args.batch_id or batch["defaults"].get("batch_id") or config_path.stem
    paths = auto_batch_paths(batch_id)
    specs = [merge_person_spec(batch["defaults"], person) for person in batch["people"]]
    prepare_commands = [build_prepare_person_command(spec, services_config=args.services) for spec in specs]
    manifest_paths = [person_manifest_path(spec["id"]) for spec in specs]
    render_command = build_manifest_render_command(paths["manifest"], paths["batch_result"])
    finalize_command = build_finalize_command(
        paths["batch_result"],
        paths["gallery"],
        paths["finalize_summary"],
        texture_size=args.texture_size,
        export_godot=not args.skip_godot_export,
    )

    report = {
        "schema": "vrm-person-factory.text-talking-batch.v1",
        "batch_id": batch_id,
        "config": str(config_path),
        "people": [spec["id"] for spec in specs],
        "manifest": str(paths["manifest"]),
        "batch_result": str(paths["batch_result"]),
        "gallery": str(paths["gallery"]),
        "prepare_commands": prepare_commands,
        "render_command": render_command,
        "finalize_command": finalize_command,
        "render": args.render,
        "dry_run": args.dry_run,
    }
    write_report(paths["report"], report)
    if args.dry_run:
        print(json.dumps(report, indent=2, sort_keys=True))
        return

    for command in prepare_commands:
        run_checked(command)
    combined = combine_person_manifests(manifest_paths, batch_defaults=batch["defaults"].get("batch_manifest_defaults", {}))
    paths["manifest"].parent.mkdir(parents=True, exist_ok=True)
    paths["manifest"].write_text(json.dumps(combined, indent=2, sort_keys=True), encoding="utf-8")
    if args.render:
        run_checked(render_command)
        run_checked(finalize_command)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
