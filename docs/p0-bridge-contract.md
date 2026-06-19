# Contrat de Bridge — Dual Pipeline FretWise

> **Branche :** `refactor/notation-core-hardening`
> **Date :** 2026-05-04
> **Contexte P0 :** analyse préalable aux fixes P0-B (mapper enrichi) et P0-C (per-measure time sig)

---

## 1. Table de correspondance des champs

Les trois colonnes représentent le parcours d'un événement note depuis le parser jusqu'au rendu SVG.

| Famille | Legacy `NoteEvent` | `CompletedScore` | Canonical `NoteEvent` | Statut |
|---|---|---|---|---|
| **Identité temporelle** | `onset`, `duration` | via `notes: list[NoteEvent]` | `onset`, `duration` (Event) | ✅ Préservé |
| **Hauteur** | `pitch` (MIDI) | idem | `pitch_sounding`, `pitch_notated` (+12 si `string_hint`) | ✅ Transformé (octave guitare) |
| **Voix** | `voice_hint: int\|None` | idem | `voice` (Event, défaut 0) | ✅ Préservé — **pas perdu** (voir §2) |
| **Mesure source** | `measure_index: int\|None` | idem | LayoutHint indirectement (calcul `_measure_index_for_note`) | ⚠️ Utilisé en lecture, jamais émis en canonical |
| **Tablature** | `string_hint`, `fret_hint` | idem | `TabInfo.string`, `TabInfo.fret` | ✅ Préservé |
| **Doigté** | _(produit par Pipeline A, non porté par NoteEvent)_ | absent | `TabInfo.left_hand_finger = None` | ❌ Non transmis |
| **Tempo** | `tempo: float` (par note) | idem (per-note) | `TempoMark(onset=0, bpm=notes[0].tempo)` | ❌ Perdu — un seul TempoMark initial |
| **Armure rythmique** | absent | `beats_per_measure`, `time_denominator` | `TimeSignature` unique pour toutes les mesures | ⚠️ Perte per-measure (cible P0-C) |
| **Dynamique** | `dynamic: Dynamic` | idem | `canonical.Dynamic(mark=…)` | ✅ Préservé |
| **Articulation principale** | `articulation: Articulation` | idem | `Technique(name=…)` si non-NORMAL | ✅ Transformé |
| **Bend** | `bend_value`, `bend_type` | idem | `Technique("bend", value=str(bend_value))` ; `bend_type` perdu | ⚠️ Partiel |
| **Slide** | `slide_type: str\|None` | idem | absent du canonical | ❌ Perdu (présence de "slide" en technique, mais pas le type) |
| **Vibrato large** | `vibrato_wide: bool` | idem | absent | ❌ Perdu |
| **Harmonique** | `harmonic_type`, `harmonic_fret` | idem | `Technique("harmonic")` ; `harmonic_fret` perdu | ⚠️ Partiel |
| **Modificateurs scène** | `muted`, `palm_muted`, `tapping`, `let_ring`, `strum_direction` | idem | `Technique` pour `palm_mute`, `let_ring`, `strum_up/down`, `tapping` | ⚠️ Partiel |
| **Modificateurs perdus** | `accent`, `accent_strong`, `ghost`, `staccato` (bool), `slap`, `pop`, `rasgueado`, `golpe`, `tremolo_picking` | idem | **absent** | ❌ Perdus silencieusement |
| **Tuplet** | `tuplet_actual`, `tuplet_normal` | idem | `LayoutHint("tuplet_actual")`, `LayoutHint("tuplet_normal")` | ⚠️ Sérialisé en string dans LayoutHint au lieu du `Tuplet` structuré |
| **Tie** | `is_tie_dest: bool` | idem | `LayoutHint("is_tie_dest", "true")` | ⚠️ Sérialisé en string au lieu du `Tie` structuré |
| **Spelling** | `note_step`, `note_accidental`, `note_octave` | idem | `LayoutHint("pitch_step/accidental/octave")` | ✅ Préservé via hints |
| **Métadonnées score** | absent | `track_name`, `chord_markers`, `section_markers`, `key_signature_fifths`, `has_anacrusis`, `chord_diagrams` | `Track.name`, `LayoutHint("chord_name")`, `Measure.section_name`, `KeySignature`, anacrusis offset | ✅ Préservé (niveau score) |

---

## 2. Analyse des pertes d'information

### 2.1 Correction d'un mythe : `voice_hint` est préservé

Contrairement à l'énoncé initial, `voice_hint` **n'est pas perdu**. Le mapper lit `note.voice_hint` et l'assigne à `Event.voice` (ligne 196 de `mappers.py`) :

```python
voice = note.voice_hint if note.voice_hint is not None else 0
```

La vraie perte est ailleurs.

### 2.2 Pertes avérées

**Tempo per-note → TempoMark unique**
Le mapper lit `completed_score.notes[0].tempo` et crée un seul `TempoMark` à `onset=0.0`. Les changements de tempo dans la pièce (champ `tempo` de chaque `NoteEvent`) sont silencieusement écrasés. Impact : rendu SVG à tempo constant erroné pour les morceaux avec accel/rit.

