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

## Format d'erreur generique

Exemple :

```json
{
  "ok": false,
  "error": "invalid_request",
  "detail": "Field 'query' is required."
}
```
