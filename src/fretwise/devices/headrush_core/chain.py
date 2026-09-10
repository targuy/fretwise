"""Slot layout for generated rigs, derived from the device's own rig corpus.

The layout here is **not invented**. All 119 rigs on the instrument were loaded and
their chains recorded; the 39 guitar rigs (HeadRush factory ``#HR - *`` plus the
``NN-GTR-*`` set) were then analysed for ordering. The result decided the design:

* **Only 3 of 39 rigs (8 %) follow a strict total order**, with a mean of 11.9 %
  pairwise inversions. A fully frozen 14-slot template — the original plan — is
  contradicted by 92 % of a professionally authored corpus.
* **The head of the chain is rigid.** ``Filter < Overdrive``, ``Overdrive < Amp``
  and ``Amp < Cab`` each hold in **100 %** of rigs that contain both, and the same
  rules hold on the 35 user-named rigs (97-100 %).
* **The tail is deliberately free.** ``Cab < Delay`` holds in only 57 % of guitar
  rigs (54 % elsewhere), ``Chorus < Cab`` 59 %, ``Volume < Delay`` 53 %. Putting the
  delay before the cab is a coin flip among professionals, not an eccentricity.
* **Reverb ends the chain**: ``Delay < Reverb`` 94 %, median slot 12.

So this module freezes slots 1-7 — which makes CC 75-81 stable, exactly the blocks
worth a footswitch — and leaves 8-13 to be chosen per song, with 14 for reverb.

One device behaviour is load-bearing for any builder: ``setModuleTypeInternal``
takes a **0-based** slot argument, and placing a module type that is already in the
chain **moves the existing instance** instead of adding a second one. See
:func:`placement_calls` and :func:`check_relocation`.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Bypass CC for a physical slot: the manual lists ``Block 1..14 Toggle (On/Off)``
#: on CC 75-88, and Block N is slot N.
CC_BYPASS_BASE = 74

#: Frozen head, slot -> selector category. Positions follow the observed medians
#: (Utility 1, Filter 1, Compressor 2, Overdrive 3, Phaser 4, Amp 6, Cab 8) with
#: ties broken by signal-flow convention.
FROZEN_HEAD: dict[int, str] = {
    1: "Utility",     # gate / noise filter
    2: "Filter",      # wah, envelope filter
    3: "Compressor",
    4: "Overdrive",
    5: "Phaser",      # pre-amp modulation
    6: "Amp",         # or Clone (NAM, captures)
    7: "Cab",         # or IR
}

#: Slots the generator may assign freely, per song.
FREE_SLOTS: tuple[int, ...] = (8, 9, 10, 11, 12, 13)

#: Reverb closes the chain (measured: median slot 12, `Delay < Reverb` 94 %).
REVERB_SLOT = 14

#: Categories accepted in the ``Amp`` and ``Cab`` positions.
_HEAD_ALIASES: dict[str, frozenset[str]] = {
    "Amp": frozenset({"Amp", "Clone"}),
    "Cab": frozenset({"Cab"}),
}

#: Ordering rules that held in 100 % of the corpus. A generated chain violating one
#: of these is wrong, not merely unusual.
HARD_PRECEDENCE: tuple[tuple[str, str], ...] = (
    ("Utility", "Overdrive"),
    ("Utility", "Amp"),
    ("Utility", "Cab"),
    ("Filter", "Overdrive"),
    ("Filter", "Phaser"),
    ("Filter", "Cab"),
    ("Filter", "Eq"),
    ("Overdrive", "Amp"),
    ("Overdrive", "Cab"),
    ("Overdrive", "Delay"),
    ("Overdrive", "Reverb"),
    ("Phaser", "Cab"),
    ("Amp", "Cab"),
    ("Compressor", "Reverb"),
)

#: Rules that held in most but not all rigs: worth a warning, never a refusal.
SOFT_PRECEDENCE: tuple[tuple[str, str, float], ...] = (
    ("Delay", "Reverb", 0.94),
    ("Cab", "Reverb", 0.94),
)


class ChainError(ValueError):
    """A proposed chain violates the corpus-derived layout rules."""


@dataclass(frozen=True)
class Placement:
    """One block assigned to one physical slot."""

    slot: int
    module: str
    category: str

    @property
    def bypass_cc(self) -> int:
        """Return the MIDI CC that toggles this slot (manual v5.1.0 p. 71)."""
        return CC_BYPASS_BASE + self.slot

    @property
    def is_frozen_head(self) -> bool:
        """Return True when this slot's role is fixed across every generated rig."""
        return self.slot in FROZEN_HEAD


