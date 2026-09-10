"""Curate ~100 beginner-friendly guitar songs not yet in collection.

Selection criteria:
- Open chords or simple power-chord progressions (3-5 chords)
- No technically demanding lead playing required to learn the song
- Slow-to-moderate tempo
- Famous enough that a Songsterr search returns a clean result

Writes prompt-songsterr-<date>.md with the filtered list + Songsterr search URLs.

Usage :
    python -m fretwise.partitions.curate_beginners [--root PATH]
"""

from __future__ import annotations

import argparse
import csv
import datetime
import re
import sys
import unicodedata
import urllib.parse
from collections.abc import Sequence
from pathlib import Path

from fretwise.partitions import paths
from fretwise.partitions.console import ensure_printable_output


def norm(s: str) -> str:
    """Normalisation lâche pour comparaison anti-doublon."""
    s = s.lower().replace("_", "")
    s = re.sub(r"[.,!?\'\"()&]", "", s)
    s = re.sub(r"\b(and|et)\b", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s


def load_skip(index_path: Path) -> set[tuple[str, str]]:
    """Charge les identités (artist, title) déjà possédées depuis songs_index.tsv."""
    skip = set()
    with open(index_path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            title = re.sub(r"\s*_fingered\s*$", "", r["title"], flags=re.I)
            title = re.sub(r"\s*test\d*\s*\d*[a-z]*\s*$", "", title, flags=re.I)
            skip.add((norm(r["artist"]), norm(title)))
    return skip


# Curated beginner pool — built from well-known easy-guitar repertoire,
# balanced between EN rock/pop and FR chanson to match user's collection.
# (Conservé tel quel depuis _curate_beginners.py — pool codé en dur.)
CANDIDATES = [
    # The Beatles — easy strummers
    ("The Beatles", "Let It Be"),
    ("The Beatles", "Hey Jude"),
    ("The Beatles", "Yesterday"),
    ("The Beatles", "Twist And Shout"),
    ("The Beatles", "Eight Days A Week"),
    ("The Beatles", "Love Me Do"),
    ("The Beatles", "I Saw Her Standing There"),
    ("The Beatles", "All My Loving"),
    # CCR
    ("Creedence Clearwater Revival", "Bad Moon Rising"),
    ("Creedence Clearwater Revival", "Have You Ever Seen The Rain"),
    ("Creedence Clearwater Revival", "Down On The Corner"),
    ("Creedence Clearwater Revival", "Up Around The Bend"),
    # Bob Dylan
    ("Bob Dylan", "Knockin' On Heaven's Door"),
    ("Bob Dylan", "Blowin' In The Wind"),
    ("Bob Dylan", "Like A Rolling Stone"),
    ("Bob Dylan", "The Times They Are A-Changin'"),
    # Tom Petty
    ("Tom Petty", "Free Fallin'"),
    ("Tom Petty", "Learning To Fly"),
    ("Tom Petty", "I Won't Back Down"),
    ("Tom Petty", "American Girl"),
    # Neil Young — acoustic easy
    ("Neil Young", "Heart Of Gold"),
    ("Neil Young", "Old Man"),
    ("Neil Young", "Harvest Moon"),
    # Eagles
    ("The Eagles", "Take It Easy"),
    ("The Eagles", "Peaceful Easy Feeling"),
    ("The Eagles", "Tequila Sunrise"),
    # Lynyrd Skynyrd / southern easy
    ("Lynyrd Skynyrd", "Sweet Home Alabama"),
    ("Lynyrd Skynyrd", "Simple Man"),
    # Easy classic-rock riffs in open position
    ("Deep Purple", "Smoke On The Water"),
    ("Black Sabbath", "Iron Man"),
    ("Black Sabbath", "Paranoid"),
    ("Cream", "Sunshine Of Your Love"),
    ("Eric Clapton", "Wonderful Tonight"),
    ("Eric Clapton", "Layla (Unplugged)"),
    ("Eric Clapton", "Tears In Heaven"),
    ("The Animals", "House Of The Rising Sun"),
    ("The Kinks", "You Really Got Me"),
    ("The Kinks", "All Day And All Of The Night"),
    ("The Troggs", "Wild Thing"),
    # Oasis
    ("Oasis", "Wonderwall"),
    ("Oasis", "Don't Look Back In Anger"),
    ("Oasis", "Stop Crying Your Heart Out"),
    ("Oasis", "Stand By Me"),
    # Green Day — power-chord beginner staples
    ("Green Day", "Good Riddance (Time Of Your Life)"),
    ("Green Day", "Boulevard Of Broken Dreams"),
    ("Green Day", "21 Guns"),
    ("Green Day", "Wake Me Up When September Ends"),
    ("Green Day", "Basket Case"),
    # Sum 41 / pop-punk beginner
    ("Sum 41", "In Too Deep"),
    ("Sum 41", "Pieces"),
    ("Blink-182", "All The Small Things"),
    ("Blink-182", "What's My Age Again?"),
    ("Blink-182", "I Miss You"),
    # Pearl Jam easier
    ("Pearl Jam", "Yellow Ledbetter"),
    ("Pearl Jam", "Last Kiss"),
    ("Pearl Jam", "Black"),
    # Nirvana easy
    ("Nirvana", "Polly"),
    ("Nirvana", "About A Girl"),
    ("Nirvana", "Something In The Way"),
    # Foo Fighters
    ("Foo Fighters", "My Hero"),
    ("Foo Fighters", "Times Like These"),
    ("Foo Fighters", "Best Of You"),
    # Coldplay
    ("Coldplay", "Yellow"),
    ("Coldplay", "The Scientist"),
    ("Coldplay", "Fix You"),
    ("Coldplay", "Viva La Vida"),
    # Radiohead — easy ones
    ("Radiohead", "Creep"),
    ("Radiohead", "No Surprises"),
    # Easy blues / blues standards
    ("B.B. King", "The Thrill Is Gone"),
    ("John Lee Hooker", "Boom Boom"),
    ("Muddy Waters", "Mannish Boy"),
    ("Robert Johnson", "Sweet Home Chicago"),
    ("Howlin' Wolf", "Spoonful"),
    # Singer-songwriter easy
    ("Jack Johnson", "Banana Pancakes"),
    ("Jack Johnson", "Better Together"),
    ("Jason Mraz", "I'm Yours"),
    ("Jason Mraz", "I Won't Give Up"),
    ("Ed Sheeran", "Thinking Out Loud"),
    ("Ed Sheeran", "Perfect"),
    ("Ed Sheeran", "Photograph"),
    ("Ed Sheeran", "Shape Of You"),
    ("John Mayer", "Free Fallin' (Live)"),
    ("John Mayer", "Stop This Train"),
    ("Tracy Chapman", "Fast Car"),
    ("Tracy Chapman", "Talkin' 'Bout A Revolution"),
    # Bob Marley — easy reggae
    ("Bob Marley", "Three Little Birds"),
    ("Bob Marley", "No Woman No Cry"),
    ("Bob Marley", "Redemption Song"),
    ("Bob Marley", "One Love"),
    # Bryan Adams / pop-rock easy
    ("Bryan Adams", "Summer Of '69"),
    ("Bryan Adams", "Heaven"),
    # Misc EN easy hits
    ("Toto", "Africa"),
    ("Toto", "Hold The Line"),
    ("Survivor", "Eye Of The Tiger"),
    ("Joan Jett", "I Love Rock 'N Roll"),
    ("Twisted Sister", "We're Not Gonna Take It"),
    ("Bon Jovi", "Wanted Dead Or Alive"),
    ("Bon Jovi", "Livin' On A Prayer"),
    ("Cyndi Lauper", "Time After Time"),
    ("Roy Orbison", "Pretty Woman"),
    ("Buddy Holly", "Peggy Sue"),
    ("Chuck Berry", "Johnny B Goode"),
    # French chanson — open chords
    ("Francis Cabrel", "Je L'aime A Mourir"),
    ("Francis Cabrel", "Petite Marie"),
    ("Francis Cabrel", "L'encre De Tes Yeux"),
    ("Francis Cabrel", "Octobre"),
    ("Francis Cabrel", "La Corrida"),
    ("Renaud", "Mistral Gagnant"),
    ("Renaud", "Dès Que Le Vent Soufflera"),
    ("Renaud", "Manhattan-Kaboul"),
    ("Jean-Jacques Goldman", "Comme Toi"),
    ("Jean-Jacques Goldman", "Quand La Musique Est Bonne"),
    ("Jean-Jacques Goldman", "Là-Bas"),
    ("Jean-Jacques Goldman", "Envole-Moi"),
    ("Jacques Brel", "Ne Me Quitte Pas"),
    ("Jacques Brel", "Amsterdam"),
    ("Georges Brassens", "Les Copains D'abord"),
    ("Georges Brassens", "Chanson Pour L'auvergnat"),
    ("Charles Aznavour", "La Bohème"),
    ("Charles Aznavour", "Emmenez-Moi"),
    ("Michel Sardou", "Les Lacs Du Connemara"),
    ("Michel Sardou", "La Maladie D'amour"),
    ("Joe Dassin", "Les Champs-Élysées"),
    ("Joe Dassin", "Et Si Tu N'existais Pas"),
    ("Téléphone", "Cendrillon"),
    ("Téléphone", "Un Autre Monde"),
    ("Téléphone", "La Bombe Humaine"),
    ("Indochine", "L'aventurier"),
    ("Indochine", "J'ai Demandé À La Lune"),
    ("Noir Désir", "Le Vent Nous Portera"),
    ("Louise Attaque", "J't'emmène Au Vent"),
    ("Louise Attaque", "Léa"),
    ("Mickey 3D", "Respire"),
    ("Calogero", "En Apesanteur"),
    ("Patrick Bruel", "Place Des Grands Hommes"),
    ("Yves Duteil", "Prendre Un Enfant"),
    ("Vianney", "Pas Là"),
    ("Vianney", "Je M'en Vais"),
    ("Stromae", "Papaoutai"),
    ("Stromae", "Alors On Danse"),
    ("Stromae", "Tous Les Mêmes"),
    ("Zaz", "Je Veux"),
    # === expansion: artists confirmed NOT in collection ===
    # Modern pop/rock — easy 4-chord
    ("Taylor Swift", "Love Story"),
    ("Taylor Swift", "Shake It Off"),
    ("Taylor Swift", "You Belong With Me"),
    ("Taylor Swift", "Cardigan"),
    ("Taylor Swift", "Anti-Hero"),
    ("Sam Smith", "Stay With Me"),
    ("Sam Smith", "I'm Not The Only One"),
    ("Lewis Capaldi", "Someone You Loved"),
    ("Lewis Capaldi", "Before You Go"),
    ("Lewis Capaldi", "Bruises"),
    ("Tom Odell", "Another Love"),
    ("George Ezra", "Budapest"),
    ("George Ezra", "Shotgun"),
    ("George Ezra", "Paradise"),
    ("The Script", "The Man Who Can't Be Moved"),
    ("The Script", "Breakeven"),
    ("Shawn Mendes", "Treat You Better"),
    ("Shawn Mendes", "Stitches"),
    ("Shawn Mendes", "Mercy"),
    ("Vance Joy", "Riptide"),
    ("Passenger", "Let Her Go"),
    ("James Bay", "Let It Go"),
    ("James Bay", "Hold Back The River"),
    ("Hozier", "Take Me To Church"),
    ("Imagine Dragons", "Radioactive"),
    ("Imagine Dragons", "Believer"),
    ("Imagine Dragons", "Demons"),
    ("OneRepublic", "Counting Stars"),
    ("OneRepublic", "Apologize"),
    ("Maroon 5", "Sunday Morning"),
    ("Maroon 5", "She Will Be Loved"),
    ("Maroon 5", "This Love"),
    ("The Lumineers", "Ho Hey"),
    ("The Lumineers", "Stubborn Love"),
    ("The Lumineers", "Ophelia"),
    ("Of Monsters And Men", "Little Talks"),
    ("Mumford And Sons", "I Will Wait"),
    ("Mumford And Sons", "Little Lion Man"),
    ("Mumford And Sons", "The Cave"),
    ("Noah Kahan", "Stick Season"),
    ("Noah Kahan", "Dial Drunk"),
    ("Dean Lewis", "Be Alright"),
    ("Phoebe Bridgers", "Motion Sickness"),
    ("Gregory Alan Isakov", "Big Black Car"),
    ("Iron And Wine", "Such Great Heights"),
    ("Bon Iver", "Skinny Love"),
    ("Dermot Kennedy", "Outnumbered"),
    # Ed Sheeran extra
    ("Ed Sheeran", "Castle On The Hill"),
    ("Ed Sheeran", "The A Team"),
    # Country / folk easy
    ("Luke Combs", "Beautiful Crazy"),
    ("Luke Combs", "Hurricane"),
    ("Chris Stapleton", "Tennessee Whiskey"),
    ("Kacey Musgraves", "Rainbow"),
    ("Zach Bryan", "Something In The Orange"),
    ("Morgan Wallen", "Whiskey Glasses"),
    ("Willie Nelson", "On The Road Again"),
    ("Willie Nelson", "Always On My Mind"),
    ("Dolly Parton", "Jolene"),
    ("Dolly Parton", "9 To 5"),
    ("Kenny Rogers", "The Gambler"),
    ("Jimmy Buffett", "Margaritaville"),
    ("Jim Croce", "Time In A Bottle"),
    ("Jim Croce", "Operator"),
    ("Cat Stevens", "Wild World"),
    ("Cat Stevens", "Father And Son"),
    ("Cat Stevens", "The First Cut Is The Deepest"),
    ("Donovan", "Catch The Wind"),
    ("Simon And Garfunkel", "Scarborough Fair"),
    ("Simon And Garfunkel", "The Sound Of Silence"),
    ("Simon And Garfunkel", "Mrs. Robinson"),
    ("Simon And Garfunkel", "The Boxer"),
    ("Leonard Cohen", "Hallelujah"),
    ("Leonard Cohen", "Suzanne"),
    ("The Everly Brothers", "All I Have To Do Is Dream"),
    ("Ritchie Valens", "La Bamba"),
    ("Frank Sinatra", "My Way"),
    ("Bill Withers", "Lean On Me"),
    ("Bill Withers", "Ain't No Sunshine"),
    ("Bill Withers", "Lovely Day"),
    ("Bobby McFerrin", "Don't Worry Be Happy"),
    ("Israel Kamakawiwo'ole", "Somewhere Over The Rainbow"),
    ("Manu Chao", "Me Gustas Tu"),
    ("Manu Chao", "Bongo Bong"),
    ("Manu Chao", "Clandestino"),
    # More easy classic-rock / pop
    ("Elvis Presley", "Can't Help Falling In Love"),
    ("Elvis Presley", "Hound Dog"),
    ("Roy Orbison", "Crying"),
    ("The Mamas And The Papas", "California Dreamin'"),
    ("Five For Fighting", "Superman"),
    ("Goo Goo Dolls", "Iris"),
    ("Goo Goo Dolls", "Name"),
    ("Counting Crows", "Mr. Jones"),
    ("Counting Crows", "A Long December"),
    ("Train", "Hey Soul Sister"),
    ("Train", "Drops Of Jupiter"),
    ("Plain White T's", "Hey There Delilah"),
    ("Daniel Powter", "Bad Day"),
    ("Gnarls Barkley", "Crazy"),
    ("MGMT", "Kids"),
    ("MGMT", "Electric Feel"),
    ("Florence And The Machine", "Dog Days Are Over"),
    # Reggae / world easy
    ("UB40", "Red Red Wine"),
    ("Inner Circle", "Sweat (A La La La La Long)"),
    # French chanson — older not-owned
    ("Edith Piaf", "La Vie En Rose"),
    ("Edith Piaf", "Non Je Ne Regrette Rien"),
    ("Charles Trenet", "La Mer"),
    ("Yves Montand", "Les Feuilles Mortes"),
    ("Henri Salvador", "Jardin D'hiver"),
    ("Henri Salvador", "Syracuse"),
    ("Françoise Hardy", "Tous Les Garçons Et Les Filles"),
    ("Françoise Hardy", "Le Temps De L'amour"),
    ("Serge Gainsbourg", "La Javanaise"),
    ("Serge Gainsbourg", "Je Suis Venu Te Dire Que Je M'en Vais"),
    ("Claude François", "Comme D'habitude"),
    ("Dalida", "Paroles Paroles"),
    ("Julien Clerc", "Femmes Je Vous Aime"),
    ("William Sheller", "Un Homme Heureux"),
    ("Étienne Daho", "Week-End À Rome"),
    ("Pascal Obispo", "Lucie"),
    ("Garou", "Belle"),
    # French — newer
    ("Clara Luciani", "La Grenade"),
    ("Clara Luciani", "Respire Encore"),
    ("Angèle", "Balance Ton Quoi"),
    ("Angèle", "Bruxelles Je T'aime"),
    ("Julien Doré", "Coco Câline"),
    ("Julien Doré", "Le Lac"),
    ("Vianney", "Je M'en Vais"),
    ("Vianney", "Pas Là"),
    ("Vianney", "Moi Aimer Toi"),
    ("Stromae", "Formidable"),
    ("Bigflo Et Oli", "Dommage"),
    ("Orelsan", "Basique"),
    ("Orelsan", "L'odeur De L'essence"),
    ("Tryo", "L'hymne De Nos Campagnes"),
    ("Tryo", "Désolé Pour Hier Soir"),
    ("Aaron", "U-Turn (Lili)"),
    ("Pomme", "Ceux Qui Rêvent"),
    ("Pomme", "Anxiété"),
    ("Barbara Pravi", "Voilà"),
    ("Thérapie Taxi", "Hit Sale"),
    # More easy hits
    ("R.E.M.", "Losing My Religion"),
    ("R.E.M.", "Everybody Hurts"),
    ("U2", "With Or Without You"),
    ("U2", "One"),
    ("U2", "Sunday Bloody Sunday"),
    ("The Cranberries", "Zombie"),
    ("The Cranberries", "Linger"),
    ("Sixpence None The Richer", "Kiss Me"),
    ("Natalie Imbruglia", "Torn"),
    ("Wheatus", "Teenage Dirtbag"),
    ("Semisonic", "Closing Time"),
    ("Hootie And The Blowfish", "Only Wanna Be With You"),
    ("Third Eye Blind", "Semi-Charmed Life"),
    ("Eagle-Eye Cherry", "Save Tonight"),
    ("Savage Garden", "Truly Madly Deeply"),
    ("Roxette", "Listen To Your Heart"),
    # Christmas / sing-along easy
    ("Wham!", "Last Christmas"),
    ("Mariah Carey", "All I Want For Christmas Is You"),
    ("José Feliciano", "Feliz Navidad"),
]


def encode_url(artist: str, title: str) -> str:
    """URL de recherche Songsterr pour un couple artiste/titre."""
    q = f"{title} {artist}"
    q = urllib.parse.quote_plus(q)
    return f"https://www.songsterr.com/?pattern={q}"


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée CLI. Retourne le code de sortie."""
    ensure_printable_output()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None, help="Racine du workspace partitions")
    args = ap.parse_args(argv)

    root = Path(args.root) if args.root else paths.partitions_root()
    index_path = paths.songs_index_path(root)

    skip = load_skip(index_path)
    print(f"skip set: {len(skip)} owned songs")

    kept = []
    dropped = []
    seen = set()
    for artist, title in CANDIDATES:
        key = (norm(artist), norm(title))
        if key in seen:
            continue
        seen.add(key)
        if key in skip:
            dropped.append((artist, title))
        else:
            kept.append((artist, title))

    print(f"candidates: {len(CANDIDATES)}  kept: {len(kept)}  dropped (owned): {len(dropped)}")
    if dropped:
        print("  dropped because already owned:")
        for a, t in dropped[:20]:
            print(f"    - {a} — {t}")
        if len(dropped) > 20:
            print(f"    ... ({len(dropped)-20} more)")

    final = kept[:100]
    print(f"final list size: {len(final)}")

    date = datetime.date.today().strftime("%Y-%m-%d")
    out_path = root / f"prompt-songsterr-{date}.md"
    lines = []
    lines.append(f"# 100 beginner-friendly guitar songs — Songsterr search URLs ({date})")
    lines.append("")
    lines.append("Selection criteria : open chords / simple power chords, "
                 "3–5 chord progressions,")
    lines.append("slow-to-moderate tempo, no lead-guitar prerequisites. "
                 "Mix EN rock/pop + FR chanson.")
    lines.append(f"Filtered against current collection "
                 f"({len(skip)} unique owned songs in `partitions/`).")
    lines.append("")
    lines.append('Format : numbered entry "Artist — Title" followed by Songsterr search URL.')
    lines.append("")
    for i, (artist, title) in enumerate(final, 1):
        lines.append(f"{i}. {artist} — {title}")
        lines.append(f"   {encode_url(artist, title)}")
    lines.append("")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"written: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
