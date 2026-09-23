# MuseTalk Integration

MuseTalk is a useful optional backend for audio-driven talking-video previews. It is not a
replacement for the Godot/VRM face-control path because it edits 2D face video frames rather than
producing 3D blendshape curves.

## Upstream Snapshot

- Repository: <https://github.com/TMElyralab/MuseTalk>
- Current recommended model path in the repo is MuseTalk 1.5.
- License: MIT for code; the README states trained models are available for any purpose, including
  commercial use. Third-party model/component licenses still apply.
- Input config is YAML with `task_N.video_path` and `task_N.audio_path`; `video_path` may be a
  video, image, or image directory.
- Normal entrypoint: `python3 -m scripts.inference`.
- Realtime entrypoint: `python3 -m scripts.realtime_inference`.
- Recommended input video rate is 25 fps.
- Runtime is heavyweight: Python 3.10, CUDA/PyTorch, MMLab packages, ffmpeg, and downloaded model
  weights. The README claims 30 fps+ on an NVIDIA Tesla V100 for realtime inference.

## Decision

Keep two separate face pipelines:

1. Godot runtime control remains the canonical game-asset path. It uses VRM shape keys, expression
   presets, and `vrm-person-factory.face-timeline.v1` cues.
2. MuseTalk becomes an optional render backend for portrait/talking-video previews from a rendered
   character still or video plus speech audio.

This keeps generated people controllable in Godot while allowing high-quality audio-driven video
review when we have a GPU service with MuseTalk weights installed.

Speech generation/transcription should also stay external to MuseTalk. The local environment already
has TTS/STT capacity on `tts-host` and `stt-host`, with Qwen3-TTS through Wan2GP noted as the
preferred recurring-character voice layer. MuseTalk should consume finished WAV files from that
voice layer, while STT can provide transcript/caption QA and later improve phoneme/viseme timing.
Discovered endpoints on 2026-05-24:

- `http://tts-host:8102/v1/audio/speech`: Qwen 1.7B voice-design TTS
- `http://tts-host:8103/v1/audio/speech`: Qwen 0.6B base/clone TTS
- `http://stt-host:8098/v1/audio/transcriptions`: CrispASR fast STT, backend `granite-4.1-nar`
- `http://stt-host:8099/v1/audio/transcriptions`: CrispASR plus STT, backend `granite-4.1-plus`

`scripts/speech_services.py` loads `config/speech_services.example.json` and can health-check these
services before a talking-video batch.

## Local Adapter

`scripts/musetalk_adapter.py` creates a tested MuseTalk job manifest, writes MuseTalk-compatible
inference YAML, and prints the command that should run inside a MuseTalk checkout/container.

Example:

```bash
python3 scripts/musetalk_adapter.py \
  --character-id gen-004-female-glasses-cheerful-wave \
  --source-media /workspace/outputs/batch/gen-004-female-glasses-cheerful-wave_pose_renders/pose_portrait_0024.png \
  --audio /workspace/input/audio/hello.wav \
  --result-name gen-004-female-glasses-cheerful-wave_hello.mp4 \
  --output results/musetalk/gen-004-female-glasses-cheerful-wave.job.json \
  --inference-config /workspace/results/musetalk/gen-004-female-glasses-cheerful-wave.yaml \
  --use-float16 \
  --write-config
```

Once MuseTalk inference produces an MP4, animation reports can include:

```json
{
  "talking_video": "/workspace/outputs/musetalk/gen-004-female-glasses-cheerful-wave_hello.mp4"
}
```

The batch gallery embeds that video for review.

## Container Profile

The optional `musetalk` Compose profile builds `Dockerfile.musetalk`, clones the upstream
repository, installs the CUDA/PyTorch/MMLab runtime, and runs `/workspace/scripts/run_musetalk_job.sh`.
It mounts the project at `/workspace` and a model cache at `/opt/MuseTalk/models` by default:

```bash
MUSE_TALK_MODEL_CACHE=./input/musetalk_models \
MUSE_TALK_JOB_JSON=/workspace/results/musetalk/batch/person_hello.job.json \
docker compose --profile musetalk run --rm musetalk
```

The runner refuses to start inference until the expected MuseTalk 1.5, Whisper, and SD-VAE model
files exist in the mounted model cache. This prevents accidental multi-GB downloads during normal
person-factory tests.

## Next Work

- Generate short portrait videos from Blender/Godot at 25 fps for better identity consistency than
  a single still.
- Add batch queue support that pairs each selected character with one or more audio clips.
- Feed MuseTalk MP4s into the gallery score/report loop alongside PNG pose renders.
