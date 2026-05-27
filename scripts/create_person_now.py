from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.make_person_manifest import ANIMATIONS, BASE_MODELS, load_accessories, render_angles_for_category, slug
from scripts.facial_presets import facial_preset_for_animation
from scripts.render_profiles import render_defaults


ROOT = Path(__file__).resolve().parents[1]


class OutputLockError(RuntimeError):
    pass


class OutputLock:
    def __init__(self, lock_path: Path, person_id: str):
        self.lock_path = lock_path
        self.person_id = person_id
        self._handle = None

    def __enter__(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.lock_path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._handle.close()
            self._handle = None
            raise OutputLockError(f"person id is already being generated: {self.person_id}") from exc
        self._handle.seek(0)
        self._handle.truncate()
        json.dump(
            {
                "person_id": self.person_id,
                "pid": os.getpid(),
                "locked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            self._handle,
            sort_keys=True,
        )
        self._handle.write("\n")
        self._handle.flush()
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._handle:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None


def output_lock_path(lock_dir: Path, person_id: str) -> Path:
    return lock_dir / f"{slug(person_id) or 'person'}.lock"


def acquire_output_lock(lock_path: Path, person_id: str) -> OutputLock:
    return OutputLock(lock_path, person_id)


def choose_accessory(accessories: list[dict], query: str) -> dict:
    wanted = slug(query)
    for accessory in accessories:
        values = [
            accessory.get("key", ""),
            accessory.get("title", ""),
            accessory.get("role", ""),
            " ".join(accessory.get("tags", [])),
        ]
        if any(wanted == slug(value) or wanted in slug(value) for value in values):
            return accessory
    raise ValueError(f"unknown accessory: {query}")


def choose_animation(preset: str) -> dict:
    for animation in ANIMATIONS:
        if animation["preset"] == preset:
            return animation
    raise ValueError(f"unknown animation preset: {preset}")


def choose_base(base_key: str) -> dict:
    for base_model in BASE_MODELS:
        if base_model["key"] == base_key:
            return base_model
    raise ValueError(f"unknown base model key: {base_key}")


def build_single_person_manifest(
    *,
    person_id: str,
    display_name: str,
    base_key: str,
    accessory_query: str,
    animation_preset: str,
    lipsync_timeline_json: str = "",
    render_profile: str = "auto",
    accessories: list[dict],
) -> dict:
    accessory = choose_accessory(accessories, accessory_query)
    animation = choose_animation(animation_preset)
    base_model = choose_base(base_key)
    facial_preset = facial_preset_for_animation(animation["preset"])
    tags = [
        "generated",
        "controllable",
        "instant",
        *base_model["tags"],
        *accessory["tags"],
        *animation["tags"],
        f"face:{facial_preset.replace('_', '-')}",
    ]
    if lipsync_timeline_json:
        tags.extend(["lip-sync", "vrm-visemes"])
    job = {
        "id": person_id,
        "display_name": display_name,
        "persona": f"{accessory['role']} character who {animation['verb']} on command",
        "model_path": base_model["model_path"],
        "outfit_model": accessory["outfit_model"],
        "category": accessory["category"],
        "animation_preset": animation["preset"],
        "facial_preset": facial_preset,
        "license": accessory.get("license"),
        "source_url": accessory.get("source_url"),
        "creator": accessory.get("creator"),
        "tags": tags,
        "notes": f"Instant generated person: {accessory['key']} accessory with {animation['preset']} motion.",
    }
    if lipsync_timeline_json:
        job["lipsync_timeline_json"] = lipsync_timeline_json
    render_settings = render_defaults(render_profile, has_lipsync=bool(lipsync_timeline_json))
    if accessory["category"] == "torso_back":
        job["render_angles"] = render_angles_for_category(accessory["category"])
    for key, value in accessory.get("fit_overrides", {}).items():
        job[f"outfit_{key}"] = value
    return {
        "defaults": {
            **render_settings,
            "render_pose_stills": render_settings.get("render_pose_stills", "1"),
            "export_blend": "0",
            "export_glb": "1",
            "export_vrm": "0",
            "cache_base_scenes": "1",
        },
        "jobs": [job],
    }


def run_command(command: list[str]) -> None:
    completed = subprocess.run(command, cwd=ROOT, text=True)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create and finalize one controllable person quickly.")
    parser.add_argument("--id", default="now-person")
    parser.add_argument("--name", default="Now Person")
    parser.add_argument("--base", choices=[item["key"] for item in BASE_MODELS], default="female")
    parser.add_argument("--accessory", default="glasses")
    parser.add_argument("--animation", default="talk_idle")
    parser.add_argument("--lipsync", default="/workspace/outputs/lipsync/person_factory_hello.face.json")
    parser.add_argument("--render-profile", default="auto")
    parser.add_argument("--asset-config", default="config/poly_pizza_assets.json")
    parser.add_argument("--manifest", default="config/person_factory.now.json")
    parser.add_argument("--result", default="results/batch_person_factory_now_latest.json")
    parser.add_argument("--gallery", default="outputs/batch/person_factory_now.html")
    parser.add_argument("--summary-json", default="results/finalize_person_factory_now_latest.json")
    parser.add_argument("--texture-size", type=int, default=1024)
    parser.add_argument("--lock-dir", default="results/locks")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-godot-export", action="store_true")
    return parser.parse_args()


def create_person(args: argparse.Namespace) -> None:
    accessories = load_accessories(ROOT / args.asset_config)
    manifest = build_single_person_manifest(
        person_id=args.id,
        display_name=args.name,
        base_key=args.base,
        accessory_query=args.accessory,
        animation_preset=args.animation,
        lipsync_timeline_json=args.lipsync,
        render_profile=args.render_profile,
        accessories=accessories,
    )
    manifest_path = ROOT / args.manifest
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"manifest": args.manifest, "job_id": args.id, "dry_run": args.dry_run}, indent=2))
    if args.dry_run:
        return

    run_command(
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
            args.manifest,
            args.result,
        ]
    )
    finalize = [
        "python3",
        "scripts/finalize_batch.py",
        args.result,
        args.gallery,
        "--summary-json",
        args.summary_json,
        "--texture-size",
        str(args.texture_size),
    ]
    if not args.skip_godot_export:
        finalize.append("--export-godot")
    run_command(finalize)


def main() -> None:
    args = parse_args()
    lock_path = output_lock_path(ROOT / args.lock_dir, args.id)
    try:
        with acquire_output_lock(lock_path, args.id):
            create_person(args)
    except OutputLockError as exc:
        print(json.dumps({"status": "locked", "job_id": args.id, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        raise SystemExit(75) from exc


if __name__ == "__main__":
    main()
