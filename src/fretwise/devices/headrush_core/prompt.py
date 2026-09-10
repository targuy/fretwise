"""Copy-paste LLM workflow for authoring a HeadRush Core rig.

Same shape as the GP-180 flow in :mod:`fretwise.gears.verify`: FretWise calls no
provider. It builds a prompt the user pastes into whatever LLM they already have
open, and validates the JSON they paste back before anything reaches the
instrument.

What differs from the GP-180 version, and why it matters: the prompt is
**generated from the device's own catalog**, so the model is handed the exact
block names, the exact enumeration labels and the real ranges of this firmware —
not a prose list written by hand. The GP-180 prompt was grounded in a Notion dump
that lists blocks this device does not have (``Blue Comp``, ``Tube Scream``,
``Klone``, ``Cry Baby Wah``), which is exactly the class of hallucination that
becomes dangerous once the output drives hardware.

Validation is deliberately harsh. A pasted document goes through
:func:`fretwise.devices.headrush_core.plan.build_plan`, which rejects an unknown
module, an invalid enum label, an out-of-range value, a duplicated module type
and an ordering violation. A sheet a human reads can survive being a bit wrong;
a document that writes into an amplifier cannot.
"""

from __future__ import annotations

import json
from typing import Any

from fretwise.devices.headrush_core.catalog import Catalog
from fretwise.devices.headrush_core.chain import FREE_SLOTS, FROZEN_HEAD, REVERB_SLOT
from fretwise.devices.headrush_core.plan import BINDING_SCHEMA_VERSION, GENERATED_PREFIX, build_plan

#: Categories worth offering the model. The device has 21, but Vocal, Synth,
#: FX-Loop and Unreleased are noise for a guitar rig prompt.
_OFFERED_CATEGORIES: tuple[str, ...] = (
    "Amp", "Cab", "Clone", "Overdrive", "Distortion", "Eq", "Compressor",
    "Delay", "Reverb", "Chorus", "Phaser", "Vib", "Filter", "Pitch",
    "Dynamics", "Utility",
)

#: Parameters whose enumerations carry the actual tone identity, so they are
#: spelled out in full rather than left to the model's memory.
_KEY_ENUMS: tuple[tuple[str, str], ...] = (
    ("Amp", "Type"),
    ("ReValver_Amp", "Type"),
    ("Cab", "CabType"),
    ("Cab", "MicType"),
)


class PromptError(ValueError):
    """The pasted response is not a usable rig document."""


def _catalog_vocabulary(catalog: Catalog) -> str:
    """Render the device's real vocabulary, compactly enough to fit in a prompt."""
    lines: list[str] = ["### Blocs disponibles (noms EXACTS, par catégorie)", ""]
    for category in _OFFERED_CATEGORIES:
        blocks = catalog.category_blocks.get(category)
        if not blocks:
            continue
        lines.append(f"- **{category}** : {', '.join(blocks)}")
    lines.append("")
    for block_name, param_name in _KEY_ENUMS:
        block = catalog.block(block_name)
        param = block.param(param_name) if block else None
        if param is None or not param.options:
            continue
        lines.append(
            f"### `{block_name.replace('_', ' ')}.{param_name}` — "
            f"{len(param.options)} valeurs EXACTES"
        )
        lines.append("")
        lines.append(", ".join(f"`{o}`" for o in param.options))
        lines.append("")
    return "\n".join(lines)


def _layout_rules() -> str:
    """Render the slot rules measured on the device's own 119-rig corpus."""
    head = "\n".join(
        f"| {slot} | {role} | figé |" for slot, role in sorted(FROZEN_HEAD.items())
    )
    return f"""### Emplacement des blocs

Mesuré sur les 119 rigs de l'appareil : la tête de chaîne est rigide
(`Filter < Overdrive < Amp < Cab` tient dans 100 % des rigs guitare), la queue est
libre (`Cab < Delay` n'est vrai que dans 57 % des cas — les deux se défendent).

| Slot | Rôle | |
|---|---|---|
{head}
| {min(FREE_SLOTS)}–{max(FREE_SLOTS)} | libres : EQ, modulation, volume, delay, pitch | au choix |
| {REVERB_SLOT} | réverbe | figé |

Tu n'écris PAS les numéros de slot : donne les blocs dans l'ordre du signal,
FretWise les place. Ne demande jamais deux fois le même bloc — pour une seconde
instance, nomme le jumeau (`"Amp 2"`, `"BBD Delay 2"`)."""


