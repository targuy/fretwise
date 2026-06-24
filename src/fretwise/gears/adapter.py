"""Convert a SongsGear/Fretwise rig export into the FretWise rig view dict.

Primary formats are ``songsgear.fretwise.rig.v1`` (blocks under ``rig.blocks``,
``musicalVerdict``/``musicalContext`` sidecars) and the compact render-oriented
``songsgear.fretwise.gear.v2``. The older assembled-rig shape (blocks under
``gp180.blocks`` with a ``general`` section) is still accepted so earlier
samples keep working. All map onto the same view dict the web renderer consumes
for ``.md`` sheets — see :func:`song_output_to_view`.
"""

from __future__ import annotations

import re
from typing import Any

from fretwise.rig import (
    GP180_CHAIN,
    _canon_effect,
    _effect_image,
    _find_guitar_image,
    _INACTIVE_VALUES,
)

# Model self-assessed confidence -> FretWise reliability grade. Per the user's
# choice, a model's "high" maps straight to A (the model's own confidence is the
# thing being compared), unlike the deterministic gen_fiche path which caps at B.
_CONFIDENCE_TO_GRADE: dict[str, str] = {
    "high": "A",
    "medium/high": "B",
    "medium": "C",
    "low": "D",
    "unknown": "D",
}

# Canonical display order for common GP-180 settings so the flattened params
# string reads like the hand-written sheets ("Gain 42 · Bass 44 · Middle 66 …").
_SETTINGS_ORDER: tuple[str, ...] = (
    "gain", "bass", "middle", "mid", "treble", "presence", "master", "level",
    "mix", "depth", "rate", "feedback", "decay", "time", "threshold",
    "low", "high", "mic", "lowcuthz", "highcuthz",
)


