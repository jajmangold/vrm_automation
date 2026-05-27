import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    request = urllib.request.Request(url, headers={"User-Agent": "vrm-automation/0.1"})
    with urllib.request.urlopen(request, timeout=120) as response:
        with tmp_path.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
    tmp_path.replace(output_path)


def main() -> None:
    config_path = Path(sys.argv[1] if len(sys.argv) > 1 else "config/base_models.json")
    manifest_path = Path(sys.argv[2] if len(sys.argv) > 2 else "results/base_model_manifest.json")
    data = json.loads(config_path.read_text(encoding="utf-8"))
    manifest = {
        "created_at_unix": int(time.time()),
        "config_path": str(config_path),
        "models": [],
    }

    for model in data["models"]:
        output_path = Path(model["output_path"])
        expected_sha = model.get("sha256")
        if not output_path.exists():
            print(f"download {model['id']}: {model['url']} -> {output_path}")
            download(model["url"], output_path)
        else:
            print(f"exists {model['id']}: {output_path}")

        actual_sha = sha256_file(output_path)
        status = "ok"
        if expected_sha and actual_sha != expected_sha:
            status = "sha256-mismatch"
        record = {
            **model,
            "path": str(output_path),
            "size_bytes": output_path.stat().st_size,
            "sha256_actual": actual_sha,
            "status": status,
        }
        manifest["models"].append(record)
        if status != "ok":
            raise SystemExit(f"{model['id']} sha256 mismatch: expected {expected_sha}, got {actual_sha}")

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
