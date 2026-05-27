from __future__ import annotations

import json
import sys
from pathlib import Path


VOWEL_TO_VISEME = {
    "a": "aa",
    "i": "ih",
    "u": "ou",
    "e": "eh",
    "o": "oh",
}

VISEME_NORMALIZATION = {
    "eh": "ee",
}


ARPABET_TO_VISEME = {
    "AA": "aa",
    "AE": "aa",
    "AH": "aa",
    "AO": "oh",
    "AW": "aa",
    "AY": "aa",
    "EH": "ee",
    "ER": "ee",
    "EY": "ee",
    "IH": "ih",
    "IY": "ih",
    "OW": "oh",
    "OY": "oh",
    "UH": "ou",
    "UW": "ou",
    "W": "ou",
    "Y": "ih",
    "SIL": "rest",
    "SP": "rest",
    "PAU": "rest",
    "REST": "rest",
}


def text_to_visemes(text: str) -> list[str]:
    visemes = [VOWEL_TO_VISEME[letter] for letter in text.lower() if letter in VOWEL_TO_VISEME]
    return visemes or ["rest"]


def normalized_viseme(viseme: str) -> str:
    return VISEME_NORMALIZATION.get(viseme, viseme)


def phoneme_to_viseme(phoneme: str) -> str:
    normalized = "".join(character for character in phoneme.upper() if not character.isdigit())
    return ARPABET_TO_VISEME.get(normalized, "rest")


def ordered_unique(values: list[str]) -> list[str]:
    output = []
    for value in values:
        if value and value not in output:
            output.append(value)
    return output


def phoneme_source_summary(
    phoneme_events: list[dict],
    *,
    source_metadata: dict | None = None,
    source_schema: str | None = None,
    source_path: str | Path | None = None,
) -> dict:
    phonemes = [str(event.get("phoneme", event.get("viseme", "rest"))) for event in phoneme_events]
    phoneme_counts = {phoneme: phonemes.count(phoneme) for phoneme in ordered_unique(phonemes)}
    source = {
        "mode": "phoneme-events",
        "event_count": len(phoneme_events),
        "phoneme_count": len(phonemes),
        "unique_phonemes": ordered_unique(phonemes),
        "phoneme_counts": phoneme_counts,
    }
    source_metadata = source_metadata if isinstance(source_metadata, dict) else {}
    if source_metadata.get("mode"):
        source["input_mode"] = str(source_metadata["mode"])
    if source_metadata.get("text"):
        source["text"] = str(source_metadata["text"])
    if source_schema:
        source["source_schema"] = str(source_schema)
    if source_path:
        source["source_path"] = str(source_path)
    return source


def build_lipsync_timeline(text: str, seconds_per_viseme: float = 0.09, intensity: float = 1.0) -> dict:
    raw_visemes = text_to_visemes(text)
    cues = []
    time = 0.0
    for viseme in raw_visemes:
        cues.append(
            {
                "time": round(time, 3),
                "duration": round(seconds_per_viseme, 3),
                "viseme": normalized_viseme(viseme),
                "value": round(intensity, 3),
            }
        )
        time += seconds_per_viseme
        cues.append(
            {
                "time": round(time, 3),
                "duration": round(seconds_per_viseme * 0.28, 3),
                "viseme": "rest",
                "value": 0.0,
            }
        )
        time += seconds_per_viseme * 0.28
    duration = round(max(time, seconds_per_viseme), 3)
    return {
        "schema": "vrm-person-factory.face-timeline.v1",
        "source": {"mode": "text", "text": text},
        "duration": duration,
        "cues": cues,
        "expressions": [
            {"time": 0.0, "duration": duration, "name": "happy", "value": 0.22},
            {"time": round(duration * 0.52, 3), "duration": 0.08, "name": "blink", "value": 1.0},
        ],
    }


def build_lipsync_timeline_from_phonemes(
    phoneme_events: list[dict],
    intensity: float = 1.0,
    *,
    source_metadata: dict | None = None,
    source_schema: str | None = None,
    source_path: str | Path | None = None,
) -> dict:
    cues = []
    duration = 0.0
    phoneme_events = list(phoneme_events)
    for index, event in enumerate(phoneme_events):
        start = round(float(event.get("time", duration)), 3)
        cue_duration = round(float(event.get("duration", 0.08)), 3)
        source_phoneme = str(event.get("phoneme", event.get("viseme", "rest")))
        viseme = phoneme_to_viseme(source_phoneme)
        value = 0.0 if viseme == "rest" else round(float(event.get("value", intensity)), 3)
        cues.append(
            {
                "time": start,
                "duration": cue_duration,
                "viseme": viseme,
                "value": value,
                "source_index": index,
                "source_phoneme": source_phoneme,
            }
        )
        duration = max(duration, start + cue_duration)
    duration = round(duration, 3)
    return {
        "schema": "vrm-person-factory.face-timeline.v1",
        "source": phoneme_source_summary(
            phoneme_events,
            source_metadata=source_metadata,
            source_schema=source_schema,
            source_path=source_path,
        ),
        "duration": duration,
        "cues": cues,
        "expressions": [
            {"time": 0.0, "duration": duration, "name": "happy", "value": 0.16},
            {"time": round(duration * 0.52, 3), "duration": 0.08, "name": "blink", "value": 1.0},
        ],
    }


def main() -> None:
    if "--phonemes-json" in sys.argv:
        index = sys.argv.index("--phonemes-json")
        phoneme_path = Path(sys.argv[index + 1])
        output_path = Path(sys.argv[index + 2] if len(sys.argv) > index + 2 else "outputs/lipsync/latest.face.json")
        data = json.loads(phoneme_path.read_text(encoding="utf-8"))
        timeline = build_lipsync_timeline_from_phonemes(
            data.get("phonemes", data.get("events", [])),
            source_metadata=data.get("source", {}),
            source_schema=data.get("schema"),
            source_path=phoneme_path,
        )
    else:
        text = sys.argv[1] if len(sys.argv) > 1 else "Hello"
        output_path = Path(sys.argv[2] if len(sys.argv) > 2 else "outputs/lipsync/latest.face.json")
        timeline = build_lipsync_timeline(text)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(timeline, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"path": str(output_path), "duration": timeline["duration"], "cues": len(timeline["cues"])}, indent=2))


if __name__ == "__main__":
    main()
