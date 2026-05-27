#!/bin/sh
set -eu

JOB_JSON="${MUSE_TALK_JOB_JSON:-/workspace/results/musetalk/latest_job.json}"
MODELS_DIR="${MUSE_TALK_MODELS_DIR:-/opt/MuseTalk/models}"
MUSE_TALK_HOME="${MUSE_TALK_HOME:-/opt/MuseTalk}"
LOCAL_UID="${LOCAL_UID:-1000}"
LOCAL_GID="${LOCAL_GID:-1000}"

if [ ! -f "${JOB_JSON}" ]; then
  echo "MuseTalk job JSON not found: ${JOB_JSON}" >&2
  exit 2
fi

for required in \
  "${MODELS_DIR}/musetalkV15/unet.pth" \
  "${MODELS_DIR}/musetalkV15/musetalk.json" \
  "${MODELS_DIR}/whisper/config.json" \
  "${MODELS_DIR}/sd-vae/config.json"; do
  if [ ! -e "${required}" ]; then
    echo "MuseTalk model file missing: ${required}" >&2
    echo "Populate the mounted model cache first, for example with MuseTalk's download_weights.sh." >&2
    exit 3
  fi
done

cd "${MUSE_TALK_HOME}"
set +e
python3.10 - "$JOB_JSON" "$MODELS_DIR" <<'PY'
import json
import os
import pickle
import subprocess
import sys

job_path, models_dir = sys.argv[1:3]
job = json.loads(open(job_path, encoding="utf-8").read())
result_dir = job.get("result_dir", "/workspace/outputs/musetalk")
command = [
    "python3.10",
    "-m",
    "scripts.inference",
    "--inference_config",
    job["inference_config"],
    "--result_dir",
    result_dir,
    "--unet_model_path",
    f"{models_dir}/musetalkV15/unet.pth",
    "--unet_config",
    f"{models_dir}/musetalkV15/musetalk.json",
    "--whisper_dir",
    f"{models_dir}/whisper",
    "--version",
    "v15",
    "--fps",
    str(job.get("fps", 25)),
]
if job.get("use_float16"):
    command.append("--use_float16")
if job.get("parsing_mode"):
    command.extend(["--parsing_mode", str(job["parsing_mode"])])
manual_coord_paths = []
for task in (job.get("tasks") or {}).values():
    manual_bbox = task.get("manual_bbox")
    if not manual_bbox:
        continue
    input_basename = os.path.basename(task["video_path"]).split(".")[0]
    coord_path = os.path.join(result_dir, "../", input_basename + ".pkl")
    os.makedirs(os.path.dirname(coord_path), exist_ok=True)
    bbox = tuple(int(value) for value in manual_bbox)
    with open(coord_path, "wb") as handle:
        pickle.dump([bbox], handle)
    manual_coord_paths.append(coord_path)
if manual_coord_paths:
    command.extend(["--use_saved_coord", "--saved_coord"])
    print(json.dumps({"saved_coord_paths": manual_coord_paths}, indent=2))
print(json.dumps({"command": command}, indent=2))
raise SystemExit(subprocess.call(command))
PY
status="$?"
set -e

for path in /workspace/outputs/musetalk /workspace/results/musetalk; do
  if [ -e "${path}" ]; then
    chown -R "${LOCAL_UID}:${LOCAL_GID}" "${path}" || true
  fi
done

exit "${status}"
