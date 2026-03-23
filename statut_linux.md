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
- 2026-03-23

Etat global Linux :
- service HTTP MVP implemente
- backend `file` valide en HTTP reelle
- backend `mem0` valide en HTTP reelle
- depot Git partage en place

Taches Linux :

| id | status | notes |
|---|---|---|
| L1 | DONE | API FastAPI conforme au contrat pour `/health`, `/search`, `/remember`, `/forget`, `/recent` |
| L2 | REVIEW | `mem0ai` + SQLite history + Qdrant local par `path` + `fastembed` valides localement |
| L3 | REVIEW | gabarit Nginx TLS pret, HTTPS non applique sur l'hote cible |
| L4 | REVIEW | docs, `.env.example`, `systemd` et notes de deploiement ajoutes puis raffines pour la prod |

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

---

## Prochaines Actions Linux

- appliquer la mise en service reelle derriere `olala.expevay.net`
- valider reverse proxy + TLS + service durable
- confirmer si Qdrant local par `path` est conserve pour la prod initiale

---

## Infos A Transmettre A Windows

- le contrat HTTP est maintenant valide en bout en bout aussi en backend `mem0`
- Windows peut tester `memory-health` et `run-ollama` contre une API non theorique
- le routage public attendu est `https://olala.expevay.net/api/memory/...`
- si Windows rencontre une erreur reelle sur `search` ou `remember`, il faut remonter :
  - code HTTP
  - body JSON
  - horodatage
  - payload simplifie envoye
