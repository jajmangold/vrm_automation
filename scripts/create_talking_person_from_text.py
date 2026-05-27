from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.create_talking_person import ROOT, local_path
from scripts.make_person_manifest import BASE_MODELS, slug


def repo_arg(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def auto_text_paths(person_id: str, root: Path = ROOT) -> dict[str, Path]:
    person_slug = slug(person_id) or "talking-person"
    return {
        "audio_wav": root / "outputs/speech" / f"{person_slug}.wav",
        "audio_manifest": root / "results/musetalk" / f"{person_slug}_audio.json",
        "report": root / "results/talking_person" / f"{person_slug}.text.json",
    }


def build_generate_speech_command(
    *,
    text: str,
    audio_wav: Path,
    audio_manifest: Path,
    clip_id: str,
    service: str,
    voice: str,
    seed: int,
    language: str,
    services_config: str,
) -> list[str]:
    command = [
        "python3",
        "scripts/generate_speech.py",
        text,
        repo_arg(audio_wav),
        "--services",
        services_config,
        "--service",
        service,
        "--clip-id",
        clip_id,
        "--manifest",
        repo_arg(audio_manifest),
        "--seed",
        str(seed),
        "--language",
        language,
    ]
    if voice:
        command.extend(["--voice", voice])
    return command


def build_create_talking_person_command(
    *,
    audio_wav: Path,
    person_id: str,
    name: str,
    base: str,
    accessory: str,
    animation: str,
    render: bool,
    normalizer: str,
    intensity: float = 0.9,
    render_profile: str = "auto",
    normalized_audio: Path | None = None,
    rhubarb_json: Path | None = None,
    lipsync_timeline: Path | None = None,
    reuse_lipsync: bool = False,
    skip_godot_export: bool = False,
) -> list[str]:
    command = [
        "python3",
        "scripts/create_talking_person.py",
        repo_arg(audio_wav),
        "--id",
        person_id,
        "--name",
        name or person_id.replace("-", " ").title(),
        "--base",
        base,
        "--accessory",
        accessory,
        "--animation",
        animation,
        "--normalizer",
        normalizer,
        "--intensity",
        str(intensity),
        "--render-profile",
        render_profile,
    ]
    if normalized_audio:
        command.extend(["--normalized-audio", repo_arg(normalized_audio)])
    if rhubarb_json:
        command.extend(["--rhubarb-json", repo_arg(rhubarb_json)])
    if lipsync_timeline:
        command.extend(["--timeline", repo_arg(lipsync_timeline)])
    if render:
        command.append("--render")
    if reuse_lipsync:
        command.append("--reuse-lipsync")
    if skip_godot_export:
        command.append("--skip-godot-export")
    return command


def should_generate_audio(audio_wav: Path, *, reuse_audio: bool = False) -> bool:
    return not (reuse_audio and audio_wav.exists())


def write_text_talking_person_report(
    path: Path,
    *,
    person_id: str,
    text: str,
    audio_wav: Path,
    audio_manifest: Path,
    generate_speech_command: list[str],
    create_talking_person_command: list[str],
    render: bool,
    reused_audio: bool = False,
    audio_cache_key: str = "",
    cache_paths: dict[str, str] | None = None,
) -> dict:
    report = {
        "schema": "vrm-person-factory.text-talking-person.v1",
        "person_id": person_id,
        "text": text,
        "audio_wav": str(audio_wav),
        "audio_manifest": str(audio_manifest),
        "generate_speech_command": generate_speech_command,
        "create_talking_person_command": create_talking_person_command,
        "render": render,
        "reused_audio": reused_audio,
    }
    if audio_cache_key:
        report["audio_cache_key"] = audio_cache_key
    if cache_paths:
        report["cache_paths"] = cache_paths
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def run_checked(command: list[str]) -> None:
    completed = subprocess.run(command, cwd=ROOT, text=True)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a talking generated person directly from text.")
    parser.add_argument("text")
    parser.add_argument("--id", default="text-talking-person")
    parser.add_argument("--name", default="")
    parser.add_argument("--base", choices=[item["key"] for item in BASE_MODELS], default="female")
    parser.add_argument("--accessory", default="glasses")
    parser.add_argument("--animation", default="talk_idle")
    parser.add_argument("--services", default="config/speech_services.example.json")
    parser.add_argument("--tts-service", default="voice_design")
    parser.add_argument("--voice", default="warm clear presenter voice")
    parser.add_argument("--seed", type=int, default=-1)
    parser.add_argument("--language", default="English")
    parser.add_argument("--normalizer", choices=["auto", "docker", "local"], default="auto")
    parser.add_argument("--intensity", type=float, default=0.9)
    parser.add_argument("--render-profile", default="auto")
    parser.add_argument("--audio-wav")
    parser.add_argument("--audio-manifest")
    parser.add_argument("--normalized-audio")
    parser.add_argument("--rhubarb-json")
    parser.add_argument("--lipsync-timeline", "--timeline", dest="lipsync_timeline")
    parser.add_argument("--audio-cache-key")
    parser.add_argument("--report")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--reuse-audio", action="store_true", help="Skip TTS when the target WAV already exists.")
    parser.add_argument("--reuse-lipsync", action="store_true", help="Skip ffmpeg/Rhubarb when the target face timeline already exists.")
    parser.add_argument("--skip-godot-export", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    paths = auto_text_paths(args.id)
    if args.audio_wav:
        paths["audio_wav"] = ROOT / args.audio_wav if not Path(args.audio_wav).is_absolute() else Path(args.audio_wav)
    if args.audio_manifest:
        paths["audio_manifest"] = ROOT / args.audio_manifest if not Path(args.audio_manifest).is_absolute() else Path(args.audio_manifest)
    if args.report:
        paths["report"] = ROOT / args.report if not Path(args.report).is_absolute() else Path(args.report)
    cache_paths = {}
    for key in ("audio_wav", "audio_manifest", "normalized_audio", "rhubarb_json", "lipsync_timeline"):
        value = getattr(args, key, None)
        if value:
            cache_paths[key] = value

    generate_command = build_generate_speech_command(
        text=args.text,
        audio_wav=paths["audio_wav"],
        audio_manifest=paths["audio_manifest"],
        clip_id=args.id,
        service=args.tts_service,
        voice=args.voice,
        seed=args.seed,
        language=args.language,
        services_config=args.services,
    )
    create_command = build_create_talking_person_command(
        audio_wav=paths["audio_wav"],
        person_id=args.id,
        name=args.name or args.id.replace("-", " ").title(),
        base=args.base,
        accessory=args.accessory,
        animation=args.animation,
        render=args.render,
        normalizer=args.normalizer,
        intensity=args.intensity,
        render_profile=args.render_profile,
        normalized_audio=local_path(args.normalized_audio) if args.normalized_audio else None,
        rhubarb_json=local_path(args.rhubarb_json) if args.rhubarb_json else None,
        lipsync_timeline=local_path(args.lipsync_timeline) if args.lipsync_timeline else None,
        reuse_lipsync=args.reuse_lipsync,
        skip_godot_export=args.skip_godot_export,
    )
    report = write_text_talking_person_report(
        paths["report"],
        person_id=args.id,
        text=args.text,
        audio_wav=paths["audio_wav"],
        audio_manifest=paths["audio_manifest"],
        generate_speech_command=generate_command,
        create_talking_person_command=create_command,
        render=args.render,
        reused_audio=not should_generate_audio(paths["audio_wav"], reuse_audio=args.reuse_audio),
        audio_cache_key=args.audio_cache_key or "",
        cache_paths=cache_paths,
    )
    if not args.dry_run:
        if should_generate_audio(paths["audio_wav"], reuse_audio=args.reuse_audio):
            run_checked(generate_command)
        run_checked(create_command)
    print(json.dumps({**report, "dry_run": args.dry_run}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
