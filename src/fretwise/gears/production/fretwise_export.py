from __future__ import annotations

from copy import deepcopy
from typing import Any

SCHEMA_VERSION = "songsgear.fretwise.rig.v1"

MODULE_BY_MODEL = {
    "None": None,
    "Gate 1": "NR",
    "Gate 2": "NR",
    "Gate 3": "NR",
    "Comp": "PRE",
    "Boost": "PRE",
    "OD 9": "PRE",
    "Green OD": "PRE",
    "Blues OD": "PRE",
    "V-Wah": "WAH",
    "C-Wah": "WAH",
    "B-Wah": "WAH",
    "T-Wah": "WAH",
    "Red Haze": "DST",
    "Distortion": "DST",
    "Fuzz": "DST",
    "Chief": "DST",
    "RAT-style": "DST",
    "Muff-style": "DST",
    "UK 45": "AMP",
    "UK 50": "AMP",
    "UK SLP": "AMP",
    "UK 800": "AMP",
    "US Deluxe": "AMP",
    "Silver Twin": "AMP",
    "Foxy 30TB": "AMP",
    "AC30 TB": "AMP",
    "Bellman 59N": "AMP",
    "Recti": "AMP",
    "EV 51": "AMP",
    "UK Vintage 4x12": "CAB/IR",
    "UK Basket 4x12": "CAB/IR",
    "UK 30 4x12": "CAB/IR",
    "Foxy 2x12": "CAB/IR",
    "US 2x12": "CAB/IR",
    "Bellman 4x10": "CAB/IR",
    "Mess 4x12": "CAB/IR",
    "User IR 1": "CAB/IR",
    "Guitar EQ 1": "EQ",
    "Guitar EQ 2": "EQ",
    "Chorus": "MOD",
    "O-Phase": "MOD",
    "Tremolo": "MOD",
    "Slapback": "DLY",
    "Digital Delay": "DLY",
    "Tape": "DLY",
    "Room": "RVB",
    "Spring": "RVB",
    "Plate": "RVB",
    "Volume": "VOL",
}

MODEL_ALIASES = {
    "Wah": "V-Wah",
    "Auto Wah": "T-Wah",
    "Auto-wah": "T-Wah",
    "Touch Wah": "T-Wah",
}

MODULE_ALIASES = {
    "CAB": "CAB/IR",
    "CAB / IR": "CAB/IR",
    "IR": "CAB/IR",
    "N->S": "N->S",
    "N→S": "N->S",
}

MATCH_QUALITY_ALIASES = {
    "perfect": "exact",
    "exact": "exact",
    "close": "close",
    "good": "close",
    "acceptable": "acceptable",
    "ok": "acceptable",
    "partial": "acceptable",
    "fallback": "fallback",
}

ALLOWED_MODULES = {
    "NR",
    "PRE",
    "WAH",
    "DST",
    "N->S",
    "AMP",
    "CAB/IR",
    "EQ",
    "MOD",
    "DLY",
    "RVB",
    "VOL",
}
ALLOWED_MATCH_QUALITIES = {"exact", "close", "acceptable", "fallback"}


def build_fretwise_export(record: dict[str, Any]) -> dict[str, Any]:
    rig = _find_rig(record)
    if not rig:
        raise ValueError("Cannot build Fretwise export without generated.Ollama.rig")

    canonical_rig = build_canonical_rig(rig)
    song = normalize_song(record.get("song") or canonical_rig.get("song") or {})
    classification = (
        record.get("genreClassification")
        if isinstance(record.get("genreClassification"), dict)
        else {}
    )
    if not song.get("genre") and classification.get("genre"):
        song["genre"] = str(classification["genre"])
    export = {
        "schemaVersion": SCHEMA_VERSION,
        "exportKind": "rig",
        "song": song,
        "rig": canonical_rig,
        "musicalVerdict": deepcopy(record.get("finalVerdict") or {}),
        "musicalContext": build_musical_context(record, canonical_rig, song),
        "improvements": normalize_improvements(rig.get("improvements") or {}),
        "validation": deepcopy(record.get("validation") or {}),
        "source": build_source(record),
    }
    export["validation"] = validate_fretwise_export(export)
    return export


