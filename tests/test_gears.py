"""Tests for the multi-model gears layer: shared naming + schema adapter."""

from __future__ import annotations

from fretwise.gears import (
    gears_filename,
    gears_key,
    gears_key_from_filename,
    slugify,
    song_output_to_view,
)


# --- naming -----------------------------------------------------------------

def test_slugify_strips_accents_and_punctuation():
    assert slugify("Arctic Monkeys") == "arctic-monkeys"
    assert slugify("Numb / Encore") == "numb-encore"
    assert slugify("Sympathy & Co.") == "sympathy-and-co"
    assert slugify("Café déjà-vu!") == "cafe-deja-vu"


def test_slugify_empty_and_nonalpha_returns_empty():
    assert slugify("") == ""
    assert slugify("   ") == ""
    assert slugify("!!!") == ""


def test_gears_key_is_artist_double_underscore_title():
    assert gears_key("AC/DC", "Highway to Hell") == "ac-dc__highway-to-hell"
    assert gears_filename("AC/DC", "Highway to Hell") == "ac-dc__highway-to-hell.json"


def test_gears_key_from_filename_splits_artist_title():
    assert gears_key_from_filename("Arctic Monkeys - When The Sun Goes Down.gp5") == (
        "arctic-monkeys__when-the-sun-goes-down"
    )


def test_gears_key_from_filename_strips_date_and_fingered():
    assert gears_key_from_filename("AC_DC - Thunderstruck - 02-11-2026_fingered.gp5") == (
        "ac-dc__thunderstruck"
    )


def test_gears_key_from_filename_title_only():
    assert gears_key_from_filename("Improvisation.mid") == "__improvisation"


# --- adapter: songsgear.fretwise.rig.v1 -------------------------------------

def _v1(confidence: str = "high") -> dict:
    return {
        "schemaVersion": "songsgear.fretwise.rig.v1",
        "exportKind": "rig",
        "song": {"artist": "AC/DC", "title": "Highway to Hell", "album": "Highway to Hell",
                 "year": 1979, "genre": "hard rock"},
        "rig": {
            "rigName": "AC/DC - Highway to Hell - Valeton GP-180",
            "status": "draft", "confidence": confidence, "needsReview": True,
            "equipment": {"model": "Valeton GP-180"},
            "guitar": "Gibson SG", "output": "FRFR / headphones",
            "toneProfile": "Medium gain crunch.",
            "signalChainSummary": "UK SLP into UK Vintage 4x12.",
            "blocks": [
                {"order": 6, "role": "Amplifier", "module": "AMP", "model": "UK SLP", "active": True,
                 "settings": {"gain": 42, "bass": 44, "middle": 66}, "purpose": "Plexi.",
                 "matchQuality": "exact", "gap": "", "alternatives": []},
                {"order": 7, "role": "Cabinet", "module": "CAB/IR", "model": "UK Vintage 4x12",
                 "active": True, "settings": {"mic": "SM57"}, "purpose": "", "matchQuality": "close",
                 "gap": "Speaker not exact.", "alternatives": [{"model": "US 4x12", "reason": "alt"}]},
                {"order": 5, "role": "Capture", "module": "N->S", "model": "None", "active": False,
                 "settings": {}, "purpose": "", "matchQuality": "acceptable", "gap": "", "alternatives": []},
            ],
        },
        "musicalVerdict": {"targetTone": "Classic AC/DC crunch.", "mustHave": ["Power-amp drive"],
                           "avoid": ["High gain"], "gearClues": ["Marshall Plexi"], "corrections": [],
                           "confidence": "high", "needsManualReview": False},
        "musicalContext": {"primaryGenre": "hard rock", "styleTags": ["classic rock"],
                           "targetTone": "Crunch", "confidence": "high"},
        "improvements": {"summary": "Strong match.", "proposals": [
            {"priority": "P1", "type": "IR", "target": "Cabinet", "recommendedAsset": "Greenback IR",
             "reason": "Best gain.", "replacesBlockOrder": 7, "whenToUse": "always",
             "expectedGain": "high", "requiredIfGp180Gap": True}]},
        "validation": {"ok": True, "errors": [], "warnings": ["Multi-track studio."]},
        "source": {"workflow": "economic_production_v1", "finalVerdictSource": "openai",
                   "usedLocalGp180Fallback": False, "usedLocalImprovementsFallback": False},
    }


def test_v1_maps_song_grade_and_genre():
    view = song_output_to_view(_v1())
    assert view["artist"] == "AC/DC"
    assert view["song"] == "Highway to Hell"
    assert view["genre"] == "hard rock"
    assert view["fiabilite"] == "A"  # confidence high -> A
    assert view["is_gears"] is True


def test_v1_builds_chain_with_amp_and_ascii_ns_module():
    view = song_output_to_view(_v1())
    assert list(view["reglages"].keys()) == view["chain"]
    amp = view["reglages"]["AMP"]
    assert amp["active"] is True and amp["preset"] == "UK SLP"
    assert amp["params"].startswith("Gain 42 · Bass 44 · Middle 66")
    cab = view["reglages"]["CAB/IR"]
    assert cab["active"] is True and cab["alternatives"] == ["US 4x12"]
    # "N->S" (ASCII) must canonicalize to the chain's "N→S" slot and stay inactive.
    assert view["reglages"]["N→S"]["active"] is False


