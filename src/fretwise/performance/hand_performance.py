"""HandPerformance 1.1 contract and loss-aware adapter for final fingerings.

Implements Notion replacement specification sections 7, 11 and 19. No optimizer
is invoked here. Unknown or insufficiently specified expressions remain visible
as diagnostics instead of being silently removed or assigned invented curves.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from fractions import Fraction
from math import isfinite, lcm
from typing import Annotated, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from fretwise.models import Articulation, FingeringResult, NoteEvent
from fretwise.performance.tempo import TempoMap
from fretwise.sustain import required_contact_ends

Tick = Annotated[int, Field(ge=0)]
Positive = Annotated[float, Field(gt=0)]
Provenance = Literal["source", "user", "computed", "inferred"]
FingerName = Literal["open", "index", "middle", "ring", "pinky", "thumb"]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class Interval(_Contract):
    """Absolute interval on the unfolded score timeline."""

    startTick: Tick
    endTick: Tick

    @model_validator(mode="after")
    def ordered(self) -> Self:
        """Reject inverted intervals."""
        if self.endTick < self.startTick:
            raise ValueError("Inverted tick interval")
        return self


class TempoPoint(_Contract):
    """Microseconds per quarter note, independent of meter denominator."""

    tick: Tick
    usPerQuarter: Positive


class Fingering(_Contract):
    """Final fingering; provenance is never treated as calibrated confidence."""

    finger: FingerName
    stringNo: Annotated[int, Field(ge=1)]
    fretAbs: Tick
    handPositionHint: int | None = None
    provenance: Provenance
    locked: bool


class PlayedNote(_Contract):
    """One unambiguous source-note occurrence."""

    occurrenceId: str
    sourceNoteId: str
    voiceId: str
    onTick: Tick
    notatedEndTick: Tick
    soundEndTick: Tick
    basePitchMidi: Annotated[int, Field(ge=0, le=127)]
    velocity: Annotated[int, Field(ge=0, le=127)]
    fingering: Fingering
    expressionIds: list[str]


class CurvePoint(_Contract):
    """Absolute tick and scalar value, with units supplied by the expression."""

    tick: Tick
    value: float


class Curve(_Contract):
    """Linear interpolation preserves plateaus without spline overshoot."""

    interpolation: Literal["linear"] = "linear"
    points: list[CurvePoint]


class Expression(Interval):
    """Musical expression with retained source data for unknown techniques."""

    id: str
    noteIds: list[str]
    provenance: Provenance
    kind: Literal[
        "bend",
        "vibrato",
        "slide",
        "hammer_on",
        "pull_off",
        "tie",
        "let_ring",
        "staccato",
        "dead_note",
        "harmonic",
        "palm_mute",
        "tremolo_picking",
        "pick_attack",
        "trill",
        "unknown",
    ]
    cents: Curve | None = None
    direction: Literal["toward_bass", "toward_treble", "auto"] | None = None
    preBend: bool | None = None
    mechanism: Literal["lateral", "longitudinal", "unspecified"] | None = None
    fromId: str | None = None
    toId: str | None = None
    mode: Literal["legato", "shift", "natural", "artificial"] | None = None
    soundingPitchMidi: Annotated[int, Field(ge=0, le=127)] | None = None
    nodeXM: float | None = None
    rateHz: Positive | None = None
    sourceKind: str | None = None
    raw: JsonValue = None

    @model_validator(mode="after")
    def semantics(self) -> Self:
        """Check required technique fields and complete finite curves."""
        if self.kind in ("bend", "vibrato") and self.cents is None:
            raise ValueError("Pitch expression requires a cents curve")
        if self.kind in ("slide", "hammer_on", "pull_off", "trill"):
            if not self.fromId or not self.toId or self.fromId == self.toId:
                raise ValueError("Linked expression requires distinct source and destination")
        if self.kind == "trill" and self.rateHz is None:
            raise ValueError("Trill frequency must be positive and explicit in Hz")
        if self.kind == "unknown" and not self.sourceKind:
            raise ValueError("Unknown expression must preserve its source kind")
        if self.cents is not None:
            ticks = [point.tick for point in self.cents.points]
            if (
                len(ticks) < 2
                or ticks != sorted(set(ticks))
                or ticks[0] != self.startTick
                or ticks[-1] != self.endTick
            ):
                raise ValueError("Curve must cover its interval with strictly increasing ticks")
        return self


class BarreHint(Interval):
    """Explicit interval occupied by a multi-string finger contact."""

    id: str
    finger: FingerName
    fretAbs: Tick
    stringNos: list[int]
    locked: bool


class HoldHint(Interval):
    """Optional planted-finger contact with a finite lifetime."""

    finger: FingerName
    stringNo: int
    fretAbs: Tick
    provenance: Provenance


class Diagnostic(_Contract):
    """Machine-readable missing-data or coverage diagnosis."""

    code: str
    message: str
    noteIds: list[str] = Field(default_factory=list)


class HandProfile(_Contract):
    """Immutable reference to a hand profile."""

    side: Literal["left", "right"] = "left"
    profileId: str = "adult-reference-left"
    profileRevision: str = "1"


class InstrumentString(_Contract):
    """String numbering starts at the highest-pitched string."""

    number: Annotated[int, Field(ge=1)]
    openPitchMidi: Annotated[int, Field(ge=0, le=127)]


class InstrumentProfile(_Contract):
    """Instrument geometry in meters, absolute frets counted from the nut."""

    profileId: str = "six-string-648"
    profileRevision: str = "1"
    scaleLengthM: Positive = 0.648
    fretCount: Annotated[int, Field(ge=1)] = 24
    capoFret: Tick = 0
    strings: list[InstrumentString] = Field(
        default_factory=lambda: [
            InstrumentString(number=i + 1, openPitchMidi=pitch)
            for i, pitch in enumerate((64, 59, 55, 50, 45, 40))
        ]
    )


class NoteExecution(_Contract):
    """Shared attack/sustain policy, distinct from the nominal note length."""

    occurrenceId: str
    attackKind: Literal["pick", "hammer_on", "pull_off", "tapping", "continuation", "none"]
    excitationGroupId: str
    sustainRequiredUntilTick: Tick
    dampingAtTick: Tick | None = None
    timingProvenance: Provenance


class ExecutionAttack(_Contract):
    """Effective attack within a chord or arpeggio."""

    occurrenceId: str
    onTick: Tick


class ExecutionGroup(_Contract):
    """Group preserves each attack's effective date."""

    id: str
    kind: Literal["single", "chord", "arpeggio", "strum"]
    noteIds: list[str]
    attacks: list[ExecutionAttack]


