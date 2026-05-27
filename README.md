# VRM Automation

Headless Blender scaffold for testing which parts of the VRM character workflow can be automated.

The default lane is intentionally conservative:

- Blender official Linux build in Docker.
- VRM Add-on for Blender for VRM import/export and future Python automation.
- `mmd_tools` for PMX/PMD import.
- Material Combiner downloaded as optional tooling, not required for the first pass.
- Human gates for licensing, character taste, clothing clipping, spring-bone motion, and final QA.

## Layout

- `docker-compose.yml`: headless Blender services.
- `Dockerfile`: downloads official Blender.
- `scripts/download_addons.sh`: downloads add-on ZIPs into `addons/`.
- `scripts/download_base_models.py`: downloads curated base characters with source/license metadata.
- `scripts/run_vroid_base_workflow.sh`: runs the current YouTube-style base model workflow.
- `scripts/create_sample_outfit.py`: writes a tiny GLB outfit asset for importer validation.
- `scripts/install_addons.py`: installs/enables add-ons inside Blender.
- `scripts/inspect_model.py`: imports a model when possible and writes structural JSON.
- `scripts/material_audit.py`: writes a material/texture report and flags likely atlas candidates.
- `scripts/animate_smoke.py`: imports a character or generates a test rig, applies a short action,
  and exports `.blend` plus animated `.glb`.
- `godot_viewer/`: Godot runtime/control API for loading batch GLBs as game-ready scenes.
- `config/pipeline.example.json`: rough pipeline contract.
- `research/rough_spots_and_better_options.md`: current research notes and sources.
- `input/`: place test `.vrm`, `.pmx`, `.pmd`, `.fbx`, `.glb`, or `.gltf` files here.
- `results/`: inspection reports.
- `outputs/`: generated artifacts.

## Run

```bash
cd /srv/nvme-data/containers/projects/vrm_automation
cp .env.example .env
docker compose --profile tools run --rm download-addons
docker compose build blender-vrm
docker compose run --rm blender-vrm
```

## Test

Run pure-Python unit tests before changing fit, manifest, or report logic:

```bash
python3 -m unittest discover -s tests
```

Run the standard local quality gate:

```bash
./scripts/run_checks.sh
```

Run a lightweight Blender integration check without PNG renders:

```bash
RENDER_POSE_STILLS=0 docker compose --profile tools run --rm animate-smoke
```

Inspect a model:

```bash
cd /srv/nvme-data/containers/projects/vrm_automation
INPUT_MODEL=/workspace/input/model.vrm \
OUTPUT_JSON=/workspace/results/model_inspection.json \
MATERIAL_AUDIT_JSON=/workspace/results/material_audit.json \
docker compose --profile tools run --rm inspect-model
```

Run the current end-to-end base model workflow:

```bash
cd /srv/nvme-data/containers/projects/vrm_automation
./scripts/run_vroid_base_workflow.sh
```

This stays close to the tutorial's useful path while using modern tooling:

1. Download a curated VRoid base VRM.
2. Import it into Blender through VRM Add-on.
3. Inspect rig/materials/shape keys.
4. Audit materials before any atlas step.
5. Apply a short humanoid smoke animation.
6. Export `.blend` and animated `.glb`.

Current base model:

- `input/base_models/vroid_hairsample_female_cc0.vrm`
- Source manifest: `results/base_model_manifest.json`
- Inspection: `results/vroid_hairsample_female_cc0_inspection.json`
- Material audit: `results/vroid_hairsample_female_cc0_material_audit.json`
- Animated output: `outputs/vroid_hairsample_female_cc0_wave.glb`
- VRM output: `outputs/vroid_hairsample_female_cc0_wave.vrm`
- Pose QA renders: `outputs/pose_renders/pose_*.png`

Generate or animate a rigged smoke character:

```bash
cd /srv/nvme-data/containers/projects/vrm_automation
docker compose --profile tools run --rm animate-smoke
```

If `input/model.vrm` does not exist, this creates a blocky rigged test character and exports:

- `outputs/animation_smoke.blend`
- `outputs/animation_smoke.glb`
- `results/animation_smoke.json`

For a real character:

