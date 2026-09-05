"""Tests de la segmentation en notes jouées (fretwise.listening.notes).

Les signaux sont synthétiques mais joués comme une prise réelle : une phrase
est rendue en un seul signal continu, puis passée dans la même chaîne que le
navigateur (trames de 64 ms, saut de 8 ms). Ce qui est vérifié, ce n'est pas
« YIN trouve la bonne fréquence » — c'est le sujet de test_listening_pitch —
mais « la bonne note est datée au bon moment ».
"""
from __future__ import annotations

import numpy as np
import pytest

from fretwise.listening.frames import DEFAULT_HOP_SEC, analyze_stream
from fretwise.listening.notes import (
    LAG_PERIODS,
    NoteSegmenter,
    onset_lag_sec,
    segment_notes,
)
from fretwise.listening.pitch import midi_to_hz

SR = 48000.0


def _pluck(hz: float, dur_sec: float, sr: float = SR, decay: float = 0.6) -> np.ndarray:
    """Corde pincée grossière : harmoniques en 1/k sous enveloppe décroissante."""
    n = int(dur_sec * sr)
    t = np.arange(n) / sr
    out = np.zeros(n)
    for k in range(1, 9):
        out += (0.4 / k) * np.sin(2 * np.pi * hz * k * t + 0.7 * k)
    return out * np.exp(-np.arange(n) / (decay * sr))


def _phrase(
    events: list[tuple[float, int, float]], total_sec: float, sr: float = SR
) -> np.ndarray:
    """Rend une phrase en un signal continu.

    Args:
        events: ``(onset_sec, midi, dur_sec)`` pour chaque note.
        total_sec: Durée du signal rendu.
        sr: Fréquence d'échantillonnage.
    """
    sig = np.zeros(int(total_sec * sr))
    for onset, midi, dur in events:
        start = int(onset * sr)
        note = _pluck(midi_to_hz(midi), dur, sr)
        end = min(len(sig), start + len(note))
        sig[start:end] += note[: end - start]
    return sig


def _detect(events, total_sec, **kwargs):
    frames = analyze_stream(_phrase(events, total_sec), SR, hop_sec=DEFAULT_HOP_SEC)
    return segment_notes(frames, **kwargs)


# ── Modèle de retard ─────────────────────────────────────────────────────


def test_onset_lag_is_larger_for_low_notes() -> None:
    # C'est toute la raison d'être du modèle : une correction constante
    # décalerait les cordes graves d'une vingtaine de millisecondes.
    low = onset_lag_sec(midi_to_hz(40))
    high = onset_lag_sec(midi_to_hz(64))
    assert low > high
    assert low - high == pytest.approx(LAG_PERIODS * (1 / 82.41 - 1 / 329.63), abs=1e-4)


def test_onset_lag_grows_with_the_hop() -> None:
    assert onset_lag_sec(200.0, 0.016) > onset_lag_sec(200.0, 0.004)


def test_onset_lag_unvoiced_frequency_stays_finite() -> None:
    assert 0.0 < onset_lag_sec(0.0) < 0.1


# ── Datation des attaques ────────────────────────────────────────────────


@pytest.mark.parametrize("midi", [40, 45, 50, 55, 59, 64, 67, 72])
def test_single_note_onset_recovered_within_10ms(midi: int) -> None:
    notes = _detect([(0.5, midi, 0.6)], 1.3)
    assert len(notes) == 1
    assert notes[0].midi == midi
    assert abs(notes[0].onset - 0.5) < 0.010


def test_onset_error_has_no_systematic_bias_across_the_register() -> None:
    # Le vrai risque du modèle de retard : bien recalé en moyenne mais penché
    # d'un bout à l'autre du manche. On vérifie les extrêmes séparément.
    errors = {}
    for midi in (40, 45, 50, 55, 59, 64, 67, 72):
        notes = _detect([(0.5, midi, 0.6)], 1.3)
        errors[midi] = notes[0].onset - 0.5
    low = np.mean([errors[m] for m in (40, 45, 50)])
    high = np.mean([errors[m] for m in (64, 67, 72)])
    assert abs(low - high) < 0.010
    assert abs(np.mean(list(errors.values()))) < 0.006


def test_scale_run_recovers_every_note_in_order() -> None:
    events = [(0.4 + i * 0.35, 52 + i, 0.30) for i in range(8)]
    notes = _detect(events, 0.4 + 8 * 0.35 + 0.5)
    assert [n.midi for n in notes] == [e[1] for e in events]
    for note, (onset, _midi, _dur) in zip(notes, events, strict=True):
        assert abs(note.onset - onset) < 0.015


