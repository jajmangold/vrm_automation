from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.generate_lipsync import normalized_viseme, phoneme_to_viseme, text_to_visemes
from scripts.person_factory_jobs import cached_line_paths, line_cache_key


EXPECTED_ACTIVE_VISEMES = ["aa", "ee", "ih", "oh", "ou"]

DEFAULT_PHRASES = [
    "Pat met Tim. Go put food.",
    "Maya kept red tools near Owen.",
    "Ivan made cool tea before Hugo spoke.",
    "Ava sees quick moves from Toby.",
    "Theo paid Lulu five coins today.",
    "Nina brought red peach pie to school.",
    "Milo gave Eve two bright photos.",
    "Olive can fix fresh huge green doors.",
]

PHONEME_LEXICON = {
    "ava": ["EY1", "V", "AH0"],
    "before": ["B", "IH0", "F", "AO1", "R"],
    "blue": ["B", "L", "UW1"],
    "bright": ["B", "R", "AY1", "T"],
    "brought": ["B", "R", "AO1", "T"],
    "can": ["K", "AE1", "N"],
    "coins": ["K", "OY1", "N", "Z"],
    "cool": ["K", "UW1", "L"],
    "doors": ["D", "AO1", "R", "Z"],
    "eve": ["IY1", "V"],
    "five": ["F", "AY1", "V"],
    "fix": ["F", "IH1", "K", "S"],
    "food": ["F", "UW1", "D"],
    "from": ["F", "R", "AH1", "M"],
    "fresh": ["F", "R", "EH1", "SH"],
    "gave": ["G", "EY1", "V"],
    "go": ["G", "OW1"],
    "green": ["G", "R", "IY1", "N"],
    "huge": ["HH", "Y", "UW1", "JH"],
    "hugo": ["HH", "Y", "UW1", "G", "OW0"],
    "ivan": ["AY1", "V", "AH0", "N"],
    "keeps": ["K", "IY1", "P", "S"],
    "kept": ["K", "EH1", "P", "T"],
    "lulu": ["L", "UW1", "L", "UW0"],
    "made": ["M", "EY1", "D"],
    "maya": ["M", "AY1", "AH0"],
    "met": ["M", "EH1", "T"],
    "milo": ["M", "AY1", "L", "OW0"],
    "moves": ["M", "UW1", "V", "Z"],
    "near": ["N", "IH1", "R"],
    "nina": ["N", "IY1", "N", "AH0"],
    "olive": ["AA1", "L", "IH0", "V"],
    "owen": ["OW1", "AH0", "N"],
    "paid": ["P", "EY1", "D"],
    "pat": ["P", "AE1", "T"],
    "peach": ["P", "IY1", "CH"],
    "photos": ["F", "OW1", "T", "OW2", "Z"],
    "pie": ["P", "AY1"],
    "put": ["P", "UH1", "T"],
    "quick": ["K", "W", "IH1", "K"],
    "red": ["R", "EH1", "D"],
    "school": ["S", "K", "UW1", "L"],
    "sees": ["S", "IY1", "Z"],
    "spoke": ["S", "P", "OW1", "K"],
    "tea": ["T", "IY1"],
    "theo": ["TH", "IY1", "OW0"],
    "tim": ["T", "IH1", "M"],
    "toby": ["T", "OW1", "B", "IY0"],
    "today": ["T", "AH0", "D", "EY1"],
    "tools": ["T", "UW1", "L", "Z"],
    "two": ["T", "UW1"],
}


def active_visemes_for_text(text: str) -> list[str]:
    visemes = [normalized_viseme(value) for value in text_to_visemes(text)]
    return [value for value in EXPECTED_ACTIVE_VISEMES if value in visemes]


def words_for_text(text: str) -> list[str]:
    word = []
    words = []
    for character in text.lower():
        if character.isalpha() or character == "'":
            word.append(character)
        elif word:
            words.append("".join(word).strip("'"))
            word = []
    if word:
        words.append("".join(word).strip("'"))
    return [value for value in words if value]


