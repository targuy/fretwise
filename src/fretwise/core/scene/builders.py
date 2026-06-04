"""Scene builders from canonical semantic model."""

from __future__ import annotations

import bisect

from fretwise.config import config as _config

from fretwise.core.canonical import NoteEvent as CanonicalNoteEvent
from fretwise.core.canonical import Score
from fretwise.core.layout import PageLayout, canonical_to_page_layout
from fretwise.core.notation_mode import has_standard as _has_standard_mode
from fretwise.core.notation_mode import has_tab as _has_tab_mode
from fretwise.core.notation_utils import (
    diatonic_step_from_metadata as _diatonic_step_from_metadata,
    is_x_notehead_drum as _is_x_notehead_drum,
    percussion_note_y as _notation_percussion_note_y,
    standard_note_y as _notation_standard_note_y,
)
from .render_helpers import (
    base_duration as _base_duration,
    boolish as _boolish,
    dot_count as _dot_count,
    duration_class as _duration_class,
    duration_components as _duration_components,
    flag_count as _flag_count,
    is_filled_notehead as _is_filled_notehead,
    is_measure_rest_event as _is_measure_rest_event,
    notated_duration as _notated_duration,
    rest_kind as _rest_kind,
    safe_int as _safe_int,
    stem_direction as _stem_direction,
    stem_x_for_notehead as _stem_x_for_notehead,
)
from fretwise.core.scene.models import (
    DocumentScene,
    GlyphInstance,
    LayerGroup,
    PageScene,
    RecipeInstance,
    RenderScene,
    StaffScene,
    SystemScene,
    TextInstance,
)

# Tunable scene metrics are sourced from the centralized config
# (src/fretwise/config/defaults.yaml -> layout.scene). Values mirror the prior
# inline literals exactly; this is a refactor, not a tuning change. Derived
# constants (e.g. _TAB_Y, _STANDARD_STEM_TOP_Y) stay computed from these bases.
_SCENE_CFG = _config().layout.scene

_PAGE_W = _SCENE_CFG.page_width
_PAGE_H = _SCENE_CFG.page_height
_MARGIN_X = _SCENE_CFG.margin_x
_MARGIN_Y = _SCENE_CFG.margin_y
_STAFF_W = _SCENE_CFG.staff_width
_STAFF_H = _SCENE_CFG.staff_height
_TAB_Y = _MARGIN_Y + 60.0
_TAB_SPACING = _SCENE_CFG.tab_spacing
_STAFF_STD_Y = _MARGIN_Y - 8.0
_STAFF_STD_SPACING = _SCENE_CFG.standard_staff_spacing
_STAFF_TAB_CLEARANCE = _SCENE_CFG.standard_tab_clearance
_STANDARD_STEM_TOP_Y = _STAFF_STD_Y - 2 * _STAFF_STD_SPACING
_STANDARD_STEM_BOTTOM_Y = _STAFF_STD_Y + 6 * _STAFF_STD_SPACING
_STANDARD_REST_CENTER_Y = _STAFF_STD_Y + 2.0 * _STAFF_STD_SPACING
_STANDARD_REST_VOICE_OFFSET = 2.0 * _STAFF_STD_SPACING
_TAB_RHYTHM_BEAM_Y = _TAB_Y + 5.0 * _TAB_SPACING + 14.0
_TAB_RHYTHM_REST_CENTER_Y = _TAB_Y + 5.0 * _TAB_SPACING + 8.0
_REST_GAP_BREAK = _SCENE_CFG.rest_gap_break
_TAB_SPAN_PAD = _SCENE_CFG.tab_span_pad
_BEAM_GAP = _SCENE_CFG.beam_gap
_FLAG_STACK_SPACING = _SCENE_CFG.flag_stack_spacing
_TAB_RHYTHM_BEAM_THICKNESS = _SCENE_CFG.tab_rhythm_beam_thickness
_TAB_RHYTHM_BEAM_GAP = _SCENE_CFG.tab_rhythm_beam_gap
_TAB_RHYTHM_FLAG_SPACING = _SCENE_CFG.tab_rhythm_flag_spacing
_TAB_RHYTHM_STEM_WIDTH = _SCENE_CFG.tab_rhythm_stem_width
_SECONDARY_BEAM_HOOK_LEN = _SCENE_CFG.secondary_beam_hook_len
_MIN_STEM_LENGTH = _SCENE_CFG.min_stem_length
_MAX_BEAM_SLOPE = _SCENE_CFG.max_beam_slope
_MAX_BEAM_VERTICAL_DELTA = _SCENE_CFG.max_beam_vertical_delta
_STANDARD_STEM_LENGTH_SPACES = _SCENE_CFG.standard_stem_length_spaces
_STANDARD_BEAMED_STEM_MIN_SPACES = _SCENE_CFG.standard_beamed_stem_min_spaces
_STANDARD_STEM_MAX_SPACES = _SCENE_CFG.standard_stem_max_spaces
_STANDARD_BEAMED_STEM_MAX_SPACES = _SCENE_CFG.standard_beamed_stem_max_spaces
_STANDARD_STEM_OUTER_EXTENSION_SPACES = _SCENE_CFG.standard_stem_outer_extension_spaces
_NOTEHEAD_STEM_X_OFFSET = _SCENE_CFG.notehead_stem_x_offset
_NOTEHEAD_RX = _SCENE_CFG.notehead_rx
_NOTEHEAD_RY = _SCENE_CFG.notehead_ry
_NOTEHEAD_ROTATION_DEG = _SCENE_CFG.notehead_rotation_deg
_NOTEHEAD_STROKE_WIDTH = _SCENE_CFG.notehead_stroke_width
_REST_BLOCK_WIDTH = _SCENE_CFG.rest_block_width
_REST_BLOCK_HEIGHT = _SCENE_CFG.rest_block_height
_ARC_ONSET_TOLERANCE = _SCENE_CFG.arc_onset_tolerance
_SLUR_TECHNIQUES = frozenset({"legato", "hammer_on", "pull_off", "slide"})

# Key signature glyph layout constants (treble clef).
# Y offsets expressed as *multiples of staff_spacing* from staff_std_y.
# Sharps: F# C# G# D# A# E# B# (FCGDAEB — BEAD GCF reversed)
_KEY_SIG_SHARP_Y_MULT: tuple[float, ...] = (0.0, 1.5, -0.5, 1.0, 2.5, 0.5, 2.0)
# Flats: Bb Eb Ab Db Gb Cb Fb
_KEY_SIG_FLAT_Y_MULT: tuple[float, ...] = (2.0, 0.5, 2.5, 1.0, 3.0, 1.5, 3.5)
_KEY_SIG_START_X = _config().notation.key_signature.start_x  # offset from staff_layout.x
_KEY_SIG_ACC_STEP = _config().notation.key_signature.accidental_step  # gap between accidentals
_KEY_SIG_TIMESIG_PAD = _config().notation.key_signature.timesig_pad  # pad before time sig

# Circle-of-fifths: diatonic step indices (mod 7) altered by the key signature.
# Sharp order: F C G D A E B
_SHARP_ORDER_STEPS: tuple[int, ...] = (3, 0, 4, 1, 5, 2, 6)
# Flat order: B E A D G C F
_FLAT_ORDER_STEPS: tuple[int, ...] = (6, 2, 5, 1, 4, 0, 3)

# Pitch-class-based key signature sets (unambiguous for MIDI input).
# Sharp order: F# C# G# D# A# E# B#
_KEY_SHARP_PCS: tuple[int, ...] = (6, 1, 8, 3, 10, 5, 0)
# Their natural counterparts: F C G D A E B
_KEY_SHARP_NATURAL_PCS: tuple[int, ...] = (5, 0, 7, 2, 9, 4, 11)
# Flat order: Bb Eb Ab Db Gb Cb Fb
_KEY_FLAT_PCS: tuple[int, ...] = (10, 3, 8, 1, 6, 11, 4)
# Their natural counterparts: B E A D G C F
_KEY_FLAT_NATURAL_PCS: tuple[int, ...] = (11, 4, 9, 2, 7, 0, 5)


def _key_altered_steps(fifths: int) -> dict[int, str]:
    """Return a dict mapping diatonic_step % 7 -> 'sharp'|'flat' for key-sig alterations."""
    altered: dict[int, str] = {}
    if fifths > 0:
        for i in range(min(fifths, 7)):
            altered[_SHARP_ORDER_STEPS[i]] = "sharp"
    elif fifths < 0:
        for i in range(min(abs(fifths), 7)):
            altered[_FLAT_ORDER_STEPS[i]] = "flat"
    return altered



def _layout_float(page_layout: PageLayout, key: str, default: float) -> float:
    raw = page_layout.metadata.get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


# Diatonic step (absolute, C0 = 0) of each clef's bottom staff line.  The
# standard-staff note-Y math is anchored on this reference so that notes land
# on the staff for the instrument's natural register:
#   treble → E4 (MIDI 64), bass → G2 (MIDI 43), percussion → unused (neutral).
_E4_DIATONIC_INDEX = _config().notation.clef_reference.treble_bottom_line_diatonic_index
_G2_DIATONIC_INDEX = _config().notation.clef_reference.bass_bottom_line_diatonic_index


def _score_clef(score: Score) -> str:
    """Return the standard-staff clef for the score's first staff.

    Falls back to ``"treble"`` so single-track guitar scores are unaffected.
    """
    for track in score.tracks:
        for staff_group in track.staff_groups:
            for staff in staff_group.staves:
                return getattr(staff, "clef", "treble") or "treble"
    return "treble"


def canonical_to_render_scene(score: Score, *, mode: str = "tablature") -> RenderScene:
    """Build a scene representation from canonical score through layout."""
    page_layout = canonical_to_page_layout(score, mode=mode)
    return layout_to_render_scene(page_layout=page_layout, score=score, mode=mode)


