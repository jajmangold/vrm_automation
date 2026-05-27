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


def render_cache_index(cache_dir: Path) -> dict[tuple[int, str], Path]:
    indexed = {}
    if not cache_dir.exists():
        return indexed
    for path in sorted(cache_dir.glob("*.glb")):
        indexed[(path.stat().st_size, file_sha256(path))] = path
    return indexed


def relink_one(target: Path, cache: Path | None, *, apply: bool) -> dict[str, Any]:
    item = {"target": str(target), "bytes": target.stat().st_size}
    if cache is None:
        return {**item, "status": "skipped", "reason": "no-matching-cache"}
    item["source"] = str(cache)
    if same_file(cache, target):
        return {**item, "status": "skipped", "reason": "already-linked"}
    if not apply:
        return {**item, "status": "dry-run"}
    target.unlink()
    os.link(cache, target)
    return {**item, "status": "linked"}


def relink_render_cache_outputs(
    *,
    root: Path = ROOT,
    apply: bool = False,
    batch_dir: str = "outputs/batch",
    cache_dir: str = "outputs/render_cache",
) -> dict[str, Any]:
    batch_root = root / batch_dir
    cache_root = root / cache_dir
    cache_by_hash = render_cache_index(cache_root)
    results = []
    if batch_root.exists():
        for target in sorted(batch_root.glob("*.glb")):
            key = (target.stat().st_size, file_sha256(target))
            results.append(relink_one(target, cache_by_hash.get(key), apply=apply))

    linked = [item for item in results if item["status"] == "linked"]
    dry_run = [item for item in results if item["status"] == "dry-run"]
    skipped = [item for item in results if item["status"] == "skipped"]
    return {
        "status": "ok",
        "apply": apply,
        "batch_dir": str(batch_root),
        "cache_dir": str(cache_root),
        "cache_count": len(cache_by_hash),
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
    parser = argparse.ArgumentParser(description="Relink raw batch GLBs to identical render-cache GLBs.")
    parser.add_argument("--apply", action="store_true", help="Replace verified duplicate files with hardlinks.")
    parser.add_argument("--report-json", default="results/relink_render_cache_outputs_latest.json")
    parser.add_argument("--batch-dir", default="outputs/batch")
    parser.add_argument("--cache-dir", default="outputs/render_cache")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = relink_render_cache_outputs(apply=args.apply, batch_dir=args.batch_dir, cache_dir=args.cache_dir)
    report_path = ROOT / args.report_json
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
