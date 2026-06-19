"""Write Guitar Pro 7/8 (.gp) files with LeftFingering annotations.

GP 7/8 files are ZIP archives. The score lives at ``Content/score.gpif`` as
XML. This module reads the original archive, injects a
``<Property name="LeftFingering">`` element into each Note that has a
fingering assignment, repacks the archive, and returns the bytes.

The matching strategy is the GPIF ``Note id="X"`` attribute, propagated
through ``NoteEvent.source_note_id`` by ``GpifAdapter``. This is exact and
voice-safe; falling back to (string, fret, onset) tuples would mis-handle
cross-voice unisons.

Output is **always a new file's bytes** — callers decide where to save it.
The original GP file is never modified in place.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Mapping

from fretwise.models import FingeringResult

GPIF_CONTENT_NAME = "Content/score.gpif"

# Guitar Pro 7/8 stores LeftFingering as a *letter* using the Spanish
# classical-guitar convention (P pulgar / I índice / M medio / A anular /
# C chiquito), as a direct child of <Note> — NOT inside <Properties>.
# Verified by saving a fingered note inside Guitar Pro and inspecting the
# resulting score.gpif.
_FINGER_TO_GPIF_LETTER: dict[str, str] = {
    "open": "P",     # thumb (rare on guitar; GP keeps "P" for it)
    "index": "I",
    "middle": "M",
    "ring": "A",
    "pinky": "C",
}


def fingerings_by_source_id(
    results: list[FingeringResult],
) -> dict[str, str]:
    """Extract ``{source_note_id → gpif_finger_letter}`` from solver results.

    Skips notes whose source_note_id is missing (non-GPIF parsers) and
    open-string fingerings (those don't need a LeftFingering annotation
    in real notation).
    """
    out: dict[str, str] = {}
    for r in results:
        nid = r.note_event.source_note_id
        if not nid:
            continue
        finger_value = r.state.finger.value
        # Open-string notes (fret=0) don't carry a left-hand finger,
        # regardless of which finger label the resolver attached.
        if r.state.fret == 0:
            continue
        letter = _FINGER_TO_GPIF_LETTER.get(finger_value)
        if letter is None:
            continue
        out[nid] = letter
    return out


def write_gp_with_fingerings(
    source_path: Path,
    fingerings: Mapping[str, str],
) -> bytes:
    """Return the bytes of a new GP archive with LeftFingering injected.

    Args:
        source_path: Existing GP 7/8 file to use as template.
        fingerings: Mapping ``{source_note_id (str) → gpif_finger_letter}``
            obtained from :func:`fingerings_by_source_id`. Letters use the
            Spanish classical convention (P/I/M/A/C) the way Guitar Pro
            writes them.

    Returns:
        Bytes of the rewritten zip archive. Caller is responsible for
        writing to disk (or returning via an HTTP response).

    Raises:
        FileNotFoundError: If source_path doesn't exist.
        ValueError: If the file is not a GP 7/8 (GPIF) archive.
    """
    src = Path(source_path)
    if not src.exists():
        raise FileNotFoundError(f"GP file not found: {source_path}")
    if not zipfile.is_zipfile(src):
        raise ValueError(
            f"Not a GP 7/8 archive: {source_path} "
            "(this writer only supports the GPIF zip format)"
        )

    with zipfile.ZipFile(src, "r") as zin:
        if GPIF_CONTENT_NAME not in zin.namelist():
            raise ValueError(
                f"Missing {GPIF_CONTENT_NAME} inside {source_path} — "
                "not a Guitar Pro 7/8 score archive."
            )
        original_xml = zin.read(GPIF_CONTENT_NAME).decode("utf-8")
        patched_xml = _inject_left_fingering(original_xml, fingerings)

        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == GPIF_CONTENT_NAME:
                    zout.writestr(item, patched_xml.encode("utf-8"))
                else:
                    zout.writestr(item, zin.read(item.filename))
    return out.getvalue()


# Regex for the existing LeftFingering element — strip it before re-
# injecting so re-runs are idempotent (re-saving a previously fingered
# file does not stack annotations). Matches the direct-child <Note>
# placement Guitar Pro actually writes.
_EXISTING_LEFT_FINGERING_RE = re.compile(
    r"\s*<LeftFingering>[^<]*</LeftFingering>",
)


def _inject_left_fingering(xml: str, fingerings: Mapping[str, str]) -> str:
    """Insert a ``<LeftFingering>X</LeftFingering>`` on each matching Note.

    Removes any pre-existing LeftFingering elements first (idempotent
    re-saves), then inserts a fresh one as a direct child of ``<Note>``
    immediately after the opening tag — the exact placement Guitar Pro
    uses when saving a manually-annotated finger.

    Format (verified by inspecting a GP-saved score)::

        <Note id="35">
          <LeftFingering>I</LeftFingering>
          <InstrumentArticulation>0</InstrumentArticulation>
          <Properties>…</Properties>
        </Note>

    Letters follow the Spanish classical convention: P/I/M/A/C
    (thumb / index / middle / ring / pinky).
    """
    if not fingerings:
        return xml

    # Strip stale LeftFingering elements (re-save idempotency).
    xml = _EXISTING_LEFT_FINGERING_RE.sub("", xml)

    def _patch_note(match: re.Match[str]) -> str:
        note_block = match.group(0)
        note_id = match.group(1)
        letter = fingerings.get(note_id)
        if letter is None:
            return note_block
        injection = f"<LeftFingering>{letter}</LeftFingering>"
        # Insert as the first child of <Note>, between the opening tag
        # and the first existing child — matches Guitar Pro's own layout.
        open_tag = f'<Note id="{note_id}">'
        return note_block.replace(
            open_tag, f"{open_tag}{injection}", 1,
        )

    note_re = re.compile(
        r'<Note id="(\d+)">.*?</Note>',
        flags=re.DOTALL,
    )
    return note_re.sub(_patch_note, xml)