def phonemes_for_text(text: str) -> list[str]:
    phonemes = []
    for word in words_for_text(text):
        phonemes.extend(PHONEME_LEXICON.get(word, []))
        phonemes.append("SIL")
    while phonemes and phonemes[-1] == "SIL":
        phonemes.pop()
    return phonemes


def phoneme_events_for_text(text: str, *, duration: float | None = None) -> list[dict[str, Any]]:
    phonemes = phonemes_for_text(text)
    if not phonemes:
        return []
    weights = [1.6 if phoneme_to_viseme(phoneme) != "rest" else 1.0 for phoneme in phonemes]
    unit = float(duration) / sum(weights) if duration else 0.075
    events = []
    time = 0.0
    for phoneme, weight in zip(phonemes, weights, strict=True):
        event_duration = round(max(0.04, unit * weight), 3)
        events.append({"time": round(time, 3), "duration": event_duration, "phoneme": phoneme})
        time += event_duration
    return events


def active_visemes_for_phonemes(phonemes: list[str]) -> list[str]:
    visemes = [phoneme_to_viseme(phoneme) for phoneme in phonemes]
    return [value for value in EXPECTED_ACTIVE_VISEMES if value in visemes]


def phrase_entry(text: str, *, seed: int = -1, voice: str = "warm clear presenter voice", language: str = "English") -> dict[str, Any]:
    request = {
        "text": text,
        "voice": voice,
        "seed": seed,
        "language": language,
    }
    key = line_cache_key(request)
    phonemes = phonemes_for_text(text)
    active = active_visemes_for_phonemes(phonemes) or active_visemes_for_text(text)
    missing = [value for value in EXPECTED_ACTIVE_VISEMES if value not in active]
    paths = cached_line_paths(key)
    return {
        "text": text,
        "audio_cache_key": key,
        "lipsync_timeline": paths["lipsync_timeline"],
        "cache_paths": paths,
        "phonemes": phonemes,
        "active_visemes": active,
        "missing_active_visemes": missing,
        "quality_grade": "A" if not missing else "review",
    }


def build_phrase_bank(
    phrases: list[str],
    *,
    batch_id: str = "full-viseme-cache-bank",
    seed: int = -1,
    voice: str = "warm clear presenter voice",
    language: str = "English",
) -> dict[str, Any]:
    entries = [phrase_entry(text, seed=seed, voice=voice, language=language) for text in phrases if text.strip()]
    cache_lines = [
        {
            "text": entry["text"],
            "audio_cache_key": entry["audio_cache_key"],
            "lipsync_timeline": entry["lipsync_timeline"],
        }
        for entry in entries
        if not entry["missing_active_visemes"]
    ]
    return {
        "schema": "vrm-person-factory.lipsync-phrase-bank.v1",
        "batch_id": batch_id,
        "expected_active_visemes": EXPECTED_ACTIVE_VISEMES,
        "entry_count": len(entries),
        "cache_line_count": len(cache_lines),
        "entries": entries,
        "cache_lines": cache_lines,
        "warm_cache_payload": {
            "id_prefix": batch_id,
            "lines": "\n".join(line["text"] for line in cache_lines),
            "cache_line_audio": True,
            "dry_run": True,
            "reuse_audio": True,
            "reuse_lipsync": True,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a complete-viseme phrase bank for lip-sync cache warming.")
    parser.add_argument("--phrases", help="Newline-delimited phrase file. Defaults to built-in short lines.")
    parser.add_argument("--batch-id", default="full-viseme-cache-bank")
    parser.add_argument("--seed", type=int, default=-1)
    parser.add_argument("--voice", default="warm clear presenter voice")
    parser.add_argument("--language", default="English")
    parser.add_argument("--output", default="config/lipsync_phrase_bank.full_viseme.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    phrases = DEFAULT_PHRASES
    if args.phrases:
        phrases = [line.strip() for line in Path(args.phrases).read_text(encoding="utf-8").splitlines() if line.strip()]
    bank = build_phrase_bank(phrases, batch_id=args.batch_id, seed=args.seed, voice=args.voice, language=args.language)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bank, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(output), "entry_count": bank["entry_count"], "cache_line_count": bank["cache_line_count"]}, indent=2))


if __name__ == "__main__":
    main()