def test_fast_run_at_sixteenths_is_not_merged() -> None:
    # Doubles-croches à 120 BPM : 125 ms par note. La segmentation doit tenir
    # ce débit, sinon tout trait rapide serait illisible.
    events = [(0.4 + i * 0.125, 55 + i, 0.115) for i in range(8)]
    notes = _detect(events, 2.2)
    assert [n.midi for n in notes] == [e[1] for e in events]


# ── Notes répétées ───────────────────────────────────────────────────────


def test_repeated_notes_separated_by_silence_are_split() -> None:
    events = [(0.4, 57, 0.30), (0.8, 57, 0.30), (1.2, 57, 0.30)]
    notes = _detect(events, 1.9)
    assert len(notes) == 3
    assert all(n.midi == 57 for n in notes)
    for note, (onset, _m, _d) in zip(notes, events, strict=True):
        assert abs(note.onset - onset) < 0.030


def test_repeated_notes_over_a_ringing_string_are_split_by_the_envelope() -> None:
    # Le cas difficile : la corde sonne encore quand on la repince. La hauteur
    # ne varie pas d'un iota et le signal ne redevient jamais silencieux —
    # seule la remontée de niveau distingue les attaques.
    events = [(0.4, 57, 1.6), (0.75, 57, 1.3), (1.10, 57, 1.0)]
    sig = _phrase(events, 2.4)
    notes = segment_notes(analyze_stream(sig, SR, hop_sec=DEFAULT_HOP_SEC))
    assert len(notes) == 3
    assert all(n.midi == 57 for n in notes)
    assert [n.re_attack for n in notes] == [False, True, True]
    for note, (onset, _m, _d) in zip(notes, events, strict=True):
        assert abs(note.onset - onset) < 0.040


def test_sustained_note_is_not_split_into_several() -> None:
    notes = _detect([(0.4, 57, 2.0)], 2.8)
    assert len(notes) == 1


# ── Robustesse ───────────────────────────────────────────────────────────


def test_silence_produces_no_notes() -> None:
    frames = analyze_stream(np.zeros(int(2.0 * SR)), SR)
    assert segment_notes(frames) == []


def test_noise_produces_no_notes() -> None:
    rng = np.random.default_rng(11)
    frames = analyze_stream(rng.normal(0.0, 0.15, int(2.0 * SR)), SR)
    assert segment_notes(frames) == []


def test_isolated_octave_glitch_does_not_create_a_note() -> None:
    # Une trame aberrante isolée ne doit pas devenir une note : c'est ce que
    # MIN_RUN_FRAMES protège.
    frames = analyze_stream(_phrase([(0.4, 57, 1.2)], 2.0), SR)
    poisoned = []
    for i, f in enumerate(frames):
        if i == 60 and f.voiced:
            poisoned.append(type(f)(f.time, f.hz * 2, f.confidence, f.rms, True))
        else:
            poisoned.append(f)
    notes = segment_notes(poisoned)
    assert len(notes) == 1
    assert notes[0].midi == 57


def test_cents_reports_a_detuned_string() -> None:
    hz = midi_to_hz(45) * 2.0 ** (25.0 / 1200.0)
    n = int(1.0 * SR)
    t = np.arange(n) / SR
    sig = np.zeros(int(1.6 * SR))
    start = int(0.4 * SR)
    sig[start:start + n] = 0.3 * np.sin(2 * np.pi * hz * t)
    notes = segment_notes(analyze_stream(sig, SR))
    assert len(notes) == 1
    assert notes[0].midi == 45
    assert 20.0 < notes[0].cents < 30.0


def test_segmenter_streaming_matches_batch() -> None:
    # Le direct et le hors-ligne doivent donner exactement la même chose :
    # sinon un score affiché en jouant différerait du bilan de fin de prise.
    frames = analyze_stream(_phrase([(0.4, 52, 0.3), (0.8, 57, 0.3), (1.2, 60, 0.3)], 1.9), SR)
    batch = segment_notes(frames)
    segmenter = NoteSegmenter()
    streamed = [n for f in frames if (n := segmenter.feed(f)) is not None]
    assert [(n.midi, round(n.onset, 6)) for n in streamed] \
        == [(n.midi, round(n.onset, 6)) for n in batch]
