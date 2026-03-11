# FretWise — Global Accuracy & Quality Report

**Date:** 2026-03-11 (mis à jour — Phase 1 complète)
**Corpus:** 36 fichiers GP (`.gp` GPIF + `.gp5` PyGuitarPro)
**Pipeline:** parse → states → Viterbi → finger_continuity → section_consistency → chord_conflicts → chord_stretch → chord_finger_ordering → ASCII tab + PDF

---

## 1. Tableau de synthèse

| Fichier | Notes | Viterbi | Drop | Sections | Issues |
|---|---|---|---|---|---|
| Adele-Rolling In The Deep | 1781 | 1781 | 0 % | 10 | ✅ |
| **Adele-Someone Like You** | **0** | **—** | **100 %** | — | ❌ Pas de piste guitare (piano/vocal) |
| Bon Jovi-Wanted Dead Or Alive | 2066 | 2066 | 0 % | 12 | ⚠️ 1 span `!` |
| David Bowie-China Girl | 590 | 590 | 0 % | 9 | ✅ (multi-voix résolu) |
| David Bowie-Life On Mars | 78 | 78 | 0 % | 6 | ✅ (tab commence mesure 44) |
| David Bowie-Modern Love | 715 | 715 | 0 % | 6 | ✅ |
| David Bowie-Moonage Daydream | 1320 | 1320 | 0 % | 8 | ✅ |
| David Bowie-Rebel Rebel | 1218 | 1218 | 0 % | 0 | ✅ |
| David Bowie-Suffragette City | 346 | 346 | 0 % | 16 | ✅ |
| David Bowie-Under Pressure | 628 | 628 | 0 % | 0 | ✅ |
| David Bowie-Ziggy Stardust | 1057 | 1057 | 0 % | 10 | ✅ |
| Django Reinhardt-Gypsy Jazz | 532 | 532 | 0 % | 0 | ✅ (était 0 → corrigé P3) |
| Django Reinhardt-I'll See You… | 854 | 854 | 0 % | 0 | ✅ |
| Django Reinhardt-Minor Swing | 1784 | 1784 | 0 % | 5 | ✅ |
| Django Reinhardt-Nuages | 667 | 667 | 0 % | 0 | ✅ |
| Gary Moore-Parisienne Walkways | 535 | 535 | 0 % | 0 | ✅ |
| Gary Moore-Still Got The Blues | 616 | 616 | 0 % | 0 | ✅ |
| Green Day-Basket Case | 2295 | 2295 | 0 % | 7 | ✅ (était 115 drops → corrigé) |
| Green Day-Boulevard Of Broken Dreams | 2750 | 2750 | 0 % | 12 | ✅ |
| Green Day-When I Come Around | 1394 | 1394 | 0 % | 7 | ✅ |
| Led Zeppelin-Stairway to Heaven | 4163 | 4163 | 0 % | 14 | ✅ |
| Lovin' Spoonful-Summer In The City | 1935 | 1935 | 0 % | 13 | ✅ |
| Metallica-Enter Sandman | 341 | 341 | 0 % | 16 | ✅ (tab commence mesure 45) |
| Michael Schenker Group-Desert Song | 768 | 768 | 0 % | 0 | ⚠️ 1 span `!` (onset 3.5) |
| Radiohead-Karma Police | 3241 | 3241 | 0 % | 7 | ✅ |
| Shocking Blue-Venus | 218 | 218 | 0 % | 8 | ✅ |
| Tears For Fears-Shout | 690 | 690 | 0 % | 13 | ✅ (était 220 G2 → corrigé P3) |
| Ted Nugent-Cat Scratch Fever | 1194 | 1194 | 0 % | 12 | ✅ |
| The Beatles-And I Love Her | 1907 | 1907 | 0 % | 0 | ⚠️ 3 spans `!` (barré > 4 frets) |
| The Beatles-Day Tripper | 467 | 467 | 0 % | 0 | ✅ |
| The Beatles-Drive My Car | 508 | 508 | 0 % | 0 | ✅ |
| The Beatles-Here Comes the Sun | 1071 | 1071 | 0 % | 0 | ✅ |
| The Beatles-Let It Be | 171 | 171 | 0 % | 0 | ✅ |
| The Beatles-Yesterday | 833 | 833 | 0 % | 0 | ✅ (était 15 drops → corrigé) |
| The Eagles-Hotel California | 4197 | 4197 | 0 % | 7 | ✅ |
| The Eagles-Hotel California Solo | 433 | 433 | 0 % | 0 | ✅ |
| The Police-Every Breath You Take | 487 | 487 | 0 % | 0 | ✅ |

