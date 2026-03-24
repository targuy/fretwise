# Audit Core Notation vs `Notation-musicale.pdf` (2026-03-17)

## Contexte

Audit demand\u00e9 apr\u00e8s comparaison visuelle des vues web core (`standard`, `standard_tablature`, `tablature_rhythm`) avec la norme de r\u00e9f\u00e9rence `Notation-musicale.pdf`.

Constat initial observ\u00e9 en UI:
- rendu tronqu\u00e9 \u00e0 un seul syst\u00e8me (une seule ligne visible),
- repr\u00e9sentation standard incompl\u00e8te,
- collisions et hi\u00e9rarchie visuelle insuffisantes.

## Correctifs appliqu\u00e9s dans ce lot

- `RenderScene` parcourt maintenant tous les `system_layouts` (plus seulement le premier).
- positions verticales de syst\u00e8mes fix\u00e9es dans le layout (`system.y` progressif),
- hauteur de page layout/sc\u00e8ne adapt\u00e9e au nombre de syst\u00e8mes,
- mode `tablature_rhythm` rendu sur tous les syst\u00e8mes,
- marquages dynamiques minimaux ajout\u00e9s c\u00f4t\u00e9 standard (changement de dynamique),
- conformance interne core v\u00e9rifi\u00e9e (\u00e0 date) sans issue sur la fixture test\u00e9e.
- accords: regroupement rythmique par `onset` (une hampe/beam/flag par attaque),
- s\u00e9paration des mesures: ajout de `barline` dans tous les modes core,
- notation standard: `notehead` pleine/creuse selon dur\u00e9e + projection verticale diatonique,
- notes hors port\u00e9e: ajout des `ledger_line`,
- collisions d'alt\u00e9rations dans les accords: d\u00e9calage horizontal progressif,
- web core: SVG rendu responsive en largeur (`width:100%`, `height:auto`).

## Mesure objective sur `AC_DC-Highway To Hell-12-22-2025.gp`

Ex\u00e9cution locale du pipeline core:
- `systems`: `5`
- `page_height`: `1376.0`

Inventaire extrait du `RenderScene`:

- Mode `tablature`:
  - glyphes: `time_signature`
  - recettes: `tab_lines`, `palm_mute_span`
  - textes: `measure_number`, `note`
- Mode `tablature_rhythm`:
  - glyphes: `time_signature`
  - recettes: `tab_lines`, `stem_line`, `beam_group`, `flag_stack`, `palm_mute_span`
  - textes: `measure_number`, `note`
- Mode `standard`:
  - glyphes: `time_signature`, `clef`, `notehead`, `accidental_sharp`, `accidental_flat`
  - recettes: `staff_lines`, `barline`, `ledger_line`, `stem_line`, `beam_group`, `flag_stack`, `tie_arc`, `slur_arc`
  - textes: `measure_number`, `dynamic`
- Mode `standard_tablature`:
  - union des \u00e9l\u00e9ments standard + tablature.

## Matrice d'\u00e9cart normatif (r\u00e9f\u00e9rence `Notation-musicale.pdf`)

### Pages 87-91: syst\u00e8me solf\u00e8ge + tablature, r\u00e9duction tab+rythme, effets

- Syst\u00e8me standard+tab sur tout le morceau: **PARTIEL -> CORRIG\u00c9 STRUCTURELLEMENT** (multi-syst\u00e8mes OK).
- R\u00e9duction tab+rythme comme variante: **PARTIEL** (structure pr\u00e9sente, couverture symbolique incompl\u00e8te).
- Effets de jeu ancr\u00e9s tab (hammer/pull/slide/bend/vibrato/tapping): **PARTIEL**.
  - pr\u00e9sent: `palm_mute_span`, `let_ring_span` (selon contenu),
  - manquant/incomplet: rendu explicite complet des familles d'effets de la norme.

### Pages 40-44: r\u00e8gles rythmiques (dur\u00e9es, silences, liaison)

- Hampes/ligatures/flags: **PARTIEL** (pr\u00e9sent au niveau recette, pas gravure compl\u00e8te normative).
- Silences standards complets (gamme de valeurs + positionnement avanc\u00e9): **PARTIEL**.
- Notation point\u00e9e/double-point\u00e9e, tuplets avanc\u00e9s: **MANQUANT/PARTIEL**.

### Pages 59-60: lisibilit\u00e9, groupements, collisions

- Groupements rythmiques de base: **PARTIEL**.
- R\u00e8gles collisions/micro-ajustements multi-objets: **INSUFFISANT** (moteur de collisions encore minimal).
- Politique stemlet (cas complexes): **MANQUANT**.

## Limites actuelles (bloquantes pour un \"100% conforme\")

- jeu de glyphes de r\u00e9f\u00e9rence encore tr\u00e8s r\u00e9duit,
- pas de moteur de gravure standard complet (positionnement avanc\u00e9, ledger lines, signatures riches, ornements),
- couverture partielle des symboles d'effets de jeu de la norme,
- conformance checks orient\u00e9s structure/alignement, pas encore validation graphique exhaustive.

## Priorit\u00e9s recommand\u00e9es (prochain lot)

1. \u00c9tendre le `reference_glyph_set` + backend SVG/PDF pour les symboles standards manquants.
2. Impl\u00e9menter un moteur collisions inter-objets (textes, arcs, accidentals, dynamiques, beams).
3. Couvrir explicitement les effets de jeu normatifs (pages 88-89) dans le canonical -> scene.
4. Ajouter des tests de conformit\u00e9 visuelle snapshot sur corpus r\u00e9el (dont `Highway To Hell`).
5. Introduire un rapport d'audit normatif d\u00e9taill\u00e9 par mode (symboles attendus vs pr\u00e9sents).
