# Spécifications de rendu PDF v2 — FretWise
> Analyse des bugs + standards + règles + algorithmes + liste de tâches
> Basé sur les captures d'écran du fichier Stairway to Heaven (14/03/2026)

---

## 1. Diagnostic des bugs identifiés dans les captures

### B1 — Silences masqués par les barres de liaison (CRITIQUE)
**Screenshots** : 095334, 095424
- Le soupir (`ζ`) est dessiné à `y_top = sys_y + STEM_H = sys_y + 16pt`, c'est-à-dire
  dans la zone des hampes, **au-dessus** des cordes.
- La barre de croche passe **par-dessus** le symbole du silence qui devient illisible.
- **Cause code** : `_draw_rest(c, rx, stem_top, ...)` — ancrage à `stem_top`.

### B2 — Les silences n'interrompent pas les barres de liaison (CRITIQUE)
**Screenshots** : 095334, 095424
- `_get_beamed_onsets()` ignore les silences : il groupe **tous** les notes
  sub-quarter consécutives en un seul groupe.
- Résultat : une barre horizontale enjambe le silence.
- **Règle à implémenter** : toute barre de liaison doit s'arrêter avant un silence
  et reprendre après. Une nouvelle barre peut commencer si ≥ 2 notes suivent.

### B3 — Regroupement des barres de liaison non conforme (IMPORTANT)
**Screenshot** : 095140 (Fmaj7, 8 croches en une seule barre)
- `_get_beamed_onsets()` regroupe **toutes** les notes sub-quarter de la mesure
  en un seul groupe, quel que soit le temps.
- En 4/4, la règle standard : regrouper par **temps** (max 2 croches par groupe
  dans un temps = 1 beat ; max 4 doubles-croches par groupe).
- **Règle** : une barre ne franchit jamais la frontière de temps (beat).
  En 4/4 : 4 groupes max de 2 croches, ou 4 groupes de 4 doubles-croches.

### B4 — Largeur de mesure fixe (IMPORTANT)
**Screenshots** : 095140, 095247, 095334
- `measure_w = (strings_x1 - _STRINGS_X0) / mps` — toutes les mesures ont
  la même largeur, peu importe leur densité rythmique.
- Une mesure avec une ronde est aussi large qu'une mesure avec 16 doubles-croches.
- Résultat : notes entassées dans les mesures denses, espace gaspillé dans les
  mesures creuses, et `_MIN_COL_STEP = 17pt` force les notes à déborder
  hors de leur proportion temporelle.

### B5 — Espacement proportionnel désactivé de facto (IMPORTANT)
**Screenshot** : 095140
- `_compute_onset_x()` fait un placement proportionnel correct, PUIS applique
  un forward-pass avec `_MIN_COL_STEP = 17pt` qui pousse toutes les notes
  vers la droite quand la mesure est dense.
- Dans une mesure de 80pt avec 8 croches : 8 × 17pt = 136pt → débordement /
  écrasement de la proportionnalité.
- **La largeur variable des mesures (B4) résout ce problème** : la mesure sera
  assez large pour que 17pt suffise proportionnellement.

### B6 — Collision numéro de mesure / nom d'accord (MOYEN)
**Screenshot** : 095247 (mesures 41, 42)
- Numéro de mesure : `sys_y + _CHORD_Y + 5` = `sys_y + 35pt`
- Nom d'accord : `sys_y + _CHORD_Y` = `sys_y + 30pt`
- Seuls 5pt les séparent verticalement. Quand le nom d'accord est long ou
  quand la section débute, les textes se chevauchent.

### B7 — Collision annotations de doigt / lignes de cordes (MOYEN)
**Screenshots** : 094931, 095140
- Annotations `i, m, r, p` en rouge, positionnées SW de l'ovale à `string_y - 5.5pt`.
- Dans les accords denses, les annotations d'une corde tombent sur l'ovale de
  la corde suivante ou sur la ligne de corde.
- Cas particulier : première note d'une mesure — l'annotation "r" sur la corde 1
  est très proche de la double barre de début.