class ExpressionDetail(_Contract):
    """Explicit pitch composition prevents applying vibrato twice."""

    expressionId: str
    pitchComposition: Literal["absoluteFromBase", "additiveResidual"] | None = None
    supportFingerIds: list[FingerName] = Field(default_factory=list)


class HandPerformance(_Contract):
    """Validated HandPerformance 1.1; JSON Schema is generated from this model."""

    schemaVersion: Literal["1.1"] = "1.1"
    scoreId: str
    trackId: str
    scoreRevision: str
    fingeringRevision: str
    performanceTimingRevision: str = "notated-v1"
    requiredCapabilities: list[str]
    ppq: Annotated[int, Field(gt=0)]
    range: Interval
    tempoMap: list[TempoPoint]
    hand: HandProfile
    instrument: InstrumentProfile
    notes: list[PlayedNote]
    expressions: list[Expression]
    barres: list[BarreHint]
    holds: list[HoldHint]
    diagnostics: list[Diagnostic]
    noteExecution: list[NoteExecution]
    executionGroups: list[ExecutionGroup]
    expressionDetails: list[ExpressionDetail]
    transitionHints: list[JsonValue] = Field(default_factory=list)

    @model_validator(mode="after")
    def references_and_geometry(self) -> Self:
        """Reject invalid identities, intervals, references and fret coordinates."""
        notes = {note.occurrenceId: note for note in self.notes}
        expressions = {expression.id: expression for expression in self.expressions}
        groups = {group.id: group for group in self.executionGroups}
        if len(notes) != len(self.notes) or len(expressions) != len(self.expressions):
            raise ValueError("Duplicate occurrence or expression ID")
        if len(groups) != len(self.executionGroups):
            raise ValueError("Duplicate execution group ID")
        ticks = [point.tick for point in self.tempoMap]
        if not ticks or ticks[0] != 0 or ticks != sorted(set(ticks)):
            raise ValueError("Tempo map must start at zero and strictly increase")
        strings = {string.number for string in self.instrument.strings}
        if strings != set(range(1, len(self.instrument.strings) + 1)):
            raise ValueError("Instrument strings must be numbered exactly 1..N")
        for note in self.notes:
            if note.notatedEndTick <= note.onTick or note.soundEndTick < note.onTick:
                raise ValueError("Invalid note interval")
            fingering = note.fingering
            if (
                fingering.stringNo not in strings
                or not self.instrument.capoFret <= fingering.fretAbs <= self.instrument.fretCount
            ):
                raise ValueError("Fingering lies outside instrument")
            if (fingering.finger == "open") != (fingering.fretAbs == self.instrument.capoFret):
                raise ValueError("Open finger must correspond exactly to nut/capo")
            if not set(note.expressionIds) <= expressions.keys():
                raise ValueError("Unknown note expression reference")
        for expression in self.expressions:
            refs = set(expression.noteIds) | {x for x in (expression.fromId, expression.toId) if x}
            if not refs <= notes.keys():
                raise ValueError("Unknown expression note reference")
            if any(expression.id not in notes[key].expressionIds for key in expression.noteIds):
                raise ValueError("Expression reference must be bidirectional")
        execution_ids = [execution.occurrenceId for execution in self.noteExecution]
        if len(execution_ids) != len(set(execution_ids)) or set(execution_ids) != notes.keys():
            raise ValueError("Exactly one noteExecution entry required per occurrence")
        for execution in self.noteExecution:
            note = notes[execution.occurrenceId]
            if execution.excitationGroupId not in groups:
                raise ValueError("Unknown excitation group")
            if not note.onTick <= execution.sustainRequiredUntilTick <= note.soundEndTick:
                raise ValueError("Sustain deadline lies outside sound interval")
            if execution.dampingAtTick is not None and execution.dampingAtTick < note.onTick:
                raise ValueError("Damping precedes the note")
        for group in self.executionGroups:
            if not set(group.noteIds) <= notes.keys():
                raise ValueError("Unknown execution group note")
            if {a.occurrenceId for a in group.attacks} != set(group.noteIds):
                raise ValueError("Group attacks must cover every member exactly")
            for attack in group.attacks:
                if attack.onTick != notes[attack.occurrenceId].onTick:
                    raise ValueError("Contradictory attack timestamp")
        for detail in self.expressionDetails:
            if detail.expressionId not in expressions:
                raise ValueError("Unknown expressionDetails reference")
        contact_hints: list[HoldHint | BarreHint] = [*self.holds, *self.barres]
        for hint in contact_hints:
            hint_strings = hint.stringNos if isinstance(hint, BarreHint) else [hint.stringNo]
            if (
                hint.finger == "open"
                or not set(hint_strings) <= strings
                or not self.instrument.capoFret < hint.fretAbs <= self.instrument.fretCount
            ):
                raise ValueError("Invalid hold/barre geometry")
        return self


