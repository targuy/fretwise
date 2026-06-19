"""Grounded GP-180 rig pipeline: verified facts -> model -> override -> validate.

This is the source-agnostic engine validated by the MVP (exports/mvp_grounding):

  1. RETRIEVAL  -> a :class:`FactsProvider` supplies verified :class:`SongFacts`
                   (curated JSON DB, or a local web-research agent — see
                   :mod:`fretwise.facts_web_agent`). gemma4 has no internet, so
                   facts MUST come from outside the generation model.
  2. MODEL      -> the local AI wrapper fills the interpretive layer (numeric
                   params, comments) under a grounded prompt.
  3. OVERRIDE   -> the hard, objective facts (tuning, capo, guitar, amp, distortion
                   source, defining effects) are WRITTEN from the fact sheet, never
                   trusted to the model (a small model ignores injected facts ~10%
                   of the time).
  4. VALIDATE   -> every preset is checked against the GP-180 palette whitelist.

Songs with no verified facts are still generated, but flagged ``grounded=False``
and graded down (C/D) — never presented as a verified "A".
"""
from __future__ import annotations

import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from fretwise.rig import _normalize, generated_rig_to_view

if TYPE_CHECKING:
    from fretwise.rig_generation import SongRigGenerationService

# --- GP-180 palette whitelist (preset substrings, lowercase) -----------------

PALETTE: dict[str, tuple[str, ...]] = {
    "nr": ("gate 1",),
    "pre": ("comp", "od9 ts808", "od9 ts9", "ts808", "ts9", "klon"),
    "dst": ("dist+", "ds1", "rat", "big muff", "fuzz face"),
    "amp": (
        "tweedy", "bassman", "foxy30", "uk 45", "uk 50", "uk 900", "solo100",
        "mesa dual recto", "tremoverb", "engl savage", "engl gigmaster",
    ),
    "cab": ("uk vintage 4x12", "4x12", "2x12", "1x12", "cab"),
    "eq": ("guitar eq 1", "eq"),
    "mod": ("ce2 chorus", "ce3 chorus", "tremolo", "micropitch", "shimmer", "chorus"),
    "dly": ("dd3", "ping pong", "carbon copy", "sweep echo"),
    "rvb": ("room", "plate", "spring", "hall", "shimmer"),
}
GUITAR_FAMILIES: tuple[str, ...] = (
    "gibson les paul", "gibson sg", "fender telecaster",
    "fender stratocaster", "superstrat",
)
# Slots whose preset is written deterministically from the fact sheet.
HARD_SLOTS: tuple[str, ...] = ("nr", "dst", "amp", "mod", "dly", "rvb")
_OFF = frozenset({"off", "non", "none", "aucun", "aucune", ""})


