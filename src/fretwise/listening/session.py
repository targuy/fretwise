"""Session d'écoute : assemble segmentation, appariement et notation.

C'est la pièce que le transport (WebSocket) manipule, et elle ne connaît rien
du transport : elle reçoit des trames, rend des verdicts, et clôt sur un score.
Tout ce qui suit est donc testable sans serveur ni navigateur.

**Convention de temps** : les trames arrivent déjà exprimées en *position dans
le morceau*, latence compensée. La conversion appartient au client, seul à
connaître à la fois l'horloge de sa capture, la position de son playback et la
latence calibrée de son périphérique. Le serveur qui tenterait de la refaire
devrait deviner ces trois éléments.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fretwise.listening.frames import DEFAULT_HOP_SEC, Frame
from fretwise.listening.matching import (
    TOLERANCE_SEC,
    ExpectedEvent,
    ExpectedNote,
    Matcher,
    Score,
    Verdict,
    build_events,
    compute_score,
)
from fretwise.listening.notes import NoteSegmenter

# Marge ajoutée à la dernière trame reçue avant de clore les fenêtres. Sans
# elle, un événement serait tranché à l'instant précis où sa fenêtre se ferme,
# alors que la note qui le satisfait peut encore être en cours de confirmation
# dans le segmenteur.
SETTLE_SEC = 0.05


class SessionError(ValueError):
    """Charge utile de session invalide."""


@dataclass
class ListeningSession:
    """Une prise : de la partition attendue au score final.

    Attributes:
        events: Événements attendus, ordre chronologique.
    """

    events: list[ExpectedEvent]
    _segmenter: NoteSegmenter = field(repr=False)
    _matcher: Matcher = field(repr=False)
    _last_time: float = field(default=0.0, init=False, repr=False)

    @classmethod
    def from_notes(
        cls,
        notes: list[ExpectedNote],
        *,
        hop_sec: float = DEFAULT_HOP_SEC,
        tolerance_sec: float = TOLERANCE_SEC,
    ) -> ListeningSession:
        """Ouvre une session sur une liste de notes attendues.

        Args:
            notes: Notes de la partition à jouer.
            hop_sec: Intervalle entre deux trames côté client — entre dans le
                modèle de retard de la segmentation.
            tolerance_sec: Demi-largeur nominale des fenêtres d'appariement.

        Returns:
            La session, prête à recevoir des trames.
        """
        events = build_events(notes)
        return cls(
            events=events,
            _segmenter=NoteSegmenter(hop_sec=hop_sec),
            _matcher=Matcher(events, tolerance=tolerance_sec),
        )

    def feed(self, frames: list[Frame]) -> list[Verdict]:
        """Consomme un lot de trames et rend les verdicts devenus certains.

        Args:
            frames: Trames en position-morceau, ordre chronologique.

        Returns:
            Les verdicts tranchés par ce lot ; souvent vide, ce qui est normal.
        """
        for frame in frames:
            note = self._segmenter.feed(frame)
            if note is not None:
                self._matcher.feed(note)
            self._last_time = max(self._last_time, frame.time)
        return self._matcher.advance(self._last_time - SETTLE_SEC)

    def finish(self) -> tuple[list[Verdict], Score]:
        """Clôt la prise.

        Returns:
            ``(verdicts_restants, score)`` — le score porte sur *toute* la
            prise, pas seulement sur les verdicts renvoyés ici.
        """
        self._segmenter.flush()
        remaining = self._matcher.finish()
        return remaining, compute_score(self._matcher.verdicts, len(self.events))


def parse_notes(payload: Any) -> list[ExpectedNote]:
    """Construit les notes attendues depuis la charge utile du client.

    Args:
        payload: Liste d'objets ``{onset, duration, midi, id}``.

    Returns:
        Les notes attendues.

    Raises:
        SessionError: Si la charge n'est pas une liste d'entrées exploitables.
            Les notes sans hauteur entière ou sans date sont rejetées en bloc
            plutôt qu'ignorées : une partition partiellement lue produirait un
            score faux sans que personne ne s'en aperçoive.
    """
    if not isinstance(payload, list):
        raise SessionError("`notes` doit être une liste")
    notes: list[ExpectedNote] = []
    for i, raw in enumerate(payload):
        if not isinstance(raw, dict):
            raise SessionError(f"note {i} : objet attendu")
        try:
            onset = float(raw["onset"])
            midi = int(raw["midi"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SessionError(f"note {i} : `onset` et `midi` sont requis") from exc
        try:
            duration = float(raw.get("duration", 0.25))
        except (TypeError, ValueError) as exc:
            raise SessionError(f"note {i} : `duration` invalide") from exc
        notes.append(
            ExpectedNote(
                onset=onset,
                duration=duration,
                midi=midi,
                note_id=raw.get("id", i),
            )
        )
    return notes


def parse_frames(payload: Any) -> list[Frame]:
    """Décode un lot de trames transmis en tableaux compacts.

    Le format est ``[time, hz, confidence, rms, voiced]`` plutôt qu'un objet
    nommé : à 125 trames par seconde, les noms de champs répétés pèseraient
    plus que les données.

    Args:
        payload: Liste de quintuplets.

    Returns:
        Les trames décodées, dans l'ordre reçu.

    Raises:
        SessionError: Si la charge n'est pas une liste de quintuplets.
    """
    if not isinstance(payload, list):
        raise SessionError("`frames` doit être une liste")
    frames: list[Frame] = []
    for i, raw in enumerate(payload):
        if not isinstance(raw, (list, tuple)) or len(raw) < 5:
            raise SessionError(f"trame {i} : [time, hz, confidence, rms, voiced] attendu")
        try:
            frames.append(
                Frame(
                    time=float(raw[0]),
                    hz=float(raw[1]),
                    confidence=float(raw[2]),
                    rms=float(raw[3]),
                    voiced=bool(raw[4]),
                )
            )
        except (TypeError, ValueError) as exc:
            raise SessionError(f"trame {i} : valeur non numérique") from exc
    return frames


def verdict_to_dict(verdict: Verdict) -> dict[str, Any]:
    """Sérialise un verdict pour l'interface.

    Args:
        verdict: Verdict rendu par l'appariement.

    Returns:
        Un dictionnaire JSON-sérialisable ; les durées passent en millisecondes,
        unité dans laquelle l'interface raisonne.
    """
    return {
        "status": verdict.status,
        "event_index": verdict.event_index,
        "note_ids": list(verdict.note_ids),
        "expected_midi": verdict.expected_midi,
        "detected_midi": verdict.detected_midi,
        "timing_error_ms": (
            None if verdict.timing_error is None else verdict.timing_error * 1000.0
        ),
        "cents": verdict.cents,
    }


def score_to_dict(score: Score) -> dict[str, Any]:
    """Sérialise un bilan de prise pour l'interface.

    Args:
        score: Bilan agrégé.

    Returns:
        Un dictionnaire JSON-sérialisable.
    """
    return {
        "events": score.events,
        "correct": score.correct,
        "wrong_pitch": score.wrong_pitch,
        "missed": score.missed,
        "extra": score.extra,
        "pitch_accuracy": score.pitch_accuracy,
        "timing_rms_ms": score.timing_rms_ms,
        "timing_bias_ms": score.timing_bias_ms,
        "mean_abs_cents": score.mean_abs_cents,
        "score": score.score,
    }
