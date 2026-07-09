import json


class SchemaError(Exception):
    pass


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def get_path(data, dotted_path, default=None):
    current = data
    for part in dotted_path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default
    return current


def validate_rig(rig):
    required = [
        "rigName",
        "song",
        "equipment",
        "guitar",
        "output",
        "toneProfile",
        "status",
        "confidence",
        "signalChainSummary",
        "blocks",
        "general",
        "gp180",
        "improvements",
        "assumptions",
        "warnings",
        "sources",
        "needsReview",
    ]
    missing = [key for key in required if key not in rig]
    if missing:
        raise SchemaError(f"Missing required keys: {', '.join(missing)}")
    if not isinstance(rig["song"], dict):
        raise SchemaError("song must be an object")
    if not rig["song"].get("artist") or not rig["song"].get("title"):
        raise SchemaError("song.artist and song.title are required")
    if not isinstance(rig["equipment"], dict) or not rig["equipment"].get("model"):
        raise SchemaError("equipment.model is required")
    confidence = str(rig.get("confidence", "")).lower()
    if confidence not in {"high", "medium/high", "medium", "low", "unknown"}:
        raise SchemaError("confidence must be high, medium/high, medium, low, or unknown")
    if not isinstance(rig.get("general"), dict):
        raise SchemaError("general must be an object")
    if not rig["general"].get("toneProfile") or not rig["general"].get("idealSignalChain"):
        raise SchemaError("general.toneProfile and general.idealSignalChain are required")
    if not isinstance(rig.get("gp180"), dict):
        raise SchemaError("gp180 must be an object")
    if not isinstance(rig["gp180"].get("equipment"), dict) or not rig["gp180"]["equipment"].get(
        "model"
    ):
        raise SchemaError("gp180.equipment.model is required")
    if not rig["gp180"].get("choicePolicy"):
        raise SchemaError("gp180.choicePolicy is required")
    if not isinstance(rig.get("improvements"), dict):
        raise SchemaError("improvements must be an object")
    if not isinstance(rig["improvements"].get("proposals"), list):
        raise SchemaError("improvements.proposals must be a list")
    if not isinstance(rig.get("blocks"), list) or not rig["blocks"]:
        raise SchemaError("blocks must be a non-empty list")
    for index, block in enumerate(rig["blocks"], start=1):
        for key in ("order", "role", "module", "model", "active", "settings"):
            if key not in block:
                raise SchemaError(f"blocks[{index}] is missing {key}")
    return rig


def validate_song_profile(profile):
    return validate_rig(profile)


def parse_json_object(raw):
    if isinstance(raw, dict):
        return raw
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)
