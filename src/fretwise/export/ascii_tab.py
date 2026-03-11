"""ASCII tablature renderer.

Converts a list of FingeringResult into a human-readable text representation:

    Measure 1  (4/4, 73 BPM)
    e |------5/p----0/---------------------0/--|
    B |---------3/m----3/m-------3/m-------0/--|
    G |---2/m----------------2/m-------2/m-----|
    D |0/--------------------0/----------------|
    A |---------------------------0/-----------|
    E |----------------------------------------|

Each beat column shows fret/finger inline on the string line:
  - Fretted note: fret/finger  e.g. "3/i", "5/m", "12/r"
  - Open string:  fret/-       e.g. "0/-"
  - No note:      dashes       e.g. "----"
"""

from __future__ import annotations

import math

from fretwise.models import Finger, FingeringResult
from fretwise.patterns.chord_recognition import recognize_chord

# Guitar string names (index 0 = string 1 = high e)
_STRING_NAMES = ["e", "B", "G", "D", "A", "E"]
_NUM_STRINGS = 6
_FINGER_CHAR = {
    Finger.OPEN: "-",
    Finger.INDEX: "i",
    Finger.MIDDLE: "m",
    Finger.RING: "r",
    Finger.PINKY: "p",
}
# Beats per ASCII tab measure (grouping column).
_MEASURE_BEATS = 4.0
# Minimum column width for a note slot (chars, including the trailing dash separator).
_MIN_COL = 4


def render_ascii_tab(
    results: list[FingeringResult],
    beats_per_measure: float = _MEASURE_BEATS,
    max_measures: int | None = None,
    title: str = "",
) -> str:
    """Render fingering results as ASCII tablature.

    Each note appears as ``fret/finger`` inline on its string line:
    ``3/i`` (index finger, fret 3), ``0/-`` (open string), ``----`` (rest).

    Args:
        results: Ordered FingeringResult list from ViterbiOptimizer.
        beats_per_measure: Duration of one measure in beats (default 4.0).
        max_measures: If set, only render the first N measures.
        title: Optional title shown at the top.

    Returns:
        Multi-line ASCII tablature string.
    """
    if not results:
        return "(no notes)\n"

    lines: list[str] = []
    if title:
        lines.append(title)
        lines.append("=" * min(len(title), 80))
    lines.append("Legend: i=index  m=middle  r=ring  p=pinky  -=open string")

    measures = _group_by_measure(results, beats_per_measure)
    # Compute the song-level measure number for the first displayed measure.
    first_song_measure = (
        int(results[0].note_event.onset / beats_per_measure) + 1 if results else 1
    )
    if max_measures is not None:
        measures = measures[:max_measures]

    for m_idx, measure_results in enumerate(measures):
        tempo = measure_results[0].note_event.tempo if measure_results else 120.0
        song_measure_num = first_song_measure + m_idx
        lines.append(
            f"\nMeasure {song_measure_num}  "
            f"({beats_per_measure:.0f}/4, {tempo:.0f} BPM)"
        )
        lines.extend(_render_measure(measure_results))

    return "\n".join(lines) + "\n"


def _group_by_measure(
    results: list[FingeringResult], beats_per_measure: float
) -> list[list[FingeringResult]]:
    """Group results into measures based on onset, offset by first note's measure.

    The returned list is relative: index 0 = first measure that contains notes,
    regardless of how many empty measures precede it in the song.
    """
    if not results:
        return []
    first_measure = int(results[0].note_event.onset / beats_per_measure)
    last_measure = int(results[-1].note_event.onset / beats_per_measure)
    count = last_measure - first_measure + 1
    measures: list[list[FingeringResult]] = [[] for _ in range(count)]
    for r in results:
        m = int(r.note_event.onset / beats_per_measure) - first_measure
        measures[m].append(r)
    return measures