def build_rig_prompt(
    artist: str,
    title: str,
    catalog: Catalog,
    *,
    existing: dict[str, Any] | None = None,
    guidance: str = "",
) -> str:
    """Build the prompt the user pastes into their own LLM.

    Args:
        artist: Song artist.
        title: Song title.
        catalog: Catalog generated from the target device — the source of every
            legal name in the prompt.
        existing: A previous binding to correct rather than start from scratch.
        guidance: Free-text note from the user ("plus sombre", "moins de gain"…).

    Returns:
        A Markdown prompt.
    """
    song = f"{artist} — {title}".strip(" —")
    mode = "corriger" if existing else "créer"
    rig_name = f"{GENERATED_PREFIX}{artist} - {title}".strip()

    parts = [
        f"# {mode.capitalize()} un rig HeadRush Core — {song}",
        "",
        "Tu es ingénieur du son guitare. Recherche le son réel de ce morceau "
        "(matériel de l'artiste à l'époque, captations live, interviews) puis "
        "traduis-le sur un **HeadRush Core**, firmware "
        f"`{catalog.app_version}`.",
        "",
        "## Règles absolues",
        "",
        "1. **N'invente aucun nom.** Chaque `module` et chaque valeur d'énumération "
        "doit être copié littéralement depuis les listes ci-dessous. Un nom absent "
        "fait rejeter le document entier.",
        "2. **Valeurs en unités d'affichage**, pas en 0-1 : `62` pour 62 %, `300` "
        "pour 300 ms, `-3` pour −3 dB. FretWise convertit.",
        "3. **Un seul bloc NAM (`Neural Amp Modeler`) et une seule réverbe à "
        "convolution (`C-Verb`) par rig.**",
        "4. Reste sobre : 5 à 9 blocs. Le CPU est déjà à ~59 % pour 9 blocs.",
        "5. Réponds **uniquement** par l'objet JSON, sans commentaire autour.",
        "",
        _layout_rules(),
        "",
        _catalog_vocabulary(catalog),
        "## Format de sortie",
        "",
        "```json",
        json.dumps(
            {
                "schemaVersion": BINDING_SCHEMA_VERSION,
                "device": {"deviceId": "headrush-core", "appVersion": catalog.app_version},
                "rig": {"name": rig_name, "programChange": None},
                "song": {"artist": artist, "title": title},
                "tone": {
                    "summary": "une phrase sur le son visé",
                    "mustHave": ["…"],
                    "avoid": ["…"],
                },
                "confidence": "high | medium/high | medium | low | unknown",
                "sources": ["…"],
                "blocks": [
                    {
                        "module": "Amp",
                        "why": "pourquoi ce modèle pour ce morceau",
                        "params": {"Type": "82 Lead 800 100W", "GainA": 62, "Master": 50},
                    }
                ],
            },
            indent=1,
            ensure_ascii=False,
        ),
        "```",
    ]
    if existing:
        parts += [
            "",
            "## Document actuel — corrige-le plutôt que de repartir de zéro",
            "",
            "```json",
            json.dumps(existing, indent=1, ensure_ascii=False),
            "```",
        ]
    if guidance.strip():
        parts += ["", "## Demande de l'utilisateur", "", guidance.strip()]
    return "\n".join(parts)


def parse_rig_response(
    raw: str | dict[str, Any],
    catalog: Catalog,
    *,
    artist: str = "",
    title: str = "",
) -> tuple[dict[str, Any], list[str]]:
    """Validate a pasted LLM response and return a usable binding.

    Args:
        raw: The pasted text (fenced code blocks and surrounding prose tolerated)
            or an already-decoded object.
        catalog: Catalog of the target device.
        artist: Expected artist, used to repair a missing rig name.
        title: Expected title.

    Returns:
        ``(binding, warnings)``.

    Raises:
        PromptError: The response is not JSON, or the resulting rig would be
            rejected by the device planner.
    """
    document = _decode(raw)

    document.setdefault("schemaVersion", BINDING_SCHEMA_VERSION)
    document.setdefault(
        "device", {"deviceId": "headrush-core", "appVersion": catalog.app_version}
    )
    rig = document.setdefault("rig", {})
    if not str(rig.get("name", "")).strip() and (artist or title):
        rig["name"] = f"{GENERATED_PREFIX}{artist} - {title}".strip()
    name = str(rig.get("name", ""))
    if not name.startswith(GENERATED_PREFIX):
        rig["name"] = f"{GENERATED_PREFIX}{name.lstrip('#').strip()}"

    plan = build_plan(document, catalog)
    if not plan.is_applicable:
        raise PromptError(
            "le document proposé serait rejeté par l'appareil :\n  - "
            + "\n  - ".join(plan.errors)
        )
    return document, list(plan.warnings)


def _decode(raw: str | dict[str, Any]) -> dict[str, Any]:
    """Pull a JSON object out of whatever the user pasted."""
    if isinstance(raw, dict):
        return dict(raw)
    text = raw.strip()
    if text.startswith("```"):
        lines = [ln for ln in text.splitlines() if not ln.startswith("```")]
        text = "\n".join(lines).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise PromptError("aucun objet JSON trouvé dans la réponse collée")
    try:
        decoded = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise PromptError(f"JSON invalide : {exc}") from exc
    if not isinstance(decoded, dict):
        raise PromptError("la réponse doit être un objet JSON")
    return decoded
