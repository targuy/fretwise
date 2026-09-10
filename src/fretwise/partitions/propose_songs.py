"""Génère un prompt-songsterr-YYYY-MM-DD.md prêt à exécuter par Claude in Chrome.

Il contient N candidats (par défaut 100) ABSENTS de la bibliothèque.

🚨 RÈGLES ANTI-DOUBLON (appliquées dans l'ordre) :
    R1 — Lire songs_index.tsv comme source de vérité principale
    R2 — Filtrer les candidats présents dans songs_index.tsv
    R3 — Appliquer équilibrage artiste/genre
    R4 — Générer extract_checked.txt puis le prompt

Mode d'emploi :
    python -m fretwise.partitions.propose_songs [--root PATH] [--count 100] [--candidates PATH]

Le fichier --candidates est un .txt avec une ligne par candidat au format
"Artist - Title (Year)" (le Year est optionnel). Si absent, le script écrit
un fichier "candidates_seed.txt" minimal et demande à l'agent de le compléter
par recherche web (cf. Workflow 3 de la skill).

Sortie :
    extract-YYYY-MM-DD.txt          : liste brute (avant check)
    extract-YYYY-MM-DD_checked.txt  : liste filtrée (après check — SEULE source pour le prompt)
    prompt-songsterr-YYYY-MM-DD.md  : prompt prêt pour Claude in Chrome
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from collections import Counter
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from fretwise.partitions import paths
from fretwise.partitions.console import ensure_printable_output
from fretwise.partitions.lib import normalize_identity

DEFAULT_COUNT = 100

# Artistes exclus (sur-représentés) — 0 nouveau candidat accepté
OVERREPRESENTED_ARTISTS = {
    "the beatles", "beatles",
    "led zeppelin",
    "the rolling stones", "rolling stones",
}

# Seuils d'équilibrage
MAX_CANDIDATES_PER_WELL_REP_ARTIST = 1   # artiste avec ≥ 10 partitions → max 1 candidat
MAX_CANDIDATES_PER_LOW_REP_ARTIST = 3    # artiste avec < 10 partitions → max 3 candidats
MAX_GENRE_PCT = 0.25                     # un genre ne peut pas dépasser 25% des candidats


def _norm_key(s: str) -> str:
    """Normalisation lâche pour comparaison."""
    s = s.lower()
    s = re.sub(r"\b(the|a|an|les|le|la|l')\b", "", s)
    s = re.sub(r"[.,!?'\"()&\-_/]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _artist_key(s: str) -> str:
    return _norm_key(s)


# ── Chargement songs_index.tsv ────────────────────────────────────────────────

def load_library_from_tsv(tsv_path: Path) -> tuple[set, Counter, Counter]:
    """
    Retourne (have_idents, artist_counts, genre_counts).
    Source de vérité principale.
    """
    have = set()
    artists: Counter = Counter()
    genres: Counter = Counter()

    if not tsv_path.exists():
        print(f"[warn] songs_index.tsv introuvable : {tsv_path}", file=sys.stderr)
        return have, artists, genres

    with open(tsv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            artist = row.get("artist", "").strip()
            title = row.get("title", "").strip()
            genre = row.get("genre", "").strip()
            if artist and title:
                have.add(normalize_identity(artist, title))
                have.add(_norm_key(f"{artist} {title}"))
                artists[_artist_key(artist)] += 1
                if genre:
                    for g in genre.split("|"):
                        g = g.strip()
                        if g:
                            genres[g] += 1

    return have, artists, genres


def load_library_fallback(list_file: Path, have: set) -> None:
    """Complète have avec liste_partitions.txt (fallback)."""
    if not list_file.exists():
        return
    for line in list_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if " - " in line:
            artist, _, title = line.partition(" - ")
            have.add(normalize_identity(artist, title))
            have.add(_norm_key(f"{artist} {title}"))


# ── Parsing candidats ─────────────────────────────────────────────────────────

def parse_candidate(line: str) -> tuple[str, str, str | None] | None:
    """Parse 'N. Artist - Title (Year)' → (artist, title, year) ou None."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    line = re.sub(r"^\d+\.\s*", "", line)
    m = re.search(r"\((\d{4})\)\s*$", line)
    year = m.group(1) if m else None
    if m:
        line = line[:m.start()].strip()
    if " - " not in line:
        return None
    artist, _, title = line.partition(" - ")
    return artist.strip(), title.strip(), year


