from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.generate_lipsync import build_lipsync_timeline
from scripts.speech_services import load_speech_services


def build_stt_request(services: dict, service: str, model: str | None = None) -> tuple[str, dict]:
    stt_services = services.get("stt", {})
    if service not in stt_services:
        raise ValueError(f"unknown STT service: {service}")
    fields = {}
    if model:
        fields["model"] = model
    return stt_services[service]["url"], fields


def workspace_path(path: Path) -> str:
    try:
        return "/workspace/" + path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def encode_multipart(fields: dict, file_field: str, file_path: Path, boundary: str | None = None) -> tuple[bytes, str]:
    boundary = boundary or f"vrm-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                f"{value}\r\n".encode("utf-8"),
            ]
        )
    chunks.extend(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{file_path.name}"\r\n'
            ).encode("utf-8"),
            b"Content-Type: audio/wav\r\n\r\n",
            file_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def normalize_transcript_response(response: dict) -> dict:
    text = str(response.get("text", "")).strip()
    if not text:
        raise ValueError("transcription response did not include text")
    segments = response.get("segments") or response.get("words") or []
    if not isinstance(segments, list):
        segments = []
    return {"text": text, "segments": segments}


def transcribe_audio(url: str, audio_path: Path, fields: dict | None = None, timeout: float = 240.0) -> dict:
    if not audio_path.exists():
        raise ValueError(f"audio file does not exist: {audio_path}")
    body, content_type = encode_multipart(fields or {}, "file", audio_path)
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": content_type, "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    return normalize_transcript_response(data)


def write_transcript_manifest(
    output_path: Path,
    *,
    audio_path: str,
    service: str,
    transcript: dict,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "schema": "vrm-person-factory.transcript.v1",
                "audio_path": audio_path,
                "service": service,
                "text": transcript["text"],
                "segments": transcript.get("segments", []),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def write_lipsync_from_transcript(transcript: dict, output_path: Path) -> dict:
    timeline = build_lipsync_timeline(transcript["text"])
    timeline["source"] = {
        "mode": "stt-text",
        "text": transcript["text"],
        "segment_count": len(transcript.get("segments", [])),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(timeline, indent=2, sort_keys=True), encoding="utf-8")
    return timeline


def parse_args(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transcribe a WAV through configured STT and optionally emit a fast viseme timeline.")
    parser.add_argument("audio_wav")
    parser.add_argument("--services", default="config/speech_services.example.json")
    parser.add_argument("--service", default="fast")
    parser.add_argument("--model")
    parser.add_argument("--output", default="results/stt/latest_transcript.json")
    parser.add_argument("--lipsync-output")
    return parser.parse_args(args)


def main(args: list[str] | None = None) -> None:
    parsed = parse_args(sys.argv[1:] if args is None else args)
    services = load_speech_services(parsed.services)
    url, fields = build_stt_request(services, parsed.service, model=parsed.model)
    audio_path = Path(parsed.audio_wav)
    transcript = transcribe_audio(url, audio_path, fields)
    workspace_audio = workspace_path(audio_path)
    write_transcript_manifest(
        Path(parsed.output),
        audio_path=workspace_audio,
        service=parsed.service,
        transcript=transcript,
    )
    result = {
        "transcript": parsed.output,
        "text": transcript["text"],
        "audio_path": workspace_audio,
    }
    if parsed.lipsync_output:
        timeline = write_lipsync_from_transcript(transcript, Path(parsed.lipsync_output))
        result["lipsync_output"] = parsed.lipsync_output
        result["cues"] = len(timeline["cues"])
        result["duration"] = timeline["duration"]
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
