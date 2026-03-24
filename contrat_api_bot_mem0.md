# Contrat d'API — Bot Twitch Windows ↔ Service mémoire mem0 Linux

## But

Ce document définit le contrat d'API entre :

- le bot Twitch exécuté sur le PC Windows
- le service mémoire exécuté sur le serveur Linux
- mem0 utilisé uniquement côté serveur Linux

Le bot Windows ne doit jamais parler directement à mem0.
Il doit parler uniquement au service HTTP exposé par le serveur Linux.

---

## Architecture retenue

### Côté Windows

Le bot :
- écoute le chat Twitch
- utilise Ollama en local pour générer les réponses
- appelle l'API HTTP distante pour lire/écrire la mémoire

### Côté Linux

Le service mémoire :
- expose une API REST JSON
- encapsule mem0
- s'appuie sur la stack retenue :
  - **Mem0 OSS**
  - **Qdrant** pour la partie vectorielle
  - **SQLite history** pour l'historique mem0

Référence produit / doc :
- [Mem0 OSS overview](https://docs.mem0.ai/open-source/overview)

---

## Exposition réseau

Le service sera exposé derrière HTTPS sur :

- `https://memory.example.net`

Le déploiement attendu côté Linux est :
- reverse proxy HTTP(S)
- certificat TLS valide

Exemples raisonnables :
- Nginx + Certbot
- Caddy

---

## Principes généraux

- API REST JSON uniquement
- encodage UTF-8
- authentification par clé d'API statique
- timeout court côté client Windows
- pas d'état de session HTTP côté serveur

### Responsabilités côté Linux

Le service Linux est responsable de :
- l'accès à mem0
- la normalisation des entrées/sorties
- la validation des payloads
- la gestion d'erreur
- la journalisation serveur
- l'idempotence raisonnable sur `/remember`

### Responsabilités côté Windows

Le bot Windows est responsable de :
- l'appel réseau
- la tolérance aux pannes
- l'orchestration des appels mémoire
- l'injection du contexte mémoire dans le prompt Ollama
- le fallback local éventuel si activé

---

## Configuration attendue

### Côté Windows

Variables minimales :

```env
MEM0_API_BASE_URL=https://memory.example.net/api/memory
MEM0_API_KEY=xxxxxxxxxxxxxxxx
MEM0_TIMEOUT_SECONDS=10
MEM0_ENABLED=true
MEM0_FALLBACK_LOCAL=true
```

### Côté Linux

Variables minimales :

```env
MEM0_API_KEY=xxxxxxxxxxxxxxxx
MEM0_DEFAULT_LIMIT=5
MEM0_HOST=127.0.0.1
MEM0_PORT=8000
LOG_LEVEL=INFO
```

Variables supplémentaires probables selon la config mem0 :
- configuration Qdrant
- chemins de persistance
- configuration du provider LLM / embedder mem0 si nécessaire

---

## Authentification

Chaque requête envoyée par le bot Windows doit contenir :

```http
X-API-Key: <MEM0_API_KEY>
Content-Type: application/json
Accept: application/json
```

Si la clé est absente ou invalide :
- HTTP 401 si la clé est absente
- HTTP 403 si la clé est invalide

---

## Convention d'identité

La mémoire doit être **par viewer**, pas seulement par chaîne.

Champ obligatoire :

- `user_id`

Format retenu :

- `twitch:<channel_login>:viewer:<viewer_login>`

Exemple :

- `twitch:streamer:viewer:alice`

### Règles

- `channel_login` doit être le login Twitch de la chaîne en minuscules
- `viewer_login` doit être le login Twitch du viewer en minuscules
- `user_id` doit être stable d'un live à l'autre

### Metadata recommandée

En complément, les payloads doivent pouvoir porter :
- `channel`
- `viewer`
- `source`
- `message_id`
- `session_id` optionnel

---

## Politique de mémoire

Le backend mémoire doit accepter :
- des souvenirs stables
- des fragments de discussion utiles

On ne veut pas seulement mémoriser des "faits profil".
On veut aussi mémoriser des éléments utiles de discussion, réutilisables sur d'autres lives.

### Contraintes

- limiter la taille des textes
- dédupliquer raisonnablement
- éviter les doublons sur retries ou rediffusions de payloads

### Recommandation d'idempotence

Sur `/remember`, si `metadata.message_id` est fourni :
- l'utiliser comme clé pratique d'idempotence
- éviter d'enregistrer deux fois le même élément si le client réessaie

---

## Endpoints obligatoires

Le service Linux doit exposer exactement ces endpoints :

- `GET /health`
- `POST /search`
- `POST /remember`
- `POST /forget`

Endpoint optionnel mais recommandé :

- `POST /recent`

---

## 1) Healthcheck

### Requête

```http
GET /health
```

### Réponse 200

```json
{
  "status": "ok",
  "service": "mem0-api"
}
```

Usage :
- vérification simple par le bot
- supervision
- test reverse proxy / TLS

---

## 2) Recherche de mémoire

### Requête

```http
POST /search
```

### Body JSON

```json
{
  "user_id": "twitch:streamer:viewer:alice",
  "query": "De quoi parlait-on hier à propos du setup audio ?",
  "limit": 5
}
```

### Règles

- `user_id` obligatoire, string non vide
- `query` obligatoire, string non vide
- `limit` optionnel, entier strictement positif
- si `limit` absent, le serveur applique sa valeur par défaut
- le serveur borne `limit` à une valeur raisonnable, par exemple 10 max

### Réponse 200

```json
{
  "ok": true,
  "results": [
    {
      "id": "mem_001",
      "score": 0.91,
      "memory": "L'utilisateur possède un DAC FiiO K11 R2R."
    },
    {
      "id": "mem_002",
      "score": 0.82,
      "memory": "L'utilisateur utilise des Eltax Monitor III avec un ampli Fosi Audio T20X."
    }
  ]
}
```

### Règles de réponse

- `ok` obligatoire
- `results` toujours présent, éventuellement vide
- chaque item contient :
  - `id` string
  - `score` number
  - `memory` string

Si aucune mémoire n'est trouvée :

```json
{
  "ok": true,
  "results": []
}
```

---

## 3) Ajout d'un souvenir

### Requête

```http
POST /remember
```

### Body JSON

```json
{
  "user_id": "twitch:streamer:viewer:alice",
  "text": "Le viewer préfère qu'on l'appelle Alice en vocal.",
  "metadata": {
    "source": "twitch_chat",
    "channel": "streamer",
    "viewer": "alice",
    "message_id": "abc123"
  }
}
```

### Règles

- `user_id` obligatoire, string non vide
- `text` obligatoire, string non vide
- `metadata` optionnel, objet JSON libre mais raisonnable en taille
- le serveur peut enrichir, normaliser ou filtrer les métadonnées avant stockage

### Réponse 200

```json
{
  "ok": true,
  "id": "mem_003"
}
```

### Variante acceptable

```json
{
  "ok": true
}
```

---

## 4) Suppression de mémoire

### Requête

```http
POST /forget
```

### Body JSON

```json
{
  "user_id": "twitch:streamer:viewer:alice",
  "memory_id": "mem_003"
}
```

### Règles

- `user_id` obligatoire
- `memory_id` obligatoire

### Réponse 200

```json
{
  "ok": true,
  "deleted": true
}
```

Si l'élément n'existe pas :

```json
{
  "ok": true,
  "deleted": false
}
```

Usage prévu :
- admin
- debug
- nettoyage manuel futur

---

## Endpoint optionnel mais recommandé

## 5) Liste récente

### Requête

```http
POST /recent
```

### Body JSON

```json
{
  "user_id": "twitch:streamer:viewer:alice",
  "limit": 10
}
```

### Réponse 200

```json
{
  "ok": true,
  "results": [
    {
      "id": "mem_010",
      "memory": "Le viewer a expliqué qu'il préfère qu'on l'appelle Alice.",
      "created_at": "2026-03-23T20:10:00Z"
    }
  ]
}
```

Usage :
- debug
- page d'admin future
- vérification manuelle

Le MVP peut fonctionner sans cet endpoint.

---

## Codes d'erreur HTTP

### 200

Requête traitée, même si aucun résultat de mémoire.

### 400

Payload invalide ou champ requis manquant.

Exemple :

```json
{
  "ok": false,
  "error": "invalid_request",
  "detail": "Field 'query' is required."
}
```

### 401

Header `X-API-Key` absent.

### 403

Clé d'API invalide.

### 404

Endpoint inexistant.

### 500

Erreur interne serveur.

Exemple :

```json
{
  "ok": false,
  "error": "internal_error"
}
```

### 503

Backend mémoire indisponible temporairement.

Exemple :

```json
{
  "ok": false,
  "error": "memory_backend_unavailable"
}
```

---

## Règles côté bot Windows

- toujours entourer les appels réseau avec `try/except`
- timeout obligatoire
- ne jamais bloquer la boucle Twitch plus que nécessaire
- limiter la taille des textes envoyés à `/remember`
- appeler `/search` seulement quand une réponse IA est réellement envisagée

### En cas d'échec réseau ou HTTP non 2xx

Le bot doit :
- journaliser l'erreur
- continuer sans casser le bot Twitch
- utiliser le fallback local si activé

### Politique fonctionnelle

Quand mem0 est activé et disponible :
- mem0 remplace la mémoire locale JSON comme source principale de mémoire

Le fallback local reste un mode de secours, pas la source de vérité cible.

---

## Règles côté service Linux

- valider systématiquement les payloads
- ne jamais exposer de stacktrace brute au client
- protéger l'accès par clé API
- être conçu pour fonctionner derrière un reverse proxy HTTPS
- ne pas dépendre d'un état de session HTTP

### Journalisation attendue

Le service doit journaliser au minimum :
- endpoint
- statut HTTP
- durée
- `user_id` si présent

---

## Séquence fonctionnelle cible

### Quand le bot est mentionné dans le chat

1. le bot détecte `@nom_du_bot`
2. il décide si une réponse est nécessaire
3. s'il doit répondre, il appelle `POST /search`
4. il injecte les souvenirs retournés dans le prompt Ollama local
5. il génère et publie la réponse
6. si le message ou l'échange mérite d'être retenu, il appelle `POST /remember`

### Quand l'API mémoire distante est indisponible

1. le bot journalise l'échec
2. le bot n'interrompt pas le traitement du chat
3. il bascule éventuellement vers le fallback local si activé

---

## Exemples cURL

### Health

```bash
curl -H "X-API-Key: xxxxxxxxxxxxxxxx" \
  https://memory.example.net/api/memory/health
```

### Search

```bash
curl -X POST \
  -H "X-API-Key: xxxxxxxxxxxxxxxx" \
  -H "Content-Type: application/json" \
  https://memory.example.net/api/memory/search \
  -d '{
    "user_id": "twitch:streamer:viewer:alice",
    "query": "De quoi parlait-on hier ?",
    "limit": 5
  }'
```

### Remember

```bash
curl -X POST \
  -H "X-API-Key: xxxxxxxxxxxxxxxx" \
  -H "Content-Type: application/json" \
  https://memory.example.net/api/memory/remember \
  -d '{
    "user_id": "twitch:streamer:viewer:alice",
    "text": "Alice a expliqué qu elle préfère qu on l appelle Alice sur le chat.",
    "metadata": {
      "source": "twitch_chat",
      "channel": "streamer",
      "viewer": "alice",
      "message_id": "abc123"
    }
  }'
```

---

## Décisions de compatibilité

Pour éviter les divergences entre Windows et Linux :

- ne pas renommer les endpoints
- ne pas renommer les champs JSON
- ne pas changer le header d'authentification
- ne pas faire parler Windows directement à mem0
- respecter la convention `user_id` par viewer

---

## MVP recommandé

Pour la première version, il suffit d'implémenter :

- `GET /health`
- `POST /search`
- `POST /remember`

Ensuite :
- `POST /forget`
- `POST /recent`

---

## Critère de succès

Le système est considéré opérationnel si :

1. le bot Twitch fonctionne même si l'API mémoire distante est hors ligne
2. le bot récupère des souvenirs distants pertinents avant appel à Ollama
3. le bot peut enregistrer de nouveaux souvenirs à distance
4. la mémoire est partitionnée correctement par viewer
5. la configuration passe uniquement par variables d'environnement
6. le service Linux est déployable proprement derrière `memory.example.net`
