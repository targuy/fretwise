"""MusicXML export for M1/M5 results.

Converts a list of :class:`~fretwise.models.FingeringResult` into a MusicXML
score (``.musicxml``) that any notation editor — MuseScore, Finale, Dorico,
Guitar Pro 8 — can open. This is the inverse of
:mod:`fretwise.parser.musicxml_adapter` and the first step of the format
interoperability roadmap (see CLAUDE.md).

The score carries, per note:

* pitch and rhythm (via music21, which guarantees valid notation: note
  types, dots, beaming, measures, divisions, rests for gaps),
* the chosen tablature position as ``<technical>`` ``<string>``/``<fret>``,
* the optimized left-hand finger as ``<technical>`` ``<fingering>``.

music21 mangles *chord-level* technical articulations (it stacks every
member onto the first note and silently drops duplicate fingerings). So we
let music21 handle only pitch and rhythm, then :func:`_inject_technicals`
writes each note's ``<technical>`` block straight from our own data, matched
back to the emitted notes by MIDI pitch within each onset group.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fretwise.config import config
from fretwise.models import Finger, FingeringResult

_MUSICXML_CFG = config().export.musicxml

# Classical/guitar left-hand finger → MusicXML <fingering> number.
# Open strings carry no fingering element.
_FINGER_NUMBER: dict[Finger, int | None] = {
    Finger.OPEN: None,
    Finger.INDEX: 1,
    Finger.MIDDLE: 2,
    Finger.RING: 3,
    Finger.PINKY: 4,
}

# Semitone offset of each diatonic step within an octave (C=0 … B=11).
_STEP_SEMITONE: dict[str, int] = {
    "C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11,
}

# Guitar notates an octave above its sounding pitch: a written-pitch staff with
# a plain treble clef plus a <transpose octave-change=-1> (the convention
# MuseScore uses for the GP7/8 lead-guitar staff). We therefore *write* every
# note one octave above the sounding (internal) pitch and declare the staff
# transposition so a reader still sounds the original pitch. This makes the
# exported score DISPLAY at the same octave MuseScore renders for the same GP.
_WRITTEN_OCTAVE_SHIFT: int = _MUSICXML_CFG.written_octave_shift


@dataclass(frozen=True)
class _PartSpec:
    """Per-instrument notation policy for one MusicXML ``<part>``.

    Attributes:
        clef: music21 clef factory name (``TrebleClef`` / ``BassClef`` /
            ``PercussionClef``) used as the part's clef.
        octave_shift: Semitones added to every written pitch. ``12`` for
            octave-transposing staves (guitar/bass, written one octave above
            sounding); ``0`` for concert-pitch staves (drums/vocal).
        transpose_down_octave: When ``True`` the part declares a
            ``<transpose octave-change=-1>`` so the staff sounds an octave
            below the written pitch (pairs with ``octave_shift == 12``).
        fingered: When ``True`` each note carries a ``<technical>``
            string/fret/fingering block (guitar). When ``False`` the part is
            staff-only (no tablature technicals): vocals, bass, drums, other.
    """

    clef: str
    octave_shift: int
    transpose_down_octave: bool
    fingered: bool


# Guitar: the historical (single-part) behaviour — a plain treble clef on an
# octave-transposing staff, written one octave above sounding, with full
# tablature technicals. This MUST stay identical so single-track export is
# byte-for-byte unchanged.
_SPEC_GUITAR = _PartSpec(
    clef="TrebleClef", octave_shift=_WRITTEN_OCTAVE_SHIFT,
    transpose_down_octave=True, fingered=True,
)
# Bass: like guitar (notated an octave above sounding on an F clef) but
# staff-only — no per-note tablature technicals in the multi-part export.
_SPEC_BASS = _PartSpec(
    clef="BassClef", octave_shift=_WRITTEN_OCTAVE_SHIFT,
    transpose_down_octave=True, fingered=False,
)
# Drums: percussion clef, concert pitch, staff-only.
_SPEC_DRUMS = _PartSpec(
    clef="PercussionClef", octave_shift=0,
    transpose_down_octave=False, fingered=False,
)
# Vocal / other: plain treble clef, concert pitch, staff-only.
_SPEC_VOCAL = _PartSpec(
    clef="TrebleClef", octave_shift=0,
    transpose_down_octave=False, fingered=False,
)

# Track-kind string (see fretwise.parser.gpif_adapter) → notation spec.
_SPEC_BY_KIND: dict[str, _PartSpec] = {
    "guitar": _SPEC_GUITAR,
    "bass": _SPEC_BASS,
    "drums": _SPEC_DRUMS,
    "vocal": _SPEC_VOCAL,
    "other": _SPEC_VOCAL,
}


def _spec_for_kind(kind: str) -> _PartSpec:
    """Return the notation spec for a track kind (default: guitar)."""
    return _SPEC_BY_KIND.get(kind, _SPEC_GUITAR)


def _safe_import_music21() -> Any:
    """Import music21, raising ImportError with install hint if missing.

    Returns ``Any``: music21 ships no type stubs, so its module surface is
    untyped — annotating it as ``object`` would force a type-ignore on every
    attribute access throughout this file.
    """
    try:
        import music21

        return music21
    except ImportError as exc:  # pragma: no cover - depends on optional dep
        raise ImportError(
            "music21 is required for MusicXML export. "
            "Install it with: pip install music21"
        ) from exc


def _group_by_onset(
    results: list[FingeringResult],
) -> list[list[FingeringResult]]:
    """Group results sharing an onset into chords, ordered by time then pitch.

    Args:
        results: Ordered FingeringResult list.

    Returns:
        List of groups; each group is sorted by ascending pitch so its order
        matches music21's chord-note output order (used by redistribution).
    """
    groups: dict[float, list[FingeringResult]] = {}
    for r in results:
        groups.setdefault(round(r.note_event.onset, 6), []).append(r)
    ordered: list[list[FingeringResult]] = []
    for onset in sorted(groups):
        members = sorted(groups[onset], key=lambda r: r.note_event.pitch)
        ordered.append(members)
    return ordered


def _make_element(
    group: list[FingeringResult],
    duration: float,
    m21: Any,
    octave_shift: int = _WRITTEN_OCTAVE_SHIFT,
) -> Any:
    """Create a music21 Note (single) or Chord (multi) for one onset group.

    Written pitch = sounding + ``octave_shift``; on an octave-transposing staff
    (``octave_shift == 12``) the part's ``<transpose octave-change=-1>``
    restores the sounding pitch for playback. Each harmonic note also
    contributes its resultant (overtone) as an extra chord member rendered with
    a ``diamond`` notehead and no fingering — matching MuseScore's two-notehead
    harmonic dyad (the fretted note plus the sounding overtone).
    """
    if duration <= 0:
        duration = _MUSICXML_CFG.min_note_quarter_length  # guard against zero-length notes
    fundamentals = [r.note_event.pitch + octave_shift for r in group]
    fundamental_set = set(fundamentals)
    # Harmonic resultants (overtones) become diamond noteheads, skipping any that
    # would collide with a fundamental already in the chord.
    resultant_set = {
        r.note_event.harmonic_resultant_pitch + octave_shift
        for r in group
        if r.note_event.harmonic_resultant_pitch is not None
    } - fundamental_set
    all_pitches = fundamentals + sorted(resultant_set)

    if len(all_pitches) == 1:
        el = m21.note.Note(all_pitches[0], quarterLength=duration)
    else:
        el = m21.chord.Chord(all_pitches, quarterLength=duration)
        if resultant_set:
            for note in el.notes:
                if note.pitch.midi in resultant_set:
                    note.notehead = "diamond"
    # Stash the source results so we can recover them after quantization, which
    # rewrites offsets/durations but preserves the element objects.
    el.editorial.fwResults = group
    return el


def _build_part(
    results: list[FingeringResult],
    m21: Any,
    *,
    instrument: str,
    beats_per_measure: float,
    spec: _PartSpec,
) -> tuple[Any, list[list[FingeringResult]]]:
    """Build one quantized music21 ``Part`` and its matching onset groups.

    Raw onsets/durations (e.g. from MIDI) are rarely notatable, so the part is
    quantized to a 16th/triplet grid. Quantization can collapse near-coincident
    onsets, so the returned groups are re-derived from the *quantized* offsets —
    guaranteeing they line up 1:1 with the notes music21 will emit.

    Args:
        results: Ordered FingeringResult list for this one track.
        m21: The imported ``music21`` module.
        instrument: Part/instrument name (becomes ``<part-name>``).
        beats_per_measure: Beats per measure (time signature ``N/4``).
        spec: Per-kind notation policy (clef, octave shift, transpose).

    Returns:
        ``(part, groups)`` where ``groups`` is onset-ordered and each group is
        pitch-ascending (matching music21's chord-note output order).
    """
    stream = m21.stream
    shift = spec.octave_shift

    scratch = stream.Part()
    for group in _group_by_onset(results):
        onset = float(group[0].note_event.onset)
        duration = max(float(r.note_event.duration) for r in group)
        scratch.insert(onset, _make_element(group, duration, m21, shift))
    # Snap offsets and durations to a notatable grid: 16ths (4), eighth-note
    # triplets (3) and 16th-note triplets / sextuplets (6). The 6 is essential:
    # 16th-triplet notes have quarterLength 1/6, and without a matching divisor
    # music21 snaps their *offsets* onto the 1/3 grid but their *durations* onto
    # the 1/4 grid (0.1667 -> 0.25). That grid mismatch makes adjacent notes
    # collide, which makeNotation then resolves by spilling them into a phantom
    # extra voice (with <backup> elements) — the exact artifact that produced a
    # 0-indexed second voice MuseScore could not render. Quantizing offsets and
    # durations on the same {4,3,6} grid keeps every note coherent.
    scratch.quantize(
        quarterLengthDivisors=tuple(_MUSICXML_CFG.quantize_divisors),
        processOffsets=True,
        processDurations=True,
        inPlace=True,
    )

    # Re-group by quantized offset; merge any elements that snapped together.
    by_offset: dict[float, list[FingeringResult]] = {}
    durations: dict[float, float] = {}
    for el in scratch.recurse().notes:
        off = round(float(el.offset), 6)
        by_offset.setdefault(off, []).extend(el.editorial.fwResults)
        durations[off] = max(durations.get(off, 0.0), float(el.quarterLength))

    part = stream.Part()
    if instrument:
        part.partName = instrument
    # The clef comes from the part's spec. For guitar this is MuseScore's GP
    # lead-guitar convention: a PLAIN treble clef on a transposing staff — the
    # notes are written one octave above sounding (see _make_element) and the
    # staff carries <transpose octave-change=-1> (injected post-serialization,
    # since music21 does not emit a bare octave <transpose>), so the score
    # DISPLAYS at MuseScore's octave while sounding the original pitch. Bass uses
    # an F clef (same octave convention), drums a percussion clef, vocal/other a
    # plain treble clef at concert pitch.
    part.insert(0.0, getattr(m21.clef, spec.clef)())
    part.insert(0.0, m21.meter.TimeSignature(f"{int(beats_per_measure)}/4"))
    tempo_bpm = results[0].note_event.tempo if results else _MUSICXML_CFG.default_tempo_bpm
    part.insert(0.0, m21.tempo.MetronomeMark(number=round(tempo_bpm)))

    groups: list[list[FingeringResult]] = []
    for off in sorted(by_offset):
        group = sorted(by_offset[off], key=lambda r: r.note_event.pitch)
        part.insert(off, _make_element(group, durations[off], m21, shift))
        groups.append(group)

    return part, groups


def _prepare(
    results: list[FingeringResult],
    *,
    title: str,
    artist: str,
    instrument: str,
    beats_per_measure: float,
) -> tuple[Any, list[list[FingeringResult]]]:
    """Build a single-part quantized Score and its matching onset groups.

    Returns:
        ``(score, groups)`` where ``groups`` is onset-ordered and each group is
        pitch-ascending (matching music21's chord-note output order).
    """
    m21 = _safe_import_music21()
    part, groups = _build_part(
        results, m21,
        instrument=instrument,
        beats_per_measure=beats_per_measure,
        spec=_SPEC_GUITAR,
    )

    score = m21.stream.Score()
    md = m21.metadata.Metadata()
    if title:
        md.title = title
    if artist:
        md.composer = artist
    score.insert(0, md)
    score.insert(0, part)
    return score, groups


def build_score(
    results: list[FingeringResult],
    *,
    title: str = "",
    artist: str = "",
    instrument: str = "",
    beats_per_measure: float = 4.0,
) -> Any:
    """Build a quantized music21 Score from fingering results.

    Args:
        results: Ordered FingeringResult list from the optimizer.
        title: Work title (movement/title metadata).
        artist: Composer/artist metadata.
        instrument: Part/instrument name (e.g. "Classical Guitar").
        beats_per_measure: Beats per measure; drives the time signature
            (``N/4``). Onsets/durations are interpreted as quarter lengths and
            quantized to a 16th/triplet grid so the result is always notatable.

    Returns:
        A populated music21 ``stream.Score``.
    """
    score, _ = _prepare(
        results,
        title=title,
        artist=artist,
        instrument=instrument,
        beats_per_measure=beats_per_measure,
    )
    return score


def _note_midi(note_el: ET.Element) -> int | None:
    """Return the MIDI pitch of a MusicXML ``<note>``, or None for a rest."""
    pitch = note_el.find("pitch")
    if pitch is None:
        return None  # rest
    step = pitch.findtext("step", "")
    if step not in _STEP_SEMITONE:
        return None
    octave = int(pitch.findtext("octave", "4"))
    alter = int(float(pitch.findtext("alter", "0")))
    return (octave + 1) * 12 + _STEP_SEMITONE[step] + alter


def _set_technical(note_el: ET.Element, state: object) -> None:
    """Replace ``note_el``'s ``<technical>`` with string/fret/finger from state."""
    notations = note_el.find("notations")
    if notations is None:
        notations = ET.SubElement(note_el, "notations")
    for existing in notations.findall("technical"):
        notations.remove(existing)
    tech = ET.SubElement(notations, "technical")
    ET.SubElement(tech, "string").text = str(state.string_num)  # type: ignore[attr-defined]
    ET.SubElement(tech, "fret").text = str(state.fret)  # type: ignore[attr-defined]
    finger_num = _FINGER_NUMBER.get(state.finger)  # type: ignore[attr-defined]
    if finger_num is not None:
        ET.SubElement(tech, "fingering").text = str(finger_num)


def _inject_technicals(
    xml: str, groups: list[list[FingeringResult]]
) -> str:
    """Write each note's tablature/fingering into the emitted MusicXML.

    music21 already laid out the correct pitches, rhythm, measures and rests.
    This walks the emitted ``<note>`` elements in melodic order — skipping
    rests — and matches them, onset group by onset group, back to the source
    results by MIDI pitch, then injects an authoritative ``<technical>`` block
    (string/fret/fingering). Doing it from our own data avoids music21's lossy
    chord-articulation handling entirely.

    Tie continuations (a long note split across a barline) reuse the previous
    group's mapping without consuming a new one, so they keep the same
    string/fret as the note they continue.

    Args:
        xml: MusicXML produced by music21 (pitch + rhythm only).
        groups: Onset groups from :func:`_group_by_onset` (source of truth).

    Returns:
        MusicXML with per-note ``<technical>`` blocks. Returned unchanged if
        the document cannot be parsed (export stays best-effort).
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:  # pragma: no cover - defensive
        return xml

    # Single-part document: scope the injection to the one <part> with the
    # historical guitar spec (octave-transposing staff, full technicals).
    part_el = root.find("part")
    if part_el is not None:
        _inject_part_transpose(part_el)
        _inject_part_technicals(
            part_el, groups, octave_shift=_WRITTEN_OCTAVE_SHIFT, fingered=True,
        )
    return ET.tostring(root, encoding="unicode")


def _inject_part_technicals(
    part_el: ET.Element,
    groups: list[list[FingeringResult]],
    *,
    octave_shift: int,
    fingered: bool,
) -> None:
    """Write one ``<part>``'s tablature/fingering from the source groups.

    music21 already laid out the correct pitches, rhythm, measures and rests.
    This walks the part's emitted ``<note>`` elements in melodic order —
    skipping rests — and matches them, onset group by onset group, back to the
    source results by (written) MIDI pitch, then injects an authoritative
    ``<technical>`` block (string/fret/fingering). Doing it from our own data
    avoids music21's lossy chord-articulation handling entirely.

    Tie continuations (a long note split across a barline) reuse the previous
    group's mapping without consuming a new one, so they keep the same
    string/fret as the note they continue.

    When ``fingered`` is False (staff-only parts: vocals/bass/drums/other) the
    function is a no-op — those parts carry no tablature technicals.
    """
    if not fingered:
        return
    # Flatten emitted notes into chord runs (head + following <chord/> notes).
    runs: list[list[ET.Element]] = []
    is_continuation: list[bool] = []
    for measure in part_el.iter("measure"):
        notes = list(measure.findall("note"))
        i = 0
        while i < len(notes):
            run = [notes[i]]
            j = i + 1
            while j < len(notes) and notes[j].find("chord") is not None:
                run.append(notes[j])
                j += 1
            if _note_midi(notes[i]) is not None:  # skip rest-only runs
                runs.append(run)
                is_continuation.append(_is_tie_stop(notes[i]))
            i = j

    gi = 0
    prev_group: list[FingeringResult] | None = None
    for run, cont in zip(runs, is_continuation):
        if cont and prev_group is not None:
            group = prev_group  # tied continuation: reuse, don't advance
        elif gi < len(groups):
            group = groups[gi]
            gi += 1
            prev_group = group
        else:
            break  # more emitted notes than source groups — stop, best-effort
        # Emitted notes carry the WRITTEN pitch (sounding + shift), so key the
        # match table on the same written pitch.
        by_pitch = {
            r.note_event.pitch + octave_shift: r for r in group
        }
        for note_el in run:
            midi = _note_midi(note_el)
            match = by_pitch.get(midi) if midi is not None else None
            if match is not None:
                _set_technical(note_el, match.state)


def _inject_part_transpose(part_el: ET.Element) -> None:
    """Declare one ``<part>``'s staff as transposing down one octave.

    The notes are written one octave above sounding pitch (see
    :func:`_make_element`), so the part needs a
    ``<transpose><octave-change>-1</octave-change></transpose>`` in its first
    ``<attributes>`` to restore the original sounding pitch for playback — the
    convention MuseScore uses for the GP lead-guitar staff. The element is
    inserted right after ``<clef>`` to keep the MusicXML element order valid.
    """
    for measure in part_el.iter("measure"):
        attributes = measure.find("attributes")
        if attributes is None:
            continue
        if attributes.find("transpose") is not None:
            return  # already present
        transpose = ET.Element("transpose")
        ET.SubElement(transpose, "diatonic").text = "0"
        ET.SubElement(transpose, "chromatic").text = "0"
        ET.SubElement(transpose, "octave-change").text = "-1"
        # MusicXML attribute order: ... clef, staff-details, transpose, ...
        children = list(attributes)
        insert_at = len(children)
        for idx, child in enumerate(children):
            if child.tag in {"clef", "staff-details"}:
                insert_at = idx + 1
        attributes.insert(insert_at, transpose)
        break  # only the first measure carries the staff transposition


def _is_tie_stop(note_el: ET.Element) -> bool:
    """True when a note only ends a tie (a continuation, not a fresh attack)."""
    ties = note_el.findall("tie")
    types = {t.get("type") for t in ties}
    return "stop" in types and "start" not in types


def render_musicxml(
    results: list[FingeringResult],
    *,
    title: str = "",
    artist: str = "",
    instrument: str = "",
    beats_per_measure: float = 4.0,
) -> str:
    """Render fingering results as a MusicXML document string.

    Args:
        results: Ordered FingeringResult list from the optimizer.
        title: Work title metadata.
        artist: Composer/artist metadata.
        instrument: Part/instrument name.
        beats_per_measure: Beats per measure (time signature ``N/4``).

    Returns:
        A complete MusicXML (partwise) document as text.
    """
    if not results:
        # Minimal valid empty score so downstream tools don't choke.
        m21 = _safe_import_music21()
        empty = m21.stream.Score()
        empty.insert(0, m21.stream.Part())
        exporter = m21.musicxml.m21ToXml.GeneralObjectExporter(empty)
        return str(exporter.parse().decode("utf-8"))

    score, groups = _prepare(
        results,
        title=title,
        artist=artist,
        instrument=instrument,
        beats_per_measure=beats_per_measure,
    )
    m21 = _safe_import_music21()
    notated = _make_notation_one_based(score, m21)
    exporter = m21.musicxml.m21ToXml.GeneralObjectExporter(notated)
    xml = exporter.parse().decode("utf-8")
    return _inject_technicals(xml, groups)


def render_musicxml_multi(
    parts: list[dict[str, Any]],
    *,
    title: str = "",
    artist: str = "",
) -> str:
    """Render several tracks into one multi-part MusicXML score.

    Emits a single ``score-partwise`` document with one ``<score-part>`` (in
    the ``<part-list>``) and one ``<part>`` per input track, applying the
    per-kind clef / octave transposition and — for guitar parts — the
    string/fret/fingering technicals and harmonic-dyad logic used by the
    single-track :func:`render_musicxml`.

    Args:
        parts: Ordered list of part descriptors. Each is a mapping with:

            * ``name`` (str): instrument / part name (``<part-name>``);
            * ``kind`` (str): track kind — ``guitar`` | ``bass`` | ``drums`` |
              ``vocal`` | ``other`` (selects clef/transpose/technicals);
            * ``results`` (list[FingeringResult]): the notes. Guitar parts carry
              real fingering states; staff-only kinds carry un-fingered results
              (string/fret/finger ignored);
            * ``beats_per_measure`` (float, optional): time signature ``N/4``
              (default ``4.0``).

        title: Work title metadata.
        artist: Composer/artist metadata.

    Returns:
        A complete multi-part MusicXML (partwise) document as text. Parts with
        no notes are skipped. If no part has notes, a minimal empty score is
        returned.
    """
    m21 = _safe_import_music21()

    built: list[tuple[Any, list[list[FingeringResult]], _PartSpec]] = []
    for part in parts:
        results = list(part.get("results") or [])
        if not results:
            continue  # nothing to notate for this track
        spec = _spec_for_kind(str(part.get("kind", "guitar")))
        part_el, groups = _build_part(
            results, m21,
            instrument=str(part.get("name", "") or ""),
            beats_per_measure=float(
                part.get("beats_per_measure", _MUSICXML_CFG.default_beats_per_measure)
                or _MUSICXML_CFG.default_beats_per_measure
            ),
            spec=spec,
        )
        built.append((part_el, groups, spec))

    if not built:
        # Minimal valid empty score so downstream tools don't choke.
        empty = m21.stream.Score()
        empty.insert(0, m21.stream.Part())
        exporter = m21.musicxml.m21ToXml.GeneralObjectExporter(empty)
        return str(exporter.parse().decode("utf-8"))

    score = m21.stream.Score()
    md = m21.metadata.Metadata()
    if title:
        md.title = title
    if artist:
        md.composer = artist
    score.insert(0, md)
    for part_el, _groups, _spec in built:
        score.insert(0, part_el)

    notated = _make_notation_one_based(score, m21)
    exporter = m21.musicxml.m21ToXml.GeneralObjectExporter(notated)
    xml = exporter.parse().decode("utf-8")

    root = ET.fromstring(xml)
    # <part> elements are emitted in score order, 1:1 with ``built``.
    part_elems = list(root.findall("part"))
    for (part_el_src, groups, spec), part_el in zip(built, part_elems):
        if spec.transpose_down_octave:
            _inject_part_transpose(part_el)
        _inject_part_technicals(
            part_el, groups,
            octave_shift=spec.octave_shift, fingered=spec.fingered,
        )
    return ET.tostring(root, encoding="unicode")


def _make_notation_one_based(score: Any, m21: Any) -> Any:
    """Run music21 notation explicitly and force MusicXML-valid 1-based voices.

    ``GeneralObjectExporter`` runs ``makeNotation`` implicitly, but the voices
    that ``Stream.makeVoices`` creates carry a *0-based* ``id`` (``0, 1, …``).
    music21 emits that id verbatim as ``<voice>0</voice>``, which is illegal in
    MusicXML (voice tokens are positive integers): MuseScore silently drops
    every note in voice ``0``, so the whole part renders as empty rest-only
    measures. Running ``makeNotation`` here first (instead of letting the
    exporter do it) also re-quantizes any degenerate tuplets into notatable
    ones, then we renumber each measure's voices to ``1, 2, …``.

    Args:
        score: The prepared (pitch + rhythm) music21 ``Score``.
        m21: The imported ``music21`` module.

    Returns:
        A notated ``Score`` whose voices are all numbered from 1.
    """
    notated = score.makeNotation(inPlace=False)
    for part in notated.parts:
        for measure in part.getElementsByClass(m21.stream.Measure):
            for idx, voice in enumerate(measure.voices, start=1):
                voice.id = idx
    return notated


def write_musicxml(
    results: list[FingeringResult],
    output_path: Path,
    *,
    title: str = "",
    artist: str = "",
    instrument: str = "",
    beats_per_measure: float = 4.0,
) -> None:
    """Write fingering results to a ``.musicxml`` file.

    Args:
        results: Ordered FingeringResult list from the optimizer.
        output_path: Destination path (``.musicxml`` or ``.xml``).
        title: Work title metadata.
        artist: Composer/artist metadata.
        instrument: Part/instrument name.
        beats_per_measure: Beats per measure (time signature ``N/4``).
    """
    xml = render_musicxml(
        results,
        title=title,
        artist=artist,
        instrument=instrument,
        beats_per_measure=beats_per_measure,
    )
    Path(output_path).write_text(xml, encoding="utf-8")


__all__ = [
    "build_score",
    "render_musicxml",
    "render_musicxml_multi",
    "write_musicxml",
]
