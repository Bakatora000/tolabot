# Admin API Contract V1

## Scope

Cette API est reservee a l'administration memoire.

Contraintes V1 en production actuelle :
- les routes admin sont montees dans le process `mem0-api` existant
- acces via tunnel SSH vers `127.0.0.1:8000`
- pas d'exposition publique via Nginx
- les routes admin sont sous le prefixe `/admin`

Pourquoi :
- le backend prod utilise Qdrant local par `path`
- un second process Python ouvrirait le meme stockage Qdrant et echouerait sur un lock

## Auth

Header obligatoire :

```http
X-Admin-Key: <value>
```

La cle attendue est `MEM0_ADMIN_KEY`.

Erreurs d'auth :

- `401` :

```json
{"ok": false, "error": "missing_api_key"}
```

- `403` :

```json
{"ok": false, "error": "invalid_api_key"}
```

## Endpoints minimaux V1

### `GET /admin/health`

Reponse `200` :

```json
{
  "status": "ok",
  "service": "mem0-admin-api"
}
```

### `GET /admin/users`

Headers :
- `X-Admin-Key`

Query params optionnels :
- `channel`
- `viewer`
- `include_test_users`

Reponse `200` :

```json
{
  "ok": true,
  "users": [
    {
      "user_id": "twitch:streamer:viewer:alice",
      "channel": "streamer",
      "viewer": "alice"
    }
  ]
}
```

Notes :
- tri par `user_id`
- `channel` et `viewer` sont derives du `user_id`
- si le format ne matche pas la convention Twitch, `channel` et `viewer` peuvent etre `null`
- `include_test_users=false` par defaut masque les `user_id` de tests d'integration (`twitch:integration:...`, `windows_linux_e2e_*`)

### `GET /admin/users/{user_id}/recent`

Headers :
- `X-Admin-Key`

Query params optionnels :
- `limit`

Reponse `200` :

```json
{
  "ok": true,
  "results": [
    {
      "id": "mem_123",
      "user_id": "twitch:streamer:viewer:alice",
      "memory": "Le viewer aime les amplis compacts.",
      "metadata": {
        "source": "twitch_chat",
        "channel": "streamer",
        "viewer": "alice"
      },
      "created_at": "2026-03-24T10:00:00Z",
      "updated_at": "2026-03-24T10:00:00Z",
      "score": 1.0
    }
  ]
}
```

### `DELETE /admin/users/{user_id}`

Headers :
- `X-Admin-Key`

Reponse `200` :

```json
{
  "ok": true,
  "user_id": "twitch:streamer:viewer:alice",
  "deleted_count": 2,
  "truncated": false
}
```

`truncated=true` signifie que la purge a atteint la limite de securite `MEM0_ADMIN_EXPORT_LIMIT`.

## Endpoints disponibles en plus dans la V1 Linux

- `POST /admin/users/{user_id}/search`
- `DELETE /admin/memories/{memory_id}`
- `POST /admin/users/{user_id}/export`
- `POST /admin/users/{user_id}/import`
- `POST /admin/users/{user_id}/remember`
- `GET /admin/homegraph/users/{user_id}/context`
- `POST /admin/homegraph/users/{user_id}/enrichment`

## Endpoint Homegraph V1

### `GET /admin/homegraph/users/{user_id}/context`

Headers :
- `X-Admin-Key`

Reponse `200` :

```json
{
  "ok": true,
  "viewer_id": "twitch:streamer:viewer:alice",
  "generated_at": "2026-03-24T18:30:00Z",
  "source": "homegraph_v1",
  "staleness": {
    "profile_last_updated_at": "2026-03-24T17:10:00Z",
    "is_stale": false
  },
  "context": {
    "summary_short": "Viewer regulier, parle souvent de jeux de construction et d'optimisation.",
    "facts_high_confidence": [
      "joue souvent a Satisfactory",
      "prefere les builds efficaces"
    ],
    "recent_relevant": [],
    "uncertain_points": []
  },
  "text_block": "Contexte viewer:\n- Viewer regulier, parle souvent de jeux de construction et d'optimisation.\n- joue souvent a Satisfactory\n- prefere les builds efficaces"
}
```

Notes :
- acces local uniquement via le meme garde admin que les autres routes `/admin/*`
- `text_block` est la sortie principale a injecter dans le prompt cote Windows

### `GET /admin/homegraph/users/{user_id}/graph`

Headers :
- `X-Admin-Key`

Reponse `200` :

