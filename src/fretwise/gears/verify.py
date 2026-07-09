"""On-demand AI re-verification of a gear.v2 sheet.

Some fiches are graded "C" (approximation fonctionnelle) or worse because the
original production batch couldn't find strong sources for a song's real rig.
This module lets the web UI build a copy-paste prompt for an external,
web-connected LLM to re-research the song and return a corrected
``songsgear.fretwise.gear.v2`` document, plus a validator for whatever JSON the
user pastes back before it overwrites the sheet on disk.

This is a human-in-the-loop shortcut, not the automated production pipeline in
``fretwise.gears.production`` (Ollama/OpenAI/Claude batch) — it targets a single
song and a chat LLM the user already has open.
"""

from __future__ import annotations

from typing import Any

from fretwise.gears.production.fretwise_export import MODULE_BY_MODEL
from fretwise.gears.production.tools.compact_fretwise_gears import COMPACT_SCHEMA_VERSION
from fretwise.rig import GP180_CHAIN, _canon_effect

_CONFIDENCE_LEVELS = ("high", "medium/high", "medium", "low", "unknown")
_MATCH_QUALITIES = ("exact", "close", "acceptable", "fallback")

# GP180_CHAIN uses the unicode arrow ("N→S"); MODULE_BY_MODEL's targets use the
# ASCII form. Canonicalize both through _canon_effect so grouping never splits
# the same slot into two buckets.
_SLOT_LABELS = {_canon_effect(slot): slot for slot in GP180_CHAIN}


def _models_by_slot() -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {slot: [] for slot in GP180_CHAIN}
    for model, module in MODULE_BY_MODEL.items():
        if not module:
            continue
        slot = _SLOT_LABELS.get(_canon_effect(module))
        if slot is not None:
            grouped[slot].append(model)
    return grouped


def _catalog_block() -> str:
    grouped = _models_by_slot()
    lines = []
    for slot in GP180_CHAIN:
        models = ", ".join(grouped[slot]) or "(pas de modèle dédié — laisser inactif)"
        lines.append(f"- **{slot}** : {models}")
    return "\n".join(lines)


_OUTPUT_TEMPLATE = """```json
{
  "schemaVersion": "%(schema_version)s",
  "song": {
    "artist": "%(artist)s",
    "title": "%(title)s",
    "album": "...",
    "year": null,
    "genre": "...",
    "subgenres": ["..."],
    "genreConfidence": "high|medium/high|medium|low|unknown"
  },
  "credits": {
    "guitar": {
      "guitaristsText": "...",
      "type": "...",
      "modelsText": "...",
      "confidence": "high|medium/high|medium|low|unknown",
      "evidence": "...",
      "notes": "...",
      "source": "..."
    }
  },
  "tone": {
    "target": "...",
    "profile": "...",
    "summary": "...",
    "mustHave": ["..."],
    "avoid": ["..."],
    "gearClues": ["..."],
    "corrections": ["..."],
    "confidence": "high|medium/high|medium|low|unknown",
    "needsReview": false
  },
  "rig": {
    "name": "...",
    "confidence": "high|medium/high|medium|low|unknown",
    "equipment": {"model": "Valeton GP-180"},
    "recommendedGuitar": "...",
    "output": "...",
    "blocks": [
      {
        "module": "AMP",
        "model": "...",
        "active": true,
        "settings": {"gain": 50, "bass": 50, "middle": 50, "treble": 50, "presence": 50, "level": 50},
        "purpose": "...",
        "matchQuality": "exact|close|acceptable|fallback",
        "gap": "...",
        "alternatives": [{"model": "...", "reason": "..."}]
      }
    ]
  },
  "improvements": {
    "summary": "...",
    "proposals": [
      {
        "priority": "...",
        "type": "...",
        "target": "...",
        "recommendedAsset": "...",
        "reason": "...",
        "whenToUse": "...",
        "expectedGain": "..."
      }
    ]
  }
}
```"""


