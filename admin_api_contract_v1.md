# Admin API Contract V1

## Scope

Cette API est reservee a l'administration memoire.

Contraintes V1 :
- ecoute locale seulement sur `127.0.0.1:9000`
- acces via tunnel SSH depuis Windows
- pas d'exposition publique via Nginx

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

### `GET /health`

Reponse `200` :

```json
{
  "status": "ok",
  "service": "mem0-admin-api"
}
```

### `GET /users`

Headers :
- `X-Admin-Key`

Query params optionnels :
- `channel`
- `viewer`

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

### `GET /users/{user_id}/recent`

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

### `DELETE /users/{user_id}`

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

- `POST /users/{user_id}/search`
- `DELETE /memories/{memory_id}`
- `POST /users/{user_id}/export`
- `POST /users/{user_id}/import`
- `POST /users/{user_id}/remember`

## Format d'erreur generique

Exemple :

```json
{
  "ok": false,
  "error": "invalid_request",
  "detail": "Field 'query' is required."
}
```
