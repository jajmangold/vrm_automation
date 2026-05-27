#!/bin/sh
set -eu

MODEL_DIR="${MUSE_TALK_MODEL_CACHE:-input/musetalk_models}"

mkdir -p \
  "${MODEL_DIR}/musetalkV15" \
  "${MODEL_DIR}/dwpose" \
  "${MODEL_DIR}/face-parse-bisent" \
  "${MODEL_DIR}/sd-vae" \
  "${MODEL_DIR}/syncnet" \
  "${MODEL_DIR}/whisper"

hf download TMElyralab/MuseTalk \
  --local-dir "${MODEL_DIR}" \
  "musetalkV15/musetalk.json"

hf download TMElyralab/MuseTalk \
  --local-dir "${MODEL_DIR}" \
  "musetalkV15/unet.pth"

hf download stabilityai/sd-vae-ft-mse \
  --local-dir "${MODEL_DIR}/sd-vae" \
  "config.json"

hf download stabilityai/sd-vae-ft-mse \
  --local-dir "${MODEL_DIR}/sd-vae" \
  "diffusion_pytorch_model.bin"

hf download openai/whisper-tiny \
  --local-dir "${MODEL_DIR}/whisper" \
  "config.json"

hf download openai/whisper-tiny \
  --local-dir "${MODEL_DIR}/whisper" \
  "pytorch_model.bin"

hf download openai/whisper-tiny \
  --local-dir "${MODEL_DIR}/whisper" \
  "preprocessor_config.json"

hf download yzd-v/DWPose \
  --local-dir "${MODEL_DIR}/dwpose" \
  "dw-ll_ucoco_384.pth"

hf download ByteDance/LatentSync \
  --local-dir "${MODEL_DIR}/syncnet" \
  "latentsync_syncnet.pt"

curl -L https://download.pytorch.org/models/resnet18-5c106cde.pth \
  -o "${MODEL_DIR}/face-parse-bisent/resnet18-5c106cde.pth"

if command -v gdown >/dev/null 2>&1; then
  gdown 154JgKpzCPW82qINcVieuPH3fZ2e0P812 \
    -O "${MODEL_DIR}/face-parse-bisent/79999_iter.pth"
elif command -v uvx >/dev/null 2>&1; then
  uvx gdown 154JgKpzCPW82qINcVieuPH3fZ2e0P812 \
    -O "${MODEL_DIR}/face-parse-bisent/79999_iter.pth"
elif command -v pipx >/dev/null 2>&1; then
  pipx run gdown 154JgKpzCPW82qINcVieuPH3fZ2e0P812 \
    -O "${MODEL_DIR}/face-parse-bisent/79999_iter.pth"
else
  echo "gdown, uvx, or pipx is required for face-parse-bisent/79999_iter.pth" >&2
  exit 4
fi

python3 scripts/musetalk_run_batch.py \
  results/musetalk/person_factory_hello_batch \
  --batch-result results/batch_asset_pool_first20.json \
  --limit 1 \
  --status-output results/musetalk/model_cache_preflight.json
