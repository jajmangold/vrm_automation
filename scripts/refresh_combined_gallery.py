from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run_checked(command: list[str]) -> dict:
    started = time.monotonic()
    completed = subprocess.run(command, cwd=ROOT, text=True)
    elapsed = round(time.monotonic() - started, 3)
    return {
        "command": command,
        "elapsed_seconds": elapsed,
        "returncode": completed.returncode,
        "status": "ok" if completed.returncode == 0 else "error",
    }


def refresh_combined_gallery(
    *,
    summary_json: str = "results/person_factory_all_latest.json",
    gallery: str = "outputs/batch/person_factory_all.html",
    contact_sheet: str = "outputs/batch/person_factory_all_contact_sheet.html",
    character_index: str = "results/person_factory_character_catalog_latest.json",
    summary_only: bool = False,
) -> dict:
    started = time.monotonic()
    build_command = ["python3", "scripts/build_combined_gallery.py", gallery, "--summary-json", summary_json]
    if summary_only:
        build_command.extend(["--summary-only", "--character-index-json", character_index])
    stages = [
        {
            "name": "combined_summary" if summary_only else "combined_gallery",
            **run_checked(build_command),
        }
    ]
    if not summary_only:
        stages.append(
            {
                "name": "contact_sheet",
                **run_checked(["python3", "scripts/build_pose_contact_sheet.py", summary_json, contact_sheet]),
            }
        )
    status = "ok" if all(stage["status"] == "ok" for stage in stages) else "error"
    return {
        "status": status,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "summary_json": summary_json,
        "gallery": None if summary_only else gallery,
        "contact_sheet": None if summary_only else contact_sheet,
        "character_index": character_index if summary_only else None,
        "summary_only": summary_only,
        "stages": stages,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh the global Person Factory gallery and contact sheet.")
    parser.add_argument("--summary-json", default="results/person_factory_all_latest.json")
    parser.add_argument("--gallery", default="outputs/batch/person_factory_all.html")
    parser.add_argument("--contact-sheet", default="outputs/batch/person_factory_all_contact_sheet.html")
    parser.add_argument("--character-index", default="results/person_factory_character_catalog_latest.json")
    parser.add_argument("--report-json", default="results/refresh_combined_gallery_latest.json")
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()

    report = refresh_combined_gallery(
        summary_json=args.summary_json,
        gallery=args.gallery,
        contact_sheet=args.contact_sheet,
        character_index=args.character_index,
        summary_only=args.summary_only,
    )
    output = Path(args.report_json)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
