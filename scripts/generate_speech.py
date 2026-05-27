from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.speech_services import load_speech_services, tts_payload


def build_tts_request(
    services: dict,
    service: str,
    text: str,
    *,
    voice: str | None = None,
    seed: int = -1,
    language: str = "English",
) -> tuple[str, dict]:
    tts_services = services.get("tts", {})
    if service not in tts_services:
        raise ValueError(f"unknown TTS service: {service}")
    return tts_services[service]["url"], tts_payload(text, voice=voice, seed=seed, language=language)


def validate_wav_bytes(data: bytes, min_bytes: int = 4096) -> None:
    if len(data) < min_bytes:
        raise ValueError(f"TTS returned too little audio data: {len(data)} bytes")
    if not data.startswith(b"RIFF"):
        raise ValueError("TTS response is not a WAV/RIFF payload")


def synthesize_wav(url: str, payload: dict, output_path: Path, timeout: float = 240.0) -> int:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "audio/wav"},
        method="POST",
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read()
    validate_wav_bytes(data)
    output_path.write_bytes(data)
    return len(data)


def build_audio_clip(
    *,
    clip_id: str,
    path: str,
    text: str,
    service: str,
    voice: str | None = None,
    seed: int = -1,
    use_float16: bool = True,
) -> dict:
    return {
        "id": clip_id,
        "path": path,
        "source": {
            "service": f"tts.{service}",
            "text": text,
            "voice": voice,
            "seed": int(seed),
        },
        "use_float16": bool(use_float16),
    }


def write_audio_manifest(clips: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "schema": "vrm-person-factory.musetalk-audio-batch.v1",
                "clips": clips,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def workspace_path(path: Path) -> str:
    try:
        return "/workspace/" + path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def parse_args(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a dialogue WAV from a configured TTS service.")
    parser.add_argument("text")
    parser.add_argument("output_wav", nargs="?", default="outputs/speech/latest.wav")
    parser.add_argument("--services", default="config/speech_services.example.json")
    parser.add_argument("--service", default="voice_design")
    parser.add_argument("--clip-id")
    parser.add_argument("--voice")
    parser.add_argument("--seed", type=int, default=-1)
    parser.add_argument("--language", default="English")
    parser.add_argument("--manifest", default="results/musetalk/generated_audio.json")
    return parser.parse_args(args)


def main(args: list[str] | None = None) -> None:
    parsed = parse_args(sys.argv[1:] if args is None else args)
    services = load_speech_services(parsed.services)
    url, payload = build_tts_request(
        services,
        parsed.service,
        parsed.text,
        voice=parsed.voice,
        seed=parsed.seed,
        language=parsed.language,
    )
    output_wav = Path(parsed.output_wav)
    size = synthesize_wav(url, payload, output_wav)
    clip_id = parsed.clip_id or output_wav.stem
    clip = build_audio_clip(
        clip_id=clip_id,
        path=workspace_path(output_wav),
        text=parsed.text,
        service=parsed.service,
        voice=parsed.voice,
        seed=parsed.seed,
    )
    write_audio_manifest([clip], Path(parsed.manifest))
    print(json.dumps({"wav": str(output_wav), "bytes": size, "manifest": parsed.manifest, "clip": clip}, indent=2))


if __name__ == "__main__":
    main()