### B8 — Barre secondaire (16e) partielle non gérée (MOYEN)
**Screenshot** : 095401
- `_draw_beams()` : la barre secondaire s'applique seulement si **toutes** les
  notes du groupe sont des doubles-croches (`if all(d < 0.5 for _, d in group)`).
- Un groupe mixte (croche + doubles-croches) devrait avoir une barre secondaire
  **partielle** au-dessus des seules doubles-croches (convention standard).

### B9 — Symbole de silence mal positionné dans la légende (MINEUR)
**Screenshot** : 094814
- Dans la légende, le label "Silences correspondants :" chevauche l'ovale
  de la Ronde dans la rangée du dessus.

### B10 — Barre de liaison flotte trop haut (ESTHETIQUE)
**Screenshots** : 094931, 095401
- `_STEM_H = 16pt` → la barre de liaison est à 16pt au-dessus de la corde 1.
- Le tout (hampe + barre) occupe 18pt de hauteur alors que la zone de texte
  des accords est à 30pt — la zone de liaisons est surdimensionnée.

---

## 2. Standards de tailles et d'espacement

### 2.1 Zones verticales d'un système (de haut en bas)

```
  sys_y + SECTION_Y    (+52pt)  Zone section marker (Intro, Verse…)
  sys_y + TEMPO_Y      (+38pt)  Zone tempo/signature (gris)
  sys_y + MNUM_Y       (+31pt)  Zone numéros de mesure (gris petit)
  sys_y + CHORD_Y      (+24pt)  Zone noms d'accords (noir gras)
  sys_y + BEAM_TOP_Y   (+16pt)  Sommet des barres de liaison (FIXE)
  sys_y + STEM_GAP     (+2.5pt) Base des hampes
  sys_y               (0pt)    Corde 1 (e)
  sys_y - 10pt                  Corde 2 (B)
  sys_y - 20pt                  Corde 3 (G)
  sys_y - 25pt                  Centre du staff (REST_CENTER_Y = -25pt)
  sys_y - 30pt                  Corde 4 (D)
  sys_y - 40pt                  Corde 5 (A)
  sys_y - 50pt                  Corde 6 (E)
  sys_y - 56pt (-BELOW)         Bas du système

CONSTANTES CIBLES:
  SECTION_Y   = 52.0   # ex ABOVE_STRINGS - 4
  TEMPO_Y     = 38.0   # separé de MNUM par 7pt
  MNUM_Y      = 31.0   # juste au-dessus de CHORD
  CHORD_Y     = 22.0   # réduit de 30 à 22 pour dégager espace
  BEAM_TOP_Y  = 14.0   # sommet barres (réduit de 16 à 14)
  STEM_GAP    =  2.0   # (inchangé)
  STRING_SPACING = 10.0  # (inchangé)
  BELOW_STRINGS  = 8.0   # légèrement augmenté pour les silences bas
  SYSTEM_H = SECTION_Y + 7 + STRING_SPACING*5 + BELOW_STRINGS  # ~117pt
```

### 2.2 Silences — position dans le staff

Les silences doivent être rendus **au centre vertical du staff**, à l'intérieur
des cordes, dans un disque blanc cerclé de noir (sauf pause/demi-pause).

```
  REST_CENTER_Y  = sys_y - 25pt     # milieu entre corde 1 et corde 6
  REST_DISC_R    = 6.5pt            # rayon du disque blanc
  REST_DISC_LW   = 0.8pt            # épaisseur du cercle noir
  REST_SYMBOL_H  = 10pt max         # hauteur max du symbole à l'intérieur

  Placement horizontal : IDENTIQUE à une note de même durée
  (même algorithme onset_x, même proportion dans la mesure)
```

### 2.3 Largeur de mesure variable

Chaque mesure a une largeur proportionnelle à sa **densité rythmique** :