@dataclass(frozen=True)
class SongFacts:
    """Verified, source-backed facts for one song, mapped to the GP-180 palette.

    Slot fields use ``"Off"`` when the module is not used. ``reliability`` is the
    honest grade for a fact sheet of this completeness (A best .. D weakest).
    """

    artist: str
    title: str
    tuning: str
    capo: str = "non"
    guitar: str = ""
    amp: str = "Off"
    pre: str = "Off"
    dst: str = "Off"
    nr: str = "Off"
    mod: str = "Off"
    dly: str = "Off"
    rvb: str = "Off"
    reliability: str = "C"
    notes: str = ""
    sources: tuple[str, ...] = field(default_factory=tuple)

    def to_json(self) -> dict[str, object]:
        return {
            "artist": self.artist, "title": self.title, "tuning": self.tuning,
            "capo": self.capo, "guitar": self.guitar, "amp": self.amp,
            "pre": self.pre, "dst": self.dst, "nr": self.nr, "mod": self.mod,
            "dly": self.dly, "rvb": self.rvb, "reliability": self.reliability,
            "notes": self.notes, "sources": list(self.sources),
        }

    @classmethod
    def from_json(cls, data: Mapping[str, object]) -> SongFacts:
        def s(key: str, default: str = "") -> str:
            v = data.get(key, default)
            return str(v).strip() if v is not None else default
        srcs = data.get("sources", [])
        sources = tuple(str(x) for x in srcs) if isinstance(srcs, list) else ()
        return cls(
            artist=s("artist"), title=s("title"), tuning=s("tuning", "inconnu"),
            capo=s("capo", "non"), guitar=s("guitar"), amp=s("amp", "Off"),
            pre=s("pre", "Off"), dst=s("dst", "Off"), nr=s("nr", "Off"),
            mod=s("mod", "Off"), dly=s("dly", "Off"), rvb=s("rvb", "Off"),
            reliability=s("reliability", "C"), notes=s("notes"), sources=sources,
        )

    def facts_block(self) -> str:
        """The French facts block injected into the grounded generation prompt."""
        lines = [
            f"- Accordage: {self.tuning}",
            f"- Capo: {self.capo}",
            f"- Guitare: {self.guitar or 'non precise'}",
            f"- Ampli (preset GP-180 le plus proche): {self.amp}",
            f"- Distorsion: {self.dst}",
            f"- Noise gate: {self.nr}",
            f"- Modulation: {self.mod}",
            f"- Delay: {self.dly}",
            f"- Reverb: {self.rvb}",
        ]
        if self.pre and self.pre.lower() not in _OFF:
            lines.append(f"- Pre/boost: {self.pre}")
        if self.notes:
            lines.append(f"- Notes: {self.notes}")
        return "\n".join(lines)


class FactsProvider(Protocol):
    """Supplies verified facts for a song, or ``None`` when none are available."""

    def get_facts(self, artist: str, title: str) -> SongFacts | None: ...


def facts_key(artist: str, title: str) -> str:
    """Normalized lookup key, consistent with rig filename normalization."""
    return f"{_normalize(artist)}::{_normalize(title)}"


class JsonFactsProvider:
    """Reads verified facts from a curated/cached JSON DB (``data/song_facts.json``).

    The DB is the durable artifact: web research (expensive, done once per song by
    a :class:`FactsProvider` with internet) is cached here so the local generation
    model reads facts offline forever after.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._index: dict[str, SongFacts] = {}
        self._load()

    def _load(self) -> None:
        import json
        if not self.path.is_file():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        entries = data.get("facts", data) if isinstance(data, dict) else data
        if isinstance(entries, list):
            for item in entries:
                if isinstance(item, dict):
                    f = SongFacts.from_json(item)
                    self._index[facts_key(f.artist, f.title)] = f

    def get_facts(self, artist: str, title: str) -> SongFacts | None:
        return self._index.get(facts_key(artist, title))

    def upsert(self, facts: SongFacts) -> None:
        """Add or replace a fact sheet and persist the whole DB."""
        import json
        self._index[facts_key(facts.artist, facts.title)] = facts
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"facts": [f.to_json() for f in self._index.values()]}
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


# --- preset helpers ----------------------------------------------------------

def preset_of(value: str) -> str:
    """First segment before a separator = the preset name."""
    if not value:
        return ""
    return re.split(r"\s*[·\-—–]\s*", value.strip())[0].strip()


def _params_of(value: str) -> str:
    m = re.search(r"[·—–]\s*(.+)$", value or "")
    return m.group(1).strip() if m else ""


def in_palette(slot: str, value: str) -> bool:
    """True if ``value``'s preset belongs to the slot's GP-180 palette (Off ok)."""
    p = preset_of(value).lower()
    if p in _OFF:
        return True
    return any(k in p for k in PALETTE.get(slot, ()))


def _force_slot(model_value: str, fact_preset: str) -> str:
    """Write the verified preset, preserving the model's numeric params if any."""
    if fact_preset.lower() in _OFF:
        return "Off"
    params = _params_of(model_value)
    return f"{fact_preset} · {params}" if params else fact_preset


def _force_guitar(model_guitar: str, fact_guitar: str) -> str:
    """Force the verified family; keep the model's pickup detail when present."""
    if not fact_guitar:
        return model_guitar
    detail = model_guitar.split(",", 1)[1].strip() if model_guitar and "," in model_guitar else ""
    family = fact_guitar.split("+")[0].split(",")[0].strip()
    return f"{family}, {detail}" if detail else family


