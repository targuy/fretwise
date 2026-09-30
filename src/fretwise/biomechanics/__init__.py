"""Pure biomechanical validation for final fingering results.

This module is intentionally separate from scoring resolvers. Scoring proposes
and repairs fingerings; biomechanics certifies the final output and reports
deterministic violations without mutating the input sequence.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite

from fretwise.config import config
from fretwise.models import Finger, FingeringResult
from fretwise.sustain import contact_end, required_contact_ends

# Constants sourced from fretwise.config -> defaults.yaml: ``biomechanics``.
_BIOMECH_CONFIG = config().biomechanics

STANDARD_TUNING: tuple[int, ...] = tuple(_BIOMECH_CONFIG.standard_tuning)
DEFAULT_MAX_FRET = _BIOMECH_CONFIG.max_fret
DEFAULT_ONSET_PRECISION = _BIOMECH_CONFIG.onset_precision
_DEFAULT_MAX_CHORD_SPAN = _BIOMECH_CONFIG.max_chord_span
_DEFAULT_MAX_SHIFT_PER_BEAT = _BIOMECH_CONFIG.max_shift_per_beat

_FINGER_OFFSET: dict[Finger, int] = {
    Finger.INDEX: 0,
    Finger.MIDDLE: 1,
    Finger.RING: 2,
    Finger.PINKY: 3,
}

_FINGER_RANK: dict[Finger, int] = {
    Finger.OPEN: -1,
    Finger.INDEX: 0,
    Finger.MIDDLE: 1,
    Finger.RING: 2,
    Finger.PINKY: 3,
}

_MAX_FINGER_PAIR_SPAN: dict[tuple[int, int], int] = {
    (0, 1): _BIOMECH_CONFIG.max_finger_pair_span.index_middle,
    (0, 2): _BIOMECH_CONFIG.max_finger_pair_span.index_ring,
    (0, 3): _BIOMECH_CONFIG.max_finger_pair_span.index_pinky,
    (1, 2): _BIOMECH_CONFIG.max_finger_pair_span.middle_ring,
    (1, 3): _BIOMECH_CONFIG.max_finger_pair_span.middle_pinky,
    (2, 3): _BIOMECH_CONFIG.max_finger_pair_span.ring_pinky,
}


class BiomechanicalSeverity(StrEnum):
    """Severity of a biomechanical guard violation."""

    FATAL = "fatal"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Codes that are data/tuning/bend artefacts rather than fingering-choice
# problems — the player cannot fix them by picking a different finger.
# BIO-STATE-003 in particular used to fire on every note of a dropped/capo'd/
# half-step-down track before tuning was derived from the source (see
# ``derive_open_string_pitches``); it still fires on genuine bends/harmonics,
# where the sounding pitch legitimately differs from the fretted position.
# Shared by every consumer (review list, audit verdict, per-note highlight)
# so they all agree on what counts as an actionable violation.
NON_ACTIONABLE_CODES: frozenset[str] = frozenset(
    {"BIO-STATE-001", "BIO-STATE-002", "BIO-STATE-003"}
)


@dataclass(frozen=True)
class BiomechanicalRuleConfig:
    """Configuration for biomechanical validation.

    Attributes:
        open_string_pitches: MIDI pitch for strings 1..6 in high-to-low order.
        max_fret: Highest fret accepted by the validator.
        max_chord_span: Maximum fret span allowed inside one simultaneous chord.
        onset_precision: Decimal precision used to group simultaneous notes.
        enforce_natural_hand_position: If true, fretted states must satisfy
            ``hand_position == fret - finger_offset``. This is disabled by
            default because post-processors may intentionally unify chord hand
            positions after Viterbi.
        max_shift_per_beat: Threshold for warning on extreme hand shifts.
    """

    open_string_pitches: tuple[int, ...] = STANDARD_TUNING
    max_fret: int = DEFAULT_MAX_FRET
    max_chord_span: int = _DEFAULT_MAX_CHORD_SPAN
    onset_precision: int = DEFAULT_ONSET_PRECISION
    enforce_natural_hand_position: bool = False
    max_shift_per_beat: float = _DEFAULT_MAX_SHIFT_PER_BEAT


@dataclass(frozen=True)
class BiomechanicalViolation:
    """One deterministic fingering violation."""

    code: str
    severity: BiomechanicalSeverity
    message: str
    note_ids: tuple[int, ...] = ()
    measure_index: int | None = None
    onset: float | None = None
    context: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class BiomechanicalReport:
    """Aggregate report for a fingered result sequence."""

    checked_notes: int
    violations: tuple[BiomechanicalViolation, ...] = ()

    @property
    def is_clean(self) -> bool:
        """Return true when no biomechanical violations were found."""
        return not self.violations

    @property
    def fatal_count(self) -> int:
        """Number of fatal violations."""
        return sum(1 for v in self.violations if v.severity == BiomechanicalSeverity.FATAL)

    @property
    def high_count(self) -> int:
        """Number of high-severity violations."""
        return sum(1 for v in self.violations if v.severity == BiomechanicalSeverity.HIGH)

    def by_measure(self) -> dict[int, list[BiomechanicalViolation]]:
        """Group violations that have a source measure index."""
        grouped: dict[int, list[BiomechanicalViolation]] = defaultdict(list)
        for violation in self.violations:
            if violation.measure_index is not None:
                grouped[violation.measure_index].append(violation)
        return dict(grouped)


def derive_open_string_pitches(results: Sequence[FingeringResult]) -> tuple[int, ...]:
    """Infer per-string open-string MIDI pitches from source tab hints.

    GP tabs encode the real (possibly non-standard / dropped / capo'd / half-
    step-down) tuning implicitly: ``open_pitch[string] = note.pitch -
    note.fret_hint``. Using this — not the hard-coded standard tuning — keeps
    BIO-STATE-003 ("pitch does not match the selected string and fret")
    honest for any tuning instead of misfiring on every note of a track that
    isn't in standard E. Strings never seen in the source hints (e.g. MIDI
    input with no tab data) fall back to standard tuning.
    """
    tuning = list(STANDARD_TUNING)
    seen: dict[int, int] = {}
    for result in results:
        note = result.note_event
        if (
            note.string_hint is not None and note.fret_hint is not None
            and 1 <= note.string_hint <= len(tuning) and note.string_hint not in seen
        ):
            seen[note.string_hint] = note.pitch - note.fret_hint
    for string_num, open_pitch in seen.items():
        tuning[string_num - 1] = open_pitch
    return tuple(tuning)


def validate_fingering_results(
    results: Sequence[FingeringResult],
    *,
    config: BiomechanicalRuleConfig | None = None,
) -> BiomechanicalReport:
    """Validate final fingerings without mutating them.

    Args:
        results: Final fingerings from the pipeline.
        config: Optional validation policy. When omitted, the open-string
            tuning is derived from the source tab hints in ``results``
            (see :func:`derive_open_string_pitches`) instead of assuming
            standard tuning.

    Returns:
        A deterministic report containing all detected violations.
    """
    rule_config = config or BiomechanicalRuleConfig(
        open_string_pitches=derive_open_string_pitches(results),
    )
    violations: list[BiomechanicalViolation] = []
    violations.extend(_validate_states(results, rule_config))
    violations.extend(_validate_chords(results, rule_config))
    violations.extend(_validate_transitions(results, rule_config))
    violations.extend(_validate_occupations(results, rule_config))
    violations.extend(_validate_tie_contacts(results))
    violations.extend(_validate_ring_releases(results))
    return BiomechanicalReport(
        checked_notes=len(results),
        violations=tuple(violations),
    )


def _validate_states(
    results: Sequence[FingeringResult],
    config: BiomechanicalRuleConfig,
) -> list[BiomechanicalViolation]:
    violations: list[BiomechanicalViolation] = []
    for result in results:
        state = result.state
        note = result.note_event
        location = _location(result)

        if state.string_num < 1 or state.string_num > len(config.open_string_pitches):
            violations.append(_violation(
                "BIO-STATE-001",
                BiomechanicalSeverity.FATAL,
                "String number is outside the configured instrument range.",
                result,
                context={"string": state.string_num},
            ))
            continue

        if state.fret < 0 or state.fret > config.max_fret:
            violations.append(_violation(
                "BIO-STATE-002",
                BiomechanicalSeverity.FATAL,
                "Fret is outside the configured neck range.",
                result,
                context={"fret": state.fret, "max_fret": config.max_fret},
            ))

        expected_pitch = config.open_string_pitches[state.string_num - 1] + state.fret
        if note.pitch != expected_pitch:
            violations.append(_violation(
                "BIO-STATE-003",
                BiomechanicalSeverity.HIGH,
                "Pitch does not match the selected string and fret.",
                result,
                context={"pitch": note.pitch, "expected_pitch": expected_pitch},
            ))

        if state.fret == 0 and state.finger != Finger.OPEN:
            violations.append(_violation(
                "BIO-STATE-004",
                BiomechanicalSeverity.FATAL,
                "Open string is assigned to a fretting finger.",
                result,
                context={"finger": state.finger.value},
            ))

        if state.fret > 0 and state.finger == Finger.OPEN:
            violations.append(_violation(
                "BIO-STATE-005",
                BiomechanicalSeverity.FATAL,
                "Fretted note is assigned to OPEN.",
                result,
                context={"fret": state.fret},
            ))

        if state.hand_position < 1:
            violations.append(_violation(
                "BIO-STATE-006",
                BiomechanicalSeverity.FATAL,
                "Hand position must be at least first position.",
                result,
                context={"hand_position": state.hand_position},
            ))

        if state.fret > 0 and state.fret < state.hand_position:
            violations.append(_violation(
                "BIO-STATE-007",
                BiomechanicalSeverity.FATAL,
                "Fretted note is below the current hand position.",
                result,
                context={"fret": state.fret, "hand_position": state.hand_position},
            ))

        if config.enforce_natural_hand_position and state.fret > 0:
            expected_hp = state.fret - _FINGER_OFFSET.get(state.finger, 0)
            if expected_hp != state.hand_position:
                violations.append(BiomechanicalViolation(
                    code="BIO-STATE-008",
                    severity=BiomechanicalSeverity.MEDIUM,
                    message="Hand position does not match the natural finger offset.",
                    note_ids=(result.note_id,),
                    measure_index=location[0],
                    onset=location[1],
                    context={
                        "finger": state.finger.value,
                        "fret": state.fret,
                        "hand_position": state.hand_position,
                        "expected_hand_position": expected_hp,
                    },
                ))
    return violations


def _validate_chords(
    results: Sequence[FingeringResult],
    config: BiomechanicalRuleConfig,
) -> list[BiomechanicalViolation]:
    violations: list[BiomechanicalViolation] = []
    for chord in _group_by_onset(results, config.onset_precision).values():
        if len(chord) < 2:
            continue
        violations.extend(_validate_same_string_chord(chord))
        contacts = {
            (r.state.string_num, r.state.fret, r.state.finger): r
            for r in chord if _is_active_fretted(r)
        }
        fretted = list(contacts.values())
        if len(fretted) < 2:
            continue
        violations.extend(_validate_duplicate_fingers(fretted))
        violations.extend(_validate_chord_ordering(fretted))
        violations.extend(_validate_chord_spans(fretted, config))
        violations.extend(_validate_chord_hand_positions(fretted))
    return violations


def _validate_transitions(
    results: Sequence[FingeringResult],
    config: BiomechanicalRuleConfig,
) -> list[BiomechanicalViolation]:
    violations: list[BiomechanicalViolation] = []
    ordered = sorted(results, key=lambda r: _timeline_key(r))
    previous_by_voice: dict[int, FingeringResult] = {}
    for current in ordered:
        voice = current.note_event.voice_hint or 0
        previous = previous_by_voice.get(voice)
        if previous is not None:
            violations.extend(_validate_extreme_shift(previous, current, config))
        previous_by_voice[voice] = current
    return violations


def _validate_tie_contacts(
    results: Sequence[FingeringResult],
) -> list[BiomechanicalViolation]:
    previous: dict[tuple[int, int], FingeringResult] = {}
    violations: list[BiomechanicalViolation] = []
    for current in sorted(results, key=lambda result: (result.note_event.onset, result.note_id)):
        note = current.note_event
        key = (note.voice_hint or 0, note.string_hint or current.state.string_num)
        prior = previous.get(key)
        if note.is_tie_dest and prior is not None and (
            prior.state.string_num != current.state.string_num
            or prior.state.fret != current.state.fret
            or prior.state.finger != current.state.finger
        ):
            violations.append(_multi_violation(
                "BIO-TIE-001", BiomechanicalSeverity.FATAL,
                "A tie changes its contact without an explicit finger substitution.",
                (prior, current), context={},
            ))
        previous[key] = current
    return violations


def _validate_ring_releases(
    results: Sequence[FingeringResult],
) -> list[BiomechanicalViolation]:
    required = required_contact_ends(results)
    violations = []
    for result in results:
        release = result.let_ring_end
        if release is not None and (
            not result.note_event.let_ring
            or not isfinite(release)
            or release < required[result.note_id]
        ):
            violations.append(BiomechanicalViolation(
                code="BIO-SUSTAIN-002", severity=BiomechanicalSeverity.FATAL,
                message="A let-ring release cannot shorten a written duration or tie.",
                note_ids=(result.note_id,), measure_index=result.note_event.measure_index,
                onset=result.note_event.onset,
                context={"release": release, "required_end": required[result.note_id]},
            ))
    return violations


def sounding_occupations(
    results: Sequence[FingeringResult],
) -> list[tuple[float, tuple[FingeringResult, ...]]]:
    """Sweep all voices, retaining every sounding contact at each attack.

    Source duration occupies a contact until its end. Let-ring extends to the
    next attack on its string or to an explicit planned release, never before
    the written duration/tie ends. A later same-voice attack on that string replaces
    its previous pitch; other voices cannot silently truncate a notated sustain.
    Cross-voice unisons retain both score identities and share a physical contact.
    """
    groups: dict[tuple[float, int | None], list[FingeringResult]] = defaultdict(list)
    for result in results:
        groups[(result.note_event.onset, result.note_event.measure_index)].append(result)
    active: list[FingeringResult] = []
    required = required_contact_ends(results)
    frames: list[tuple[float, tuple[FingeringResult, ...]]] = []
    for (onset, measure), attacks in sorted(
        groups.items(), key=lambda item: (item[0][0], item[0][1] or 0),
    ):
        kept: list[FingeringResult] = []
        for previous in active:
            note = previous.note_event
            if note.onset == onset and note.measure_index != measure:
                continue
            if contact_end(previous, required[previous.note_id]) <= onset:
                continue
            replaced = any(
                previous.state.string_num == attack.state.string_num
                and note.onset < onset
                and (
                    _same_voice(previous, attack)
                    or (note.let_ring and required[previous.note_id] <= onset)
                )
                for attack in attacks
            )
            if not replaced:
                kept.append(previous)
        active = kept + attacks
        frames.append((onset, tuple(active)))
    return frames


def validate_contact_configuration(
    contacts: Sequence[FingeringResult],
    config: BiomechanicalRuleConfig | None = None,
) -> tuple[BiomechanicalViolation, ...]:
    """Check one whole-hand occupation, including open strings under a barre.

    This discrete check establishes contact compatibility only. It does not
    certify joint angles, motion speeds, skin collisions or acoustic pressure.
    """
    rule_config = config or BiomechanicalRuleConfig()
    sounding = [result for result in contacts if not result.note_event.muted]
    violations = _validate_same_string_chord(sounding)
    # Identical notation in two voices is one contact, not two fingers.
    unique: dict[tuple[int, int, Finger], FingeringResult] = {}
    for result in sounding:
        unique.setdefault(
            (result.state.string_num, result.state.fret, result.state.finger), result,
        )
    fretted = [result for result in unique.values() if _is_active_fretted(result)]
    violations.extend(_validate_duplicate_fingers(fretted))
    violations.extend(_validate_chord_ordering(fretted))
    if len(fretted) > 1:
        violations.extend(_validate_chord_spans(fretted, rule_config))
    by_position: dict[tuple[int, int], list[FingeringResult]] = defaultdict(list)
    for result in fretted:
        by_position[(result.state.string_num, result.state.fret)].append(result)
    for notes in by_position.values():
        if len(notes) > 1:
            violations.append(_multi_violation(
                "BIO-CONTACT-001", BiomechanicalSeverity.FATAL,
                "A shared sounding contact is assigned to different fingers.", notes,
                context={},
            ))
    indices = [result for result in fretted if result.state.finger == Finger.INDEX]
    if len(indices) > 1 and len({result.state.fret for result in indices}) == 1:
        fret = indices[0].state.fret
        low = min(result.state.string_num for result in indices)
        high = max(result.state.string_num for result in indices)
        blocked = [
            result for result in sounding
            if low <= result.state.string_num <= high and result.state.fret < fret
        ]
        if blocked:
            violations.append(_multi_violation(
                "BIO-CONTACT-002", BiomechanicalSeverity.FATAL,
                "An index barre interrupts a required lower or open-string note.",
                [*indices, *blocked],
                context={"barre_fret": fret, "string_from": low, "string_to": high},
            ))
    return tuple(violations)


def _validate_occupations(
    results: Sequence[FingeringResult], config: BiomechanicalRuleConfig,
) -> list[BiomechanicalViolation]:
    violations: list[BiomechanicalViolation] = []
    seen: set[tuple[str, tuple[int, ...]]] = set()
    for onset, active in sounding_occupations(results):
        for violation in validate_contact_configuration(active, config):
            # Existing chord diagnostics already describe simultaneous attacks.
            involved = [r for r in active if r.note_id in violation.note_ids]
            if (
                violation.code.startswith("BIO-CHORD-")
                and len({r.note_event.onset for r in involved}) <= 1
            ):
                continue
            code = "BIO-SUSTAIN-001" if violation.code == "BIO-CHORD-001" else violation.code
            if violation.code == "BIO-CHORD-002":
                code = "BIO-TRANS-002"
            key = (code, tuple(sorted(violation.note_ids)))
            if key in seen:
                continue
            seen.add(key)
            violations.append(BiomechanicalViolation(
                code=code, severity=violation.severity, message=violation.message,
                note_ids=violation.note_ids, measure_index=violation.measure_index,
                onset=onset, context=violation.context,
            ))
    return violations


def _validate_same_string_chord(chord: Sequence[FingeringResult]) -> list[BiomechanicalViolation]:
    by_string: dict[int, list[FingeringResult]] = defaultdict(list)
    for result in chord:
        by_string[result.state.string_num].append(result)

    violations: list[BiomechanicalViolation] = []
    for string_num, notes in by_string.items():
        frets = {r.state.fret for r in notes}
        if len(frets) <= 1:
            continue
        violations.append(_multi_violation(
            "BIO-CHORD-001",
            BiomechanicalSeverity.FATAL,
            "Two simultaneous notes use the same string at different frets.",
            notes,
            context={"string": string_num, "frets": sorted(frets)},
        ))
    return violations


def _validate_duplicate_fingers(
    fretted: Sequence[FingeringResult],
) -> list[BiomechanicalViolation]:
    by_finger: dict[Finger, list[FingeringResult]] = defaultdict(list)
    for result in fretted:
        by_finger[result.state.finger].append(result)

    violations: list[BiomechanicalViolation] = []
    for finger, notes in by_finger.items():
        if len(notes) <= 1:
            continue
        frets = {r.state.fret for r in notes}
        strings = sorted(r.state.string_num for r in notes)
        if finger == Finger.INDEX and len(frets) == 1:
            continue
        violations.append(_multi_violation(
            "BIO-CHORD-002",
            BiomechanicalSeverity.FATAL,
            "A fretting finger is assigned to incompatible simultaneous notes.",
            notes,
            context={
                "finger": finger.value,
                "frets": sorted(frets),
                "strings": strings,
            },
        ))
    return violations


def _validate_chord_ordering(
    fretted: Sequence[FingeringResult],
) -> list[BiomechanicalViolation]:
    violations: list[BiomechanicalViolation] = []
    notes = sorted(fretted, key=lambda r: (r.state.fret, r.state.string_num))
    for index, lower in enumerate(notes):
        lower_rank = _FINGER_RANK[lower.state.finger]
        for higher in notes[index + 1:]:
            higher_rank = _FINGER_RANK[higher.state.finger]
            if lower.state.fret < higher.state.fret and lower_rank > higher_rank:
                violations.append(_multi_violation(
                    "BIO-CHORD-003",
                    BiomechanicalSeverity.FATAL,
                    "Finger order crosses ascending frets inside a chord.",
                    (lower, higher),
                    context={
                        "lower_fret": lower.state.fret,
                        "lower_finger": lower.state.finger.value,
                        "higher_fret": higher.state.fret,
                        "higher_finger": higher.state.finger.value,
                    },
                ))
    return violations


def _validate_chord_spans(
    fretted: Sequence[FingeringResult],
    config: BiomechanicalRuleConfig,
) -> list[BiomechanicalViolation]:
    frets = [r.state.fret for r in fretted]
    violations: list[BiomechanicalViolation] = []
    if max(frets) - min(frets) > config.max_chord_span:
        violations.append(_multi_violation(
            "BIO-CHORD-004",
            BiomechanicalSeverity.FATAL,
            "Chord fret span exceeds the configured hard limit.",
            fretted,
            context={"span": max(frets) - min(frets), "max_span": config.max_chord_span},
        ))

    for first_index, first in enumerate(fretted):
        first_rank = _FINGER_RANK[first.state.finger]
        for second in fretted[first_index + 1:]:
            second_rank = _FINGER_RANK[second.state.finger]
            if first_rank == second_rank:
                continue
            low_rank, high_rank = sorted((first_rank, second_rank))
            gap = abs(second.state.fret - first.state.fret)
            max_gap = _MAX_FINGER_PAIR_SPAN.get((low_rank, high_rank), config.max_chord_span)
            if min(first.state.fret, second.state.fret) >= 12:
                max_gap += 1
            if gap > max_gap:
                violations.append(_multi_violation(
                    "BIO-CHORD-005",
                    BiomechanicalSeverity.FATAL,
                    "Finger-pair fret span exceeds the anatomical limit.",
                    (first, second),
                    context={"gap": gap, "max_gap": max_gap},
                ))
    return violations


def _validate_chord_hand_positions(
    fretted: Sequence[FingeringResult],
) -> list[BiomechanicalViolation]:
    hand_positions = {r.state.hand_position for r in fretted}
    if len(hand_positions) <= 1:
        return []
    return [_multi_violation(
        "BIO-CHORD-006",
        BiomechanicalSeverity.MEDIUM,
        "Simultaneous fretted notes do not share one hand position.",
        fretted,
        context={"hand_positions": sorted(hand_positions)},
    )]


def _validate_extreme_shift(
    previous: FingeringResult,
    current: FingeringResult,
    config: BiomechanicalRuleConfig,
) -> list[BiomechanicalViolation]:
    delta = abs(current.state.hand_position - previous.state.hand_position)
    if delta == 0:
        return []
    elapsed_beats = max(current.note_event.onset - previous.note_event.onset, 0.0)
    if elapsed_beats <= 0:
        return []
    shift_per_beat = delta / elapsed_beats
    if shift_per_beat <= config.max_shift_per_beat:
        return []
    return [_multi_violation(
        "BIO-TRANS-001",
        BiomechanicalSeverity.MEDIUM,
        "Hand-position shift is extreme for the elapsed musical time.",
        (previous, current),
        context={
            "delta_hand_position": delta,
            "elapsed_beats": elapsed_beats,
            "shift_per_beat": shift_per_beat,
            "max_shift_per_beat": config.max_shift_per_beat,
        },
    )]


def _group_by_onset(
    results: Sequence[FingeringResult],
    precision: int,
) -> dict[tuple[int | None, float], list[FingeringResult]]:
    groups: dict[tuple[int | None, float], list[FingeringResult]] = defaultdict(list)
    for result in results:
        groups[
            (result.note_event.measure_index, round(result.note_event.onset, precision))
        ].append(result)
    return dict(groups)


def _timeline_key(result: FingeringResult) -> tuple[int, float, int]:
    measure = result.note_event.measure_index
    return (-1 if measure is None else measure, result.note_event.onset, result.note_id)


def _same_voice(first: FingeringResult, second: FingeringResult) -> bool:
    first_voice = first.note_event.voice_hint if first.note_event.voice_hint is not None else 0
    second_voice = second.note_event.voice_hint if second.note_event.voice_hint is not None else 0
    return first_voice == second_voice


def _is_active_fretted(result: FingeringResult) -> bool:
    return (
        result.state.fret > 0
        and result.state.finger != Finger.OPEN
        and not result.note_event.muted
    )


def _location(result: FingeringResult) -> tuple[int | None, float]:
    return result.note_event.measure_index, result.note_event.onset


def _violation(
    code: str,
    severity: BiomechanicalSeverity,
    message: str,
    result: FingeringResult,
    *,
    context: dict[str, object],
) -> BiomechanicalViolation:
    measure_index, onset = _location(result)
    return BiomechanicalViolation(
        code=code,
        severity=severity,
        message=message,
        note_ids=(result.note_id,),
        measure_index=measure_index,
        onset=onset,
        context=context,
    )


def _multi_violation(
    code: str,
    severity: BiomechanicalSeverity,
    message: str,
    results: Sequence[FingeringResult],
    *,
    context: dict[str, object],
) -> BiomechanicalViolation:
    first = results[0]
    measure_index, onset = _location(first)
    return BiomechanicalViolation(
        code=code,
        severity=severity,
        message=message,
        note_ids=tuple(r.note_id for r in results),
        measure_index=measure_index,
        onset=onset,
        context=context,
    )


__all__ = [
    "BiomechanicalReport",
    "BiomechanicalRuleConfig",
    "BiomechanicalSeverity",
    "BiomechanicalViolation",
    "validate_fingering_results",
    "sounding_occupations",
    "validate_contact_configuration",
]
