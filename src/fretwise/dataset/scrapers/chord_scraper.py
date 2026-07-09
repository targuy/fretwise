"""Scraper for online chord libraries — collects chord voicings with fingerings."""
import logging
import time
from pathlib import Path

from fretwise.dataset._mldeps import optional_attr, optional_import

requests = optional_import("requests")
BeautifulSoup = optional_attr("bs4", "BeautifulSoup")

from fretwise.dataset.config import CHORDS_RAW_DIR, REQUEST_DELAY, USER_AGENT  # noqa: E402
from fretwise.dataset.data_schema.schema import (  # noqa: E402
    Finger,
    FingeredChord,
    save_chords,
)

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": USER_AGENT}

# --- all-guitar-chords.com scraper ---

ALL_GUITAR_CHORDS_BASE = "https://www.all-guitar-chords.com"

CHORD_ROOTS = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
CHORD_TYPES = [
    "maj", "min", "7", "maj7", "min7", "dim", "aug", "sus2", "sus4",
    "6", "min6", "9", "min9", "maj9", "add9", "7sus4", "dim7",
    "min7b5", "aug7", "7b9", "7#9", "13",
]


def _parse_finger(val: str | int | None) -> Finger | None:
    if val is None or val == "x" or val == "X":
        return None
    val = int(val)
    if val == 0:
        return Finger.NONE
    mapping = {1: Finger.INDEX, 2: Finger.MIDDLE, 3: Finger.RING, 4: Finger.PINKY, 5: Finger.THUMB}
    return mapping.get(val, Finger.NONE)


def scrape_chorddb_api(output_dir: Path = None) -> list[FingeredChord]:
    """
    Scrape chord voicings from a public chord API.
    Uses the JGuitar chord API which returns JSON with finger positions.
    """
    output_dir = output_dir or CHORDS_RAW_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    all_chords = []

    for root in CHORD_ROOTS:
        for chord_type in CHORD_TYPES:
            chord_name = f"{root}{chord_type}"
            try:
                voicings = _fetch_chord_voicings(root, chord_type)
                for v in voicings:
                    chord = FingeredChord(
                        name=chord_name,
                        strings=v["strings"],
                        fingers=v["fingers"],
                        position=v.get("position", 0),
                        is_barre=v.get("barre", False),
                        source="jguitar",
                    )
                    all_chords.append(chord)
            except Exception as e:
                logger.warning("Failed to fetch %s: %s", chord_name, e)

            time.sleep(REQUEST_DELAY)

        logger.info("Completed root %s — %d chords total so far", root, len(all_chords))

    save_chords(all_chords, str(output_dir / "chords_jguitar.json"))
    logger.info("Saved %d chord voicings", len(all_chords))
    return all_chords


def _fetch_chord_voicings(root: str, chord_type: str) -> list[dict]:
    """Fetch chord voicings from JGuitar's chord calculator API."""
    url = "http://jguitar.com/apiresult"
    params = {"root": root, "quality": chord_type, "instrument": "guitar"}

    resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
    if resp.status_code != 200:
        return []

    return _parse_jguitar_response(resp.text)


def _parse_jguitar_response(html: str) -> list[dict]:
    """Parse JGuitar HTML response to extract chord voicings."""
    soup = BeautifulSoup(html, "lxml")
    voicings = []

    for diagram in soup.find_all("div", class_="chord-diagram"):
        strings = []
        fingers = []

        for string_el in diagram.find_all("span", class_="string"):
            fret_text = string_el.get("data-fret", "x")
            finger_text = string_el.get("data-finger", None)

            if fret_text.lower() == "x":
                strings.append(None)
                fingers.append(None)
            else:
                strings.append(int(fret_text))
                fingers.append(_parse_finger(finger_text))

        if strings:
            while len(strings) < 6:
                strings.append(None)
                fingers.append(None)
            voicings.append({
                "strings": strings[:6],
                "fingers": fingers[:6],
                "position": min((f for f in strings if f and f > 0), default=0),
            })

    return voicings


# --- Standard chord dictionary (built-in, no scraping needed) ---

# Chromatic note names used for transposition (sharps only for simplicity).
_CHROMATIC = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Semitone index of each open string in standard tuning (low E to high E):
# E=4, A=9, D=2, G=7, B=11, E=4
_OPEN_STRING_PITCHES = [4, 9, 2, 7, 11, 4]


