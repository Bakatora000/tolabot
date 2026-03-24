# Deploiement Linux

## Strategie retenue

La configuration la plus pragmatique actuellement validee est :
- API FastAPI locale sur `127.0.0.1:8000`
- reverse proxy Nginx sur `memory.example.net`
- backend `mem0`
- Qdrant local par `MEM0_QDRANT_PATH`
- SQLite history locale par `MEM0_HISTORY_DB_PATH`
- embeddings `fastembed`

Cette approche evite un service Qdrant separe pour le premier deploiement.

## 1. Preparation du projet

```bash
cd /home/appuser/project
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Configurer ensuite `.env` au minimum :

```env
MEM0_API_KEY=change-me
MEM0_HOST=127.0.0.1
MEM0_PORT=8000
MEMORY_BACKEND=mem0
MEM0_QDRANT_PATH=/home/appuser/project/data/qdrant
MEM0_QDRANT_COLLECTION=mem0
MEM0_QDRANT_ON_DISK=true
MEM0_HISTORY_DB_PATH=/home/appuser/project/data/history.db
MEM0_LLM_PROVIDER=lmstudio
MEM0_LLM_MODEL=dummy-local-model
MEM0_LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1
MEM0_EMBEDDER_PROVIDER=fastembed
MEM0_EMBEDDER_MODEL=BAAI/bge-small-en-v1.5
MEM0_EMBEDDER_DIMS=384
```

## 2. Test local avant systemd

```bash
source /home/appuser/project/.venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8000
```

Puis :

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/remember \
  -H 'X-API-Key: change-me' \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"twitch:streamer:viewer:alice","text":"test","metadata":{"message_id":"deploy-check-001"}}'
```

## 3. Installation systemd

Copier l'unite :

```bash
sudo cp deploy/systemd/mem0-api.service /etc/systemd/system/mem0-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now mem0-api
sudo systemctl status mem0-api
```

Logs :

```bash
journalctl -u mem0-api -f
```

## 4. Installation Nginx

Copier la conf :

```bash
sudo cp deploy/nginx/memory.example.net.conf /etc/nginx/sites-available/memory.example.net.conf
sudo ln -s /etc/nginx/sites-available/memory.example.net.conf /etc/nginx/sites-enabled/memory.example.net.conf
sudo nginx -t
sudo systemctl reload nginx
```

## 5. Certificat TLS

Avec Certbot :

```bash
sudo mkdir -p /var/www/certbot
sudo certbot certonly --webroot -w /var/www/certbot -d memory.example.net
sudo nginx -t
sudo systemctl reload nginx
```

## 6. Validation publique

```bash
curl https://memory.example.net/api/memory/health
```

Puis depuis Windows :
- `py .\manage_bot.py memory-health`
- `py .\manage_bot.py run-ollama`

## Notes

- Si `fastembed` telecharge son modele au premier lancement, prevoir ce premier demarrage avant mise en prod.
- Si vous voulez isoler davantage la partie vectorielle plus tard, la config peut etre deplacee vers un Qdrant dedie via `MEM0_QDRANT_HOST` / `MEM0_QDRANT_PORT` ou `MEM0_QDRANT_URL`.