def _render_measure(results: list[FingeringResult]) -> list[str]:
    """Render a single measure as ASCII tab lines with inline fret/finger
    and a chord name annotation row above the strings."""
    if not results:
        return []

    # Collect distinct onsets → one column per onset.
    onset_map: dict[float, dict[int, FingeringResult]] = {}
    for r in results:
        onset = round(r.note_event.onset, 6)
        if onset not in onset_map:
            onset_map[onset] = {}
        onset_map[onset][r.state.string_num] = r

    sorted_onsets = sorted(onset_map.keys())
    measure_start = sorted_onsets[0]

    # Build column content: each cell is "fret/finger" or "-" (no note).
    # Detect impossible chord spans at each onset: any fretted note whose fret
    # is more than 4 away from the cluster median gets marked "fret/!" instead
    # of a finger letter — it cannot be played simultaneously with the others.
    _MAX_CHORD_SPAN = 4
    columns: list[dict[int, str]] = []
    for onset in sorted_onsets:
        slot = onset_map[onset]
        # Check for impossible spans only WITHIN the same voice.
        # Cross-voice notes at the same onset legitimately span large fret ranges.
        impossible_strings: set[int] = set()
        voice_groups: dict[int, list[tuple[int, int]]] = {}
        for sn, r in slot.items():
            v = r.note_event.voice_hint if r.note_event.voice_hint is not None else 0
            voice_groups.setdefault(v, []).append((sn, r.state.fret))
        for voice_fretted in voice_groups.values():
            fretted = [(sn, f) for sn, f in voice_fretted if f > 0]
            if len(fretted) < 2:
                continue
            frets_only = [f for _, f in fretted]
            if max(frets_only) - min(frets_only) > _MAX_CHORD_SPAN:
                s_frets = sorted(frets_only)
                median_f = s_frets[len(s_frets) // 2]
                for sn, f in fretted:
                    if abs(f - median_f) > _MAX_CHORD_SPAN // 2:
                        impossible_strings.add(sn)
        col: dict[int, str] = {}
        for string_num in range(1, _NUM_STRINGS + 1):
            r = slot.get(string_num)
            if r is not None:
                if string_num in impossible_strings:
                    col[string_num] = f"{r.state.fret}/!"
                else:
                    finger_char = _FINGER_CHAR.get(r.state.finger, "?")
                    col[string_num] = f"{r.state.fret}/{finger_char}"
            else:
                col[string_num] = "-"
        columns.append(col)

    if not columns:
        return []

    # Column widths.
    col_widths = [
        max(max(len(col[s]) for s in range(1, _NUM_STRINGS + 1)), _MIN_COL - 1)
        for col in columns
    ]

    # --- Chord recognition ---
    # Group onsets by beat (1-beat window).
    beat_to_onsets: dict[int, list[float]] = {}
    for onset in sorted_onsets:
        beat = math.floor(onset - measure_start)
        beat_to_onsets.setdefault(beat, []).append(onset)

    # Collect pitch classes per beat and recognize chord.
    beat_chords: dict[int, str] = {}
    for beat, beat_onsets in sorted(beat_to_onsets.items()):
        pitches: list[int] = []
        for onset in beat_onsets:
            for r in onset_map[onset].values():
                pitches.append(r.note_event.pitch)
        chord = recognize_chord(pitches)
        if chord:
            beat_chords[beat] = chord

    # Compute character start position of each onset column.
    # Prefix "e |" = 3 chars; each column occupies col_widths[i]+1 chars.
    col_start_positions: list[int] = []
    pos = 3
    for w in col_widths:
        col_start_positions.append(pos)
        pos += w + 1
    total_width = pos + 1  # +1 for closing "|"

    # Build chord annotation line.
    chord_chars = [" "] * total_width
    prev_chord: str | None = None
    for col_idx, onset in enumerate(sorted_onsets):
        beat = math.floor(onset - measure_start)
        chord = beat_chords.get(beat)
        if not chord or chord == prev_chord:
            continue
        # Only place at the first onset of this beat.
        if beat_to_onsets[beat][0] != onset:
            continue
        start = col_start_positions[col_idx]
        for i, ch in enumerate(chord):
            if start + i < total_width:
                chord_chars[start + i] = ch
        prev_chord = chord

    chord_line = "".join(chord_chars)
    # Only include chord line if at least one chord was identified.
    lines: list[str] = []
    if any(c != " " for c in chord_chars):
        lines.append(chord_line)

    # Build one line per string (string 1 = high e first).
    for string_num in range(1, _NUM_STRINGS + 1):
        name = _STRING_NAMES[string_num - 1]
        parts = [f"{name} |"]
        for col, w in zip(columns, col_widths):
            cell = col[string_num]
            if cell == "-":
                parts.append("-" * (w + 1))
            else:
                parts.append(cell.ljust(w) + "-")
        parts.append("|")
        lines.append("".join(parts))

    return lines


def render_text_report(
    results: list[FingeringResult],
    title: str = "",
    max_notes: int | None = None,
) -> str:
    """Render a tabular text report: one line per note.

    Columns: note_id | onset | pitch | string | fret | finger | hand_pos | cost

    Args:
        results: FingeringResult list.
        title: Optional title line.
        max_notes: Limit to first N notes.
    Returns:
        Formatted text report.
    """
    rows = results[:max_notes] if max_notes else results
    lines: list[str] = []
    if title:
        lines.append(title)
        lines.append("=" * min(len(title), 80))
    lines.append(
        f"{'#':>5}  {'onset':>7}  {'pitch':>5}  {'str':>3}  "
        f"{'fret':>4}  {'finger':>6}  {'pos':>3}  {'cost':>8}  articulation"
    )
    lines.append("-" * 72)
    for r in rows:
        e = r.note_event
        s = r.state
        lines.append(
            f"{r.note_id:5d}  {e.onset:7.3f}  {e.pitch:5d}  {s.string_num:3d}  "
            f"{s.fret:4d}  {s.finger.value:>6}  {s.hand_position:3d}  "
            f"{r.cost:8.2f}  {e.articulation.value}"
        )
    lines.append("-" * 72)
    lines.append(
        f"Total notes: {len(rows)}  |  "
        f"Total cost: {sum(r.cost for r in rows):.2f}  |  "
        f"Tempo: {rows[0].note_event.tempo:.0f} BPM"
    ) if rows else None
    return "\n".join(str(line) for line in lines) + "\n"