```bash
INPUT_MODEL=/workspace/input/your_character.vrm \
OUTPUT_GLB=/workspace/outputs/your_character_wave.glb \
OUTPUT_VRM=/workspace/outputs/your_character_wave.vrm \
docker compose --profile tools run --rm animate-smoke
```

Set `OUTPUT_VRM` when you want the VRM Add-on export path in addition to `.blend` and `.glb`.
The report records `exports.vrm`, `input_vrm_summary`, `output_vrm_summary`, and
`vrm_preservation`. For VRM 0.x files this includes `secondaryAnimation` spring/collider group
counts; for VRM 1.0 files it checks `VRMC_springBone` summary counts.

Validate the external outfit import lane with the bundled sample GLB:

```bash
docker compose --profile tools run --rm create-sample-outfit
OUTFIT_MODEL=/workspace/input/outfits/sample_torso_sash.glb ADD_OUTFIT_PROBE=0 \
docker compose --profile tools run --rm animate-smoke
```

For a real outfit or accessory, place a `.glb`, `.gltf`, `.fbx`, or `.obj` under `input/outfits/`
and set `OUTFIT_MODEL=/workspace/input/outfits/your_asset.glb`. The importer classifies common
accessories into `torso_back`, `neck_chest`, `head_face`, `torso_front`, or `unknown`, then applies
category-specific scale, placement, and bind bones. Override filename inference with
`OUTFIT_CATEGORY=head_face` or the manifest `category` field. The `fit_check` block flags obvious
scale, placement, floating, or buried-depth issues from bounds; visual PNG QA is still required.
Tune front placement with `OUTFIT_FRONT_OFFSET_RATIO` when side renders show the asset is floating
or buried.

Use image-guided calibration when a fitted accessory looks wrong in the PNGs. The intended loop is:
render the bad placement, use Qwen Image Edit to make a corrected target image, use SAM 3.1 or a
mask to locate the accessory in both images, then bake the measured delta back into deterministic
`fit_overrides`.

```bash
python3 scripts/accessory_visual_calibration.py \
  --current-mask outputs/calibration/bowtie_bad_red_mask.png \
  --target-mask outputs/calibration/bowtie_qwen_target_mask.png \
  --character-box 0,280,640,960 \
  --current-overrides-json outputs/calibration/bowtie_current_overrides.json \
  --asset-key bowtie-jeremy \
  --category neck_chest \
  --output-json outputs/calibration/bowtie_fit_overrides_proposed.json
```

The same script can call a running local SAM 3.1 endpoint when masks are not precomputed:

```bash
python3 scripts/accessory_visual_calibration.py \
  --current-image outputs/batch/qa-bowtie-fit-001_pose_renders/pose_portrait_0009.png \
  --target-image outputs/calibration/bowtie_qwen_corrected.png \
  --sam-prompt "red bow tie" \
  --character-box 0,280,640,960
```

For rendered PNGs, the character box can be inferred from the foreground so the loop is just the
current render plus the Qwen target:

```bash
python3 scripts/accessory_visual_calibration.py \
  --current-image outputs/batch/qa-bowtie-fit-001_pose_renders/pose_portrait_0009.png \
  --target-image outputs/calibration/bowtie_qwen_corrected.png \
  --image-box-mode red-accessory \
  --character-image outputs/batch/qa-bowtie-fit-001_pose_renders/pose_portrait_0009.png \
  --asset-key bowtie-jeremy \
  --category neck_chest \
  --output-json outputs/calibration/bowtie_auto_character_measurement.json
```

It can also prepare and optionally run the local Qwen Image Edit workflow directly. Without
`--qwen-run`, this stages the source render into Comfy input, writes a prepared workflow for review,
and measures a supplied target. Add `--qwen-run` only when you want to spend the GPU time and use
the saved Comfy output as the target image:

