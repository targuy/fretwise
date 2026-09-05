"""Appariement du jeu capté avec la partition, et notation.

Mode **guidé** : le playback tourne, donc la position dans le morceau est
connue et il n'y a pas de suivi à faire — chaque événement attendu ouvre une
fenêtre autour de sa date, et on regarde ce qui y a été joué.

Deux partis pris structurent tout le module.

**On raisonne par événement, pas par note.** Les notes attendues simultanées
sont regroupées : un accord plaqué est *un* événement à cinq hauteurs
possibles. La détection de hauteur est monophonique — sur un accord elle ne
rapportera qu'une voix — donc compter cinq notes manquées pour un accord
correctement plaqué serait faux et décourageant. L'événement est validé si
l'une de ses hauteurs est reconnue.

**Les fenêtres ne se chevauchent jamais.** La tolérance nominale est rabotée à
la moitié de l'écart aux événements voisins : sans cela, sur un trait rapide,
une note captée pourrait satisfaire deux événements consécutifs, et la note
réellement manquée passerait inaperçue.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from fretwise.listening.notes import DetectedNote

# Fenêtre nominale de part et d'autre d'un événement attendu. 150 ms est large
# à dessein : la fenêtre sert à *rattacher* une note à sa cible, pas à juger si
# elle est en place — c'est l'erreur de date rapportée qui juge.
TOLERANCE_SEC = 0.15

# Écart en deçà duquel deux notes attendues sont tenues pour simultanées.
CHORD_GROUP_SEC = 0.02

# Erreur de date (RMS) à laquelle la note de rythme tombe à zéro.
TIMING_ZERO_SEC = 0.12

# Poids de la justesse et du rythme dans la note finale.
PITCH_WEIGHT = 0.7
TIMING_WEIGHT = 0.3

# Plafond de la pénalité de notes en trop, et son taux.
EXTRA_PENALTY_RATE = 0.5
EXTRA_PENALTY_CAP = 0.2

CORRECT = "correct"
WRONG_PITCH = "wrong_pitch"
MISSED = "missed"
EXTRA = "extra"


@dataclass(frozen=True)
class ExpectedNote:
    """Une note de la partition, ramenée à l'axe des temps du playback.

    Attributes:
        onset: Date d'attaque attendue, en secondes de position dans le morceau.
        duration: Durée attendue, en secondes.
        midi: Hauteur sonnante.
        note_id: Identifiant opaque, restitué tel quel pour que l'interface
            sache quelle tête de note colorer.
    """

    onset: float
    duration: float
    midi: int
    note_id: Any = None


@dataclass(frozen=True)
class ExpectedEvent:
    """Un instant musical : une note isolée, ou plusieurs notes simultanées.

    Attributes:
        index: Rang chronologique de l'événement.
        onset: Date d'attaque attendue, en secondes.
        duration: Durée la plus longue du groupe, en secondes.
        midis: Hauteurs acceptables pour valider l'événement.
        note_ids: Identifiants des notes du groupe.
        is_chord: Vrai si le groupe compte plusieurs hauteurs distinctes.
    """

    index: int
    onset: float
    duration: float
    midis: tuple[int, ...]
    note_ids: tuple[Any, ...] = ()
    is_chord: bool = False


@dataclass(frozen=True)
class Verdict:
    """Ce qui a été constaté pour un événement (ou une note jouée en trop).

    Attributes:
        status: ``correct``, ``wrong_pitch``, ``missed`` ou ``extra``.
        event_index: Rang de l'événement visé ; ``None`` pour ``extra``.
        note_ids: Identifiants des notes concernées.
        expected_midi: Hauteur attendue retenue ; ``None`` si rien n'a été joué.
        detected_midi: Hauteur effectivement jouée ; ``None`` si rien.
        timing_error: Écart de date en secondes, positif quand la note est en
            retard ; ``None`` hors des cas appariés.
        cents: Écart au tempérament de la note jouée ; ``None`` hors appariement.
    """

    status: str
    event_index: int | None = None
    note_ids: tuple[Any, ...] = ()
    expected_midi: int | None = None
    detected_midi: int | None = None
    timing_error: float | None = None
    cents: float | None = None


@dataclass(frozen=True)
class Score:
    """Bilan chiffré d'une prise.

    Attributes:
        events: Nombre d'événements attendus.
        correct: Événements joués juste.
        wrong_pitch: Événements joués, mais à la mauvaise hauteur.
        missed: Événements sans rien de joué dans leur fenêtre.
        extra: Notes jouées qui ne correspondent à aucun événement.
        pitch_accuracy: Part d'événements justes, dans ``[0, 1]``.
        timing_rms_ms: Écart-type des erreurs de date sur les événements justes.
        timing_bias_ms: Erreur de date moyenne — un biais positif franc signale
            un joueur systématiquement en retard, ce qui se corrige autrement
            qu'un jeu simplement imprécis.
        mean_abs_cents: Écart moyen au tempérament, en valeur absolue.
        score: Note globale sur 100.
    """

    events: int
    correct: int
    wrong_pitch: int
    missed: int
    extra: int
    pitch_accuracy: float
    timing_rms_ms: float
    timing_bias_ms: float
    mean_abs_cents: float
    score: float


def build_events(
    notes: list[ExpectedNote], *, group_sec: float = CHORD_GROUP_SEC
) -> list[ExpectedEvent]:
    """Regroupe les notes attendues simultanées en événements.

    Args:
        notes: Notes de la partition, dans un ordre quelconque.
        group_sec: Écart en deçà duquel deux notes sont tenues pour simultanées.

    Returns:
        Les événements, dans l'ordre chronologique.
    """
    ordered = sorted(notes, key=lambda n: n.onset)
    events: list[ExpectedEvent] = []
    group: list[ExpectedNote] = []

    def flush() -> None:
        if not group:
            return
        midis = tuple(sorted({n.midi for n in group}))
        events.append(
            ExpectedEvent(
                index=len(events),
                onset=group[0].onset,
                duration=max(n.duration for n in group),
                midis=midis,
                note_ids=tuple(n.note_id for n in group),
                is_chord=len(midis) > 1,
            )
        )
        group.clear()

    for note in ordered:
        if group and note.onset - group[0].onset > group_sec:
            flush()
        group.append(note)
    flush()
    return events


def _windows(
    events: list[ExpectedEvent], tolerance: float
) -> list[tuple[float, float]]:
    """Fenêtre ``(début, fin)`` de chaque événement, rabotée pour ne pas se chevaucher."""
    bounds: list[tuple[float, float]] = []
    for i, event in enumerate(events):
        before = tolerance
        after = tolerance
        if i > 0:
            before = min(before, (event.onset - events[i - 1].onset) / 2.0)
        if i + 1 < len(events):
            after = min(after, (events[i + 1].onset - event.onset) / 2.0)
        bounds.append((event.onset - before, event.onset + after))
    return bounds


@dataclass
class _Candidate:
    note: DetectedNote
    consumed: bool = False


@dataclass
class Matcher:
    """Apparie au fil de l'eau les notes jouées avec les événements attendus.

    Le direct impose de rendre un verdict sans connaître la suite : un
    événement est tranché dès que sa fenêtre est refermée, c'est-à-dire dès que
    l'horloge a dépassé sa borne haute. D'où :meth:`advance`, qu'il faut
    appeler avec la position courante du playback — sinon rien ne sort tant que
    :meth:`finish` n'est pas appelé.
    """

    events: list[ExpectedEvent]
    tolerance: float = TOLERANCE_SEC
    _bounds: list[tuple[float, float]] = field(init=False, repr=False)
    _index: int = field(default=0, init=False, repr=False)
    _candidates: list[_Candidate] = field(default_factory=list, init=False, repr=False)
    _verdicts: list[Verdict] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self.events = sorted(self.events, key=lambda e: e.onset)
        self._bounds = _windows(self.events, self.tolerance)

    def feed(self, note: DetectedNote) -> None:
        """Enregistre une note jouée.

        Args:
            note: Note détectée ; les attaques doivent arriver dans l'ordre.
        """
        self._candidates.append(_Candidate(note))

    def advance(self, now: float) -> list[Verdict]:
        """Tranche les événements dont la fenêtre est refermée à ``now``.

        Args:
            now: Position courante dans le morceau, en secondes.

        Returns:
            Les verdicts rendus depuis le dernier appel.
        """
        emitted: list[Verdict] = []
        while self._index < len(self.events) and self._bounds[self._index][1] <= now:
            emitted.append(self._resolve(self._index))
            self._index += 1
        self._verdicts.extend(emitted)
        return emitted

    def finish(self) -> list[Verdict]:
        """Referme la prise : tranche le reste, puis signale les notes en trop.

        Returns:
            Les verdicts restants, événements manquants et notes en trop compris.
        """
        emitted = self.advance(math.inf)
        for candidate in self._candidates:
            if candidate.consumed:
                continue
            extra = Verdict(
                status=EXTRA,
                detected_midi=candidate.note.midi,
                cents=candidate.note.cents,
            )
            emitted.append(extra)
            self._verdicts.append(extra)
        return emitted

    @property
    def verdicts(self) -> list[Verdict]:
        """Tous les verdicts rendus depuis le début de la prise."""
        return list(self._verdicts)

    def _resolve(self, index: int) -> Verdict:
        event = self.events[index]
        low, high = self._bounds[index]
        in_window = [
            c for c in self._candidates
            if not c.consumed and low <= c.note.onset <= high
        ]
        if not in_window:
            return Verdict(
                status=MISSED,
                event_index=event.index,
                note_ids=event.note_ids,
                expected_midi=event.midis[0],
            )
        on_pitch = [c for c in in_window if c.note.midi in event.midis]
        pool = on_pitch or in_window
        best = min(pool, key=lambda c: abs(c.note.onset - event.onset))
        best.consumed = True
        return Verdict(
            status=CORRECT if on_pitch else WRONG_PITCH,
            event_index=event.index,
            note_ids=event.note_ids,
            expected_midi=best.note.midi if on_pitch else event.midis[0],
            detected_midi=best.note.midi,
            timing_error=best.note.onset - event.onset,
            cents=best.note.cents,
        )


def compute_score(verdicts: list[Verdict], events: int) -> Score:
    """Agrège des verdicts en bilan chiffré.

    La note finale pondère justesse (70 %) et rythme (30 %) : jouer les bonnes
    notes reste l'essentiel, mais un jeu juste et systématiquement à côté du
    temps ne doit pas décrocher un sans-faute. Les notes en trop retranchent
    ensuite un forfait plafonné — elles témoignent d'un doigt qui traîne ou
    d'une corde mal étouffée, pas d'une erreur aussi grave qu'une note ratée.

    Args:
        verdicts: Verdicts d'une prise.
        events: Nombre d'événements attendus.

    Returns:
        Le bilan. Sur une partition sans événement, tout est à zéro plutôt
        qu'une division par zéro déguisée en note parfaite.
    """
    correct = [v for v in verdicts if v.status == CORRECT]
    wrong = sum(1 for v in verdicts if v.status == WRONG_PITCH)
    missed = sum(1 for v in verdicts if v.status == MISSED)
    extra = sum(1 for v in verdicts if v.status == EXTRA)
    if events <= 0:
        return Score(0, 0, 0, 0, extra, 0.0, 0.0, 0.0, 0.0, 0.0)

    errors = [v.timing_error for v in correct if v.timing_error is not None]
    timing_rms = math.sqrt(sum(e * e for e in errors) / len(errors)) if errors else 0.0
    timing_bias = sum(errors) / len(errors) if errors else 0.0
    cents = [abs(v.cents) for v in correct if v.cents is not None]
    mean_abs_cents = sum(cents) / len(cents) if cents else 0.0

    pitch_accuracy = len(correct) / events
    timing_quality = max(0.0, 1.0 - timing_rms / TIMING_ZERO_SEC) if errors else 0.0
    penalty = min(EXTRA_PENALTY_CAP, EXTRA_PENALTY_RATE * extra / events)
    score = 100.0 * max(
        0.0, PITCH_WEIGHT * pitch_accuracy + TIMING_WEIGHT * timing_quality - penalty
    )
    return Score(
        events=events,
        correct=len(correct),
        wrong_pitch=wrong,
        missed=missed,
        extra=extra,
        pitch_accuracy=pitch_accuracy,
        timing_rms_ms=timing_rms * 1000.0,
        timing_bias_ms=timing_bias * 1000.0,
        mean_abs_cents=mean_abs_cents,
        score=score,
    )
