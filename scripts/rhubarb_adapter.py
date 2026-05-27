from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


RHUBARB_TO_VRM_VISEME = {
    "X": "rest",
    "A": "rest",
    "B": "ee",
    "C": "aa",
    "D": "aa",
    "E": "oh",
    "F": "ou",
    "G": "ee",
    "H": "aa",
}


def rhubarb_shape_to_viseme(shape: str) -> str:
    return RHUBARB_TO_VRM_VISEME.get(str(shape).strip().upper(), "rest")


def rhubarb_to_lipsync_timeline(rhubarb_data: dict, intensity: float = 1.0) -> dict:
    mouth_cues = rhubarb_data.get("mouthCues") or []
    cues = []
    duration = 0.0
    for cue in mouth_cues:
        start = round(float(cue.get("start", duration)), 3)
        end = round(float(cue.get("end", start)), 3)
        cue_duration = max(0.0, round(end - start, 3))
        viseme = rhubarb_shape_to_viseme(str(cue.get("value", "X")))
        value = 0.0 if viseme == "rest" else round(float(cue.get("weight", intensity)), 3)
        cues.append(
            {
                "time": start,
                "duration": cue_duration,
                "viseme": viseme,
                "value": value,
            }
        )
        duration = max(duration, end)
    duration = round(duration, 3)
    return {
        "schema": "vrm-person-factory.face-timeline.v1",
        "source": {
            "mode": "rhubarb",
            "mouthCue_count": len(mouth_cues),
            "soundFile": (rhubarb_data.get("metadata") or {}).get("soundFile"),
        },
        "duration": duration,
        "cues": cues,
        "expressions": [
            {"time": 0.0, "duration": duration, "name": "happy", "value": 0.14},
            {"time": round(duration * 0.52, 3), "duration": 0.08, "name": "blink", "value": 1.0},
        ],
    }


def write_lipsync_timeline(output_path: Path, rhubarb_data: dict, intensity: float = 1.0) -> dict:
    timeline = rhubarb_to_lipsync_timeline(rhubarb_data, intensity=intensity)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(timeline, indent=2, sort_keys=True), encoding="utf-8")
    return timeline


def parse_args(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert Rhubarb Lip Sync JSON mouthCues into a VRM face timeline.")
    parser.add_argument("rhubarb_json")
    parser.add_argument("output", nargs="?", default="outputs/lipsync/rhubarb.face.json")
    parser.add_argument("--intensity", type=float, default=1.0)
    return parser.parse_args(args)


def main(args: list[str] | None = None) -> None:
    parsed = parse_args(sys.argv[1:] if args is None else args)
    rhubarb_data = json.loads(Path(parsed.rhubarb_json).read_text(encoding="utf-8"))
    timeline = write_lipsync_timeline(Path(parsed.output), rhubarb_data, intensity=parsed.intensity)
    print(json.dumps({"path": parsed.output, "duration": timeline["duration"], "cues": len(timeline["cues"])}, indent=2))


if __name__ == "__main__":
    main()
