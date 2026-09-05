"""Détection de hauteur (YIN) — implémentation de référence du module d'écoute.

Ce module est la **source de vérité** de la façon dont FretWise transforme un
bloc d'échantillons en fréquence fondamentale. Le navigateur exécute le même
algorithme dans un AudioWorklet
(``web/static/js/worklets/pitch-worklet.js``) — la détection doit vivre à côté
du thread audio — mais c'est ici que le comportement est épinglé par les tests,
et c'est ici que taperont les outils hors ligne (notation d'un WAV, CLI).

**Contrat de parité** : toute évolution ici doit être répercutée dans le
worklet JS, qui reprend les mêmes constantes et les mêmes trois étapes dans le
même ordre (même règle que la parité ``fretwise.dataset.features`` ↔
``fretwise.ml``).

Algorithme — YIN (de Cheveigné & Kawahara, 2002), en version grossier → fin :

1. anti-repliement + décimation vers ~12 kHz. Les fondamentales de guitare
   plafonnent vers 1,4 kHz : garder 48 kHz ne fait que rendre la fonction de
   différence, en O(W·τ), inutilement chère ;
2. YIN sur le signal décimé — fonction de différence, normalisation par la
   moyenne cumulative, seuil absolu, premier minimum local → période entière ;
3. raffinement de cette période **au taux d'échantillonnage d'origine**, sur une
   fenêtre de ±(DECIM+1) échantillons, avec interpolation parabolique.

L'étape 3 n'est pas un luxe : à 12 kHz, un échantillon de τ autour de E2
(82,4 Hz) vaut ~18 cents — inutilisable pour un accordeur. Après raffinement à
48 kHz on passe sous le cent.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# Bande d'analyse. 60 Hz laisse passer le B1 (61,7 Hz) d'une 7-cordes avec de la
# marge ; 1400 Hz couvre la 24e case de la mi aiguë (1318,5 Hz).
F_MIN_HZ = 60.0
F_MAX_HZ = 1400.0

# Seuil absolu de YIN sur la différence normalisée par la moyenne cumulative.
# 0.15 est la valeur retenue dans l'évaluation de l'article ; plus bas = plus strict.
YIN_THRESHOLD = 0.15

# En dessous de ce RMS la trame est traitée comme du silence (ni hauteur ni confiance).
SILENCE_RMS = 0.004

# Taux visé pour l'étape 2. Une Nyquist à ~6 kHz conserve toutes les
# fondamentales de guitare et les premières harmoniques sur lesquelles la
# fonction de différence s'appuie réellement.
DECIMATED_RATE_HZ = 12000.0

# Accordage standard EADGBE, hauteurs MIDI des cordes à vide (6e → 1re).
STANDARD_TUNING_MIDI: tuple[int, ...] = (40, 45, 50, 55, 59, 64)

_NOTE_NAMES: tuple[str, ...] = (
    "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B",
)


@dataclass(frozen=True)
class PitchEstimate:
    """Résultat d'analyse d'une trame.

    Attributes:
        hz: Fondamentale estimée en Hz, ``0.0`` si aucune hauteur n'est trouvée.
        confidence: Périodicité de la trame, dans ``[0, 1]`` (``1 - d'(τ)``).
        rms: Niveau efficace de la trame, pour le vu-mètre et la détection de silence.
        voiced: ``True`` seulement si YIN a franchi son seuil absolu — c'est le
            drapeau à tester avant d'afficher une note, pas ``hz > 0``.
    """

    hz: float
    confidence: float
    rms: float
    voiced: bool


def _lowpass_taps(decim: int) -> np.ndarray:
    """Coefficients FIR passe-bas (sinc fenêtré par Hamming) pour la décimation.

    Args:
        decim: Facteur de décimation entier.

    Returns:
        Noyau symétrique de longueur impaire, de somme unitaire, coupant à
        0,45·(sr/decim) — soit 10 % sous la nouvelle Nyquist.
    """
    num_taps = 8 * decim + 1
    cutoff = 0.45 / decim  # en cycles/échantillon du taux d'origine
    n = np.arange(num_taps, dtype=np.float64)
    centre = (num_taps - 1) / 2.0
    ideal = 2.0 * cutoff * np.sinc(2.0 * cutoff * (n - centre))
    window = np.hamming(num_taps)
    taps: np.ndarray = ideal * window
    return taps / float(np.sum(taps))


def _decimate(samples: np.ndarray, decim: int) -> np.ndarray:
    """Filtre en anti-repliement puis sous-échantillonne d'un facteur entier.

    Args:
        samples: Signal d'entrée (1-D).
        decim: Facteur de décimation ; ``<= 1`` renvoie le signal inchangé.

    Returns:
        Le signal décimé. La convolution est centrée et à bords nuls, ce que le
        worklet JS reproduit en n'évaluant le FIR qu'aux points de sortie.
    """
    if decim <= 1:
        return samples
    filtered = np.convolve(samples, _lowpass_taps(decim), mode="same")
    return filtered[::decim]


def _difference_function(x: np.ndarray, tau_max: int, window: int) -> np.ndarray:
    """Fonction de différence de YIN : ``d(τ) = Σ (x[j] - x[j+τ])²``.

    Args:
        x: Signal ; doit contenir au moins ``window + tau_max`` échantillons.
        tau_max: Décalage maximal évalué (inclus).
        window: Nombre d'échantillons comparés à chaque décalage.

    Returns:
        Tableau de longueur ``tau_max + 1`` ; l'indice 0 vaut 0 par construction.
    """
    d = np.zeros(tau_max + 1, dtype=np.float64)
    frame = x[:window]
    for tau in range(1, tau_max + 1):
        diff = frame - x[tau:tau + window]
        d[tau] = float(np.dot(diff, diff))
    return d


def _cumulative_mean_normalized(d: np.ndarray) -> np.ndarray:
    """Normalise la fonction de différence par sa moyenne cumulative.

    C'est l'étape qui supprime le minimum trivial en τ=0 et rend un seuil
    absolu utilisable — sans elle, YIN se réduit à une autocorrélation et
    octavie.

    Args:
        d: Sortie de :func:`_difference_function`.

    Returns:
        ``d'`` de même longueur, avec ``d'(0) = 1``.
    """
    dp = np.ones_like(d)
    running = 0.0
    for tau in range(1, d.size):
        running += float(d[tau])
        dp[tau] = float(d[tau]) * tau / running if running > 0.0 else 1.0
    return dp


def _absolute_threshold(
    dp: np.ndarray, tau_min: int, tau_max: int, threshold: float
) -> tuple[int, bool]:
    """Retient le **premier** τ passant sous le seuil, puis descend au minimum local.

    Prendre le premier et non le plus profond est ce qui protège des erreurs
    d'octave basse : une période double satisfait aussi le critère de
    périodicité, souvent avec un creux plus marqué.

    Args:
        dp: Différence normalisée par la moyenne cumulative.
        tau_min: Décalage minimal admissible (borne haute de fréquence).
        tau_max: Décalage maximal admissible (borne basse de fréquence).
        threshold: Seuil absolu de YIN.

    Returns:
        ``(tau, crossed)`` — ``crossed`` est ``False`` quand rien n'a franchi le
        seuil, auquel cas ``tau`` est le minimum global (trame non voisée).
    """
    tau = tau_min
    while tau <= tau_max:
        if dp[tau] < threshold:
            while tau + 1 <= tau_max and dp[tau + 1] < dp[tau]:
                tau += 1
            return tau, True
        tau += 1
    return int(np.argmin(dp[tau_min:tau_max + 1])) + tau_min, False


def _parabolic(values: np.ndarray, index: int) -> float:
    """Affine par interpolation parabolique la position d'un minimum discret.

    Args:
        values: Suite contenant le minimum.
        index: Indice du minimum entier.

    Returns:
        Position sous-échantillonnée du minimum ; ``index`` tel quel aux bords
        ou si les trois points sont alignés.
    """
    if index <= 0 or index >= values.size - 1:
        return float(index)
    a, b, c = float(values[index - 1]), float(values[index]), float(values[index + 1])
    denom = a - 2.0 * b + c
    if denom == 0.0:
        return float(index)
    return index + 0.5 * (a - c) / denom


def _refine_period(x: np.ndarray, guess: float, span: int) -> float:
    """Réévalue la période au taux d'origine autour d'une estimation décimée.

    Args:
        x: Signal au taux d'échantillonnage d'origine.
        guess: Période estimée, en échantillons du taux d'origine.
        span: Demi-largeur de recherche, en échantillons.

    Returns:
        La période affinée ; ``guess`` si le signal est trop court pour une
        fenêtre de comparaison utile.
    """
    centre = int(round(guess))
    lo = max(2, centre - span)
    hi = centre + span
    window = x.size - hi
    if window < 64:
        return guess
    frame = x[:window]
    vals = np.empty(hi - lo + 1, dtype=np.float64)
    for i, tau in enumerate(range(lo, hi + 1)):
        diff = frame - x[tau:tau + window]
        vals[i] = float(np.dot(diff, diff))
    return lo + _parabolic(vals, int(np.argmin(vals)))


def detect_pitch(
    samples: np.ndarray,
    sample_rate: float,
    *,
    f_min: float = F_MIN_HZ,
    f_max: float = F_MAX_HZ,
    threshold: float = YIN_THRESHOLD,
    min_rms: float = SILENCE_RMS,
) -> PitchEstimate:
    """Estime la fondamentale d'une trame audio monophonique.

    Args:
        samples: Trame mono. Il en faut au moins ``sample_rate / f_min * 3``
            environ (≈ 64 ms à 48 kHz) pour que l'étape YIN dispose de
            plusieurs périodes de la note la plus grave.
        sample_rate: Fréquence d'échantillonnage de ``samples``, en Hz.
        f_min: Borne basse de la bande d'analyse, en Hz.
        f_max: Borne haute de la bande d'analyse, en Hz.
        threshold: Seuil absolu de YIN.
        min_rms: RMS en dessous duquel la trame est déclarée silencieuse.

    Returns:
        Le :class:`PitchEstimate` de la trame. Une trame silencieuse, trop
        courte ou apériodique revient avec ``voiced=False`` et ``hz=0.0``.
    """
    x = np.asarray(samples, dtype=np.float64).ravel()
    rms = float(np.sqrt(np.mean(x * x))) if x.size else 0.0
    if x.size < 256 or rms < min_rms:
        return PitchEstimate(0.0, 0.0, rms, False)

    decim = max(1, int(round(sample_rate / DECIMATED_RATE_HZ)))
    rate_dec = sample_rate / decim
    xd = _decimate(x, decim)

    tau_min = max(1, int(math.floor(rate_dec / f_max)))
    tau_max = int(math.ceil(rate_dec / f_min))
    window = xd.size - tau_max
    if tau_max <= tau_min or window < 2 * tau_min:
        return PitchEstimate(0.0, 0.0, rms, False)

    dp = _cumulative_mean_normalized(_difference_function(xd, tau_max, window))
    # La recherche démarre sous tau_min exprès : si le signal est déjà périodique
    # à un décalage plus court que ce que f_max autorise, sa fondamentale est
    # hors bande. Repartir à tau_min renverrait alors une sous-harmonique — un
    # sinus à 2 kHz lu 1 kHz, soit une octave d'erreur affichée avec aplomb.
    tau_floor = max(1, tau_min // 2)
    tau, crossed = _absolute_threshold(dp, tau_floor, tau_max, threshold)
    confidence = float(np.clip(1.0 - dp[tau], 0.0, 1.0))
    if not crossed or tau < tau_min:
        return PitchEstimate(0.0, 0.0 if tau < tau_min else confidence, rms, False)

    period = _refine_period(x, _parabolic(dp, tau) * decim, decim + 1)
    if period <= 0.0:
        return PitchEstimate(0.0, confidence, rms, False)
    hz = sample_rate / period
    if not (f_min <= hz <= f_max):
        return PitchEstimate(0.0, confidence, rms, False)
    return PitchEstimate(hz, confidence, rms, True)


# ── Conversions musicales ────────────────────────────────────────────────


def hz_to_midi(hz: float, a4_hz: float = 440.0) -> float:
    """Convertit une fréquence en hauteur MIDI fractionnaire.

    Args:
        hz: Fréquence, en Hz. Doit être strictement positive.
        a4_hz: Diapason de référence (A4). 440 par défaut ; certains jouent
            à 432 ou 442, et l'accordeur doit suivre.

    Returns:
        La hauteur MIDI, partie fractionnaire comprise (69.5 = un demi-demi-ton
        au-dessus du A4).

    Raises:
        ValueError: Si ``hz`` n'est pas strictement positive.
    """
    if hz <= 0.0:
        raise ValueError("hz doit être > 0")
    return 69.0 + 12.0 * math.log2(hz / a4_hz)


def midi_to_hz(midi: float, a4_hz: float = 440.0) -> float:
    """Convertit une hauteur MIDI (éventuellement fractionnaire) en Hz.

    Args:
        midi: Hauteur MIDI.
        a4_hz: Diapason de référence (A4).

    Returns:
        La fréquence correspondante, en Hz.
    """
    return float(a4_hz * (2.0 ** ((midi - 69.0) / 12.0)))


def note_name(midi: int) -> str:
    """Nomme une hauteur MIDI entière, dièses uniquement.

    Args:
        midi: Hauteur MIDI entière.

    Returns:
        Le nom scientifique de la note, p. ex. ``"E2"`` pour 40.
    """
    return f"{_NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def cents_between(hz: float, target_hz: float) -> float:
    """Écart en cents entre une fréquence mesurée et sa cible.

    Args:
        hz: Fréquence mesurée, en Hz.
        target_hz: Fréquence visée, en Hz.

    Returns:
        L'écart en cents ; positif quand la note sonne trop haut.

    Raises:
        ValueError: Si l'une des deux fréquences n'est pas strictement positive.
    """
    if hz <= 0.0 or target_hz <= 0.0:
        raise ValueError("les fréquences doivent être > 0")
    return 1200.0 * math.log2(hz / target_hz)


def nearest_semitone(hz: float, a4_hz: float = 440.0) -> tuple[int, float]:
    """Demi-ton tempéré le plus proche — mode chromatique de l'accordeur.

    Args:
        hz: Fréquence mesurée, en Hz.
        a4_hz: Diapason de référence (A4).

    Returns:
        ``(midi, cents)`` : la hauteur MIDI visée et l'écart signé, dans
        ``[-50, +50]``.
    """
    midi = int(round(hz_to_midi(hz, a4_hz)))
    return midi, cents_between(hz, midi_to_hz(midi, a4_hz))


def nearest_target(
    hz: float, targets_midi: tuple[int, ...] | list[int], a4_hz: float = 440.0
) -> tuple[int, float]:
    """Cible la plus proche dans une liste de hauteurs — mode « cordes du morceau ».

    La comparaison se fait en cents, pas en Hz : à 82 Hz un écart de 3 Hz est
    énorme, à 330 Hz il est marginal, et un accordeur qui trie en Hz saute de
    corde sur la mi grave.

    Args:
        hz: Fréquence mesurée, en Hz.
        targets_midi: Hauteurs MIDI des cordes à vide, dans l'ordre où
            l'appelant veut les indexer.
        a4_hz: Diapason de référence (A4).

    Returns:
        ``(index, cents)`` : l'indice dans ``targets_midi`` et l'écart signé à
        cette cible.

    Raises:
        ValueError: Si ``targets_midi`` est vide.
    """
    if not len(targets_midi):
        raise ValueError("targets_midi ne peut pas être vide")
    deviations = [cents_between(hz, midi_to_hz(m, a4_hz)) for m in targets_midi]
    best = min(range(len(deviations)), key=lambda i: abs(deviations[i]))
    return best, deviations[best]
