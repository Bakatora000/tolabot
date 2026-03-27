# Homegraph GPT Enrichment Contract V1

## But

Ce contrat sert de passerelle entre :
- l'analyse GPT cote Windows
- et le merge `homegraph` cote Linux

L'objectif produit est simple :
- l'admin clique `Analyser avec GPT`
- Windows obtient un JSON structure
- Windows peut ensuite proposer `Fusionner dans Homegraph`
- Linux applique le merge et renvoie un apercu du resultat

## Endpoint Linux

```text
POST /admin/homegraph/users/{user_id}/enrichment
```

Validation rapide :

```text
POST /admin/homegraph/users/{user_id}/enrichment/validate
```

Auth :

```http
X-Admin-Key: <value>
```

Query param optionnel :
- `dry_run=true|false`

## Requete attendue

Champs top-level :
- `viewer_id`
- `channel`
- `viewer_login`
- `display_name`
- `summary_short`
- `summary_long`
- `facts`
- `relations`
- `links`
- `conflicts`
- `needs_human_review`
- `model_name`
- `source_ref`

Exemple :

```json
{
  "viewer_id": "twitch:expevay:viewer:dame_gaby",
  "channel": "expevay",
  "viewer_login": "dame_gaby",
  "display_name": "Dame_Gaby",
  "summary_short": "Joue a Valheim, pose souvent des questions au bot.",
  "summary_long": "Viewer reguliere autour de Valheim, avec plusieurs references sociales a MissCouette76 et Dae_3_7.",
  "facts": [
    {
      "kind": "stream_context",
      "value": "joue souvent a Valheim",
      "confidence": 0.92,
      "status": "active",
      "source_memory_ids": ["mem_1"],
      "source_excerpt": "Elle joue souvent a Valheim."
    }
  ],
  "relations": [
    {
      "target_type": "game",
      "target_id_or_value": "Valheim",
      "relation_type": "plays",
      "confidence": 0.93,
      "source_memory_ids": ["mem_1"]
    }
  ],
  "links": [
    {
      "target_type": "viewer",
      "target_value": "MissCouette76",
      "relation_type": "interacts_with",
      "strength": 0.78,
      "confidence": 0.74,
      "status": "active",
      "polarity": "neutral",
      "source_memory_ids": ["mem_2"],
      "source_excerpt": "Elle fait partie d'un groupe avec MissCouette76."
    }
  ],
  "conflicts": [],
  "needs_human_review": [],
  "model_name": "gpt-5",
  "source_ref": "openai-review:dame_gaby:2026-03-27"
}
```

## Regles de qualite recommandees cote Windows

- produire peu d'items, mais utiles
- preferer des liens explicites et exploitables
- ne pas dupliquer la meme info en `fact`, `relation` et `link` sans raison
- utiliser `status=uncertain` quand GPT hesite
- reserver `interacts_with`, `jokes_about`, `compliments` aux cas suffisamment clairs
- inclure `source_memory_ids` quand le mapping vers l'export mem0 est disponible

## Reponse Linux

La route renvoie :
- les compteurs merges
- le contexte viewer reconstruit
- le `text_block`
- les stats du graphe viewer courant

Exemple :

```json
{
  "ok": true,
  "viewer_id": "twitch:expevay:viewer:dame_gaby",
  "generated_at": "2026-03-27T14:00:00Z",
  "source": "homegraph_enrichment_v1",
  "dry_run": false,
  "merged": {
    "facts": 1,
    "relations": 1,
    "links": 1
  },
  "context": {
    "summary_short": "Joue a Valheim, pose souvent des questions au bot.",
    "facts_high_confidence": [
      "joue souvent a Valheim"
    ],
    "recent_relevant": [],
    "uncertain_points": []
  },
  "text_block": "Contexte viewer:\n- Joue a Valheim, pose souvent des questions au bot.\n- joue souvent a Valheim",
  "graph_stats": {
    "node_count": 3,
    "link_count": 2,
    "node_kinds": {
      "viewer": 2,
      "game": 1
    },
    "link_kinds": {
      "plays": 1,
      "interacts_with": 1
    }
  }
}
```

## Usage recommande cote produit

### V1

- bouton Windows : `Analyser avec GPT`
- afficher :
  - resume humain
  - JSON d'enrichissement propose
- bouton secondaire :
  - `Fusionner dans Homegraph`

### Preview conseillee

- Windows peut d'abord appeler :
  - `POST /admin/homegraph/users/{user_id}/enrichment/validate`
- si `mergeable=false`, on reste dans l'UI de correction et on ne propose pas le merge

- Windows peut d'abord appeler :
  - `POST /admin/homegraph/users/{user_id}/enrichment?dry_run=true`
- Linux renvoie alors le meme apercu de contexte et de graphe
- mais sans ecrire dans la vraie base

Ensuite seulement :
- `POST /admin/homegraph/users/{user_id}/enrichment`
- pour appliquer le merge reel

### Pourquoi cette separation

- l'analyse GPT reste explicite et controlable
- l'admin voit ce qui va etre merge
- on evite les merges automatiques opaques

## Non-objectifs V1

- pas de merge automatique en masse
- pas de review GPT obligatoire pour tous les viewers
- pas de resolution parfaite des alias sociaux

La V1 sert surtout a enrichir proprement les viewers importants ou ambigus.
