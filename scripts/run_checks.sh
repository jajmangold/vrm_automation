#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

echo "== unit tests =="
python3 -m unittest discover -s tests

echo "== compose config =="
docker compose config >/tmp/vrm_automation.compose.yml

echo "== blender no-render smoke =="
RENDER_POSE_STILLS=0 \
INPUT_MODEL=/workspace/input/checks_missing_input.vrm \
ANIMATION_REPORT_JSON=/workspace/results/checks_animation_smoke.json \
OUTPUT_BLEND=/workspace/outputs/checks_animation_smoke.blend \
OUTPUT_GLB=/workspace/outputs/checks_animation_smoke.glb \
docker compose --profile tools run --rm animate-smoke >/tmp/vrm_automation_checks_blender.log 2>&1

python3 - <<'PY'
import json
from pathlib import Path

report_path = Path("results/checks_animation_smoke.json")
report = json.loads(report_path.read_text(encoding="utf-8"))
if report.get("status") != "ok":
    raise SystemExit(f"{report_path} status is {report.get('status')!r}: {report.get('errors')}")
if report.get("errors"):
    raise SystemExit(f"{report_path} has errors: {report['errors']}")
print(f"{report_path}: status=ok mode={report.get('mode')}")
PY

echo "checks passed"
