import json
import wave
from pathlib import Path

from scripts.promote_lipsync_phrase_bank_timelines import promote_phrase_bank, wav_duration


def write_silent_wav(path: Path, duration: float = 1.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 16_000
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * duration))


def test_promote_phrase_bank_writes_phoneme_timeline(tmp_path):
    key = "demo"
    audio_path = tmp_path / "outputs/speech/cache/demo.wav"
    timeline_path = tmp_path / "outputs/lipsync/cache/demo.face.json"
    write_silent_wav(audio_path, duration=2.0)
    bank_path = tmp_path / "config/phrase_bank.json"
    bank_path.parent.mkdir(parents=True)
    bank_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "text": "Pat met Tim. Go put food.",
                        "audio_cache_key": key,
                        "lipsync_timeline": "outputs/lipsync/cache/demo.face.json",
                        "cache_paths": {"audio_wav": "outputs/speech/cache/demo.wav"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = promote_phrase_bank(bank_path, root=tmp_path)
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))

    assert report["promoted_count"] == 1
    assert timeline["source"]["mode"] == "phoneme-events"
    assert timeline["source"]["input_mode"] == "phrase-bank-arpabet"
    assert timeline["source"]["text"] == "Pat met Tim. Go put food."
    assert {cue["viseme"] for cue in timeline["cues"]} >= {"aa", "ee", "ih", "oh", "ou"}


def test_wav_duration_falls_back_for_placeholder_frame_count(tmp_path):
    path = tmp_path / "placeholder.wav"
    write_silent_wav(path, duration=1.25)
    data = bytearray(path.read_bytes())
    data[40:44] = (0xFFFFFFFF).to_bytes(4, "little")
    path.write_bytes(data)

    assert abs(wav_duration(path) - 1.25) < 0.01