def normalize_song(value: dict[str, Any]) -> dict[str, Any]:
    song = deepcopy(value) if isinstance(value, dict) else {}
    return {
        "artist": str(song.get("artist") or ""),
        "title": str(song.get("title") or ""),
        "album": str(song.get("album") or ""),
        "year": song.get("year"),
        "genre": str(song.get("genre") or ""),
    }


def build_musical_context(
    record: dict[str, Any], rig: dict[str, Any], song: dict[str, Any]
) -> dict[str, Any]:
    verdict = record.get("finalVerdict") if isinstance(record.get("finalVerdict"), dict) else {}
    classification = (
        record.get("genreClassification")
        if isinstance(record.get("genreClassification"), dict)
        else {}
    )
    target_tone = str(verdict.get("targetTone") or rig.get("toneProfile") or "")
    classifier_tags = (
        classification.get("subgenres") if isinstance(classification.get("subgenres"), list) else []
    )
    tags = [str(tag) for tag in classifier_tags if str(tag).strip()]
    if not tags:
        tags = infer_style_tags(
            [target_tone, *verdict.get("mustHave", []), *verdict.get("gearClues", [])]
        )
    return {
        "primaryGenre": song.get("genre", ""),
        "styleTags": tags,
        "targetTone": target_tone,
        "confidence": str(
            classification.get("confidence")
            or verdict.get("confidence")
            or rig.get("confidence")
            or "unknown"
        ),
    }


def infer_style_tags(values: list[Any]) -> list[str]:
    text = " ".join(str(value) for value in values).lower()
    rules = [
        ("blues", ("blues", "b.b. king", "bb king")),
        ("classic rock", ("classic rock", "70s", "plexi", "marshall", "ac/dc")),
        ("hard rock", ("hard rock", "arena rock", "uk 800")),
        ("metal", ("metal", "recti", "high-gain", "high gain", "thrash")),
        ("punk", ("punk", "downstroke")),
        ("grunge", ("grunge", "alice in chains")),
        ("funk", ("funk", "stax", "muted chops")),
        ("soul", ("soul", "stax")),
        ("indie rock", ("indie", "garage")),
        ("pop rock", ("pop-rock", "pop rock")),
        ("bossa nova", ("bossa", "jobim")),
        ("goth", ("goth", "dubby")),
        ("fusion", ("fusion", "holdsworth")),
    ]
    tags = []
    for tag, needles in rules:
        if any(needle in text for needle in needles):
            tags.append(tag)
    if not tags and text:
        tags.append("unspecified")
    return tags


def build_canonical_rig(rig: dict[str, Any]) -> dict[str, Any]:
    blocks = [
        normalize_block(block, index)
        for index, block in enumerate(rig.get("blocks") or [], start=1)
    ]
    blocks.sort(key=lambda block: block["order"])
    return {
        "rigName": str(rig.get("rigName") or ""),
        "status": str(rig.get("status") or "draft"),
        "confidence": str(rig.get("confidence") or "unknown"),
        "needsReview": bool(rig.get("needsReview", True)),
        "equipment": deepcopy(rig.get("equipment") or {"model": "Valeton GP-180"}),
        "guitar": str(rig.get("guitar") or "Default electric guitar"),
        "output": str(rig.get("output") or "FRFR / headphones"),
        "toneProfile": str(rig.get("toneProfile") or ""),
        "signalChainSummary": str(rig.get("signalChainSummary") or ""),
        "blocks": blocks,
    }


def normalize_block(raw_block: dict[str, Any], fallback_order: int) -> dict[str, Any]:
    block = deepcopy(raw_block) if isinstance(raw_block, dict) else {}
    model = MODEL_ALIASES.get(str(block.get("model") or "None"), str(block.get("model") or "None"))
    module = normalize_module(block.get("module"), model)
    match_quality = MATCH_QUALITY_ALIASES.get(
        str(block.get("matchQuality") or "fallback").lower(), "fallback"
    )
    return {
        "order": safe_int(block.get("order"), fallback_order),
        "role": str(block.get("role") or module.lower()),
        "module": module,
        "model": model,
        "active": bool(block.get("active", model != "None")),
        "settings": deepcopy(
            block.get("settings") if isinstance(block.get("settings"), dict) else {}
        ),
        "purpose": str(block.get("purpose") or ""),
        "matchQuality": match_quality,
        "gap": str(block.get("gap") or ""),
        "alternatives": normalize_alternatives(block.get("alternatives")),
    }


