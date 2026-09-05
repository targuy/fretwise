"""Tests de l'appariement jeu ↔ partition et de la notation.

Deux niveaux : l'algorithme d'appariement sur des notes fabriquées à la main
(rapide, exhaustif), puis la chaîne complète signal → trames → notes → verdicts
→ score sur une phrase synthétisée, qui est le seul test qui prouve que les
maillons s'emboîtent vraiment.
"""
from __future__ import annotations

import numpy as np
import pytest

from fretwise.listening.frames import analyze_stream
from fretwise.listening.matching import (
    CORRECT,
    EXTRA,
    MISSED,
    WRONG_PITCH,
    ExpectedNote,
    Matcher,
    build_events,
    compute_score,
)
from fretwise.listening.notes import DetectedNote, segment_notes
from fretwise.listening.pitch import midi_to_hz

SR = 48000.0


def _played(onset: float, midi: int, cents: float = 0.0) -> DetectedNote:
    return DetectedNote(onset=onset, midi=midi, cents=cents, confidence=0.95)


def _expected(pairs: list[tuple[float, int]], dur: float = 0.3) -> list[ExpectedNote]:
    return [
        ExpectedNote(onset=o, duration=dur, midi=m, note_id=f"n{i}")
        for i, (o, m) in enumerate(pairs)
    ]


def _run(events, notes):
    matcher = Matcher(events)
    for note in notes:
        matcher.feed(note)
    matcher.finish()
    return matcher.verdicts


# ── Regroupement en événements ───────────────────────────────────────────


def test_build_events_groups_simultaneous_notes_into_one_chord() -> None:
    notes = _expected([(1.0, 40), (1.005, 47), (1.01, 52), (2.0, 55)])
    events = build_events(notes)
    assert len(events) == 2
    assert events[0].midis == (40, 47, 52)
    assert events[0].is_chord
    assert not events[1].is_chord


def test_build_events_keeps_close_but_distinct_onsets_apart() -> None:
    events = build_events(_expected([(1.0, 40), (1.10, 47)]))
    assert len(events) == 2


def test_build_events_orders_by_onset_regardless_of_input_order() -> None:
    events = build_events(_expected([(2.0, 55), (1.0, 40)]))
    assert [e.onset for e in events] == [1.0, 2.0]
    assert [e.index for e in events] == [0, 1]


def test_build_events_carries_note_ids_for_the_ui() -> None:
    events = build_events(_expected([(1.0, 40), (1.005, 47)]))
    assert events[0].note_ids == ("n0", "n1")


# ── Appariement ──────────────────────────────────────────────────────────


def test_note_played_on_time_and_in_tune_is_correct() -> None:
    events = build_events(_expected([(1.0, 55)]))
    verdicts = _run(events, [_played(1.02, 55)])
    assert [v.status for v in verdicts] == [CORRECT]
    assert verdicts[0].timing_error == pytest.approx(0.02)


def test_note_played_at_the_wrong_pitch_is_flagged_not_missed() -> None:
    events = build_events(_expected([(1.0, 55)]))
    verdicts = _run(events, [_played(1.01, 56)])
    assert verdicts[0].status == WRONG_PITCH
    assert verdicts[0].expected_midi == 55
    assert verdicts[0].detected_midi == 56


def test_nothing_played_in_the_window_is_missed() -> None:
    events = build_events(_expected([(1.0, 55)]))
    verdicts = _run(events, [])
    assert [v.status for v in verdicts] == [MISSED]
    assert verdicts[0].note_ids == ("n0",)


def test_note_played_outside_every_window_is_extra() -> None:
    events = build_events(_expected([(1.0, 55)]))
    verdicts = _run(events, [_played(1.0, 55), _played(3.0, 60)])
    assert [v.status for v in verdicts] == [CORRECT, EXTRA]
    assert verdicts[1].event_index is None