def layout_to_render_scene(
    *, page_layout: PageLayout, score: Score, mode: str = "tablature"
) -> RenderScene:
    """Build render scene from explicit page layout contract."""
    has_tab = _has_tab_mode(mode)
    has_standard = _has_standard_mode(mode)
    has_tab_rhythm = mode == "tablature_rhythm"
    clef = _score_clef(score)
    is_percussion = clef == "percussion"
    staff_spacing = _layout_float(page_layout, "standard_staff_spacing", _STAFF_STD_SPACING)
    tab_spacing = _layout_float(page_layout, "tab_staff_spacing", _TAB_SPACING)
    standard_tab_gap = _layout_float(page_layout, "standard_tab_gap", _STAFF_TAB_CLEARANCE)
    notehead_rx = _layout_float(page_layout, "notehead_rx", _NOTEHEAD_RX)
    notehead_ry = _layout_float(page_layout, "notehead_ry", _NOTEHEAD_RY)
    notehead_rotation = _layout_float(
        page_layout, "notehead_rotation_deg", _NOTEHEAD_ROTATION_DEG
    )
    notehead_stroke_width = _layout_float(
        page_layout, "notehead_stroke_width", _NOTEHEAD_STROKE_WIDTH
    )
    stem_notehead_dx = _layout_float(page_layout, "stem_notehead_dx", _NOTEHEAD_STEM_X_OFFSET)
    rest_block_width = _layout_float(page_layout, "rest_block_width", _REST_BLOCK_WIDTH)
    rest_block_height = _layout_float(page_layout, "rest_block_height", _REST_BLOCK_HEIGHT)
    time_num, time_den = _score_time_signature(score)
    # Build section name lookup: {measure_number: section_name}
    _section_measures: dict[int, str] = {}
    for _trk in score.tracks:
        for _sg in _trk.staff_groups:
            for _st in _sg.staves:
                for _meas in _st.measures:
                    sn = getattr(_meas, "section_name", "")
                    if sn:
                        _section_measures[_meas.number] = sn
    # Build tempo-change lookup: {measure_number: bpm} — only measures where tempo changes.
    _tempo_by_measure: dict[int, int] = _build_tempo_by_measure(score)
    page_systems: list[SystemScene] = []
    for system_index, system_layout in enumerate(page_layout.systems, start=1):
        staff_scenes: list[StaffScene] = []
        for staff_index, staff_layout in enumerate(system_layout.staves, start=1):
            staff_layer = LayerGroup(layer_id="staff")
            notes_layer = LayerGroup(layer_id="notes")

            staff_std_y = staff_layout.y + 4.0
            tab_y = staff_std_y + 4.0 * staff_spacing + standard_tab_gap
            # Stem endpoints are bounded two staff-spaces outside the staff,
            # matching the standard engraving rule for beam heights.
            stem_top_y = staff_std_y - 2 * staff_spacing
            stem_bottom_y = staff_std_y + 6 * staff_spacing
            tab_rhythm_beam_y = tab_y + 5.0 * tab_spacing + 14.0
            # In standard-only mode there is no tab staff; place dynamics just below
            # the bottom of the standard staff (6 staff-spaces below first line).
            if has_tab:
                dynamic_y = tab_y + 5.0 * tab_spacing + 18.0
            else:
                dynamic_y = staff_std_y + 6.0 * staff_spacing + 12.0
            # Compute key-signature layout before time_signature_x so that the
            # time signature can be pushed right when accidentals are present.
            key_fifths = score.key_signature.fifths
            key_sig_count = abs(key_fifths)
            base_timesig_x = staff_layout.x + (30.0 if has_standard else 18.0)
            if has_standard and key_sig_count > 0:
                time_signature_x = (
                    staff_layout.x
                    + _KEY_SIG_START_X
                    + key_sig_count * _KEY_SIG_ACC_STEP
                    + _KEY_SIG_TIMESIG_PAD
                )
            else:
                time_signature_x = base_timesig_x
            time_signature_y = (
                staff_std_y + 2.0 * staff_spacing
                if has_standard
                else tab_y + 2.0 * tab_spacing
            )

            first_measure_number = (
                staff_layout.measure_layouts[0].measure_number
                if staff_layout.measure_layouts
                else 1
            )
            current_num, current_den = _score_time_signature_for_measure(
                score,
                first_measure_number,
                default=(time_num, time_den),
            )
            previous_num, previous_den = _score_time_signature_for_measure(
                score,
                max(1, first_measure_number - 1),
                default=(current_num, current_den),
            )
            show_time_signature = (
                system_index == 1
                or first_measure_number <= 1
                or (current_num, current_den) != (previous_num, previous_den)
            )
            if show_time_signature:
                staff_layer.glyph_instances.append(
                    GlyphInstance(
                        glyph_id="time_signature",
                        x=time_signature_x,
                        y=time_signature_y,
                        size=13.0,
                        metadata={"numerator": current_num, "denominator": current_den},
                    )
                )
            if has_standard:
                # Bass clef sits a line lower than treble; percussion clef is
                # centred.  The y reference keeps the clef visually anchored to
                # its defining staff line.
                if clef == "bass":
                    clef_y = staff_std_y + 1.0 * staff_spacing
                elif clef == "percussion":
                    clef_y = staff_std_y + 2.0 * staff_spacing
                else:
                    clef_y = staff_std_y + 2.0 * staff_spacing
                staff_layer.glyph_instances.append(
                    GlyphInstance(
                        glyph_id="clef",
                        x=staff_layout.x + 8.0,
                        y=clef_y,
                        size=31.0,
                        # staff_spacing lets the SVG backend draw a font-free
                        # percussion (neutral two-bar) clef sized to the staff.
                        metadata={"clef": clef, "staff_spacing": staff_spacing},
                    )
                )
                # Key signature glyphs (sharps or flats) — shown on every system.
                # Percussion staves carry no key signature.
                if key_sig_count > 0 and not is_percussion:
                    ks_glyph = "key_sig_sharp" if key_fifths > 0 else "key_sig_flat"
                    ks_y_mults = _KEY_SIG_SHARP_Y_MULT if key_fifths > 0 else _KEY_SIG_FLAT_Y_MULT
                    for i in range(key_sig_count):
                        staff_layer.glyph_instances.append(
                            GlyphInstance(
                                glyph_id=ks_glyph,
                                x=staff_layout.x + _KEY_SIG_START_X + i * _KEY_SIG_ACC_STEP,
                                y=staff_std_y + ks_y_mults[i] * staff_spacing,
                                size=9.0,
                                metadata={"index": str(i), "fifths": str(key_fifths)},
                            )
                        )
            # Tempo marks are rendered per-measure inside the measure loop below.

            if has_standard:
                staff_layer.recipe_instances.append(
                    RecipeInstance(
                        recipe_id="staff_lines",
                        params={
                            "x": staff_layout.x,
                            "y": staff_std_y,
                            "width": staff_layout.width,
                            "count": 5,
                            "spacing": staff_spacing,
                        },
                    )
                )
            if has_tab:
                staff_layer.recipe_instances.append(
                    RecipeInstance(
                        recipe_id="tab_lines",
                        params={
                            "x": staff_layout.x,
                            "y": tab_y,
                            "width": staff_layout.width,
                            "count": 6,
                            "spacing": tab_spacing,
                        },
                    )
                )
                _append_tab_left_labels(
                    staff_layer,
                    staff_x=staff_layout.x,
                    tab_y=tab_y,
                    tab_spacing=tab_spacing,
                    open_pitches=None,
                )
            _append_measure_barlines(
                staff_layer,
                measure_layouts=staff_layout.measure_layouts,
                has_standard=has_standard,
                has_tab=has_tab,
                staff_std_y=staff_std_y,
                tab_y=tab_y,
                staff_spacing=staff_spacing,
                tab_spacing=tab_spacing,
            )

            key_altered = _key_altered_steps(key_fifths)
            last_dynamic_by_voice: dict[int, str] = {}
            # Connection events are accumulated across all measures within this
            # staff so that cross-measure tie arcs can be drawn (a tie origin at
            # the end of measure N and the continuation at the start of N+1 are
            # detected by _append_standard_connections via contiguous onset check).
            standard_connection_events: list[dict[str, object]] = []
            # Slide events accumulated cross-measure, like standard_connection_events for ties.
            # All tab events (slide and non-slide) are stored here so that the slide target
            # can be located by finding the next note on the same string across measures.
            all_tab_span_events: list[dict[str, object]] = []
            for measure_index, measure_layout in enumerate(staff_layout.measure_layouts):
                standard_rhythm_events: list[tuple[float, float, float, float, str]] = []
                tab_rhythm_events: list[tuple[float, float, float, float]] = []
                tab_span_events: list[dict[str, object]] = []
                tuplet_by_onset: dict[float, tuple[int, int]] = {}
                accidental_columns_by_onset: dict[float, list[float]] = {}
                shown_accidentals_by_step: dict[int, str | None] = {}
                shown_chord_labels_by_onset: set[float] = set()
                shown_strum_marks_by_onset: set[float] = set()
                rhythm_duration_by_onset_voice = _rhythm_duration_by_onset_voice(
                    measure_layout.event_layouts
                )
                stem_direction_by_onset_voice = _stem_direction_by_onset_voice(
                    measure_layout.event_layouts,
                    staff_std_y=staff_std_y,
                    staff_spacing=staff_spacing,
                    clef=clef,
                )
                standard_visible_event_ids = _standard_visible_event_ids(
                    measure_layout.event_layouts
                )
                notehead_offset_by_event_id = _standard_notehead_offsets_by_event_id(
                    measure_layout.event_layouts,
                    stem_direction_by_onset_voice=stem_direction_by_onset_voice,
                    staff_std_y=staff_std_y,
                    staff_spacing=staff_spacing,
                    notehead_rx=notehead_rx,
                    visible_event_ids=standard_visible_event_ids,
                    clef=clef,
                )
                measure_number_x = measure_layout.x + (18.0 if measure_index == 0 else 2.0)
                measure_number_y = staff_std_y - 6.0 if has_standard else tab_y - 6.0
                display_measure_number = measure_layout.measure_number
                if display_measure_number >= 1:
                    notes_layer.text_instances.append(
                        TextInstance(
                            text=str(display_measure_number),
                            x=measure_number_x,
                            y=measure_number_y,
                            font_family="Times-Roman",
                            font_size=8.0,
                            metadata={"kind": "measure_number"},
                        )
                    )
                # Section name and double barline at section boundaries
                _section_name = _section_measures.get(measure_layout.measure_number, "")
                if _section_name:
                    _section_y = (staff_std_y - 28.0) if has_standard else (tab_y - 8.0)
                    notes_layer.text_instances.append(
                        TextInstance(
                            text=_section_name,
                            x=measure_layout.x + 2.0,
                            y=_section_y,
                            font_family="Times-Bold",
                            font_size=9.0,
                            metadata={"kind": "section_name"},
                        )
                    )
                    if measure_layout.measure_number > 1:
                        if has_standard and has_tab:
                            _bar_y0 = staff_std_y
                            _bar_y1 = tab_y + 5.0 * tab_spacing
                        elif has_standard:
                            _bar_y0 = staff_std_y
                            _bar_y1 = staff_std_y + 4.0 * staff_spacing
                        else:
                            _bar_y0 = tab_y
                            _bar_y1 = tab_y + 5.0 * tab_spacing
                        staff_layer.recipe_instances.append(
                            RecipeInstance(
                                recipe_id="barline",
                                params={
                                    "x": measure_layout.x + 2.5,
                                    "y0": _bar_y0,
                                    "y1": _bar_y1,
                                    "width": 0.8,
                                },
                            )
                        )
                # Tempo mark at this measure (if the tempo changes here).
                _measure_bpm = _tempo_by_measure.get(measure_layout.measure_number)
                if _measure_bpm is not None:
                    # Anchor the tempo mark just above the measure number so it
                    # stays in the correct inter-system gap regardless of mode.
                    _tempo_y = measure_number_y - 14.0
                    _tempo_x = measure_layout.x + (18.0 if measure_index == 0 else 2.0)
                    notes_layer.text_instances.append(
                        TextInstance(
                            text=f"♩ = {_measure_bpm}",
                            x=_tempo_x,
                            y=_tempo_y,
                            font_family="Helvetica-Bold",
                            font_size=10.0,
                            metadata={"kind": "tempo"},
                        )
                    )
                for event_layout in measure_layout.event_layouts:
                    event_type = event_layout.metadata.get("event_type")
                    if event_type != "RestEvent":
                        _ta = _safe_int(event_layout.metadata.get("tuplet_actual"))
                        _tn = _safe_int(event_layout.metadata.get("tuplet_normal"))
                        if _ta and _tn and _ta != _tn:
                            tuplet_by_onset[round(event_layout.onset, 6)] = (_ta, _tn)
                    # Harmonic *resultant* overtones are a standard-staff-only
                    # diamond notehead; they have no string/fret and must not
                    # produce a tab digit (but must still reach the standard plane
                    # below, so this only gates the tab block — never ``continue``).
                    tab_hidden = event_layout.metadata.get("tab_hidden") == "true"
                    if has_tab and event_type != "RestEvent" and not tab_hidden:
                        techniques = _parse_techniques(event_layout.metadata.get("techniques"))
                        if "muted" in techniques:
                            text = "X"
                        else:
                            text = event_layout.metadata.get(
                                "tab_fret"
                            ) or event_layout.metadata.get("pitch_notated", "0")
                        tab_note_y = _tab_note_y_from_metadata(
                            event_layout.metadata,
                            tab_y=tab_y,
                            tab_spacing=tab_spacing,
                        )
                        tab_note_x = min(
                            event_layout.x,
                            measure_layout.x + measure_layout.width - 4.0,
                        )
                        notes_layer.text_instances.append(
                            TextInstance(
                                text=str(text),
                                x=tab_note_x,
                                y=tab_note_y,
                                font_family="Times-Roman",
                                font_size=8.5,
                                metadata={
                                    "kind": "note",
                                    "event_id": event_layout.event_id,
                                    "tab_string": event_layout.metadata.get("tab_string", "3"),
                                    "onset": event_layout.onset,
                                    "pitch_notated": event_layout.metadata.get("pitch_notated", ""),
                                    "text_anchor": "middle",
                                    "dominant_baseline": "central",
                                },
                            )
                        )
                        onset_key = round(event_layout.onset, 6)
                        if onset_key not in shown_strum_marks_by_onset:
                            strum_symbol = ""
                            strum_direction = ""
                            if "strum_down" in techniques:
                                strum_symbol = "↓"
                                strum_direction = "down"
                            elif "strum_up" in techniques:
                                strum_symbol = "↑"
                                strum_direction = "up"
                            if strum_symbol:
                                notes_layer.text_instances.append(
                                    TextInstance(
                                        text=strum_symbol,
                                        x=event_layout.x - 2.0,
                                        y=tab_y + 5.0 * tab_spacing + 10.0,
                                        font_family="Times-Bold",
                                        font_size=10.5,
                                        metadata={
                                            "kind": "strum_direction",
                                            "onset": onset_key,
                                            "direction": strum_direction,
                                        },
                                    )
                                )
                                shown_strum_marks_by_onset.add(onset_key)
                        _tab_event_dict = {
                            "event_id": event_layout.event_id,
                            "x": event_layout.x,
                            "y": tab_note_y,
                            "onset": event_layout.onset,
                            "tab_string": _safe_int(event_layout.metadata.get("tab_string"))
                            or 3,
                            "techniques": techniques,
                            "fret_num": _safe_int(event_layout.metadata.get("tab_fret")) or 0,
                        }
                        tab_span_events.append(_tab_event_dict)
                        all_tab_span_events.append(_tab_event_dict)

                    if has_standard:
                        voice_number = _safe_int(event_layout.metadata.get("voice_number")) or 0
                        if event_type == "RestEvent":
                            _append_rest_glyph(
                                notes_layer,
                                x=event_layout.x,
                                event_id=event_layout.event_id,
                                voice_number=voice_number,
                                duration=event_layout.duration,
                                staff_std_y=staff_std_y,
                                staff_spacing=staff_spacing,
                                measure_number=measure_layout.measure_number,
                                beats_per_measure=measure_layout.beats_per_measure,
                                rest_onset=event_layout.onset,
                                measure_rest_hint=event_layout.metadata.get("measure_rest", ""),
                                rest_block_width=rest_block_width,
                                rest_block_height=rest_block_height,
                            )
                        else:
                            if event_layout.event_id not in standard_visible_event_ids:
                                continue
                            note_y = _standard_note_y(
                                event_layout.metadata,
                                staff_std_y=staff_std_y,
                                staff_spacing=staff_spacing,
                                clef=clef,
                            )
                            techniques = _parse_techniques(event_layout.metadata.get("techniques"))
                            pitch = _safe_int(event_layout.metadata.get("pitch_notated")) or 64
                            diatonic_step = _diatonic_step_from_metadata(
                                event_layout.metadata,
                                fallback_pitch=pitch,
                            )
                            onset_key = round(event_layout.onset, 6)
                            display_duration = rhythm_duration_by_onset_voice.get(
                                (onset_key, voice_number),
                                event_layout.duration,
                            )
                            chord_offset = notehead_offset_by_event_id.get(
                                event_layout.event_id, 0.0
                            )
                            note_x = event_layout.x + chord_offset
                            stem_direction = stem_direction_by_onset_voice.get(
                                (onset_key, voice_number),
                                _stem_direction_for_note(
                                    note_y=note_y,
                                    voice_number=voice_number,
                                    staff_std_y=staff_std_y,
                                    staff_spacing=staff_spacing,
                                ),
                            )
                            chord_name = str(event_layout.metadata.get("chord_name", "")).strip()
                            if chord_name and onset_key not in shown_chord_labels_by_onset:
                                notes_layer.text_instances.append(
                                    TextInstance(
                                        text=chord_name,
                                        x=event_layout.x,
                                        y=staff_std_y - 18.0,
                                        font_family="Times-Bold",
                                        font_size=11.0,
                                        metadata={"kind": "chord_name", "onset": onset_key},
                                    )
                                )
                                shown_chord_labels_by_onset.add(onset_key)
                            accidental = _accidental_glyph_for_event_key_aware(
                                event_layout.metadata,
                                fallback_pitch=pitch,
                                diatonic_step=diatonic_step,
                                key_altered=key_altered,
                            )
                            if "muted" in techniques:
                                accidental = None
                            elif (
                                accidental is None
                                and shown_accidentals_by_step.get(diatonic_step) is not None
                            ):
                                # Natural cancellation: a prior alteration on this
                                # diatonic step within the measure needs a ♮ to cancel.
                                accidental = "accidental_natural"
                            if (
                                accidental is not None
                                and accidental != shown_accidentals_by_step.get(diatonic_step)
                            ):
                                columns_for_onset = accidental_columns_by_onset.setdefault(
                                    onset_key, []
                                )
                                column = _accidental_column_for_note_y(
                                    columns_for_onset,
                                    note_y,
                                    min_vertical_gap=staff_spacing * 3.0,
                                )
                                accidental_base_offset = notehead_rx + 7.0
                                accidental_column_gap = max(7.8, notehead_rx * 1.95)
                                accidental_anchor_x = min(event_layout.x, note_x)
                                notes_layer.glyph_instances.append(
                                    GlyphInstance(
                                        glyph_id=accidental,
                                        x=accidental_anchor_x
                                        - accidental_base_offset
                                        - column * accidental_column_gap,
                                        y=note_y + 0.5,
                                        size=9.0,
                                        metadata={"event_id": event_layout.event_id},
                                    )
                                )
                                shown_accidentals_by_step[diatonic_step] = accidental
                            is_dyad_fundamental = (
                                event_layout.metadata.get("harmonic_dyad_fundamental") == "true"
                            )
                            if is_percussion and _is_x_notehead_drum(pitch):
                                # Hi-hats, cymbals and the ride use an 'x'-shaped
                                # notehead.  The muted glyph already renders as an X.
                                notehead_glyph = "notehead_muted"
                            elif "muted" in techniques:
                                notehead_glyph = "notehead_muted"
                            elif "harmonic" in techniques and not is_dyad_fundamental:
                                # The diamond belongs to the resultant overtone; the
                                # fretted fundamental of a harmonic dyad keeps a normal
                                # notehead (matching Guitar Pro / MuseScore).
                                notehead_glyph = "notehead_harmonic"
                            else:
                                notehead_glyph = "notehead"
                            notes_layer.glyph_instances.append(
                                GlyphInstance(
                                    glyph_id=notehead_glyph,
                                    x=note_x,
                                    y=note_y,
                                    size=3.6,
                                    metadata={
                                        "event_id": event_layout.event_id,
                                        "onset": event_layout.onset,
                                        "duration": display_duration,
                                        "pitch_notated": pitch,
                                        "filled": _is_filled_notehead(display_duration),
                                        "duration_class": _duration_class(display_duration),
                                        "dot_count": _dot_count(display_duration),
                                        "on_staff_line": "true"
                                        if diatonic_step % 2 == 0
                                        else "false",
                                        "staff_spacing": staff_spacing,
                                        "rx": notehead_rx,
                                        "ry": notehead_ry,
                                        "rotation": notehead_rotation,
                                        "stroke_width": notehead_stroke_width,
                                        "head_displaced": "true"
                                        if abs(chord_offset) > 0.1
                                        else "false",
                                        "head_dx": chord_offset,
                                    },
                                )
                            )
                            _append_ledger_lines(
                                notes_layer,
                                x=note_x,
                                note_y=note_y,
                                staff_std_y=staff_std_y,
                                staff_spacing=staff_spacing,
                            )
                            dynamic_mark = str(event_layout.metadata.get("dynamic", "")).strip()
                            if (
                                dynamic_mark
                                and last_dynamic_by_voice.get(voice_number) != dynamic_mark
                            ):
                                notes_layer.text_instances.append(
                                    TextInstance(
                                        text=dynamic_mark,
                                        x=note_x - 2.0,
                                        y=dynamic_y,
                                        font_family="Times-Italic",
                                        font_size=8.5,
                                        metadata={
                                            "kind": "dynamic",
                                            "voice_number": str(voice_number),
                                        },
                                    )
                                )
                                last_dynamic_by_voice[voice_number] = dynamic_mark

                            standard_rhythm_events.append(
                                (
                                    note_x,
                                    event_layout.onset,
                                    event_layout.duration,
                                    note_y,
                                    stem_direction,
                                )
                            )
                            standard_connection_events.append(
                                {
                                    "event_id": event_layout.event_id,
                                    "x": note_x,
                                    "y": note_y,
                                    "onset": event_layout.onset,
                                    "duration": event_layout.duration,
                                    "pitch": pitch,
                                    "techniques": techniques,
                                    "stem_direction": stem_direction,
                                    "voice_number": voice_number,
                                    "is_tie_dest": str(
                                        event_layout.metadata.get("is_tie_dest", "")
                                    ).lower() == "true",
                                }
                            )

                    if has_tab_rhythm:
                        voice_number = _safe_int(event_layout.metadata.get("voice_number")) or 0
                        if event_type == "RestEvent":
                            _append_tab_rhythm_rest_glyph(
                                notes_layer,
                                x=event_layout.x,
                                event_id=event_layout.event_id,
                                voice_number=voice_number,
                                duration=event_layout.duration,
                                tab_y=tab_y,
                                tab_spacing=tab_spacing,
                            )
                        else:
                            # Use the same chord-level display duration as standard notation
                            # (min per onset+voice), not the raw note duration.
                            _tab_onset_key = round(event_layout.onset, 6)
                            _tab_display_dur = rhythm_duration_by_onset_voice.get(
                                (_tab_onset_key, voice_number),
                                event_layout.duration,
                            )
                            tab_rhythm_events.append(
                                (
                                    event_layout.x,
                                    event_layout.onset,
                                    _tab_display_dur,
                                    _tab_note_y_from_metadata(
                                        event_layout.metadata,
                                        tab_y=tab_y,
                                        tab_spacing=tab_spacing,
                                    ),
                                )
                            )

                if has_standard and standard_rhythm_events:
                    _append_standard_rhythm(
                        notes_layer,
                        measure_number=measure_layout.measure_number,
                        beats_per_measure=measure_layout.beats_per_measure,
                        time_denominator=measure_layout.time_denominator,
                        events=standard_rhythm_events,
                        stem_top_y=stem_top_y,
                        stem_bottom_y=stem_bottom_y,
                        staff_spacing=staff_spacing,
                        stem_offset=stem_notehead_dx,
                        tab_y=tab_y if has_tab else None,
                        tuplet_by_onset=tuplet_by_onset,
                    )
                if has_tab_rhythm and tab_rhythm_events:
                    _append_tablature_rhythm(
                        notes_layer,
                        measure_number=measure_layout.measure_number,
                        beats_per_measure=measure_layout.beats_per_measure,
                        time_denominator=measure_layout.time_denominator,
                        events=tab_rhythm_events,
                        tab_rhythm_beam_y=tab_rhythm_beam_y,
                        tuplet_by_onset=tuplet_by_onset,
                    )
                if has_tab and tab_span_events:
                    _append_tab_technique_spans(
                        notes_layer,
                        measure_x=measure_layout.x,
                        measure_width=measure_layout.width,
                        events=tab_span_events,
                    )

            # Draw tie/slur arcs once per staff after all measures, so that
            # cross-measure ties (origin in measure N, destination in N+1) are
            # connected correctly.
            if has_standard and standard_connection_events:
                _append_standard_connections(notes_layer, standard_connection_events)
            # Draw slide diagonal lines after all measures using the full cross-measure
            # event list, so that slides at the end of a measure connect to the next
            # note even if it is in a different measure.
            if has_tab and all_tab_span_events:
                _append_tab_slide_connections(notes_layer, all_tab_span_events)

            staff_scenes.append(
                StaffScene(
                    staff_id=staff_layout.staff_id,
                    x=staff_layout.x,
                    y=staff_layout.y,
                    width=staff_layout.width,
                    height=staff_layout.height,
                    layer_groups=[staff_layer, notes_layer],
                )
            )

        page_systems.append(
            SystemScene(
                system_id=system_layout.system_id,
                x=system_layout.x,
                y=system_layout.y,
                width=system_layout.width,
                height=system_layout.height,
                staves=staff_scenes,
            )
        )

    page_width = page_layout.width or _PAGE_W
    page_height = page_layout.height or _PAGE_H
    if page_systems:
        page_height = max(
            page_height,
            max(system.y + system.height for system in page_systems) + _MARGIN_Y,
        )

    page_scene = PageScene(
        page_number=page_layout.page_number,
        width=page_width,
        height=page_height,
        systems=page_systems,
    )
    document_scene = DocumentScene(title=score.title, pages=[page_scene])
    return RenderScene(document_scene=document_scene)


