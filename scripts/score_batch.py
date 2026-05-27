from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_batch_gallery import read_report
from scripts.qa_scoring import score_job


ROOT = Path(__file__).resolve().parents[1]


def score_batch(batch_result: dict) -> dict:
    scored = dict(batch_result)
    jobs = []
    counts: dict[str, int] = {}
    priorities: dict[str, int] = {}
    for job in batch_result.get("jobs", []):
        updated = dict(job)
        report = read_report(job.get("environment", {})) if job.get("environment") else {}
        qa = score_job(job, report, ROOT)
        updated["qa"] = qa
        counts[qa["qa_grade"]] = counts.get(qa["qa_grade"], 0) + 1
        priorities[qa["review_priority"]] = priorities.get(qa["review_priority"], 0) + 1
        jobs.append(updated)
    scored["jobs"] = jobs
    scored["qa_summary"] = {
        "grades": counts,
        "priorities": priorities,
        "review_count": sum(count for name, count in priorities.items() if name != "ship"),
        "ship_count": priorities.get("ship", 0),
    }
    return scored


def main() -> None:
    input_path = Path(sys.argv[1] if len(sys.argv) > 1 else "results/batch_person_factory_in_blender_latest.json")
    output_path = Path(sys.argv[2] if len(sys.argv) > 2 else input_path)
    batch_result = json.loads(input_path.read_text(encoding="utf-8"))
    scored = score_batch(batch_result)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(scored, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(scored["qa_summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
