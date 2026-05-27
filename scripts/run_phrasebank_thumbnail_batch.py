#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.make_person_manifest import slug


DEFAULT_PHRASE_BANK = "config/lipsync_phrase_bank.full_viseme.json"
DEFAULT_ACCESSORIES = "aviator,pirate,cowboy,necklace,necktie"
DEFAULT_BASES = "female,male"
DEFAULT_ANIMATIONS = "talk_idle,present_explain,confident_point,listening_nod"
DEFAULT_RENDER_PROFILE = "thumbnail_lipsync"
DEFAULT_GODOT_URL = "http://127.0.0.1:8790"


def load_phrasebank_cache_lines(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    lines = payload.get("cache_lines", [])
    if not isinstance(lines, list) or not lines:
        raise ValueError(f"phrase bank has no cache_lines: {path}")
    output = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        text = str(line.get("text") or "").strip()
        audio_cache_key = str(line.get("audio_cache_key") or "").strip()
        lipsync_timeline = str(line.get("lipsync_timeline") or "").strip()
        if text and audio_cache_key and lipsync_timeline:
            output.append(
                {
                    "audio_cache_key": audio_cache_key,
                    "lipsync_timeline": lipsync_timeline,
                    "text": text,
                }
            )
    if not output:
        raise ValueError(f"phrase bank has no complete cache lines: {path}")
    return output


def default_batch_id(count: int) -> str:
    return f"thumb-prod-{count:03d}-{slug(__import__('datetime').datetime.now().strftime('%H%M%S'))}"


def build_phrasebank_thumbnail_command(
    *,
    batch_id: str,
    count: int,
    cache_lines: list[dict],
    accessories: str = DEFAULT_ACCESSORIES,
    bases: str = DEFAULT_BASES,
    animations: str = DEFAULT_ANIMATIONS,
    render_profile: str = DEFAULT_RENDER_PROFILE,
    texture_size: int = 768,
    optimization_profile: str = "auto",
    godot_url: str = DEFAULT_GODOT_URL,
    validation_urls: str = "",
    start_index: int = 1,
    skip_combined_refresh: bool = True,
) -> list[str]:
    if count < 1:
        raise ValueError("count must be at least 1")
    if not cache_lines:
        raise ValueError("at least one cache line is required")
    first = cache_lines[0]
    command = [
        "python3",
        "scripts/run_cached_lipsync_batch.py",
        "--batch-id",
        batch_id,
        "--count",
        str(count),
        "--accessories",
        accessories,
        "--bases",
        bases,
        "--animations",
        animations,
        "--text",
        str(first["text"]),
        "--audio-cache-key",
        str(first["audio_cache_key"]),
        "--lipsync-timeline",
        str(first["lipsync_timeline"]),
        "--cache-lines-json",
        json.dumps(cache_lines, separators=(",", ":")),
        "--render-profile",
        render_profile,
        "--texture-size",
        str(texture_size),
        "--optimization-profile",
        optimization_profile,
        "--start-index",
        str(start_index),
        "--godot-url",
        godot_url,
        "--gallery-detail-mode",
        "compact" if skip_combined_refresh else "full",
    ]
    if validation_urls:
        command.extend(["--validation-urls", validation_urls])
    if skip_combined_refresh:
        command.append("--skip-combined-refresh")
    return command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the current best fast-review thumbnail lip-sync batch preset."
    )
    parser.add_argument("--batch-id", default="")
    parser.add_argument("--count", type=int, default=16)
    parser.add_argument("--phrase-bank", default=DEFAULT_PHRASE_BANK)
    parser.add_argument("--accessories", default=DEFAULT_ACCESSORIES)
    parser.add_argument("--bases", default=DEFAULT_BASES)
    parser.add_argument("--animations", default=DEFAULT_ANIMATIONS)
    parser.add_argument("--render-profile", default=DEFAULT_RENDER_PROFILE)
    parser.add_argument("--texture-size", type=int, default=768)
    parser.add_argument("--optimization-profile", choices=["auto", "standard", "rough_preview"], default="auto")
    parser.add_argument("--godot-url", default=DEFAULT_GODOT_URL)
    parser.add_argument("--validation-urls", default="")
    parser.add_argument("--start-index", type=int, default=1)
    parser.add_argument("--publish-combined", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cache_lines = load_phrasebank_cache_lines(ROOT / args.phrase_bank)
    batch_id = args.batch_id.strip() or default_batch_id(args.count)
    command = build_phrasebank_thumbnail_command(
        batch_id=batch_id,
        count=args.count,
        cache_lines=cache_lines,
        accessories=args.accessories,
        bases=args.bases,
        animations=args.animations,
        render_profile=args.render_profile,
        texture_size=args.texture_size,
        optimization_profile=args.optimization_profile,
        godot_url=args.godot_url,
        validation_urls=args.validation_urls,
        start_index=args.start_index,
        skip_combined_refresh=not args.publish_combined,
    )
    if args.dry_run:
        print(json.dumps({"batch_id": batch_id, "command": command}, indent=2, sort_keys=True))
        return
    completed = subprocess.run(command, cwd=ROOT, text=True)
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