def validate_hand_performance(document: Mapping[str, object]) -> HandPerformance:
    """Validate input and reject unknown versions rather than losing semantics."""
    return HandPerformance.model_validate(document)


def _ppq(events: Sequence[NoteEvent]) -> int:
    ppq = 960
    for event in events:
        for beat in (event.onset, event.duration):
            fraction = Fraction(beat).limit_denominator(15360)
            ppq = lcm(ppq, fraction.denominator)
            if ppq > 15_360_000:
                raise ValueError("Rhythmic precision exceeds supported PPQ")
    return ppq


def build_hand_performance(
    events: Sequence[NoteEvent],
    results: Sequence[FingeringResult],
    score_context: Mapping[str, object] | None = None,
    instrument: Mapping[str, object] | None = None,
    hand_profile: Mapping[str, object] | None = None,
) -> dict[str, JsonValue]:
    """Join final results to events and build a validated, absolute-time document.

    Context accepts scoreId/trackId and revision strings, an optional tempoMap
    (in the chosen PPQ), range, and lockedNoteIds/userNoteIds (source IDs). Notes
    are already in transport occurrence order; callers must unfold repeats with
    the audio transport before calling, never independently inside the renderer.
    """
    context = dict(score_context or {})
    if len(events) != len(results):
        raise ValueError("Every source occurrence must have exactly one final fingering")
    by_key = {
        (r.note_event.source_note_id, r.note_event.onset, r.note_event.voice_hint, r.note_id): r
        for r in results
    }
    if len(by_key) != len(results):
        raise ValueError("Duplicate result identity")
    unused = list(results)
    joined: list[tuple[NoteEvent, FingeringResult]] = []
    for event in events:
        result = next((r for r in unused if r.note_event is event), None)
        if result is None:
            matches = [r for r in unused if r.note_event == event]
            if len(matches) != 1:
                raise ValueError("Source/result join is missing or ambiguous")
            result = matches[0]
        unused.remove(result)
        joined.append((event, result))
    joined.sort(key=lambda pair: (pair[0].onset, pair[0].voice_hint or 0, pair[1].note_id))
    ppq = _ppq(events)
    tempo = TempoMap.from_events(events)
    instrument_model = InstrumentProfile.model_validate(instrument or {})
    notes: list[PlayedNote] = []
    expressions: list[Expression] = []
    execution: list[NoteExecution] = []
    groups: list[ExecutionGroup] = []
    diagnostics: list[Diagnostic] = []
    details: list[ExpressionDetail] = []
    counts: dict[str, int] = defaultdict(int)
    locked = set(cast(Sequence[str], context.get("lockedNoteIds", [])))
    user_ids = set(cast(Sequence[str], context.get("userNoteIds", [])))
    performance_rows = cast(
        Mapping[str, Mapping[str, object]], context.get("performanceByNoteId", {})
    )
    capabilities = {"transport.tempoMap", "performance.noteExecution"}
    source_events: dict[str, NoteEvent] = {}
    source_performance: dict[str, Mapping[str, object]] = {}
    source_results: dict[str, FingeringResult] = {}
    required_ends = required_contact_ends([result for _event, result in joined])
    for event, result in joined:
        source_id = event.source_note_id or f"note-{result.note_id}"
        counts[source_id] += 1
        occurrence_id = f"{source_id}@{counts[source_id]}"
        on_tick = round(event.onset * ppq)
        end_tick = round((event.onset + event.duration) * ppq)
        perf = performance_rows.get(str(result.note_id), {})
        sound_end_tick = (
            on_tick + round(float(cast(float, perf["dur_beats"])) * ppq)
            if "dur_beats" in perf
            else end_tick
        )
        provenance: Provenance = "computed"
        if source_id in user_ids:
            provenance = "user"
        elif event.source_finger is not None and event.source_finger == result.state.finger:
            provenance = "source"
        note = PlayedNote(
            occurrenceId=occurrence_id,
            sourceNoteId=source_id,
            voiceId=str(event.voice_hint or 0),
            onTick=on_tick,
            notatedEndTick=end_tick,
            soundEndTick=sound_end_tick,
            basePitchMidi=event.pitch,
            velocity=int(
                cast(
                    int,
                    perf.get(
                        "velocity",
                        {"pp": 32, "p": 48, "mp": 64, "mf": 80, "f": 96, "ff": 112}[
                            event.dynamic.value
                        ],
                    ),
                )
            ),
            fingering=Fingering(
                finger=result.state.finger.value,
                stringNo=result.state.string_num,
                fretAbs=result.state.fret + instrument_model.capoFret,
                handPositionHint=result.state.hand_position,
                provenance=provenance,
                locked=source_id in locked,
            ),
            expressionIds=[],
        )
        notes.append(note)
        source_events[occurrence_id] = event
        source_performance[occurrence_id] = perf
        source_results[occurrence_id] = result
        for code in event.timing_diagnostics:
            diagnostics.append(Diagnostic(code=code, message=code, noteIds=[occurrence_id]))
        if event.source_note_id is None:
            diagnostics.append(
                Diagnostic(
                    code="SOURCE_ID_INFERRED",
                    message="Source format did not supply a stable note ID",
                    noteIds=[occurrence_id],
                )
            )
    # A note with let-ring holds until the next attack on that string, or score end.
    score_end = max((note.notatedEndTick for note in notes), default=0)
    incoming: dict[str, tuple[PlayedNote, str]] = {}
    linked_destinations: dict[str, PlayedNote] = {}
    for note in notes:
        event = source_events[note.occurrenceId]
        if not event.technique_to_source_note_id:
            continue
        destination = next(
            (
                candidate
                for candidate in notes
                if candidate.sourceNoteId == event.technique_to_source_note_id
                and candidate.voiceId == note.voiceId
                and candidate.fingering.stringNo == note.fingering.stringNo
                and note.onTick < candidate.onTick <= note.notatedEndTick
            ),
            None,
        )
        if destination is not None:
            linked_destinations[note.occurrenceId] = destination
            incoming[destination.occurrenceId] = (note, event.articulation.value)
    for index, note in enumerate(notes):
        event = source_events[note.occurrenceId]
        has_timing = "dur_beats" in source_performance[note.occurrenceId]
        if event.let_ring and not has_timing:
            following = next(
                (
                    n
                    for n in notes[index + 1 :]
                    if n.fingering.stringNo == note.fingering.stringNo and n.onTick > note.onTick
                ),
                None,
            )
            note.soundEndTick = max(
                note.notatedEndTick, following.onTick if following else score_end
            )
        result = source_results[note.occurrenceId]
        has_release = event.let_ring and result.let_ring_end is not None
        if has_release:
            release = cast(float, result.let_ring_end)
            if not isfinite(release):
                raise ValueError("Let-ring release must be finite")
            note.soundEndTick = max(
                round(required_ends[result.note_id] * ppq),
                min(note.soundEndTick, round(release * ppq)),
            )
        group_id = f"attack-{note.onTick}"
        attack_kind: Literal["pick", "tapping", "continuation", "hammer_on", "pull_off"] = (
            "continuation" if event.is_tie_dest else "tapping" if event.tapping else "pick"
        )
        origin_relation = incoming.get(note.occurrenceId)
        if origin_relation is not None:
            origin, relation = origin_relation
            if relation in ("hammer_on", "pull_off"):
                attack_kind = cast(Literal["hammer_on", "pull_off"], relation)
                group_id = next(
                    ex.excitationGroupId
                    for ex in execution
                    if ex.occurrenceId == origin.occurrenceId
                )
            elif relation == "slide" and source_events[origin.occurrenceId].slide_type == "legato":
                attack_kind = "continuation"
                group_id = next(
                    ex.excitationGroupId
                    for ex in execution
                    if ex.occurrenceId == origin.occurrenceId
                )
        execution.append(
            NoteExecution(
                occurrenceId=note.occurrenceId,
                attackKind=attack_kind,
                excitationGroupId=group_id,
                sustainRequiredUntilTick=note.soundEndTick,
                dampingAtTick=note.soundEndTick if has_timing or has_release else None,
                timingProvenance=(
                    "computed"
                    if has_timing or has_release
                    else "inferred"
                    if event.let_ring or event.staccato
                    else "source"
                ),
            )
        )
        kinds = []
        for flag, kind in (
            (event.let_ring, "let_ring"),
            (event.is_tie_dest, "tie"),
            (event.staccato, "staccato"),
            (event.muted, "dead_note"),
            (event.palm_muted, "palm_mute"),
            (event.tremolo_picking, "tremolo_picking"),
        ):
            if flag:
                kinds.append(kind)
        if event.bend_points or event.bend_value is not None:
            kinds.append("bend")
        if event.harmonic_type:
            kinds.append("harmonic")
        if event.articulation in (
            Articulation.HAMMER_ON,
            Articulation.PULL_OFF,
            Articulation.SLIDE,
            Articulation.VIBRATO,
            Articulation.WIDE_VIBRATO,
            Articulation.TAPPING,
        ):
            kinds.append(event.articulation.value)
        for kind in dict.fromkeys(kinds):
            expression_id = f"{note.occurrenceId}:{kind}"
            payload: dict[str, object] = dict(
                id=expression_id,
                noteIds=[note.occurrenceId],
                startTick=note.onTick,
                endTick=note.notatedEndTick,
                provenance="source",
                kind=kind,
            )
            if kind == "bend" and event.bend_points:
                payload.update(
                    cents={
                        "interpolation": "linear",
                        "points": [
                            {
                                "tick": note.onTick
                                + round(position * (note.notatedEndTick - note.onTick)),
                                "value": cents,
                            }
                            for position, cents in event.bend_points
                        ],
                    },
                    direction="auto",
                    preBend=event.bend_points[0][1] != 0,
                )
                details.append(
                    ExpressionDetail(
                        expressionId=expression_id, pitchComposition="absoluteFromBase"
                    )
                )
                capabilities.add("motion.bendCurve")
            elif kind == "harmonic":
                payload.update(
                    mode="natural" if event.harmonic_type == "natural" else "artificial",
                    soundingPitchMidi=event.harmonic_resultant_pitch or event.pitch,
                )
            elif kind in ("hammer_on", "pull_off", "slide") and (
                note.occurrenceId in linked_destinations
            ):
                destination = linked_destinations[note.occurrenceId]
                payload.update(
                    fromId=note.occurrenceId,
                    toId=destination.occurrenceId,
                    noteIds=[note.occurrenceId, destination.occurrenceId],
                    endTick=destination.notatedEndTick,
                )
                if kind == "slide":
                    payload["mode"] = "legato" if event.slide_type == "legato" else "shift"
                destination.expressionIds.append(expression_id)
                capabilities.add(
                    {
                        "hammer_on": "motion.hammerOn",
                        "pull_off": "motion.pullOff",
                        "slide": "motion.slide",
                    }[kind]
                )
            elif kind not in (
                "tie",
                "let_ring",
                "staccato",
                "dead_note",
                "palm_mute",
                "tremolo_picking",
            ):
                payload.update(
                    kind="unknown",
                    sourceKind=kind,
                    raw={
                        "articulation": event.articulation.value,
                        "bend_value": event.bend_value,
                        "bend_type": event.bend_type,
                        "slide_type": event.slide_type,
                        "vibrato_wide": event.vibrato_wide,
                    },
                )
                diagnostics.append(
                    Diagnostic(
                        code="EXPRESSION_DATA_INCOMPLETE",
                        message=f"{kind}: exact curve or source relation unavailable",
                        noteIds=[note.occurrenceId],
                    )
                )
                capabilities.add("expression.unknown")
            expressions.append(Expression.model_validate(payload))
            note.expressionIds.append(expression_id)
        if event.staccato and not has_timing:
            diagnostics.append(
                Diagnostic(
                    code="TIMING_AMBIGUOUS",
                    message="Staccato damping needs the shared playback articulation policy",
                    noteIds=[note.occurrenceId],
                )
            )
    for tick in sorted({note.onTick for note in notes}):
        members = [note for note in notes if note.onTick == tick]
        groups.append(
            ExecutionGroup(
                id=f"attack-{tick}",
                kind="chord" if len(members) > 1 else "single",
                noteIds=[note.occurrenceId for note in members],
                attacks=[
                    ExecutionAttack(occurrenceId=n.occurrenceId, onTick=n.onTick) for n in members
                ],
            )
        )
    tempo_json = context.get("tempoMap")
    tempo_points = (
        [TempoPoint.model_validate(point) for point in cast(list[object], tempo_json)]
        if tempo_json is not None
        else [
            TempoPoint(tick=round(beat * ppq), usPerQuarter=60_000_000.0 / bpm)
            for beat, bpm in tempo.points
        ]
    )
    if not any(event.tempo_points for event in events) and tempo_json is None and events:
        diagnostics.append(
            Diagnostic(
                code="TEMPO_MAP_INFERRED",
                message=("Tempo inferred from notes; silent-span changes require "
                         "source tempo metadata"),
            )
        )
    holds: list[HoldHint] = []
    barres: list[BarreHint] = []
    for note in notes:
        result = source_results[note.occurrenceId]
        end = next((n.onTick for n in notes if n.onTick > note.onTick), note.notatedEndTick)
        for finger, (string_no, fret) in result.planted_fingers.items():
            if finger == "open" or fret <= 0:
                continue
            holds.append(
                HoldHint(
                    finger=cast(FingerName, finger),
                    stringNo=string_no,
                    fretAbs=fret + instrument_model.capoFret,
                    startTick=note.onTick,
                    endTick=end,
                    provenance="computed",
                )
            )
    # Infer barre hints from simultaneous selected contacts, never reassign fingers.
    boundaries: dict[int, list[tuple[bool, PlayedNote]]] = defaultdict(list)
    for note, ex in zip(notes, execution):
        if note.fingering.finger == "open":
            continue
        boundaries[note.onTick].append((True, note))
        boundaries[ex.sustainRequiredUntilTick].append((False, note))
    active: dict[str, PlayedNote] = {}
    times = sorted(boundaries)
    for tick, end in zip(times, times[1:]):
        for adding, note in sorted(boundaries[tick], key=lambda action: action[0]):
            if adding:
                active[note.occurrenceId] = note
            else:
                active.pop(note.occurrenceId, None)
        contacts: dict[tuple[FingerName, int], list[PlayedNote]] = defaultdict(list)
        for note in active.values():
            contacts[(note.fingering.finger, note.fingering.fretAbs)].append(note)
        for (finger, fret), members in contacts.items():
            strings = sorted({n.fingering.stringNo for n in members})
            if len(strings) > 1 and end > tick:
                barres.append(
                    BarreHint(
                        id=f"barre-{len(barres)}",
                        finger=finger,
                        fretAbs=fret,
                        stringNos=strings,
                        startTick=tick,
                        endTick=end,
                        locked=any(n.fingering.locked for n in members),
                    )
                )
    performance = HandPerformance(
        scoreId=str(context.get("scoreId", "score")),
        trackId=str(context.get("trackId", "0")),
        scoreRevision=str(context.get("scoreRevision", "unversioned")),
        fingeringRevision=str(context.get("fingeringRevision", "unversioned")),
        performanceTimingRevision=str(
            context.get(
                "performanceTimingRevision", "playback-v1" if performance_rows else "notated-v1"
            )
        ),
        requiredCapabilities=sorted(capabilities),
        ppq=ppq,
        range=Interval.model_validate(context.get("range", {"startTick": 0, "endTick": score_end})),
        tempoMap=tempo_points,
        hand=HandProfile.model_validate(hand_profile or {}),
        instrument=instrument_model,
        notes=notes,
        expressions=expressions,
        barres=barres,
        holds=holds,
        diagnostics=diagnostics,
        noteExecution=execution,
        executionGroups=groups,
        expressionDetails=details,
    )
    return cast(dict[str, JsonValue], performance.model_dump(mode="json", exclude_none=True))
