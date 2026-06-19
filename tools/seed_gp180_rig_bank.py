"""Seed FretWise's GP-180 rig bank from the captured preset list.

The GP-180 displays patches as 001..200, while FretWise stores MIDI program
numbers as zero-based values. This script converts the captured full patch names
into `partitions/rigs/rig_bank.json` and records cautious artist/genre guesses.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from fretwise.rig_bank import RigBank, RigBinding, RigProfile, save_rig_bank

SOURCE = "gp180_screenshot_2026-06-17"

PresetRow = tuple[int, str, str | None, str | None, tuple[str, ...], str]


PRESETS: tuple[PresetRow, ...] = (
    (1, "New GEN.", "modern", None, ("generic", "modern"), "Generic modern tone."),
    (2, "Dark Clean", "clean", None, ("dark",), "Dark clean preset."),
    (3, "Tweedy OD", "blues rock", None, ("fender", "tweed", "overdrive"), "Fender Tweed-style overdrive."),
    (4, "Foxy Clean", "british clean", None, ("vox", "ac30", "clean"), "Likely Vox AC-style clean."),
    (5, "Foxy OD", "british rock", None, ("vox", "ac30", "overdrive"), "Likely Vox AC-style overdrive."),
    (6, "UK900 DIST", "hard rock", None, ("marshall", "jcm900", "distortion"), "Marshall JCM900-style distortion."),
    (7, "Mess DIST", "metal", None, ("mesa", "rectifier", "distortion"), "Mesa/Boogie-style distortion."),
    (8, "Match Clean", "clean", None, ("matchless", "clean"), "Matchless-style clean."),
    (9, "Match OD", "rock", None, ("matchless", "overdrive"), "Matchless-style overdrive."),
    (10, "EV51 DIST", "hard rock", None, ("5150", "evh", "distortion"), "Likely EVH 5150-style distortion."),
    (11, "Morse Purple", "hard rock", "Steve Morse", ("deep purple",), "Likely Steve Morse / Deep Purple reference."),
    (12, "Gypsy of AT", "melodic rock", "Andy Timmons", ("electric gypsy",), "Likely Andy Timmons reference."),
    (13, "Love of Lord", "instrumental rock", "Steve Vai", ("for the love of god",), "Likely For the Love of God-style lead."),
    (14, "JS Iconic", "instrumental rock", "Joe Satriani", ("js",), "Likely Joe Satriani initials."),
    (15, "Neo-Classical", "neoclassical metal", "Yngwie Malmsteen", ("shred",), "Neoclassical lead style."),
    (16, "JP Iconic", "progressive metal", "John Petrucci", ("dream theater",), "Likely John Petrucci initials."),
    (17, "GG Iconic", "fusion", "Guthrie Govan", ("gg",), "Likely Guthrie Govan initials."),
    (18, "Racer of PG", "shred", "Paul Gilbert", ("racer x",), "Likely Paul Gilbert / Racer X reference."),
    (19, "MF Iconic", "melodic metal", "Marty Friedman", ("mf",), "Likely Marty Friedman initials; low confidence."),
    (20, "E.C. Iconic", "blues rock", "Eric Clapton", ("ec",), "Likely Eric Clapton initials."),
    (21, "Hendrix Riff", "psychedelic rock", "Jimi Hendrix", ("fuzz", "riff"), "Jimi Hendrix-style riff tone."),
    (22, "Red May", "classic rock", "Brian May", ("queen", "red special"), "Likely Brian May / Red Special reference."),
    (23, "Luke Iconic", "session rock", "Steve Lukather", ("toto",), "Likely Steve Lukather reference."),
    (24, "Mayer's OD", "blues pop", "John Mayer", ("overdrive",), "John Mayer-style overdrive."),
    (25, "Funky Clean", "funk", None, ("clean",), "Funk clean preset."),
    (26, "JAZZ Clean", "jazz", None, ("clean",), "Jazz clean preset."),
    (27, "Bluegrass", "bluegrass", None, ("acoustic",), "Bluegrass preset."),
    (28, "New wave CL", "new wave", None, ("clean", "chorus"), "New wave clean."),
    (29, "Thin Blues", "blues", None, ("thin",), "Thin blues tone."),
    (30, "Thick Blues", "blues", None, ("thick",), "Thick blues tone."),
    (31, "Fusion DST", "fusion", None, ("distortion",), "Fusion distortion."),
    (32, "Fusion OD", "fusion", None, ("overdrive",), "Fusion overdrive."),
    (33, "POP Lead", "pop", None, ("lead",), "Pop lead."),
    (34, "POP Rhythm", "pop", None, ("rhythm",), "Pop rhythm."),
    (35, "Chorus OD", "rock", None, ("chorus", "overdrive"), "Chorus overdrive."),
    (36, "Metal Core", "metalcore", None, ("metal",), "Metalcore preset."),
    (37, "Punk Rhythm", "punk", None, ("rhythm",), "Punk rhythm."),
    (38, "POP Punk", "pop punk", None, ("punk",), "Pop-punk preset."),
    (39, "J Rock", "j-rock", None, ("japanese rock",), "Japanese rock preset."),
    (40, "POST Clean", "post-rock", None, ("clean",), "Post-rock clean."),
    (41, "POST ROCK", "post-rock", None, ("ambient",), "Post-rock preset."),
    (42, "80s Clean", "80s pop", None, ("clean", "chorus"), "80s clean tone."),
    (43, "Purple Riff", "hard rock", "Deep Purple", ("smoke on the water",), "Likely Deep Purple riff reference."),
    (44, "Zeppelin Riff", "classic rock", "Led Zeppelin", ("jimmy page",), "Led Zeppelin-style riff tone."),
    (45, "Sabbath Riff", "doom metal", "Black Sabbath", ("tony iommi",), "Black Sabbath-style riff tone."),
    (46, "Back in DC", "hard rock", "AC/DC", ("back in black",), "AC/DC-style riff tone."),
    (47, "GNR Sound", "hard rock", "Guns N' Roses", ("slash",), "Guns N' Roses-style tone."),
    (48, "Numb of PF", "progressive rock", "Pink Floyd", ("comfortably numb", "david gilmour"), "Likely Pink Floyd / Comfortably Numb reference."),
    (49, "Motel CA", "classic rock", "Eagles", ("hotel california",), "Likely Hotel California reference."),
    (50, "Eddie Solo", "hard rock", "Eddie Van Halen", ("van halen", "solo"), "Eddie Van Halen-style solo tone."),
    (51, "Eddie Riff", "hard rock", "Van Halen", ("eddie van halen", "riff"), "Van Halen-style riff tone."),
    (52, "Bros in Dire", "classic rock", "Dire Straits", ("mark knopfler",), "Likely Dire Straits / Brothers in Arms reference."),
    (53, "Straits Clean", "classic rock", "Dire Straits", ("mark knopfler", "clean"), "Dire Straits-style clean tone."),
    (54, "Metal Maiden", "heavy metal", "Iron Maiden", ("maiden",), "Iron Maiden-style metal tone."),
    (55, "Metal of Lica", "thrash metal", "Metallica", ("metallica",), "Metallica-style metal tone."),
    (56, "Leopard DIST", "hard rock", "Def Leppard", ("def leppard",), "Likely Def Leppard reference."),
    (57, "Groove Cowboy", "groove metal", "Pantera", ("cowboys from hell",), "Likely Pantera / Cowboys from Hell reference."),
    (58, "Alexi & Child", "melodic death metal", "Children of Bodom", ("alexi laiho",), "Likely Alexi Laiho / Children of Bodom reference."),
    (59, "Psycho Knot", "nu metal", "Slipknot", ("psychosocial",), "Likely Slipknot reference."),
    (60, "Grunge of KC", "grunge", "Nirvana", ("kurt cobain",), "Likely Kurt Cobain initials."),
    (61, "Greenland", "pop punk", "Green Day", ("green day",), "Likely Green Day wordplay; low confidence."),
    (62, "Rammst. Metal", "industrial metal", "Rammstein", ("rammstein",), "Rammstein-style metal tone."),
    (63, "No More Doubt", "ska punk", "No Doubt", ("no doubt",), "No Doubt-style preset."),
    (64, "Really Love U", "pop rock", None, ("love",), "Song/artist inference unclear."),
    (65, "Ocean and Sky", "ambient", None, ("clean", "wide"), "Atmospheric clean preset."),
    (66, "Glorious Year", "pop rock", None, ("anthem",), "Song/artist inference unclear."),
    (67, "Hammony m3", "effect", None, ("harmony", "minor third"), "Harmony minor-third effect."),
    (68, "Hammony P5", "effect", None, ("harmony", "perfect fifth"), "Harmony perfect-fifth effect."),
    (69, "WAH-WAH LD", "effect", None, ("wah", "lead"), "Wah lead preset."),
    (70, "Auto Swell", "effect", None, ("swell",), "Auto-swell effect."),
    (71, "Step Filter", "effect", None, ("filter",), "Step filter effect."),
    (72, "Clean SYNC", "clean", None, ("sync",), "Synchronized clean effect preset."),
    (73, "Octave Fuzz", "fuzz", None, ("octave",), "Octave fuzz preset."),
    (74, "Ethereal RVB", "ambient", None, ("reverb",), "Ethereal reverb preset."),
    (75, "Leslie & Vibe", "effect", None, ("leslie", "vibe"), "Rotary/vibe preset."),
    (76, "Freeze", "effect", None, ("hold", "sustain"), "Freeze/hold effect."),
    (77, "Vibrato Jump", "effect", None, ("vibrato",), "Vibrato effect preset."),
    (78, "Crystal TREM", "effect", None, ("tremolo",), "Crystal tremolo preset."),
    (79, "Organ Synth", "synth", None, ("organ",), "Organ synth preset."),
    (80, "Luminous", "ambient", None, ("shimmer",), "Luminous ambient preset."),
    (81, "Pick-up S-H", "utility", None, ("single coil", "humbucker"), "Single-coil to humbucker pickup simulation."),
    (82, "Pick-up H-S", "utility", None, ("humbucker", "single coil"), "Humbucker to single-coil pickup simulation."),
    (83, "AC SIM", "acoustic", None, ("acoustic simulator",), "Acoustic simulator."),
    (84, "Hammy Pedal", "effect", None, ("whammy", "pitch"), "Whammy-style pitch pedal."),
    (85, "Tone crasher", "effect", None, ("bitcrusher", "tone"), "Tone/bit-crusher style effect."),
    (86, "Finger Bass", "bass", None, ("fingerstyle",), "Fingerstyle bass preset."),
    (87, "Pick Bass", "bass", None, ("pick",), "Picked bass preset."),
    (88, "Slap Bass", "bass", None, ("slap",), "Slap bass preset."),
    (89, "Bass Tapping", "bass", None, ("tapping",), "Bass tapping preset."),
    (90, "Bass Drive", "bass", None, ("drive",), "Bass drive preset."),
    (91, "Bass Dist", "bass", None, ("distortion",), "Bass distortion preset."),
    (92, "Bass Fuzz", "bass", None, ("fuzz",), "Bass fuzz preset."),
    (93, "Bass Chorus", "bass", None, ("chorus",), "Bass chorus preset."),
    (94, "Bass Q", "bass", None, ("filter", "q"), "Bass filter/Q preset."),
    (95, "Bass Synth", "bass synth", None, ("synth",), "Bass synth preset."),
    (96, "Bird AC", "acoustic", "The Beatles", ("blackbird",), "Likely Blackbird acoustic reference; low confidence."),
    (97, "Standard AC", "acoustic", None, ("standard",), "Standard acoustic preset."),
    (98, "Solo AC", "acoustic", None, ("solo",), "Acoustic solo preset."),
    (99, "12-Strings", "acoustic", None, ("12-string",), "12-string acoustic preset."),
    (100, "Finger AC", "acoustic", None, ("fingerstyle",), "Fingerstyle acoustic preset."),
    (101, "EC Cream", "blues rock", "Cream", ("eric clapton",), "Likely Eric Clapton / Cream reference."),
    (102, "It's GP-180", "demo", None, ("factory demo",), "Factory GP-180 showcase preset."),
    (103, "JohnMayer", "blues pop", "John Mayer", ("john mayer",), "John Mayer-style preset."),
    (104, "david bowie", "art rock", "David Bowie", ("david bowie",), "David Bowie-style preset."),
)


BINDINGS: tuple[tuple[str, str, str], ...] = (
    ("genre", "bluegrass", "gp180-027-bluegrass"),
    ("genre", "blues", "gp180-030-thick-blues"),
    ("genre", "funk", "gp180-025-funky-clean"),
    ("genre", "jazz", "gp180-026-jazz-clean"),
    ("genre", "metalcore", "gp180-036-metal-core"),
    ("genre", "post-rock", "gp180-041-post-rock"),
    ("genre", "punk", "gp180-037-punk-rhythm"),
    ("genre", "pop punk", "gp180-038-pop-punk"),
    ("genre", "acoustic", "gp180-097-standard-ac"),
    ("genre", "bass", "gp180-086-finger-bass"),
    ("artist", "AC/DC", "gp180-046-back-in-dc"),
    ("artist", "Pink Floyd", "gp180-048-numb-of-pf"),
    ("artist", "Dire Straits", "gp180-053-straits-clean"),
    ("artist", "Metallica", "gp180-055-metal-of-lica"),
    ("artist", "Iron Maiden", "gp180-054-metal-maiden"),
    ("artist", "Black Sabbath", "gp180-045-sabbath-riff"),
    ("artist", "Led Zeppelin", "gp180-044-zeppelin-riff"),
    ("artist", "Van Halen", "gp180-051-eddie-riff"),
    ("artist", "Eddie Van Halen", "gp180-050-eddie-solo"),
    ("artist", "Guns N' Roses", "gp180-047-gnr-sound"),
    ("artist", "John Mayer", "gp180-103-johnmayer"),
    ("artist", "Eric Clapton", "gp180-020-e-c-iconic"),
    ("artist", "Cream", "gp180-101-ec-cream"),
    ("artist", "Jimi Hendrix", "gp180-021-hendrix-riff"),
    ("artist", "Brian May", "gp180-022-red-may"),
    ("artist", "Queen", "gp180-022-red-may"),
    ("artist", "David Bowie", "gp180-104-david-bowie"),
    ("song", "Back In Black", "gp180-046-back-in-dc"),
    ("song", "Comfortably Numb", "gp180-048-numb-of-pf"),
    ("song", "Hotel California", "gp180-049-motel-ca"),
    ("song", "Sultans Of Swing", "gp180-053-straits-clean"),
    ("song", "Brothers In Arms", "gp180-052-bros-in-dire"),
    ("song", "Whole Lotta Love", "gp180-044-zeppelin-riff"),
    ("song", "Paranoid", "gp180-045-sabbath-riff"),
    ("song", "Enter Sandman", "gp180-055-metal-of-lica"),
    ("song", "Sweet Child O' Mine", "gp180-047-gnr-sound"),
    ("song", "Eruption", "gp180-050-eddie-solo"),
    ("song", "For The Love Of God", "gp180-013-love-of-lord"),
    ("song", "Smoke On The Water", "gp180-043-purple-riff"),
    ("song", "Smells Like Teen Spirit", "gp180-060-grunge-of-kc"),
)


def _profile_id(slot: int, name: str) -> str:
    slug = name.lower().replace("&", "and")
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return f"gp180-{slot:03d}-{slug}"


def build_bank() -> RigBank:
    profiles = []
    for slot, name, genre, artist, tags, inference in PRESETS:
        profile_tags = ("factory", f"slot-{slot:03d}", *tags)
        notes = f"Captured GP-180 preset name. Inference: {inference}"
        profiles.append(
            RigProfile(
                id=_profile_id(slot, name),
                name=f"{slot:03d} {name}",
                program=slot - 1,
                artist=artist,
                genre=genre,
                tags=profile_tags,
                source=SOURCE,
                notes=notes,
            )
        )
    bindings = tuple(
        RigBinding(scope=scope, key=key, profile_id=profile_id)
        for scope, key, profile_id in BINDINGS
    )
    return RigBank(profiles=tuple(profiles), bindings=bindings)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "output",
        nargs="?",
        default="partitions/rigs/rig_bank.json",
        help="Destination rig_bank.json path.",
    )
    args = parser.parse_args()
    output = Path(args.output)
    bank = build_bank()
    save_rig_bank(output, bank)
    print(f"Wrote {len(bank.profiles)} profiles and {len(bank.bindings)} bindings to {output}")


if __name__ == "__main__":
    main()
