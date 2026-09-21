"""Render only catalog choices the current binding importer can express.

The catalog describes the device, not every capability of FretWise's importer.
In particular, file selectors and reversed numeric bounds cannot currently be
written through ``device_value``. Keep those gaps visible without inventing data.
"""

from __future__ import annotations

import json
import re

from fretwise.devices.headrush_core.catalog import BlockSchema, Catalog, ParamSchema

OFFERED_CATEGORIES = (
    "Amp", "Cab", "Clone", "Overdrive", "Distortion", "Eq", "Compressor",
    "Delay", "Reverb", "Chorus", "Phaser", "Vib", "Filter", "Pitch",
    "Dynamics", "Utility",
)

_PLUMBING = frozenset({
    "PreGain", "PostGain", "PresetName", "Colour", "In-Bus", "Doubling",
    "DoubleMode", "Balance", "Width", "StereoAmp", "FileMissing", "Tails",
})
_PRINTF_NUMBER = re.compile(r"%(?!%)[-+ #0]*\d*(?:\.\d+)?[fFeEgGdi]")


def offered_modules(catalog: Catalog) -> tuple[str, ...]:
    """Return selectable guitar modules in stable category order."""
    return tuple(dict.fromkeys(
        module
        for category in OFFERED_CATEGORIES
        for module in catalog.category_blocks.get(category, ())
        if catalog.block(module) is not None and catalog.module_type_id(module) is not None
    ))


def _visible(block: BlockSchema, param: ParamSchema) -> bool:
    if param.read_only or param.name in _PLUMBING or param.name.startswith("Slt"):
        return False
    # A suffix 2 alone is insufficient: Bit2 and EQ band 2 are real controls.
    doubled_channel = (
        param.name.endswith("2") and block.param("Doubling") is not None
        and block.param(param.name[:-1]) is not None
    )
    return not doubled_channel


def _unsupported_reason(param: ParamSchema) -> str:
    if not param.is_writable_safely:
        return "conversion non prise en charge"
    if param.type == "boolean" or param.options:
        return ""
    if param.type not in {"number", "integer"}:
        return "chaîne/fichier non pris en charge par le binding"
    if param.minimum is None or param.maximum is None:
        return "bornes absentes du catalogue"
    if param.minimum > param.maximum:
        return "bornes inversées, refusées par le convertisseur actuel"
    return ""


def writable_params(block: BlockSchema) -> tuple[ParamSchema, ...]:
    """Return parameters with an explicit representation accepted by the importer."""
    return tuple(
        param for param in block.params
        if _visible(block, param) and not _unsupported_reason(param)
    )


def _enum_references(catalog: Catalog) -> dict[tuple[str, ...], str]:
    references: dict[tuple[str, ...], str] = {}
    for module in offered_modules(catalog):
        block = catalog.block(module)
        assert block is not None
        for param in writable_params(block):
            # device_value accepts booleans before checking their option labels.
            if param.options and param.type != "boolean":
                references.setdefault(param.options, f"{module}.{param.name}")
    return references


def catalog_vocabulary(catalog: Catalog) -> str:
    """Render exact modules and complete, deduplicated enumeration labels."""
    offered = frozenset(offered_modules(catalog))
    lines = ["### Blocs disponibles (noms EXACTS, par catégorie)", ""]
    for category in OFFERED_CATEGORIES:
        modules = [name for name in catalog.category_blocks.get(category, ()) if name in offered]
        if modules:
            lines.append(f"- **{category}** : {', '.join(modules)}")
    lines += ["", "### Énumérations complètes", "",
              "Chaque référence ci-dessous contient tous ses choix. Une même liste est "
              "partagée quand plusieurs paramètres ont exactement les mêmes valeurs.", ""]
    for options, reference in _enum_references(catalog).items():
        lines.append(f"- `{reference}` : {json.dumps(options, ensure_ascii=False)}")
    return "\n".join(lines)


def _number(value: float) -> str:
    # Preserve fractional bounds: rounding Resampling to six digits falls outside
    # the importer's tolerance at the lower boundary.
    return str(int(value)) if float(value).is_integer() else repr(value)


def block_parameters(catalog: Catalog) -> str:
    """Render importable controls and explicit catalog/importer limitations."""
    references = _enum_references(catalog)
    lines = [
        "### Paramètres de chaque bloc (noms EXACTS)", "",
        "N'écris que les paramètres proposés ici. Nombres en unités d'affichage; "
        "true/false pour les booléens; libellés exacts pour les enums. Une plage sans unité "
        "n'autorise pas à inventer des Hz, dB ou %. Les paramètres d'un même bloc peuvent "
        "dépendre du modèle sélectionné : cette dépendance n'est pas décrite par ce catalogue.",
        "",
    ]
    unsupported: list[str] = []
    for module in offered_modules(catalog):
        block = catalog.block(module)
        assert block is not None
        bits = []
        for param in writable_params(block):
            if param.type == "boolean":
                bits.append(f"{param.name} (true/false)")
            elif param.options:
                bits.append(f"{param.name} (voir `{references[param.options]}`)")
            else:
                assert param.minimum is not None and param.maximum is not None
                unit = _PRINTF_NUMBER.sub("", param.unit_format or "").replace("%%", "%")
                unit = " ".join(unit.split())
                bounds = f"{_number(param.minimum)} à {_number(param.maximum)}"
                bits.append(f"{param.name} [{bounds}]{(' ' + unit) if unit else ''}")
        if bits:
            lines.append(f"- **{module}** : {', '.join(bits)}")
        for param in block.params:
            reason = _unsupported_reason(param)
            if _visible(block, param) and reason:
                unsupported.append(f"`{module}.{param.name}` ({reason})")
    if unsupported:
        lines += ["", "### Paramètres non proposés à l'import", "",
                  "; ".join(unsupported) + "."]
    lines += [
        "",
        "Les fichiers NAM, IR, clones et convolutions disponibles sur votre appareil ne sont "
        "pas inventoriés ici. Le binding actuel ne charge pas de chemin de fichier. "
        "N'ajoute pas un bloc dépendant d'un fichier sans confirmation de son chargement "
        "dans le rig de départ; propose un modèle interne et explique la substitution dans `why`.",
        "",
        "Un paramètre omis n'est pas remis à zéro : la création part de `#FW - SCRATCH`, "
        "la correction du rig existant, et seules les valeurs demandées sont écrites. "
        "Leurs valeurs actuelles ne sont pas incluses ici. Explicite les réglages utiles "
        "à la cible sans inventer les paramètres actifs; signale les contrôles non vérifiés "
        "dans `why` sous À TESTER.",
    ]
    return "\n".join(lines)


def example_params(catalog: Catalog, module: str) -> dict[str, str | float]:
    """Return a small example whose names and values come from this catalog."""
    block = catalog.block(module)
    if block is None:
        return {}
    params: dict[str, str | float] = {}
    for param in writable_params(block):
        if param.name == "Type" and param.options and param.type != "boolean":
            params[param.name] = param.options[0]
        elif param.name in {"GainA", "Master"}:
            if param.minimum is not None and param.maximum is not None:
                params[param.name] = (param.minimum + param.maximum) / 2
    return params
