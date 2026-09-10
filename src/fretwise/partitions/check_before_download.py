"""Vérification obligatoire AVANT de générer ou exécuter un prompt de téléchargement.

Lit songs_index.tsv (source de vérité locale) et un fichier de candidats,
puis retourne :
  - La liste filtrée (candidats absents de la bibliothèque)
  - Les doublons détectés (candidats déjà présents)
  - Un résumé artiste/genre pour équilibrage

Usage :
    python -m fretwise.partitions.check_before_download <candidats.txt> [--tsv PATH] [--out PATH]

Format candidats.txt :
    1. Artiste - Titre (Année)   ← format extract-YYYY-MM-DD.txt
    ou
    Artiste - Titre              ← format libre

Sortie :
    <candidats>_checked.txt  (liste filtrée, prête pour prompt Songsterr)
    Rapport affiché sur stdout
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from fretwise.partitions import paths
from fretwise.partitions.console import ensure_printable_output

# ── Normalisation ──────────────────────────────────────────────────────────────


def normalize_key(s: str) -> str:
    """Normalisation lâche (accents, articles, ponctuation) pour comparaison."""
    s = s.lower()
    s = re.sub(r"[.,!?\'\"()\[\]&_\-]", " ", s)
    s = re.sub(r"\b(the|a|an|and|et|les|le|la|de|des|du)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def make_ident(artist: str, title: str) -> str:
    """Identité canonique artiste|titre pour la dédup."""
    return f"{normalize_key(artist)}|{normalize_key(title)}"


# ── Lecture songs_index.tsv ───────────────────────────────────────────────────

def load_library(tsv_path: Path) -> tuple[set, Counter, Counter]:
    """Retourne (idents_set, artist_counter, genre_counter)."""
    idents: set[str] = set()
    artists: Counter = Counter()
    genres: Counter = Counter()

    if not tsv_path.exists():
        print(f"[WARN] {tsv_path} introuvable — vérification partielle uniquement",
              file=sys.stderr)
        return idents, artists, genres

    with open(tsv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            artist = row.get("artist", "").strip()
            title = row.get("title", "").strip()
            genre = row.get("genre", "").strip()
            if artist and title:
                idents.add(make_ident(artist, title))
                artists[artist] += 1
                if genre:
                    for g in genre.split("|"):
                        genres[g.strip()] += 1

    return idents, artists, genres


# ── Parsing candidats ─────────────────────────────────────────────────────────

CANDIDATE_RE = re.compile(
    r"^\s*(?:\d+\.\s*)?"          # numéro optionnel
    r"(.+?)\s*-\s*(.+?)"          # Artiste - Titre
    r"(?:\s*\(\d{4}\))?\s*$"      # (Année) optionnel
)


def parse_candidates(path: Path) -> list[tuple[str, str, str]]:
    """Retourne [(artist, title, original_line)]."""
    results = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip() or line.strip().startswith("#"):
                continue
            m = CANDIDATE_RE.match(line)
            if m:
                results.append((m.group(1).strip(), m.group(2).strip(), line))
            else:
                # Ligne non parseable → inclure avec avertissement
                results.append(("?", line.strip(), line))
    return results


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée CLI. Retourne le code de sortie."""
    ensure_printable_output()
    ap = argparse.ArgumentParser(description="Vérifie les candidats contre songs_index.tsv")
    ap.add_argument("candidates", help="Fichier de candidats (extract-*.txt ou liste libre)")
    ap.add_argument("--tsv", default=None, help="Chemin vers songs_index.tsv")
    ap.add_argument("--out", default=None, help="Fichier de sortie (défaut: <input>_checked.txt)")
    ap.add_argument("--max-per-artist", type=int, default=3,
                    help="Nombre max de candidats par artiste déjà bien représenté (défaut: 3)")
    ap.add_argument("--dry-run", action="store_true", help="Afficher sans écrire")
    args = ap.parse_args(argv)

    cand_path = Path(args.candidates)
    tsv_path = Path(args.tsv) if args.tsv else paths.songs_index_path()
    out_path = Path(args.out) if args.out else cand_path.with_name(
        cand_path.stem + "_checked" + cand_path.suffix
    )

    # Charger la bibliothèque
    print("[check] Chargement songs_index.tsv…", flush=True)
    library_idents, lib_artists, lib_genres = load_library(tsv_path)
    print(f"[check] {len(library_idents)} identités connues, "
          f"{len(lib_artists)} artistes, genres: {dict(lib_genres.most_common(5))}")

    # Parser les candidats
    candidates = parse_candidates(cand_path)
    print(f"[check] {len(candidates)} candidats à vérifier")

    already_have: list[tuple[str, str, str]] = []
    to_download: list[tuple[str, str, str]] = []
    artist_count_in_candidates: Counter = Counter()

    for artist, title, orig_line in candidates:
        ident = make_ident(artist, title)
        if ident in library_idents:
            already_have.append((artist, title, orig_line))
        else:
            artist_count_in_candidates[artist] += 1
            to_download.append((artist, title, orig_line))

    # Rapport doublons
    print(f"\n{'='*60}")
    print(f"  DOUBLONS DÉTECTÉS ({len(already_have)}) — EXCLUS DU PROMPT :")
    for artist, title, _ in already_have:
        print(f"    ✗  {artist} - {title}")

    # Rapport équilibrage artiste
    print("\n  ARTISTES DÉJÀ BIEN REPRÉSENTÉS dans la bibliothèque (≥10 partitions) :")
    for artist, cnt in lib_artists.most_common(20):
        cand_cnt = artist_count_in_candidates.get(artist, 0)
        if cnt >= 10:
            print(f"    {cnt:3}× {artist:<35} +{cand_cnt} nouveaux")

    print(f"\n  LISTE FILTRÉE : {len(to_download)} chansons à télécharger "
          f"(sur {len(candidates)} candidats, {len(already_have)} exclus)")
    print(f"{'='*60}\n")

    if not args.dry_run:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"# Candidats vérifiés — {datetime.now():%Y-%m-%d}\n")
            f.write(f"# {len(to_download)} chansons / {len(already_have)} doublons exclus\n\n")
            for i, (artist, title, _) in enumerate(to_download, 1):
                f.write(f"{i}. {artist} - {title}\n")
        print(f"[done] {out_path.name} — {len(to_download)} candidats prêts pour Songsterr")
    else:
        print(f"[dry-run] {len(to_download)} candidats seraient écrits dans {out_path.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