# ── Filtrage et équilibrage ───────────────────────────────────────────────────

def filter_and_balance(
    raw_candidates: list[tuple[str, str, str | None]],
    have: set,
    lib_artists: Counter,
    lib_genres: Counter,
    count: int,
    verbose: bool = True,
) -> tuple[list, list]:
    """
    Applique les règles R2 (dedup) + R4 (équilibrage) dans l'ordre.
    Retourne (accepted, rejected_log).
    """
    accepted = []
    rejected_log = []
    seen_idents = set()
    artist_count_accepted: Counter = Counter()

    for artist, title, year in raw_candidates:
        ak = _artist_key(artist)
        ident = normalize_identity(artist, title)
        ident2 = _norm_key(f"{artist} {title}")

        # R2 — déjà en bibliothèque ?
        if ident in have or ident2 in have:
            rejected_log.append(f"DOUBLON   {artist} - {title}")
            continue

        # R2 — doublon dans les candidats eux-mêmes ?
        if ident in seen_idents:
            rejected_log.append(f"DUP_CAND  {artist} - {title}")
            continue

        # R4 — artiste exclu (sur-représenté)
        if ak in OVERREPRESENTED_ARTISTS:
            rejected_log.append(f"OVERREP   {artist} - {title}")
            continue

        # R4 — limite par artiste
        lib_count = lib_artists.get(ak, 0)
        max_per_artist = (MAX_CANDIDATES_PER_WELL_REP_ARTIST if lib_count >= 10
                          else MAX_CANDIDATES_PER_LOW_REP_ARTIST)
        if artist_count_accepted[ak] >= max_per_artist:
            rejected_log.append(
                f"ARTIST_LIM {artist} - {title} "
                f"(déjà {artist_count_accepted[ak]} candidats)")
            continue

        # Ajouter
        seen_idents.add(ident)
        accepted.append((artist, title, year))
        artist_count_accepted[ak] += 1

        if len(accepted) >= count:
            break

    if verbose:
        print(f"[filter] {len(raw_candidates)} bruts → {len(accepted)} retenus "
              f"({len(rejected_log)} exclus)")
        doublon_count = sum(1 for r in rejected_log if r.startswith("DOUBLON"))
        if doublon_count > 0:
            print(f"[filter] {doublon_count} doublons bibliothèque exclus :")
            for r in rejected_log:
                if r.startswith("DOUBLON"):
                    print(f"         ✗ {r[10:]}")

    return accepted, rejected_log


# ── Rendu du prompt ───────────────────────────────────────────────────────────

