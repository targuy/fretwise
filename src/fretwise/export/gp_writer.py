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

# Model class index → GPIF fingering value. GPIF uses the same convention
# as the v3 ONNX model (0 = open/thumb, 1 = index, 2 = middle, 3 = ring,
# 4 = pinky). FretWise's Finger enum values are lower-case strings; map
# them here so the writer is self-contained.
_FINGER_TO_GPIF_INT: dict[str, int] = {
    "open": 0,
    "index": 1,
    "middle": 2,
    "ring": 3,
    "pinky": 4,
}


def fingerings_by_source_id(
    results: list[FingeringResult],
) -> dict[str, int]:
    """Extract ``{source_note_id → gpif_finger_int}`` from solver results.

    Skips notes whose source_note_id is missing (non-GPIF parsers) and
    open-string fingerings on string > 0 when the finger is "open"
    (those don't need a LeftFingering annotation in real notation).
    """
    out: dict[str, int] = {}
    for r in results:
        nid = r.note_event.source_note_id
        if not nid:
            continue
        finger_value = r.state.finger.value
        gpif_int = _FINGER_TO_GPIF_INT.get(finger_value)
        if gpif_int is None:
            continue
        # Open-string notes (fret=0) don't carry a left-hand finger.
        if r.state.fret == 0 and gpif_int == 0:
            continue
        out[nid] = gpif_int
    return out


def write_gp_with_fingerings(
    source_path: Path,
    fingerings: Mapping[str, int],
) -> bytes:
    """Return the bytes of a new GP archive with LeftFingering injected.

    Args:
        source_path: Existing GP 7/8 file to use as template.
        fingerings: Mapping ``{source_note_id (str) → gpif_finger_int}``
            obtained from :func:`fingerings_by_source_id`.

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


# Regex for the existing LeftFingering Property block — strip it before
# re-injecting so re-runs are idempotent (re-saving a previously fingered
# file does not stack annotations).
_EXISTING_LEFT_FINGERING_RE = re.compile(
    r"\s*<Property name=\"LeftFingering\">.*?</Property>",
    flags=re.DOTALL,
)


def _inject_left_fingering(xml: str, fingerings: Mapping[str, int]) -> str:
    """Insert a LeftFingering Property on each matching Note in the XML.

    Removes any pre-existing LeftFingering blocks (idempotent re-saves),
    then appends a fresh one inside each Note's ``<Properties>`` container
    when ``source_note_id`` appears in the ``fingerings`` map.

    Format used::

        <Property name="LeftFingering">
          <Fingering>1</Fingering>
        </Property>

    where the integer is 0=thumb 1=index 2=middle 3=ring 4=pinky.
    """
    if not fingerings:
        return xml

    # Strip stale LeftFingering blocks (re-save idempotency).
    xml = _EXISTING_LEFT_FINGERING_RE.sub("", xml)

    def _patch_note(match: re.Match[str]) -> str:
        note_block = match.group(0)
        note_id = match.group(1)
        finger_int = fingerings.get(note_id)
        if finger_int is None:
            return note_block
        # Append inside the Properties container. If the Note has no
        # <Properties>, create one (rare for guitar tracks, but safe).
        new_prop = (
            f'<Property name="LeftFingering">'
            f'<Fingering>{finger_int}</Fingering>'
            f'</Property>'
        )
        if "</Properties>" in note_block:
            return note_block.replace(
                "</Properties>", f"{new_prop}</Properties>", 1,
            )
        # No Properties container: insert one just before </Note>.
        return note_block.replace(
            "</Note>", f"<Properties>{new_prop}</Properties></Note>", 1,
        )

    note_re = re.compile(
        r'<Note id="(\d+)">.*?</Note>',
        flags=re.DOTALL,
    )
    return note_re.sub(_patch_note, xml)