def test_chord_is_validated_by_any_of_its_pitches() -> None:
    # La détection est monophonique : compter cinq notes manquées pour un accord
    # correctement plaqué serait faux, et décourageant.
    events = build_events(_expected([(1.0, 40), (1.005, 47), (1.01, 52)]))
    verdicts = _run(events, [_played(1.01, 47)])
    assert [v.status for v in verdicts] == [CORRECT]
    assert verdicts[0].note_ids == ("n0", "n1", "n2")


def test_one_note_cannot_satisfy_two_consecutive_events() -> None:
    # Sans le rabotage des fenêtres, la note jouée à 1.0 satisferait aussi
    # l'événement de 1.1, et la note réellement manquée passerait inaperçue.
    events = build_events(_expected([(1.0, 55), (1.10, 55)]))
    verdicts = _run(events, [_played(1.0, 55)])
    assert [v.status for v in verdicts] == [CORRECT, MISSED]


def test_closest_note_wins_when_several_land_in_one_window() -> None:
    events = build_events(_expected([(1.0, 55)]))
    verdicts = _run(events, [_played(0.90, 55), _played(1.01, 55)])
    assert verdicts[0].status == CORRECT
    assert verdicts[0].timing_error == pytest.approx(0.01)
    assert verdicts[1].status == EXTRA


def test_right_pitch_is_preferred_over_a_closer_wrong_one() -> None:
    events = build_events(_expected([(1.0, 55)]))
    verdicts = _run(events, [_played(1.0, 60), _played(1.05, 55)])
    assert verdicts[0].status == CORRECT
    assert verdicts[0].detected_midi == 55


# ── Direct ───────────────────────────────────────────────────────────────


def test_advance_emits_only_events_whose_window_has_closed() -> None:
    events = build_events(_expected([(1.0, 55), (2.0, 57)]))
    matcher = Matcher(events)
    matcher.feed(_played(1.0, 55))
    assert matcher.advance(1.05) == []          # fenêtre encore ouverte
    emitted = matcher.advance(1.20)
    assert [v.status for v in emitted] == [CORRECT]
    assert matcher.advance(1.90) == []


def test_streaming_verdicts_match_the_batch_result() -> None:
    # Le score affiché en jouant doit être celui du bilan de fin de prise.
    events = build_events(_expected([(1.0, 55), (1.5, 57), (2.0, 59), (2.5, 60)]))
    notes = [_played(1.01, 55), _played(1.52, 58), _played(2.48, 60)]
    batch = _run(events, notes)
    live = Matcher(events)
    streamed = []
    for note in notes:
        live.feed(note)
        streamed.extend(live.advance(note.onset))
    streamed.extend(live.finish())
    assert [(v.status, v.event_index) for v in streamed] \
        == [(v.status, v.event_index) for v in batch]


# ── Notation ─────────────────────────────────────────────────────────────


def test_score_of_a_flawless_take_is_one_hundred() -> None:
    events = build_events(_expected([(1.0, 55), (1.5, 57)]))
    verdicts = _run(events, [_played(1.0, 55), _played(1.5, 57)])
    score = compute_score(verdicts, len(events))
    assert score.score == pytest.approx(100.0)
    assert score.pitch_accuracy == 1.0
    assert score.timing_rms_ms == pytest.approx(0.0)


def test_score_of_a_take_where_nothing_was_played_is_zero() -> None:
    events = build_events(_expected([(1.0, 55), (1.5, 57)]))
    score = compute_score(_run(events, []), len(events))
    assert score.score == 0.0
    assert score.missed == 2


def test_score_penalises_a_steady_lag_through_the_timing_term() -> None:
    events = build_events(_expected([(1.0, 55), (1.5, 57)]))
    late = _run(events, [_played(1.06, 55), _played(1.56, 57)])
    score = compute_score(late, len(events))
    assert score.pitch_accuracy == 1.0
    assert score.score < 100.0
    assert score.timing_bias_ms == pytest.approx(60.0, abs=1.0)


