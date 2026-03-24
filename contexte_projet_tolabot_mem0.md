# Contexte Projet — Tolabot mem0

## Objet

Ce projet met en place une memoire distante pour le bot Twitch Windows.

Architecture retenue :
- bot principal sur PC Windows
- Ollama local sur Windows
- service memoire sur serveur Linux
- backend memoire via `mem0`

Le bot Windows ne doit jamais parler directement a `mem0`.
Il parle uniquement a l'API HTTP Linux.

---

## Depot Git

Depot partage :
- `git@github.com:Bakatora000/tolabot.git`

Fichiers de suivi :
- `pilotage_projet_mem0.md` : source de verite legere, etat global, handoffs
- `statut_linux.md` : suivi operationnel Linux
- `statut_windows.md` : suivi operationnel Windows

Code partage :
- `memory_service/` : service Linux
- `windows_bot/` : bot Twitch Windows
- `admin_interface_v1.md` : design V1 pour l'administration memoire via tunnel SSH
- `admin_api_contract_v1.md` : contrat de l'API admin locale Linux
- `context_codex_linux_graphiti.md` : cadrage du chantier Graphiti local/offline cote Linux
- `graphiti/` : base de travail Graphiti V1 Linux locale/offline

---

## Contrat Fonctionnel

Documents de reference :
- `contrat_api_bot_mem0.md`
- `context_codex_linux_mem0.md`
- `context_codex_windows.md`

Convention d'identite :
- `user_id = twitch:<channel_login>:viewer:<viewer_login>`

Exemple :
- `twitch:streamer:viewer:alice`

API publique attendue :
- `GET /api/memory/health`
- `POST /api/memory/search`
- `POST /api/memory/remember`
- `POST /api/memory/forget`
- `POST /api/memory/recent`

Auth :
- header `X-API-Key`

---

## Etat Actuel

### Linux

Etat actuel :
- API FastAPI implemente
- backend `file` valide
- backend `mem0` valide
- service `systemd` actif
- domaine public actif
- TLS valide
- Graphiti V1 locale validee jusqu'au pipeline offline

URL publique :
- `https://memory.example.net/api/memory`

Healthcheck public valide :
- `https://memory.example.net/api/memory/health`

Stack Linux actuellement en service :
- `mem0ai`
- Qdrant local via `MEM0_QDRANT_PATH`
- SQLite history via `MEM0_HISTORY_DB_PATH`
- embeddings `fastembed`
- provider LLM `lmstudio` pour satisfaire l'initialisation du SDK

Service durable :
- `mem0-api.service`

Graphiti V1 locale :
- `.venv-graphiti` validee
- `graphiti/data/graphiti.kuzu` initialise
- `graphiti/validate_local_kuzu.py` : OK
- export mem0 viewer -> JSON : OK
- import Graphiti `--dry-run` : OK
- reverse tunnel SSH Windows -> Linux vers Ollama : OK
- import Graphiti reel declenche via Ollama Windows : OK cote connectique
- compatibilite locale Graphiti/Kuzu corrigee dans l'importeur
- performance d'ingestion encore insuffisante avec `gemma:7b`, meme sur `--limit 1`
- Graphiti passe donc en veille pour la voie produit principale
- voie prioritaire retenue :
  - graphe metier maison
  - memoire source = `mem0`
  - extraction semantique = GPT
  - stockage = SQLite structuree
- premiere brique maison deja posee :
  - schema SQLite V1
  - initialisation DB
  - inspection DB
  - payload viewer pour extraction GPT
  - prompt GPT reproductible
  - merge GPT JSON -> SQLite
  - builder contexte viewer compact
  - endpoint admin local pour recuperer ce contexte
  - durcissement qualite du `text_block` pour reduire les cas `too_short` / `low_value` / `empty`
  - bootstrap heuristique local depuis exports mem0 pour alimenter rapidement certains viewers avant l'automatisation GPT complete

### Windows

Etat connu :
- client HTTP mem0 implemente
- lecture memoire distante branchee avant Ollama
- ecriture memoire distante branchee apres generation
- fallback local conserve
- validation reelle Windows mem0 deja observee contre l'API Linux
- code source Windows migre dans `windows_bot/`
- memoire hybride stabilisee :
  - `mem0` pour la memoire durable generale
  - memoire locale pour les fils courts specialises