```
  UNIT_W = 12.0pt     # largeur par "unité" (1 beat = 1 croche + 1 espace)
  MIN_MEASURE_W = 40pt     # minimum absolu (ronde seule)
  MAX_MEASURE_W = 200pt    # maximum (mesure très dense)
  COL_MIN_STEP  = 14.0pt   # minimum entre 2 colonnes (réduit de 17 à 14)
  LEFT_PAD      = 8.0pt    # idem
  RIGHT_PAD     = 5.0pt    # espace avant la barre de mesure droite

  measure_units(measure) = sum of (1/duration_i) for each unique onset i
    # Ex: 8 croches → sum(1/0.5 × 8) = 16 → mesure "large"
    #     1 ronde  → sum(1/4.0 × 1)  = 0.25 → mesure "étroite"

  measure_w_raw(m) = LEFT_PAD + measure_units(m) × UNIT_W + RIGHT_PAD
  measure_w(m)     = clamp(measure_w_raw(m), MIN_MEASURE_W, MAX_MEASURE_W)

  # Normalisation : les largeurs sont ensuite mises à l'échelle pour que
  # la somme des mesures d'un système remplisse exactement la largeur disponible.
  # scale = available_w / sum(measure_w_raw for m in system)
  # final_w(m) = measure_w_raw(m) × scale  (clampé min/max)
```

### 2.4 Regroupement des barres de liaison (beaming)

```
  Règles standard (4/4) :
    - Beat unit = 1.0 beat (croche) ou 0.5 beat (double-croche)
    - 8th notes  : groupes de 2 (un groupe = un temps)
    - 16th notes : groupes de 4 (un groupe = un temps) OU de 2 (demi-temps)
    - 32nd notes : groupes de 4 ou 8 selon le flux

  Interruptions obligatoires :
    1. Frontière de temps (beat boundary)
    2. Présence d'un silence entre deux notes (même 1/32e de silence)
    3. Note de valeur >= croche (noire, blanche, ronde)
    4. Changement de voix ou de mesure

  Barre secondaire partielle :
    Quand un groupe contient des croches ET des doubles-croches :
    - Barre primaire : de la 1ère à la dernière note du groupe
    - Barre secondaire : uniquement au-dessus des runs de doubles-croches
      (de la 1ère double-croche jusqu'à la dernière consécutive)
```

### 2.5 Dimensions des objets graphiques

```
  Ovale fret :
    oval_h    = 7pt  (±3.5 du centre)
    oval_w1   = 10pt  (1 chiffre)
    oval_w2   = 13.5pt (2 chiffres, fret >= 10)
    fret_font = Helvetica-Bold 6pt

  Annotation doigt LH (rouge) :
    font  = Helvetica-Bold 4.5pt  (réduit de 5 à 4.5)
    pos_x = oval_left_edge - 1pt  (drawRightString)
    pos_y = string_y - 6.5pt  (inchangé, sous l'ovale)
    REGLE : si string_num < 6, vérifier que pos_y - 2pt > next_string_y + 3.5pt
            sinon décaler vers la gauche (drawRightString(oval_left - 4pt, ...))

  Disque de silence :
    disc_r  = 6.5pt   (rayon cercle blanc)
    disc_lw = 0.8pt   (trait noir)
    symbol_scale = 0.9  (symbole dessiné à 90% de la taille max dans le disque)

  Hampe (stem) :
    stem_w     = 0.8pt
    stem_bot   = sys_y + 2.0pt   (base à 2pt au-dessus corde 1)
    stem_top   = sys_y + 14.0pt  (réduit de 16 à 14)

  Barre de liaison (beam) :
    beam_h   = 2.5pt  (inchangé)
    beam_gap = 3.0pt  (entre barre primaire et secondaire)
    beam_y   = stem_top  (= sys_y + 14pt)

  Barre de mesure :
    simple_lw = 0.5pt
    double_lw = (0.5pt + 1.5pt)  séparées de 2.5pt
    final_lw  = (0.5pt + 2.0pt)  séparées de 3.5pt
    hauteur   = sys_y + 1pt  à  sys_y - STRING_SPACING*5 - 1pt
```

---

## 3. Règles de placement

### R1 — Placement horizontal proportionnel (loi fondamentale)