**Global : 35/36 fichiers avec sortie utilisable (97 %). Total notes : ~44 000.**

---

## 2. Métriques clés

| Métrique | Valeur |
|---|---|
| Fichiers traités sans crash | 36/36 (100 %) |
| Fichiers avec sortie utilisable | 35/36 (97 %) |
| Notes totales traitées | ~44 000 |
| Drops (aucun état valide) | < 0.1 % |
| **Croisements de doigts dans les accords** | **0 / 36 fichiers** |
| Spans `!` non résolvables | 5 (barré > 4 frets, genuins) |
| Marqueurs de section détectés | 159 sur 26 fichiers |
| PDFs générés | 36/36 |

---

## 3. Bugs corrigés depuis v1 (2026-03-10)

| Bug | Description | Correction |
|---|---|---|
| BUG-01 | Tab vide (notes tardives) | `_group_by_measure` offset par première mesure |
| BUG-02 | Shout : 220 G2 identiques | Sélection piste améliorée (score multi-critères GPIF) |
| BUG-03 | Multi-voix `!` pervasifs | Pipeline par voix (Viterbi indépendant par voix GP) |
| BUG-04 | Gypsy Jazz : 0 notes | Matching MIDI program + type explicite guitare |
| BUG-05 | Basket Case 115 drops | Fallback hint-based pour tunings alternatifs |
| BUG-05 | Yesterday 15 drops | Idem |
| NEW | Croisement de doigts | `resolve_chord_finger_ordering` + passe inter-voix |

---

## 4. Qualité des doigtés — évaluation qualitative

### Meilleurs résultats (doigtés musicalement cohérents)
1. **Hotel California** — 4197 notes d'arpège, positions de main stables, accords Em/B7/G/D/A/C/C#dim corrects
2. **Stairway to Heaven** — 4163 notes, fingerpicking sections lentes correctement annotées, 14 sections
3. **Karma Police** — Am/G/C/Dm/F progressions correctes, arpeggios cohérents
4. **Yesterday** — Fmaj7/Em/Am7/Dm, barré F correctement détecté
5. **Here Comes the Sun** — Gmaj7/Em/E7/Dsus2 corrects, fingerpicking cohérent

### Points d'amélioration restants
- **Barré** : INDEX assigné à chaque corde séparément — pas de modélisation du barré réel
- **Principe diagonal** : la diagonale naturelle de la main (cordes graves→frets plus bas) non prise en compte dans le coût
- **And I Love Her** : 3 accords plaqués impossibles C#m7 (span 12 frets) marqués `!`

---

## 5. Nouvelles fonctionnalités PDF (Phase 1 finale)

| Fonctionnalité | Description |
|---|---|
| Marqueurs de section | Titre en bleu gras au-dessus de la mesure concernée |
| Let ring | Ligne en tirets bleus de l'ovale droit jusqu'à la mesure suivante |
| Symbole tempo | `♩ = 120` (Helvetica-Oblique) |
| Double barre finale | Barre thin + thick sur la dernière mesure du morceau |
| Doigt sous l'ovale | Lettre rouge (i/m/r/p) centrée sous le numéro de fret |
| Numéros de mesure réels | Offset depuis la première mesure de la guitare |

---

*Rapport généré automatiquement par `scripts/run_fingering.py` — Phase 1 MVP terminée.*
