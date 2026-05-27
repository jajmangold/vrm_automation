from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GLB_DIRS = (
    "outputs/batch",
    "outputs/render_cache",
    "outputs/batch_optimized",
    "godot_viewer/game_assets/glb",
)
CLEANUP_REPORTS = {
    "render_cache_outputs": "results/relink_render_cache_outputs_latest.json",
    "godot_game_assets": "results/relink_godot_game_assets_latest.json",
}


def human_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    number = float(value)
    for unit in units:
        if number < 1024.0 or unit == units[-1]:
            return f"{number:.1f}{unit}" if unit != "B" else f"{int(number)}B"
        number /= 1024.0
    return f"{value}B"


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def summarize_glbs(path: Path) -> dict[str, Any]:
    files = sorted(path.glob("*.glb")) if path.exists() else []
    apparent = 0
    actual = 0
    seen_inodes = set()
    largest = []
    for file_path in files:
        stat = file_path.stat()
        apparent += stat.st_size
        inode_key = (stat.st_dev, stat.st_ino)
        if inode_key not in seen_inodes:
            seen_inodes.add(inode_key)
            actual += stat.st_size
        largest.append(
            {
                "path": str(file_path),
                "bytes": stat.st_size,
                "links": stat.st_nlink,
            }
        )
    largest.sort(key=lambda item: item["bytes"], reverse=True)
    saved = max(0, apparent - actual)
    return {
        "path": str(path),
        "file_count": len(files),
        "unique_inode_count": len(seen_inodes),
        "apparent_bytes": apparent,
        "actual_bytes": actual,
        "hardlink_saved_bytes": saved,
        "apparent": human_bytes(apparent),
        "actual": human_bytes(actual),
        "hardlink_saved": human_bytes(saved),
        "largest": largest[:10],
    }


def summarize_glb_paths(paths: list[Path]) -> dict[str, Any]:
    apparent = 0
    actual = 0
    seen_inodes = set()
    for file_path in paths:
        stat = file_path.stat()
        apparent += stat.st_size
        inode_key = (stat.st_dev, stat.st_ino)
        if inode_key not in seen_inodes:
            seen_inodes.add(inode_key)
            actual += stat.st_size
    saved = max(0, apparent - actual)
    return {
        "glb_file_count": len(paths),
        "unique_inode_count": len(seen_inodes),
        "apparent_bytes": apparent,
        "actual_bytes": actual,
        "hardlink_saved_bytes": saved,
        "apparent": human_bytes(apparent),
        "actual": human_bytes(actual),
        "hardlink_saved": human_bytes(saved),
    }


def audit_storage(*, root: Path = ROOT) -> dict[str, Any]:
    directories = {name: summarize_glbs(root / name) for name in GLB_DIRS}
    cleanup_reports = {
        name: read_json(root / relative_path)
        for name, relative_path in CLEANUP_REPORTS.items()
    }
    all_glbs = []
    for name in GLB_DIRS:
        path = root / name
        if path.exists():
            all_glbs.extend(sorted(path.glob("*.glb")))
    totals = summarize_glb_paths(all_glbs)
    return {
        "status": "ok",
        "directories": directories,
        "cleanup_reports": cleanup_reports,
        "totals": totals,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report VRM person factory GLB storage and hardlink savings.")
    parser.add_argument("--output-json", default="results/storage_audit_latest.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = audit_storage()
    output_path = ROOT / args.output_json
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