def _validate_chord(name: str, strings: list, fingers: list) -> bool:
    """Validate that a chord entry is internally consistent.

    Checks:
    - Length must be 6 for both strings and fingers
    - Muted/fretted consistency between strings and fingers
    - Fretted strings (fret > 0) must have a non-NONE finger
    - No finger assigned to different frets (same finger, different frets is unplayable)
    """
    if len(strings) != 6 or len(fingers) != 6:
        return False
    for s_val, f_val in zip(strings, fingers):
        if s_val is None and f_val is not None:
            return False
        if s_val is not None and f_val is None:
            return False
        if s_val is not None and s_val > 0 and f_val == Finger.NONE:
            return False
    # Check: no finger on different frets (physically impossible)
    finger_frets: dict[Finger, set[int]] = {}
    for s_val, f_val in zip(strings, fingers):
        if s_val is not None and s_val > 0 and f_val is not None and f_val != Finger.NONE:
            finger_frets.setdefault(f_val, set()).add(s_val)
    for finger, frets in finger_frets.items():
        if len(frets) > 1:
            logger.debug("Finger %s on multiple frets %s in chord %s", finger.name, frets, name)
            return False
    return True


def _root_name_from_string_and_offset(string_idx: int, offset: int) -> str:
    """Compute the root note name given a string index (0-5) and fret offset."""
    return _CHROMATIC[(_OPEN_STRING_PITCHES[string_idx] + offset) % 12]


