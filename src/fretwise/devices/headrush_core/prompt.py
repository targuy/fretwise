"""Shared prompt and validation for authoring a HeadRush Core rig.

The manual flow follows :mod:`fretwise.gears.verify`: the user copies a prompt
into their LLM and pastes its response. The optional server-side API flow uses
the same prompt and validates its returned JSON with the same domain checks.
Neither flow sends the result to the instrument automatically.

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
import math

# Existing binding documents contain heterogeneous JSON values. Runtime shape
# checks below preserve that public API while rejecting malformed provider input.
from typing import Any

from fretwise.devices.headrush_core.catalog import Catalog
from fretwise.devices.headrush_core.chain import FREE_SLOTS, FROZEN_HEAD, REVERB_SLOT
from fretwise.devices.headrush_core.plan import BINDING_SCHEMA_VERSION, GENERATED_PREFIX, build_plan
from fretwise.devices.headrush_core.prompt_catalog import (
    block_parameters,
    catalog_vocabulary,
    example_params,
    offered_modules,
)

_CONFIDENCE = frozenset({"high", "medium/high", "medium", "low", "unknown"})


class PromptError(ValueError):
    """The pasted response is not a usable rig document."""


def _layout_rules() -> str:
    """Describe the current importer's layout, not a universal hardware restriction."""
    head = "\n".join(
        f"| {slot} | {role} | figé |" for slot, role in sorted(FROZEN_HEAD.items())
    )
    return f"""### Emplacement des blocs

Ce profil est imposé par l'importeur FretWise actuel, inspiré d'un corpus de rigs.
Ce n'est pas une restriction universelle du HeadRush. Un seul bloc par rôle figé;
Amp et Clone se partagent le slot 6. La queue conserve l'ordre fourni.

| Slot | Rôle | |
|---|---|---|
{head}
| {min(FREE_SLOTS)}–{max(FREE_SLOTS)} | libres : EQ, modulation, volume, delay, pitch | au choix |
| {REVERB_SLOT} | réverbe | figé |

Tu n'écris PAS les numéros de slot : FretWise applique ce placement. Un ordre
historique différent peut donc nécessiter une adaptation à expliquer dans `why`.
Ne répète pas un module. N'invente pas de jumeau avec un suffixe « 2 » : son nom
doit être fourni par le catalogue et son rôle doit tenir dans ce profil.
Deux amplis ou deux réverbes se disputent leur slot figé, même si l'appareil
possède leurs types d'instances. N'ajoute aucun effet pour remplir un slot."""


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
        guidance: Free-text target version, part, guitar/pickups, input level,
            listening system and tonal preferences supplied by the user.

    Returns:
        A Markdown prompt.
    """
    song = f"{artist} — {title}".strip(" —")
    mode = "corriger" if existing else "créer"
    rig_name = f"{GENERATED_PREFIX}{artist} - {title}".strip()
    modules = offered_modules(catalog)
    example_module = "Amp" if "Amp" in modules else next(iter(modules), "")

    parts = [
        f"# {mode.capitalize()} un rig HeadRush Core — {song}",
        "",
        "Conçois une adaptation documentée du son de guitare ciblé sur un "
        "**HeadRush Core**, firmware "
        f"`{catalog.app_version}`.",
        "",
        "## Cible et preuves",
        "",
        "Lis la demande utilisateur et le document existant : version/enregistrement, "
        "partie (clair, rythmique, solo), guitare et micros utilisés, niveau d'entrée, "
        "écoute (casque, FRFR, ampli/retour), préférences. Si ces informations manquent, "
        "ne les invente pas : choisis une seule cible de travail explicitée dans "
        "`tone.summary` et indique les inconnues dans `why`. Un rig ne promet pas de "
        "reproduire toutes les parties, couches studio ou chaînes parallèles.",
        "Priorité aux sources liées à cette prise et cette partie : témoignage de "
        "l'artiste/ingénieur et documents de session, puis recoupements datés. "
        "Le matériel live ou actuel ne prouve pas le matériel studio; une information "
        "sur un album ou un autre titre ne prouve pas cette prise. Sans recherche web "
        "disponible, annonce cette limite et ne fabrique ni citation ni URL.",
        "Dans `sources`, conserve des chaînes de texte donnant auteur/titre/date ou "
        "URL vérifiable et portée de la preuve. Dans `why`, distingue **FAIT SOURCÉ** "
        "(ou absence de preuve), **ADAPTATION** (modèle disponible, circuit non confirmé, "
        "guitare/micros/écoute différents) et **À TESTER** (réglages initiaux et contrôle "
        "à niveau égal). Ne transforme pas une famille d'ampli en circuit ou réglage exact.",
        "`confidence` exprime la solidité documentaire de la proposition : "
        "high, medium/high, medium, low ou unknown. Ce n'est ni une note de fidélité audio "
        "ni la preuve d'une écoute ou d'un import réel. Les réglages restent à ajuster "
        "à l'écoute; n'annonce aucune reproduction garantie.",
        "",
        "## Règles absolues",
        "",
        "1. **N'invente aucun nom.** Chaque `module` et chaque valeur d'énumération "
        "doit être copié littéralement depuis les listes ci-dessous. Un nom absent "
        "fait rejeter le document entier.",
        "2. **Valeurs en unités d'affichage**, pas en 0-1 : `62` pour 62 %, `300` "
        "pour 300 ms, `-3` pour −3 dB. FretWise convertit.",
        "3. Respecte le profil de placement ci-dessous et les limites de l'importeur. "
        "La disponibilité de fichiers, les scènes et le routage parallèle ne sont "
        "pas décrits par ce binding.",
        "4. Garde uniquement les blocs utiles, sans minimum. Vise au plus 9 blocs "
        "par sobriété, pas comme limite matérielle. Le CPU doit être mesuré sur le "
        "rig réel : le nombre de blocs ne permet pas de le prédire.",
        "5. Réponds **uniquement** par l'objet JSON, sans commentaire autour.",
        "",
        _layout_rules(),
        "",
        catalog_vocabulary(catalog),
        block_parameters(catalog),
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
                    "summary": "version et partie ciblées; contexte manquant à confirmer",
                    "mustHave": ["…"],
                    "avoid": ["…"],
                },
                "confidence": "unknown",
                "sources": [],
                "blocks": [
                    {
                        "module": example_module,
                        "why": "FAIT SOURCÉ : à documenter; ADAPTATION : à expliquer; "
                        "À TESTER : réglages initiaux à comparer à niveau égal",
                        "params": example_params(catalog, example_module),
                    }
                ],
            },
            indent=1,
            ensure_ascii=False,
        ),
        "```",
        "",
        "L'exemple illustre le format, pas le son du morceau. Garde exactement "
        "les champs de ce binding; n'ajoute pas de champ d'audit ou de contexte.",
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
    parts += [
        "",
        "Avant de produire le JSON, contrôle chaque paire `module` / clé de `params` "
        "dans la ligne de ce module : aucune clé empruntée à un autre EQ ou ampli; "
        "respecte ses énumérations et bornes. Retire tout bloc sans utilité musicale, "
        "sans remplir les slots. Respecte le placement et les limites de fichiers "
        "signalées; vérifie la portée réelle de chaque source.",
    ]
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
    _validate_binding(document, catalog)

    document.setdefault("schemaVersion", BINDING_SCHEMA_VERSION)
    device = document.setdefault("device", {})
    device.setdefault("deviceId", "headrush-core")
    device.setdefault("appVersion", catalog.app_version)
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


def _text_list(value: object, label: str) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PromptError(f"{label} doit être une liste de chaînes de texte")


def _validate_binding(document: dict[str, Any], catalog: Catalog) -> None:
    """Check JSON shapes before the planner touches untrusted response fields."""
    if "schemaVersion" in document and document["schemaVersion"] != BINDING_SCHEMA_VERSION:
        raise PromptError(f"schemaVersion doit être {BINDING_SCHEMA_VERSION!r}")
    for section in ("device", "rig", "song", "tone"):
        if section in document and not isinstance(document[section], dict):
            raise PromptError(f"{section} doit être un objet JSON")
    device = document.get("device", {})
    for name, expected in (("deviceId", "headrush-core"), ("appVersion", catalog.app_version)):
        if name in device and device[name] != expected:
            raise PromptError(f"device.{name} doit être {expected!r}")
    for section, names in (("rig", ("name",)), ("song", ("artist", "title")),
                           ("tone", ("summary",))):
        values = document.get(section, {})
        for name in names:
            if name in values and not isinstance(values[name], str):
                raise PromptError(f"{section}.{name} doit être une chaîne de texte")
    program_change = document.get("rig", {}).get("programChange")
    if program_change is not None and (
        isinstance(program_change, bool) or not isinstance(program_change, int)
        or not 0 <= program_change <= 127
    ):
        raise PromptError("rig.programChange doit être null ou un entier entre 0 et 127")
    if "confidence" in document and (
        not isinstance(document["confidence"], str) or document["confidence"] not in _CONFIDENCE
    ):
        raise PromptError("confidence doit être high, medium/high, medium, low ou unknown")
    if "sources" in document:
        _text_list(document["sources"], "sources")
    tone = document.get("tone", {})
    for name in ("mustHave", "avoid"):
        if name in tone:
            _text_list(tone[name], f"tone.{name}")
    blocks = document.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise PromptError("blocks doit être une liste non vide d'objets JSON")
    for index, block in enumerate(blocks):
        label = f"blocks[{index}]"
        if not isinstance(block, dict):
            raise PromptError(f"{label} doit être un objet JSON")
        if not isinstance(block.get("module"), str) or not block["module"].strip():
            raise PromptError(f"{label}.module doit être un nom de module non vide")
        if "why" in block and not isinstance(block["why"], str):
            raise PromptError(f"{label}.why doit être une chaîne de texte")
        params = block.get("params", {})
        if not isinstance(params, dict):
            raise PromptError(f"{label}.params doit être un objet JSON")
        for name, value in params.items():
            if not isinstance(name, str) or not isinstance(value, (str, int, float, bool)):
                raise PromptError(f"{label}.params contient un nom ou une valeur non scalaire")
            if isinstance(value, float) and not math.isfinite(value):
                raise PromptError(f"{label}.params.{name} doit être un nombre fini")


def _decode(raw: str | dict[str, Any]) -> dict[str, Any]:
    """Pull a JSON object out of whatever the user pasted."""
    if isinstance(raw, dict):
        return dict(raw)
    if not isinstance(raw, str):
        raise PromptError("la réponse doit être du texte JSON ou un objet JSON")
    text = raw.strip()
    if text.startswith("```"):
        lines = [ln for ln in text.splitlines() if not ln.startswith("```")]
        text = "\n".join(lines).strip()
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        # Preserve the existing manual paste workflow, including surrounding prose.
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise PromptError("aucun objet JSON trouvé dans la réponse collée") from None
        try:
            decoded = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise PromptError(f"JSON invalide : {exc}") from exc
    if not isinstance(decoded, dict):
        raise PromptError("la réponse doit être un objet JSON")
    return decoded