```
  x(onset) = measure_x0 + LEFT_PAD
            + (onset - measure_onset) / beats_per_measure
            × (measure_w - LEFT_PAD - RIGHT_PAD)

  La contrainte COL_MIN_STEP est satisfaite par la largeur variable
  de la mesure (voir algorithme A2), PAS en poussant les notes.
  Si COL_MIN_STEP ne peut pas être respecté (mesure extrêmement dense),
  la mesure est marquée comme "surchargée" et ses notes peuvent être
  légèrement décalées, JAMAIS empilées.
```

### R2 — Les silences occupent le même espace que les notes équivalentes

```
  Un soupir (1 beat) = position proportionnelle exacte dans la mesure.
  Une demi-pause (2 beats) = centrée sur les 2 beats qu'elle occupe.
  Les silences participent au calcul de measure_units() au même titre
  que les notes (contribution rythmique identique).
```

### R3 — Placement vertical des silences

```
  Tous les silences sont dessinés à REST_CENTER_Y = sys_y - 25pt
  (centre du staff, entre cordes 3 et 4).
  Exception : pause (ronde entière) et demi-pause — symboles rectangulaires
  positionnés à REST_CENTER_Y ± offset selon convention standard.
  Chaque silence est entouré d'un disque blanc (rayon 6.5pt) cerclé de noir
  pour garantir la lisibilité sur les lignes de cordes.
```

### R4 — Barres de liaison n'enjambent jamais un silence ou une frontière de temps

```
  Algorithme de groupement (voir A3) :
  - Construire la liste fusionnée [notes + silences] triée par onset
  - Tout élément "silence" interrompt le groupe en cours
  - Tout élément dont l'onset dépasse la prochaine frontière de temps
    interrompt le groupe en cours
```

### R5 — Numéro de mesure et nom d'accord dans des zones séparées

```
  Zone numéro : MNUM_Y = +31pt  (gris, Helvetica 5.5pt)
  Zone accord  : CHORD_Y = +22pt (noir gras, Helvetica-Bold 7pt)
  Zone section : SECTION_Y = +52pt (bleu, Helvetica-Bold 8pt)
  Jamais de chevauchement : chaque zone a sa propre ligne.
  Si un nom d'accord est trop long (> measure_w - 4pt), le tronquer avec "…".
```

### R6 — Annotations de doigt sans collision

```
  Position nominale : SW de l'ovale (droite du char aligne avec gauche ovale).
  Test anti-collision :
    bottom_of_annotation = string_y - 7.5pt
    top_of_next_string   = (string_y - STRING_SPACING) + OVAL_H/2
    if bottom_of_annotation < top_of_next_string + 2pt :
        décaler vers la gauche : x -= 3pt (annotate SW with extra offset)
  Pour les accords multi-cordes denses : priorité aux annotations des cordes
  les plus graves (doigts r, p), les cordes aiguës (i) peuvent être omises
  si espace insuffisant.
```

### R7 — Largeur de système = somme des largeurs de mesures normalisée

```
  available_w = PAGE_W - 2*MARGIN - TAB_LABEL_W
  Pour chaque lot de mps mesures formant un système :
    total_raw = sum(measure_w_raw(m) for m in system)
    scale = available_w / total_raw
    final_w(m) = clamp(measure_w_raw(m) × scale, MIN_MEASURE_W, MAX_MEASURE_W)
  Le nombre de mesures par système mps est lui-même calculé pour que
  total_raw soit proche de available_w (voir algorithme A1).
```

---

## 4. Algorithmes

### A1 — Calcul de mps (mesures par système)

