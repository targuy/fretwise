"""Tests for ``fretwise.review.feedback`` — persistence + lock/bias derivation."""
from __future__ import annotations

import json
from pathlib import Path

from fretwise.models import Finger
from fretwise.review.feedback import (
    FeedbackRecord,
    append_corpus,
    feedback_dir,
    load_song_feedback,
    save_choice,
)


def _record(stem: str = "song") -> FeedbackRecord:
    return FeedbackRecord(
        song_stem=stem,
        measure_index=4,
        onset=6.0,
        severity="impossible",
        chosen=[{
            "note_id": 12, "string": 2, "fret": 7, "finger": "ring",
            "hand_position": 5, "onset": 6.0, "pitch": 64, "voice_hint": 0,
        }],
        rejected=[{
            "note_id": 12, "string": 2, "fret": 7, "finger": "pinky",
            "hand_position": 4, "onset": 6.0, "pitch": 64, "voice_hint": 0,
        }],
        reasons=["BIO-STATE-007"],
        features_chosen={"curr_fret": 7.0},
    )


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    rec = _record()
    save_choice(tmp_path, rec)
    loaded = load_song_feedback(tmp_path, "song")
    assert loaded
    assert len(loaded.records) == 1
    assert loaded.records[0].measure_index == 4
    assert loaded.records[0].chosen[0]["finger"] == "ring"


def test_save_appends_multiple(tmp_path: Path) -> None:
    save_choice(tmp_path, _record())
    save_choice(tmp_path, _record())
    assert len(load_song_feedback(tmp_path, "song").records) == 2


def test_load_missing_returns_empty(tmp_path: Path) -> None:
    fb = load_song_feedback(tmp_path, "nope")
    assert not fb
    assert fb.records == []


def test_append_corpus_writes_one_json_line(tmp_path: Path) -> None:
    append_corpus(tmp_path, _record())
    append_corpus(tmp_path, _record())
    corpus = tmp_path / "feedback_corpus.jsonl"
    lines = corpus.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    row = json.loads(lines[0])
    assert row["song_stem"] == "song"
    assert row["features_chosen"]["curr_fret"] == 7.0


def test_locks_reconstruct_fingering_state(tmp_path: Path) -> None:
    save_choice(tmp_path, _record())
    fb = load_song_feedback(tmp_path, "song")
    locks = fb.locks()
    key = (6.0, 64, 0)
    assert key in locks
    state = locks[key]
    assert state.string_num == 2
    assert state.fret == 7
    assert state.finger is Finger.RING


def test_preferred_and_rejected_signatures(tmp_path: Path) -> None:
    save_choice(tmp_path, _record())
    fb = load_song_feedback(tmp_path, "song")
    assert (2, 7, "ring") in fb.preferred_signatures()
    assert (2, 7, "pinky") in fb.rejected_signatures()


def test_feedback_dir_created(tmp_path: Path) -> None:
    d = feedback_dir(tmp_path)
    assert d.exists()
    assert d.name == ".fretwise_feedback"
