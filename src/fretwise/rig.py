"""Valeton GP-180 rig file parser and lookup utilities."""
from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

GP180_CHAIN = ["NR", "PRE", "WAH", "DST", "N→S", "AMP", "CAB/IR", "EQ", "MOD", "DLY", "RVB", "VOL"]

# Maps lowercased keyword substrings (longest match wins) to pedal image filenames.
PEDAL_IMAGES: dict[str, str | None] = {
    "gate 1": "01_NR_Gate1_ISP_Decimator.jpg",
    "comp": "02_PRE_COMP_MXR_DynaComp.jpg",
    "ts808": "03_PRE_OD9_Ibanez_TS808.jpg",
    "ts9": "04_PRE_OD9_Ibanez_TS9.jpg",
    "klon": "05_PRE_Penesas_Klon_Centaur.jpg",
    "mutron": "06_PRE_TWah_MuTron_III.jpg",
    "crybaby style": "07_PRE_AWah_CryBaby_Style.jpg",
    "whammy": "08_PRE_Hammy_DigiTech_Whammy.jpg",
    "dist+": "11_DST_Plustortion_MXR_DistPlus.jpg",
    "distplus": "11_DST_Plustortion_MXR_DistPlus.jpg",
    "ds1": "12_DST_SMDist_Boss_DS1.jpg",
    "rat": "13_DST_Darktale_ProCo_Rat.jpg",
    "big muff": "14_DST_Lazaro_BigMuffPi.jpg",
    "fuzz face": "15_DST_RedHaze_FuzzFace.jpg",
    "darkglass": "20_DST_BlackBass_Darkglass_B7K.jpg",
    "aguilar": "21_DST_BassHammer_Aguilar.jpg",
    "crybaby": "23_WAH_CWah_Dunlop_CryBaby.jpg",
    "tweedy": "24_AMP_Tweedy_Fender_Deluxe.jpg",
    "fender deluxe": "24_AMP_Tweedy_Fender_Deluxe.jpg",
    "bassman": "25_AMP_Bellman_Fender_Bassman.jpg",
    "foxy30": "27_AMP_Foxy30N_Vox_AC30_Twin.jpg",
    "vox ac30": "27_AMP_Foxy30N_Vox_AC30_Twin.jpg",
    "uk 45": "29_AMP_UK45_Marshall_JTM45.jpg",
    "uk45": "29_AMP_UK45_Marshall_JTM45.jpg",
    "uk 50": "29_AMP_UK45_Marshall_JTM45.jpg",
    "uk 900": "32_AMP_UK900_Marshall_JCM900.jpg",
    "uk900": "32_AMP_UK900_Marshall_JCM900.jpg",
    "soldano": "33_AMP_Solo100_Soldano_SLO100.jpg",
    "mesa dual": "35_AMP_MessDualV_Mesa_DualRecto.jpg",
    "tremoverb": "36_AMP_MessDualM_Mesa_Tremoverb.jpg",
    "engl savage": "37_AMP_Eagle120_ENGL_Savage.jpg",
    "engl gigmaster": "38_AMP_Eagle120_ENGL_Gigmaster.jpg",
    "ampeg": "39_AMP_Ampeg_SVT_Bass.jpg",
    "uk vintage 4x12": "41_CAB_UK4x12_Marshall.jpg",
    "uk 4x12": "41_CAB_UK4x12_Marshall.jpg",
    "ce2": "45_MOD_CChorus_Boss_CE2.jpg",
    "tc electronic": "47_MOD_TC_Electronic.jpg",
    "shimmer": "50_RVB_Shimmer_Strymon_BigSky.jpg",
    "guitar eq 1": "51_EQ_GuitarEQ1.jpg",
    "ce3": "55_MOD_BChorus_Boss_CE3.jpg",
    "tremolo": "60_MOD_OTrem_Tremolo_Optique.jpg",
    "micropitch": "64_MOD_Detune_MicroPitch.jpg",
    "sustain": "66_MOD_Hold_Sustain.jpg",
    "dd3": "69_DLY_DigitalDelayS_Boss_DD3.jpg",
    "ping pong": "74_DLY_PingPong_Eventide_Timefactor.jpg",
    "carbon copy": "76_DLY_RingEcho_MXR_CarbonCopy_Analog.jpg",
    "sweep echo": "76_DLY_SweepEcho.jpg",
}


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def _normalize(name: str) -> str:
    name = _strip_accents(name).encode("ascii", "ignore").decode("ascii")
    name = name.lower()
    name = name.replace("&", "and").replace("/", "")
    name = re.sub(r"[''',\.!\(\)\?:;\"…_]", "", name)
    name = re.sub(r"[-\s]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name


def _fingerprint(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _rig_body(stem: str) -> str:
    """Strip the ``rig_`` (or bare ``rig``) prefix from a rig filename stem.

    Uses a single conditional strip, NOT chained ``removeprefix`` calls: chaining
    ``.removeprefix("rig_").removeprefix("rig")`` corrupts any song whose name
    starts with "ri" (e.g. ``rig_right_now_…`` → ``ht_now_…``).
    """
    if stem.startswith("rig_"):
        return stem[4:]
    if stem.startswith("rig"):
        return stem[3:]
    return stem


_DATE_TAIL = re.compile(r"[\s-]+\d{2}[.\-]\d{2}[.\-]\d{4}(?:\s+\d+)?$")
_FINGERED_SUFFIX = re.compile(r"_fingered$", re.IGNORECASE)
_SPLIT_SEP = re.compile(r"\s*-\s*")


def _partition_key(stem: str) -> tuple[str, str]:
    """Return (artist_normalized, song_normalized) from a partition filename stem.

    Strips the ``_fingered`` suffix BEFORE the date: a name like
    ``Artist - Song - 02-11-2026_fingered`` hides the date behind ``_fingered``,
    so the date regex (anchored at end) only bites once the suffix is gone.
    """
    stem = _FINGERED_SUFFIX.sub("", stem)
    stem = _DATE_TAIL.sub("", stem)
    parts = _SPLIT_SEP.split(stem, maxsplit=1)
    if len(parts) == 2:
        return _normalize(parts[0]), _normalize(parts[1])
    return "", _normalize(parts[0])


def find_rigs_dir(fixtures_dir: Path) -> Path | None:
    """Locate the rigs directory, checking fixtures_dir/rigs then common fallbacks."""
    primary = fixtures_dir / "rigs"
    if primary.is_dir():
        return primary
    for fallback in (
        Path("E:/pythonProject/fretwise/partitions/rigs"),
        fixtures_dir.parent / "partitions" / "rigs",
    ):
        if fallback.is_dir():
            return fallback
    return None


def find_rig(partition_name: str, rigs_dir: Path) -> Path | None:
    """Return the rig .md file for partition_name, or None if no match.

    Suited to a single lookup (``GET /api/rig/{file}``). For bulk has-rig checks
    over a whole library, use :func:`build_rig_index` + :func:`partition_has_rig`,
    which scan the rigs directory **once** instead of per file.
    """
    if not rigs_dir.is_dir():
        return None
    artist_n, song_n = _partition_key(Path(partition_name).stem)
    expected = f"rig_{song_n}_{artist_n}"
    candidate = rigs_dir / f"{expected}.md"
    if candidate.is_file():
        return candidate
    # Fallback: fingerprint match (strips underscores for near-miss detection)
    fp_expected = _fingerprint(f"{song_n}{artist_n}")
    for rig in rigs_dir.iterdir():
        if rig.suffix != ".md":
            continue
        if _fingerprint(_rig_body(rig.stem)) == fp_expected:
            return rig
    return None


def build_rig_index(rigs_dir: Path | None) -> set[str]:
    """Scan ``rigs_dir`` **once** and return a set of rig fingerprints.

    The returned set feeds :func:`partition_has_rig` for O(1) per-file has-rig
    checks, turning a library-wide scan from O(files × rigs) filesystem calls
    into a single directory read plus in-memory lookups. Returns an empty set if
    the directory is missing or unreadable (never raises).
    """
    index: set[str] = set()
    if not rigs_dir or not rigs_dir.is_dir():
        return index
    try:
        entries = list(os.scandir(rigs_dir))
    except OSError:
        return index
    for entry in entries:
        try:
            if not (entry.is_file() and entry.name.endswith(".md")):
                continue
        except OSError:
            continue
        index.add(_fingerprint(_rig_body(entry.name[:-3])))
    return index


def partition_has_rig(partition_name: str, rig_index: set[str]) -> bool:
    """Return True if a rig exists for ``partition_name`` (uses a prebuilt index).

    Consistent with :func:`find_rig`'s fingerprint fallback, so a True here means
    ``find_rig`` will also resolve the file (no phantom rig icons).
    """
    if not rig_index:
        return False
    artist_n, song_n = _partition_key(Path(partition_name).stem)
    return _fingerprint(f"{song_n}{artist_n}") in rig_index


def _find_image(preset: str | None) -> str | None:
    if not preset:
        return None
    pl = preset.lower()
    # Longest matching key wins
    best = max((k for k in PEDAL_IMAGES if k in pl), key=len, default=None)
    if best:
        return PEDAL_IMAGES[best]
    return None


_INACTIVE_VALUES = frozenset({"off", "non", "no", "aucun", "aucune", "non (désactivé)", "non (none)"})

# Regex patterns for section extraction
_RE_FIELD = re.compile(r"^(Artiste|Chanson|Fiabilit[eé]|Accordage|Capo|Guitare originale|Guitare cible|Guitare target)\s*:\s*(.+)$", re.MULTILINE)
_RE_COMPENSATION = re.compile(r"Compensation guitare\s*:\s*\n(.*?)(?=\n(?:Objectif|R[eé]f[eé]rence|Cœur|Cha[iî]ne|R[eé]glages|\Z))", re.DOTALL)
_RE_REGLAGES = re.compile(r"R[eé]glages GP-180\s*:\s*\n(.*?)(?=\n\n|\nNotes de jeu|\nLimites|\Z)", re.DOTALL)
_RE_NOTES = re.compile(r"Notes de jeu\s*:\s*\n(.*?)(?=\n\nLimites|\n\ndate_added|\Z)", re.DOTALL)
_RE_LIMITES = re.compile(r"Limites\s*/\s*compromis\s*:\s*\n(.*?)(?=\n\ndate_added|\Z)", re.DOTALL)
_RE_EFFECT_LINE = re.compile(r"(.+?)\s*:\s*(.+)")

_EFFECT_ALIASES: dict[str, str] = {
    "CAB": "CAB/IR",
    "CAB / IR": "CAB/IR",
    "CAB/IR": "CAB/IR",
    "N>S": "N→S",
    "N→S": "N→S",
}


def _canon_effect(raw: str) -> str:
    key = raw.strip().upper()
    return _EFFECT_ALIASES.get(key, key)


def parse_rig(content: str) -> dict:
    """Parse a GP-180 rig Markdown file into a structured dict."""
    fields: dict[str, str] = {}
    for m in _RE_FIELD.finditer(content):
        label = m.group(1).strip()
        value = m.group(2).strip()
        fields[label] = value

    fiabilite_raw = fields.get("Fiabilité") or fields.get("Fiabilite", "")
    fiabilite = fiabilite_raw.split("—")[0].strip() if fiabilite_raw else None

    comp_m = _RE_COMPENSATION.search(content)
    compensation = comp_m.group(1).strip() if comp_m else None

    notes_m = _RE_NOTES.search(content)
    notes = notes_m.group(1).strip() if notes_m else None

    lim_m = _RE_LIMITES.search(content)
    limites = lim_m.group(1).strip() if lim_m else None

    # Parse réglages block
    reglages: dict[str, dict] = {}
    reg_m = _RE_REGLAGES.search(content)
    if reg_m:
        for line in reg_m.group(1).splitlines():
            line = line.strip()
            if not line.startswith(("-", "–")):
                continue
            em = _RE_EFFECT_LINE.match(line.lstrip("-– "))
            if not em:
                continue
            effect_raw, value_raw = em.group(1).strip(), em.group(2).strip()
            effect_key = _canon_effect(effect_raw)
            value_lower = value_raw.lower().strip()
            active = value_lower not in _INACTIVE_VALUES and not value_lower.startswith("non ")

            if active:
                # Split on interpunct · or em-dash — to get preset vs params
                preset = re.split(r"\s*[·—–]\s*", value_raw)[0].strip()
                # Also stop at em-dash in "UK 50 — Gain 55"
                preset = re.split(r"\s+—\s+", preset)[0].strip()
                params_m = re.search(r"[·—–]\s*(.+)$", value_raw)
                params = params_m.group(1).strip() if params_m else None
                image = _find_image(preset)
            else:
                preset = params = image = None

            reglages[effect_key] = {
                "effect": effect_raw,
                "preset": preset,
                "params": params,
                "active": active,
                "image": image,
            }

    return {
        "artist": fields.get("Artiste"),
        "song": fields.get("Chanson"),
        "fiabilite": fiabilite,
        "accordage": fields.get("Accordage"),
        "capo": fields.get("Capo"),
        "guitare_originale": fields.get("Guitare originale"),
        "guitare_cible": fields.get("Guitare cible"),
        "compensation": compensation,
        "chain": GP180_CHAIN,
        "reglages": reglages,
        "notes": notes,
        "limites": limites,
    }