def build_gear_verification_prompt(
    artist: str, title: str, *, existing: dict[str, Any] | None = None
) -> str:
    """Build a copy-paste prompt asking an LLM to (re-)verify one song's gear sheet.

    ``existing`` is the current ``gear.v2`` document (if any) — when present the
    prompt asks the LLM to double-check/correct it rather than start from
    scratch, which is the "en cas de doute" workflow this exists for.
    """
    artist = (artist or "").strip()
    title = (title or "").strip()

    context_lines = [f"- Artiste : {artist or '?'}", f"- Chanson : {title or '?'}"]
    review_section = ""
    if isinstance(existing, dict) and existing:
        import json as _json

        current_grade = None
        rig = existing.get("rig") if isinstance(existing.get("rig"), dict) else {}
        tone = existing.get("tone") if isinstance(existing.get("tone"), dict) else {}
        current_grade = rig.get("confidence") or tone.get("confidence")
        review_section = (
            f"\nUne fiche existe déjà (confiance actuelle : {current_grade or 'inconnue'}). "
            "Vérifie chaque information avec des sources fiables (interviews, rig "
            "rundowns, Ultimate Guitar/Equipboard, forums spécialisés) et corrige ce "
            "qui est faux ou approximatif plutôt que de tout réinventer :\n\n"
            f"```json\n{_json.dumps(existing, ensure_ascii=False, indent=2)}\n```\n"
        )

    prompt = f"""# Vérification de la fiche gear — {artist or '?'} – {title or '?'}

Tu es un expert en équipement guitare (rigs, amplis, pédales) et en configuration
Valeton GP-180 (multi-effets à modélisation, 12 emplacements en chaîne).

## Contexte
{chr(10).join(context_lines)}
{review_section}
## Ta mission
1. Recherche le matériel réellement utilisé pour cette chanson : guitare, micros,
   position micro, accordage, ampli(s), pédales, réglages. Croise plusieurs
   sources fiables (interviews, rig rundowns, Equipboard, forums spécialisés)
   avant de conclure.
2. Traduis ce matériel en configuration Valeton GP-180 : pour chaque emplacement
   actif de la chaîne ({' → '.join(GP180_CHAIN)}), choisis le modèle le plus
   proche parmi le catalogue ci-dessous. Ne laisse actif que les emplacements
   pertinents pour ce son.
3. Indique un niveau de confiance honnête pour chaque information
   ({', '.join(_CONFIDENCE_LEVELS)}) — ne survends jamais une donnée incertaine ;
   documente les limites/compromis dans les champs prévus (``gap``, ``avoid``,
   ``corrections``) plutôt que de deviner en silence.

## Catalogue des modèles GP-180 par emplacement
{_catalog_block()}

## Format de sortie attendu
Réponds uniquement avec un objet JSON valide, sans texte ni commentaire autour,
respectant strictement ce gabarit (adapte les valeurs, garde les clés) :

{_OUTPUT_TEMPLATE % {
    "schema_version": COMPACT_SCHEMA_VERSION,
    "artist": artist or "?",
    "title": title or "?",
}}
"""
    return prompt


def validate_gear_v2(doc: Any) -> dict[str, Any]:
    """Validate a pasted ``gear.v2`` document before it overwrites a sheet.

    Returns ``{"ok": bool, "errors": [...], "warnings": [...]}``. Deliberately
    lenient on shape (this is a human pasting an LLM's best-effort JSON, not a
    machine-generated export) — only the fields the web renderer and the
    canonical filename actually depend on are required.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(doc, dict):
        return {"ok": False, "errors": ["Le document n'est pas un objet JSON."], "warnings": []}

    if doc.get("schemaVersion") != COMPACT_SCHEMA_VERSION:
        errors.append(f"schemaVersion doit être {COMPACT_SCHEMA_VERSION!r}.")

    song = doc.get("song") if isinstance(doc.get("song"), dict) else {}
    if not str(song.get("artist") or "").strip():
        errors.append("song.artist est manquant.")
    if not str(song.get("title") or "").strip():
        errors.append("song.title est manquant.")

    rig = doc.get("rig") if isinstance(doc.get("rig"), dict) else {}
    blocks = rig.get("blocks") if isinstance(rig.get("blocks"), list) else None
    if not blocks:
        errors.append("rig.blocks est manquant ou vide.")
        blocks = []

    for i, block in enumerate(blocks):
        if not isinstance(block, dict):
            errors.append(f"rig.blocks[{i}] n'est pas un objet.")
            continue
        module = str(block.get("module") or "")
        if not module or _canon_effect(module) not in _SLOT_LABELS:
            errors.append(f"rig.blocks[{i}].module n'est pas un emplacement GP-180 reconnu : {module!r}")
        match_quality = block.get("matchQuality")
        if match_quality is not None and str(match_quality).strip().lower() not in _MATCH_QUALITIES:
            warnings.append(f"rig.blocks[{i}].matchQuality est inhabituel : {match_quality!r}")

    return {"ok": not errors, "errors": errors, "warnings": warnings}