```json
{
  "ok": true,
  "viewer_id": "twitch:streamer:viewer:alice",
  "generated_at": "2026-03-26T10:00:00Z",
  "source": "homegraph_graph_v1",
  "meta": {
    "root_node_id": "viewer:twitch:streamer:viewer:alice",
    "filtered_by_viewer": true,
    "profile_last_updated_at": "2026-03-26T09:45:00Z",
    "stable_node_kinds": ["viewer", "game", "topic", "running_gag", "trait", "stream_mode", "object"],
    "stable_link_kinds": ["plays", "likes", "dislikes", "talks_about", "returns_to", "knows", "compliments", "jokes_about", "interacts_with", "uses_build_style", "plays_in_mode", "owns"]
  },
  "stats": {
    "node_count": 6,
    "link_count": 5,
    "node_kinds": {
      "viewer": 1,
      "game": 2
    },
    "link_kinds": {
      "plays": 1,
      "likes": 2
    }
  },
  "nodes": [
    {
      "id": "viewer:twitch:streamer:viewer:alice",
      "label": "Alice",
      "kind": "viewer",
      "color": "#4F46E5",
      "detail": "Resume court optionnel"
    }
  ],
  "links": [
    {
      "source": "viewer:twitch:streamer:viewer:alice",
      "target": "game:valheim",
      "kind": "plays",
      "label": "plays",
      "color": "#2563EB",
      "weight": 0.95,
      "detail": "status=active | polarity=positive | evidence=3"
    }
  ]
}
```

Notes :
- sous-graphe filtre par viewer, destine a une vue 2D/3D admin
- le contrat detaille est documente dans `homegraph/viewer_graph_contract_v1.md`
- acces local uniquement via le meme garde admin que les autres routes `/admin/*`
- filtres optionnels supportes :
  - `include_uncertain=true|false`
  - `min_weight=<float>`
  - `max_links=<int>`

### `GET /admin/homegraph/graph`

Route multi-hop pour charger un sous-graphe centre sur n'importe quel noeud connu.

Headers :
- `X-Admin-Key`

Query params :
- `center_node_id` (obligatoire)
- `max_depth`
- `max_nodes`
- `max_links`
- `include_uncertain`
- `min_weight`

Exemple :

```text
/admin/homegraph/graph?center_node_id=game:valheim&max_depth=2&max_nodes=20&max_links=30&include_uncertain=false&min_weight=0.7
```

### `POST /admin/homegraph/users/{user_id}/enrichment`

Route de fusion d'un enrichissement GPT vers `homegraph`.

Headers :
- `X-Admin-Key`

Query params optionnels :
- `dry_run=true|false`

Body minimal :

```json
{
  "viewer_id": "twitch:streamer:viewer:alice",
  "summary_short": "Viewer regulier, joue surtout a Valheim.",
  "facts": [
    {
      "kind": "stream_context",
      "value": "revient souvent sur Valheim",
      "confidence": 0.86,
      "status": "active",
      "source_memory_ids": ["mem_1"]
    }
  ],
  "relations": [
    {
      "target_type": "game",
      "target_id_or_value": "Valheim",
      "relation_type": "plays",
      "confidence": 0.92,
      "source_memory_ids": ["mem_1"]
    }
  ],
  "links": [
    {
      "target_type": "stream_mode",
      "target_value": "no death",
      "relation_type": "likes",
      "strength": 0.84,
      "confidence": 0.81,
      "status": "active",
      "polarity": "positive",
      "source_memory_ids": ["mem_2"]
    }
  ],
  "model_name": "gpt-5",
  "source_ref": "openai-review:alice:2026-03-27"
}
```

Reponse `200` :

```json
{
  "ok": true,
  "viewer_id": "twitch:streamer:viewer:alice",
  "generated_at": "2026-03-27T14:00:00Z",
  "source": "homegraph_enrichment_v1",
  "dry_run": false,
  "merged": {
    "facts": 1,
    "relations": 1,
    "links": 1
  },
  "context": {
    "summary_short": "Viewer regulier, joue surtout a Valheim.",
    "facts_high_confidence": [
      "joue souvent a Valheim"
    ],
    "recent_relevant": [],
    "uncertain_points": []
  },
  "text_block": "Contexte viewer:\n- Viewer regulier, joue surtout a Valheim.\n- joue souvent a Valheim",
  "graph_stats": {
    "node_count": 3,
    "link_count": 2,
    "node_kinds": {
      "viewer": 1,
      "game": 1,
      "stream_mode": 1
    },
    "link_kinds": {
      "plays": 1,
      "likes": 1
    }
  }
}
```

Notes :
- `viewer_id` dans le body doit matcher exactement le `user_id` de la route
- la route applique directement le merge dans SQLite via `homegraph`
- `model_name` et `source_ref` sont optionnels mais recommandes pour tracer une analyse GPT
- la reponse renvoie un apercu direct du contexte et des stats de graphe pour l'UI Windows
- si `dry_run=true`, Linux merge sur une copie temporaire de la base et ne persiste rien
/admin/homegraph/graph?center_node_id=game:valheim&max_depth=2&max_nodes=20&max_links=30&include_uncertain=false&min_weight=0.7
```

Meta retournee :
- `root_node_id`
- `center_node_id`
- `max_depth`
- `truncated`
- `filters_applied`

Notes :
- expansion BFS bornee cote Linux
- la route viewer V1 reste intacte pour compatibilite
- contrat detaille documente dans `homegraph/viewer_graph_contract_v1.md`

## Format d'erreur generique

Exemple :

```json
{
  "ok": false,
  "error": "invalid_request",
  "detail": "Field 'query' is required."
}
```