```bash
python3 scripts/accessory_visual_calibration.py \
  --current-image outputs/batch/qa-bowtie-fit-001_pose_renders/pose_portrait_0009.png \
  --qwen-workflow-json auto \
  --qwen-source-image outputs/batch/qa-bowtie-fit-001_pose_renders/pose_portrait_0009.png \
  --qwen-prompt "Move only the red bow tie to the shirt collar. Keep the same character, pose, camera, and outfit." \
  --qwen-filename-prefix vrm_calibration/bowtie_corrected \
  --qwen-prepared-workflow-json outputs/calibration/bowtie_qwen_prepared.api.json \
  --target-image outputs/calibration/bowtie_qwen_corrected.png \
  --sam-prompt "red bow tie" \
  --image-box-mode sam-red-fallback \
  --character-box 0,280,640,960 \
  --asset-key poly-pizza-bowtie-jeremy \
  --category neck_chest \
  --asset-config-json config/poly_pizza_assets.json \
  --current-overrides-from-asset-config \
  --apply-to-asset-config \
  --center-correction-gain 0.42 \
  --output-json outputs/calibration/bowtie_anchor_calibration.json
```

`auto` searches the local Comfy/Wan workspace for Qwen Image Edit API workflows and records the
selected workflow plus LoRA names in the output metadata. Override the search when testing a new
workflow or multi-angle LoRA:

```bash
python3 scripts/accessory_visual_calibration.py \
  --qwen-workflow-json auto \
  --qwen-workflow-search-root /srv/nvme-data/containers/comfy/storage-user/workflows \
  --qwen-workflow-search-root /srv/nvme-data/containers/wan2gp/profiles/qwen \
  ...
```

For red accessories such as the bow tie, `--image-box-mode sam-red-fallback` keeps SAM as the
primary locator but falls back to deterministic red-pixel bounds if the text prompt misses.

The output records both the Qwen/SAM image-space measurement and the deterministic placement
values to copy into an asset `fit_overrides` block. It also writes an `anchor_calibration` block
with the Qwen target center/size ratios, so the catalog can tag assets such as
`calibration:image-guided-anchor` and `anchor:neck-chest-collar-center`. Treat Qwen as the visual
target proposal; keep the generated GLB/renders deterministic and accept the result only after
rerendered PNG QA. Use `--apply-to-asset-config` only after that QA path is intentional. If a direct
image delta overcorrects, lower `--center-correction-gain` and iterate; the bowtie calibration uses
`0.42` because its rendered vertical motion responds more strongly than one pixel per stored ratio
unit.

For multi-angle calibration, measure each current render and each Qwen-corrected target with SAM,
then store the per-view targets in the same anchor artifact:

```bash
python3 scripts/accessory_visual_calibration.py \
  --current-view-image front=outputs/batch/bowtie_front.png \
  --target-view-image front=outputs/calibration/bowtie_qwen_front.png \
  --current-view-image right45=outputs/batch/bowtie_right45.png \
  --target-view-image right45=outputs/calibration/bowtie_qwen_right45.png \
  --sam-prompt "red bow tie" \
  --character-box 0,280,640,960 \
  --asset-key bowtie-jeremy \
  --category neck_chest \
  --source qwen-image-edit+sam31+multi-angle \
  --primary-view front \
  --output-json outputs/calibration/bowtie_multi_view_anchor.json
```

Use `--current-view-box` / `--target-view-box` or masks instead of images when SAM boxes have
already been reviewed. The output keeps a primary anchor plus a `views` map, so validation can
compare each camera angle against its own Qwen target.

Validate the stored anchor against rendered QA frames before promoting it beyond review:

```bash
python3 scripts/accessory_visual_calibration.py \
  --anchor-calibration-json outputs/calibration/bowtie_anchor_calibration.json \
  --view-image front-0024=outputs/batch/gen-018-female-bowtie-jeremy-cheerful-wave_pose_renders/pose_0024.png \
  --view-image portrait-0024=outputs/batch/gen-018-female-bowtie-jeremy-cheerful-wave_pose_renders/pose_portrait_0024.png \
  --sam-prompt "red bow tie" \
  --character-box 0,280,640,960 \
  --output-json outputs/calibration/bowtie_anchor_validation.json
```

The validator requires at least two views by default and returns `review` for missing detections,
center/size drift, or insufficient view coverage.

To batch the first measurement step across queued accessories, build the queue and measure the
highest-priority render examples with SAM 3.1:

