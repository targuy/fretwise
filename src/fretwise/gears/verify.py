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

# Copy/paste workflow: FretWise does not call a provider, API, or batch service.
_INTERACTIVE_LLM_GUIDANCE = """## Mode interactif et modèle conseillé
- Utilise un LLM dans son interface web : aucun appel API n'est fait par FretWise.
- Modèle conseillé : **GPT-5.6 Sol**, raisonnement élevé, avec recherche Web activée.
  Si indisponible, choisis le modèle GPT-5 de raisonnement le plus avancé proposé.
- Colle ce prompt, puis recolle ici uniquement l'objet JSON retourné."""

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
        "referenceModel": "nom réel documenté, ou null",
        "active": true,
        "settings": {
          "gain": 50, "bass": 50, "middle": 50,
          "treble": 50, "presence": 50, "level": 50
        },
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


def _prompt_preamble(artist: str, title: str) -> str:
    """Return shared song identity and GP-180 constraints for AI prompts."""

    return f"""## Cible
- Artiste : {artist or '?'}
- Morceau : {title or '?'}

## Règles non négociables
- Distingue faits sourcés, hypothèses et adaptations pratiques GP-180.
- Priorité sources : interview/crédit/rig rundown officiel, puis presse spécialisée.
  Forums, Equipboard et agrégateurs servent seulement d'indices à recouper.
- N'importe jamais un équipement d'un autre morceau sans preuve propre à celui-ci.
- Si versions studio/live diffèrent, cible une seule version et nomme-la dans `tone.target`.
- Utilise uniquement les modèles GP-180 du catalogue ci-dessous. N'invente aucun nom.
- `rig.blocks[].model` stocke toujours le libellé exact du GP-180. Si une source cite
  une marque, garde son nom dans `referenceModel`, puis traduis-le vers le clone Valeton.
  Exemples : Vox AC30 → Foxy 30TB/Foxy 30N selon variante, EVH 5150 → EV 51,
  Marshall → UK, Mesa/Boogie → Mess.
  Applique même logique aux CAB et pédales. Ne remplace jamais le libellé GP-180 par la marque.
- `rig.blocks` contient uniquement les modules actifs et utiles. Un module absent = bypass.
- Réglages 0–100 : points de départ réalistes, jamais présentés comme réglages historiques.
- Réponse : un seul objet JSON valide, sans Markdown ni commentaire.

## Catalogue GP-180
{_catalog_block()}
"""


def _format_output_template(artist: str, title: str) -> str:
    """Return JSON output contract populated with immutable song identity."""

    return _OUTPUT_TEMPLATE % {
        "schema_version": COMPACT_SCHEMA_VERSION,
        "artist": artist or "?",
        "title": title or "?",
    }


def build_gear_creation_prompt(artist: str, title: str) -> str:
    """Build a concise prompt creating one ``gear.v2`` sheet from scratch."""

    artist = (artist or "").strip()
    title = (title or "").strip()
    return f"""# Création fiche gear FretWise

Tu es spécialiste rigs guitare et Valeton GP-180. Crée une fiche factuelle et jouable.

{_INTERACTIVE_LLM_GUIDANCE}

{_prompt_preamble(artist, title)}
## Travail
1. Identifie version/section de référence, puis matériel réellement documenté.
2. Croise deux sources indépendantes pour chaque affirmation importante.
3. Traduis le son vers le GP-180 avec chaîne minimale et fidélité perceptive.
4. Si preuve insuffisante : confiance basse, `gap` court, aucune invention.
5. Renseigne `credits.guitar.source` avec titres ou URL des meilleures sources.

## Contrat JSON
Garde exactement ces clés. Phrases courtes. Tableaux sans doublons. Modules inactifs omis.

{_format_output_template(artist, title)}
"""


def build_gear_verification_prompt(
    artist: str, title: str, *, existing: dict[str, Any] | None = None
) -> str:
    """Build a concise prompt auditing and correcting one ``gear.v2`` sheet."""

    artist = (artist or "").strip()
    title = (title or "").strip()
    review_section = "Aucune fiche fournie : utilise plutôt le prompt de création."
    if isinstance(existing, dict) and existing:
        import json as _json

        rig_obj = existing.get("rig")
        tone_obj = existing.get("tone")
        rig = rig_obj if isinstance(rig_obj, dict) else {}
        tone = tone_obj if isinstance(tone_obj, dict) else {}
        current_grade = rig.get("confidence") or tone.get("confidence")
        review_section = (
            "Une fiche existe déjà. "
            f"Confiance actuelle : {current_grade or 'inconnue'}.\n"
            "```json\n"
            f"{_json.dumps(existing, ensure_ascii=False, indent=2)}\n"
            "```"
        )

    return f"""# Vérification fiche gear FretWise

Tu es auditeur de rigs guitare et spécialiste Valeton GP-180. Corrige sans réécrire
ce qui est déjà exact.

{_INTERACTIVE_LLM_GUIDANCE}

{_prompt_preamble(artist, title)}
## Fiche actuelle
{review_section}

## Travail
1. Contrôle identité, version ciblée, crédits, guitare, micro, accordage, ampli et effets.
2. Chaque affirmation importante : confirme par deux sources indépendantes, rétrograde la
   confiance ou supprime. Une source recopiée sur plusieurs sites compte une fois.
3. Vérifie modèles contre catalogue GP-180. Retire modules non prouvés ou inutiles.
4. Préserve valeurs exactes. `tone.corrections` contient seulement changements réels et courts.
5. Renseigne `credits.guitar.source` avec titres ou URL des meilleures sources.

## Contrat JSON
Retourne document complet corrigé avec exactement ces clés. Phrases courtes. Modules
inactifs omis. Aucun champ d'audit supplémentaire.

{_format_output_template(artist, title)}
"""


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

    song_obj = doc.get("song")
    song = song_obj if isinstance(song_obj, dict) else {}
    if not str(song.get("artist") or "").strip():
        errors.append("song.artist est manquant.")
    if not str(song.get("title") or "").strip():
        errors.append("song.title est manquant.")

    rig_obj = doc.get("rig")
    rig = rig_obj if isinstance(rig_obj, dict) else {}
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
            errors.append(
                f"rig.blocks[{i}].module n'est pas un emplacement GP-180 reconnu : {module!r}"
            )
        match_quality = block.get("matchQuality")
        if match_quality is not None and str(match_quality).strip().lower() not in _MATCH_QUALITIES:
            warnings.append(f"rig.blocks[{i}].matchQuality est inhabituel : {match_quality!r}")

    return {"ok": not errors, "errors": errors, "warnings": warnings}
