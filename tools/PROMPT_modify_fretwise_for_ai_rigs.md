# Prompt pour modifier FretWise

Utilise le skill local `tools/fretwise-song-rig.SKILL.md`.

Objectif : modifier FretWise pour appeler le wrapper local de generation de rigs guitare et recuperer le JSON produit.

Contexte :
- Tous les fichiers d'integration sont dans `tools/`.
- Wrapper : `tools/codex_song_rig.py`
- Config : `tools/fretwise_ai_rig.config.json`
- Prompt parametrable : `tools/fretwise_song_rig.prompt.md`
- Skill : `tools/fretwise-song-rig.SKILL.md`
- Schema de sortie : `tools/codex_song_rig.schema.json`

Travail a faire :
1. Trouver dans FretWise le modele/metier qui represente une chanson et son rig.
2. Ajouter un service applicatif local, par exemple `SongRigGenerationService`, qui :
   - recoit `artist`, `title`, et optionnellement `targetGuitar`;
   - lance `tools/codex_song_rig.py` en sous-processus;
   - ne passe jamais par PowerShell;
   - lit stdout;
   - parse stdout comme JSON;
   - capture stderr pour diagnostic;
   - gere timeout, annulation, erreur et cache;
   - renvoie un objet typé ou un DTO.
3. Ajouter un point d'appel UI/commande :
   - bouton ou action "Generer rig";
   - etat "generation en cours";
   - affichage des erreurs non bloquant;
   - conservation de l'ancien rig si la generation echoue.
4. Ajouter un stockage du JSON accepte dans le catalogue FretWise existant.
5. Ajouter des reglages :
   - provider (`codex`, plus tard `lmstudio`, `openai`, `mcp`);
   - chemin Python;
   - chemin tools;
   - timeout;
   - refresh/cache.
6. Ajouter au minimum un test unitaire du parsing JSON et un test du service avec un faux process runner.

Contraintes :
- Garder les changements scopes.
- Ne pas hard-coder le chemin exact du binaire Codex WindowsApps.
- Utiliser `ArgumentList` en C#.
- Ne pas bloquer le thread UI.
- Ne pas supprimer les donnees existantes.
- Ne pas appeler directement l'API OpenAI depuis FretWise pour l'instant.

Commande de reference :

```powershell
python tools\codex_song_rig.py "AC/DC" "Highway To Hell"
```

Exemple stdout attendu :

```json
{
  "schema_version": "codex_output_schema_v1",
  "artist": "AC/DC",
  "song": "Highway To Hell",
  "recommended_guitar": "Gibson SG bridge humbucker",
  "signal_chain": "NR -> AMP -> CAB -> EQ -> RVB",
  "rig": {
    "nr": "Gate 1 ...",
    "pre": "Off",
    "dst": "Off",
    "amp": "UK 50 ...",
    "cab": "UK Vintage 4x12 ...",
    "eq": "Guitar EQ 1 ...",
    "mod": "Off",
    "dly": "Off",
    "rvb": "Room ..."
  },
  "reliability": "B",
  "comments": "..."
}
```