def category_slot(category: str) -> int | None:
    """Return the frozen slot for a category, or None when it belongs to the free tail."""
    for slot, name in FROZEN_HEAD.items():
        if category == name or category in _HEAD_ALIASES.get(name, frozenset()):
            return slot
    return None


def assign_slots(blocks: list[tuple[str, str]]) -> list[Placement]:
    """Lay out ``(module, category)`` pairs onto physical slots.

    Head categories go to their frozen positions; reverb goes to slot 14; whatever
    remains fills the free tail in the order given, which is the song's own choice.

    Args:
        blocks: Ordered ``(module name, selector category)`` pairs.

    Returns:
        Placements sorted by slot.

    Raises:
        ChainError: Two blocks claim the same frozen slot, or the free tail
            overflows. Both are real conditions the generator must handle
            (the design's degradation ladder), not assertions.
    """
    placements: dict[int, Placement] = {}
    tail: list[tuple[str, str]] = []

    for module, category in blocks:
        if category == "Reverb":
            slot: int = REVERB_SLOT
        else:
            head_slot = category_slot(category)
            if head_slot is None:
                tail.append((module, category))
                continue
            slot = head_slot
        if slot in placements:
            raise ChainError(
                f"slot {slot} ({FROZEN_HEAD.get(slot, 'reverb')}) claimed twice: "
                f"{placements[slot].module!r} and {module!r}"
            )
        placements[slot] = Placement(slot=slot, module=module, category=category)

    if len(tail) > len(FREE_SLOTS):
        raise ChainError(
            f"{len(tail)} blocks for {len(FREE_SLOTS)} free slots: "
            f"{', '.join(m for m, _ in tail)}"
        )
    for slot, (module, category) in zip(FREE_SLOTS, tail):
        placements[slot] = Placement(slot=slot, module=module, category=category)

    return [placements[s] for s in sorted(placements)]


def validate_order(placements: list[Placement]) -> list[str]:
    """Return the ordering violations of a laid-out chain.

    Hard rules produce an error string; soft rules produce a warning naming the
    corpus frequency, so a deliberate choice reads as a choice rather than a bug.
    """
    problems: list[str] = []
    by_category: dict[str, int] = {}
    for placement in placements:
        by_category.setdefault(placement.category, placement.slot)

    for before, after in HARD_PRECEDENCE:
        if before in by_category and after in by_category:
            if by_category[before] > by_category[after]:
                problems.append(
                    f"{before} (slot {by_category[before]}) must precede "
                    f"{after} (slot {by_category[after]}) — 100 % of the corpus"
                )
    for before, after, frequency in SOFT_PRECEDENCE:
        if before in by_category and after in by_category:
            if by_category[before] > by_category[after]:
                problems.append(
                    f"note: {before} after {after} — unusual but attested "
                    f"({frequency:.0%} of the corpus does the opposite)"
                )
    return problems


def placement_calls(placements: list[Placement]) -> list[tuple[int, str]]:
    """Return the ``setModuleTypeInternal`` arguments for a layout.

    **The slot argument is 0-based** — verified three times on hardware: argument 1
    lands in slot 2, argument 9 in slot 10, argument 11 in slot 12. Getting this
    wrong shifts the whole layout by one and silently invalidates every bypass CC.

    Returns:
        ``(zero_based_slot, module_name)`` pairs, ordered by slot.
    """
    return [(p.slot - 1, p.module) for p in placements]


def check_relocation(placements: list[Placement]) -> list[str]:
    """Return errors for module types requested more than once.

    Placing a type that is already in the chain **moves** the existing instance
    rather than adding a second one — a behaviour that silently destroyed a block
    during calibration. A second instance must name the twin explicitly
    (``"Amp 2"``, ``"BBD Delay 2"``).
    """
    seen: dict[str, int] = {}
    problems: list[str] = []
    for placement in placements:
        if placement.module in seen:
            problems.append(
                f"{placement.module!r} requested for slots {seen[placement.module]} and "
                f"{placement.slot}: the device would MOVE the first instance. "
                f"Use the twin {placement.module + ' 2'!r} for the second."
            )
        seen[placement.module] = placement.slot
    return problems


def describe(placements: list[Placement]) -> str:
    """Render a layout as an aligned table with each slot's bypass CC."""
    lines = [f"{'slot':>4}  {'CC':<5} {'catégorie':<12} module"]
    for placement in placements:
        marker = "*" if placement.is_frozen_head else " "
        lines.append(
            f"{placement.slot:>4}{marker} CC{placement.bypass_cc:<3} "
            f"{placement.category:<12} {placement.module}"
        )
    lines.append("  (* = tête de chaîne figée, CC stable dans toute la bibliothèque)")
    return "\n".join(lines)