- file FIFO globale bornee en place avec priorite streamer
- admin UI Windows validee en reel via tunnel SSH
- revue GPT offline viewer-par-viewer en place dans l'admin UI
- chantier futur Graphiti initialise cote documentation, avec deploiement Linux local/offline prevu
- Ollama Windows reste le meilleur candidat provider pour Graphiti, mais seulement en mode batch/opportuniste car le PC n'est pas allume en permanence
- Homegraph est maintenant la voie produit prioritaire pour un contexte viewer compact enrichissant le prompt du bot
- integration runtime Homegraph validee cote Windows via tunnel admin, avec ordre d'injection :
  - local specialise
  - homegraph
  - mem0
  - local general
- une voie de memoire ciblee reservee au streamer existe maintenant cote Windows pour injecter un fait durable sur un viewer cible directement dans mem0

---

## Fichiers Importants

### Service Linux

- `main.py`
- `memory_service/app.py`
- `memory_service/backend.py`
- `memory_service/config.py`
- `.env.example`
- `deploy/systemd/mem0-api.service`
- `deploy/nginx/memory.example.net.conf`
- `deploy/DEPLOYMENT.md`
- `graphiti/README.md`
- `graphiti/requirements.txt`
- `graphiti/.env.example`
- `graphiti/schema_minimal.md`
- `graphiti/validate_local_kuzu.py`
- `graphiti/export_viewer_memories.py`
- `graphiti/import_viewer_memories.py`

### Suivi Projet

- `pilotage_projet_mem0.md`
- `statut_linux.md`
- `statut_windows.md`

---

## Configuration Linux Retenue

Configuration actuellement validee :

```env
MEMORY_BACKEND=mem0
MEM0_HOST=127.0.0.1
MEM0_PORT=8000
MEM0_QDRANT_PATH=/home/vhserver/bt/data/qdrant
MEM0_QDRANT_COLLECTION=mem0
MEM0_QDRANT_ON_DISK=true
MEM0_HISTORY_DB_PATH=/home/vhserver/bt/data/history.db
MEM0_LLM_PROVIDER=lmstudio
MEM0_LLM_MODEL=dummy-local-model
MEM0_LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1
MEM0_EMBEDDER_PROVIDER=fastembed
MEM0_EMBEDDER_MODEL=BAAI/bge-small-en-v1.5
MEM0_EMBEDDER_DIMS=384
```

Note importante :
- `mem0` initialise aussi le provider LLM au demarrage
- `/remember` utilise `infer=False`
- le backend stocke donc le texte brut conforme au contrat du bot

---

## Incidents Techniques Deja Resolus

- absence initiale de service durable Linux
- certificat TLS incorrect sur `memory.example.net`
- mauvais routage public vers une page HTML AMP
- alignement corrige du routage public vers `/api/memory/...`
- chargement `.env` corrige cote Python
- unite `systemd` corrigee pour utiliser `/usr/bin/python3` et `PYTHONPATH=/home/vhserver/bt/.deps`

---

## Point De Vigilance

- Qdrant tourne actuellement en mode local par `path`
- c'est pragmatique et valide pour la prod initiale, mais pourra etre remplace plus tard par un service dedie si besoin

- `fastembed` peut telecharger son modele au premier lancement
- il faut garder cela en tete en cas de redeploiement ou de machine neuve

- la cle `MEM0_API_KEY` doit rester uniquement dans les fichiers `.env` locaux

---

## Prochaines Actions Probables

- surveiller les premiers usages reels cote Windows
- ajuster les logs si besoin
- confirmer si la config Qdrant locale est gardee telle quelle
- durcir eventuellement la config Nginx / systemd apres retour d'usage
- enrichir l'admin UI Windows (`search`, suppression unitaire, export/import)
- eventuellement historiser les commits de revue GPT
- reevaluer plus tard une action `merge` une fois le workflow stable
- deployer Graphiti localement cote Linux pour experimentation offline a partir des exports mem0
- definir ensuite le mode batch Linux -> Ollama Windows pour permettre un premier import Graphiti reel

---

## Resume Court

Le projet Tolabot mem0 est maintenant operationnel :
- bot Windows connecte a une API Linux distante
- memoire distante fonctionnelle en reel
- domaine public et TLS valides
- service Linux durable installe
- admin UI Windows fonctionnelle via tunnel SSH
- revue GPT offline avec validation admin et commit en lot disponible dans `windows_bot/`
- socle Graphiti Linux V1 valide jusqu'au pipeline offline
- Homegraph runtime maintenant consomme reellement par le bot Windows quand un `text_block` utile est disponible
- memoire ciblee streamer -> viewer cible validee en runtime cote Windows et verifiee via l'API admin mem0

Le repo partage contient maintenant le code, la doc, les statuts separes et le contexte necessaire pour reprendre le projet rapidement.
