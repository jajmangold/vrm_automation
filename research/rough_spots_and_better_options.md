# VRM Automation Rough Spots

Date: 2026-05-22

This project starts from the PULP ANIME workflow in `https://www.youtube.com/watch?v=2GTMiSi-xD8`.
The useful idea is the same: create or acquire an anime humanoid model, normalize it, export VRM,
then tune expressions, physics, and clothing. The implementation should not copy the tutorial
toolchain literally.

## Better Default Path

Use **Blender + VRM Add-on for Blender + mmd_tools** as the primary automation lane.

- VRM Add-on is actively maintained, supports Blender `2.93` through current Blender families, and
  documents a Python automation API.
- `mmd_tools` is the direct PMX/PMD importer/exporter surface. It avoids routing PMX import through
  old CATS behavior unless CATS-specific fixups are required. Use the Blender Extensions artifact
  pinned to `mmd_tools` `4.5.11`, not GitHub `main`.
- Blender headless mode gives us a real CLI boundary for reproducible inspection, cleanup, export,
  and smoke validation.

## Avoid As Core Dependencies

- **Original CATS 0.19 + Blender 2.93**: useful as a compatibility fallback, but too old to be the
  main production container.
- **Team Neoneko CATS**: targets Blender 5.0+, but the repository says the Neoneko version is no
  longer maintained. Treat it as optional until a test proves it is needed.
- **Avatar Toolkit**: good directionally, but still alpha and its GitHub repo was archived/moved.
  Track it, but do not depend on it for the first automated lane.
- **Material Combiner**: do not install by default. The GitHub release page warns to use its own
  download link rather than arbitrary release assets, and user reports indicate atlas-save failures
  can be model/version dependent. Prefer a scripted material audit first, then only opt in when a
  model actually needs atlas work.
- **VRoid Clothing Maker**: GUI/Steam/Early Access workflow. Keep it outside Docker unless we later
  build a Windows GUI automation lane.
- **120byte BOOTH tools**: useful manual utilities, but Windows/GUI and VRM-version-sensitive.
  Prefer VRM Add-on/Blender Python for repeatable blendshape and spring-bone edits where possible.

## Non-Automatable Or Human-Gated Parts

- Asset sourcing and licensing checks from DeviantArt, VRoid Hub, BOOTH, Steam, and random model
  repositories.
- Creative edits: character design intent, texture paint quality, facial expression taste, and
  outfit selection.
- Geometry failures: clipping, missing body parts under clothing, bad normals, and broken UVs.
- Rigging failures: missing humanoid bones, invalid rest pose, wrong bone names, bad weights, or
  models that cannot be normalized without manual rig work.
- Physics tuning: spring-bone colliders and motion quality need visual review.

## Planned Automation Gates

1. Pull/download only from explicit URLs and record source terms in a manifest.
2. Inspect model structure: armature count, mesh count, materials, shape keys, basic humanoid bone
   presence.
3. Normalize/import/export in Blender via scripts.
4. Run a material audit before any atlas operation; use scripted Blender baking later if the audit
   proves draw-call/material count is a real bottleneck.
5. Run a VRM validation smoke: re-import exported VRM and compare object counts, materials, shape
   keys, and warnings.
6. Emit a JSON report and mark any manual gate that remains.

## Sources

- Video workflow: https://www.youtube.com/watch?v=2GTMiSi-xD8
- VRM Add-on for Blender: https://vrm-addon-for-blender.info/en-us/
- VRM Add-on release: https://github.com/saturday06/VRM-Addon-for-Blender/releases/tag/v4.2.0
- mmd_tools extension: https://extensions.blender.org/add-ons/mmd-tools/
- Original CATS release: https://github.com/absolute-quantum/cats-blender-plugin/releases/tag/0.19.0
- Team Neoneko CATS: https://github.com/teamneoneko/Cats-Blender-Plugin
- Avatar Toolkit: https://github.com/teamneoneko/Avatar-Toolkit
- UniVRM export requirements: https://vrm.dev/en/univrm/export/univrm_export/
- Material Combiner: https://github.com/Grim-es/material-combiner-addon/releases/tag/2.1.2.9
- VRoid Clothing Maker: https://store.steampowered.com/app/2330730/VRoid_Clothing_Maker/