def _append_note_text(
    layer: LayerGroup, event: CanonicalNoteEvent, measure_x: float, *, tab_y: float
) -> None:
    column_x = measure_x + (event.onset % 4.0) * 36.0 + 28.0
    if event.tab_info is not None and event.tab_info.string is not None:
        string_num = max(1, min(6, event.tab_info.string))
    else:
        string_num = 3
    y = tab_y + (string_num - 1) * 18.0 + 4.0

    text = str(event.pitch_notated)
    if event.tab_info is not None and event.tab_info.fret is not None:
        text = str(event.tab_info.fret)

    layer.text_instances.append(
        TextInstance(
            text=text,
            x=column_x,
            y=y,
            font_size=11.0,
            metadata={
                "kind": "note",
                "event_id": event.event_id,
                "tab_string": str(string_num),
            },
        )
    )


def _standard_note_y(
    metadata: dict[str, str],
    *,
    staff_std_y: float,
    staff_spacing: float,
    clef: str = "treble",
) -> float:
    pitch_raw = metadata.get("pitch_notated", "64")
    try:
        pitch = int(pitch_raw)
    except ValueError:
        pitch = 64

    if clef == "percussion":
        return _notation_percussion_note_y(
            pitch,
            staff_y_origin=staff_std_y,
            staff_spacing=staff_spacing,
        )

    step_raw = str(metadata.get("pitch_step", "")).strip().upper() or None
    octave_raw = str(metadata.get("pitch_octave", "")).strip()
    octave: int | None
    try:
        octave = int(octave_raw) if octave_raw else None
    except ValueError:
        octave = None

    return _notation_standard_note_y(
        pitch,
        staff_y_origin=staff_std_y,
        staff_spacing=staff_spacing,
        step=step_raw,
        octave=octave,
        clef=clef,
    )


