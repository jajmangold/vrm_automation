# Repository Guidelines

## Project Structure & Module Organization

This repository automates VRM character inspection, fitting, animation, rendering, and review. Python automation lives in `scripts/`; unit tests live in `tests/`. Blender and service entry points are defined by `docker-compose.yml` plus root `Dockerfile*` files.

Runtime assets are separated: put source models and caches under `input/`, reports under `results/`, generated media under `outputs/`, and logs under `logs/`. The review UI is in `webapp/`; Godot scenes and scripts are in `godot_viewer/`; notes belong in `research/`.

## Agent-Specific Instructions

Use the Sequential Thinking MCP server before starting work, and again when the plan changes or before significant system changes. For substantial pipeline work, check Atlas first and update it afterward with durable decisions, task status, and completed work.

## Build, Test, and Development Commands

```bash
cp .env.example .env
docker compose --profile tools run --rm download-addons
docker compose build blender-vrm
docker compose run --rm blender-vrm
```

These prepare local configuration, download Blender add-ons, build the Blender image, and run the default headless smoke script.

```bash
python3 -m unittest discover -s tests
./scripts/run_checks.sh
RENDER_POSE_STILLS=0 docker compose --profile tools run --rm animate-smoke
docker compose --profile webapp up webapp
docker compose --profile godot up godot-viewer
```

Use `unittest` and `run_checks.sh` for local quality gates. Use `animate-smoke` for lightweight Blender integration, and start web or Godot profiles only when affected.

## Coding Style & Naming Conventions

Python uses 4-space indentation, clear `snake_case` names, and type hints where useful. Keep changes service-local and prefer existing helpers. Shell scripts should be executable, POSIX-compatible where practical, and named for their workflow, such as `run_musetalk_job.sh`.

## Testing Guidelines

Add or update `tests/test_*.py` for Python behavior. Run the full unit suite before changing fit logic, manifests, reports, speech, or batch orchestration. Avoid long GPU renders as routine tests; use no-render smoke commands unless render output is under test.

## Commit & Pull Request Guidelines

Before committing, run `git status` from this repo root and avoid model weights, caches, database files, or generated renders. Use concise imperative commits, for example `Add outfit fit regression test`. PRs should summarize affected services, include test output, mention changed ports or volumes, and link relevant result files or task IDs.

## Security & Configuration Tips

Keep local secrets in `.env` and never commit them. Keep services bound to localhost unless remote access is intentional. Treat `input/`, `outputs/`, `results/`, model caches, and Docker volumes as large or sensitive runtime data.
