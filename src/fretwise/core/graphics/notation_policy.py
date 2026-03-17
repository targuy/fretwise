"""Notation policy and symbol-usage rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class RepresentationMode(StrEnum):
    """Supported representation modes."""

    STANDARD = "standard"
    TAB = "tablature"
    STANDARD_TAB = "standard_tablature"
    TAB_RHYTHM = "tablature_rhythm"


class SymbolAnchor(StrEnum):
    """Preferred notation plane for a symbol."""

    STANDARD = "standard"
    TAB = "tab"
    BOTH = "both"
    SYSTEM = "system"


@dataclass(frozen=True)
class SymbolRule:
    """One policy rule for a symbol."""

    symbol_id: str
    allowed_modes: frozenset[RepresentationMode]
    anchor: SymbolAnchor
    notes: str = ""

    def is_allowed(self, mode: RepresentationMode) -> bool:
        """Return True when this symbol is allowed in *mode*."""
        return mode in self.allowed_modes


@dataclass
class NotationPolicy:
    """Collection of symbol rules and policy metadata."""

    policy_id: str
    symbol_rules: dict[str, SymbolRule] = field(default_factory=dict)
    metadata: dict[str, str] = field(default_factory=dict)

    def get_rule(self, symbol_id: str) -> SymbolRule | None:
        """Return rule for symbol, if registered."""
        return self.symbol_rules.get(symbol_id)

    def is_allowed(self, mode: RepresentationMode, symbol_id: str) -> bool:
        """Return True when symbol is allowed in mode."""
        rule = self.get_rule(symbol_id)
        if rule is None:
            return False
        return rule.is_allowed(mode)


def default_notation_policy() -> NotationPolicy:
    """Build default symbol policy aligned with notation-core goals."""
    all_modes = frozenset(
        {
            RepresentationMode.STANDARD,
            RepresentationMode.TAB,
            RepresentationMode.STANDARD_TAB,
            RepresentationMode.TAB_RHYTHM,
        }
    )
    tab_modes = frozenset(
        {
            RepresentationMode.TAB,
            RepresentationMode.STANDARD_TAB,
            RepresentationMode.TAB_RHYTHM,
        }
    )
    standard_modes = frozenset(
        {
            RepresentationMode.STANDARD,
            RepresentationMode.STANDARD_TAB,
        }
    )
    rhythm_modes = frozenset(
        {
            RepresentationMode.STANDARD,
            RepresentationMode.STANDARD_TAB,
            RepresentationMode.TAB_RHYTHM,
        }
    )

    rules = {
        "notehead": SymbolRule(
            symbol_id="notehead",
            allowed_modes=standard_modes,
            anchor=SymbolAnchor.STANDARD,
        ),
        "rest": SymbolRule(
            symbol_id="rest",
            allowed_modes=all_modes,
            anchor=SymbolAnchor.BOTH,
        ),
        "clef": SymbolRule(
            symbol_id="clef",
            allowed_modes=standard_modes,
            anchor=SymbolAnchor.STANDARD,
        ),
        "time_signature": SymbolRule(
            symbol_id="time_signature",
            allowed_modes=all_modes,
            anchor=SymbolAnchor.SYSTEM,
        ),
        "tab_lines": SymbolRule(
            symbol_id="tab_lines",
            allowed_modes=tab_modes,
            anchor=SymbolAnchor.TAB,
        ),
        "staff_lines": SymbolRule(
            symbol_id="staff_lines",
            allowed_modes=standard_modes,
            anchor=SymbolAnchor.STANDARD,
        ),
        "accidental_sharp": SymbolRule(
            symbol_id="accidental_sharp",
            allowed_modes=standard_modes,
            anchor=SymbolAnchor.STANDARD,
        ),
        "accidental_flat": SymbolRule(
            symbol_id="accidental_flat",
            allowed_modes=standard_modes,
            anchor=SymbolAnchor.STANDARD,
        ),
        "stem_line": SymbolRule(
            symbol_id="stem_line",
            allowed_modes=rhythm_modes,
            anchor=SymbolAnchor.STANDARD,
        ),
        "tie_arc": SymbolRule(
            symbol_id="tie_arc",
            allowed_modes=standard_modes,
            anchor=SymbolAnchor.STANDARD,
        ),
        "slur_arc": SymbolRule(
            symbol_id="slur_arc",
            allowed_modes=standard_modes,
            anchor=SymbolAnchor.STANDARD,
        ),
        "beam_group": SymbolRule(
            symbol_id="beam_group",
            allowed_modes=rhythm_modes,
            anchor=SymbolAnchor.STANDARD,
        ),
        "tab_digit": SymbolRule(
            symbol_id="tab_digit",
            allowed_modes=tab_modes,
            anchor=SymbolAnchor.TAB,
        ),
        "measure_number": SymbolRule(
            symbol_id="measure_number",
            allowed_modes=all_modes,
            anchor=SymbolAnchor.SYSTEM,
        ),
        "hammer_on": SymbolRule(
            symbol_id="hammer_on",
            allowed_modes=tab_modes,
            anchor=SymbolAnchor.TAB,
            notes="Instrumental effect marker anchored to tablature plane.",
        ),
        "pull_off": SymbolRule(
            symbol_id="pull_off",
            allowed_modes=tab_modes,
            anchor=SymbolAnchor.TAB,
            notes="Instrumental effect marker anchored to tablature plane.",
        ),
        "slide": SymbolRule(
            symbol_id="slide",
            allowed_modes=tab_modes,
            anchor=SymbolAnchor.TAB,
            notes="Instrumental effect marker anchored to tablature plane.",
        ),
        "bend": SymbolRule(
            symbol_id="bend",
            allowed_modes=tab_modes,
            anchor=SymbolAnchor.TAB,
            notes="Instrumental effect marker anchored to tablature plane.",
        ),
        "vibrato": SymbolRule(
            symbol_id="vibrato",
            allowed_modes=tab_modes,
            anchor=SymbolAnchor.TAB,
            notes="Instrumental effect marker anchored to tablature plane.",
        ),
        "palm_mute": SymbolRule(
            symbol_id="palm_mute",
            allowed_modes=tab_modes,
            anchor=SymbolAnchor.TAB,
            notes="Instrumental effect marker anchored to tablature plane.",
        ),
        "let_ring": SymbolRule(
            symbol_id="let_ring",
            allowed_modes=tab_modes,
            anchor=SymbolAnchor.TAB,
            notes="Instrumental effect marker anchored to tablature plane.",
        ),
        "let_ring_span": SymbolRule(
            symbol_id="let_ring_span",
            allowed_modes=tab_modes,
            anchor=SymbolAnchor.TAB,
            notes="Instrumental effect span anchored to tablature plane.",
        ),
        "tapping": SymbolRule(
            symbol_id="tapping",
            allowed_modes=tab_modes,
            anchor=SymbolAnchor.TAB,
            notes="Instrumental effect marker anchored to tablature plane.",
        ),
        "palm_mute_span": SymbolRule(
            symbol_id="palm_mute_span",
            allowed_modes=tab_modes,
            anchor=SymbolAnchor.TAB,
            notes="Instrumental effect span anchored to tablature plane.",
        ),
    }

    return NotationPolicy(
        policy_id="default-v1",
        symbol_rules=rules,
        metadata={
            "tab_rhythm_is_reduction": "true",
            "standard_tab_alignment_required": "true",
        },
    )