```bash
python3 scripts/build_anchor_calibration_queue.py \
  --workspace-root . \
  --output-json results/accessory_anchor_calibration_queue_latest.json

python3 scripts/measure_anchor_render_examples.py \
  --queue-json results/accessory_anchor_calibration_queue_latest.json \
  --workspace-root . \
  --image-box-mode sam-red-fallback \
  --max-items 8 \
  --max-renders-per-item 1 \
  --output-json results/accessory_anchor_current_measurements_batch_latest.json

python3 scripts/suggest_anchor_fit_overrides.py \
  --measurements-json results/accessory_anchor_current_measurements_batch_latest.json \
  --output-json results/accessory_anchor_fit_suggestions_batch_latest.json
```

This does not edit the asset catalog. It produces measured current placement and deterministic
fit suggestions so the next Qwen/SAM calibration or rerender pass starts from the worst offenders.
Turn candidate suggestions into a small render probe without catalog promotion:

```bash
python3 scripts/build_anchor_probe_manifest.py \
  --suggestions-json results/accessory_anchor_fit_suggestions_batch_latest.json \
  --output-json config/person_factory.anchor_candidate_probe_latest.json \
  --id-prefix anchor-candidate-sam-001

python3 scripts/batch_pipeline.py \
  config/person_factory.anchor_candidate_probe_latest.json \
  results/batch_anchor_candidate_probe_latest.json

python3 scripts/finalize_batch.py \
  results/batch_anchor_candidate_probe_latest.json \
  outputs/batch/person_factory_anchor_candidate_probe.html \
  --summary-json results/finalize_anchor_candidate_probe_latest.json \
  --skip-optimize
```

By default the animation export clears imported animation data, simplifies material node graphs
for GLB export, keys a reusable facial preset when matching shape keys exist, and adds a generated
outfit-fit probe for visual QA. Disable those only for diagnosis:

```bash
CLEAR_IMPORTED_ANIMATION=0 NORMALIZE_MATERIALS_FOR_GLB=0 ANIMATE_EXPRESSIONS=0 ADD_OUTFIT_PROBE=0 \
docker compose --profile tools run --rm animate-smoke
```

Choose a facial preset explicitly when reviewing expressions:

```bash
FACIAL_PRESET=talking_soft RENDER_POSE_FRAMES=8,18,29,40,72 \
docker compose --profile tools run --rm animate-smoke
```

Supported presets include `neutral`, `happy`, `shy`, `surprised`, `talking_soft`, and
`talking_wide`. Generated person manifests tag these as `face:<preset>` and choose QA frames that
capture active mouth/blink moments.

It also writes front, side, and three-quarter pose QA stills by default. Disable only when you
need a faster non-visual run:

```bash
RENDER_POSE_STILLS=0 docker compose --profile tools run --rm animate-smoke
```

Limit the stills to the front camera only when iterating quickly:

```bash
RENDER_ANGLES=front docker compose --profile tools run --rm animate-smoke
```

Run a manifest-driven outfit batch:

```bash
docker compose --profile tools run --rm create-sample-outfit
python3 scripts/batch_pipeline.py config/outfit_batch.example.json
```

Start the webapp and browse results in Chrome:

```bash
cd /srv/nvme-data/containers/projects/vrm_automation
docker compose --profile webapp up -d webapp
```

Then open:

`http://127.0.0.1:8780`

The factory page includes a paginated character browser backed by `/api/characters`, so Chrome can
search, tag-filter, QA-filter, and lip-sync-filter thousands of generated characters without loading
the full all-assets gallery into the main UI. The legacy full gallery is still available from the
embedded frame and the `Open gallery` link.

Build the combined all-assets review page when new result files are ready:

```bash
python3 scripts/build_combined_gallery.py
```

The combined page uses compact QA details so it remains practical for thousands of characters.
Single-batch galleries keep deeper embedded debug JSON; the combined page links each card to its
full result JSON instead.

`scripts/finalize_batch.py` also writes a searchable pose-render contact sheet beside each batch
gallery by default, for example `outputs/batch/headwear_refresh_contact_sheet.html`. Build the
all-assets contact sheet after refreshing the combined summary:

```bash
python3 scripts/build_pose_contact_sheet.py \
  results/person_factory_all_latest.json \
  outputs/batch/person_factory_all_contact_sheet.html
```

The webapp serves optimized GLBs, MuseTalk videos, and result JSON through in-gallery paths such as
`batch_optimized/...` and `results/...`, so the output links are usable directly from Chrome.
Lip-sync-capable cards also link their face timeline JSON and include a `Talk` action that loads
the character into Godot and posts the timeline to `/lipsync`.

