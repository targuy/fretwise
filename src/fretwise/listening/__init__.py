"""Module d'écoute — du signal capté au score de la prise.

La capture vit dans le navigateur (``getUserMedia`` + AudioWorklet) ; ce
package porte tout ce qui décide quelque chose de musical, testé et
réutilisable hors ligne :

- :mod:`~fretwise.listening.pitch` — détection de hauteur (YIN), référence dont
  le worklet navigateur est le miroir ;
- :mod:`~fretwise.listening.frames` — découpage en trames, miroir hors ligne du
  worklet, qui permet de rejouer toute la chaîne sur un fichier ;
- :mod:`~fretwise.listening.notes` — segmentation des trames en notes jouées ;
- :mod:`~fretwise.listening.matching` — appariement avec la partition et notation ;
- :mod:`~fretwise.listening.session` — assemblage, manipulé par le WebSocket.

Voir ``docs/ecoute.md`` pour la conception d'ensemble.
"""
from fretwise.listening.frames import Frame, analyze_stream
from fretwise.listening.matching import (
    ExpectedEvent,
    ExpectedNote,
    Matcher,
    Score,
    Verdict,
    build_events,
    compute_score,
)
from fretwise.listening.notes import (
    DetectedNote,
    NoteSegmenter,
    onset_lag_sec,
    segment_notes,
)
from fretwise.listening.pitch import (
    F_MAX_HZ,
    F_MIN_HZ,
    SILENCE_RMS,
    STANDARD_TUNING_MIDI,
    YIN_THRESHOLD,
    PitchEstimate,
    cents_between,
    detect_pitch,
    hz_to_midi,
    midi_to_hz,
    nearest_semitone,
    nearest_target,
    note_name,
)
from fretwise.listening.session import ListeningSession, SessionError

__all__ = [
    "F_MAX_HZ",
    "F_MIN_HZ",
    "SILENCE_RMS",
    "STANDARD_TUNING_MIDI",
    "YIN_THRESHOLD",
    "DetectedNote",
    "ExpectedEvent",
    "ExpectedNote",
    "Frame",
    "ListeningSession",
    "Matcher",
    "NoteSegmenter",
    "PitchEstimate",
    "Score",
    "SessionError",
    "Verdict",
    "analyze_stream",
    "build_events",
    "cents_between",
    "compute_score",
    "detect_pitch",
    "hz_to_midi",
    "midi_to_hz",
    "nearest_semitone",
    "nearest_target",
    "note_name",
    "onset_lag_sec",
    "segment_notes",
]
