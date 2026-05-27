#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sparse_items_by_priority(audit: dict[str, Any]) -> list[dict[str, Any]]:
    items = [
        item
        for item in audit.get("items", [])
        if isinstance(item, dict)
        and item.get("status") == "ok"
        and item.get("needs_sparse_densify")
        and str(item.get("id", "")).strip()
    ]
    return sorted(
        items,
        key=lambda item: (
            int(item.get("sparse_accessor_count", 0) or 0),
            int(item.get("bytes", 0) or 0),
            str(item.get("id", "")),
        ),
        reverse=True,
    )


def select_sparse_jobs(
    combined: dict[str, Any],
    audit: dict[str, Any],
    *,
    limit: int,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], list[str]]:
    jobs_by_id = {
        str(job.get("id", "")): job
        for job in combined.get("jobs", [])
        if isinstance(job, dict) and str(job.get("id", "")).strip()
    }
    selected_jobs: list[dict[str, Any]] = []
    missing_ids: list[str] = []
    selected_items = sparse_items_by_priority(audit)[max(offset, 0) : max(offset, 0) + max(limit, 0)]
    for item in selected_items:
        item_id = str(item.get("id", ""))
        job = jobs_by_id.get(item_id)
        if job:
            selected_jobs.append(job)
        else:
            missing_ids.append(item_id)
    return selected_jobs, missing_ids


def build_sparse_batch(
    combined: dict[str, Any],
    audit: dict[str, Any],
    *,
    limit: int,
    offset: int = 0,
    manifest: str = "sparse-densify-next",
) -> dict[str, Any]:
    jobs, missing_ids = select_sparse_jobs(combined, audit, limit=limit, offset=offset)
    return {
        "status": "ok" if not missing_ids else "review",
        "manifest": manifest,
        "source": "results/glb_sparse_audit_latest.json",
        "selection": {
            "limit": limit,
            "offset": offset,
            "selected_count": len(jobs),
            "selected_ids": [job["id"] for job in jobs],
            "missing_ids": missing_ids,
        },
        "jobs": jobs,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a batch result for remaining sparse GLB densification.")
    parser.add_argument("--audit", default="results/glb_sparse_audit_latest.json")
    parser.add_argument("--combined", default="results/person_factory_all_latest.json")
    parser.add_argument("--output", default="results/batch_person_factory_sparse_next_latest.json")
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--manifest", default="sparse-densify-next")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    batch = build_sparse_batch(
        read_json(Path(args.combined)),
        read_json(Path(args.audit)),
        limit=args.limit,
        offset=args.offset,
        manifest=args.manifest,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(batch, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": batch["status"],
                "output": str(output),
                **batch["selection"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