def _append_ledger_lines(
    layer: LayerGroup,
    *,
    x: float,
    note_y: float,
    staff_std_y: float,
    staff_spacing: float,
) -> None:
    top_line_y = staff_std_y
    bottom_line_y = staff_std_y + 4.0 * staff_spacing
    half_step = staff_spacing / 2.0
    ledger_half_span = 7.5

    if note_y < top_line_y - half_step:
        # Notes in the first outer space (top_line - half_step) do not carry
        # a ledger line. Ledger starts on the first outer line.
        count = int((top_line_y - note_y) // staff_spacing)
        for idx in range(1, count + 1):
            y = top_line_y - idx * staff_spacing
            layer.recipe_instances.append(
                RecipeInstance(
                    recipe_id="ledger_line",
                    params={
                        "x0": x - ledger_half_span,
                        "x1": x + ledger_half_span,
                        "y": y,
                        "width": 1.0,
                    },
                )
            )

    if note_y > bottom_line_y + half_step:
        # Symmetric rule below the staff: first outer space has no ledger.
        count = int((note_y - bottom_line_y) // staff_spacing)
        for idx in range(1, count + 1):
            y = bottom_line_y + idx * staff_spacing
            layer.recipe_instances.append(
                RecipeInstance(
                    recipe_id="ledger_line",
                    params={
                        "x0": x - ledger_half_span,
                        "x1": x + ledger_half_span,
                        "y": y,
                        "width": 1.0,
                    },
                )
            )


def _append_rest_glyph(
    layer: LayerGroup,
    *,
    x: float,
    event_id: str,
    voice_number: int,
    duration: float,
    staff_std_y: float,
    staff_spacing: float,
    measure_number: int,
    beats_per_measure: int,
    rest_onset: float,
    measure_rest_hint: str = "",
    rest_block_width: float = _REST_BLOCK_WIDTH,
    rest_block_height: float = _REST_BLOCK_HEIGHT,
) -> None:
    is_measure_rest = _is_measure_rest_event(
        rest_onset,
        duration,
        measure_number=measure_number,
        beats_per_measure=beats_per_measure,
    ) or _boolish(measure_rest_hint)
    rest_kind = _rest_kind(duration, is_measure_rest=is_measure_rest)
    dot_count = 0 if is_measure_rest else _dot_count(duration)
    layer.glyph_instances.append(
        GlyphInstance(
            glyph_id="rest",
            x=x,
            y=_standard_rest_y(
                voice_number,
                staff_std_y=staff_std_y,
                staff_spacing=staff_spacing,
                rest_kind=rest_kind,
            ),
            size=11.0,
            metadata={
                "event_id": event_id,
                "voice_number": str(voice_number),
                "duration": duration,
                "duration_class": _duration_class(duration),
                "rest_kind": rest_kind,
                "is_measure_rest": "true" if is_measure_rest else "false",
                "dot_count": dot_count,
                "rest_block_width": rest_block_width,
                "rest_block_height": rest_block_height,
            },
        )
    )


def _standard_rest_y(
    voice_number: int,
    *,
    staff_std_y: float,
    staff_spacing: float,
    rest_kind: str,
) -> float:
    standard_rest_center_y = staff_std_y + 2.0 * staff_spacing
    if rest_kind == "whole":
        anchor_y = staff_std_y + 1.0 * staff_spacing
    elif rest_kind == "half":
        anchor_y = staff_std_y + 2.0 * staff_spacing
    else:
        anchor_y = standard_rest_center_y

    rest_voice_offset = 0.75 * staff_spacing
    if voice_number <= 0:
        return anchor_y
    if voice_number >= 1:
        return anchor_y + rest_voice_offset
    return anchor_y


def _append_tab_rhythm_rest_glyph(
    layer: LayerGroup,
    *,
    x: float,
    event_id: str,
    voice_number: int,
    duration: float,
    tab_y: float,
    tab_spacing: float,
) -> None:
    rest_kind = _rest_kind(duration)
    dot_count = _dot_count(duration)
    layer.glyph_instances.append(
        GlyphInstance(
            glyph_id="rest",
            x=x,
            y=_tab_rhythm_rest_y(voice_number, tab_y=tab_y, tab_spacing=tab_spacing),
            size=12.0,
            metadata={
                "event_id": event_id,
                "voice_number": str(voice_number),
                "mode": "tablature_rhythm",
                "duration": duration,
                "duration_class": _duration_class(duration),
                "rest_kind": rest_kind,
                "is_measure_rest": "false",
                "dot_count": dot_count,
            },
        )
    )


def _tab_rhythm_rest_y(voice_number: int, *, tab_y: float, tab_spacing: float) -> float:
    tab_rhythm_rest_center_y = tab_y + 5.0 * tab_spacing + 8.0
    return tab_rhythm_rest_center_y + (voice_number - 0.5) * 2.5


def _tab_digit_y(event: CanonicalNoteEvent, *, tab_y: float, tab_spacing: float) -> float:
    if event.tab_info is not None and event.tab_info.string is not None:
        string_num = max(1, min(6, event.tab_info.string))
    else:
        string_num = 3
    return tab_y + (string_num - 1) * tab_spacing


def _tab_note_y_from_metadata(
    metadata: dict[str, str], *, tab_y: float, tab_spacing: float
) -> float:
    string_num = _safe_int(metadata.get("tab_string")) or 3
    string_num = max(1, min(6, string_num))
    return tab_y + (string_num - 1) * tab_spacing


def _build_tempo_by_measure(score: Score) -> dict[int, int]:
    """Return {measure_number: bpm} for every measure where tempo changes.

    Uses the canonical measure list to determine each measure's start onset
    (from the first event in the measure), then bisects the sorted tempo_marks
    list to find the active BPM.  Only measures where the BPM differs from
    the previous measure are included, so the renderer can skip unchanged bars.
    """
    if not score.tempo_marks:
        return {}
    tm_onsets = [tm.onset for tm in score.tempo_marks]
    tm_bpms = [tm.bpm for tm in score.tempo_marks]
    result: dict[int, int] = {}
    prev_bpm: float | None = None
    for track in score.tracks:
        for staff_group in track.staff_groups:
            for staff in staff_group.staves:
                for measure in staff.measures:
                    # Find the earliest event onset in this measure.
                    all_events = [e for v in measure.voices for e in v.events]
                    if not all_events:
                        continue
                    measure_onset = min(e.onset for e in all_events)
                    idx = bisect.bisect_right(tm_onsets, measure_onset) - 1
                    idx = max(0, idx)
                    bpm = tm_bpms[idx]
                    if prev_bpm is None or abs(bpm - prev_bpm) > 0.5:
                        result[measure.number] = int(round(bpm))
                        prev_bpm = bpm
                return result  # Only process first track/staff
    return result


def _score_time_signature(score: Score) -> tuple[int, int]:
    for track in score.tracks:
        for staff_group in track.staff_groups:
            for staff in staff_group.staves:
                for measure in staff.measures:
                    return measure.time_signature.numerator, measure.time_signature.denominator
    return 4, 4


def _score_time_signature_for_measure(
    score: Score,
    measure_number: int,
    *,
    default: tuple[int, int] = (4, 4),
) -> tuple[int, int]:
    target = max(1, measure_number)
    for track in score.tracks:
        for staff_group in track.staff_groups:
            for staff in staff_group.staves:
                fallback = default
                for measure in staff.measures:
                    signature = (
                        measure.time_signature.numerator,
                        measure.time_signature.denominator,
                    )
                    if measure.number == target:
                        return signature
                    fallback = signature
                return fallback
    return default


_PITCH_CLASS_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_STANDARD_OPEN_PITCHES: tuple[int, ...] = (64, 59, 55, 50, 45, 40)


def _open_pitch_to_string_label(midi: int, string_num: int) -> str:
    name = _PITCH_CLASS_NAMES[midi % 12]
    # High E (string 1) shown lowercase by convention to distinguish from low E
    if name == "E" and string_num == 1:
        return "e"
    return name


def _extract_open_pitches(score: Score) -> tuple[int, ...]:
    """Infer open-string MIDI pitches from TabInfo on score notes (pitch - fret)."""
    pitches: dict[int, int] = {}
    for track in score.tracks:
        for sg in track.staff_groups:
            for staff in sg.staves:
                for measure in staff.measures:
                    for voice in measure.voices:
                        for event in voice.events:
                            candidates = []
                            notes = getattr(event, "notes", None)
                            if notes is not None:
                                candidates.extend(notes)
                            else:
                                candidates.append(event)
                            for note in candidates:
                                ti = getattr(note, "tab_info", None)
                                if ti is None:
                                    continue
                                s = getattr(ti, "string", None)
                                f = getattr(ti, "fret", None)
                                p = getattr(note, "pitch_sounding", None)
                                if s and f is not None and p is not None and s not in pitches:
                                    pitches[s] = p - f
                        if len(pitches) == 6:
                            break
    if len(pitches) < 6:
        return _STANDARD_OPEN_PITCHES
    return tuple(pitches[s] for s in range(1, 7))


def _append_tab_left_labels(
    layer: LayerGroup,
    *,
    staff_x: float,
    tab_y: float,
    tab_spacing: float,
    open_pitches: tuple[int, ...] | None = None,
) -> None:
    tab_letters = ("T", "A", "B")
    for idx, letter in enumerate(tab_letters):
        layer.text_instances.append(
            TextInstance(
                text=letter,
                x=staff_x - 34.0,
                y=tab_y + 10.0 + idx * 14.0,
                font_size=10.0,

                metadata={"kind": "tab_label"},
            )
        )

    if open_pitches and len(open_pitches) == 6:
        for idx in range(6):
            string_label = _open_pitch_to_string_label(open_pitches[idx], idx + 1)
            layer.text_instances.append(
                TextInstance(
                    text=string_label,
                    x=staff_x - 14.0,
                    y=tab_y + idx * tab_spacing + 4.0,
                    font_size=8.0,
                    metadata={"kind": "string_label", "string_number": str(idx + 1)},
                )
            )


def _append_measure_barlines(
    layer: LayerGroup,
    *,
    measure_layouts: list[object],
    has_standard: bool,
    has_tab: bool,
    staff_std_y: float,
    tab_y: float,
    staff_spacing: float,
    tab_spacing: float,
) -> None:
    if not measure_layouts or not (has_standard or has_tab):
        return

    boundaries: list[float] = []
    for measure_layout in measure_layouts:
        x = float(getattr(measure_layout, "x", 0.0)) + float(getattr(measure_layout, "width", 0.0))
        if boundaries and abs(boundaries[-1] - x) < 1e-3:
            continue
        boundaries.append(x)

    if not boundaries:
        return
    if has_standard and has_tab:
        y0 = staff_std_y
        y1 = tab_y + 5.0 * tab_spacing
    elif has_standard:
        y0 = staff_std_y
        y1 = staff_std_y + 4.0 * staff_spacing
    else:
        y0 = tab_y
        y1 = tab_y + 5.0 * tab_spacing

    for x in boundaries:
        layer.recipe_instances.append(
            RecipeInstance(
                recipe_id="barline",
                params={"x": x, "y0": y0, "y1": y1, "width": 0.8},
            )
        )


def _tuplet_bracket_runs(
    group: list[tuple[float, float, float]],
    tuplet_by_onset: dict[float, tuple[int, int]],
) -> list[tuple[float, float, int]]:
    """Find contiguous runs of same-tuplet notes within a beam group.

    Returns a list of (x0, x1, tuplet_number) for each run of ≥2 consecutive
    notes sharing the same non-trivial tuplet ratio.  This handles the common
    case where a beam group mixes tuplet notes and regular notes (e.g. 3 triplet
    16ths followed by a regular 8th in the same beat).
    """
    results: list[tuple[float, float, int]] = []
    run_start: int | None = None
    run_tup: tuple[int, int] | None = None

    def _flush(end_idx: int) -> None:
        nonlocal run_start, run_tup
        if run_start is not None and end_idx - run_start >= 2:
            results.append((group[run_start][0], group[end_idx - 1][0], run_tup[0]))  # type: ignore[index]
        run_start = None
        run_tup = None

    for idx, (x, onset, _dur) in enumerate(group):
        tup = tuplet_by_onset.get(round(onset, 6))
        if tup is not None:
            if tup == run_tup:
                pass  # extend current run
            else:
                _flush(idx)
                run_start = idx
                run_tup = tup
        else:
            _flush(idx)

    _flush(len(group))
    return results


def _rhythm_duration_by_onset_voice(events: list[object]) -> dict[tuple[float, int], float]:
    duration_map: dict[tuple[float, int], float] = {}
    for event in events:
        event_type = str(getattr(event, "metadata", {}).get("event_type", ""))
        if event_type == "RestEvent":
            continue
        onset = round(float(getattr(event, "onset", 0.0)), 6)
        voice_number = _safe_int(getattr(event, "metadata", {}).get("voice_number")) or 0
        duration = float(getattr(event, "duration", 1.0))
        key = (onset, voice_number)
        if key in duration_map:
            duration_map[key] = min(duration_map[key], duration)
        else:
            duration_map[key] = duration
    return duration_map


def _stem_direction_by_onset_voice(
    events: list[object],
    *,
    staff_std_y: float,
    staff_spacing: float,
    clef: str = "treble",
) -> dict[tuple[float, int], str]:
    grouped_note_ys: dict[tuple[float, int], list[float]] = {}
    # Track which voices are active at each specific onset, not globally.
    # A measure with sparse Voice-1 notes (e.g. Stairway accompaniment) should
    # still use pitch-based direction at onsets where only Voice 0 is present.
    voices_at_onset: dict[float, set[int]] = {}
    middle_line_y = staff_std_y + 2.0 * staff_spacing

    for event in events:
        event_type = str(getattr(event, "metadata", {}).get("event_type", ""))
        if event_type == "RestEvent":
            continue
        onset = round(float(getattr(event, "onset", 0.0)), 6)
        voice_number = _safe_int(getattr(event, "metadata", {}).get("voice_number")) or 0
        voices_at_onset.setdefault(onset, set()).add(voice_number)
        note_y = _standard_note_y(
            getattr(event, "metadata", {}),
            staff_std_y=staff_std_y,
            staff_spacing=staff_spacing,
            clef=clef,
        )
        grouped_note_ys.setdefault((onset, voice_number), []).append(note_y)

    direction_by_key: dict[tuple[float, int], str] = {}
    for key, note_ys in grouped_note_ys.items():
        onset, voice_number = key
        onset_is_polyphonic = len(voices_at_onset.get(onset, set())) > 1
        if onset_is_polyphonic:
            direction_by_key[key] = "down" if voice_number >= 1 else "up"
        else:
            direction_by_key[key] = _stem_direction_for_cluster(
                note_ys,
                voice_number=voice_number,
                middle_line_y=middle_line_y,
            )
    return direction_by_key


def _standard_notehead_offsets_by_event_id(
    events: list[object],
    *,
    stem_direction_by_onset_voice: dict[tuple[float, int], str],
    staff_std_y: float,
    staff_spacing: float,
    notehead_rx: float,
    visible_event_ids: set[str] | None = None,
    clef: str = "treble",
) -> dict[str, float]:
    by_key: dict[tuple[float, int], list[tuple[str, float]]] = {}
    # Keep packed chord clusters readable by alternating displaced heads when
    # adjacent notes are a second apart (or closer).
    min_vertical_gap = staff_spacing * 0.92
    horizontal_shift = max(6.8, notehead_rx * 2.0)

    for event in events:
        metadata = getattr(event, "metadata", {})
        if str(metadata.get("event_type", "")) == "RestEvent":
            continue
        event_id = str(getattr(event, "event_id", ""))
        if not event_id:
            continue
        if visible_event_ids is not None and event_id not in visible_event_ids:
            continue
        onset = round(float(getattr(event, "onset", 0.0)), 6)
        voice_number = _safe_int(metadata.get("voice_number")) or 0
        note_y = _standard_note_y(
            metadata,
            staff_std_y=staff_std_y,
            staff_spacing=staff_spacing,
            clef=clef,
        )
        by_key.setdefault((onset, voice_number), []).append((event_id, note_y))

    offsets_by_event_id: dict[str, float] = {}
    for key, notes in by_key.items():
        if len(notes) < 2:
            continue
        onset, voice_number = key
        direction = stem_direction_by_onset_voice.get((onset, voice_number), "up")
        sorted_notes = sorted(notes, key=lambda item: item[1])
        sign = 1.0 if direction == "up" else -1.0

        run_start = 0
        runs: list[tuple[int, int]] = []
        for idx in range(1, len(sorted_notes)):
            if abs(sorted_notes[idx][1] - sorted_notes[idx - 1][1]) >= min_vertical_gap:
                runs.append((run_start, idx))
                run_start = idx
        runs.append((run_start, len(sorted_notes)))

        # GP-like rule: in close-note chord runs, displace the note nearest the
        # stem side first, then alternate. This keeps outer notes visibly tied
        # to the stem side for both up- and down-stem chords.
        for start, end in runs:
            if (end - start) < 2:
                continue
            if direction == "up":
                idx = end - 1  # lowest note is nearest the stem side for up-stems
                while idx >= start:
                    event_id, _note_y = sorted_notes[idx]
                    offsets_by_event_id[event_id] = sign * horizontal_shift
                    idx -= 2
            else:
                idx = start  # highest note is nearest the stem side for down-stems
                while idx < end:
                    event_id, _note_y = sorted_notes[idx]
                    offsets_by_event_id[event_id] = sign * horizontal_shift
                    idx += 2
    return offsets_by_event_id


def _standard_visible_event_ids(events: list[object]) -> set[str]:
    visible_ids: set[str] = set()
    seen_keys: set[tuple[float, int, tuple[str, str]]] = set()
    for event in events:
        metadata = getattr(event, "metadata", {})
        if str(metadata.get("event_type", "")) == "RestEvent":
            continue
        event_id = str(getattr(event, "event_id", ""))
        if not event_id:
            continue

        onset = round(float(getattr(event, "onset", 0.0)), 6)
        voice_number = _safe_int(metadata.get("voice_number")) or 0
        step = str(metadata.get("pitch_step", "")).strip().upper()
        octave = str(metadata.get("pitch_octave", "")).strip()
        if step in {"A", "B", "C", "D", "E", "F", "G"} and octave:
            pitch_key = (step, octave)
        else:
            pitch_key = ("midi", str(metadata.get("pitch_notated", "")))

        dedupe_key = (onset, voice_number, pitch_key)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        visible_ids.add(event_id)
    return visible_ids


def _append_standard_rhythm(
    layer: LayerGroup,
    *,
    measure_number: int,
    beats_per_measure: int,
    time_denominator: int = 4,
    events: list[tuple[float, float, float, float, str]],
    stem_top_y: float,
    stem_bottom_y: float,
    staff_spacing: float,
    stem_offset: float,
    tab_y: float | None = None,
    tuplet_by_onset: dict[float, tuple[int, int]] | None = None,
) -> None:
    stem_entries: list[dict[str, float | int | str]] = []
    stem_length = max(_MIN_STEM_LENGTH, _STANDARD_STEM_LENGTH_SPACES * staff_spacing)
    beamed_stem_length = max(stem_length, _STANDARD_BEAMED_STEM_MIN_SPACES * staff_spacing)
    max_stem_length = max(stem_length, _STANDARD_STEM_MAX_SPACES * staff_spacing)
    beamed_max_stem_length = max(max_stem_length, _STANDARD_BEAMED_STEM_MAX_SPACES * staff_spacing)
    # On chord stems, the stem tip should clearly exceed the opposite outer
    # notehead by at least one staff-space for readability.
    outer_note_extension = max(
        2.0,
        _STANDARD_STEM_OUTER_EXTENSION_SPACES * staff_spacing,
    )
    middle_line_y = stem_top_y + 3.0 * staff_spacing

    # ---- Pre-process: unify stem direction per beam group ----
    # When a single-voice arpeggio crosses the staff middle line, individual
    # notes receive different per-note directions (up/down).  The beam-grouping
    # loop below processes each direction separately, which fragments what
    # should be a single beam group.  Fix: compute ONE direction per beam group
    # and override the per-note directions before any stem construction.
    #
    # Polyphonic staves are excluded: they have opposite directions at the SAME
    # onset (voice 0 → up, voice 1 → down), which must be preserved.
    _dir_middle_y = stem_top_y + 4.0 * staff_spacing  # true staff middle (B4 line)
    _onset_dirs: dict[float, set[str]] = {}
    for _x, _on, _dur, _ny, _d in events:
        _onset_dirs.setdefault(round(_on, 6), set()).add(_d)
    _all_dirs = {d for ds in _onset_dirs.values() for d in ds}
    _has_mixed = len(_all_dirs) > 1
    _is_poly = any(len(ds) > 1 for ds in _onset_dirs.values())

    if _has_mixed and not _is_poly:
        # Direction-neutral collapse: one entry per onset.
        _neutral: dict[float, tuple[float, float, list[float]]] = {}
        for x, on, dur, ny, _d in events:
            ok = round(on, 6)
            if ok in _neutral:
                px, pd, ys = _neutral[ok]
                ys.append(ny)
                _neutral[ok] = (min(px, x), min(pd, dur), ys)
            else:
                _neutral[ok] = (x, dur, [ny])

        _beamable = sorted(
            [(x, ok, dur) for ok, (x, dur, _ys) in _neutral.items()
             if _base_duration(dur) < 1.0],
            key=lambda t: t[1],
        )
        _prelim = (
            _beam_groups(
                _beamable,
                beats_per_measure=beats_per_measure,
                measure_number=measure_number,
                time_denominator=time_denominator,
            )
            if len(_beamable) >= 2
            else []
        )

        _grp_dir: dict[float, str] = {}
        for _pg in _prelim:
            _gon = {round(on, 6) for _gx, on, _gd in _pg}
            _all_ys: list[float] = []
            for ok in _gon:
                if ok in _neutral:
                    _all_ys.extend(_neutral[ok][2])
            _unified = _stem_direction_for_cluster(
                _all_ys, voice_number=0, middle_line_y=_dir_middle_y,
            )
            for ok in _gon:
                _grp_dir[ok] = _unified

        events = [
            (x, on, dur, ny, _grp_dir.get(round(on, 6), d))
            for x, on, dur, ny, d in events
        ]
    # ---- End pre-process ----

    extents_by_key: dict[tuple[float, str], tuple[float, float]] = {}
    count_by_key: dict[tuple[float, str], int] = {}
    for _x, onset, _duration, note_y, direction in events:
        key = (round(onset, 6), direction)
        count_by_key[key] = count_by_key.get(key, 0) + 1
        if key in extents_by_key:
            min_y, max_y = extents_by_key[key]
            extents_by_key[key] = (min(min_y, note_y), max(max_y, note_y))
        else:
            extents_by_key[key] = (note_y, note_y)
    collapsed_events = _collapse_standard_rhythm_events(events)
    up_note_ys = [
        note_y
        for _x, _onset, _duration, note_y, direction in collapsed_events
        if direction == "up"
    ]
    down_note_ys = [
        note_y
        for _x, _onset, _duration, note_y, direction in collapsed_events
        if direction == "down"
    ]
    anchor_up_target = min((y - 22.0 for y in up_note_ys), default=stem_top_y)
    anchor_down_target = max((y + 22.0 for y in down_note_ys), default=stem_bottom_y)
    anchor_up = min(stem_top_y, max(anchor_up_target, stem_top_y))
    anchor_down = max(stem_bottom_y, min(anchor_down_target, stem_bottom_y))
    for x, onset, duration, note_y, stem_direction in sorted(
        collapsed_events, key=lambda item: (item[1], item[0])
    ):
        _tup = (tuplet_by_onset or {}).get(round(onset, 6))
        _ndur = _notated_duration(
            duration, _tup[0] if _tup else None, _tup[1] if _tup else None
        )
        base_dur = _base_duration(_ndur)
        if base_dur >= 4.0:
            continue
        stem_x = _stem_x_for_notehead(
            x, direction=stem_direction, stem_offset=stem_offset
        )
        onset_key = round(onset, 6)
        key = (onset_key, stem_direction)
        chord_size = count_by_key.get(key, 1)
        min_y, max_y = extents_by_key.get(key, (note_y, note_y))
        if stem_direction == "down":
            stem_y0 = note_y + 3.0
            # For chords the stem MUST reach past the outermost (lowest) notehead.
            chord_reach = (max_y + outer_note_extension) - stem_y0
            required_len = max(stem_length, chord_reach)
            if chord_size > 1 and base_dur >= 1.0:
                required_len = max(required_len, middle_line_y - stem_y0)
            max_allowed = max(0.0, stem_bottom_y - stem_y0)
            if chord_size > 1:
                # Chord stems may extend beyond the staff boundary to connect all notes.
                max_cap = max(max_stem_length, chord_reach)
                current_len = min(required_len, max_cap)
                current_len = max(current_len, chord_reach)  # Always reach outermost note
            else:
                max_cap = max_stem_length
                current_len = min(required_len, max_cap)
                if max_allowed > 0.0:
                    current_len = min(current_len, max_allowed)
            if current_len <= 0.0:
                continue
            # For single notes below the staff boundary, let the stem go freely
            # from the notehead (downward) rather than being clipped to an inverted
            # result.  The 2-space boundary is a soft guideline, not a hard cap.
            if chord_size > 1 or stem_y0 >= stem_bottom_y:
                stem_y1 = stem_y0 + current_len
            else:
                stem_y1 = min(stem_bottom_y, stem_y0 + current_len)
            # Hard cap: stems must never enter the TAB area (when displayed).
            if tab_y is not None:
                tab_clearance = 4.0
                stem_y1 = min(stem_y1, tab_y - tab_clearance)
        else:
            stem_y0 = note_y - 3.0
            # For chords the stem MUST reach past the outermost (highest) notehead.
            chord_reach = stem_y0 - (min_y - outer_note_extension)
            required_len = max(stem_length, chord_reach)
            if chord_size > 1 and base_dur >= 1.0:
                required_len = max(required_len, stem_y0 - middle_line_y)
            max_allowed = max(0.0, stem_y0 - stem_top_y)
            if chord_size > 1:
                # Chord stems may extend beyond the staff boundary to connect all notes.
                max_cap = max(max_stem_length, chord_reach)
                current_len = min(required_len, max_cap)
                current_len = max(current_len, chord_reach)  # Always reach outermost note
            else:
                max_cap = max_stem_length
                current_len = min(required_len, max_cap)
                if max_allowed > 0.0:
                    current_len = min(current_len, max_allowed)
            if current_len <= 0.0:
                continue
            # For single notes above the staff boundary, let the stem go freely
            # from the notehead (upward) rather than being clipped to an inverted
            # result.  The 2-space boundary is a soft guideline, not a hard cap.
            if chord_size > 1 or stem_y0 <= stem_top_y:
                stem_y1 = stem_y0 - current_len
            else:
                stem_y1 = max(stem_top_y, stem_y0 - current_len)
        # Direction sanity: discard inverted stems (notehead beyond the staff boundary).
        if stem_direction == "down" and stem_y1 <= stem_y0:
            continue
        if stem_direction == "up" and stem_y1 >= stem_y0:
            continue
        if abs(stem_y1 - stem_y0) <= 0.1:
            continue
        stem_entries.append(
            {
                "x": stem_x,
                "onset": onset,
                "duration": duration,
                "direction": stem_direction,
                "note_y": note_y,
                "y0": stem_y0,
                "y1": stem_y1,
                "flag_count": _flag_count(_ndur) if base_dur < 1.0 else 0,
            }
        )

    beamed_keys: set[tuple[float, str]] = set()
    for direction in ("up", "down"):
        directional_short = [
            entry
            for entry in stem_entries
            if str(entry["direction"]) == direction and int(entry["flag_count"]) > 0
        ]
        beam_groups = _beam_groups(
            [
                (float(entry["x"]), float(entry["onset"]), float(entry["duration"]))
                for entry in directional_short
            ],
            beats_per_measure=beats_per_measure,
            measure_number=measure_number,
            time_denominator=time_denominator,
        )
        flag_by_onset: dict[float, int] = {
            round(float(entry["onset"]), 6): int(entry["flag_count"])
            for entry in directional_short
        }
        short_by_onset: dict[float, dict[str, float | int | str]] = {
            round(float(entry["onset"]), 6): entry for entry in directional_short
        }
        for group in beam_groups:
            group_entries = [
                short_by_onset[round(onset, 6)]
                for _x, onset, _duration in group
                if round(onset, 6) in short_by_onset
            ]
            if len(group_entries) < 2:
                continue
            # Recursively resolve into sub-groups if the beam would cross through
            # intermediate chord noteheads; otherwise yield the group as-is.
            resolved_groups = _resolve_beam_crossing(
                group,
                group_entries,
                direction=direction,
                anchor_up=anchor_up,
                anchor_down=anchor_down,
                stem_length=beamed_stem_length,
                max_stem_length=beamed_max_stem_length,
            )
            for resolved_group_stems, resolved_entries in resolved_groups:
                _draw_single_beam_group(
                    layer,
                    group=resolved_group_stems,
                    group_entries=resolved_entries,
                    direction=direction,
                    anchor_up=anchor_up,
                    anchor_down=anchor_down,
                    stem_length=beamed_stem_length,
                    max_stem_length=beamed_max_stem_length,
                    flag_by_onset=flag_by_onset,
                    beamed_keys=beamed_keys,
                )
                if tuplet_by_onset:
                    _bracket_y = (
                        anchor_up - 6.0 if direction == "up" else anchor_down + 8.0
                    )
                    for _bx0, _bx1, _bta in _tuplet_bracket_runs(
                        resolved_group_stems, tuplet_by_onset
                    ):
                        layer.recipe_instances.append(
                            RecipeInstance(
                                recipe_id="tuplet_bracket",
                                params={
                                    "x0": _bx0,
                                    "x1": _bx1,
                                    "y": _bracket_y,
                                    "number": _bta,
                                    "direction": direction,
                                    "style": "standard",
                                },
                                metadata={"direction": direction, "style": "standard"},
                            )
                        )

    for entry in stem_entries:
        onset = float(entry["onset"])
        duration = float(entry["duration"])
        stem_direction = str(entry["direction"])
        layer.recipe_instances.append(
            RecipeInstance(
                recipe_id="stem_line",
                params={
                    "x": float(entry["x"]),
                    "y0": float(entry["y0"]),
                    "y1": float(entry["y1"]),
                    "width": 0.8,
                },
                metadata={
                    "onset": onset,
                    "duration": duration,
                    "direction": stem_direction,
                },
            )
        )

    for entry in stem_entries:
        onset_key = round(float(entry["onset"]), 6)
        stem_direction = str(entry["direction"])
        flag_count = int(entry["flag_count"])
        if (onset_key, stem_direction) in beamed_keys or flag_count <= 0:
            continue
        layer.recipe_instances.append(
            RecipeInstance(
                recipe_id="flag_stack",
                params={
                    "x": float(entry["x"]),
                    "y": float(entry["y1"]),
                    "count": flag_count,
                    "spacing": _FLAG_STACK_SPACING,
                    "direction": stem_direction,
                    "width": 0.75,
                },
                metadata={"onset": float(entry["onset"]), "direction": stem_direction},
            )
        )


def _append_tablature_rhythm(
    layer: LayerGroup,
    *,
    measure_number: int,
    beats_per_measure: int,
    time_denominator: int = 4,
    events: list[tuple[float, float, float, float]],
    tab_rhythm_beam_y: float,
    tuplet_by_onset: dict[float, tuple[int, int]] | None = None,
) -> None:
    short_stems: list[tuple[float, float, float, int]] = []
    collapsed_events = _collapse_tablature_rhythm_events(events)
    for x, onset, duration, note_y in sorted(collapsed_events, key=lambda item: (item[1], item[0])):
        _tup = (tuplet_by_onset or {}).get(round(onset, 6))
        _ndur = _notated_duration(
            duration, _tup[0] if _tup else None, _tup[1] if _tup else None
        )
        base_dur = _base_duration(_ndur)
        if base_dur >= 4.0:
            continue
        layer.recipe_instances.append(
            RecipeInstance(
                recipe_id="stem_line",
                params={
                    "x": x,
                    "y0": tab_rhythm_beam_y - 11.0,
                    "y1": tab_rhythm_beam_y,
                    "width": _TAB_RHYTHM_STEM_WIDTH,
                    "direction": "down",
                },
                metadata={
                    "onset": onset,
                    "duration": duration,
                    "direction": "down",
                    "plane": "tablature_rhythm",
                },
            )
        )
        if base_dur < 1.0:
            short_stems.append((x, onset, duration, _flag_count(_ndur)))
        # Augmentation dot: emit a small filled circle to the right of the stem
        # for dotted durations (e.g. dotted 8th = 0.75 beats).
        _dots = _dot_count(_ndur)
        if _dots > 0:
            _dot_r = 1.1
            for _di in range(_dots):
                _dot_cx = x + 3.5 + _di * 3.0
                layer.recipe_instances.append(
                    RecipeInstance(
                        recipe_id="filled_circle",
                        params={
                            "cx": _dot_cx,
                            "cy": tab_rhythm_beam_y + 4.5,
                            "r": _dot_r,
                        },
                        metadata={"plane": "tablature_rhythm", "kind": "augmentation_dot"},
                    )
                )

    beamed_onsets: set[float] = set()
    beam_groups = _beam_groups(
        [(x, onset, duration) for x, onset, duration, _flags in short_stems],
        beats_per_measure=beats_per_measure,
        measure_number=measure_number,
        time_denominator=time_denominator,
    )
    flag_by_onset: dict[float, int] = {
        onset: flags for _x, onset, _duration, flags in short_stems
    }
    for group in beam_groups:
        for _x, onset, _duration in group:
            beamed_onsets.add(onset)
        layer.recipe_instances.append(
            RecipeInstance(
                recipe_id="beam_group",
                params={
                    "x0": group[0][0],
                    "x1": group[-1][0],
                    "y": tab_rhythm_beam_y,
                    "level": 1,
                    "thickness": _TAB_RHYTHM_BEAM_THICKNESS,
                    "gap": _TAB_RHYTHM_BEAM_GAP,
                    # TAB+Rhythm: stems go down from the staff to the beam line.
                    # Secondary beams must stack *toward* the staff (upward = smaller y).
                    # "down" → sign=-1 → offset negative → beams above primary beam.
                    "direction": "down",
                },
                metadata={"plane": "tablature_rhythm"},
            )
        )
        for level, x0, x1 in _secondary_beam_segments(group, flag_by_onset=flag_by_onset):
            layer.recipe_instances.append(
                RecipeInstance(
                    recipe_id="beam_group",
                    params={
                        "x0": x0,
                        "x1": x1,
                        "y": tab_rhythm_beam_y,
                        "level": level,
                        "thickness": _TAB_RHYTHM_BEAM_THICKNESS,
                        "gap": _TAB_RHYTHM_BEAM_GAP,
                        "direction": "down",
                    },
                    metadata={"plane": "tablature_rhythm"},
                )
            )
        if tuplet_by_onset:
            for _tbx0, _tbx1, _tbta in _tuplet_bracket_runs(group, tuplet_by_onset):
                layer.recipe_instances.append(
                    RecipeInstance(
                        recipe_id="tuplet_bracket",
                        params={
                            "x0": _tbx0,
                            "x1": _tbx1,
                            "y": tab_rhythm_beam_y + 8.0,
                            "number": _tbta,
                            "direction": "down",
                            "style": "tablature_rhythm",
                        },
                        metadata={"plane": "tablature_rhythm", "style": "tablature_rhythm"},
                    )
                )

    # Emit brackets for tuplet notes not covered by beam groups (e.g. triplet quarter
    # notes: notated dur == 1.0, so they don't enter short_stems and never get beamed).
    if tuplet_by_onset:
        unbeamed_tuplet = [
            (x, onset, dur)
            for x, onset, dur, _note_y in sorted(collapsed_events, key=lambda e: e[1])
            if (tuplet_by_onset or {}).get(round(onset, 6)) is not None
            and onset not in beamed_onsets
        ]
        _emit_standalone_tuplet_brackets(layer, unbeamed_tuplet, tuplet_by_onset, tab_rhythm_beam_y)

    for x, onset, _duration, flag_count in short_stems:
        if onset in beamed_onsets or flag_count <= 0:
            continue
        layer.recipe_instances.append(
            RecipeInstance(
                recipe_id="flag_stack",
                params={
                    "x": x,
                    "y": tab_rhythm_beam_y,
                    "count": flag_count,
                    "spacing": _TAB_RHYTHM_FLAG_SPACING,
                    "direction": "up",
                    "width": 0.95,
                },
                metadata={"onset": onset, "direction": "up", "plane": "tablature_rhythm"},
            )
        )


def _collapse_standard_rhythm_events(
    events: list[tuple[float, float, float, float, str]],
) -> list[tuple[float, float, float, float, str]]:
    by_onset_direction: dict[tuple[float, str], list[tuple[float, float, float, float, str]]] = {}
    for event in events:
        x, onset, _duration, _note_y, stem_direction = event
        by_onset_direction.setdefault((round(onset, 6), stem_direction), []).append(event)

    collapsed: list[tuple[float, float, float, float, str]] = []
    for onset_key, direction in sorted(by_onset_direction.keys(), key=lambda key: (key[0], key[1])):
        group = by_onset_direction[(onset_key, direction)]
        # Displaced noteheads (2nd-interval collision avoidance) are shifted AWAY from
        # the stem: right for up-stem (+), left for down-stem (-).  The stem must be
        # anchored to the UN-displaced (canonical) notehead position, which is the
        # minimum x for up-stem chords and the maximum x for down-stem chords.
        x = min(item[0] for item in group) if direction == "up" else max(item[0] for item in group)
        onset = group[0][1]
        duration = min(item[2] for item in group)
        if direction == "down":
            note_y = min(item[3] for item in group)
        else:
            note_y = max(item[3] for item in group)
        collapsed.append((x, onset, duration, note_y, direction))
    return collapsed


def _collapse_tablature_rhythm_events(
    events: list[tuple[float, float, float, float]],
) -> list[tuple[float, float, float, float]]:
    by_onset: dict[float, list[tuple[float, float, float, float]]] = {}
    for event in events:
        _x, onset, _duration, _note_y = event
        by_onset.setdefault(round(onset, 6), []).append(event)

    collapsed: list[tuple[float, float, float, float]] = []
    for onset_key in sorted(by_onset.keys()):
        group = by_onset[onset_key]
        x = sum(item[0] for item in group) / len(group)
        onset = group[0][1]
        # Prefer the longest duration at this onset: this matches the primary voice's
        # rhythm (voice 0 typically plays the main chord/melody) rather than picking
        # up a short secondary-voice note as the representative rhythm.
        duration = max(item[2] for item in group)
        note_y = min(item[3] for item in group)
        collapsed.append((x, onset, duration, note_y))
    return collapsed


def _resolve_beam_crossing(
    group: list[tuple[float, float, float]],
    group_entries: list[dict[str, float | int | str]],
    *,
    direction: str,
    anchor_up: float,
    anchor_down: float,
    stem_length: float,
    max_stem_length: float,
    _depth: int = 0,
) -> list[tuple[list[tuple[float, float, float]], list[dict[str, float | int | str]]]]:
    """Recursively split a beam group at any position where the beam bar would
    physically cross through an intermediate chord's noteheads.

    Guitar Pro's engraving rule: when a diagonal beam cannot be drawn without
    passing through a chord, the group is split into two sub-groups at that
    chord, each drawn with its own (shorter, cleaner) beam.

    Returns a flat list of (group_stems, group_entries) pairs, each safe to draw.
    """
    _MAX_SPLIT_DEPTH = 8
    if len(group_entries) < 2 or _depth >= _MAX_SPLIT_DEPTH:
        return [(group, group_entries)]

    line_y0, line_y1 = _beam_line_for_group(
        group_entries,
        direction=direction,
        stem_top_y=anchor_up,
        stem_bottom_y=anchor_down,
        min_stem_length=stem_length,
        max_stem_length=max_stem_length,
    )
    group_x0 = float(group[0][0])
    group_x1 = float(group[-1][0])

    # Find the first *interior* entry where the beam would sit inside the chord
    # extent rather than beyond it. Never split on the first/last stem; doing
    # so can discard valid 2-note groups entirely.
    split_idx: int | None = None
    for i, entry in enumerate(group_entries):
        entry_x = float(entry["x"])
        beam_y = _beam_y_at_x(entry_x, x0=group_x0, x1=group_x1, y0=line_y0, y1=line_y1)
        chord_tip_y = float(entry["y1"])  # pre-computed chord-aware stem tip
        is_interior = 0 < i < (len(group_entries) - 1)
        if direction == "down" and beam_y < chord_tip_y - 1.0 and is_interior:
            split_idx = i
            break
        if direction == "up" and beam_y > chord_tip_y + 1.0 and is_interior:
            split_idx = i
            break

    if split_idx is None:
        return [(group, group_entries)]

    # Split at split_idx: left = [0 .. split_idx-1], right = [split_idx .. end]
    left_entries = group_entries[:split_idx]
    right_entries = group_entries[split_idx:]
    left_group = [(float(e["x"]), float(e["onset"]), float(e["duration"])) for e in left_entries]
    right_group = [(float(e["x"]), float(e["onset"]), float(e["duration"])) for e in right_entries]

    result: list[tuple[list[tuple[float, float, float]], list[dict[str, float | int | str]]]] = []
    if len(left_entries) >= 2:
        result.extend(
            _resolve_beam_crossing(
                left_group, left_entries,
                direction=direction, anchor_up=anchor_up, anchor_down=anchor_down,
                stem_length=stem_length, max_stem_length=max_stem_length,
                _depth=_depth + 1,
            )
        )
    if len(right_entries) >= 2:
        result.extend(
            _resolve_beam_crossing(
                right_group, right_entries,
                direction=direction, anchor_up=anchor_up, anchor_down=anchor_down,
                stem_length=stem_length, max_stem_length=max_stem_length,
                _depth=_depth + 1,
            )
        )
    return result


def _draw_single_beam_group(
    layer: LayerGroup,
    group: list[tuple[float, float, float]],
    group_entries: list[dict[str, float | int | str]],
    *,
    direction: str,
    anchor_up: float,
    anchor_down: float,
    stem_length: float,
    max_stem_length: float,
    flag_by_onset: dict[float, int],
    beamed_keys: set[tuple[float, str]],
) -> None:
    """Compute the final beam line for a group and emit beam + stem updates."""
    if len(group_entries) < 2:
        return
    line_y0, line_y1 = _beam_line_for_group(
        group_entries,
        direction=direction,
        stem_top_y=anchor_up,
        stem_bottom_y=anchor_down,
        min_stem_length=stem_length,
        max_stem_length=max_stem_length,
    )
    group_x0 = float(group[0][0])
    group_x1 = float(group[-1][0])
    for entry in group_entries:
        onset_key = round(float(entry["onset"]), 6)
        beamed_keys.add((onset_key, direction))
        entry_x = float(entry["x"])
        target_y1 = _beam_y_at_x(
            entry_x,
            x0=group_x0,
            x1=group_x1,
            y0=line_y0,
            y1=line_y1,
        )
        notehead_y = float(entry["y0"])
        if direction == "down" and target_y1 > notehead_y:
            entry["y1"] = target_y1
        elif direction == "up" and target_y1 < notehead_y:
            entry["y1"] = target_y1
    layer.recipe_instances.append(
        RecipeInstance(
            recipe_id="beam_group",
            params={
                "x0": group_x0,
                "x1": group_x1,
                "y0": line_y0,
                "y1": line_y1,
                "level": 1,
                "thickness": 2.5,
                "gap": _BEAM_GAP,
                "direction": direction,
            },
        )
    )
    for level, x0, x1 in _secondary_beam_segments(group, flag_by_onset=flag_by_onset):
        seg_y0 = _beam_y_at_x(x0, x0=group_x0, x1=group_x1, y0=line_y0, y1=line_y1)
        seg_y1 = _beam_y_at_x(x1, x0=group_x0, x1=group_x1, y0=line_y0, y1=line_y1)
        layer.recipe_instances.append(
            RecipeInstance(
                recipe_id="beam_group",
                params={
                    "x0": x0,
                    "x1": x1,
                    "y0": seg_y0,
                    "y1": seg_y1,
                    "level": level,
                    "thickness": 2.5,
                    "gap": _BEAM_GAP,
                    "direction": direction,
                },
            )
        )


def _beam_anchor_y(
    direction: str,
    *,
    stem_top_y: float,
    stem_bottom_y: float,
) -> float:
    return stem_bottom_y if direction == "down" else stem_top_y


def _beam_line_for_group(
    group_entries: list[dict[str, float | int | str]],
    *,
    direction: str,
    stem_top_y: float,
    stem_bottom_y: float,
    min_stem_length: float,
    max_stem_length: float,
) -> tuple[float, float]:
    if len(group_entries) < 2:
        fallback = _beam_anchor_y(
            direction,
            stem_top_y=stem_top_y,
            stem_bottom_y=stem_bottom_y,
        )
        return fallback, fallback

    x0 = float(group_entries[0]["x"])
    x1 = float(group_entries[-1]["x"])
    span = max(1.0, x1 - x0)
    y0 = float(group_entries[0]["y1"])
    y1 = float(group_entries[-1]["y1"])

    slope = (y1 - y0) / span
    slope = max(-_MAX_BEAM_SLOPE, min(_MAX_BEAM_SLOPE, slope))
    y1 = y0 + slope * span
    beam_delta = y1 - y0
    if abs(beam_delta) > _MAX_BEAM_VERTICAL_DELTA:
        y1 = y0 + (_MAX_BEAM_VERTICAL_DELTA if beam_delta > 0 else -_MAX_BEAM_VERTICAL_DELTA)

    low_shift = float("-inf")
    high_shift = float("inf")
    for entry in group_entries:
        note_side_y = float(entry["y0"])  # stem origin (top for down, bottom for up)
        stem_extent_y = float(entry["y1"])  # pre-computed chord-aware stem tip
        beam_y = _beam_y_at_x(
            float(entry["x"]),
            x0=x0,
            x1=x1,
            y0=y0,
            y1=y1,
        )
        if direction == "down":
            # Beam must clear the ENTIRE chord extent (entry["y1"]), not just
            # stem_y0 + min_stem_length; the chord's lowest note may be much
            # further below the topmost notehead.
            required_y = max(note_side_y + min_stem_length, stem_extent_y)
            low_shift = max(low_shift, required_y - beam_y)
            high_shift = min(high_shift, note_side_y + max_stem_length - beam_y)
        else:
            # Symmetric for up-stems: beam must be above the topmost chord note.
            required_y = min(note_side_y - min_stem_length, stem_extent_y)
            low_shift = max(low_shift, note_side_y - max_stem_length - beam_y)
            high_shift = min(high_shift, required_y - beam_y)

    if low_shift <= high_shift:
        shift = min(max(0.0, low_shift), high_shift)
    else:
        shift = (low_shift + high_shift) / 2.0
    y0 += shift
    y1 += shift
    # Hard-clamp: beam must NOT exceed 2 staff-spaces above/below the staff.
    # stem_top_y and stem_bottom_y already encode that limit.
    if direction == "down":
        y0 = min(y0, stem_bottom_y)
        y1 = min(y1, stem_bottom_y)
    else:
        y0 = max(y0, stem_top_y)
        y1 = max(y1, stem_top_y)
    return y0, y1


def _beam_y_at_x(
    x: float,
    *,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
) -> float:
    if abs(x1 - x0) <= 1e-6:
        return y0
    t = (x - x0) / (x1 - x0)
    return y0 + (y1 - y0) * t


def _stem_direction_for_note(
    *,
    note_y: float,
    voice_number: int,
    staff_std_y: float,
    staff_spacing: float,
) -> str:
    if voice_number >= 1:
        return "down"
    middle_line_y = staff_std_y + 2.0 * staff_spacing
    return "down" if note_y <= middle_line_y else "up"


def _stem_direction_for_cluster(
    note_ys: list[float],
    *,
    voice_number: int,
    middle_line_y: float,
) -> str:
    if voice_number >= 1:
        return "down"
    if not note_ys:
        return "up"
    highest = min(note_ys)
    lowest = max(note_ys)

    # Entire cluster above or below the middle line.
    if lowest < middle_line_y:
        return "down"
    if highest > middle_line_y:
        return "up"

    # Cluster spans the middle line: choose direction from the outermost note.
    above_distance = max(0.0, middle_line_y - highest)
    below_distance = max(0.0, lowest - middle_line_y)
    if above_distance > below_distance:
        return "down"
    if below_distance > above_distance:
        return "up"
    center = (highest + lowest) / 2.0
    return "down" if center <= middle_line_y else "up"


def _append_standard_connections(
    layer: LayerGroup,
    events: list[dict[str, object]],
) -> None:
    """Draw tie and slur arcs between connected notes.

    Tie arcs are drawn only for notes explicitly marked ``is_tie_dest=True``
    (set by the parser).  For each tie-destination note the nearest preceding
    note with the same pitch at a contiguous onset is located and an arc is
    drawn.  This avoids false ties between identical-pitch notes that just
    happen to follow each other in a repeating chord pattern.

    Slur arcs (hammer-on / pull-off / slide) are detected as before from the
    technique flag on the preceding note.
    """
    if len(events) < 2:
        return

    by_voice: dict[int, list[dict[str, object]]] = {}
    for event in events:
        voice_number = _safe_int(event.get("voice_number")) or 0
        by_voice.setdefault(voice_number, []).append(event)

    for voice_number, voice_events in by_voice.items():
        ordered = sorted(
            voice_events,
            key=lambda item: (float(item.get("onset", 0.0)), str(item.get("event_id", ""))),
        )

        # ── Tie arcs ────────────────────────────────────────────────────────
        # Only draw a tie when the destination note is explicitly flagged.
        # Search backwards for the nearest same-pitch note at contiguous onset.
        for curr in ordered:
            if not curr.get("is_tie_dest"):
                continue
            curr_onset = float(curr.get("onset", 0.0))
            curr_pitch = int(curr.get("pitch", 64))
            prev: dict[str, object] | None = None
            for candidate in reversed(ordered):
                if float(candidate.get("onset", 0.0)) >= curr_onset:
                    continue
                cand_end = float(candidate.get("onset", 0.0)) + float(candidate.get("duration", 0.0))
                if abs(cand_end - curr_onset) > _ARC_ONSET_TOLERANCE:
                    continue
                if int(candidate.get("pitch", 64)) == curr_pitch:
                    prev = candidate
                    break
            if prev is None:
                continue

            stem_direction = str(curr.get("stem_direction", _stem_direction(voice_number)))
            arc_x0 = float(prev.get("x", 0.0)) + 3.0
            arc_x1 = float(curr.get("x", 0.0)) - 3.0
            if arc_x1 <= arc_x0 + 1.0:
                # Cross-system tie — cannot draw a single arc that wraps
                continue
            arc_y_offset, arc_curvature = _arc_profile(
                x0=arc_x0,
                x1=arc_x1,
                stem_direction=stem_direction,
                voice_number=voice_number,
                is_slur=False,
            )
            arc_y0 = float(prev.get("y", 0.0)) + arc_y_offset
            arc_y1 = float(curr.get("y", 0.0)) + arc_y_offset
            layer.recipe_instances.append(
                RecipeInstance(
                    recipe_id="tie_arc",
                    params={
                        "x0": arc_x0,
                        "y0": arc_y0,
                        "x1": arc_x1,
                        "y1": arc_y1,
                        "curvature": arc_curvature,
                    },
                    metadata={
                        "start_event_id": str(prev.get("event_id")),
                        "end_event_id": str(curr.get("event_id")),
                        "voice_number": str(voice_number),
                    },
                )
            )

        # ── Slur arcs (hammer-on / pull-off / slide) ─────────────────────────
        for prev_s, curr_s in zip(ordered, ordered[1:]):
            prev_onset = float(prev_s.get("onset", 0.0))
            prev_duration = float(prev_s.get("duration", 0.0))
            curr_onset = float(curr_s.get("onset", 0.0))
            if abs(prev_onset + prev_duration - curr_onset) > _ARC_ONSET_TOLERANCE:
                continue
            prev_pitch = int(prev_s.get("pitch", 64))
            curr_pitch = int(curr_s.get("pitch", 64))
            if prev_pitch == curr_pitch:
                continue  # Same-pitch would be a tie, not a slur
            prev_techniques = set(prev_s.get("techniques", set()))
            is_slur = bool(prev_techniques.intersection(_SLUR_TECHNIQUES))
            if not is_slur:
                continue

            stem_direction = str(prev_s.get("stem_direction", _stem_direction(voice_number)))
            arc_x0 = float(prev_s.get("x", 0.0)) + 3.0
            arc_x1 = float(curr_s.get("x", 0.0)) - 3.0
            if arc_x1 <= arc_x0 + 1.0:
                continue
            arc_y_offset, arc_curvature = _arc_profile(
                x0=arc_x0,
                x1=arc_x1,
                stem_direction=stem_direction,
                voice_number=voice_number,
                is_slur=True,
            )
            arc_y0 = float(prev_s.get("y", 0.0)) + arc_y_offset
            arc_y1 = float(curr_s.get("y", 0.0)) + arc_y_offset
            layer.recipe_instances.append(
                RecipeInstance(
                    recipe_id="slur_arc",
                    params={
                        "x0": arc_x0,
                        "y0": arc_y0,
                        "x1": arc_x1,
                        "y1": arc_y1,
                        "curvature": arc_curvature,
                    },
                    metadata={
                        "start_event_id": str(prev_s.get("event_id")),
                        "end_event_id": str(curr_s.get("event_id")),
                        "voice_number": str(voice_number),
                    },
                )
            )
            # H/P label at arc apex
            if "hammer_on" in prev_techniques:
                hp_label = "H"
            elif "pull_off" in prev_techniques:
                hp_label = "P"
            else:
                hp_label = ""
            if hp_label:
                label_x = (arc_x0 + arc_x1) / 2.0
                label_y = max(arc_y0, arc_y1) + arc_curvature - 2.5
                layer.text_instances.append(
                    TextInstance(
                        text=hp_label,
                        x=label_x,
                        y=label_y,
                        font_family="Times-Italic",
                        font_size=7.0,
                        metadata={"kind": "hp_label"},
                    )
                )


def _arc_profile(
    *,
    x0: float,
    x1: float,
    stem_direction: str,
    voice_number: int,
    is_slur: bool,
) -> tuple[float, float]:
    span = max(0.0, x1 - x0)
    side = -1.0 if stem_direction == "down" else 1.0
    offset_base = 4.0 + min(2.5, max(0, voice_number) * 1.5)
    offset_span_boost = min(2.0, span / 64.0)
    y_offset = side * (offset_base + offset_span_boost)

    curve_base = 8.0 + min(4.0, span / 24.0)
    if is_slur:
        curve_base += 1.5
    curvature = side * curve_base
    return y_offset, curvature


def _beam_groups(
    stems: list[tuple[float, float, float]],
    *,
    beats_per_measure: int,
    measure_number: int,
    time_denominator: int = 4,
) -> list[list[tuple[float, float, float]]]:
    """Group consecutive short stems into meter-aware beam groups.

    The fundamental beam break is the quarter-note beat (and any rest gap).
    In simple duple/quadruple meters (e.g. 4/4, 2/4, 2/2) a run made up
    entirely of eighth notes sitting on the eighth-note grid is then beamed
    by the half-note unit (4 eighths per group in 4/4), matching MuseScore's
    default.  Runs that contain a sixteenth (or shorter), a tuplet/off-grid
    onset, or a rest gap keep the per-beat break so secondary beams stay
    readable.

    Args:
        stems: ``(x, onset, duration)`` tuples sorted by onset (durations in
            quarter-note beats).
        beats_per_measure: Time-signature numerator (quarter-beat count).
        measure_number: 1-based measure index (sets the absolute beat origin).
        time_denominator: Time-signature denominator (4 for x/4 meters).

    Returns:
        Beam groups; each is a list of ``(x, onset, duration)`` with ≥ 2 stems.
    """
    if len(stems) < 2:
        return []

    q_beats = beats_per_measure  # already in quarter-note beat units
    measure_onset = max(0.0, (measure_number - 1) * q_beats)

    # First split on the quarter-note beat and on rest gaps, keeping singleton
    # groups so the half-bar merge below can reason about adjacency.
    quarter_groups, gap_before = _quarter_beam_groups(
        stems, measure_onset=measure_onset, beats_per_measure=beats_per_measure
    )
    merged = _merge_eighth_beam_groups(
        quarter_groups,
        gap_before=gap_before,
        measure_onset=measure_onset,
        beats_per_measure=beats_per_measure,
        time_denominator=time_denominator,
    )
    return [group for group in merged if len(group) >= 2]


def _quarter_beam_groups(
    stems: list[tuple[float, float, float]],
    *,
    measure_onset: float,
    beats_per_measure: int,
) -> tuple[list[list[tuple[float, float, float]]], list[bool]]:
    """Split stems at every quarter-beat boundary and rest gap.

    Returns the per-quarter groups (singletons retained) plus a parallel list
    of flags marking whether each group is preceded by a rest gap (which must
    block any later half-bar merge).
    """
    beat_boundaries = frozenset(
        round(measure_onset + k, 9) for k in range(1, beats_per_measure)
    )
    groups: list[list[tuple[float, float, float]]] = []
    gap_before: list[bool] = []
    current: list[tuple[float, float, float]] = []
    for x, onset, duration in stems:
        if not current:
            current.append((x, onset, duration))
            gap_before.append(False)
            continue
        _prev_x, prev_onset, prev_duration = current[-1]
        prev_end = prev_onset + prev_duration
        has_rest_gap = (onset - prev_end) >= _REST_GAP_BREAK
        crosses_beat = any(prev_onset < bb <= onset for bb in beat_boundaries)
        if has_rest_gap or crosses_beat:
            groups.append(current)
            current = [(x, onset, duration)]
            gap_before.append(has_rest_gap)
            continue
        current.append((x, onset, duration))
    if current:
        groups.append(current)
    return groups, gap_before


# Beam-unit (in quarter-note beats) for an all-eighth run in simple meters.
# 4/4 and 2/2-style meters beam eighths by the half note (2 beats); other
# simple meters keep the per-beat unit so the half-bar merge is a no-op.
def _eighth_beam_unit(beats_per_measure: int, time_denominator: int) -> float:
    """Return the quarter-beat span of one eighth-note beam group.

    A value of 1.0 disables the half-bar merge (per-beat grouping); 2.0 beams
    eighths by the half note as in 4/4.
    """
    if time_denominator == 4 and beats_per_measure % 2 == 0 and beats_per_measure >= 4:
        # Simple quadruple (4/4, 8/4, …): half-note beam unit for eighths.
        return 2.0
    if time_denominator == 2:
        # Cut-time family (2/2, 4/2): the notated beat already spans 2 quarters.
        return 2.0
    return 1.0


def _group_is_pure_eighth_on_grid(
    group: list[tuple[float, float, float]], *, measure_onset: float
) -> bool:
    """True if every note is an eighth (1 flag) sitting on the eighth grid.

    Sixteenths (2 flags) force a per-beat break; tuplet / off-beat onsets do
    not land on the 0.5-beat grid and must not be merged across beats.
    """
    for _x, onset, duration in group:
        if _flag_count(duration) != 1:
            return False
        rel = onset - measure_onset
        if abs(round(rel / 0.5) * 0.5 - rel) > 1e-6:
            return False
    return True


def _merge_eighth_beam_groups(
    quarter_groups: list[list[tuple[float, float, float]]],
    *,
    gap_before: list[bool],
    measure_onset: float,
    beats_per_measure: int,
    time_denominator: int,
) -> list[list[tuple[float, float, float]]]:
    """Merge adjacent per-beat groups into half-bar eighth-note beam groups.

    Two consecutive quarter groups merge when they share the same eighth-beam
    unit window, are contiguous (no rest gap between them), and both contain
    only on-grid eighth notes.  This reproduces MuseScore's grouping of four
    eighths per half note in 4/4 while leaving sixteenth/tuplet runs per beat.
    """
    unit = _eighth_beam_unit(beats_per_measure, time_denominator)
    if unit <= 1.0:
        return quarter_groups

    merged: list[list[tuple[float, float, float]]] = []
    for idx, group in enumerate(quarter_groups):
        if not merged:
            merged.append(list(group))
            continue
        prev = merged[-1]
        same_unit = (
            int((group[0][1] - measure_onset) // unit)
            == int((prev[0][1] - measure_onset) // unit)
        )
        contiguous = not gap_before[idx]
        if (
            same_unit
            and contiguous
            and _group_is_pure_eighth_on_grid(prev, measure_onset=measure_onset)
            and _group_is_pure_eighth_on_grid(group, measure_onset=measure_onset)
        ):
            prev.extend(group)
        else:
            merged.append(list(group))
    return merged



def _secondary_beam_segments(
    group: list[tuple[float, float, float]],
    *,
    flag_by_onset: dict[float, int],
) -> list[tuple[int, float, float]]:
    max_level = max((flag_by_onset.get(onset, 0) for _x, onset, _dur in group), default=0)
    if max_level < 2:
        return []

    segments: list[tuple[int, float, float]] = []
    for level in range(2, max_level + 1):
        qualifying: list[int] = [
            idx
            for idx, (_x, onset, _dur) in enumerate(group)
            if flag_by_onset.get(onset, 0) >= level
        ]
        if not qualifying:
            continue

        run: list[int] = []
        for idx in qualifying:
            if run and idx != run[-1] + 1:
                if len(run) >= 2:
                    segments.append((level, group[run[0]][0], group[run[-1]][0]))
                elif len(run) == 1:
                    solo = run[0]
                    if solo == 0 and len(group) > 1:
                        x0 = group[solo][0]
                        x1 = min(group[solo + 1][0] - 0.5, x0 + _SECONDARY_BEAM_HOOK_LEN)
                        if x1 > x0:
                            segments.append((level, x0, x1))
                    elif solo == len(group) - 1 and len(group) > 1:
                        x1 = group[solo][0]
                        x0 = max(group[solo - 1][0] + 0.5, x1 - _SECONDARY_BEAM_HOOK_LEN)
                        if x1 > x0:
                            segments.append((level, x0, x1))
                run = []
            run.append(idx)

        if len(run) >= 2:
            segments.append((level, group[run[0]][0], group[run[-1]][0]))
        elif len(run) == 1:
            solo = run[0]
            if solo == 0 and len(group) > 1:
                x0 = group[solo][0]
                x1 = min(group[solo + 1][0] - 0.5, x0 + _SECONDARY_BEAM_HOOK_LEN)
                if x1 > x0:
                    segments.append((level, x0, x1))
            elif solo == len(group) - 1 and len(group) > 1:
                x1 = group[solo][0]
                x0 = max(group[solo - 1][0] + 0.5, x1 - _SECONDARY_BEAM_HOOK_LEN)
                if x1 > x0:
                    segments.append((level, x0, x1))
    return segments


def _emit_standalone_tuplet_brackets(
    layer: LayerGroup,
    stems: list[tuple[float, float, float]],
    tuplet_by_onset: dict[float, tuple[int, int]],
    beam_y: float,
) -> None:
    """Emit tuplet_bracket recipes for notes not covered by a beam group.

    Groups consecutive notes sharing the same (tuplet_actual, tuplet_normal) ratio
    into visual brackets.  Requires ≥ 2 consecutive same-ratio notes for a bracket.
    Used for triplet quarter notes and other tuplet values whose notated duration is
    a quarter note or longer (base_dur ≥ 1.0), which never enter the short_stems path.
    """
    if not stems or not tuplet_by_onset:
        return

    sorted_stems = sorted(stems, key=lambda s: s[1])  # sort by onset
    run_start: int | None = None
    run_tup: tuple[int, int] | None = None
    results: list[tuple[float, float, int]] = []

    def _flush(end_idx: int) -> None:
        nonlocal run_start, run_tup
        if run_start is not None and end_idx - run_start >= 2:
            results.append((
                sorted_stems[run_start][0],
                sorted_stems[end_idx - 1][0],
                run_tup[0],  # type: ignore[index]
            ))
        run_start = None
        run_tup = None

    for idx, (x, onset, _dur) in enumerate(sorted_stems):
        tup = tuplet_by_onset.get(round(onset, 6))
        if tup is not None:
            if tup == run_tup:
                pass  # extend current run
            else:
                _flush(idx)
                run_start = idx
                run_tup = tup
        else:
            _flush(idx)
    _flush(len(sorted_stems))

    for x0, x1, number in results:
        layer.recipe_instances.append(
            RecipeInstance(
                recipe_id="tuplet_bracket",
                params={
                    "x0": x0,
                    "x1": x1,
                    "y": beam_y + 8.0,
                    "number": number,
                    "direction": "down",
                    "style": "tablature_rhythm",
                },
                metadata={"plane": "tablature_rhythm", "style": "tablature_rhythm"},
            )
        )


def _append_tab_slide_connections(
    layer: LayerGroup,
    events: list[dict[str, object]],
) -> None:
    """Draw diagonal slide lines connecting slide sources to the next note on the same string.

    Receives ALL tab events (slide and non-slide) for the entire staff so that slides at
    the end of a measure connect to the next note even across measure boundaries.
    Groups events by string, then for each slide source draws a diagonal to the next note.
    """
    by_string: dict[int, list[dict[str, object]]] = {}
    for event in events:
        string_num = int(event.get("tab_string", 3))
        by_string.setdefault(string_num, []).append(event)

    for string_num, string_events in by_string.items():
        sorted_events = sorted(string_events, key=lambda e: float(e.get("onset", 0.0)))
        for idx, event in enumerate(sorted_events):
            techs = set(event.get("techniques", set()))
            if "slide" not in techs:
                continue
            if idx + 1 >= len(sorted_events):
                continue
            next_event = sorted_events[idx + 1]
            sl_x0 = float(event.get("x", 0.0)) + 5.0
            sl_x1 = float(next_event.get("x", 0.0)) - 5.0
            sl_y_mid = float(event.get("y", 0.0))
            fret0 = int(event.get("fret_num", 0))
            fret1 = int(next_event.get("fret_num", 0))
            if fret1 > fret0:
                sl_y0, sl_y1 = sl_y_mid + 2.5, sl_y_mid - 2.5
            elif fret1 < fret0:
                sl_y0, sl_y1 = sl_y_mid - 2.5, sl_y_mid + 2.5
            else:
                sl_y0 = sl_y1 = sl_y_mid
            if sl_x1 > sl_x0 + 2.0:
                layer.recipe_instances.append(
                    RecipeInstance(
                        recipe_id="tab_slide_line",
                        params={"x0": sl_x0, "y0": sl_y0, "x1": sl_x1, "y1": sl_y1},
                        metadata={
                            "string": str(string_num),
                            "event_id": str(event.get("event_id")),
                        },
                    )
                )


def _append_tab_technique_spans(
    layer: LayerGroup,
    *,
    measure_x: float,
    measure_width: float,
    events: list[dict[str, object]],
) -> None:
    by_string: dict[int, list[dict[str, object]]] = {}
    for event in events:
        string_num = int(event.get("tab_string", 3))
        by_string.setdefault(string_num, []).append(event)

    for string_num, notes in by_string.items():
        notes_sorted = sorted(notes, key=lambda item: float(item.get("onset", 0.0)))

        # Accumulators for merged span runs: (x0, x1, y)
        pm_runs: list[tuple[float, float, float]] = []
        lr_runs: list[tuple[float, float, float]] = []
        pm_run: tuple[float, float, float] | None = None
        lr_run: tuple[float, float, float] | None = None

        for idx, event in enumerate(notes_sorted):
            techs = set(event.get("techniques", set()))

            # H/P arcs (hammer-on, pull-off, legato)
            hp_tech = techs.intersection({"hammer_on", "pull_off", "legato"})
            if hp_tech and idx + 1 < len(notes_sorted):
                next_event = notes_sorted[idx + 1]
                arc_x0 = float(event.get("x", 0.0)) + 5.0
                arc_x1 = float(next_event.get("x", 0.0)) - 5.0
                arc_y = float(event.get("y", 0.0)) - 3.0
                if arc_x1 > arc_x0 + 2.0:
                    layer.recipe_instances.append(
                        RecipeInstance(
                            recipe_id="slur_arc",
                            params={"x0": arc_x0, "y0": arc_y, "x1": arc_x1, "y1": arc_y,
                                    "curvature": -8.0},
                            metadata={"string": str(string_num),
                                      "event_id": str(event.get("event_id"))},
                        )
                    )
                    if "hammer_on" in hp_tech:
                        tab_hp_label = "H"
                    elif "pull_off" in hp_tech:
                        tab_hp_label = "P"
                    else:
                        tab_hp_label = ""
                    if tab_hp_label:
                        layer.text_instances.append(
                            TextInstance(
                                text=tab_hp_label,
                                x=(arc_x0 + arc_x1) / 2.0,
                                y=arc_y - 8.0 - 2.5,
                                font_family="Times-Italic",
                                font_size=7.0,
                                metadata={"kind": "hp_label"},
                            )
                        )

            # Slide diagonal lines are handled cross-measure by _append_tab_slide_connections.

            x = float(event.get("x", 0.0))
            y = float(event.get("y", 0.0))
            next_x = (
                float(notes_sorted[idx + 1].get("x", x))
                if idx + 1 < len(notes_sorted)
                else measure_x + measure_width - 4.0
            )
            x1_note = min(measure_x + measure_width - 4.0, next_x - _TAB_SPAN_PAD)

            # Accumulate palm_mute runs (merge consecutive into one span)
            if "palm_mute" in techs:
                if pm_run is None:
                    pm_run = (x + _TAB_SPAN_PAD, x1_note, y)
                else:
                    pm_run = (pm_run[0], x1_note, pm_run[2])
            else:
                if pm_run is not None:
                    pm_runs.append(pm_run)
                    pm_run = None

            # Accumulate let_ring runs
            if "let_ring" in techs:
                if lr_run is None:
                    lr_run = (x + _TAB_SPAN_PAD, x1_note, y)
                else:
                    lr_run = (lr_run[0], x1_note, lr_run[2])
            else:
                if lr_run is not None:
                    lr_runs.append(lr_run)
                    lr_run = None

        if pm_run is not None:
            pm_runs.append(pm_run)
        if lr_run is not None:
            lr_runs.append(lr_run)

        for (x0, x1, y) in pm_runs:
            if x1 > x0 + 1.0:
                layer.recipe_instances.append(
                    RecipeInstance(
                        recipe_id="palm_mute_span",
                        params={"x0": x0, "x1": x1, "y": y - 14.0, "label": "P.M.", "dash": "3,2"},
                        metadata={"string": str(string_num)},
                    )
                )

        for (x0, x1, y) in lr_runs:
            if x1 > x0 + 1.0:
                layer.recipe_instances.append(
                    RecipeInstance(
                        recipe_id="let_ring_span",
                        params={"x0": x0, "x1": x1, "y": y - 8.0, "dash": "2,2"},
                        metadata={"string": str(string_num)},
                    )
                )


def _parse_techniques(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def _accidental_column_for_note_y(
    columns_for_onset: list[float],
    note_y: float,
    *,
    min_vertical_gap: float,
) -> int:
    for idx, existing_y in enumerate(columns_for_onset):
        if abs(note_y - existing_y) >= min_vertical_gap:
            columns_for_onset[idx] = note_y
            return idx
    columns_for_onset.append(note_y)
    return len(columns_for_onset) - 1


def _notehead_column_for_note_y(
    columns_for_noteheads: list[float],
    note_y: float,
    *,
    min_vertical_gap: float,
    max_columns: int,
) -> int:
    for idx, existing_y in enumerate(columns_for_noteheads):
        if abs(note_y - existing_y) >= min_vertical_gap:
            columns_for_noteheads[idx] = note_y
            return idx
    if len(columns_for_noteheads) < max(1, max_columns):
        columns_for_noteheads.append(note_y)
        return len(columns_for_noteheads) - 1
    overflow_idx = len(columns_for_noteheads) - 1
    columns_for_noteheads[overflow_idx] = note_y
    return overflow_idx


def _accidental_glyph_for_event(
    metadata: dict[str, str],
    *,
    fallback_pitch: int,
) -> str | None:
    accidental = str(metadata.get("pitch_accidental", "")).strip().lower()
    if accidental == "sharp":
        return "accidental_sharp"
    if accidental == "flat":
        return "accidental_flat"
    if accidental == "natural":
        return "accidental_natural"
    return _accidental_glyph_for_pitch(fallback_pitch)


def _accidental_glyph_for_event_key_aware(
    metadata: dict[str, str],
    *,
    fallback_pitch: int,
    diatonic_step: int,
    key_altered: dict[int, str],
) -> str | None:
    """Determine accidental glyph considering the key signature.

    Uses pitch-class sets for unambiguous MIDI-based key awareness.
    """
    raw_glyph = _accidental_glyph_for_event(metadata, fallback_pitch=fallback_pitch)
    if not key_altered:
        return raw_glyph

    pc = fallback_pitch % 12
    # Determine key direction from key_altered values.
    is_sharp_key = "sharp" in key_altered.values()
    n = len(key_altered)

    if is_sharp_key:
        altered_pcs = set(_KEY_SHARP_PCS[:n])
        natural_pcs = set(_KEY_SHARP_NATURAL_PCS[:n])
        if pc in altered_pcs and raw_glyph == "accidental_sharp":
            return None  # Key already provides this sharp.
        if pc in natural_pcs and raw_glyph is None:
            return "accidental_natural"  # Natural cancels key-sig sharp.
    else:
        altered_pcs = set(_KEY_FLAT_PCS[:n])
        natural_pcs = set(_KEY_FLAT_NATURAL_PCS[:n])
        if pc in altered_pcs and raw_glyph == "accidental_flat":
            return None  # Key already provides this flat.
        if pc in natural_pcs and raw_glyph is None:
            return "accidental_natural"  # Natural cancels key-sig flat.

    return raw_glyph


def _accidental_glyph_for_pitch(pitch: int) -> str | None:
    pitch_class = pitch % 12
    if pitch_class in {1, 6}:
        return "accidental_sharp"
    if pitch_class in {3, 8, 10}:
        return "accidental_flat"
    return None