```python
def compute_mps(measures: list[list[FingeringResult]],
                beats_per_measure: float,
                available_w: float) -> list[int]:
    """
    Retourne la liste du nombre de mesures par système.
    Stratégie glouton : empiler les mesures dans un système jusqu'à ce que
    total_raw > available_w, puis commencer un nouveau système.
    """
    systems = []
    current = []
    current_w = 0.0
    for m in measures:
        w = measure_w_raw(m, beats_per_measure)
        if current and current_w + w > available_w * 1.05:
            systems.append(len(current))
            current = [m]
            current_w = w
        else:
            current.append(m)
            current_w += w
    if current:
        systems.append(len(current))
    return systems

def measure_w_raw(measure: list[FingeringResult],
                  beats_per_measure: float) -> float:
    """Largeur brute d'une mesure basée sur sa densité rythmique."""
    # Collecter les durées minimales par onset (= durée du rythme notée)
    onset_durs: dict[float, float] = {}
    for r in measure:
        onset = round(r.note_event.onset, 6)
        onset_durs[onset] = min(onset_durs.get(onset, 999), r.note_event.duration)
    # Ajouter les silences
    all_events = list(onset_durs.items())  # (onset, duration)
    all_events.extend(compute_rests_as_events(measure, beats_per_measure))
    # units = somme des 1/durée pour chaque événement
    units = sum(1.0 / max(dur, 0.125) for _, dur in all_events)
    return LEFT_PAD + units * UNIT_W + RIGHT_PAD
```

### A2 — Normalisation des largeurs dans un système

```python
def normalize_measure_widths(raw_widths: list[float],
                              available_w: float) -> list[float]:
    """
    Mise à l'échelle proportionnelle, respectant MIN/MAX par mesure.
    Algorithme itératif : scale → clamp → redistribuer le reste.
    """
    widths = list(raw_widths)
    n = len(widths)
    clamped = [False] * n
    for _ in range(n):  # max n itérations
        free_slots = [i for i in range(n) if not clamped[i]]
        if not free_slots:
            break
        total_free = sum(widths[i] for i in free_slots)
        target = available_w - sum(widths[i] for i in range(n) if clamped[i])
        scale = target / total_free if total_free > 0 else 1.0
        changed = False
        for i in free_slots:
            scaled = widths[i] * scale
            clamped_val = max(MIN_MEASURE_W, min(MAX_MEASURE_W, scaled))
            if abs(clamped_val - scaled) > 0.5:
                widths[i] = clamped_val
                clamped[i] = True
                changed = True
            else:
                widths[i] = scaled
        if not changed:
            break
    return widths
```

### A3 — Regroupement des liaisons (beat-aware, rest-aware)

```python
def compute_beam_groups(
    stem_info: list[tuple[float, float, float]],   # (x, onset, duration)
    rests: list[tuple[float, float]],              # (onset, duration)
    beats_per_measure: float,
    measure_onset: float,
) -> list[list[float]]:
    """
    Retourne une liste de groupes, chaque groupe étant une liste d'onsets.
    Règles :
    1. Ne grouper que les notes de durée < 1.0 beat (sub-quarter).
    2. Arrêter le groupe à chaque frontière de temps (beat boundary).
    3. Arrêter le groupe si un silence tombe entre deux onsets consécutifs.
    4. Un groupe doit avoir >= 2 éléments pour mériter une barre.
    """
    rest_onsets = {round(o, 6) for o, _ in rests}

    groups: list[list[float]] = []
    current_group: list[float] = []
    prev_beat_end: float = measure_onset  # prochaine frontière de temps

    # Construire les frontières de temps pour cette mesure
    beat_boundaries = [
        measure_onset + i
        for i in range(1, int(beats_per_measure) + 1)
    ]

    for idx, (x, onset, dur) in enumerate(stem_info):
        if dur >= 1.0:
            # Note non beamable : fermer le groupe courant
            if len(current_group) >= 2:
                groups.append(current_group)
            current_group = []
            continue

        # Vérifier si un silence précède cette note (depuis la fin de la note précédente)
        if idx > 0:
            prev_onset = stem_info[idx - 1][1]
            prev_dur = stem_info[idx - 1][2]
            prev_end = prev_onset + prev_dur
            gap = onset - prev_end
            has_rest_between = gap >= 0.115  # >= 1/32 beat
        else:
            has_rest_between = False

        # Vérifier si on franchit une frontière de temps
        crosses_beat = any(
            prev_onset_in_group < bb <= onset
            for bb in beat_boundaries
            if current_group
        )
        # Pour la vérification de crossing, utiliser l'onset précédent dans le groupe
        if current_group:
            last_in_group = current_group[-1]
            crosses_beat = any(last_in_group < bb <= onset for bb in beat_boundaries)
        else:
            crosses_beat = False

        if has_rest_between or crosses_beat:
            if len(current_group) >= 2:
                groups.append(current_group)
            current_group = [onset]
        else:
            current_group.append(onset)

    if len(current_group) >= 2:
        groups.append(current_group)

    return groups


def compute_partial_secondary_beams(
    groups: list[list[float]],
    stem_info_by_onset: dict[float, tuple[float, float, float]],
) -> list[tuple[float, float]]:
    """
    Pour chaque groupe, retourne les segments de barre secondaire (16e).
    Chaque segment = (x_start, x_end) pour la barre secondaire partielle.
    """
    secondary_segs: list[tuple[float, float]] = []
    for group in groups:
        # Trouver les runs consécutifs de doubles-croches dans le groupe
        run_start: float | None = None
        run_last_x: float | None = None
        for onset in group:
            x, _, dur = stem_info_by_onset[onset]
            if dur < 0.5:  # double-croche ou plus court
                if run_start is None:
                    run_start = x
                run_last_x = x
            else:
                if run_start is not None and run_last_x is not None and run_last_x > run_start:
                    secondary_segs.append((run_start, run_last_x))
                run_start = None
                run_last_x = None
        if run_start is not None and run_last_x is not None and run_last_x > run_start:
            secondary_segs.append((run_start, run_last_x))
    return secondary_segs
```

