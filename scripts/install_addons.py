import addon_utils
import bpy
import os
from pathlib import Path
import shutil
import tempfile
import zipfile


ADDONS = [
    ("addons/vrm-addon.zip", ("vrm", "VRM")),
    ("addons/mmd-tools.zip", ("mmd", "MMD")),
]

if os.environ.get("INSTALL_MATERIAL_COMBINER") == "1":
    ADDONS.append(("addons/material-combiner.zip", ("material", "combiner", "shotariya")))


def install_zip(path: Path) -> None:
    if not path.exists():
        print(f"addon missing: {path}")
        return
    if path.name == "mmd-tools.zip":
        install_mmd_tools(path)
        return
    print(f"installing addon zip: {path}")
    bpy.ops.preferences.addon_install(filepath=str(path), overwrite=True)


def install_mmd_tools(path: Path) -> None:
    if is_blender_extension_zip(path):
        print(f"installing mmd_tools extension zip: {path}")
        try:
            bpy.ops.extensions.package_install_files(
                filepath=str(path),
                repo="user_default",
                enable_on_install=True,
                overwrite=True,
            )
            return
        except Exception as exc:
            print(f"extension install failed for mmd_tools, trying archive repack: {exc}")

    scripts_dir = Path(bpy.utils.user_resource("SCRIPTS", path="addons", create=True))
    target = scripts_dir / "mmd_tools"
    if target.exists():
        shutil.rmtree(target)

    repacked = repackage_mmd_tools(path)
    if repacked:
        try:
            bpy.ops.extensions.package_install_files(
                filepath=str(repacked),
                repo="user_default",
                enable_on_install=True,
                overwrite=True,
            )
            print(f"installed mmd_tools extension from {repacked}")
            return
        except Exception as exc:
            print(f"extension install failed for mmd_tools, falling back to add-ons path: {exc}")

    with zipfile.ZipFile(path) as archive:
        members = archive.namelist()
        init_candidates = [m for m in members if m.endswith("/mmd_tools/__init__.py")]
        if not init_candidates:
            print(f"mmd_tools package not found in {path}")
            return
        prefix = init_candidates[0].removesuffix("mmd_tools/__init__.py")
        for member in members:
            if not member.startswith(prefix + "mmd_tools/"):
                continue
            rel = member[len(prefix) :]
            dest = scripts_dir / rel
            if member.endswith("/"):
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(archive.read(member))
    print(f"installed mmd_tools into {target}")


def repackage_mmd_tools(path: Path) -> Path | None:
    temp_dir = Path(tempfile.mkdtemp(prefix="mmd_tools_repack_"))
    repacked = temp_dir / "mmd_tools.zip"
    with zipfile.ZipFile(path) as archive:
        members = archive.namelist()
        init_candidates = [m for m in members if m.endswith("/mmd_tools/__init__.py")]
        if not init_candidates:
            print(f"mmd_tools package not found in {path}")
            return None
        prefix = init_candidates[0].removesuffix("mmd_tools/__init__.py")
        with zipfile.ZipFile(repacked, "w", compression=zipfile.ZIP_DEFLATED) as out:
            for member in members:
                if not member.startswith(prefix + "mmd_tools/") or member.endswith("/"):
                    continue
                rel = member[len(prefix + "mmd_tools/") :]
                out.writestr(rel, archive.read(member))
    return repacked


def is_blender_extension_zip(path: Path) -> bool:
    with zipfile.ZipFile(path) as archive:
        return "blender_manifest.toml" in archive.namelist()


def enable_matching(keywords: tuple[str, ...]) -> None:
    addon_utils.modules_refresh()
    candidates = []
    lowered = tuple(k.lower() for k in keywords)
    for module in addon_utils.modules():
        name = module.__name__
        label = getattr(module, "bl_info", {}).get("name", "")
        haystack = f"{name} {label}".lower()
        if all(k in haystack for k in lowered[:1]) or any(k in haystack for k in lowered):
            candidates.append(name)

    for name in sorted(set(candidates)):
        try:
            addon_utils.enable(name, default_set=True, persistent=True)
            print(f"enabled addon: {name}")
        except Exception as exc:
            print(f"could not enable addon {name}: {exc}")


def main() -> None:
    for rel_path, keywords in ADDONS:
        install_zip(Path(rel_path))
        enable_matching(keywords)
    bpy.ops.wm.save_userpref()


if __name__ == "__main__":
    main()