**Per-measure TimeSignature → TimeSignature unique**
`completed_to_canonical_score` calcule une `TimeSignature` à partir des scalaires `beats_per_measure` / `time_denominator` et l'applique à **toutes** les mesures (ligne 80). Les changements de métrique en cours de morceau sont impossibles à représenter. C'est la cible explicite de P0-C.

**`measure_index` : consommé mais jamais émis**
`_measure_index_for_note` lit `note.measure_index` pour décider dans quelle mesure placer la note — mais la mesure canonique n'expose pas son numéro source. Si `measure_index` est absent (None), le calcul tombe en fallback `onset // beats_per_measure`, qui peut diverger pour les morceaux avec anacrusis ou changements de métrique.

**Champs structurés `Tuplet` et `Tie` non utilisés**
Le modèle canonical possède `NoteEvent.tuplet: Tuplet | None` et `NoteEvent.tie: Tie | None`, mais le mapper les ignore et écrit des `LayoutHint` en chaîne à la place. Le backend SVG doit donc désérialiser des strings pour obtenir ces informations.

**Modificateurs de jeu perdus**
Les booléens suivants n'ont aucun équivalent dans le canonical ni dans les `Technique` émis : `accent`, `accent_strong`, `ghost`, `staccato` (bool distinct de l'articulation), `slap`, `pop`, `rasgueado`, `golpe`, `tremolo_picking`, `vibrato_wide`.

**Doigté (output Pipeline A)**
`TabInfo.left_hand_finger` est systématiquement `None`. Le résultat du pipeline de doigté (Pipeline A) n'est jamais injecté dans le pipeline notation (Pipeline B).

---

## 3. Trois options de bridge

### Option A — Enrichir le mapper (recommandée pour P0)

**Principe :** `CompletedScore` reçoit de nouveaux champs d'enveloppe ; `_map_note` et `completed_to_canonical_score` les consomment. Le legacy `NoteEvent` reste la source de vérité inchangée.

```python
@dataclass
class CompletedScore:
    # champs existants …
    measure_time_signatures: dict[int, tuple[int, int]] = field(default_factory=dict)
    # clé = numéro de mesure (1-based), valeur = (numérateur, dénominateur)
    tempo_changes: list[tuple[float, float]] = field(default_factory=list)
    # liste de (onset_en_beats, bpm)
```

Impact mapper :
```python
# completed_to_canonical_score — remplace la TimeSignature unique
def _time_sig_for_measure(completed: CompletedScore, measure_number: int) -> TimeSignature:
    if measure_number in completed.measure_time_signatures:
        num, den = completed.measure_time_signatures[measure_number]
        return TimeSignature(numerator=num, denominator=den)
    return TimeSignature(
        numerator=int(round(completed.beats_per_measure)),
        denominator=completed.time_denominator,
    )
```

**Pro :** non-invasif, risque minimal, chaque parser enrichit son output de façon optionnelle.
**Con :** `CompletedScore` grossit à chaque sprint ; la duplication legacy/canonical reste entière.

---

### Option B — Unification partielle par héritage

**Principe :** introduire un `CoreNoteEvent` partagé avec `pitch`, `onset`, `duration`. `fretwise.models.NoteEvent` et `canonical.NoteEvent` en héritent.

```python
# fretwise/core/shared/base_event.py
@dataclass
class CoreNoteEvent:
    pitch: int
    onset: float
    duration: float
```

**Con critique :** `canonical.NoteEvent` hérite déjà de `canonical.Event` (qui porte `voice`, `event_id`, `onset`, `duration`). Un double héritage ou une refonte de la hiérarchie est nécessaire. De plus, `fretwise.models.NoteEvent` est consommé par les 4 parsers **et** par le scoring/optimizer (M4, M5) — tout changement de sa signature impose une migration simultanée des 6 modules.

**Verdict :** rapport risque/bénéfice défavorable à court terme.

---

### Option C — Suppression du pipeline legacy

**Principe :** les parsers produisent directement `canonical.NoteEvent`. Plus de mapper.

**Con critique :** `canonical.NoteEvent` ne porte pas `string_hint`, `fret_hint`, `voice_hint`, ni les champs bioméchaniques (bend_type, slide_type, muted…). Il faudrait soit étendre le canonical (ce qui contredit son rôle de modèle backend-agnostique), soit maintenir un modèle d'exécution adjacent. C'est une réécriture complète des 4 parsers + refonte du générateur d'états.

**Verdict :** objectif correct à Phase 3, hors de portée pour P0.

---

## 4. Recommandation et plan de migration phasé

**Option A est recommandée pour les 3 prochains sprints.** Elle offre la meilleure balance risque/bénéfice : les points d'extension du mapper sont clairs, les parsers peuvent enrichir `CompletedScore` de façon optionnelle, et aucune interface publique de M4/M5 n'est touchée.

### Phase 1 — Sprint actuel (P0-B + P0-C)