def render_prompt(date_iso: str, candidates: list) -> str:
    """Rend le prompt Songsterr markdown pour Claude in Chrome."""
    n = len(candidates)
    lines = [
        f"# Prompt Songsterr — {date_iso}",
        f"# Objectif : télécharger {n} partitions Guitar Pro sur songsterr.com",
        "",
        "0 screenshot. 0 verbosity. 1 ligne par chanson.",
        "",
        f"Tu vas télécharger ces {n} chansons sur songsterr.com (compte Songsterr Plus actif, "
        "export Guitar Pro activé).",
        "",
        "## ⚠️ IMPORTANT — anti-doublon",
        "",
        "Ces chansons ont été vérifiées absentes de la bibliothèque locale.",
        "Ne pas télécharger si tu trouves un résultat qui semble déjà connu.",
        "",
        "## Procédure par chanson (5 actions)",
        "",
        "1. Naviguer vers : `https://www.songsterr.com/?pattern=<TITRE>+<ARTISTE>` (espaces → +)",
        "2. Cliquer le PREMIER résultat matching guitare (`a[href^=\"/a/wsa/\"]`, "
        "puis `[role=\"link\"]`). IGNORER bass / drum / ukulele si version guitare dispo.",
        "3. Cliquer **DOWNLOAD** (`button[aria-label*=\"Download\" i]`, "
        "`button[title*=\"Download\" i]`).",
        "4. Dans le dialog de format : cliquer **Guitar Pro** (= bouton le plus à droite, "
        "`[role=\"dialog\"] button` → dernier, ou texte 'Guitar Pro'/'GP'). **JAMAIS MIDI.**",
        "5. Émettre `[N/total] OK <Song>` et continuer.",
        "",
        "## Échecs",
        "",
        "- `INDISPONIBLE` : pas de version guitare trouvée",
        "- `NO_GP` : version trouvée mais pas d'export Guitar Pro",
        "- `ERREUR` : autre",
        "",
        "Continue toujours à la suivante, ne bloque pas.",
        "",
        "## Récap final UNIQUE",
        "",
        "- Comptes par statut",
        "- Listes des INDISPONIBLE / NO_GP / ERREUR",
        "",
        f"## Plan B (si la session bloque) : découpe en 3 × {n//3} chansons",
        "",
        "## Liste à télécharger",
        "",
    ]
    for i, (artist, title, year) in enumerate(candidates, 1):
        yr = f" ({year})" if year else ""
        lines.append(f"{i}. {artist} - {title}{yr}")
    lines += ["", f"COMMENCE. Va jusqu'à {n}. Récap à la fin. C'EST TOUT."]
    return "\n".join(lines) + "\n"


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée CLI. Retourne le code de sortie."""
    ensure_printable_output()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None, help="Racine du workspace partitions")
    ap.add_argument("--count", type=int, default=DEFAULT_COUNT)
    ap.add_argument("--candidates", default=None)
    ap.add_argument("--skip-balance", action="store_true",
                    help="Désactive les règles d'équilibrage (R4) — utiliser avec précaution")
    args = ap.parse_args(argv)

    root = Path(args.root) if args.root else paths.partitions_root()
    tsv_file = paths.songs_index_path(root)
    list_file = paths.liste_partitions_path(root)
    cand_file = Path(args.candidates) if args.candidates else (root / "candidates_seed.txt")

    # ── R1/R2 : charger la bibliothèque ──────────────────────────────────────
    print("[R1] Chargement songs_index.tsv…", flush=True)
    have, lib_artists, lib_genres = load_library_from_tsv(tsv_file)
    load_library_fallback(list_file, have)
    print(f"[R1] {len(have)//2} morceaux connus, {len(lib_artists)} artistes")

    # ── Lecture candidats ─────────────────────────────────────────────────────
    if not cand_file.exists():
        cand_file.write_text(
            "# candidates_seed.txt\n"
            "# Remplir via web_search (cf. Workflow 3 skill partitions-manager)\n"
            "# Format : Artist - Title (Year)\n",
            encoding="utf-8",
        )
        print(f"[wait] {cand_file} créé vide — compléter via web_search.")
        return 2

    raw = [parse_candidate(line) for line in cand_file.read_text(encoding="utf-8").splitlines()]
    raw = [c for c in raw if c is not None]
    print(f"[info] {len(raw)} candidats lus depuis {cand_file.name}")

    # ── R2 + R4 : filtrage et équilibrage ────────────────────────────────────
    accepted, rejected_log = filter_and_balance(
        raw, have, lib_artists, lib_genres,
        count=args.count,
        verbose=True,
    )

    today = date.today().isoformat()

    if not accepted:
        print(f"[warn] aucun candidat valide trouvé — ajouter des candidats dans {cand_file.name}")
        return 2

    # ── Écriture des sorties ──────────────────────────────────────────────────
    extract_raw = root / f"extract-{today}.txt"
    extract_checked = root / f"extract-{today}_checked.txt"
    prompt_file = root / f"prompt-songsterr-{today}.md"

    # Fichier brut (avant équilibrage — pour référence)
    all_raw_lines = []
    for a, t, y in raw[:200]:
        yr = f" ({y})" if y else ""
        all_raw_lines.append(f"{a} - {t}{yr}")
    extract_raw.write_text("\n".join(all_raw_lines) + "\n", encoding="utf-8")

    # Fichier vérifié (source officielle pour le prompt)
    extract_checked.write_text(
        f"# Candidats vérifiés — {today}\n"
        f"# R2 anti-doublon + R4 équilibrage appliqués\n"
        f"# {len(accepted)} candidats retenus\n\n"
        + "\n".join(f"{i}. {a} - {t}" + (f" ({y})" if y else "")
                    for i, (a, t, y) in enumerate(accepted, 1)) + "\n",
        encoding="utf-8",
    )

    # Prompt Songsterr (généré depuis extract_checked uniquement)
    prompt_file.write_text(render_prompt(today, accepted), encoding="utf-8")

    print(f"[done] extract_checked={extract_checked.name}  prompt={prompt_file.name}  "
          f"candidates={len(accepted)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
