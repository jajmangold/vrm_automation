from __future__ import annotations

import argparse
import json
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_lipsync_phrase_bank import EXPECTED_ACTIVE_VISEMES, active_visemes_for_phonemes, phoneme_events_for_text
from scripts.generate_lipsync import build_lipsync_timeline_from_phonemes


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        rate = handle.getframerate()
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
    duration = frames / float(rate) if rate else 0.0
    if duration > 600 and rate and channels and sample_width:
        # Some local TTS WAVs have a placeholder RIFF frame count. For PCM,
        # the file payload size gives the usable duration for timeline scaling.
        payload_bytes = max(0, path.stat().st_size - 44)
        duration = payload_bytes / float(rate * channels * sample_width)
    return round(duration, 3)


def promote_entry(entry: dict, *, root: Path = ROOT, overwrite: bool = True) -> dict:
    key = str(entry.get("audio_cache_key") or "").strip()
    text = str(entry.get("text") or "").strip()
    cache_paths = entry.get("cache_paths", {}) if isinstance(entry.get("cache_paths"), dict) else {}
    audio_path = root / str(cache_paths.get("audio_wav") or f"outputs/speech/cache/{key}.wav")
    timeline_path = root / str(entry.get("lipsync_timeline") or cache_paths.get("lipsync_timeline") or f"outputs/lipsync/cache/{key}.face.json")
    if not key or not text:
        return {"status": "skipped", "reason": "missing-key-or-text", "audio_cache_key": key}
    if not audio_path.exists():
        return {"status": "skipped", "reason": "missing-audio", "audio_cache_key": key, "audio_wav": str(audio_path)}
    if timeline_path.exists() and not overwrite:
        return {"status": "skipped", "reason": "timeline-exists", "audio_cache_key": key, "timeline": str(timeline_path)}

    duration = wav_duration(audio_path)
    events = phoneme_events_for_text(text, duration=duration)
    active = active_visemes_for_phonemes([str(event["phoneme"]) for event in events])
    missing = [value for value in EXPECTED_ACTIVE_VISEMES if value not in active]
    if missing:
        return {"status": "skipped", "reason": "missing-visemes", "audio_cache_key": key, "missing_active_visemes": missing}

    timeline = build_lipsync_timeline_from_phonemes(
        events,
        source_metadata={"mode": "phrase-bank-arpabet", "text": text, "audio_cache_key": key},
        source_schema="vrm-person-factory.phoneme-events.v1",
        source_path="config/lipsync_phrase_bank.full_viseme.json",
    )
    timeline_path.parent.mkdir(parents=True, exist_ok=True)
    timeline_path.write_text(json.dumps(timeline, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "status": "ok",
        "audio_cache_key": key,
        "text": text,
        "timeline": str(timeline_path),
        "audio_wav": str(audio_path),
        "duration": timeline["duration"],
        "phoneme_count": len(events),
        "active_visemes": active,
    }


def promote_phrase_bank(path: Path, *, root: Path = ROOT, overwrite: bool = True) -> dict:
    bank = json.loads(path.read_text(encoding="utf-8"))
    results = [promote_entry(entry, root=root, overwrite=overwrite) for entry in bank.get("entries", [])]
    return {
        "schema": "vrm-person-factory.promote-lipsync-phrase-bank-timelines.v1",
        "status": "ok" if all(item["status"] in {"ok", "skipped"} for item in results) else "review",
        "source": str(path),
        "promoted_count": sum(1 for item in results if item["status"] == "ok"),
        "skipped_count": sum(1 for item in results if item["status"] == "skipped"),
        "results": results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Promote warmed phrase-bank audio to explicit phoneme-event face timelines.")
    parser.add_argument("--phrase-bank", default="config/lipsync_phrase_bank.full_viseme.json")
    parser.add_argument("--output", default="results/promote_lipsync_phrase_bank_timelines_latest.json")
    parser.add_argument("--no-overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = promote_phrase_bank(ROOT / args.phrase_bank, overwrite=not args.no_overwrite)
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"path": str(output), "promoted_count": report["promoted_count"], "skipped_count": report["skipped_count"]}, indent=2))


if __name__ == "__main__":
    main()
