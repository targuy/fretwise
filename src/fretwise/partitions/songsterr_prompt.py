"""Régénère prompt-songsterr-<date>.md avec la procédure javascript_tool éprouvée.

Version de travail calquée sur exports/prompt-songsterr-2026-05-15b.md (zéro
screenshot, javascript_tool uniquement, IDs stables control-export /
control-export-gp / export_modal).

Sources des chansons (dans l'ordre) :
    1. <tempdir>/songs100.json s'il existe (liste [[artist, title], ...])
    2. sinon, re-parse le prompt-songsterr-<date>.md du jour à la racine

Usage :
    python -m fretwise.partitions.songsterr_prompt [--root PATH]
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from fretwise.partitions import paths
from fretwise.partitions.console import ensure_printable_output


def load_songs(root: Path, date: str) -> list[tuple[str, str]]:
    """Charge la liste (artist, title) depuis le cache temp ou le prompt du jour."""
    cached = Path(tempfile.gettempdir()) / "songs100.json"
    if cached.exists():
        with open(cached, encoding="utf-8") as f:
            return [tuple(x) for x in json.load(f)]
    src = root / f"prompt-songsterr-{date}.md"
    with open(src, encoding="utf-8") as f:
        lines = f.read().split("\n")
    out = []
    for line in lines:
        m = re.match(r"^>?\s*(\d+)\. (?:\*\*)?(.+?)(?:\*\*)? [—\-] (.+?)(?:\*\*)?$", line)
        if m:
            out.append((m.group(2).strip().rstrip("*"), m.group(3).strip().rstrip("*")))
    return out


def build(songs: list[tuple[str, str]], gp_dir: Path) -> str:
    """Construit le texte du prompt Songsterr (procédure javascript_tool, IDs stables)."""
    n = len(songs)
    lines: list[str] = []
    add = lines.append
    add("0 screenshot. 0 verbosity. 0 read_page. 0 find. 1 ligne par chanson.")
    add("")
    add(f"Télécharge les {n} chansons suivantes en Guitar Pro depuis Songsterr "
        "(abonnement Plus actif).")
    add("Utilise **exclusivement `javascript_tool`** — jamais `read_page`, `find`, `screenshot`.")
    add("")
    add("---")
    add("")
    add("## SONGSTERR — Téléchargement Guitar Pro (zéro screenshot)")
    add("")
    add("### Contexte")
    add("- Chrome sur https://www.songsterr.com, abonnement Plus actif")
    add("- Langue de l'interface : française (mais les IDs restent en anglais)")
    add("- Formats disponibles dans le dialog : MIDI et Guitar Pro uniquement")
    add("")
    add("---")
    add("")
    add("### Sélecteurs stables (tous testés, tous par ID)")
    add("")
    add("| Élément | Sélecteur garanti |")
    add("|---|---|")
    add("| Bouton Download | `button#control-export` |")
    add("| Dialog de format | `form#export_modal` |")
    add("| Bouton Guitar Pro | `button#control-export-gp` |")
    add("| Bouton MIDI (à ignorer) | `button#control-export-midi` |")
    add("| Premier résultat de recherche | `main a[href^=\"/a/wsa/\"]:not([href*=\"/r\"])` "
        "— premier élément |")
    add("")
    add("---")
    add("")
    add("### Construction de l'URL de recherche")
    add("- Paramètre `&inst=guitar` inclus → filtre guitare dès l'URL, pas de filtrage manuel")
    add("- Format : `https://www.songsterr.com/?pattern=TITRE+ARTISTE&inst=guitar`")
    add("- Retire `The ` en début d'artiste, supprime `/`, `&`, apostrophes, caractères spéciaux")
    add("")
    add("Exemples :")
    add("- `AC/DC - Rock and Roll Ain't Noise Pollution` → "
        "`/?pattern=Rock+and+Roll+Aint+Noise+Pollution+ACDC&inst=guitar`")
    add("- `The Beatles - Back in the USSR` → `/?pattern=Back+in+the+USSR+Beatles&inst=guitar`")
    add("- `Blink-182 - Dammit` → `/?pattern=Dammit+Blink+182&inst=guitar`")
    add("")
    add("---")
    add("")
    add("### Procédure pour chaque chanson — 5 étapes, 0 screenshot")
    add("")
    add("**Étape 1 — Navigate**")
    add("`navigate → https://www.songsterr.com/?pattern=<TITRE>+<ARTISTE>&inst=guitar`")
    add("")
    add("**Étape 2 — Vérifier et cliquer le premier résultat**")
    add("```javascript")
    add("const links = Array.from(document.querySelectorAll('main a[href^=\"/a/wsa/\"]'))")
    add("  .filter(a => !a.getAttribute('href').includes('/r') && "
        "a.textContent.trim().length > 0);")
    add("const first = links[0];")
    add("const name = first?.querySelector('[data-field=\"name\"]')?.textContent?.trim();")
    add("const artist = first?.querySelector('[data-field=\"artist\"]')?.textContent?.trim();")
    add("first?.click();")
    add("({ clicked: !!first, href: first?.getAttribute('href'), name, artist })")
    add("```")
    add("→ Vérifier que `name` et `artist` correspondent à la chanson cherchée.")
    add("→ Si non : chercher le bon lien dans `links` par correspondance `name`/`artist` "
        "et cliquer.")
    add("→ Si `links` est vide : émettre `INDISPONIBLE` et passer à la suivante.")
    add("")
    add("**Étape 3 — Attendre la page tablature**")
    add("```javascript")
    add("({ isTabPage: window.location.pathname.startsWith('/a/wsa/'), "
        "url: window.location.href })")
    add("```")
    add("→ Si `isTabPage: false` → wait 1s et réessayer.")
    add("")
    add("**Étape 4 — Cliquer Download**")
    add("```javascript")
    add("document.getElementById('control-export')?.click();")
    add("({ clicked: !!document.getElementById('control-export') })")
    add("```")
    add("")
    add("**Étape 5 — Cliquer Guitar Pro**")
    add("```javascript")
    add("const modal = document.getElementById('export_modal');")
    add("const gpBtn = document.getElementById('control-export-gp');")
    add("gpBtn?.click();")
    add("({ modalWasOpen: !!modal, gpBtnFound: !!gpBtn, done: true })")
    add("```")
    add("→ `done: true` = téléchargement déclenché. Modal se ferme automatiquement.")
    add("→ Si `gpBtnFound: false` → réexécuter étape 4 puis étape 5.")
    add("")
    add("---")
    add("")
    add("### Règles absolues")
    add("- **JAMAIS** `button#control-export-midi`")
    add("- **JAMAIS** screenshot pour naviguer ou vérifier")
    add("- **JAMAIS** `read_page` ou `find` — tout se fait par `javascript_tool` "
        "via IDs stables")
    add("- L'URL ne change PAS après le téléchargement — c'est normal")
    add(f"- Objectif : ~20-25 secondes par chanson → ~{n*25//60} min total")
    add("")
    add(f"**Statuts** : `[N/{n}] OK Artiste - Titre` | `INDISPONIBLE` | `NO_GP` | `ERREUR` "
        "→ continuer sans s'arrêter.")
    add("")
    add("---")
    add("")
    add(f"## Liste des {n} chansons (débutant — open chords / power chords, 3–5 accords)")
    add("")
    add(f"Sélection filtrée contre la collection actuelle ({1529} morceaux uniques dans "
        "`partitions/`) — aucun doublon.")
    add("")
    for i, (artist, title) in enumerate(songs, 1):
        add(f"{i}. {artist} - {title}")
    add("")
    add("---")
    add("Récap final : OK / INDISPONIBLE / NO_GP / ERREUR + listes d'échecs.")
    a1 = n // 3
    a2 = 2 * n // 3
    add(f"**Plan B** si blocage : 3 sessions ({a1} / {a2-a1} / {n-a2} chansons).")
    add(f"COMMENCE. Va jusqu'à {n}. Récap à la fin. C'EST TOUT.")
    add("")
    add("---")
    add("")
    add("## Notes destination")
    add("")
    win_path = str(gp_dir) + "\\"
    add(f"- Les fichiers iront dans le dossier Téléchargements ; déplace-les ensuite "
        f"dans `{win_path}`.")
    add("- Structure réorganisée le 2026-05-20 : tous les `.gp` sont désormais dans le "
        "sous-dossier `partitions/`.")
    add("- Après déplacement : `python -m fretwise.partitions.sync_songs rebuild` régénère "
        "`songs_index.tsv` (qui scanne désormais `partitions/`).")
    add("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée CLI. Retourne le code de sortie."""
    ensure_printable_output()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None, help="Racine du workspace partitions")
    args = ap.parse_args(argv)

    root = Path(args.root) if args.root else paths.partitions_root()
    date = datetime.date.today().strftime("%Y-%m-%d")

    songs = load_songs(root, date)
    print(f"loaded {len(songs)} songs")
    text = build(songs, paths.gp_dir(root))
    out = root / f"prompt-songsterr-{date}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print("written:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
