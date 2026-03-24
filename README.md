# mem0-api

Service HTTP JSON pour fournir une couche mémoire distante au bot Twitch Windows.

## Structure du repo

- `memory_service/` : service mem0 HTTP cote Linux
- `deploy/` : deploiement systemd / Nginx
- `windows_bot/` : code du bot Twitch Windows partage

## Objectif

Le service expose une API REST stable devant le backend mémoire.

Contrat visé :
- `GET /health` en interne, publie via `GET /api/memory/health`
- `POST /search` en interne, publie via `POST /api/memory/search`
- `POST /remember` en interne, publie via `POST /api/memory/remember`
- `POST /forget` en interne, publie via `POST /api/memory/forget`
- `POST /recent` en interne, publie via `POST /api/memory/recent`

Le bot Windows parle uniquement à cette API. Il ne doit jamais parler directement à mem0.

## Stack actuelle

- API : FastAPI
- Backend MVP local : stockage fichier JSON
- Backend cible : Mem0 OSS + Qdrant + SQLite history
- Validation Mem0 locale : `mem0ai` + Qdrant en mode `path` + `fastembed`

Le backend actif est piloté par `MEMORY_BACKEND` :
- `file` : mode de démarrage simple, utile pour valider l’API et l’intégration Windows
- `mem0` : mode cible, utilisant `mem0ai`, Qdrant et SQLite history

## Mode mem0 valide localement

Une validation réelle a été faite localement avec :
- `MEMORY_BACKEND=mem0`
- `mem0ai`
- Qdrant local via `MEM0_QDRANT_PATH`
- `fastembed` pour les embeddings
- provider LLM `lmstudio` configuré uniquement pour satisfaire l’initialisation du SDK, avec `infer=False` sur `/remember`

Dans cette configuration :
- le service n’a pas besoin d’un serveur Qdrant séparé pour le test local
- `/remember`, `/search`, `/recent` et `/forget` fonctionnent réellement via `mem0`
- le backend stocke le texte brut reçu par l’API, ce qui correspond bien au contrat du bot Windows

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

### Variante mem0 locale validée

```bash
PYTHONPATH=.deps \
MEM0_API_KEY=xxxxxxxxxxxxxxxx \
MEMORY_BACKEND=mem0 \
MEM0_QDRANT_PATH=./data/qdrant \
MEM0_QDRANT_COLLECTION=mem0 \
MEM0_QDRANT_ON_DISK=true \
MEM0_HISTORY_DB_PATH=./data/history.db \
MEM0_LLM_PROVIDER=lmstudio \
MEM0_LLM_MODEL=dummy-local-model \
MEM0_LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1 \
MEM0_EMBEDDER_PROVIDER=fastembed \
MEM0_EMBEDDER_MODEL=BAAI/bge-small-en-v1.5 \
MEM0_EMBEDDER_DIMS=384 \
python3 -m uvicorn main:app --host 127.0.0.1 --port 8000
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
    "user_id": "twitch:streamer:viewer:alice",
    "text": "Le viewer préfère les amplis compacts.",
    "metadata": {
      "source": "twitch_chat",
      "channel": "streamer",
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
    "user_id": "twitch:streamer:viewer:alice",
    "query": "De quoi parlait-on à propos des amplis ?",
    "limit": 5
  }'
```

## Notes mem0 OSS

La documentation officielle mem0 OSS indique actuellement :
- installation Python via `pip install mem0ai`
- Qdrant comme vector store supporté
- SQLite history configurable via `history_db_path`

Le point pratique important observé ici :
- `mem0` initialise aussi le provider LLM au démarrage, même si `/remember` utilise `infer=False`
- pour un test local sans clé externe, `fastembed` + Qdrant local par `path` fonctionnent
- pour la prod, tu peux garder cette approche locale, ou remplacer le provider LLM/embedder par une pile distante explicitement choisie

## Déploiement

Des gabarits sont fournis dans :
- `deploy/systemd/mem0-api.service`
- `deploy/nginx/memory.example.net.conf`
- `deploy/DEPLOYMENT.md`

Recommendation pragmatique actuelle :
- demarrer en prod avec `MEMORY_BACKEND=mem0`
- utiliser Qdrant local par `MEM0_QDRANT_PATH`
- garder Nginx devant l'API avec TLS

La procedure detaillee est dans `deploy/DEPLOYMENT.md`.