### A4 — Rendu des silences dans le staff

```python
def draw_rest_in_staff(
    c: Canvas,
    rx: float,           # position x (proportionnelle dans la mesure)
    rest_center_y: float,  # sys_y - 25pt  (centre vertical du staff)
    duration: float,
) -> None:
    """
    Dessine un symbole de silence centré en rest_center_y, dans un disque
    blanc cerclé de noir. Le disque efface les lignes de cordes.
    """
    # 1. Disque blanc (efface les cordes)
    c.setFillColor(white)
    c.setStrokeColor(black)
    c.setLineWidth(REST_DISC_LW)  # 0.8pt
    c.circle(rx, rest_center_y, REST_DISC_R, fill=1, stroke=1)

    # 2. Symbole à l'intérieur
    c.setFillColor(black)
    c.setStrokeColor(black)
    _draw_rest_symbol(c, rx, rest_center_y, duration, scale=0.75)

    # Note : pas de disque pour pause (ronde) et demi-pause — ce sont des
    # rectangles horizontaux dont la lisibilité n'est pas gênée par les cordes.
    # Pour pause/demi-pause : dessiner directement sans disque.
```

### A5 — Vérification anti-collision des annotations de doigt

```python
def check_finger_annotation_collisions(
    results_at_onset: list[FingeringResult],
    onset_x: float,
    sys_y: float,
) -> dict[int, tuple[float, float]]:
    """
    Retourne pour chaque string_num la position (x, y) ajustée de l'annotation.
    Résout les conflits en décalant latéralement les annotations qui empiètent
    sur les ovales ou lignes adjacents.
    """
    positions: dict[int, tuple[float, float]] = {}
    for r in sorted(results_at_onset, key=lambda x: x.state.string_num):
        sn = r.state.string_num
        string_y = sys_y - (sn - 1) * STRING_SPACING
        oval_w = OVAL_W2 if r.state.fret >= 10 else OVAL_W1
        nominal_x = onset_x - oval_w / 2 - 1.0   # SW position
        nominal_y = string_y + LH_FINGER_Y        # string_y - 5.5

        # Test : le bas de l'annotation (nominal_y - 2pt) doit rester
        # au-dessus du haut de l'ovale de la corde suivante (string_y - STRING_SPACING + 3.5pt)
        if sn < NUM_STRINGS:
            next_string_y = sys_y - sn * STRING_SPACING
            clearance = nominal_y - 2.0 - (next_string_y + OVAL_H / 2)
            if clearance < 2.0:
                nominal_x -= 3.5   # décaler vers la gauche

        positions[sn] = (nominal_x, nominal_y)
    return positions
```

---

## 5. Liste de tâches ordonnée

> Priorité **P0** = bloquant / illisible | **P1** = important | **P2** = amélioration