def test_score_separates_a_steady_lag_from_an_erratic_one() -> None:
    # Même erreur moyenne nulle, mais l'un est décalé et l'autre imprécis :
    # le biais et l'écart-type doivent les distinguer, sinon le conseil donné
    # au joueur serait le même dans les deux cas.
    events = build_events(_expected([(1.0, 55), (1.5, 57)]))
    erratic = compute_score(_run(events, [_played(1.05, 55), _played(1.45, 57)]), 2)
    assert abs(erratic.timing_bias_ms) < 1.0
    assert erratic.timing_rms_ms == pytest.approx(50.0, abs=1.0)


def test_score_penalises_extra_notes_but_caps_the_penalty() -> None:
    events = build_events(_expected([(1.0, 55), (1.5, 57)]))
    ghosts = [_played(3.0 + i * 0.3, 60) for i in range(8)]
    score = compute_score(_run(events, [_played(1.0, 55), _played(1.5, 57), *ghosts]), 2)
    assert score.extra == 8
    assert score.score == pytest.approx(80.0)   # 100 − plafond de 20 points


def test_score_of_an_empty_part_is_zero_not_a_free_hundred() -> None:
    score = compute_score([], 0)
    assert score.score == 0.0
    assert score.events == 0


def test_score_reports_mean_intonation_error() -> None:
    events = build_events(_expected([(1.0, 55), (1.5, 57)]))
    verdicts = _run(events, [_played(1.0, 55, cents=18.0), _played(1.5, 57, cents=-22.0)])
    score = compute_score(verdicts, 2)
    assert score.mean_abs_cents == pytest.approx(20.0)


# ── Chaîne complète, depuis le signal ────────────────────────────────────


def _pluck(hz: float, dur: float, decay: float = 0.6) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for k in range(1, 9):
        out += (0.4 / k) * np.sin(2 * np.pi * hz * k * t + 0.7 * k)
    return out * np.exp(-np.arange(n) / (decay * SR))


def _render(events: list[tuple[float, int]], total: float) -> np.ndarray:
    sig = np.zeros(int(total * SR))
    for onset, midi in events:
        start = int(onset * SR)
        note = _pluck(midi_to_hz(midi), 0.34)
        end = min(len(sig), start + len(note))
        sig[start:end] += note[: end - start]
    return sig


PHRASE = [(0.50, 52), (0.90, 55), (1.30, 57), (1.70, 59), (2.10, 60)]


def _score_of(played: list[tuple[float, int]]):
    expected = build_events(_expected(PHRASE))
    notes = segment_notes(analyze_stream(_render(played, 2.9), SR))
    verdicts = _run(expected, notes)
    return compute_score(verdicts, len(expected)), verdicts


def test_end_to_end_faithful_performance_scores_high() -> None:
    score, verdicts = _score_of(PHRASE)
    assert [v.status for v in verdicts] == [CORRECT] * 5
    assert score.pitch_accuracy == 1.0
    # Le résiduel de datation (~10 ms) empêche le 100 pur : c'est la précision
    # réelle de la chaîne, pas un défaut de jeu.
    assert score.score > 90.0
    assert abs(score.timing_bias_ms) < 15.0


def test_end_to_end_wrong_note_is_pinpointed() -> None:
    wrong = list(PHRASE)
    wrong[2] = (1.30, 58)          # un demi-ton trop haut
    score, verdicts = _score_of(wrong)
    statuses = [v.status for v in verdicts]
    assert statuses == [CORRECT, CORRECT, WRONG_PITCH, CORRECT, CORRECT]
    assert verdicts[2].expected_midi == 57
    assert verdicts[2].detected_midi == 58
    assert score.correct == 4


def test_end_to_end_skipped_note_is_reported_missed() -> None:
    score, verdicts = _score_of([e for e in PHRASE if e[0] != 1.30])
    assert [v.status for v in verdicts] == [CORRECT, CORRECT, MISSED, CORRECT, CORRECT]
    assert score.missed == 1


def test_end_to_end_rushed_performance_shows_a_negative_bias() -> None:
    rushed = [(onset - 0.05, midi) for onset, midi in PHRASE]
    score, verdicts = _score_of(rushed)
    assert [v.status for v in verdicts] == [CORRECT] * 5
    assert score.timing_bias_ms < -35.0