def test_v1_carries_guitar_notes_limits_and_sidecars():
    view = song_output_to_view(_v1())
    assert view["recommended_guitar"] == "Gibson SG"
    assert "Medium gain crunch." in view["notes"]
    assert "À garder : Power-amp drive" in view["notes"]
    assert "À éviter : High gain" in view["limites"]
    assert "Multi-track studio." in view["limites"]
    assert "CAB/IR: Speaker not exact." in view["limites"]
    assert view["improvements"]["proposals"][0]["priority"] == "P1"
    assert view["musical_verdict"]["targetTone"] == "Classic AC/DC crunch."
    assert view["musical_context"]["primaryGenre"] == "hard rock"
    assert view["comments"] == "Classic AC/DC crunch."


def test_v1_grade_table():
    grades = {"high": "A", "medium/high": "B", "medium": "C", "low": "D", "unknown": "D"}
    for confidence, expected in grades.items():
        assert song_output_to_view(_v1(confidence))["fiabilite"] == expected, confidence


# --- adapter: songsgear.fretwise.gear.v2 compact ----------------------------

def test_compact_v2_maps_to_same_render_view():
    doc = {
        "schemaVersion": "songsgear.fretwise.gear.v2",
        "id": "AC_DC__Highway_To_Hell",
        "song": {
            "artist": "AC/DC",
            "title": "Highway To Hell",
            "genre": "hard rock",
            "subgenres": ["classic rock"],
            "genreConfidence": "high",
        },
        "credits": {
            "guitar": {
                "guitaristsText": "Angus Young / Malcolm Young",
                "guitarists": ["Angus Young", "Malcolm Young"],
                "type": "Solid-body electric",
                "modelsText": "Gibson SG (Angus) / Gretsch Jet Firebird (Malcolm)",
                "models": ["Gibson SG (Angus)", "Gretsch Jet Firebird (Malcolm)"],
                "confidence": "high",
                "evidence": "trained knowledge",
                "notes": "Iconic pairing.",
                "source": "songs_guitar_enriched_audited.json",
            }
        },
        "tone": {
            "target": "Classic AC/DC crunch.",
            "profile": "Medium gain crunch.",
            "summary": "UK SLP into UK Vintage 4x12.",
            "mustHave": ["Power-amp drive"],
            "avoid": ["High gain"],
            "gearClues": ["Marshall Plexi"],
            "corrections": [],
            "confidence": "high",
            "needsReview": True,
        },
        "rig": {
            "name": "AC/DC - Highway To Hell - Valeton GP-180",
            "confidence": "high",
            "equipment": {"model": "Valeton GP-180"},
            "recommendedGuitar": "Default electric guitar",
            "output": "FRFR / headphones",
            "blocks": [
                {"order": 6, "role": "Amplifier", "module": "AMP", "model": "UK SLP", "active": True,
                 "settings": {"gain": 42}, "purpose": "Plexi.", "matchQuality": "exact", "gap": "",
                 "alternatives": []},
            ],
        },
        "improvements": {"summary": "Strong match.", "proposals": []},
        "audit": {"validation": {"ok": True, "errors": [], "warnings": ["Multi-track studio."]}},
    }

    view = song_output_to_view(doc)
    assert view["artist"] == "AC/DC"
    assert view["song"] == "Highway To Hell"
    assert view["fiabilite"] == "A"
    assert view["reglages"]["AMP"]["preset"] == "UK SLP"
    assert "À garder : Power-amp drive" in view["notes"]
    assert "Multi-track studio." in view["limites"]
    assert view["guitare_originale"] == "Gibson SG (Angus) / Gretsch Jet Firebird (Malcolm) (Angus Young / Malcolm Young)"


# --- adapter: legacy assembled-rig shape (back-compat) ----------------------

def test_legacy_gp180_shape_still_supported():
    doc = {
        "song": {"artist": "AC/DC", "title": "Highway to Hell"},
        "confidence": "medium",
        "general": {"toneProfile": "Crunch.", "idealSignalChain": "SG -> Plexi.",
                    "bestPossibleEquipment": [{"role": "Guitar", "model": "Gibson SG Standard", "reason": "x"}]},
        "gp180": {"equipment": {"model": "Valeton GP-180"}, "guitar": "Gibson SG",
                  "choicePolicy": "Factory.",
                  "blocks": [{"order": 6, "role": "Amplifier", "module": "AMP", "model": "UK SLP",
                              "active": True, "settings": {"gain": 42}}]},
        "improvements": {"summary": "ok", "proposals": []},
    }
    view = song_output_to_view(doc)
    assert view["fiabilite"] == "C"
    assert view["reglages"]["AMP"]["preset"] == "UK SLP"
    assert view["guitare_originale"] == "Gibson SG Standard"
