from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.make_person_manifest import load_accessories, slug


DEFAULT_ANIMATIONS = ["talk_idle", "present_explain", "listening_nod", "confident_point"]
DEFAULT_BASES = ["female", "male"]


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value).split(",") if item.strip()]


def title_words(value: str) -> str:
    return " ".join(part.capitalize() for part in slug(value).split("-"))


def matching_accessories(accessories: list[dict[str, Any]], queries: list[str]) -> list[dict[str, Any]]:
    matches = []
    for query in queries:
        wanted = slug(query)
        for accessory in accessories:
            values = [
                accessory.get("key", ""),
                accessory.get("title", ""),
                accessory.get("role", ""),
                " ".join(accessory.get("tags", [])),
            ]
            if any(wanted == slug(value) or wanted in slug(value) for value in values):
                if accessory not in matches:
                    matches.append(accessory)
                break
    return matches


def build_requests(
    *,
    batch_id: str,
    count: int,
    accessories: list[dict[str, Any]],
    accessory_queries: list[str],
    bases: list[str],
    animations: list[str],
    text: str,
    audio_cache_key: str,
    lipsync_timeline: str,
    render_profile: str,
    start_index: int = 1,
    cache_lines: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    selected_accessories = matching_accessories(accessories, accessory_queries)
    if not selected_accessories:
        raise ValueError("no accessories matched")
    if not bases:
        raise ValueError("at least one base is required")
    if not animations:
        raise ValueError("at least one animation is required")
    if count < 1:
        raise ValueError("count must be at least 1")

    requests = []
    line_cycle = cache_lines or [
        {
            "text": text,
            "audio_cache_key": audio_cache_key,
            "lipsync_timeline": lipsync_timeline,
        }
    ]
    for offset in range(count):
        sequence = start_index + offset
        accessory = selected_accessories[offset % len(selected_accessories)]
        base = bases[(offset // len(selected_accessories)) % len(bases)]
        animation = animations[offset % len(animations)]
        line = line_cycle[offset % len(line_cycle)]
        requests.append(
            {
                "id": f"{batch_id}-{sequence:03d}",
                "name": f"{title_words(batch_id)} {sequence:03d} {title_words(base)} {title_words(accessory['key'])} {title_words(animation)}",
                "base": base,
                "accessory": accessory["key"],
                "animation": animation,
                "render_profile": render_profile,
                "text": str(line.get("text") or text),
                "audio_cache_key": str(line.get("audio_cache_key") or audio_cache_key),
                "lipsync_timeline": str(line.get("lipsync_timeline") or lipsync_timeline),
            }
        )
    return requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build cached lip-sync request JSON for render_matrix_batch.py.")
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--asset-config", default="config/poly_pizza_assets.json")
    parser.add_argument("--accessories", default="aviator,pirate,necktie,cowboy,necklace")
    parser.add_argument("--bases", default=",".join(DEFAULT_BASES))
    parser.add_argument("--animations", default=",".join(DEFAULT_ANIMATIONS))
    parser.add_argument("--text", required=True)
    parser.add_argument("--audio-cache-key", required=True)
    parser.add_argument("--lipsync-timeline", required=True)
    parser.add_argument("--cache-lines-json", default="")
    parser.add_argument("--render-profile", default="fast_lipsync")
    parser.add_argument("--start-index", type=int, default=1)
    parser.add_argument("--include-review", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    include_qualities = {"ship", "review", "fix"} if args.include_review else {"ship"}
    accessories = load_accessories(ROOT / args.asset_config, include_qualities=include_qualities)
    cache_lines = json.loads(args.cache_lines_json) if args.cache_lines_json else None
    requests = build_requests(
        batch_id=args.batch_id,
        count=args.count,
        accessories=accessories,
        accessory_queries=parse_csv(args.accessories),
        bases=parse_csv(args.bases),
        animations=parse_csv(args.animations),
        text=args.text,
        audio_cache_key=args.audio_cache_key,
        lipsync_timeline=args.lipsync_timeline,
        render_profile=args.render_profile,
        start_index=args.start_index,
        cache_lines=cache_lines,
    )
    output = {"requests": requests}
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "path": str(output_path),
                "request_count": len(requests),
                "batch_id": args.batch_id,
                "include_qualities": sorted(include_qualities),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
