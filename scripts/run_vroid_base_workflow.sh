#!/bin/sh
set -eu

MODEL_ID="${MODEL_ID:-vroid_hairsample_female_cc0}"
MODEL_PATH="${MODEL_PATH:-/workspace/input/base_models/${MODEL_ID}.vrm}"

docker compose --profile tools run --rm download-base-models

INPUT_MODEL="${MODEL_PATH}" \
OUTPUT_JSON="/workspace/results/${MODEL_ID}_inspection.json" \
MATERIAL_AUDIT_JSON="/workspace/results/${MODEL_ID}_material_audit.json" \
docker compose --profile tools run --rm inspect-model

INPUT_MODEL="${MODEL_PATH}" \
ANIMATION_REPORT_JSON="/workspace/results/${MODEL_ID}_animation.json" \
OUTPUT_BLEND="/workspace/outputs/${MODEL_ID}_wave.blend" \
OUTPUT_GLB="/workspace/outputs/${MODEL_ID}_wave.glb" \
OUTPUT_VRM="/workspace/outputs/${MODEL_ID}_wave.vrm" \
docker compose --profile tools run --rm animate-smoke