def generate_standard_chords() -> list[FingeredChord]:
    """
    Generate a comprehensive dictionary of guitar chord voicings with standard
    fingerings. Returns 500+ unique voicings covering:

    - Open chords (major, minor, 7th, maj7, m7, sus, add9, etc.)
    - CAGED barre shapes (E, Em, A, Am, C, D forms) transposed chromatically
    - Dominant 7th, major 7th, minor 7th in movable shapes
    - Extended chords: 9, m9, add9, sus2, sus4, 7sus4
    - Power chords (5th chords) on 6th and 5th strings
    - Diminished triads, diminished 7th, augmented triads
    """
    I, M, R, P = Finger.INDEX, Finger.MIDDLE, Finger.RING, Finger.PINKY  # noqa: E741
    O = Finger.NONE  # open string  # noqa: E741
    X = None         # muted string

    chords: list[FingeredChord] = []
    seen: set[tuple] = set()  # (name, tuple(strings)) for dedup

    def _add(name: str, strings: list, fingers: list,
             position: int = 0, is_barre: bool = False, source: str = "standard_dictionary"):
        key = (name, tuple(strings))
        if key in seen:
            return
        if not _validate_chord(name, strings, fingers):
            logger.debug("Skipping invalid chord %s: strings=%s fingers=%s", name, strings, fingers)
            return
        seen.add(key)
        chords.append(FingeredChord(
            name=name, strings=list(strings), fingers=list(fingers),
            position=position, is_barre=is_barre, source=source,
        ))

    # =====================================================================
    # 1. OPEN CHORDS — hand-verified standard fingerings
    # =====================================================================

    # Major open chords
    _add("C",    [X, 3, 2, 0, 1, 0], [X, R, M, O, I, O])
    _add("D",    [X, X, 0, 2, 3, 2], [X, X, O, I, R, M])
    _add("E",    [0, 2, 2, 1, 0, 0], [O, M, R, I, O, O])
    _add("G",    [3, 2, 0, 0, 0, 3], [M, I, O, O, O, R])
    _add("A",    [X, 0, 2, 2, 2, 0], [X, O, I, M, R, O])

    # Minor open chords
    _add("Dm",   [X, X, 0, 2, 3, 1], [X, X, O, M, R, I])
    _add("Em",   [0, 2, 2, 0, 0, 0], [O, M, R, O, O, O])
    _add("Am",   [X, 0, 2, 2, 1, 0], [X, O, M, R, I, O])

    # Dominant 7th open chords
    _add("A7",   [X, 0, 2, 0, 2, 0], [X, O, M, O, R, O])
    _add("B7",   [X, 2, 1, 2, 0, 2], [X, M, I, R, O, P])
    _add("C7",   [X, 3, 2, 3, 1, 0], [X, R, M, P, I, O])
    _add("D7",   [X, X, 0, 2, 1, 2], [X, X, O, M, I, R])
    _add("E7",   [0, 2, 0, 1, 0, 0], [O, M, O, I, O, O])
    _add("G7",   [3, 2, 0, 0, 0, 1], [R, M, O, O, O, I])

    # Major 7th open chords
    _add("Cmaj7", [X, 3, 2, 0, 0, 0], [X, R, M, O, O, O])
    _add("Dmaj7", [X, X, 0, 2, 2, 2], [X, X, O, I, M, R])
    _add("Emaj7", [0, 2, 1, 1, 0, 0], [O, R, M, I, O, O])
    _add("Fmaj7", [X, X, 3, 2, 1, 0], [X, X, R, M, I, O])
    _add("Gmaj7", [3, 2, 0, 0, 0, 2], [R, M, O, O, O, I])
    _add("Amaj7", [X, 0, 2, 1, 2, 0], [X, O, R, I, M, O])

    # Minor 7th open chords
    _add("Am7",  [X, 0, 2, 0, 1, 0], [X, O, M, O, I, O])
    _add("Bm7",  [X, 2, 0, 2, 0, 2], [X, I, O, R, O, P])
    _add("Dm7",  [X, X, 0, 2, 1, 1], [X, X, O, R, I, I], is_barre=True)
    _add("Em7",  [0, 2, 0, 0, 0, 0], [O, M, O, O, O, O])
    _add("Em7",  [0, 2, 2, 0, 3, 0], [O, I, M, O, R, O], source="standard_dictionary")

    # Sus2 open chords
    _add("Asus2", [X, 0, 2, 2, 0, 0], [X, O, M, R, O, O])
    _add("Dsus2", [X, X, 0, 2, 3, 0], [X, X, O, I, R, O])
    _add("Esus2", [0, 2, 4, 4, 0, 0], [O, I, R, P, O, O])

    # Sus4 open chords
    _add("Asus4", [X, 0, 2, 2, 3, 0], [X, O, I, M, R, O])
    _add("Dsus4", [X, X, 0, 2, 3, 3], [X, X, O, I, R, P])
    _add("Esus4", [0, 2, 2, 2, 0, 0], [O, I, M, R, O, O])

    # Add9 open chords (must contain root, 3rd, 5th, and 9th)
    _add("Cadd9", [X, 3, 2, 0, 3, 0], [X, M, I, O, R, O])    # C-G-E-C-D-E
    _add("Eadd9", [0, 2, 2, 1, 0, 2], [O, M, R, I, O, P])    # E-B-E-G#-E-F#
    _add("Gadd9", [3, 0, 0, 0, 0, 3], [M, O, O, O, O, R])    # G-A-D-G-B-G  (root, 9th, 5th, 3rd)
    _add("Aadd9", [X, 0, 2, 4, 2, 0], [X, O, I, R, M, O])    # A-E-A-B-C#-E
    _add("Dadd9", [X, X, 4, 2, 3, 0], [X, X, P, I, M, O],
         source="standard_dictionary")                        # F#-A-E-E (3rd, 5th, root octave, 9th)

    # Open diminished
    _add("Bdim7", [X, 2, 0, 1, 0, 1], [X, M, O, I, O, R])  # B-D-Ab-B-F (fully diminished 7th)
    _add("Edim",  [0, 1, 2, 0, X, X], [O, I, M, O, X, X])

    # Open augmented
    _add("Caug",  [X, 3, 2, 1, 1, 0], [X, R, M, I, I, O], is_barre=True)
    _add("Eaug",  [0, 3, 2, 1, 1, 0], [O, P, R, M, I, O])

    # 7sus4 open
    _add("A7sus4",[X, 0, 2, 0, 3, 0], [X, O, I, O, R, O])
    _add("D7sus4",[X, X, 0, 2, 1, 3], [X, X, O, M, I, R])
    _add("E7sus4",[0, 2, 0, 2, 0, 0], [O, I, O, R, O, O])
    _add("G7sus4",[3, 3, 0, 0, 1, 1], [R, P, O, O, I, I], is_barre=True)

    # Minor 6 open
    _add("Am6",   [X, 0, 2, 2, 1, 2], [X, O, M, R, I, P])

    # 6th chords open
    _add("A6",    [X, 0, 2, 2, 2, 2], [X, O, I, I, I, I], is_barre=True)
    _add("C6",    [X, 3, 2, 2, 1, 0], [X, P, R, M, I, O])
    _add("D6",    [X, X, 0, 2, 0, 2], [X, X, O, I, O, R])
    _add("E6",    [0, 2, 2, 1, 2, 0], [O, M, R, I, P, O])
    _add("G6",    [3, 2, 0, 0, 0, 0], [M, I, O, O, O, O])

    # 9th open voicings
    _add("A9",    [X, 0, 2, 4, 2, 3], [X, O, I, R, I, M], is_barre=True)
    _add("E9",    [0, 2, 0, 1, 0, 2], [O, M, O, I, O, R])
    _add("G9",    [3, 0, 0, 0, 0, 1], [R, O, O, O, O, I])

    # =====================================================================
    # 2. MOVABLE BARRE SHAPES — template + transposition
    # =====================================================================
    # Each template: (suffix, relative_frets, fingers, root_string, max_offset)
    # relative_frets are offsets from the barre fret (position).
    # root_string: 0=6th string (E), 1=5th string (A), 2=4th string (D)

    # --- 6th-string-root shapes (E-form family) ---
    e_root_templates = [
        # Major (E shape)
        ("",       [0, 2, 2, 1, 0, 0], [I, R, P, M, I, I]),
        # Minor (Em shape)
        ("m",      [0, 2, 2, 0, 0, 0], [I, R, P, I, I, I]),
        # Dominant 7 (E7 shape)
        ("7",      [0, 2, 0, 1, 0, 0], [I, R, I, M, I, I]),
        # Major 7 (Emaj7 shape)
        ("maj7",   [0, 2, 1, 1, 0, 0], [I, P, M, R, I, I]),
        # Minor 7 (Em7 shape)
        ("m7",     [0, 2, 0, 0, 0, 0], [I, R, I, I, I, I]),
        # Sus2
        ("sus2",   [0, 2, 4, 4, 0, 0], [I, M, R, P, I, I]),
        # Sus4
        ("sus4",   [0, 2, 2, 2, 0, 0], [I, R, R, R, I, I]),
        # 7sus4
        ("7sus4",  [0, 2, 0, 2, 0, 0], [I, R, I, P, I, I]),
        # Augmented
        ("aug",    [0, 3, 2, 1, 1, 0], [I, P, R, M, M, I]),
        # Power chord (5th) — 3-note version
        ("5",      [0, 2, 2, X, X, X], [I, R, P, X, X, X]),
        # Minor 9 (partial voicing)
        ("m9",     [0, 2, 0, 0, 0, 3], [I, P, I, I, I, R]),
    ]

    # --- 5th-string-root shapes (A-form family) ---
    a_root_templates = [
        # Major (A shape)
        ("",       [X, 0, 2, 2, 2, 0], [X, I, R, R, R, I]),
        # Minor (Am shape)
        ("m",      [X, 0, 2, 2, 1, 0], [X, I, R, P, M, I]),
        # Dominant 7 (A7 shape)
        ("7",      [X, 0, 2, 0, 2, 0], [X, I, R, I, P, I]),
        # Major 7 (Amaj7 shape)
        ("maj7",   [X, 0, 2, 1, 2, 0], [X, I, R, M, P, I]),
        # Minor 7 (Am7 shape)
        ("m7",     [X, 0, 2, 0, 1, 0], [X, I, R, I, M, I]),
        # Sus2
        ("sus2",   [X, 0, 2, 2, 0, 0], [X, I, R, P, I, I]),
        # Sus4
        ("sus4",   [X, 0, 2, 2, 3, 0], [X, I, M, R, P, I]),
        # 7sus4
        ("7sus4",  [X, 0, 2, 0, 3, 0], [X, I, M, I, P, I]),
        # Augmented (mute high E — INDEX can't barre A + high E at different frets)
        ("aug",    [X, 0, 3, 2, 2, X], [X, I, P, R, M, X]),
        # Diminished triad
        ("dim",    [X, 0, 1, 2, 1, X], [X, I, M, P, R, X]),
        # Power chord (5th) — 3-note
        ("5",      [X, 0, 2, 2, X, X], [X, I, R, P, X, X]),
        # Add9 — root, 3rd, 5th, 9th; root on A string, 9th on high E
        ("add9",   [X, 0, 2, 4, 2, 0], [X, I, M, P, R, I]),
        # 9 (dominant 9)
        ("9",      [X, 0, 2, 1, 0, 0], [X, I, R, M, I, I]),
    ]

    # --- 4th-string-root shapes (D-form family) ---
    d_root_templates = [
        # Major (D shape, partial barre)
        ("",       [X, X, 0, 2, 3, 2], [X, X, I, M, P, R]),
        # Minor (Dm shape)
        ("m",      [X, X, 0, 2, 3, 1], [X, X, I, R, P, M]),
        # Dominant 7 (D7 shape)
        ("7",      [X, X, 0, 2, 1, 2], [X, X, I, R, M, P]),
        # Major 7 (Dmaj7 shape)
        ("maj7",   [X, X, 0, 2, 2, 2], [X, X, I, M, R, P]),
        # Minor 7
        ("m7",     [X, X, 0, 2, 1, 1], [X, X, I, R, M, M]),
        # Sus2
        ("sus2",   [X, X, 0, 2, 3, 0], [X, X, I, M, R, I]),
        # Sus4
        ("sus4",   [X, X, 0, 2, 3, 3], [X, X, I, M, R, P]),
    ]

    # --- 6th-string-root diminished shapes ---
    e_dim_templates = [
        # Diminished triad
        ("dim",    [0, 1, 2, 0, X, X], [I, M, R, I, X, X]),
    ]

    # ---- Transpose all E-root (6th string root) templates ----
    for suffix, rel_frets, template_fingers, *_ in e_root_templates:
        for offset in range(1, 13):
            if offset > 12:
                continue
            root = _root_name_from_string_and_offset(0, offset)
            chord_name = f"{root}{suffix}"
            strings = []
            fingers = []
            max_fret = 0
            valid = True
            for i in range(6):
                rf = rel_frets[i]
                tf = template_fingers[i]
                if rf is None:
                    strings.append(None)
                    fingers.append(None)
                else:
                    fret = rf + offset
                    if fret > 24:
                        valid = False
                        break
                    strings.append(fret)
                    fingers.append(tf)
                    if fret > max_fret:
                        max_fret = fret
            if not valid:
                continue
            # Skip if fret span is too large (unplayable)
            fretted = [s for s in strings if s is not None and s > 0]
            if fretted and (max(fretted) - min(fretted)) > 5:
                continue
            _add(chord_name, strings, fingers, position=offset, is_barre=True,
                 source="barre_E_shape")

    # ---- Transpose all A-root (5th string root) templates ----
    for suffix, rel_frets, template_fingers, *_ in a_root_templates:
        for offset in range(1, 13):
            if offset > 12:
                continue
            root = _root_name_from_string_and_offset(1, offset)
            chord_name = f"{root}{suffix}"
            strings = []
            fingers = []
            max_fret = 0
            valid = True
            for i in range(6):
                rf = rel_frets[i]
                tf = template_fingers[i]
                if rf is None:
                    strings.append(None)
                    fingers.append(None)
                else:
                    fret = rf + offset
                    if fret > 24:
                        valid = False
                        break
                    strings.append(fret)
                    fingers.append(tf)
                    if fret > max_fret:
                        max_fret = fret
            if not valid:
                continue
            fretted = [s for s in strings if s is not None and s > 0]
            if fretted and (max(fretted) - min(fretted)) > 5:
                continue
            _add(chord_name, strings, fingers, position=offset, is_barre=True,
                 source="barre_A_shape")

    # ---- Transpose D-root (4th string root) templates (up to fret 10) ----
    for suffix, rel_frets, template_fingers, *_ in d_root_templates:
        for offset in range(1, 11):
            root = _root_name_from_string_and_offset(2, offset)
            chord_name = f"{root}{suffix}"
            strings = []
            fingers = []
            valid = True
            for i in range(6):
                rf = rel_frets[i]
                tf = template_fingers[i]
                if rf is None:
                    strings.append(None)
                    fingers.append(None)
                else:
                    fret = rf + offset
                    if fret > 22:
                        valid = False
                        break
                    strings.append(fret)
                    fingers.append(tf)
            if not valid:
                continue
            fretted = [s for s in strings if s is not None and s > 0]
            if fretted and (max(fretted) - min(fretted)) > 5:
                continue
            _add(chord_name, strings, fingers, position=offset, is_barre=True,
                 source="barre_D_shape")

    # ---- Transpose E-root diminished templates ----
    for suffix, rel_frets, template_fingers, *_ in e_dim_templates:
        for offset in range(1, 13):
            root = _root_name_from_string_and_offset(0, offset)
            chord_name = f"{root}{suffix}"
            strings = []
            fingers = []
            valid = True
            for i in range(6):
                rf = rel_frets[i]
                tf = template_fingers[i]
                if rf is None:
                    strings.append(None)
                    fingers.append(None)
                else:
                    fret = rf + offset
                    if fret > 18:
                        valid = False
                        break
                    strings.append(fret)
                    fingers.append(tf)
            if not valid:
                continue
            _add(chord_name, strings, fingers, position=offset, is_barre=True,
                 source="barre_E_shape")

    # =====================================================================
    # 3. C-SHAPE BARRE CHORDS — practical positions only (frets 1-5)
    # =====================================================================
    # The C shape barre is physically demanding; we include it at lower frets.
    c_shape_templates = [
        # C-shape major
        ("",     [X, 3, 2, 0, 1, 0], [X, P, R, I, M, I]),
        # C-shape minor (Cm-ish voicing)
        ("m",    [X, 3, 1, 0, 1, X], [X, P, R, I, M, X]),
        # C-shape dom7 (4-note voicing, mute high E)
        ("7",    [X, 3, 2, 3, 1, X], [X, R, M, P, I, X]),
    ]

    for suffix, rel_frets, template_fingers, *_ in c_shape_templates:
        for offset in range(1, 5):
            root = _root_name_from_string_and_offset(1, offset + 3)
            # C-shape: the root on the A string is at relative fret 3
            chord_name = f"{root}{suffix}"
            strings = []
            fingers = []
            valid = True
            for i in range(6):
                rf = rel_frets[i]
                tf = template_fingers[i]
                if rf is None:
                    strings.append(None)
                    fingers.append(None)
                else:
                    fret = rf + offset
                    if fret > 18:
                        valid = False
                        break
                    strings.append(fret)
                    fingers.append(tf)
            if not valid:
                continue
            fretted = [s for s in strings if s is not None and s > 0]
            if fretted and (max(fretted) - min(fretted)) > 5:
                continue
            _add(chord_name, strings, fingers, position=offset, is_barre=True,
                 source="barre_C_shape")

    # =====================================================================
    # 4. POWER CHORDS — 6th and 5th string root, 2-note and 3-note
    # =====================================================================

    # 6th string power chords (2-note: root + 5th)
    for offset in range(1, 13):
        root = _root_name_from_string_and_offset(0, offset)
        # 2-note power chord
        _add(f"{root}5",
             [offset, offset + 2, X, X, X, X],
             [I, R, X, X, X, X],
             position=offset, is_barre=False, source="power_chord")
        # 3-note power chord (root + 5th + octave)
        _add(f"{root}5",
             [offset, offset + 2, offset + 2, X, X, X],
             [I, R, P, X, X, X],
             position=offset, is_barre=False, source="power_chord")

    # 5th string power chords
    for offset in range(1, 13):
        root = _root_name_from_string_and_offset(1, offset)
        _add(f"{root}5",
             [X, offset, offset + 2, X, X, X],
             [X, I, R, X, X, X],
             position=offset, is_barre=False, source="power_chord")
        _add(f"{root}5",
             [X, offset, offset + 2, offset + 2, X, X],
             [X, I, R, P, X, X],
             position=offset, is_barre=False, source="power_chord")

    # =====================================================================
    # 5. DIMINISHED 7TH CHORDS — symmetric, 3 unique shapes cover all 12
    # =====================================================================
    # Dim7 is symmetric every 3 semitones. We define 3 base voicings and
    # transpose each by 0-2 semitones to cover all roots.

    # 5th-string root dim7 voicing (mute high E — PINKY can't span G + high E
    # across a fretted B string in between)
    dim7_a_template = [X, 0, 1, 2, 1, X]
    dim7_a_fingers  = [X, I, M, P, R, X]

    for offset in range(1, 13):
        root = _root_name_from_string_and_offset(1, offset)
        strings = [X if v is None else v + offset for v in dim7_a_template]
        fretted = [s for s in strings if s is not None and s > 0]
        if fretted and max(fretted) > 18:
            continue
        _add(f"{root}dim7", strings, dim7_a_fingers,
             position=offset, is_barre=False, source="dim7_shape")

    # 6th-string root dim7 voicing
    dim7_e_template = [0, X, 1, 2, 1, X]
    dim7_e_fingers  = [I, X, M, P, R, X]

    for offset in range(1, 13):
        root = _root_name_from_string_and_offset(0, offset)
        strings = [X if v is None else v + offset for v in dim7_e_template]
        fretted = [s for s in strings if s is not None and s > 0]
        if fretted and max(fretted) > 18:
            continue
        _add(f"{root}dim7", strings, dim7_e_fingers,
             position=offset, is_barre=False, source="dim7_shape")

    # 4th-string root dim7
    dim7_d_template = [X, X, 0, 1, 0, 1]
    dim7_d_fingers  = [X, X, I, R, M, P]

    for offset in range(1, 13):
        root = _root_name_from_string_and_offset(2, offset)
        strings = [X if v is None else v + offset for v in dim7_d_template]
        fretted = [s for s in strings if s is not None and s > 0]
        if fretted and max(fretted) > 18:
            continue
        _add(f"{root}dim7", strings, dim7_d_fingers,
             position=offset, is_barre=False, source="dim7_shape")

    # =====================================================================
    # 6. AUGMENTED TRIADS — symmetric every 4 semitones
    # =====================================================================

    # 6th-string root aug
    aug_e_template = [0, 3, 2, 1, 1, 0]
    aug_e_fingers  = [I, P, R, M, I, I]

    for offset in range(1, 13):
        root = _root_name_from_string_and_offset(0, offset)
        strings = [v + offset for v in aug_e_template]
        if max(strings) > 18:
            continue
        _add(f"{root}aug", strings, aug_e_fingers,
             position=offset, is_barre=True, source="aug_shape")

    # 5th-string root aug
    aug_a_template = [X, 0, 3, 2, 2, 1]
    aug_a_fingers  = [X, I, P, R, M, I]

    for offset in range(1, 13):
        root = _root_name_from_string_and_offset(1, offset)
        strings = [X if v is None else v + offset for v in aug_a_template]
        fretted = [s for s in strings if s is not None and s > 0]
        if fretted and max(fretted) > 18:
            continue
        _add(f"{root}aug", strings, aug_a_fingers,
             position=offset, is_barre=True, source="aug_shape")

    # =====================================================================
    # 7. ADDITIONAL OPEN/LOW POSITION VOICINGS
    # =====================================================================
    # Voicings that don't fit neatly into the transposition templates.

    # F (already an E-shape barre at 1, but include the standard open F)
    _add("F",    [1, 3, 3, 2, 1, 1], [I, R, P, M, I, I], position=1,
         is_barre=True, source="standard_dictionary")
    _add("Fm",   [1, 3, 3, 1, 1, 1], [I, R, P, I, I, I], position=1,
         is_barre=True, source="standard_dictionary")

    # Common Bm open-position partial barre
    _add("Bm",   [X, 2, 4, 4, 3, 2], [X, I, R, P, M, I], position=2,
         is_barre=True, source="standard_dictionary")

    # F#m / Gb m
    _add("F#m",  [2, 4, 4, 2, 2, 2], [I, R, P, I, I, I], position=2,
         is_barre=True, source="standard_dictionary")

    # C#m
    _add("C#m",  [X, 4, 6, 6, 5, 4], [X, I, R, P, M, I], position=4,
         is_barre=True, source="standard_dictionary")

    # Additional 9th voicings (dom9 = root, 3rd, 5th, b7, 9th)
    _add("C9",   [X, 3, 2, 3, 3, 0], [X, M, I, R, P, O], source="standard_dictionary")
    _add("D9",   [X, X, 4, 5, 5, 5], [X, X, I, R, M, P], position=4,
         source="standard_dictionary")                        # F#-C-E-A (rootless D9 voicing)
    _add("G9",   [3, 2, 0, 2, 0, 1], [R, M, O, P, O, I],
         source="standard_dictionary")                        # G-B-D-A-D-F (root, 3rd, 5th, 9th, 5th, b7)

    # m9 voicings (minor9 = root, b3, 5th, b7, 9th)
    _add("Amadd9",[X, 0, 2, 4, 1, 0], [X, O, I, P, M, O], source="standard_dictionary")
                                                              # A-E-B-C-E (root, 5th, 9th, b3 — no b7)
    _add("Em9",  [0, 2, 0, 0, 0, 2], [O, M, O, O, O, I], source="standard_dictionary")
    _add("Dm9",  [X, X, 3, 5, 5, 5], [X, X, I, R, M, P], position=3,
         source="standard_dictionary")                        # F-C-E-A (rootless Dm9 voicing)

    # half-diminished (m7b5)
    _add("Bm7b5", [X, 2, 0, 2, 0, 1], [X, M, O, R, O, I], source="standard_dictionary")
    _add("Am7b5", [X, 0, 1, 2, 1, X], [X, O, I, R, M, X], source="standard_dictionary")

    # =====================================================================
    # 8. JAZZ VOICINGS — common partial voicings
    # =====================================================================

    # Movable maj7 shell voicings (6th string root, 3-4 strings)
    maj7_shell_6 = [0, X, 1, 1, X, X]
    maj7_shell_6f = [I, X, R, M, X, X]

    for offset in range(1, 13):
        root = _root_name_from_string_and_offset(0, offset)
        strings = [v + offset for v in maj7_shell_6 if v is not None]
        all_strings = []
        for v in maj7_shell_6:
            if v is None:
                all_strings.append(None)
            else:
                all_strings.append(v + offset)
        fretted = [s for s in all_strings if s is not None and s > 0]
        if fretted and max(fretted) > 15:
            continue
        _add(f"{root}maj7", all_strings, maj7_shell_6f,
             position=offset, is_barre=False, source="jazz_shell")

    # Movable m7 shell voicings (5th string root)
    m7_shell_5 = [X, 0, X, 0, 1, X]
    m7_shell_5f = [X, I, X, R, M, X]

    for offset in range(1, 13):
        root = _root_name_from_string_and_offset(1, offset)
        all_strings = [X if v is None else v + offset for v in m7_shell_5]
        fretted = [s for s in all_strings if s is not None and s > 0]
        if fretted and max(fretted) > 15:
            continue
        _add(f"{root}m7", all_strings, m7_shell_5f,
             position=offset, is_barre=False, source="jazz_shell")

    # Movable dom7 shell voicings (6th string root)
    dom7_shell_6 = [0, X, 1, 0, X, X]
    dom7_shell_6f = [I, X, R, M, X, X]

    for offset in range(1, 13):
        root = _root_name_from_string_and_offset(0, offset)
        all_strings = [X if v is None else v + offset for v in dom7_shell_6]
        fretted = [s for s in all_strings if s is not None and s > 0]
        if fretted and max(fretted) > 15:
            continue
        _add(f"{root}7", all_strings, dom7_shell_6f,
             position=offset, is_barre=False, source="jazz_shell")

    # Movable dom7 shell voicings (5th string root)
    dom7_shell_5 = [X, 0, X, 0, 2, X]
    dom7_shell_5f = [X, I, X, M, R, X]

    for offset in range(1, 13):
        root = _root_name_from_string_and_offset(1, offset)
        all_strings = [X if v is None else v + offset for v in dom7_shell_5]
        fretted = [s for s in all_strings if s is not None and s > 0]
        if fretted and max(fretted) > 15:
            continue
        _add(f"{root}7", all_strings, dom7_shell_5f,
             position=offset, is_barre=False, source="jazz_shell")

    # =====================================================================
    # 9. OPEN POSITION CHORDS for remaining roots via open-ish voicings
    # =====================================================================
    # Some common voicings using open strings in keys like F#, Bb, etc.

    _add("Bb",   [X, 1, 3, 3, 3, 1], [X, I, R, R, R, I], position=1,
         is_barre=True, source="standard_dictionary")
    _add("Bbm",  [X, 1, 3, 3, 2, 1], [X, I, R, P, M, I], position=1,
         is_barre=True, source="standard_dictionary")
    _add("Bb7",  [X, 1, 3, 1, 3, 1], [X, I, R, I, P, I], position=1,
         is_barre=True, source="standard_dictionary")
    _add("Bbmaj7",[X,1, 3, 2, 3, 1], [X, I, R, M, P, I], position=1,
         is_barre=True, source="standard_dictionary")
    _add("Bbm7", [X, 1, 3, 1, 2, 1], [X, I, R, I, M, I], position=1,
         is_barre=True, source="standard_dictionary")

    _add("Eb",   [X, X, 1, 3, 4, 3], [X, X, I, M, P, R], position=1,
         is_barre=False, source="standard_dictionary")
    _add("Ebm",  [X, X, 1, 3, 4, 2], [X, X, I, R, P, M], position=1,
         is_barre=False, source="standard_dictionary")
    _add("Ab",   [4, 6, 6, 5, 4, 4], [I, R, P, M, I, I], position=4,
         is_barre=True, source="standard_dictionary")

    logger.info("Generated %d unique chord voicings", len(chords))
    return chords
