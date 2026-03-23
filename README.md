# mem0-api

Service HTTP JSON pour fournir une couche mémoire distante au bot Twitch Windows.

## Objectif

Le service expose une API REST stable devant le backend mémoire.

Contrat visé :
- `GET /health`
- `POST /search`
- `POST /remember`
- `POST /forget`
- `POST /recent`

Le bot Windows parle uniquement à cette API. Il ne doit jamais parler directement à mem0.

## Stack actuelle

- API : FastAPI
- Backend MVP local : stockage fichier JSON
- Backend cible : Mem0 OSS + Qdrant + SQLite history

Le backend actif est piloté par `MEMORY_BACKEND` :
- `file` : mode de démarrage simple, utile pour valider l’API et l’intégration Windows
- `mem0` : mode cible, utilisant `mem0ai` et Qdrant

## Lancement local

1. Installer les dépendances :

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Copier l’exemple d’environnement :

```bash
cp .env.example .env
```

3. Ajuster au minimum :

```env
MEM0_API_KEY=xxxxxxxxxxxxxxxx
MEMORY_BACKEND=file
```

4. Lancer le service :

```bash
uvicorn main:app --host 127.0.0.1 --port 8000
```

## Exemple d’appels

Healthcheck :

```bash
curl http://127.0.0.1:8000/health
```

Remember :

```bash
curl -X POST http://127.0.0.1:8000/remember \
  -H 'X-API-Key: xxxxxxxxxxxxxxxx' \
  -H 'Content-Type: application/json' \
  -d '{
    "user_id": "twitch:expevay:viewer:alice",
    "text": "Le viewer préfère les amplis compacts.",
    "metadata": {
      "source": "twitch_chat",
      "channel": "expevay",
      "viewer": "alice",
      "message_id": "abc123"
    }
  }'
```

Search :

```bash
curl -X POST http://127.0.0.1:8000/search \
  -H 'X-API-Key: xxxxxxxxxxxxxxxx' \
  -H 'Content-Type: application/json' \
  -d '{
    "user_id": "twitch:expevay:viewer:alice",
    "query": "De quoi parlait-on à propos des amplis ?",
    "limit": 5
  }'
```

## Notes mem0 OSS

La documentation officielle mem0 OSS indique actuellement :
- installation Python via `pip install mem0ai`
- Qdrant comme vector store supporté
- SQLite history par défaut ou configurable

La classe `Mem0MemoryBackend` a été câblée pour ces composants via configuration, mais la validation réelle dépendra de l’installation effective de `mem0ai`, de Qdrant, et des clés provider nécessaires.

## Déploiement

Des gabarits sont fournis dans :
- `deploy/systemd/mem0-api.service`
- `deploy/nginx/olala.expevay.net.conf`

Ils sont volontairement simples pour un premier déploiement.