def _split_camel(key: str) -> str:
    """Turn a settings key into a human label (``lowCutHz`` -> ``Low Cut Hz``)."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(key))
    spaced = spaced.replace("_", " ").strip()
    return " ".join(word[:1].upper() + word[1:] for word in spaced.split())


def _format_settings(settings: Any) -> str | None:
    """Flatten a block ``settings`` object into a ``Label value · …`` string."""
    if not isinstance(settings, dict) or not settings:
        return None
    items = list(settings.items())

    def _rank(item: tuple[str, Any]) -> int:
        try:
            return _SETTINGS_ORDER.index(str(item[0]).lower())
        except ValueError:
            return len(_SETTINGS_ORDER)

    items.sort(key=_rank)
    parts = [f"{_split_camel(key)} {value}" for key, value in items if value not in (None, "")]
    return " · ".join(parts) or None


def _is_inactive(model: str | None, active: Any) -> bool:
    if active is False:
        return True
    value = str(model or "").strip().lower()
    return not value or value in _INACTIVE_VALUES or value.startswith("non ")


def _grade(confidence: Any) -> str | None:
    if confidence in (None, ""):
        return None
    return _CONFIDENCE_TO_GRADE.get(str(confidence).strip().lower(), "D")


def _reglages_from_blocks(blocks: Any) -> dict[str, dict]:
    """Build the 12-slot ``reglages`` chain from a list of schema blocks."""
    reglages: dict[str, dict] = {
        key: {"effect": key, "preset": None, "params": None, "active": False, "image": None}
        for key in GP180_CHAIN
    }
    if not isinstance(blocks, list):
        return reglages
    for block in blocks:
        if not isinstance(block, dict):
            continue
        chain_key = _canon_effect(str(block.get("module") or ""))
        if chain_key not in reglages:
            continue
        model = str(block.get("model") or "").strip()
        if _is_inactive(model, block.get("active")):
            continue
        alternatives = [
            str(alt.get("model") or "").strip()
            for alt in (block.get("alternatives") or [])
            if isinstance(alt, dict) and str(alt.get("model") or "").strip()
        ]
        reglages[chain_key] = {
            "effect": chain_key,
            "preset": model,
            "params": _format_settings(block.get("settings")),
            "active": True,
            "image": _effect_image(model, chain_key),
            "purpose": str(block.get("purpose") or "").strip() or None,
            "match_quality": str(block.get("matchQuality") or "").strip() or None,
            "gap": str(block.get("gap") or "").strip() or None,
            "alternatives": alternatives or None,
        }
    return reglages


def _bullets(label: str, items: Any) -> list[str]:
    out: list[str] = []
    for item in items or []:
        text = str(item or "").strip()
        if text:
            out.append(f"{label}{text}" if label else text)
    return out


def _block_gaps(reglages: dict[str, dict]) -> list[str]:
    gaps: list[str] = []
    for key, reg in reglages.items():
        gap = reg.get("gap")
        if gap:
            gaps.append(f"{key}: {gap}")
    return gaps


def _view_from_v1(doc: dict) -> dict:
    song = doc.get("song") if isinstance(doc.get("song"), dict) else {}
    rig = doc.get("rig") if isinstance(doc.get("rig"), dict) else {}
    verdict = doc.get("musicalVerdict") if isinstance(doc.get("musicalVerdict"), dict) else {}
    context = doc.get("musicalContext") if isinstance(doc.get("musicalContext"), dict) else {}
    improvements = doc.get("improvements") if isinstance(doc.get("improvements"), dict) else {}
    validation = doc.get("validation") if isinstance(doc.get("validation"), dict) else {}

    reglages = _reglages_from_blocks(rig.get("blocks"))
    recommended = str(rig.get("guitar") or "").strip() or None
    research = doc.get("originalGearResearch")
    original = _original_guitar_label(research if isinstance(research, dict) else None)
    tone = str(rig.get("toneProfile") or "").strip()
    target_tone = str(verdict.get("targetTone") or context.get("targetTone") or "").strip()

    notes = "\n".join(
        ([tone] if tone else [])
        + _bullets("À garder : ", verdict.get("mustHave"))
        + _bullets("Indice gear : ", verdict.get("gearClues"))
    ) or None
    limites = "\n".join(
        _bullets("À éviter : ", verdict.get("avoid"))
        + _bullets("Correction : ", verdict.get("corrections"))
        + _bullets("", validation.get("warnings"))
        + _bullets("Erreur : ", validation.get("errors"))
        + _bullets("", _block_gaps(reglages))
    ) or None

    return {
        "artist": song.get("artist"),
        "song": song.get("title"),
        "album": song.get("album") or None,
        "year": song.get("year"),
        "genre": song.get("genre") or context.get("primaryGenre"),
        "fiabilite": _grade(rig.get("confidence")),
        "confidence": rig.get("confidence"),
        "status": rig.get("status"),
        "needs_review": rig.get("needsReview"),
        "accordage": None,
        "capo": None,
        "guitare_originale": original,
        "guitare_originale_image": _find_guitar_image(original),
        "recommended_guitar": recommended,
        "recommended_guitar_image": _find_guitar_image(recommended),
        "signal_chain": str(rig.get("signalChainSummary") or "").strip() or None,
        "chain": GP180_CHAIN,
        "reglages": reglages,
        "notes": notes,
        "limites": limites,
        "comments": target_tone or None,
        "improvements": improvements or None,
        "musical_verdict": verdict or None,
        "musical_context": context or None,
        "validation": validation or None,
        "source": doc.get("source") or None,
        "original_gear_research": research if isinstance(research, dict) else None,
        "is_generated": True,
        "is_gears": True,
    }


def _research_from_v2(doc: dict) -> dict | None:
    credits = doc.get("credits") if isinstance(doc.get("credits"), dict) else {}
    guitar = credits.get("guitar") if isinstance(credits.get("guitar"), dict) else {}
    if not guitar:
        return None
    return {
        "guitarist": guitar.get("guitaristsText") or " / ".join(guitar.get("guitarists") or []),
        "guitar_type": guitar.get("type"),
        "guitar_model": guitar.get("modelsText") or " / ".join(guitar.get("models") or []),
        "confidence": guitar.get("confidence"),
        "evidence_basis": guitar.get("evidence"),
        "notes": guitar.get("notes"),
        "source": guitar.get("source"),
    }


def _view_from_v2(doc: dict) -> dict:
    """Adapter for compact render sheets.

    The compact shape removes generation history but carries the same final
    rendering data. Rehydrate the v1 sidecars and reuse the v1 renderer so the
    web UI gets identical field names.
    """
    song = doc.get("song") if isinstance(doc.get("song"), dict) else {}
    tone = doc.get("tone") if isinstance(doc.get("tone"), dict) else {}
    rig = doc.get("rig") if isinstance(doc.get("rig"), dict) else {}
    audit = doc.get("audit") if isinstance(doc.get("audit"), dict) else {}
    validation = audit.get("validation") if isinstance(audit.get("validation"), dict) else {}

    v1_doc = {
        "schemaVersion": "songsgear.fretwise.rig.v1",
        "song": {
            "artist": song.get("artist"),
            "title": song.get("title"),
            "album": song.get("album"),
            "year": song.get("year"),
            "genre": song.get("genre"),
        },
        "rig": {
            "rigName": rig.get("name"),
            "status": None,
            "confidence": rig.get("confidence") or tone.get("confidence"),
            "needsReview": bool(tone.get("needsReview")),
            "equipment": rig.get("equipment") or {"model": "Valeton GP-180"},
            "guitar": rig.get("recommendedGuitar"),
            "output": rig.get("output"),
            "toneProfile": tone.get("profile"),
            "signalChainSummary": tone.get("summary"),
            "blocks": rig.get("blocks") if isinstance(rig.get("blocks"), list) else [],
        },
        "musicalVerdict": {
            "targetTone": tone.get("target"),
            "mustHave": tone.get("mustHave") or [],
            "avoid": tone.get("avoid") or [],
            "gearClues": tone.get("gearClues") or [],
            "corrections": tone.get("corrections") or [],
            "confidence": tone.get("confidence"),
            "needsManualReview": bool(tone.get("needsReview")),
        },
        "musicalContext": {
            "primaryGenre": song.get("genre"),
            "styleTags": song.get("subgenres") or [],
            "targetTone": tone.get("target"),
            "confidence": song.get("genreConfidence") or tone.get("confidence"),
        },
        "improvements": doc.get("improvements") if isinstance(doc.get("improvements"), dict) else {},
        "validation": validation,
        "source": {key: value for key, value in audit.items() if key != "validation"},
        "originalGearResearch": _research_from_v2(doc),
    }
    return _view_from_v1(v1_doc)


def _best_equipment(general: dict, role_keyword: str) -> str | None:
    for entry in general.get("bestPossibleEquipment") or []:
        if isinstance(entry, dict) and role_keyword.lower() in str(entry.get("role", "")).lower():
            model = str(entry.get("model") or "").strip()
            if model:
                return model
    return None


def _original_guitar_label(research: dict | None) -> str | None:
    """Render an ``originalGearResearch`` block (artist-level gear audit) as a
    single display string, e.g. ``"Gibson SG / Gretsch Jet Firebird (Angus
    Young / Malcolm Young)"``. Returns ``None`` when the audit confidence is
    ``unknown`` or no model/type was resolved.
    """
    if not isinstance(research, dict):
        return None
    if str(research.get("confidence") or "").strip().lower() == "unknown":
        return None
    label = str(research.get("guitar_model") or "").strip() or str(
        research.get("guitar_type") or ""
    ).strip()
    if not label:
        return None
    guitarist = str(research.get("guitarist") or "").strip()
    return f"{label} ({guitarist})" if guitarist else label


def _view_from_legacy(doc: dict) -> dict:
    """Adapter for the older assembled-rig shape (gp180.blocks + general)."""
    song = doc.get("song") if isinstance(doc.get("song"), dict) else {}
    general = doc.get("general") if isinstance(doc.get("general"), dict) else {}
    gp180 = doc.get("gp180") if isinstance(doc.get("gp180"), dict) else {}
    improvements = doc.get("improvements") if isinstance(doc.get("improvements"), dict) else {}

    blocks = gp180.get("blocks")
    if not isinstance(blocks, list):
        blocks = doc.get("blocks") if isinstance(doc.get("blocks"), list) else []
    reglages = _reglages_from_blocks(blocks)

    recommended = str(gp180.get("guitar") or "").strip() or None
    research = doc.get("originalGearResearch")
    research = research if isinstance(research, dict) else None
    original = _original_guitar_label(research) or _best_equipment(general, "guitar")
    notes = "\n".join(
        ([str(general.get("toneProfile") or "").strip()] if general.get("toneProfile") else [])
        + _bullets("- ", general.get("productionNotes"))
    ) or None
    limites = "\n".join(
        _bullets("- ", doc.get("warnings"))
        + _bullets("- (hypothèse) ", doc.get("assumptions"))
    ) or None
    signal_chain = (
        str(general.get("idealSignalChain") or "").strip()
        or str(gp180.get("bestMatchSummary") or "").strip()
        or None
    )
    return {
        "artist": song.get("artist") or doc.get("artist"),
        "song": song.get("title") or doc.get("song"),
        "album": song.get("album") or None,
        "year": song.get("year"),
        "genre": doc.get("genre") or general.get("genre"),
        "fiabilite": _grade(doc.get("confidence")),
        "confidence": doc.get("confidence"),
        "status": doc.get("status"),
        "accordage": doc.get("accordage"),
        "capo": doc.get("capo"),
        "guitare_originale": original,
        "guitare_originale_image": _find_guitar_image(original),
        "recommended_guitar": recommended,
        "recommended_guitar_image": _find_guitar_image(recommended),
        "signal_chain": signal_chain,
        "chain": GP180_CHAIN,
        "reglages": reglages,
        "notes": notes,
        "limites": limites,
        "comments": str(gp180.get("choicePolicy") or "").strip() or None,
        "improvements": improvements or None,
        "sources": doc.get("sources") or None,
        "original_gear_research": research,
        "is_generated": True,
        "is_gears": True,
    }


def song_output_to_view(doc: dict) -> dict:
    """Convert a SongsGear rig export into the FretWise rig view dict.

    Dispatches on shape: ``songsgear.fretwise.rig.v1`` (``rig`` object with
    ``blocks``) uses the v1 mapping; anything else falls back to the legacy
    assembled-rig adapter. The returned dict matches :func:`fretwise.rig.parse_rig`
    output plus gear-research extras (``improvements``, ``musical_verdict``,
    ``musical_context``, ``validation``, ``source``) and ``is_gears=True``.
    """
    if not isinstance(doc, dict):
        doc = {}
    # The SongsGear pipeline wraps the v1 export inside a larger run record under
    # ``fretwiseExport`` (alongside judge/fallback/timing data); unwrap it.
    if isinstance(doc.get("fretwiseExport"), dict):
        doc = doc["fretwiseExport"]
    schema = str(doc.get("schemaVersion") or "")
    rig = doc.get("rig")
    if schema == "songsgear.fretwise.gear.v2":
        return _view_from_v2(doc)
    if schema.startswith("songsgear.fretwise.rig") or (isinstance(rig, dict) and "blocks" in rig):
        return _view_from_v1(doc)
    return _view_from_legacy(doc)
