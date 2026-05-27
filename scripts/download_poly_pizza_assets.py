from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path


GLB_RE = re.compile(r"https://static\.poly\.pizza/[^\"&<>]+\.glb")
ALLOWED_LICENSES = {"CC0 1.0", "Creative Commons Attribution 3.0"}
REQUIRED_METADATA = {
    "id",
    "title",
    "creator",
    "license",
    "license_url",
    "source_url",
    "expected_public_id",
    "output_path",
    "category",
}


def find_glb_url(page_html: str) -> str:
    matches = sorted(set(GLB_RE.findall(page_html)))
    if not matches:
        raise ValueError("no static.poly.pizza .glb URL found")
    return matches[0]


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "ignore")


def download(url: str, path: Path) -> int:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    path.write_bytes(data)
    return len(data)


def validate_asset_metadata(asset: dict) -> None:
    missing = sorted(key for key in REQUIRED_METADATA if not asset.get(key))
    if missing:
        raise ValueError(f"{asset.get('id', '<unknown>')} missing metadata: {', '.join(missing)}")
    if asset["license"] not in ALLOWED_LICENSES:
        raise ValueError(f"{asset['id']} has unsupported license: {asset['license']}")
    if asset["expected_public_id"] not in asset["source_url"]:
        raise ValueError(f"{asset['id']} source_url does not contain expected_public_id")


def main() -> None:
    config_path = Path(sys.argv[1] if len(sys.argv) > 1 else "config/poly_pizza_assets.json")
    manifest_path = Path(sys.argv[2] if len(sys.argv) > 2 else "results/poly_pizza_asset_manifest.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    results = []
    for asset in config["assets"]:
        validate_asset_metadata(asset)
        html = fetch_text(asset["source_url"])
        glb_url = find_glb_url(html)
        output_path = Path(asset["output_path"])
        if output_path.exists():
            size_bytes = output_path.stat().st_size
            status = "exists"
        else:
            size_bytes = download(glb_url, output_path)
            status = "downloaded"
        results.append(
            {
                **asset,
                "download_url": glb_url,
                "path": str(output_path),
                "size_bytes": size_bytes,
                "status": status,
            }
        )
    manifest = {"assets": results}
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
