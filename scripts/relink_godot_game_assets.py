from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def same_file(path_a: Path, path_b: Path) -> bool:
    try:
        return path_a.samefile(path_b)
    except FileNotFoundError:
        return False


def relink_one(source: Path, target: Path, *, apply: bool) -> dict[str, Any]:
    item = {
        "source": str(source),
        "target": str(target),
        "bytes": target.stat().st_size if target.exists() else 0,
    }
    if not source.exists():
        return {**item, "status": "skipped", "reason": "missing-source"}
    if not target.exists():
        return {**item, "status": "skipped", "reason": "missing-target"}
    if same_file(source, target):
        return {**item, "status": "skipped", "reason": "already-linked"}
    if source.stat().st_size != target.stat().st_size:
        return {**item, "status": "skipped", "reason": "size-mismatch"}
    if file_sha256(source) != file_sha256(target):
        return {**item, "status": "skipped", "reason": "sha256-mismatch"}
    if not apply:
        return {**item, "status": "dry-run"}

    target.unlink()
    os.link(source, target)
    return {**item, "status": "linked"}


def relink_game_assets(
    *,
    root: Path = ROOT,
    apply: bool = False,
    optimized_dir: str = "outputs/batch_optimized",
    game_glb_dir: str = "godot_viewer/game_assets/glb",
) -> dict[str, Any]:
    optimized_root = root / optimized_dir
    game_root = root / game_glb_dir
    results = []
    if game_root.exists():
        for target in sorted(game_root.glob("*.glb")):
            source = optimized_root / target.name
            results.append(relink_one(source, target, apply=apply))

    linked = [item for item in results if item["status"] == "linked"]
    dry_run = [item for item in results if item["status"] == "dry-run"]
    skipped = [item for item in results if item["status"] == "skipped"]
    return {
        "status": "ok",
        "apply": apply,
        "optimized_dir": str(optimized_root),
        "game_glb_dir": str(game_root),
        "candidate_count": len(results),
        "linked_count": len(linked),
        "dry_run_count": len(dry_run),
        "skipped_count": len(skipped),
        "linked_bytes": sum(int(item.get("bytes") or 0) for item in linked),
        "dry_run_bytes": sum(int(item.get("bytes") or 0) for item in dry_run),
        "skipped_reasons": {
            reason: sum(1 for item in skipped if item.get("reason") == reason)
            for reason in sorted({str(item.get("reason", "")) for item in skipped})
        },
        "linked": linked,
        "dry_run": dry_run,
        "skipped": skipped,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Relink existing Godot exported GLBs to identical optimized GLBs.")
    parser.add_argument("--apply", action="store_true", help="Replace verified duplicate files with hardlinks.")
    parser.add_argument("--report-json", default="results/relink_godot_game_assets_latest.json")
    parser.add_argument("--optimized-dir", default="outputs/batch_optimized")
    parser.add_argument("--game-glb-dir", default="godot_viewer/game_assets/glb")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = relink_game_assets(
        apply=args.apply,
        optimized_dir=args.optimized_dir,
        game_glb_dir=args.game_glb_dir,
    )
    report_path = ROOT / args.report_json
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
