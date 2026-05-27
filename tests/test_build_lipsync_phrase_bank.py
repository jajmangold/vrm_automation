from scripts.build_lipsync_phrase_bank import (
    EXPECTED_ACTIVE_VISEMES,
    build_phrase_bank,
    phoneme_events_for_text,
    phrase_entry,
)


def test_phrase_entry_scores_complete_active_visemes():
    entry = phrase_entry("Pat met Tim. Go put food.")

    assert entry["quality_grade"] == "A"
    assert entry["missing_active_visemes"] == []
    assert entry["active_visemes"] == EXPECTED_ACTIVE_VISEMES
    assert "IH1" in entry["phonemes"]
    assert entry["lipsync_timeline"].startswith("outputs/lipsync/cache/")


def test_phrase_bank_exports_cache_lines_and_warm_payload():
    bank = build_phrase_bank(
        [
            "Pat met Tim. Go put food.",
            "Bad rhythm.",
        ],
        batch_id="phrase-bank-test",
    )

    assert bank["entry_count"] == 2
    assert bank["cache_line_count"] == 1
    assert bank["cache_lines"][0]["text"] == "Pat met Tim. Go put food."
    assert bank["warm_cache_payload"]["id_prefix"] == "phrase-bank-test"
    assert bank["warm_cache_payload"]["cache_line_audio"] is True
    assert bank["warm_cache_payload"]["dry_run"] is True


def test_phoneme_events_scale_to_audio_duration():
    events = phoneme_events_for_text("Pat met Tim. Go put food.", duration=2.4)

    assert events[0]["time"] == 0.0
    assert events[0]["phoneme"] == "P"
    assert events[0]["duration"] > 0
    assert events[-1]["phoneme"] == "D"
    end_time = events[-1]["time"] + events[-1]["duration"]
    assert abs(end_time - 2.4) < 0.02
