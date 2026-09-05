"""Segmentation des trames d'analyse en notes jouées.

Entre « le signal fait 196 Hz sur cette fenêtre » et « le joueur a attaqué un
sol à telle seconde », il y a tout ce module : regrouper les trames en notes,
dater l'attaque, et surtout ne pas inventer de notes là où il n'y a qu'un
tressaillement du détecteur.

Trois pièges traités explicitement :

1. **Le retard d'analyse.** La date d'une trame est celle de la fin de sa
   fenêtre (voir :mod:`fretwise.listening.frames`). YIN n'accroche que lorsque
   la fenêtre contient assez de périodes de la nouvelle note : l'attaque est
   donc rapportée systématiquement en retard, et **d'autant plus que la note
   est grave**. Mesuré : 60 ms sur un mi grave contre 28 ms deux octaves plus
   haut. Une correction constante laisserait donc un riff sur cordes graves
   « toujours en retard » et un solo aigu « toujours en avance » ; le retard est
   modélisé et retranché note par note (voir :func:`onset_lag_sec`).

2. **Les tressaillements.** Une trame isolée à l'octave, ou un creux non voisé
   au milieu d'une tenue, ne doit pas découper la note. D'où le nombre minimal
   de trames concordantes avant de confirmer un changement, et la tolérance aux
   trous non voisés.

3. **Les notes répétées.** Deux croches sur la même corde donnent une hauteur
   constante : aucune segmentation par hauteur ne peut les séparer. C'est
   l'enveloppe qui les distingue — une ré-attaque fait remonter le niveau après
   la décroissance de la précédente.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from fretwise.listening.frames import DEFAULT_HOP_SEC, Frame
from fretwise.listening.pitch import hz_to_midi

# Modèle du retard d'analyse : part fixe + quantification du saut + le temps
# qu'il faut à la fenêtre pour contenir assez de périodes de la note.
# Coefficients ajustés sur cordes pincées synthétiques de mi grave à do5, à
# quatre valeurs de saut (2, 4, 8, 16 ms) : résidu maximal ~3 ms, soit moins
# d'un saut d'analyse. tests/test_listening_notes.py les épingle.
LAG_BASE_SEC = 0.017
LAG_PERIODS = 3.1

# Trames concordantes exigées avant de confirmer une note. À 8 ms de saut, trois
# trames = 24 ms : assez pour écarter un tressaillement, assez court pour ne pas
# manquer une note brève.
MIN_RUN_FRAMES = 3

# Trames non voisées tolérées à l'intérieur d'une note avant de la clore.
MAX_GAP_FRAMES = 4

# En dessous, la trame est trop peu périodique pour porter une décision.
MIN_CONFIDENCE = 0.80

# Une note doit durer ça avant qu'une remontée de niveau soit lue comme une
# ré-attaque, et non comme le corps de l'attaque en cours.
MIN_NOTE_SEC = 0.05

# Facteur de remontée du niveau caractérisant une ré-attaque (≈ +4,6 dB). Une
# note qui décroît ne remonte jamais ; le vibrato module de moins de 3 dB. Un
# seuil plus haut, lui, laisserait passer un repincement sur corde encore
# sonnante, où la note précédente masque une partie du saut.
RE_ATTACK_RATIO = 1.7

# Durée sur laquelle chercher le creux de niveau précédant une ré-attaque.
# Doit dépasser la fenêtre d'analyse (64 ms) : en deçà, le creux de référence
# est lui-même pris dans la montée que lisse la fenêtre, et le rapport mesuré
# s'effondre sous le seuil.
RE_ATTACK_LOOKBACK_SEC = 0.10


def onset_lag_sec(hz: float, hop_sec: float = DEFAULT_HOP_SEC) -> float:
    """Retard avec lequel une attaque de fréquence ``hz`` est rapportée.

    Args:
        hz: Fondamentale de la note attaquée.
        hop_sec: Intervalle entre deux analyses.

    Returns:
        Le retard en secondes, à retrancher de la date de la première trame qui
        rapporte la note. Le terme en ``1/hz`` est le cœur du modèle : YIN a
        besoin d'environ trois périodes dans sa fenêtre, ce qui coûte 37 ms sur
        un mi grave et 6 ms deux octaves plus haut.
    """
    if hz <= 0.0:
        return LAG_BASE_SEC + hop_sec / 2.0
    return LAG_BASE_SEC + hop_sec / 2.0 + LAG_PERIODS / hz


@dataclass(frozen=True)
class DetectedNote:
    """Une note effectivement jouée, telle que reconstruite depuis les trames.

    Attributes:
        onset: Date de l'attaque, en secondes, **déjà corrigée** du retard
            d'analyse.
        midi: Hauteur tempérée la plus proche.
        cents: Écart moyen au tempérament sur les trames de confirmation ;
            positif quand la note sonne trop haut.
        confidence: Périodicité moyenne sur ces mêmes trames.
        re_attack: Vrai si la note a été isolée par une remontée de niveau à
            hauteur constante (note répétée) plutôt que par un changement de
            hauteur.
    """

    onset: float
    midi: int
    cents: float
    confidence: float
    re_attack: bool = False


class NoteSegmenter:
    """Reconstruit les notes jouées au fil de l'eau.

    Conçu pour le direct : une note est émise dès que son attaque est
    **confirmée**, sans attendre qu'elle se termine. Le retour à l'écran suit
    donc le jeu à :data:`MIN_RUN_FRAMES` trames près, et non à la durée de la
    note.
    """

    def __init__(
        self,
        *,
        hop_sec: float = DEFAULT_HOP_SEC,
        min_run_frames: int = MIN_RUN_FRAMES,
        min_confidence: float = MIN_CONFIDENCE,
    ) -> None:
        """Initialise un segmenteur.

        Args:
            hop_sec: Intervalle entre deux trames — entre dans le modèle de
                retard, qui dépend de la quantification du saut.
            min_run_frames: Trames concordantes exigées pour confirmer une note.
            min_confidence: Périodicité minimale d'une trame exploitable.
        """
        self._hop = hop_sec
        self._min_run = max(1, min_run_frames)
        self._min_conf = min_confidence
        self._active_midi: int | None = None
        self._active_onset = 0.0
        self._cand_midi: int | None = None
        self._cand_frames: list[Frame] = []
        self._unvoiced = 0
        self._recent_rms: deque[float] = deque(
            maxlen=max(3, int(round(RE_ATTACK_LOOKBACK_SEC / max(1e-6, hop_sec))))
        )

    def feed(self, frame: Frame) -> DetectedNote | None:
        """Consomme une trame et renvoie la note dont l'attaque vient d'être confirmée.

        Args:
            frame: Trame d'analyse, dans l'ordre chronologique.

        Returns:
            La note nouvellement confirmée, ou ``None``.
        """
        if not frame.voiced or frame.confidence < self._min_conf:
            self._unvoiced += 1
            if self._unvoiced >= MAX_GAP_FRAMES:
                self._reset()
            return None
        self._unvoiced = 0
        midi = int(round(hz_to_midi(frame.hz)))

        if self._active_midi is not None and midi == self._active_midi:
            self._cand_midi = None
            self._cand_frames = []
            return self._check_re_attack(frame)

        if self._cand_midi != midi:
            self._cand_midi = midi
            self._cand_frames = [frame]
        else:
            self._cand_frames.append(frame)
        if len(self._cand_frames) < self._min_run:
            return None
        return self._confirm(self._cand_frames, re_attack=False)

    def flush(self) -> None:
        """Clôt la note en cours — à appeler en fin de prise."""
        self._reset()

    def _reset(self) -> None:
        self._active_midi = None
        self._cand_midi = None
        self._cand_frames = []
        self._recent_rms.clear()

    def _confirm(self, run: list[Frame], *, re_attack: bool) -> DetectedNote:
        midi = int(round(hz_to_midi(run[0].hz)))
        cents = sum((hz_to_midi(f.hz) - midi) * 100.0 for f in run) / len(run)
        confidence = sum(f.confidence for f in run) / len(run)
        onset = run[0].time - onset_lag_sec(run[0].hz, self._hop)
        self._active_midi = midi
        self._active_onset = onset
        self._cand_midi = None
        self._cand_frames = []
        self._recent_rms.clear()
        self._recent_rms.append(run[-1].rms)
        return DetectedNote(
            onset=onset, midi=midi, cents=cents, confidence=confidence, re_attack=re_attack
        )

    def _check_re_attack(self, frame: Frame) -> DetectedNote | None:
        """Détecte une note répétée à hauteur constante via l'enveloppe."""
        floor = min(self._recent_rms) if self._recent_rms else frame.rms
        self._recent_rms.append(frame.rms)
        lag = onset_lag_sec(frame.hz, self._hop)
        long_enough = (frame.time - lag) - self._active_onset >= MIN_NOTE_SEC
        if long_enough and floor > 0 and frame.rms > floor * RE_ATTACK_RATIO:
            return self._confirm([frame], re_attack=True)
        return None


def segment_notes(
    frames: list[Frame],
    *,
    hop_sec: float = DEFAULT_HOP_SEC,
    min_run_frames: int = MIN_RUN_FRAMES,
    min_confidence: float = MIN_CONFIDENCE,
) -> list[DetectedNote]:
    """Segmente une série complète de trames — variante hors ligne de :class:`NoteSegmenter`.

    Args:
        frames: Trames dans l'ordre chronologique.
        hop_sec: Intervalle entre deux trames.
        min_run_frames: Trames concordantes exigées pour confirmer une note.
        min_confidence: Périodicité minimale d'une trame exploitable.

    Returns:
        Les notes jouées, dans l'ordre des attaques.
    """
    segmenter = NoteSegmenter(
        hop_sec=hop_sec, min_run_frames=min_run_frames, min_confidence=min_confidence
    )
    notes = [note for frame in frames if (note := segmenter.feed(frame)) is not None]
    segmenter.flush()
    return notes
