from dataclasses import dataclass, field
from typing import Any


@dataclass
class Song:
    title: str
    artist: str
    album: str = ""
    year: int | None = None


@dataclass
class RigBlock:
    order: int
    role: str
    module: str
    model: str
    active: bool = True
    settings: dict[str, Any] = field(default_factory=dict)
    purpose: str = ""
    alternatives: list[str] = field(default_factory=list)


@dataclass
class Rig:
    rig_name: str
    song: Song
    equipment: dict[str, str]
    guitar: str
    output: str
    tone_profile: str
    status: str
    confidence: str
    signal_chain_summary: str
    blocks: list[RigBlock]
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    created_from: str = "generated"
    needs_review: bool = True


CONFIDENCE_ORDER = {
    "unknown": 0,
    "low": 1,
    "medium": 2,
    "medium/high": 3,
    "high": 4,
}


def confidence_needs_review(confidence: str) -> bool:
    return CONFIDENCE_ORDER.get(confidence.lower(), 0) < CONFIDENCE_ORDER["high"]


def normalize_rig(raw: dict[str, Any]) -> dict[str, Any]:
    rig = dict(raw)
    general = rig.get("general") if isinstance(rig.get("general"), dict) else {}
    gp180 = rig.get("gp180") if isinstance(rig.get("gp180"), dict) else {}
    if "rigName" not in rig and "rig_name" in rig:
        rig["rigName"] = rig["rig_name"]
    if "general" not in rig:
        rig["general"] = {
            "targetSound": rig.get("toneProfile", ""),
            "toneProfile": rig.get("toneProfile", ""),
            "idealSignalChain": rig.get("signalChainSummary", ""),
            "bestPossibleEquipment": [],
            "productionNotes": [],
        }
        general = rig["general"]
    if "gp180" not in rig:
        rig["gp180"] = {
            "equipment": rig.get("equipment", {}),
            "guitar": rig.get("guitar", ""),
            "output": rig.get("output", ""),
            "choicePolicy": "Legacy profile without explicit GP-180 choice policy.",
            "bestMatchSummary": rig.get("signalChainSummary", ""),
            "blocks": rig.get("blocks", []),
        }
        gp180 = rig["gp180"]
    if "improvements" not in rig:
        rig["improvements"] = {
            "summary": "No structured improvements were provided.",
            "proposals": [],
        }
    if "equipment" not in rig and isinstance(gp180.get("equipment"), dict):
        rig["equipment"] = gp180["equipment"]
    if "guitar" not in rig and gp180.get("guitar"):
        rig["guitar"] = gp180["guitar"]
    if "output" not in rig and gp180.get("output"):
        rig["output"] = gp180["output"]
    if "toneProfile" not in rig and "tone_profile" in rig:
        rig["toneProfile"] = rig["tone_profile"]
    if "toneProfile" not in rig:
        rig["toneProfile"] = general.get("toneProfile") or general.get("targetSound", "")
    if "signalChainSummary" not in rig and "signal_chain_summary" in rig:
        rig["signalChainSummary"] = rig["signal_chain_summary"]
    if "signalChainSummary" not in rig:
        rig["signalChainSummary"] = gp180.get("bestMatchSummary") or general.get(
            "idealSignalChain", ""
        )
    if "blocks" not in rig and isinstance(gp180.get("blocks"), list):
        rig["blocks"] = gp180["blocks"]
    if "createdFrom" not in rig and "created_from" in rig:
        rig["createdFrom"] = rig["created_from"]
    if "needsReview" not in rig:
        rig["needsReview"] = confidence_needs_review(str(rig.get("confidence", "unknown")))
    return rig