| Ticket | Action | Fichier |
|---|---|---|
| P0-B | Transmettre `tuplet_actual/normal` dans `Tuplet` structuré (au lieu de `LayoutHint`) | `mappers.py:_map_note` |
| P0-B | Transmettre `is_tie_dest` dans `Tie` structuré | `mappers.py:_map_note` |
| P0-C | Ajouter `measure_time_signatures: dict[int, tuple[int,int]]` à `CompletedScore` | `core/ingest/models.py` |
| P0-C | Adapter `completed_to_canonical_score` pour appliquer une `TimeSignature` par mesure | `mappers.py` |
| P0-C | Peupler `measure_time_signatures` dans `guitarpro_adapter` et `gpif_adapter` | parsers |

### Phase 2 — Sprint suivant (enrichissement mapper)

- Ajouter `tempo_changes: list[tuple[float, float]]` à `CompletedScore`
- Émettre un `TempoMark` par changement de tempo dans la canonical `Score`
- Mapper `slide_type` → `Technique(name="slide", value=slide_type)`
- Mapper `harmonic_fret` → `Technique(name="harmonic", value=str(harmonic_fret))`
- Documenter les champs définitivement abandonnés (`rasgueado`, `golpe`, `pop`, `slap`) en commentaire dans `_map_note`

### Phase 3 — Sprint 3 (unification ou nettoyage)

- Évaluer si Option B est viable après stabilisation du canonical
- Si oui : introduire `CoreNoteEvent` et migrer le parser GP uniquement (test de faisabilité)
- Si non : supprimer les champs legacy orphelins et consolider la documentation du mapper comme contrat stable

---

## 5. Contrat d'interface du mapper après fixes P0

### Préconditions (`CompletedScore` → mapper)

Les champs suivants doivent être non-None / non-vides pour un rendu correct :

```python
@dataclass
class CompletedScore:
    source_path: str                          # non-vide, requis pour le titre
    notes: list[NoteEvent]                    # non-vide (au moins 1 note)
    beats_per_measure: float                  # > 0 ; défaut 4.0
    time_denominator: int                     # > 0 ; défaut 4
    # Après P0-C — optionnel, fallback sur beats_per_measure si absent
    measure_time_signatures: dict[int, tuple[int, int]]  # clé 1-based

    # Champs score-level (peuvent être vides mais pas None)
    section_markers: dict[int, str]           # clé = measure_number 1-based
    chord_markers: dict[str, str]             # clé = str(onset)
    key_signature_fifths: int                 # 0 = C majeur
```

Champs de chaque `NoteEvent` consommés par le mapper :

| Champ | Criticité | Fallback si absent |
|---|---|---|
| `pitch` | **Requis** | — |
| `onset`, `duration` | **Requis** | — |
| `measure_index` | Fortement recommandé | `onset // beats_per_measure` (peut dériver en cas de changement de métrique) |
| `voice_hint` | Recommandé | `0` (voix unique) |
| `string_hint`, `fret_hint` | Optionnel | `TabInfo = None` ; `pitch_notated = pitch` (pas d'octave guitare) |
| `tempo` | Optionnel (Phase 2+) | Seul `notes[0].tempo` est utilisé en P0 |
| `tuplet_actual`, `tuplet_normal` | Optionnel | `Tuplet = None` (après P0-B) |
| `is_tie_dest` | Optionnel | `Tie = None` (après P0-B) |
| `note_step`, `note_accidental`, `note_octave` | Optionnel | LayoutHints absents ; spelling déduit par le renderer |

### Garanties sur `canonical.Score` en sortie

Après `completed_to_canonical_score(completed)` avec un `CompletedScore` valide :

```python
score: Score
assert score.score_id == "score-1"
assert len(score.tracks) == 1
assert len(score.tempo_marks) >= 1             # au moins onset=0
assert score.key_signature is not None

track = score.tracks[0]
assert len(track.staff_groups) == 1
staff = track.staff_groups[0].staves[0]
assert len(staff.measures) >= 1

# Chaque mesure contient au moins une voix
for measure in staff.measures:
    assert len(measure.voices) >= 1
    # Chaque voix est complète (notes + rests couvrent la mesure)
    for voice in measure.voices:
        assert len(voice.events) >= 1

# Après P0-C : chaque mesure a sa propre TimeSignature
# (peut différer de la précédente en cas de changement de métrique)
```

### Conditions de fallback

| Situation | Comportement du mapper |
|---|---|
| `beats_per_measure <= 0` | Remplacé par 4 (`_safe_beats_per_measure`) |
| `completed_score.notes` vide | `Score` avec 0 mesures, `tempo_marks=[TempoMark(0, 120.0)]` |
| `note.measure_index is None` | Calcul par `onset // beats_per_measure` |
| `note.voice_hint is None` | `voice = 0` |
| `string_hint` et `fret_hint` tous deux None | `tab_info = None` ; `pitch_notated = pitch` |
| Mesure absente de `measure_time_signatures` (P0-C) | Fallback sur la `TimeSignature` globale |