def validate_against_palette(rig: Mapping[str, object], guitar: str | None = None) -> list[str]:
    """Return a list of human-readable flags for any out-of-palette preset."""
    flags: list[str] = []
    for slot, value in rig.items():
        if slot in PALETTE and not in_palette(slot, str(value)):
            flags.append(f"slot '{slot}' hors-palette = {preset_of(str(value))!r}")
    if guitar:
        gl = guitar.lower()
        if not any(fam in gl for fam in GUITAR_FAMILIES):
            flags.append(f"guitare hors-palette = {guitar!r}")
    return flags


def apply_facts_override(raw: dict, facts: SongFacts) -> dict:
    """Deterministically write the verified hard facts onto a generated rig dict.

    ``raw`` is the wrapper's ``codex_output_schema_v1`` object. Returns a new dict
    with accordage/capo/guitar and the hard rig slots forced from ``facts``, while
    keeping the model's numeric params, ``pre``/``cab``/``eq`` slots and comments.
    """
    out = dict(raw)
    rig = dict(out.get("rig", {}))
    out["accordage"] = facts.tuning
    out["capo"] = facts.capo
    out["recommended_guitar"] = _force_guitar(str(out.get("recommended_guitar", "")), facts.guitar)
    slot_facts = {"nr": facts.nr, "dst": facts.dst, "amp": facts.amp,
                  "mod": facts.mod, "dly": facts.dly, "rvb": facts.rvb}
    for slot, fact_preset in slot_facts.items():
        rig[slot] = _force_slot(str(rig.get(slot, "")), fact_preset)
    if facts.pre and facts.pre.lower() not in _OFF:
        rig["pre"] = _force_slot(str(rig.get("pre", "")), facts.pre)
    out["rig"] = rig
    out["reliability"] = facts.reliability or out.get("reliability", "C")
    return out


@dataclass(frozen=True)
class GroundedResult:
    """A produced rig view plus provenance/quality metadata."""

    view: dict
    grounded: bool
    reliability: str
    flags: tuple[str, ...]
    sources: tuple[str, ...]


def generate_grounded_rig(
    service: SongRigGenerationService,
    artist: str,
    title: str,
    *,
    facts: SongFacts | None,
    genre: str | None = None,
    target_guitar: str | None = None,
    refresh: bool = False,
    ungrounded_reliability: str = "D",
) -> GroundedResult:
    """Run the full pipeline for one song and return a renderable view + metadata.

    When ``facts`` is given the prompt is grounded and the hard facts are written
    deterministically; otherwise the rig is still generated but flagged
    ``grounded=False`` and graded down (never an inflated "A").
    """
    facts_path: Path | None = None
    try:
        if facts is not None:
            tmp = tempfile.NamedTemporaryFile(
                "w", suffix=".facts.txt", delete=False, encoding="utf-8"
            )
            tmp.write(facts.facts_block())
            tmp.close()
            facts_path = Path(tmp.name)
        result = service.generate(
            artist, title, genre=genre, target_guitar=target_guitar,
            refresh=refresh, facts_file=facts_path,
        )
    finally:
        if facts_path is not None:
            facts_path.unlink(missing_ok=True)

    raw = result.raw
    pre_flags = validate_against_palette(
        raw.get("rig", {}) if isinstance(raw.get("rig"), dict) else {},
        str(raw.get("recommended_guitar") or ""),
    )
    if facts is not None:
        raw = apply_facts_override(raw, facts)
        reliability = facts.reliability
        sources = facts.sources
        grounded = True
    else:
        reliability = ungrounded_reliability
        raw["reliability"] = reliability
        sources = ()
        grounded = False

    view = generated_rig_to_view(raw)
    view["grounded"] = grounded
    view["validation_flags"] = list(pre_flags)
    return GroundedResult(
        view=view, grounded=grounded, reliability=reliability,
        flags=tuple(pre_flags), sources=tuple(sources),
    )