---

### P0 — Bugs critiques de lisibilité

#### RENDER-01 — Déplacer les silences dans le staff + disque blanc
**Fichier** : `src/fretwise/export/pdf_tab.py`
**Fonctions** : `_draw_rest()`, `_draw_measure()`
- Changer le point d'ancrage de `stem_top` à `sys_y - REST_CENTER_OFFSET`
  (centre vertical du staff, entre cordes 3 et 4)
- Entourer chaque silence d'un disque blanc cerclé de noir (rayon 6.5pt)
- Sauf pause/demi-pause : rectangles dessinés directement, pas de disque
- **Tests** : vérifier que toutes les durées (0.125 à 4.0) s'affichent
  proprement sur les 6 lignes de cordes, qu'aucune ligne ne traverse le symbole

#### RENDER-02 — Silences interrompent les barres de liaison
**Fichier** : `src/fretwise/export/pdf_tab.py`
**Fonctions** : `_get_beamed_onsets()` → remplacer par `compute_beam_groups()`
- Intégrer les rests dans l'algorithme de groupement (voir A3)
- Un silence de n'importe quelle durée coupe le groupe en cours
- **Tests** : mesure avec [croche, silence, croche] → 2 hampes isolées sans barre

#### RENDER-03 — Regroupement des liaisons par temps (beat-aware)
**Fichier** : `src/fretwise/export/pdf_tab.py`
**Fonctions** : `_get_beamed_onsets()` → remplacer par `compute_beam_groups()`
- Passer les frontières de temps à l'algorithme de groupement (voir A3)
- En 4/4 : max 2 croches par groupe ; max 4 doubles-croches par groupe
- **Tests** : 8 croches → 4 groupes de 2 ; 16 doubles-croches → 4 groupes de 4

---

### P1 — Layout et proportionnalité

#### RENDER-04 — Largeur de mesure variable
**Fichier** : `src/fretwise/export/pdf_tab.py`
**Fonctions** : nouvelles `measure_w_raw()`, `normalize_measure_widths()`,
              modifier `_draw_system()` et `_compute_onset_x()`
- Implémenter A1 : calcul de `measure_w_raw()` basé sur `measure_units`
- Implémenter A2 : normalisation avec clamp MIN/MAX
- Modifier `_draw_system()` : calculer `x0` de chaque mesure depuis les
  largeurs variables (pas plus `slot * measure_w` uniforme)
- Modifier `_compute_onset_x()` : supprimer le forward-pass qui pousse
  les notes (le MIN_COL_STEP est maintenant garanti par la largeur)
  ou réduire `COL_MIN_STEP` à 14pt
- **Tests** : ronde seule dans une mesure = mesure plus étroite que 8 croches

#### RENDER-05 — Calcul du nombre de mesures par système (mps variable)
**Fichier** : `src/fretwise/export/pdf_tab.py`
**Fonctions** : `_calc_mps()` → remplacer par `compute_mps()` (algorithme A1)
- mps n'est plus un entier fixe mais une liste d'entiers, un par système
- Le système s'adapte à la largeur totale des mesures qu'il contient
- Modifier la boucle principale de `render_pdf_tab()`
- **Tests** : système avec une mesure dense + une mesure creuse →
  les largeurs reflètent le contenu

#### RENDER-06 — Barres secondaires partielles (16e dans groupe mixte)
**Fichier** : `src/fretwise/export/pdf_tab.py`
**Fonctions** : `_draw_beams()` → utiliser `compute_partial_secondary_beams()`
- Remplacer `if all(d < 0.5 ...)` par le rendu de segments partiels (voir A3)
- **Tests** : groupe [croche, double-croche, double-croche, croche] →
  barre primaire sur les 4, barre secondaire uniquement sur les 2 du milieu

#### RENDER-07 — Séparation des zones numéro de mesure / accord / section
**Fichier** : `src/fretwise/export/pdf_tab.py`
**Fonctions** : `_draw_system()`, constantes de layout
- Ajuster les constantes verticales selon §2.1
- `CHORD_Y = 22pt`, `MNUM_Y = 31pt`, `SECTION_Y = 52pt`
- Couper les noms d'accord trop longs (`> measure_w - 6pt`) avec `…`
- Vérifier que section marker ne chevauche pas le numéro de mesure ni le tempo

