from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def argv_after_separator() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def parse_vector(value: str) -> list[float]:
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if len(parts) != 7:
        raise argparse.ArgumentTypeError("expected x,y,z,rot_x,rot_y,rot_z,scale")
    return [float(part) for part in parts]


def workspace_path(path: str) -> Path:
    if path.startswith("/workspace/"):
        return ROOT / path.removeprefix("/workspace/")
    return Path(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Set a Blender object's transform and save the blend.")
    parser.add_argument("--object-name", required=True)
    parser.add_argument("--pose", type=parse_vector, required=True)
    parser.add_argument("--output-blend", required=True)
    parser.add_argument("--report-json")
    return parser.parse_args(argv_after_separator())


def main() -> None:
    import bpy

    args = parse_args()
    obj = bpy.data.objects.get(args.object_name)
    if obj is None:
        raise SystemExit(f"object not found: {args.object_name}")

    pose = args.pose
    obj.location = (pose[0], pose[1], pose[2])
    obj.rotation_euler = (pose[3], pose[4], pose[5])
    obj.scale = (pose[6], pose[6], pose[6])
    bpy.context.view_layer.update()

    output_blend = workspace_path(args.output_blend)
    output_blend.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend))

    report = {
        "status": "ok",
        "object_name": args.object_name,
        "pose": [round(value, 6) for value in pose],
        "output_blend": str(output_blend),
    }
    if args.report_json:
        report_path = workspace_path(args.report_json)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
