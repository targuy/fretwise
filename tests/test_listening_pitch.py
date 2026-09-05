"""Tests de la détection de hauteur du module d'écoute (fretwise.listening.pitch).

Ces tests épinglent le comportement que le worklet JS
(``web/static/js/worklets/pitch-worklet.js``) doit reproduire : ils sont le
contrat de parité entre l'implémentation de référence et celle du navigateur.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from fretwise.listening.pitch import (
    STANDARD_TUNING_MIDI,
    cents_between,
    detect_pitch,
    hz_to_midi,
    midi_to_hz,
    nearest_semitone,
    nearest_target,
    note_name,
)

SR = 48000.0
# 64 ms : ce que le worklet garde en tampon (5 périodes du E2 le plus grave).
FRAME = 3072


def _sine(hz: float, n: int = FRAME, sr: float = SR, amp: float = 0.3) -> np.ndarray:
    t = np.arange(n) / sr
    return amp * np.sin(2.0 * np.pi * hz * t)


def _harmonics(
    hz: float, weights: dict[int, float], n: int = FRAME, sr: float = SR
) -> np.ndarray:
    """Empile des harmoniques avec des phases décalées (pas de crête artificielle)."""
    t = np.arange(n) / sr
    out = np.zeros(n)
    for k, w in weights.items():
        out += w * np.sin(2.0 * np.pi * hz * k * t + 0.7 * k)
    return out


def _plucked(hz: float, n: int = FRAME, sr: float = SR) -> np.ndarray:
    """Corde pincée grossière : harmoniques en 1/k sous enveloppe décroissante."""
    weights = {k: 0.4 / k for k in range(1, 9)}
    env = np.exp(-np.arange(n) / (0.7 * sr))
    return _harmonics(hz, weights, n, sr) * env


# ── Détection sur signaux synthétiques ───────────────────────────────────


@pytest.mark.parametrize("hz", [82.41, 110.0, 146.83, 196.0, 246.94, 329.63, 440.0, 880.0])
def test_detect_pitch_pure_sine_returns_within_one_cent(hz: float) -> None:
    est = detect_pitch(_sine(hz), SR)
    assert est.voiced
    assert abs(cents_between(est.hz, hz)) < 1.0


@pytest.mark.parametrize("hz", [82.41, 110.0, 196.0, 329.63])
def test_detect_pitch_harmonic_stack_returns_fundamental(hz: float) -> None:
    sig = _harmonics(hz, {1: 0.3, 2: 0.2, 3: 0.15, 4: 0.1, 5: 0.06})
    est = detect_pitch(sig, SR)
    assert est.voiced
    assert abs(cents_between(est.hz, hz)) < 5.0


@pytest.mark.parametrize("hz", [82.41, 110.0, 196.0])
def test_detect_pitch_missing_fundamental_returns_true_period(hz: float) -> None:
    # Harmoniques 2/3/4 sans fondamentale : le piège classique de
    # l'autocorrélation brute, que la normalisation cumulative de YIN doit tenir.
    est = detect_pitch(_harmonics(hz, {2: 0.25, 3: 0.2, 4: 0.15}), SR)
    assert est.voiced
    assert abs(cents_between(est.hz, hz)) < 10.0


@pytest.mark.parametrize("hz", [82.41, 110.0, 196.0, 329.63])
def test_detect_pitch_plucked_string_returns_fundamental(hz: float) -> None:
    est = detect_pitch(_plucked(hz), SR)
    assert est.voiced
    assert abs(cents_between(est.hz, hz)) < 10.0


def test_detect_pitch_detuned_string_reports_the_offset() -> None:
    # E2 vingt cents trop haut : l'accordeur doit lire l'écart, pas l'arrondir.
    target = midi_to_hz(40)
    est = detect_pitch(_plucked(target * 2.0 ** (20.0 / 1200.0)), SR)
    assert est.voiced
    _, cents = nearest_target(est.hz, STANDARD_TUNING_MIDI)
    assert 15.0 < cents < 25.0


@pytest.mark.parametrize("sr", [44100.0, 48000.0, 96000.0])
def test_detect_pitch_various_sample_rates_returns_same_pitch(sr: float) -> None:
    n = int(0.064 * sr)
    est = detect_pitch(_plucked(196.0, n, sr), sr)
    assert est.voiced
    assert abs(cents_between(est.hz, 196.0)) < 10.0


# ── Rejets ───────────────────────────────────────────────────────────────


def test_detect_pitch_silence_returns_unvoiced() -> None:
    est = detect_pitch(np.zeros(FRAME), SR)
    assert not est.voiced
    assert est.hz == 0.0
    assert est.rms == 0.0


def test_detect_pitch_white_noise_returns_unvoiced() -> None:
    rng = np.random.default_rng(1234)
    est = detect_pitch(rng.normal(0.0, 0.2, FRAME), SR)
    assert not est.voiced


def test_detect_pitch_below_silence_floor_returns_unvoiced() -> None:
    # Un signal parfaitement périodique mais inaudible ne doit pas faire bouger
    # l'aiguille — sinon l'accordeur s'agite sur le souffle de l'ampli.
    est = detect_pitch(_sine(196.0, amp=0.0005), SR)
    assert not est.voiced


def test_detect_pitch_frame_too_short_returns_unvoiced() -> None:
    est = detect_pitch(_sine(196.0, n=128), SR)
    assert not est.voiced


def test_detect_pitch_above_analysis_band_returns_unvoiced() -> None:
    # 2 kHz est au-dessus de F_MAX_HZ : hors périmètre guitare, on préfère ne
    # rien afficher plutôt qu'une sous-harmonique inventée.
    est = detect_pitch(_sine(2000.0), SR)
    assert not est.voiced


def test_detect_pitch_reports_rms_even_when_unvoiced() -> None:
    rng = np.random.default_rng(7)
    est = detect_pitch(rng.normal(0.0, 0.25, FRAME), SR)
    assert est.rms > 0.2  # le vu-mètre reste vivant sur du bruit


def test_detect_pitch_confidence_higher_on_tone_than_noise() -> None:
    rng = np.random.default_rng(99)
    tone = detect_pitch(_plucked(196.0), SR)
    noise = detect_pitch(rng.normal(0.0, 0.2, FRAME), SR)
    assert tone.confidence > noise.confidence


# ── Conversions musicales ────────────────────────────────────────────────


def test_hz_to_midi_concert_a_returns_69() -> None:
    assert hz_to_midi(440.0) == pytest.approx(69.0)


def test_hz_to_midi_honours_alternate_diapason() -> None:
    assert hz_to_midi(432.0, a4_hz=432.0) == pytest.approx(69.0)


def test_midi_to_hz_low_e_returns_82_41() -> None:
    assert midi_to_hz(40) == pytest.approx(82.4069, abs=1e-3)


def test_midi_to_hz_round_trips_hz_to_midi() -> None:
    for midi in range(28, 89):
        assert hz_to_midi(midi_to_hz(midi)) == pytest.approx(float(midi))


def test_hz_to_midi_non_positive_raises() -> None:
    with pytest.raises(ValueError):
        hz_to_midi(0.0)


@pytest.mark.parametrize(
    ("midi", "expected"),
    [(40, "E2"), (45, "A2"), (50, "D3"), (55, "G3"), (59, "B3"), (64, "E4"), (69, "A4")],
)
def test_note_name_standard_tuning_returns_scientific_pitch(midi: int, expected: str) -> None:
    assert note_name(midi) == expected


def test_cents_between_one_semitone_returns_100() -> None:
    assert cents_between(midi_to_hz(41), midi_to_hz(40)) == pytest.approx(100.0)


def test_cents_between_flat_note_returns_negative() -> None:
    assert cents_between(440.0 * 2.0 ** (-10.0 / 1200.0), 440.0) == pytest.approx(-10.0)


def test_nearest_semitone_slightly_sharp_a_returns_a4_and_offset() -> None:
    midi, cents = nearest_semitone(440.0 * 2.0 ** (12.0 / 1200.0))
    assert midi == 69
    assert cents == pytest.approx(12.0)


def test_nearest_semitone_never_exceeds_half_a_semitone() -> None:
    for hz in np.linspace(80.0, 900.0, 400):
        _, cents = nearest_semitone(float(hz))
        assert abs(cents) <= 50.0 + 1e-6


@pytest.mark.parametrize("index", range(6))
def test_nearest_target_open_string_returns_its_own_index(index: int) -> None:
    hz = midi_to_hz(STANDARD_TUNING_MIDI[index])
    found, cents = nearest_target(hz, STANDARD_TUNING_MIDI)
    assert found == index
    assert cents == pytest.approx(0.0, abs=1e-9)


def test_nearest_target_compares_in_cents_not_hertz() -> None:
    # 4 Hz au-dessus du E2 (82,41) = +82 cents, donc plus proche du F2 en
    # cents comme en Hz ; le vrai piège est l'inverse : 4 Hz sous le E4 (329,63)
    # ne vaut que -21 cents et doit rester sur le E4, alors qu'un tri en Hz
    # brut placerait les deux écarts sur un pied d'égalité.
    found, cents = nearest_target(329.63 - 4.0, STANDARD_TUNING_MIDI)
    assert found == 5
    assert -25.0 < cents < -18.0


def test_nearest_target_seven_string_tuning_finds_low_b() -> None:
    seven = (35, *STANDARD_TUNING_MIDI)  # B1 + EADGBE
    found, cents = nearest_target(midi_to_hz(35), seven)
    assert found == 0
    assert cents == pytest.approx(0.0, abs=1e-9)


def test_nearest_target_empty_targets_raises() -> None:
    with pytest.raises(ValueError):
        nearest_target(440.0, [])


def test_nearest_target_matches_a_hand_computed_deviation() -> None:
    hz = midi_to_hz(50) * 2.0 ** (-7.0 / 1200.0)
    found, cents = nearest_target(hz, STANDARD_TUNING_MIDI)
    assert found == 2
    assert cents == pytest.approx(-7.0)
    assert math.isclose(midi_to_hz(50, 440.0), 146.8324, abs_tol=1e-3)
