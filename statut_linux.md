# Statut Linux — mem0 API

## Role

Ce fichier est reserve au suivi operationnel de Codex Linux.

Il doit contenir :
- l'etat des taches Linux
- les validations runtime Linux
- les choix techniques Linux
- les prochains points a transmettre a Windows

Il ne doit pas dupliquer toute la source de verite du projet.

---

## Etat Actuel

Date de reference :
- 2026-03-24

Etat global Linux :
- service HTTP MVP implemente
- backend `file` valide en HTTP reelle
- backend `mem0` valide en HTTP reelle
- depot Git partage en place
- service `systemd` actif sur l'hote
- domaine public `https://memory.example.net/api/memory/health` operationnel
- routes admin locales `/admin/*` actives dans `mem0-api`
- listing viewers admin corrige via retrolecture Qdrant + registre local

Taches Linux :

| id | status | notes |
|---|---|---|
| L1 | DONE | API FastAPI conforme au contrat pour `/health`, `/search`, `/remember`, `/forget`, `/recent` |
| L2 | DONE | `mem0ai` + SQLite history + Qdrant local par `path` + `fastembed` valides localement puis en usage reel |
| L3 | DONE | `memory.example.net` sert maintenant le bon certificat TLS et route `/api/memory/` vers l'API |
| L4 | DONE | `systemd`, Nginx et notes de deploiement appliques; service durable actif |
| L5 | DONE | admin V1 integree au service principal; auth `X-Admin-Key`, acces via tunnel SSH, healthcheck valide |
| L6 | DONE | `/admin/users` retroalimente maintenant les viewers existants depuis le stockage Qdrant local |

---

## Validations Reelles

Backend `file` valide :
- `GET /health`
- `POST /remember`
- `POST /search`
- `POST /recent`
- `POST /forget`
- auth `X-API-Key`
- idempotence pratique cote backend fichier via `metadata.message_id`

Backend `mem0` valide :
- `mem0ai` instancie via `Memory.from_config(...)`
- Qdrant local valide via `MEM0_QDRANT_PATH`
- SQLite history valide via `MEM0_HISTORY_DB_PATH`
- embeddings locaux valides via `fastembed`
- API HTTP validee sur `/health`, `/remember`, `/search`, `/recent`, `/forget`
- domaine public valide sur `https://memory.example.net/api/memory/health`
- service durable valide via `mem0-api.service`
- admin locale validee :
  - `GET /admin/health`
  - `GET /admin/users`
  - `GET /admin/users/{user_id}/recent`
  - `DELETE /admin/users/{user_id}`
  - auth `X-Admin-Key`
  - refus des acces proxifies publics via `admin_local_only`

Point admin important observe :
- avec Qdrant local par `path`, un second process Python ne peut pas ouvrir le meme stockage
- l'admin V1 est donc integree dans `mem0-api` au lieu d'un service `admin-api` separe
- topologie reelle retenue pour Windows :
  - tunnel SSH `127.0.0.1:9000 -> 127.0.0.1:8000`
  - endpoints admin sous `/admin/*`

Correction viewer list admin :
- `GET /admin/users` etait initialement vide car `data/user_registry.json` n'etait pas retroalimente depuis les memoires plus anciennes
- correctif durable pousse :
  - lecture des `user_id` depuis `data/qdrant/collection/mem0/storage.sqlite`
  - repopulation automatique du registre local
- verification reelle faite :
  - 9 viewers existants remontent maintenant correctement via `/admin/users`

Point pratique observe :
- `mem0` initialise aussi le provider LLM au demarrage
- pour eviter une cle externe en validation locale, la config actuelle utilise `MEM0_LLM_PROVIDER=lmstudio` avec `infer=False` sur `/remember`

---

## Decision Technique Provisoire

Configuration Linux actuellement la mieux validee localement :
- `MEMORY_BACKEND=mem0`
- `MEM0_QDRANT_PATH=./data/qdrant`
- `MEM0_QDRANT_ON_DISK=true`
- `MEM0_HISTORY_DB_PATH=./data/history.db`
- `MEM0_EMBEDDER_PROVIDER=fastembed`
- `MEM0_EMBEDDER_MODEL=BAAI/bge-small-en-v1.5`
- `MEM0_EMBEDDER_DIMS=384`
- `MEM0_LLM_PROVIDER=lmstudio`
- `MEM0_LLM_MODEL=dummy-local-model`

Decision encore ouverte pour la prod :
- garder Qdrant local par `path`
- ou passer a un Qdrant dedie via `host/port` ou `url`

Decision admin V1 retenue :
- pas d'interface admin publique
- pas de service admin Linux separe tant que Qdrant reste en mode `path`
- routes admin montees dans `mem0-api`
- acces uniquement via tunnel SSH + `X-Admin-Key`

---

## Prochaines Actions Linux

- surveiller les premiers tests reels cote Windows
- accompagner les tests reels de l'UI admin Windows
- confirmer si Qdrant local par `path` est conserve tel quel pour la prod initiale
- eventuellement reduire les logs de telechargement/modeles apres stabilisation
- au prochain redemarrage `mem0-api`, le correctif code de retrolecture viewers depuis Qdrant sera charge en runtime de facon durable

---

## Infos A Transmettre A Windows

- le contrat HTTP est maintenant valide en bout en bout aussi en backend `mem0`
- Windows peut tester `memory-health` et `run-ollama` contre une API non theorique
- le routage public attendu est `https://memory.example.net/api/memory/...`
- l'admin V1 reelle utilise :
  - tunnel SSH vers `127.0.0.1:8000`
  - endpoints `/admin/*`
  - header `X-Admin-Key`
- `/admin/users` renvoie maintenant les viewers reels existants
- si Windows rencontre une erreur reelle sur `search` ou `remember`, il faut remonter :
  - code HTTP
  - body JSON
  - horodatage
  - payload simplifie envoye
