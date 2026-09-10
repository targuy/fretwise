"""Auto-taggue les colonnes genre/guitar dans songs_index.tsv.

Utilise une table de correspondance artiste → genre codée en dur.

Usage :
    python -m fretwise.partitions.tag_genres [--tsv PATH] [--dry-run]

Ne remplace PAS les valeurs déjà renseignées (préserve le travail manuel).
Ajoute seulement là où genre est vide.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Sequence
from pathlib import Path

from fretwise.partitions import paths
from fretwise.partitions.console import ensure_printable_output

# ── Table artiste → genre ──────────────────────────────────────────────────────
# Format: 'Artist Name': 'Genre1|Genre2'
# Genres utilisés: Blues, Blues Rock, Classic Rock, Hard Rock, Heavy Metal,
#   Thrash Metal, Death Metal, Progressive Rock, Alternative Rock, Grunge,
#   Indie Rock, Punk, New Wave, Post-Punk, Pop Rock, Pop, Folk Rock, Country Rock,
#   Southern Rock, Psychedelic Rock, Funk, Soul, R&B, Jazz, Reggae, Latin Rock,
#   Electronic, French Rock, French Pop, Metal, Rock
#
# NB portage : le dict d'origine contenait des clés dupliquées (Python garde la
# dernière valeur) — dédupliqué ici en conservant la valeur effective (last-wins).

ARTIST_GENRES: dict[str, str] = {
    # Blues / Blues Rock
    "B.B. King": "Blues",
    "Muddy Waters": "Blues",
    "Robert Johnson": "Blues",
    "John Lee Hooker": "Blues",
    "Elmore James": "Blues",
    "Freddie King": "Blues",
    "Albert King": "Blues",
    "Howlin Wolf": "Blues",
    "Magic Sam": "Blues",
    "Otis Rush": "Blues",
    "Buddy Guy": "Blues",
    "Stevie Ray Vaughan": "Blues Rock",
    "Stevie Ray Vaughan & Double Trouble": "Blues Rock",
    "Gary Moore": "Blues Rock|Hard Rock",
    "Rory Gallagher": "Blues Rock",
    "Eric Clapton": "Blues Rock|Classic Rock",
    "Cream": "Blues Rock|Classic Rock",
    "Peter Green": "Blues Rock",
    "Johnny Winter": "Blues Rock",
    "Joe Bonamassa": "Blues Rock",
    "Gary Clark Jr": "Blues Rock",
    "John Mayer": "Blues Rock|Pop Rock",
    "Derek Trucks": "Blues Rock",
    "Gov't Mule": "Blues Rock",

    # Classic Rock
    "The Beatles": "Classic Rock|Pop Rock",
    "The Rolling Stones": "Classic Rock",
    "The Who": "Classic Rock",
    "Led Zeppelin": "Classic Rock|Hard Rock",
    "Jimi Hendrix": "Classic Rock|Blues Rock",
    "The Jimi Hendrix Experience": "Classic Rock|Blues Rock",
    "The Doors": "Classic Rock|Psychedelic Rock",
    "The Kinks": "Classic Rock",
    "The Byrds": "Classic Rock|Folk Rock",
    "The Animals": "Classic Rock",
    "Simon & Garfunkel": "Folk Rock",
    "Bob Dylan": "Folk Rock",
    "Neil Young": "Folk Rock|Classic Rock",
    "Crosby Stills Nash & Young": "Folk Rock|Classic Rock",
    "Creedence Clearwater Revival": "Classic Rock",
    "Lynyrd Skynyrd": "Southern Rock|Classic Rock",
    "The Allman Brothers Band": "Southern Rock|Blues Rock",
    "ZZ Top": "Blues Rock|Hard Rock",
    "Tom Petty": "Classic Rock|Pop Rock",
    "Tom Petty and the Heartbreakers": "Classic Rock|Pop Rock",
    "Bruce Springsteen": "Classic Rock|Rock",
    "Steve Miller Band": "Classic Rock",
    "Eagles": "Country Rock|Classic Rock",
    "The Eagles": "Country Rock|Classic Rock",
    "Fleetwood Mac": "Classic Rock|Blues Rock",
    "Santana": "Latin Rock|Classic Rock",
    "Carlos Santana": "Latin Rock|Classic Rock",
    "Thin Lizzy": "Hard Rock|Classic Rock",
    "Bad Company": "Hard Rock|Classic Rock",
    "Foghat": "Hard Rock|Classic Rock",
    "Free": "Hard Rock|Blues Rock",
    "Humble Pie": "Hard Rock|Blues Rock",

    # Hard Rock / Heavy Metal
    "Deep Purple": "Hard Rock|Heavy Metal",
    "Black Sabbath": "Heavy Metal|Hard Rock",
    "Ozzy Osbourne": "Heavy Metal|Hard Rock",
    "AC/DC": "Hard Rock|Heavy Metal",
    "Aerosmith": "Hard Rock|Blues Rock",
    "Van Halen": "Hard Rock",
    "Kiss": "Hard Rock|Heavy Metal",
    "Judas Priest": "Heavy Metal",
    "Iron Maiden": "Heavy Metal",
    "Dio": "Heavy Metal|Hard Rock",
    "Rainbow": "Heavy Metal|Hard Rock",
    "Scorpions": "Hard Rock|Heavy Metal",
    "Whitesnake": "Hard Rock|Heavy Metal",
    "Def Leppard": "Hard Rock|Heavy Metal",
    "Bon Jovi": "Hard Rock|Pop Rock",
    "Guns N' Roses": "Hard Rock|Heavy Metal",
    "Skid Row": "Hard Rock|Heavy Metal",
    "Motley Crue": "Hard Rock|Heavy Metal",
    "Twisted Sister": "Hard Rock|Heavy Metal",
    "Warrant": "Hard Rock",
    "Dokken": "Hard Rock|Heavy Metal",
    "Winger": "Hard Rock",
    "Lynch Mob": "Hard Rock",

    # Thrash / Progressive Metal
    "Metallica": "Thrash Metal|Heavy Metal",
    "Megadeth": "Thrash Metal|Heavy Metal",
    "Slayer": "Thrash Metal|Heavy Metal",
    "Anthrax": "Thrash Metal|Heavy Metal",
    "Pantera": "Heavy Metal|Groove Metal",
    "Sepultura": "Thrash Metal|Heavy Metal",
    "Testament": "Thrash Metal",
    "Exodus": "Thrash Metal",
    "Overkill": "Thrash Metal",
    "Tool": "Progressive Metal|Alternative Metal",
    "A Perfect Circle": "Alternative Metal",
    "System of a Down": "Alternative Metal|Heavy Metal",
    "Rage Against The Machine": "Alternative Metal|Funk Metal",
    "Korn": "Nu Metal",
    "Linkin Park": "Nu Metal|Alternative Rock",
    "Disturbed": "Heavy Metal|Alternative Metal",
    "Godsmack": "Heavy Metal|Alternative Metal",
    "Audioslave": "Alternative Metal|Hard Rock",
    "Soundgarden": "Grunge|Alternative Rock",
    "Alice in Chains": "Grunge|Heavy Metal",

    # Progressive Rock
    "Pink Floyd": "Progressive Rock|Classic Rock",
    "Genesis": "Progressive Rock",
    "Yes": "Progressive Rock",
    "Rush": "Progressive Rock|Hard Rock",
    "Emerson Lake & Palmer": "Progressive Rock",
    "King Crimson": "Progressive Rock",
    "Jethro Tull": "Progressive Rock|Folk Rock",
    "Supertramp": "Progressive Rock|Pop Rock",
    "Queen": "Hard Rock|Classic Rock",
    "David Bowie": "Classic Rock|Glam Rock",
    "T. Rex": "Glam Rock|Classic Rock",
    "T-Rex": "Glam Rock|Classic Rock",

    # Psychedelic / Space Rock
    "Jefferson Airplane": "Psychedelic Rock",
    "The Grateful Dead": "Psychedelic Rock",
    "Crosby Stills & Nash": "Folk Rock",

    # Grunge / Alternative 90s
    "Nirvana": "Grunge|Alternative Rock",
    "Pearl Jam": "Grunge|Alternative Rock",
    "Stone Temple Pilots": "Grunge|Alternative Rock",
    "Smashing Pumpkins": "Alternative Rock|Grunge",
    "Bush": "Alternative Rock|Grunge",
    "Live": "Alternative Rock",
    "Everclear": "Alternative Rock",
    "Candlebox": "Alternative Rock|Grunge",
    "Screaming Trees": "Grunge|Alternative Rock",

    # Alternative / Indie Rock
    "Radiohead": "Alternative Rock|Art Rock",
    "R.E.M.": "Alternative Rock|Post-Punk",
    "The Cure": "Post-Punk|Alternative Rock",
    "The Smiths": "Post-Punk|Alternative Rock",
    "Depeche Mode": "New Wave|Electronic",
    "New Order": "New Wave|Electronic",
    "Joy Division": "Post-Punk",
    "U2": "Rock|Post-Punk",
    "Oasis": "Britpop|Alternative Rock",
    "Blur": "Britpop|Alternative Rock",
    "Pulp": "Britpop|Alternative Rock",
    "The Verve": "Alternative Rock|Britpop",
    "Suede": "Britpop|Alternative Rock",
    "Garbage": "Alternative Rock",
    "PJ Harvey": "Alternative Rock|Punk",
    "Beck": "Alternative Rock",
    "Weezer": "Alternative Rock|Pop Rock",
    "Pixies": "Alternative Rock|Indie Rock",
    "Violent Femmes": "Alternative Rock|Indie Rock",
    "The Pixies": "Alternative Rock|Indie Rock",
    "Sonic Youth": "Alternative Rock|Noise Rock",
    "Dinosaur Jr": "Alternative Rock|Indie Rock",
    "Built to Spill": "Alternative Rock|Indie Rock",
    "The National": "Indie Rock|Alternative Rock",
    "Wilco": "Indie Rock|Alternative Rock",
    "Modest Mouse": "Indie Rock|Alternative Rock",
    "Death Cab for Cutie": "Indie Rock",
    "Arcade Fire": "Indie Rock|Alternative Rock",
    "The Strokes": "Indie Rock|Alternative Rock",
    "Franz Ferdinand": "Indie Rock|Post-Punk",
    "Interpol": "Post-Punk|Indie Rock",
    "White Stripes": "Blues Rock|Alternative Rock",
    "The White Stripes": "Blues Rock|Alternative Rock",
    "The Black Keys": "Blues Rock|Alternative Rock",
    "Jack White": "Blues Rock|Alternative Rock",
    "Queens Of The Stone Age": "Hard Rock|Alternative Rock",
    "Arctic Monkeys": "Indie Rock|Alternative Rock",
    "The Arctic Monkeys": "Indie Rock|Alternative Rock",
    "Muse": "Alternative Rock|Progressive Rock",
    "Coldplay": "Alternative Rock|Pop Rock",
    "Placebo": "Alternative Rock",
    "Editors": "Post-Punk|Alternative Rock",
    "My Chemical Romance": "Alternative Rock|Emo",
    "Fall Out Boy": "Pop Punk|Alternative Rock",
    "Panic! At The Disco": "Pop Punk|Alternative Rock",
    "Paramore": "Pop Punk|Alternative Rock",
    "Green Day": "Punk|Pop Punk",
    "Blink-182": "Pop Punk|Punk",
    "blink-182": "Pop Punk|Punk",
    "The Offspring": "Punk|Alternative Rock",
    "NOFX": "Punk",
    "Bad Religion": "Punk",
    "Pennywise": "Punk",
    "Rancid": "Punk",
    "The Clash": "Punk|New Wave",
    "Sex Pistols": "Punk",
    "The Ramones": "Punk",
    "The Buzzcocks": "Punk",
    "Wire": "Post-Punk",
    "Talking Heads": "New Wave|Post-Punk",
    "Television": "Post-Punk",
    "Patti Smith": "Punk|Alternative Rock",
    "Nine Inch Nails": "Industrial Rock|Alternative Metal",
    "Marilyn Manson": "Industrial Rock|Alternative Metal",
    "Trent Reznor": "Industrial Rock",

    # Guitar Heroes / Instrumentals
    "Joe Satriani": "Rock|Instrumental",
    "Steve Vai": "Rock|Instrumental",
    "Yngwie Malmsteen": "Neoclassical Metal|Instrumental",
    "Eric Johnson": "Rock|Instrumental",
    "Buckethead": "Rock|Instrumental",
    "Guthrie Govan": "Rock|Instrumental",
    "John Petrucci": "Progressive Metal|Instrumental",
    "Paul Gilbert": "Hard Rock|Instrumental",

    # Pop / Pop Rock
    "Michael Jackson": "Pop|R&B",
    "Prince": "Pop|Funk|R&B",
    "Madonna": "Pop",
    "Lenny Kravitz": "Pop Rock|R&B|Funk",
    "Bruno Mars": "Pop|R&B|Funk",
    "Ed Sheeran": "Pop|Folk",
    "John Lennon": "Pop Rock|Classic Rock",
    "Paul McCartney": "Pop Rock|Classic Rock",
    "Elvis Presley": "Rock and Roll|Country Rock",
    "Roy Orbison": "Rock and Roll|Pop",
    "Chuck Berry": "Rock and Roll|Blues Rock",
    "Little Richard": "Rock and Roll",
    "Buddy Holly": "Rock and Roll",

    # Folk / Country / Singer-Songwriter
    "Cat Stevens": "Folk|Pop",
    "Paul Simon": "Folk Rock|Pop",
    "James Taylor": "Folk Rock|Pop",
    "Joni Mitchell": "Folk|Pop",
    "Gordon Lightfoot": "Folk|Country Rock",
    "Leonard Cohen": "Folk|Pop",
    "Nick Drake": "Folk",
    "Jackson Browne": "Folk Rock|Country Rock",
    "Doobie Brothers": "Classic Rock|Southern Rock",
    "The Doobie Brothers": "Classic Rock|Southern Rock",

    # Funk / Soul / R&B
    "Chic": "Funk|Disco",
    "Earth Wind & Fire": "Funk|Soul",
    "Kool & The Gang": "Funk|Soul",
    "Parliament": "Funk",
    "Funkadelic": "Funk|Rock",
    "Stevie Wonder": "R&B|Funk|Soul",
    "James Brown": "R&B|Funk|Soul",
    "Otis Redding": "Soul|R&B",
    "Marvin Gaye": "Soul|R&B",
    "Aretha Franklin": "Soul|R&B",
    "Sly & The Family Stone": "Funk|Soul|Rock",

    # Jazz
    "Miles Davis": "Jazz",
    "John Coltrane": "Jazz",
    "Charlie Parker": "Jazz",
    "Wes Montgomery": "Jazz",
    "Django Reinhardt": "Jazz|Gypsy Jazz",
    "Pat Metheny": "Jazz|Fusion",
    "John Scofield": "Jazz|Fusion",
    "Herbie Hancock": "Jazz|Fusion",

    # Reggae
    "Bob Marley": "Reggae",
    "Bob Marley & The Wailers": "Reggae",
    "The Wailers": "Reggae",
    "Peter Tosh": "Reggae",
    "Jimmy Cliff": "Reggae",

    # Post-2000 Rock / Indie
    "The Killers": "Indie Rock|Post-Punk",
    "Kaiser Chiefs": "Indie Rock|Post-Punk",
    "The Libertines": "Indie Rock|Post-Punk",
    "The Hives": "Punk|Garage Rock",
    "The Vines": "Garage Rock|Alternative Rock",
    "Kings of Leon": "Indie Rock|Alternative Rock",
    "Vampire Weekend": "Indie Rock",
    "Tame Impala": "Psychedelic Rock|Indie Rock",
    "Royal Blood": "Hard Rock|Alternative Rock",
    "Rival Sons": "Hard Rock|Blues Rock",
    "Greta Van Fleet": "Hard Rock|Classic Rock",
    "Jack Johnson": "Folk Rock|Pop",
    "Dave Matthews Band": "Alternative Rock|Jam Rock",
    "Red Hot Chili Peppers": "Alternative Rock|Funk Rock",
    "Foo Fighters": "Alternative Rock|Hard Rock",
    "Chris Cornell": "Alternative Rock",
    "Twenty One Pilots": "Alternative Rock|Pop",
    "Imagine Dragons": "Alternative Rock|Pop Rock",
    "Hozier": "Blues Rock|Soul",
    "The 1975": "Indie Rock|Pop",
    "Cage The Elephant": "Alternative Rock|Indie Rock",

    # French Rock / French Pop
    "Téléphone": "French Rock",
    "Telephone": "French Rock",
    "Indochine": "French Rock|New Wave",
    "Francis Cabrel": "French Pop|Folk",
    "Renaud": "French Pop|Folk",
    "Noir Désir": "French Rock|Alternative Rock",
    "Bashung": "French Rock|Alternative Rock",
    "Jean-Jacques Goldman": "French Pop|French Rock",
    "Julien Doré": "French Pop",
    "Benjamin Biolay": "French Pop",
    "Camille": "French Pop",
    "Syd Matters": "Indie Rock|French Rock",
    "Pony Pony Run Run": "Indie Rock|French Rock",
    "Phoenix": "Indie Rock|French Pop",
    "Daft Punk": "Electronic|French Pop",
    "Air": "Electronic|French Pop",

    # Other notable
    "Dire Straits": "Classic Rock",
    "Mark Knopfler": "Classic Rock|Blues Rock",
    "Sting": "Pop Rock|Jazz",
    "The Police": "Rock|Reggae Rock|New Wave",
    "Bryan Adams": "Rock|Pop Rock",
    "Foreigner": "Hard Rock|Classic Rock",
    "Journey": "Hard Rock|Classic Rock",
    "Boston": "Hard Rock|Classic Rock",
    "Kansas": "Progressive Rock|Classic Rock",
    "Styx": "Progressive Rock|Hard Rock",
    "REO Speedwagon": "Classic Rock|Pop Rock",
    "Heart": "Hard Rock|Classic Rock",
    "Pat Benatar": "Hard Rock|Pop Rock",
    "Joan Jett": "Hard Rock|Punk",
    "Blondie": "New Wave|Punk",
    "Cyndi Lauper": "New Wave|Pop",
    "Billy Joel": "Pop Rock|Classic Rock",
    "Elton John": "Pop Rock|Classic Rock",
    "Rod Stewart": "Classic Rock|Pop Rock",
    "Stevie Nicks": "Pop Rock|Classic Rock",
    "The Cranberries": "Alternative Rock|Indie Rock",
    "Alanis Morissette": "Alternative Rock|Pop Rock",
    "Sheryl Crow": "Pop Rock|Alternative Rock",
    "Melissa Etheridge": "Rock|Pop Rock",
    "Tracy Chapman": "Folk Rock|R&B",
    "Dave Matthews": "Alternative Rock",
    "Ben Harper": "Blues Rock|Folk Rock",
    "Jason Mraz": "Pop|Folk Pop",
    "Damien Rice": "Folk|Indie",
    "Sufjan Stevens": "Folk|Indie",
    "Iron & Wine": "Folk|Indie",
    "Bon Iver": "Indie Folk",
    "Mumford & Sons": "Folk Rock|Indie Folk",
    "The Lumineers": "Folk Rock|Indie Folk",
    "Of Monsters and Men": "Indie Folk|Indie Rock",
    "Passenger": "Folk Pop",
    "James Bay": "Pop Rock|Folk",
}


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée CLI. Retourne le code de sortie."""
    ensure_printable_output()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tsv", default=None, help="Chemin vers songs_index.tsv")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    tsv_path = Path(args.tsv) if args.tsv else paths.songs_index_path()
    if not tsv_path.exists():
        print(f"ERREUR : {tsv_path} introuvable")
        return 1

    rows = []
    with open(tsv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        fieldnames = reader.fieldnames
        rows = list(reader)

    tagged = 0
    for row in rows:
        artist = row.get("artist", "").strip()
        genre_current = row.get("genre", "").strip()

        if genre_current:  # Ne pas écraser les valeurs manuelles
            continue

        # Chercher dans la table (case insensitive)
        genre_found = None
        for key, genre in ARTIST_GENRES.items():
            if artist.lower() == key.lower():
                genre_found = genre
                break

        if genre_found:
            row["genre"] = genre_found
            tagged += 1

    print(f"[tag_genres] {tagged} entrées taggées (sur {len(rows)} total)")

    if not args.dry_run:
        with open(tsv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t",
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(f"[done] songs_index.tsv mis à jour avec {tagged} genres")
    else:
        print(f"[dry-run] {tagged} genres seraient ajoutés")

    return 0


if __name__ == "__main__":
    sys.exit(main())