For matrix batches, keep `Cache line audio` enabled when multiple accessories or animations use the
same dialogue line. The queue will share deterministic speech/Rhubarb artifacts under
`outputs/speech/cache/`, `results/rhubarb/cache/`, and `outputs/lipsync/cache/` while still writing
separate character manifests, GLBs, renders, and gallery cards.
Cached gallery cards are tagged with `cache:line`, `cache-key:<hash>`,
`audio-cache:hit|miss`, and `lipsync-cache:hit|miss`, and the QA details block includes the
shared cache paths.
Use `Preview matrix` to estimate cache reuse before queueing. Use `Warm cache` to prepare the
missing unique dialogue-line speech/Rhubarb/timeline artifacts without rendering characters; keep
Dry run enabled to inspect the planned warm commands first.
Use `Warm + render matrix` for the production path: the webapp creates a coordinator job, runs any
missing cache warm jobs first, and queues the matrix renders only after the warm stage succeeds.
Ordinary matrix runs are capped by `PERSON_FACTORY_MAX_BATCH_JOBS` (`24` by default). Enable
`Chunk large matrix` only for bigger production sweeps: it keeps the normal per-render-batch size
at 24, but allows up to `PERSON_FACTORY_MAX_CHUNKED_MATRIX_JOBS` (`768` by default) by splitting
the render stage into multiple `render_matrix_batch.py` children after one shared cache-warm stage.
Cached lip-sync chunk batches also skip per-child combined-gallery/contact-sheet rebuilds and run
up to four chunks in parallel by default. Drop back to serial mode when diagnosing a noisy render or
when the machine is already saturated:

```bash
WEBAPP_MAX_CONCURRENT_JOBS=1 PERSON_FACTORY_CHUNK_WORKERS=1 \
docker compose --profile webapp up -d --build webapp
```

Validation can be sharded across a Godot control pool while render/export still use the primary
Godot service. Start the optional internal validator and restart the webapp with both service URLs:

```bash
docker compose --profile godot --profile godot-pool up -d godot-viewer godot-viewer-validator-2
GODOT_VALIDATION_URLS=http://godot-viewer:8790,http://godot-viewer-validator-2:8790 \
docker compose --profile webapp up -d --build webapp
```

Start the Godot game-asset/control API:

```bash
cd /srv/nvme-data/containers/projects/vrm_automation
docker compose --profile godot up -d godot-viewer
```

Control API:

```bash
curl http://127.0.0.1:8790/health
curl http://127.0.0.1:8790/assets
curl -X POST http://127.0.0.1:8790/load \
  -H 'Content-Type: application/json' \
  -d '{"id":"quick-person-glasses-cheerful"}'
curl -X POST http://127.0.0.1:8790/export-game-asset \
  -H 'Content-Type: application/json' \
  -d '{"id":"quick-person-glasses-cheerful"}'
curl -X POST http://127.0.0.1:8790/export-all-game-assets
```

Face/lip-sync control:

```bash
python3 scripts/generate_lipsync.py \
  "Hello world, I can talk now." \
  outputs/lipsync/hello_world.face.json

curl http://127.0.0.1:8790/face-profile
curl -X POST http://127.0.0.1:8790/lipsync \
  -H 'Content-Type: application/json' \
  -d '{"path":"/workspace/outputs/lipsync/hello_world.face.json"}'
curl http://127.0.0.1:8790/lipsync-status
python3 scripts/validate_godot_lipsync.py \
  --control-url http://127.0.0.1:8790 \
  --max-assets 5 \
  --output results/godot_lipsync_validation_latest.json
```

`scripts/face_profile.py` maps VRoid/VRM shape keys into canonical visemes (`aa`, `ih`, `ou`,
`ee`, `oh`) and expressions (`blink`, `happy`, `angry`, `sad`, `surprised`). `animate-smoke`
writes that face profile into each animation report. `scripts/generate_lipsync.py` currently
creates deterministic text-derived face timelines; it is the runtime contract that an audio solver
such as Rhubarb, Audio2Face, ARKit capture, or another phoneme model can replace later.