def normalize_module(raw_module: Any, model: str) -> str:
    inferred = MODULE_BY_MODEL.get(model)
    if inferred:
        return inferred
    module = str(raw_module or "").strip()
    module = MODULE_ALIASES.get(module, module)
    if module in ALLOWED_MODULES:
        return module
    return "MOD" if model in {"Chorus", "O-Phase", "Tremolo"} else "PRE"


def normalize_alternatives(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    alternatives = []
    for item in value:
        if isinstance(item, dict):
            alternatives.append(
                {
                    "model": str(item.get("model") or item.get("name") or ""),
                    "reason": str(item.get("reason") or ""),
                }
            )
        else:
            alternatives.append({"model": str(item), "reason": ""})
    return [item for item in alternatives if item["model"] or item["reason"]]


def normalize_improvements(value: dict[str, Any]) -> dict[str, Any]:
    improvements = deepcopy(value) if isinstance(value, dict) else {}
    proposals = improvements.get("proposals")
    if not isinstance(proposals, list):
        proposals = []
    normalized_proposals = []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        normalized_proposals.append(
            {
                "priority": str(proposal.get("priority") or "none"),
                "type": str(proposal.get("type") or "none"),
                "target": str(proposal.get("target") or ""),
                "recommendedAsset": str(proposal.get("recommendedAsset") or ""),
                "reason": str(proposal.get("reason") or ""),
                "replacesBlockOrder": proposal.get("replacesBlockOrder"),
                "whenToUse": str(proposal.get("whenToUse") or ""),
                "expectedGain": str(proposal.get("expectedGain") or ""),
                "requiredIfGp180Gap": bool(proposal.get("requiredIfGp180Gap", False)),
            }
        )
    return {
        "summary": str(improvements.get("summary") or ""),
        "proposals": normalized_proposals,
    }


def build_source(record: dict[str, Any]) -> dict[str, Any]:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    return {
        "workflow": metadata.get("workflow"),
        "sourceIndex": metadata.get("sourceIndex"),
        "models": deepcopy(metadata.get("models") or {}),
        "finalVerdictSource": metadata.get("finalVerdictSource"),
        "openaiAction": metadata.get("openaiAction"),
        "usedLocalGp180Fallback": bool(metadata.get("usedLocalGp180Fallback", False)),
        "usedLocalImprovementsFallback": bool(metadata.get("usedLocalImprovementsFallback", False)),
    }


def validate_fretwise_export(export: dict[str, Any]) -> dict[str, Any]:
    errors = []
    warnings = []
    rig = export.get("rig") if isinstance(export.get("rig"), dict) else {}
    blocks = rig.get("blocks") if isinstance(rig.get("blocks"), list) else []
    if export.get("schemaVersion") != SCHEMA_VERSION:
        errors.append("Wrong schemaVersion.")
    if not export.get("song", {}).get("artist") or not export.get("song", {}).get("title"):
        errors.append("Missing song.artist or song.title.")
    if not rig.get("rigName"):
        errors.append("Missing rig.rigName.")
    if not blocks:
        errors.append("Missing rig.blocks.")
    for block in blocks:
        if block.get("module") not in ALLOWED_MODULES:
            errors.append(f"Invalid module: {block.get('module')}")
        if block.get("matchQuality") not in ALLOWED_MATCH_QUALITIES:
            errors.append(f"Invalid matchQuality: {block.get('matchQuality')}")
    orders = [block.get("order") for block in blocks]
    if orders != sorted(orders):
        warnings.append("Block orders are not sorted.")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def attach_fretwise_export(record: dict[str, Any]) -> dict[str, Any]:
    updated = deepcopy(record)
    updated["schemaVersion"] = SCHEMA_VERSION
    updated["fretwiseExport"] = build_fretwise_export(updated)
    return updated


def _find_rig(record: dict[str, Any]) -> dict[str, Any] | None:
    generated = record.get("generated") if isinstance(record.get("generated"), dict) else {}
    ollama = generated.get("Ollama") if isinstance(generated.get("Ollama"), dict) else {}
    rig = ollama.get("rig")
    if isinstance(rig, dict):
        return rig
    if isinstance(record.get("rig"), dict):
        return record["rig"]
    return None


def safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
