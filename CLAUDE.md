# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An assisted (not one-click) pipeline that turns VRM/PMX/GLB character models into
controllable, game-ready, optionally talking characters. The work splits across four runtimes
wired together by `docker-compose.yml` profiles:

- **Blender (headless)** — the source of truth for model import, rig/material inspection, outfit
  fitting, animation, GLB/VRM export, and PNG pose QA renders. Runs the VRM Add-on + `mmd_tools`.
- **Host Python (`scripts/`)** — orchestration, manifest building, batch coordination, gallery
  generation, GLB optimization, speech/lip-sync, and the image-guided placement solver. No Blender.
- **Godot (headless, control API)** — runtime use: load optimized GLBs, play animations, drive
  expressions/lip-sync, and export `.tscn` game assets. HTTP API on `:8790`.
- **Webapp** — review/QA UI and batch job coordinator. HTTP server on `:8780` (host) /`:8765` (container).

MuseTalk (2D talking-video) is an optional, heavyweight complementary backend, kept on its own profile.

## Commands

```bash
# Setup (once)
cp .env.example .env
docker compose --profile tools run --rm download-addons   # add-on ZIPs into addons/
docker compose build blender-vrm

# Local quality gate (run before changing fit, manifest, report, speech, or batch logic)
./scripts/run_checks.sh                    # unit tests + compose config + no-render Blender smoke
python3 -m unittest discover -s tests      # unit tests only
python3 -m unittest tests.test_placement_solver            # single test module
python3 -m unittest tests.test_placement_solver.TestClass.test_method   # single test

# Blender integration without slow PNG renders
RENDER_POSE_STILLS=0 docker compose --profile tools run --rm animate-smoke

# Long-lived services (start only the profile you need)
docker compose --profile webapp up -d webapp        # http://127.0.0.1:8780
docker compose --profile godot up -d godot-viewer   # http://127.0.0.1:8790
docker compose --profile debug run --rm shell       # debug shell
```

`tests/` are pure-Python and do **not** require Blender — host scripts are designed to be unit-testable
in isolation from `bpy`. Avoid long GPU renders as routine tests; use no-render smoke commands unless
render output is specifically under test. Most `scripts/X.py` have a matching `tests/test_X.py`.

## The Blender boundary (important)

`scripts/` contains two distinct kinds of module, and confusing them is the most common mistake:

- **Blender-side** (`import bpy` at top): `animate_smoke.py`, `run_manifest_in_blender.py`,
  `inspect_model.py`, `material_audit.py`, `blender_silhouette_fit.py`, `set_blender_object_pose.py`,
  `install_addons.py`, `create_sample_outfit.py`, and the `vrm_*`/`blender_necktie_*` probes. These run
  **only** inside the Blender container via `blender --background --python ...` and cannot be imported by
  host code or tests.
- **Host-side** (everything else): orchestration and pure logic. These are unit-tested and never import `bpy`.

Note that Blender-side scripts still `import` host-side modules (e.g. `animate_smoke.py` imports
`asset_classifier`, `fit_checks`, `face_profile`, `render_profiles`) — keep that shared logic free of `bpy`.

## Core pipeline flow

The "person factory" is the main production path. Stages:

1. **Manifest** — `make_person_manifest.py` / `person_factory_jobs.py` build a JSON manifest of jobs.
   Manifests are `config/person_factory.*.json`; `*.requests.json` are the matching request payloads.
2. **Render** — `batch_pipeline.py` resolves per-job environment, then Blender runs `animate_smoke.py`
   (single) or `run_manifest_in_blender.py` (batch, with base-scene caching under `cache/base_scenes/`).
   `render_matrix_batch.py` handles large chunked matrix sweeps.
3. **Finalize** — `finalize_batch.py` optimizes GLBs into `outputs/batch_optimized/` (`optimize_glb.py`),
   re-scores QA (`qa_scoring.py`/`score_batch.py`/`review_quality.py`), rebuilds the gallery
   (`build_batch_gallery.py`), writes a contact sheet, and can trigger Godot game-asset export.
4. **Gallery / catalog** — `build_combined_gallery.py` + `character_catalog_index.py` produce the
   searchable all-assets browser the webapp serves via `/api/characters`.

The webapp (`person_factory_webapp.py`) drives stages 1–4 as background jobs, including cache-warm →
render matrix coordination. It runs Docker commands through the mounted `/var/run/docker.sock`.

## Accessory placement subsystem

Fitting wearables/props is image-guided and deterministic. The canonical loop (see
`docs/accessory_attachment_standard.md`) is:

```
Qwen target image -> SAM target mask -> Blender object-mask render -> silhouette pose optimization
```

OpenCV is for *metrics only* (IoU, centroid/box error) — never to move the object. The real Blender
transform is adjusted by the optimizer. Key modules: `placement_solver.py` / `placement_methods.py` /
`placement_api.py` (deterministic solving), `asset_classifier.py` (category inference:
`neck_chest`/`head_face`/`torso_back`/`torso_front`/`unknown`), `accessory_visual_calibration.py`
(Qwen+SAM measurement → `fit_overrides`), `silhouette_pose_optimizer.py`, `blender_silhouette_fit.py`.
Learned placements are saved as anchors/profiles in `config/accessory_attachment_profiles.json` and
asset `fit_overrides`, then reused. Treat Qwen output as a *visual target proposal*; accept only after
re-rendered PNG QA.

## Speech & lip-sync

TTS/STT are intentionally external (remote services on `amd0`/`amd1`, see
`config/speech_services.example.json`). The face-timeline format is canonical: `face_profile.py` maps
VRoid/VRM shape keys to visemes (`aa ih ou ee oh`) + expressions. `generate_lipsync.py` (text-derived)
and `rhubarb_adapter.py` (Rhubarb JSON → timeline) both emit `*.face.json`, the runtime contract the
Godot `/lipsync` endpoint and MuseTalk consume. `create_talking_person*.py` chain TTS → Rhubarb →
manifest → render. Matrix batches share deterministic speech/Rhubarb/timeline artifacts via
`outputs/speech/cache/`, `results/rhubarb/cache/`, `outputs/lipsync/cache/` (`cache:line` tags).

## Directory layout & data hygiene

- `config/` — manifests, asset pools (`poly_pizza_assets.json` is the vetted accessory catalog with
  license metadata), example configs. Highly churned with generated `*.json`.
- `input/` `outputs/` `results/` `logs/` `cache/` — large/sensitive runtime data, **gitignored**.
  Source models go in `input/`, reports in `results/`, generated media in `outputs/`.
- `godot_viewer/game_assets/` — small `.tscn` wrappers that reference (hardlinked) GLBs under
  `game_assets/glb/` (gitignored); never embed full character scenes.
- `webapp/` — static `factory.{html,css,js}` served alongside galleries.

Before committing: run `git status` from repo root and keep model weights, caches, DB files, and
generated renders out. Use concise imperative commit messages; keep services bound to localhost.

## Conventions

- Python: 4-space indent, `snake_case`, `from __future__ import annotations`, type hints where useful.
  Host scripts insert the repo root on `sys.path` (`sys.path.insert(0, ...parents[1])`) so
  `from scripts.X import Y` works both as a module and under Blender.
- Many CLIs share flags: `--dry-run` (inspect planned env without launching Blender), `*_latest.json`
  result naming, `--skip-optimize`. Prefer existing helpers and keep changes service-local.
- See `AGENTS.md` and `README.md` for the full command catalog (calibration, MuseTalk, Godot control API).
