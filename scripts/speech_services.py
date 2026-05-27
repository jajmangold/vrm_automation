from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


def join_url(base_url: str, endpoint: str) -> str:
    return base_url.rstrip("/") + "/" + endpoint.lstrip("/")


def load_speech_services(path: Path | str) -> dict:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    indexed = {}
    for role, services in config.get("services", {}).items():
        indexed[role] = {}
        for name, service in services.items():
            normalized = dict(service)
            normalized["url"] = join_url(service["base_url"], service.get("endpoint", ""))
            indexed[role][name] = normalized
    return indexed


def speech_health_urls(services: dict) -> dict[str, str]:
    urls = {}
    for role, role_services in services.items():
        for name, service in role_services.items():
            urls[f"{role}.{name}"] = join_url(service["base_url"], service.get("health_endpoint", "/health"))
    return urls


def tts_payload(text: str, voice: str | None = None, seed: int = -1, language: str = "English") -> dict:
    payload = {"input": text, "language": language, "seed": int(seed)}
    if voice:
        payload["instruct"] = voice
    return payload


def check_health(url: str, timeout: float = 3.0) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read(2048).decode("utf-8", errors="replace")
            return {"ok": 200 <= response.status < 300, "status": response.status, "body": body}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "body": exc.read(2048).decode("utf-8", errors="replace")}
    except Exception as exc:
        return {"ok": False, "status": None, "body": str(exc)}


def parse_args(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect configured remote TTS/STT services.")
    parser.add_argument("config", nargs="?", default="config/speech_services.example.json")
    parser.add_argument("--check-health", action="store_true")
    return parser.parse_args(args)


def main(args: list[str] | None = None) -> None:
    parsed = parse_args(sys.argv[1:] if args is None else args)
    services = load_speech_services(parsed.config)
    output = {"services": services}
    if parsed.check_health:
        output["health"] = {
            key: check_health(url)
            for key, url in speech_health_urls(services).items()
        }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
