"""Physical constraint validation for guitar fingerings."""
from fretwise.dataset.config import MAX_FRET_SPAN
from fretwise.dataset.data_schema.schema import Finger, FingeredChord, FingeredNote, NoteSequence


def validate_chord(chord: FingeredChord) -> list[str]:
    """Validate physical plausibility of a chord fingering. Returns list of issues."""
    issues = []
    fretted = [(i, f, finger) for i, (f, finger) in enumerate(zip(chord.strings, chord.fingers))
               if f is not None and f > 0 and finger is not None and finger != Finger.NONE]

    if not fretted:
        return issues

    frets = [f for _, f, _ in fretted]
    span = max(frets) - min(frets)
    if span > MAX_FRET_SPAN:
        issues.append(f"fret_span_too_large: {span} (max {MAX_FRET_SPAN})")

    finger_usage = {}
    for string_idx, fret, finger in fretted:
        if finger not in finger_usage:
            finger_usage[finger] = []
        finger_usage[finger].append((string_idx, fret))

    for finger, positions in finger_usage.items():
        if finger == Finger.INDEX and chord.is_barre:
            continue
        frets_used = set(f for _, f in positions)
        if len(frets_used) > 1:
            issues.append(f"finger_{finger.name}_on_multiple_frets: {frets_used}")

    return issues


def validate_transition(prev: FingeredNote, curr: FingeredNote) -> list[str]:
    """Validate a note-to-note transition. Returns list of issues."""
    issues = []
    if prev.finger == curr.finger and prev.finger != Finger.NONE:
        if prev.fret != curr.fret or prev.string != curr.string:
            issues.append(f"same_finger_different_position: finger={prev.finger.name}")

    if prev.fret > 0 and curr.fret > 0:
        if abs(prev.fret - curr.fret) > MAX_FRET_SPAN:
            issues.append(f"large_position_jump: {abs(prev.fret - curr.fret)} frets")

    return issues


def validate_sequence(seq: NoteSequence) -> dict:
    """Validate an entire sequence and return statistics."""
    playable = [n for n in seq.notes if not n.is_rest and n.finger != Finger.NONE]
    total_transitions = max(len(playable) - 1, 0)
    issues = []

    for i in range(1, len(playable)):
        t_issues = validate_transition(playable[i - 1], playable[i])
        if t_issues:
            issues.append({"position": i, "issues": t_issues})

    return {
        "total_notes": len(seq.notes),
        "fingered_notes": len(playable),
        "total_transitions": total_transitions,
        "invalid_transitions": len(issues),
        "issues": issues,
        "valid_rate": 1 - len(issues) / total_transitions if total_transitions else 1.0,
    }