The Godot layer is for interactive/runtime use: load generated GLBs, play animations, drive
expressions, and save `.tscn` game-asset scenes under `godot_viewer/game_assets/`. Exported scenes
are small wrapper files that reference GLBs under `godot_viewer/game_assets/glb/`; the exporter
hardlinks those GLBs to optimized outputs when possible and falls back to copy when needed. This
keeps the `.tscn` files in the hundreds of bytes instead of embedding 70MB+ character scenes while
avoiding duplicate GLB storage for batched variants. For talking characters, the Godot asset catalog
and exported `.tscn` metadata include `lipsync_timeline`, so a runtime can trigger the same
phoneme/Rhubarb timeline used in the gallery. The default container runs Godot headless so the
control API stays lightweight; use the Blender pose renders for fast PNG QA. Blender remains the
source of truth for VRM import, fitting, cleanup, and GLB export.

MuseTalk can be used as an optional talking-video preview backend. It is a 2D audio-driven video
model, so it complements rather than replaces the Godot/VRM blendshape control path. The local
adapter writes MuseTalk-compatible job/config files without requiring model weights in this repo:

```bash
python3 scripts/musetalk_adapter.py \
  --character-id gen-004-female-glasses-cheerful-wave \
  --source-media /workspace/outputs/batch/gen-004-female-glasses-cheerful-wave_pose_renders/pose_portrait_0024.png \
  --audio /workspace/outputs/speech/person_factory_hello.wav \
  --result-name gen-004-female-glasses-cheerful-wave_hello.mp4 \
  --output results/musetalk/gen-004-female-glasses-cheerful-wave.job.json \
  --inference-config /workspace/results/musetalk/gen-004-female-glasses-cheerful-wave.yaml \
  --use-float16 \
  --write-config
```

See `research/musetalk_integration.md` for the upstream requirements and the boundary between
controllable game assets and talking-video renders.

Build MuseTalk jobs from a batch result and an audio manifest:

```bash
python3 scripts/musetalk_batch.py \
  results/batch_person_factory_lipsync_phoneme1_latest.json \
  config/musetalk_audio.hello.json \
  results/musetalk/lipsync_phoneme1
```

For lip-sync jobs, the batch builder prefers the active mouth QA frame, such as
`pose_portrait_0009.png`, over a neutral portrait frame.

Publish finished MuseTalk MP4s back into character reports so the gallery embeds them:

```bash
python3 scripts/musetalk_run_batch.py \
  results/musetalk/lipsync_phoneme1 \
  --batch-result results/batch_person_factory_lipsync_phoneme1_latest.json \
  --publish \
  --status-output results/musetalk/run_status.json
```

Run a limited batch through the optional container and publish any completed outputs:

```bash
python3 scripts/musetalk_run_batch.py \
  results/musetalk/lipsync_phoneme1 \
  --batch-result results/batch_person_factory_lipsync_phoneme1_latest.json \
  --limit 1 \
  --run \
  --publish
```

`musetalk_run_batch.py --run` auto-selects the GPU with the most free memory by default. Set
`MUSE_TALK_GPU_ID=7` or pass `--gpu-id 7` when you want a specific device.

Run one generated job in the optional MuseTalk container after populating the model cache with the
upstream MuseTalk weights layout:

```bash
MUSE_TALK_MODEL_CACHE=./input/musetalk_models \
MUSE_TALK_JOB_JSON=/workspace/results/musetalk/lipsync_phoneme1/lip-phoneme-001-pixel-talk_person_factory_hello.job.json \
docker compose --profile musetalk run --rm musetalk
```

The MuseTalk profile is intentionally separate from the default workflow because it has a heavy
CUDA/PyTorch/MMLab runtime and large model weights. The default person factory tests only validate
job/config generation and gallery integration.

TTS/STT are intentionally external. Use the existing speech services on `josh@amd0`/`josh@amd1` to
create or transcribe WAVs, then reference those files in a MuseTalk audio manifest such as
`config/musetalk_audio.hello.json`.
`config/speech_services.example.json` tracks the discovered endpoints:

- `http://amd1:8102/v1/audio/speech`: Qwen 1.7B voice-design TTS
- `http://amd1:8103/v1/audio/speech`: Qwen 0.6B base/clone TTS
- `http://amd0:8098/v1/audio/transcriptions`: CrispASR fast STT
- `http://amd0:8099/v1/audio/transcriptions`: CrispASR plus STT

Check them before a talking-video batch:

```bash
python3 scripts/speech_services.py config/speech_services.example.json --check-health
```

Generate a WAV with the remote Qwen voice-design service and write a MuseTalk audio manifest:

```bash
python3 scripts/generate_speech.py \
  "Hello. I am a generated character ready for a quick talking video test." \
  outputs/speech/person_factory_hello.wav \
  --voice "warm clear character voice" \
  --seed 42 \
  --clip-id person_factory_hello \
  --manifest results/musetalk/person_factory_hello_audio.json
```

Create a talking person directly from text:

```bash
python3 scripts/create_talking_person_from_text.py \
  "Hello. I can become a controllable game character from one line of text." \
  --id text-host-001 \
  --name "Text Host 001" \
  --base female \
  --accessory glasses \
  --animation talk_idle \
  --render
```

That command calls the configured TTS service, writes the audio manifest, runs the Rhubarb
audio-to-face pipeline, then renders/finalizes the generated character when `--render` is set.

Create several talking people while rendering through one Blender batch:

```bash
python3 scripts/create_talking_batch_from_text.py \
  config/text_talking_batch.example.json \
  --render \
  --texture-size 768
```

The batch command prepares speech and Rhubarb timelines per person, combines the generated
one-person manifests, then runs the existing manifest renderer once so base-scene caching can help.
The example uses `render_profile: fast_lipsync`, which renders only portrait frames `3,9,16` for
faster mouth-shape QA. Use `render_profile: auto` when you need the fuller front+portrait frame set.
For unchanged prompts, add `"reuse_audio": true` per person or in defaults to skip TTS and iterate
only on alignment, rendering, optimization, or gallery settings. Add `"reuse_lipsync": true` too
when the audio and face timeline are both unchanged and you only need to rerender/refinalize.

Quick STT sanity check for the generated WAV:

```bash
python3 scripts/transcribe_speech.py \
  outputs/speech/person_factory_hello.wav \
  --service fast \
  --output results/stt/person_factory_hello_fast.json \
  --lipsync-output outputs/lipsync/person_factory_hello_stt_fast.face.json
```

This creates a transcript manifest and a fast text-derived VRM viseme timeline. It is a useful
batch fallback when no forced-alignment/phoneme timestamps are available yet.

For tighter pre-recorded audio timing, use Rhubarb Lip Sync JSON and convert it into the same VRM
face timeline format:

```bash
python3 scripts/create_talking_person.py \
  outputs/speech/person_factory_hello.wav \
  --id lip-rhubarb-now \
  --name "Rhubarb Now" \
  --base male \
  --accessory glasses \
  --animation talk_idle \
  --render
```

This normalizes generated WAVs through the MuseTalk ffmpeg container when host ffmpeg is not
available, runs Rhubarb, writes a VRM face timeline, creates a one-person manifest, then optionally
runs the existing Blender/finalize pipeline.

The lower-level Rhubarb commands are useful for diagnosis:

```bash
input/rhubarb/Rhubarb-Lip-Sync-1.14.0-Linux/rhubarb \
  -f json \
  -o results/rhubarb/person_factory_hello_clean.json \
  outputs/speech/person_factory_hello_clean.wav

python3 scripts/rhubarb_adapter.py \
  results/rhubarb/person_factory_hello_clean.json \
  outputs/lipsync/person_factory_hello_rhubarb.face.json \
  --intensity 0.9
```

If Rhubarb rejects a generated WAV, normalize it first with ffmpeg to 16 kHz mono PCM.

```bash
curl -F file=@outputs/speech/person_factory_hello.wav \
  http://amd0:8098/v1/audio/transcriptions
```

Create a fast review batch of named people with animated GLBs and PNG QA renders:

```bash
python3 scripts/download_poly_pizza_assets.py
docker compose --profile tools run --rm blender-vrm blender --background \
  --python scripts/install_addons.py \
  --python scripts/run_manifest_in_blender.py -- \
  config/person_factory.quick.json results/batch_person_factory_in_blender_latest.json
python3 scripts/build_batch_gallery.py \
  results/batch_person_factory_in_blender_latest.json \
  outputs/batch/person_factory_in_blender_gallery.html
```

