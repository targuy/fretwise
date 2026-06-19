#!/usr/bin/env python3
"""Générateur déterministe de fiches rig GP-180 (template, sans LLM).

Lit une table de faits curés (data/curated_facts.json) — où chaque entrée ne
porte QUE les champs spécifiques au morceau (tuning, guitare, ampli, effets,
fiabilité) — et l'étend dans le format .md complet de partitions/rigs/.

Tout le boilerplate (chaîne, bloc de compensation, EQ par défaut) et les
voicings d'ampli typiques vivent ici, pas dans les données. Cela rend
l'authoring d'un morceau quasi gratuit en tokens.

Usage :
    pixi run python tools/gen_fiche.py                 # génère tout curated_facts.json
    pixi run python tools/gen_fiche.py --only nirvana  # filtre sur le nom de fichier
    pixi run python tools/gen_fiche.py --dry-run       # affiche sans écrire
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "data" / "curated_facts.json"
RIGS = ROOT / "partitions" / "rigs"
DATE = "18-06-2026"

# Voicings d'ampli typiques GP-180 : (gain, bass, mid, treble, presence, level, cab).
# Point de départ crédible par modèle ; surchargeable par morceau.
_AMP_PROFILE: dict[str, tuple[int, int, int, int, int, int, str]] = {
    "Tweedy":           (40, 55, 50, 55, 50, 62, "Tweed 1x12"),
    "Bassman":          (45, 55, 52, 58, 55, 62, "Bassman 4x10"),
    "Foxy30":           (55, 50, 58, 60, 58, 60, "Blue 2x12"),
    "UK 45":            (50, 52, 58, 60, 58, 60, "Greenback 4x12"),
    "UK 50":            (55, 48, 60, 58, 55, 60, "UK Vintage 4x12"),
    "UK 900":           (72, 50, 55, 62, 60, 58, "UK Vintage 4x12"),
    "Solo100":          (78, 52, 52, 60, 62, 58, "UK Modern 4x12"),
    "Mesa Dual Recto":  (82, 55, 45, 58, 55, 56, "Mesa 4x12"),
    "Tremoverb":        (70, 54, 50, 56, 54, 58, "Mesa 4x12"),
    "ENGL Savage":      (85, 56, 48, 58, 58, 56, "ENGL 4x12"),
    "ENGL Gigmaster":   (75, 52, 52, 56, 56, 58, "ENGL 4x12"),
}

_RELIA = {
    "A": "A — Vérifié (gear documenté, sources fiables concordantes)",
    "B": "B — Solide (gear documenté, réglages dérivés du style)",
    "C": "C — Approximation de style (cohérent époque/genre, à affiner)",
    "D": "D — À confirmer (peu de références ; valeurs à l'oreille)",
}

_COMPENSATION = (
    "Compensation guitare :\n"
    "- Cible Strat (si original humbucker) : Gain +5, Bass −2, Mid +2, Treble −3, Presence −1\n"
    "- Cible SG/Les Paul (si original single coil) : Gain −5, Bass +2, Mid +2, Treble +3, Presence +2\n"
    "- Si guitare cible = guitare originale : aucune compensation"
)
_CHAIN = "NR → PRE → WAH → DST → N→S → AMP → CAB/IR → EQ → MOD → DLY → RVB → VOL"


def _g(d: dict, key: str, default: str) -> str:
    v = d.get(key)
    return str(v) if v not in (None, "") else default


def _amp_line(d: dict) -> tuple[str, str]:
    """Retourne (ligne_ampli, cab)."""
    model = _g(d, "amp", "UK 50")
    prof = _AMP_PROFILE.get(model, _AMP_PROFILE["UK 50"])
    g, b, m, t, p, lvl, cab = prof
    g = int(d.get("gain", g))
    cab = _g(d, "cab", cab)
    line = (f"{model} — Gain {g} · Bass {b} · Mid {m} · Treble {t} · "
            f"Presence {p} · Level {lvl}")
    return line, cab


def render(d: dict) -> str:
    artist = d["artist"]
    title = d["title"]
    amp_line, cab = _amp_line(d)
    relia = d.get("reliability", "C")
    notes = d.get("notes", []) or ["Régler les niveaux à l'oreille en comparant à l'enregistrement."]
    note_block = "\n".join(f"- {n}" for n in notes)
    sources = d.get("sources", []) or ["connaissance gear documentée (artiste/morceau)"]
    src_line = " ; ".join(sources)

    dst = _g(d, "dst", "Non")
    pre = _g(d, "pre", "off")
    mod = _g(d, "mod", "Non")
    dly = _g(d, "dly", "Non")
    rvb = _g(d, "rvb", "Room · Mix 8")
    wah = _g(d, "wah", "off")

    return f"""# Rig GP-180 — {artist} · {title}

Artiste : {artist}
Chanson : {title}
Album / période : {_g(d, "album", "Non documenté")}
Version ciblée : {_g(d, "version", "studio")}
Guitariste : {_g(d, "guitarist", "Non précisé")}
Rôle guitare : {_g(d, "role", "rythmique / lead selon section")}

Guitare originale : {_g(d, "guitar", "Non précisé")}
Micros originaux : {_g(d, "pickups", "Non précisé")}
Position micro : {_g(d, "pickup_pos", "à préciser selon section du morceau")}
Accordage : {_g(d, "tuning", "Mi standard (E standard)")}
Capo : {_g(d, "capo", "non")}
Guitare cible : identique à la guitare originale par défaut
{_COMPENSATION}

Objectif sonore : reproduction fidèle du son du morceau original, dans l'esprit du genre et de l'époque
Référence sonore principale : version {_g(d, "version", "studio")} originale de « {title} » par {artist}
Sources utilisées : {src_line}
Fiabilité : {_RELIA.get(relia, _RELIA["C"])}

Cœur sonore GP-180 :
- SnapTone / NAM : {_g(d, "snaptone", "Non")}
- AMP : {amp_line}
- CAB / IR : {cab}

Chaîne GP-180 :
{_CHAIN}

Réglages GP-180 :
- NR : {_g(d, "nr", "Gate 1 · Threshold −55 dB")}
- PRE : {pre}
- WAH : {wah}
- DST : {dst}
- N→S : Non
- AMP : {amp_line}
- CAB / IR : {cab} · Level 60
- EQ : {_g(d, "eq", "Guitar EQ 1 · neutre · à ajuster")}
- MOD : {mod}
- DLY : {dly}
- RVB : {rvb}
- VOL : {_g(d, "vol", "Level 60 · niveau final (boost solo +3 dB optionnel)")}

Notes de jeu :
{note_block}

Limites / compromis :
- {_g(d, "limit", "Réglages = point de départ ; position micro, attaque et volume guitare comptent autant.")}
- date_added : {DATE}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--facts", default=str(FACTS))
    ap.add_argument("--only", default="", help="Ne traiter que les fichiers contenant cette sous-chaîne")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    data = json.loads(Path(args.facts).read_text(encoding="utf-8"))
    songs = data.get("songs", data) if isinstance(data, dict) else data

    n = 0
    for d in songs:
        fname = d.get("file") or ""
        if not fname:
            print(f"SKIP (pas de 'file') : {d.get('artist')} - {d.get('title')}")
            continue
        if args.only and args.only.lower() not in fname.lower():
            continue
        md = render(d)
        if args.dry_run:
            print(f"--- {fname} ({d.get('reliability', 'C')}) ---")
        else:
            (RIGS / fname).write_text(md, encoding="utf-8")
        n += 1
    print(f"{'(dry-run) ' if args.dry_run else ''}{n} fiche(s) générée(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
