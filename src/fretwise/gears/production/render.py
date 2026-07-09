import json

from .schema import get_path


def notion_payload(profile, config):
    return {
        "properties": build_properties(profile, config),
        "children": build_blocks(profile),
    }


def build_properties(profile, config):
    mapping = config["notion"].get("property_map", {})
    props = {}
    song = profile.get("song", {})
    gp180 = profile.get("gp180", {})
    equipment = gp180.get("equipment") or profile.get("equipment", {})
    template_vars = {
        "artist": song.get("artist", ""),
        "title": song.get("title", ""),
        "album": song.get("album", ""),
        "year": song.get("year", ""),
        "rigName": profile.get("rigName", ""),
        "equipment": equipment.get("model", ""),
        "guitar": gp180.get("guitar") or profile.get("guitar", ""),
    }
    for spec in mapping.values():
        name = spec["property"]
        value = spec.get("static")
        if "path" in spec:
            value = get_path(profile, spec["path"])
        if "template" in spec:
            value = spec["template"].format(**template_vars)
        props[name] = _property_value(spec["type"], value)
    return props


def build_blocks(profile):
    song = profile["song"]
    general = profile.get("general", {})
    gp180 = profile.get("gp180", {})
    improvements = profile.get("improvements", {})
    equipment = gp180.get("equipment") or profile.get("equipment", {})
    guitar = gp180.get("guitar") or profile.get("guitar", "")
    output = gp180.get("output") or profile.get("output", "")
    blocks = [
        heading("Rig Snapshot"),
        callout(profile.get("signalChainSummary", ""), "guitar"),
        bullet(f"Song: {song.get('artist', '')} - {song.get('title', '')}"),
        bullet(f"Equipment: {equipment.get('model', '')}"),
        bullet(f"Guitar: {guitar}"),
        bullet(f"Output: {output}"),
        bullet(f"Tone profile: {general.get('toneProfile') or profile.get('toneProfile', '')}"),
        bullet(f"Confidence: {profile.get('confidence', 'unknown')}"),
        heading("General Information"),
        bullet(f"Target sound: {general.get('targetSound', '')}"),
        bullet(f"Ideal signal chain: {general.get('idealSignalChain', '')}"),
    ]
    best_equipment = general.get("bestPossibleEquipment") or []
    if best_equipment:
        blocks.append(heading("Best Possible Equipment"))
        for item in best_equipment:
            blocks.append(
                bullet(
                    f"{item.get('role', '')}: {item.get('model', '')} - {item.get('reason', '')}"
                )
            )
    production_notes = general.get("productionNotes") or []
    if production_notes:
        blocks.append(heading("Production Notes"))
        for note in production_notes:
            blocks.append(bullet(note))
    blocks.extend(
        [
            heading("GP-180 Best Match"),
            callout(gp180.get("choicePolicy", ""), "settings"),
            bullet(
                "Best match: "
                f"{gp180.get('bestMatchSummary') or profile.get('signalChainSummary', '')}"
            ),
        ]
    )
    for block in sorted(profile.get("blocks", []), key=lambda p: p.get("order", 999)):
        settings = _settings_text(block.get("settings", {}))
        purpose = block.get("purpose", "")
        active = "on" if block.get("active", True) else "off"
        match = block.get("matchQuality", "")
        gap = block.get("gap", "")
        suffix = ""
        if match or gap:
            suffix = f" Match={match or 'unknown'}. Gap={gap or 'none'}."
        blocks.append(
            numbered(
                f"{block.get('order')}. {block.get('role')} / {block.get('module')} / "
                f"{block.get('model')} "
                f"({active}): {settings}. {purpose}{suffix}"
            )
        )
    blocks.append(heading("NAM / IR Improvements"))
    blocks.append(paragraph(improvements.get("summary", "")))
    proposals = improvements.get("proposals") or []
    if proposals:
        for proposal in proposals:
            replaces = proposal.get("replacesBlockOrder")
            replaces_text = f" replaces block {replaces}" if replaces is not None else ""
            blocks.append(
                bullet(
                    f"{proposal.get('priority', 'none')} / "
                    f"{proposal.get('type', '')}{replaces_text}: "
                    f"{proposal.get('recommendedAsset', '')} - {proposal.get('reason', '')}"
                )
            )
    else:
        blocks.append(paragraph("No NAM, SnapTone, or IR improvement proposed."))
    blocks.append(heading("Assumptions"))
    for assumption in profile.get("assumptions", []):
        blocks.append(bullet(assumption))
    blocks.append(heading("Warnings"))
    warnings = profile.get("warnings") or []
    if warnings:
        for warning in warnings:
            blocks.append(bullet(warning))
    else:
        blocks.append(paragraph("No warnings."))
    blocks.append(heading("Sources"))
    sources = profile.get("sources") or []
    if sources:
        for source in sources:
            url = source.get("url") if isinstance(source, dict) else ""
            if url:
                blocks.append(bookmark(url))
            else:
                blocks.append(bullet(str(source)))
    else:
        blocks.append(paragraph("No external sources were provided for this generated draft."))
    blocks.extend(
        [
            heading("Raw JSON"),
            code(json.dumps(profile, ensure_ascii=False, indent=2), "json"),
        ]
    )
    return blocks


def _property_value(prop_type, value):
    if value is None:
        value = ""
    if prop_type == "title":
        return {"title": [_rich_text(str(value))]}
    if prop_type == "rich_text":
        return {"rich_text": [_rich_text(str(value))]} if str(value) else {"rich_text": []}
    if prop_type == "select":
        return {"select": {"name": str(value)}} if value else {"select": None}
    if prop_type == "multi_select":
        values = value if isinstance(value, list) else [value]
        return {"multi_select": [{"name": str(item)} for item in values if item]}
    if prop_type == "number":
        return {"number": float(value)} if value not in ("", None) else {"number": None}
    if prop_type == "checkbox":
        return {"checkbox": bool(value)}
    if prop_type == "url":
        return {"url": str(value) if value else None}
    raise ValueError(f"Unsupported property type: {prop_type}")


def heading(text):
    return {"type": "heading_2", "heading_2": {"rich_text": [_rich_text(text)]}}


def paragraph(text):
    return {"type": "paragraph", "paragraph": {"rich_text": _rich_text_chunks(text)}}


def bullet(text):
    return {
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": _rich_text_chunks(text)},
    }


def numbered(text):
    return {
        "type": "numbered_list_item",
        "numbered_list_item": {"rich_text": _rich_text_chunks(text)},
    }


def callout(text, icon_name="guitar"):
    return {
        "type": "callout",
        "callout": {
            "rich_text": _rich_text_chunks(text),
            "icon": {
                "type": "external",
                "external": {"url": f"https://www.notion.so/icons/{icon_name}_gray.svg"},
            },
        },
    }


def bookmark(url):
    return {"type": "bookmark", "bookmark": {"url": url}}


def code(text, language="plain text"):
    return {"type": "code", "code": {"rich_text": _rich_text_chunks(text), "language": language}}


def _rich_text(text):
    return {"type": "text", "text": {"content": text[:2000]}}


def _rich_text_chunks(text):
    text = text or ""
    return [_rich_text(text[i : i + 2000]) for i in range(0, len(text), 2000)] or [_rich_text("")]


def _settings_text(settings):
    if not settings:
        return "no specific settings"
    return ", ".join(f"{key}={value}" for key, value in settings.items())
