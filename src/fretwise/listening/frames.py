"""Découpage en trames d'analyse — miroir hors ligne du worklet navigateur.

Le worklet garde en tampon les 64 dernières millisecondes captées et lance une
analyse tous les `hop` échantillons. Ce module reproduit ce découpage sur un
signal complet, ce qui permet de rejouer toute la chaîne d'écoute (trames →
notes jouées → appariement → score) sur un fichier, dans les tests comme en
ligne de commande, sans navigateur ni micro.

**Convention d'horodatage** : la date d'une trame est celle de la **fin** de la
fenêtre analysée, parce que c'est ce que fait le worklet (il analyse les
échantillons les plus récents et poste `currentTime` dans la foulée). Une note
qui commence à `t` n'est donc jamais datée à `t` : il faut que la fenêtre se
remplisse assez pour que YIN accroche. Ce retard est systématique, mesuré, et
corrigé dans :mod:`fretwise.listening.notes` — pas ici.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fretwise.listening.pitch import detect_pitch

# Fenêtre d'analyse — miroir de FRAME_SEC dans pitch-worklet.js.
FRAME_SEC = 0.064

# Saut par défaut en mode notation : ~125 analyses/s. Le worklet utilise 21 ms
# pour l'accordeur (une aiguille n'a pas besoin de plus), mais dater un jeu à
# 21 ms près rendrait indiscernables « en place » et « approximatif » : à
# 120 BPM une double-croche ne dure que 125 ms.
DEFAULT_HOP_SEC = 0.008


@dataclass(frozen=True)
class Frame:
    """Une analyse ponctuelle du signal capté.

    Attributes:
        time: Date de **fin** de la fenêtre analysée, en secondes.
        hz: Fondamentale estimée, ``0.0`` si aucune.
        confidence: Périodicité, dans ``[0, 1]``.
        rms: Niveau efficace de la fenêtre.
        voiced: Vrai si YIN a franchi son seuil absolu.
    """

    time: float
    hz: float
    confidence: float
    rms: float
    voiced: bool


def analyze_stream(
    samples: np.ndarray,
    sample_rate: float,
    *,
    hop_sec: float = DEFAULT_HOP_SEC,
    start_time: float = 0.0,
) -> list[Frame]:
    """Découpe un signal et analyse chaque trame comme le ferait le worklet.

    Args:
        samples: Signal mono.
        sample_rate: Fréquence d'échantillonnage, en Hz.
        hop_sec: Intervalle entre deux analyses, en secondes.
        start_time: Date attribuée à l'échantillon 0, pour recaler la série sur
            une horloge externe.

    Returns:
        Les trames, dans l'ordre chronologique. La liste est vide si le signal
        est plus court qu'une fenêtre d'analyse.
    """
    x = np.asarray(samples, dtype=np.float64).ravel()
    window = int(round(FRAME_SEC * sample_rate))
    hop = max(1, int(round(hop_sec * sample_rate)))
    frames: list[Frame] = []
    for end in range(window, x.size + 1, hop):
        est = detect_pitch(x[end - window:end], sample_rate)
        frames.append(
            Frame(
                time=start_time + end / sample_rate,
                hz=est.hz,
                confidence=est.confidence,
                rms=est.rms,
                voiced=est.voiced,
            )
        )
    return frames