---

### P2 — Qualité visuelle

#### RENDER-08 — Annotations de doigt sans collision
**Fichier** : `src/fretwise/export/pdf_tab.py`
**Fonctions** : `_draw_note()` → intégrer A5
- Vérifier la clearance avant de dessiner chaque annotation
- Si collision : décaler latéralement (x -= 3.5pt)
- Si espace insuffisant malgré décalage : omettre l'annotation de la corde
  la plus aiguë (la moins informative dans un accord dense)

#### RENDER-09 — Réduction de la hauteur des hampes
**Fichier** : `src/fretwise/export/pdf_tab.py`
**Constante** : `STEM_H = 16pt → 14pt`, `BEAM_TOP_Y = 14pt`
- Réduire d'1 à 2pt pour dégager la zone d'accord
- Ajuster `CHORD_Y = 22pt` pour rester 6pt sous la barre

#### RENDER-10 — Correction chevauchement dans la légende
**Fichier** : `src/fretwise/export/pdf_tab.py`
**Fonction** : `_draw_rhythm_legend()`
- Décaler vers le bas le label "Silences correspondants :" de 4pt
  pour ne pas chevaucher l'ovale de la Ronde
- Ou augmenter l'espacement entre les deux rangées (notes / silences)

#### RENDER-11 — Rendu des silences dans la légende avec disque
**Fichier** : `src/fretwise/export/pdf_tab.py`
**Fonction** : `_draw_rhythm_legend()`
- Appliquer le même rendu disque blanc + symbole pour les silences
  de la légende, pour que la légende soit cohérente avec le rendu réel

#### RENDER-12 — Vérificateur de collisions post-rendu
**Fichier** : nouveau `src/fretwise/export/collision_checker.py`
- Fonction `check_collisions(bboxes: list[BBox]) -> list[Collision]`
- Chaque objet rendu (ovale, annotation, barre, silence) enregistre sa bbox
- Après rendu d'une mesure : vérifier les chevauchements
- Retourner un rapport de collisions (pour debug, pas affiché dans le PDF)
- Intégrer dans les tests : `assert len(check_collisions(...)) == 0`

---

## 6. Ordre d'implémentation suggéré

```
Sprint A — Corrections critiques (P0, 1-2 jours)
  RENDER-01  silences dans le staff + disque blanc
  RENDER-02  silences coupent les barres
  RENDER-03  regroupement par temps (beat-aware)

Sprint B — Layout proportionnel (P1, 2-3 jours)
  RENDER-04  largeur de mesure variable
  RENDER-05  mps variable par système
  RENDER-06  barres secondaires partielles
  RENDER-07  séparation des zones textuelles

Sprint C — Polish visuel (P2, 1-2 jours)
  RENDER-08  annotations sans collision
  RENDER-09  hauteur des hampes
  RENDER-10  légende sans chevauchement
  RENDER-11  silences dans la légende
  RENDER-12  vérificateur de collisions

Validation finale :
  - Générer Stairway to Heaven et vérifier visuellement chaque screenshot
  - Générer 10 fichiers du corpus benchmarks/
  - pytest --cov >= 80%
```

---

## 7. Critères de validation visuelle

Pour chaque tâche, le critère de succès est :

| Critère | RENDER-01 | RENDER-02 | RENDER-03 | RENDER-04 | RENDER-05 |
|---------|-----------|-----------|-----------|-----------|-----------|
| Aucun silence masqué par une barre | X | | | | |
| Aucune barre enjambe un silence | | X | | | |
| Barres groupées par temps | | | X | | |
| Notes espacées proportionnellement | | | | X | |
| Mesures larges si denses | | | | X | X |
| Aucune collision texte visible | | | | | |

Outil de validation : `scripts/diagnose_pdf_rests.py` (existant) +
nouveau `scripts/validate_layout.py` qui génère un rapport HTML des
bounding boxes pour inspection visuelle.
