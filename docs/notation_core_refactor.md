# Notation Core Refactor (Scaffold)

This document freezes the target layering for the notation-core hardening
branch. The existing pipeline remains active while these layers are introduced.

## Layers

1. `core.ingest`: format detection and raw extraction boundary.
2. `core.normalize`: cross-format harmonization without musical rewrite.
3. `core.complete`: prudent completion for safe inferences only.
4. `core.validate`: syntax/structure/notation/musical/instrumental checks.
5. `core.decision`: explicit accept/reject policy outcomes.
6. `core.canonical`: source-format-independent semantic model.
7. `core.layout`: anchors, placement rules, collisions, deformation policy.
8. `core.graphics`: notation policy, reference glyphs, parametric recipes.
9. `core.scene`: backend-independent render scene.
10. `core.backends`: scene rendering backends (SVG master, PDF, UI bridge).
11. `core.transform`: transposition, respelling, tuning adaptation, editing ops.

## Migration Rule

No major functional behavior is removed during scaffold introduction.
Existing modules (`parser`, `pipeline`, `export`, `web`) remain the production
path until replacement layers are contract-tested and integrated.
