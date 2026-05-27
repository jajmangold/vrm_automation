#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.optimize_glb import summarize_gltf_document, workspace_path
from scripts.vrm_metadata import load_glb_json


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def report_glb_path(job: dict[str, Any], root: Path = ROOT) -> Path | None:
    env = job.get("environment", {}) if isinstance(job.get("environment", {}), dict) else {}
    report_path = workspace_path(env.get("ANIMATION_REPORT_JSON", ""), root=root) if env.get("ANIMATION_REPORT_JSON") else None
    report: dict[str, Any] = {}
    if report_path and report_path.exists():
        report = read_json(report_path)
    glb_value = report.get("optimized_glb") or report.get("output_glb") or env.get("OUTPUT_GLB")
    return workspace_path(glb_value, root=root) if glb_value else None


def audit_jobs(combined: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for job in combined.get("jobs", []):
        if not isinstance(job, dict):
            continue
        job_id = str(job.get("id", "")).strip()
        glb_path = report_glb_path(job, root=root)
        if not job_id or not glb_path:
            continue
        key = str(glb_path)
        if key in seen:
            continue
        seen.add(key)
        glb_value = str(glb_path)
        try:
            if glb_path.resolve().is_relative_to(root.resolve()):
                glb_value = "/workspace/" + glb_path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            pass
        if not glb_path.exists():
            items.append({"id": job_id, "status": "missing-glb", "glb": glb_value})
            continue
        try:
            document = load_glb_json(glb_path)
            summary = summarize_gltf_document(document)
        except Exception as exc:  # pragma: no cover - defensive guard for malformed generated assets
            items.append({"id": job_id, "status": "error", "error": str(exc), "glb": glb_value})
            continue
        sparse_count = int(summary.get("sparse_accessor_count", 0) or 0)
        items.append(
            {
                "id": job_id,
                "status": "ok",
                "glb": glb_value,
                "bytes": glb_path.stat().st_size,
                **summary,
                "needs_sparse_densify": sparse_count > 0,
            }
        )

    summary = {
        "status": "ok" if not any(item["status"] == "error" for item in items) else "review",
        "job_count": len(combined.get("jobs", [])),
        "glb_count": len(items),
        "missing_count": sum(1 for item in items if item["status"] == "missing-glb"),
        "error_count": sum(1 for item in items if item["status"] == "error"),
        "dense_glb_count": sum(
            1 for item in items if item.get("status") == "ok" and not item.get("needs_sparse_densify")
        ),
        "sparse_glb_count": sum(1 for item in items if item.get("needs_sparse_densify")),
        "total_bytes": sum(int(item.get("bytes", 0) or 0) for item in items),
        "sparse_bytes": sum(int(item.get("bytes", 0) or 0) for item in items if item.get("needs_sparse_densify")),
        "items": items,
    }
    summary["top_sparse"] = sorted(
        [item for item in items if item.get("needs_sparse_densify")],
        key=lambda item: (
            int(item.get("sparse_accessor_count", 0) or 0),
            int(item.get("bytes", 0) or 0),
            str(item.get("id", "")),
        ),
        reverse=True,
    )[:20]
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit generated GLBs for sparse accessors.")
    parser.add_argument("--combined", default="results/person_factory_all_latest.json")
    parser.add_argument("--output", default="results/glb_sparse_audit_latest.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = audit_jobs(read_json(Path(args.combined)))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                key: summary[key]
                for key in (
                    "status",
                    "job_count",
                    "glb_count",
                    "dense_glb_count",
                    "sparse_glb_count",
                    "missing_count",
                    "error_count",
                    "total_bytes",
                    "sparse_bytes",
                )
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