The quick person manifest skips `.blend` and `.vrm` exports, keeps animated `.glb` output, and
renders only frames `24,48,72` from front, side, and portrait cameras. The default render engine is
Workbench with texture, cavity, and shadow preview enabled because it keeps QA renders near
1-2 seconds each in this container. Use `animation_preset`, `render_pose_frames`, `render_engine`,
`render_width`, `render_height`, `export_blend`, and `export_vrm` in manifests to trade speed for
fidelity. It also caches repeated base models as clean `.blend` scenes under `cache/base_scenes/`;
the first run builds the cache, then later runs reuse it.

Finalize a finished batch for review/game export in one pass:

```bash
python3 scripts/finalize_batch.py \
  results/batch_person_factory_in_blender_latest.json \
  outputs/batch/person_factory_review.html \
  --export-godot
```

The finalize step optimizes GLBs into `outputs/batch_optimized/`, refreshes QA scoring, rebuilds
the gallery, and optionally asks the Godot API to export referenced game assets. The default
optimizer caps textures at 1024px, avoids geometry-compression extensions, and densifies sparse
accessors so Godot can import morph-heavy character GLBs without sparse-accessor warning spam. Use
`--preserve-sparse-accessors` only when you prefer the smallest GLB over cleaner Godot logs.

Relink older copied Godot GLBs to identical optimized outputs after large batches:

```bash
python3 scripts/relink_godot_game_assets.py
python3 scripts/relink_godot_game_assets.py --apply
```

Relink older raw batch GLBs to identical render-cache outputs:

```bash
python3 scripts/relink_render_cache_outputs.py
python3 scripts/relink_render_cache_outputs.py --apply
```

Generate a larger controllable batch programmatically:

```bash
python3 scripts/make_person_manifest.py 80 \
  config/person_factory.generated_asset_pool.json \
  config/poly_pizza_assets.json
python3 scripts/batch_pipeline.py \
  config/person_factory.generated_asset_pool.json \
  results/batch_asset_pool_dry_run.json \
  --dry-run
docker compose run --rm blender-vrm blender --background \
  --python scripts/install_addons.py \
  --python scripts/run_manifest_in_blender.py -- \
  config/person_factory.generated_asset_pool.json results/batch_person_factory_in_blender_latest.json
python3 scripts/finalize_batch.py \
  results/batch_person_factory_in_blender_latest.json \
  outputs/batch/person_factory_review.html \
  --export-godot
```

Download and run the vetted Poly Pizza accessory batch:

```bash
python3 scripts/download_poly_pizza_assets.py
python3 scripts/batch_pipeline.py config/outfit_batch.poly_pizza.json results/batch_poly_pizza_latest.json
```

`config/poly_pizza_assets.json` is the current vetted accessory pool. It tracks source URL,
creator, license, license URL, attribution requirement, category, and local output path for 20
downloadable GLB assets. The pool mixes CC0 and Creative Commons Attribution 3.0 assets, so exported
review manifests and generated jobs preserve license/source metadata for filtering and attribution.

Use `--dry-run` to inspect planned environment values without launching Blender:

```bash
python3 scripts/batch_pipeline.py --dry-run config/outfit_batch.example.json
```

The default still-render engine is Workbench for fast iteration. EEVEE is available for selective
beauty stills, but in the current CPU/headless path it took about 110 seconds for one portrait PNG:

```bash
RENDER_ENGINE=BLENDER_EEVEE_NEXT docker compose --profile tools run --rm animate-smoke
```

Open a debug shell:

```bash
docker compose --profile debug run --rm shell
```

## Current Judgment

The workflow can become a reliable assisted pipeline, not a universal one-click converter.
Containerized Blender can cover import, inspection, scripted cleanup, export, and repeatable checks.
The remaining hard parts are asset rights, topology-specific rig/mesh repair, clothing fit, physics,
and subjective visual approval.

Material Combiner is no longer installed by default. The current default is to audit materials first
and only opt into Material Combiner with `INSTALL_MATERIAL_COMBINER=1` when a test model proves the
atlas workflow needs it.
