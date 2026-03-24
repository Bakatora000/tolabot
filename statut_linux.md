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
- socle Graphiti V1 valide localement en venv dediee avec Kuzu

Taches Linux :

| id | status | notes |
|---|---|---|
| L1 | DONE | API FastAPI conforme au contrat pour `/health`, `/search`, `/remember`, `/forget`, `/recent` |
| L2 | DONE | `mem0ai` + SQLite history + Qdrant local par `path` + `fastembed` valides localement puis en usage reel |
| L3 | DONE | `memory.example.net` sert maintenant le bon certificat TLS et route `/api/memory/` vers l'API |
| L4 | DONE | `systemd`, Nginx et notes de deploiement appliques; service durable actif |
| L5 | DONE | admin V1 integree au service principal; auth `X-Admin-Key`, acces via tunnel SSH, healthcheck valide |
| L6 | DONE | `/admin/users` retroalimente maintenant les viewers existants depuis le stockage Qdrant local |
| G1 | DONE | cadrage Graphiti V1 pose dans le repo avec choix `graphiti-core[kuzu]`, schema minimal et pipeline offline |
| G2 | DONE | installation Graphiti validee localement dans `.venv-graphiti`; base Kuzu locale initialisee |
| G3 | DONE | export mem0 viewer -> JSON et import Graphiti `--dry-run` valides |
| G4 | DONE | provider batch Linux -> Ollama Windows valide via reverse tunnel SSH; import Graphiti reel demarre avec Kuzu |
| G5 | STANDBY | compatibilite Graphiti/Kuzu corrigee, mais ingestion trop lente avec `gemma:7b`; chantier mis en veille |
| H1 | DONE | cadrage du graphe metier maison base sur `mem0 + GPT + SQLite` |
| H2 | DONE | schema SQLite V1 et scripts Linux minimaux poses dans `homegraph/` |
| H3 | DONE | pipeline maison `mem0 export -> payload GPT` amorce |
| H4 | DONE | merge initial `GPT JSON -> SQLite` implemente avec traçabilite `graph_jobs` |
| H5 | DONE | builder `SQLite -> prompt context` implemente avec contrat V1 fige |
| H6 | DONE | endpoint admin local `GET /admin/homegraph/users/{user_id}/context` ajoute cote Linux |
| H7 | DONE | qualite du `text_block` Homegraph durcie pour eviter placeholders et blocs trop pauvres |
| H8 | DONE | workflow reproductible `mem0 -> payload -> prompt GPT -> merge -> context` documente et outille |

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
  - `GET /admin/homegraph/users/{user_id}/context`
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

Graphiti V1 valide localement :
- `.venv-graphiti` creee et dependencies installees
- `python graphiti/validate_local_kuzu.py` : OK
- `graphiti/data/graphiti.kuzu` creee
- `python graphiti/export_viewer_memories.py twitch:expevay:viewer:arthii_tv` : OK
- `python graphiti/import_viewer_memories.py graphiti/imports/arthii_tv.json --dry-run` : OK
- reverse tunnel SSH Windows -> Linux valide :
  - Linux atteint `127.0.0.1:11434`
  - `curl /api/tags` et `/v1/models` : OK
  - Ollama Windows traite bien `gemma:7b` et `nomic-embed-text:latest`
- import Graphiti reel lance avec succes jusqu'aux phases LLM/embedding

Corrections Graphiti/Kuzu appliquees localement :
- normalisation stable `user_id -> group_id` pour respecter les contraintes Graphiti
- contournement local du bug `KuzuDriver._database` attendu par `Graphiti.add_episode()`
- creation explicite des index full-text Kuzu attendus par Graphiti
- instrumentation ajoutee dans l'importeur :
  - `import_start`
  - `episode_start`
  - `episode_ok`
  - `import_ok`

Point Graphiti critique observe maintenant :
- le pipeline reel est branche bout en bout
- mais l'ingestion reste trop lente avec `gemma:7b`, y compris sur `--limit 1`
- le prochain travail n'est plus la connectivite mais le benchmarking/choix du modele d'ingestion et l'amelioration de l'observabilite

Decision prise ensuite :
- Graphiti passe en veille pour la voie produit principale
- la priorite bascule vers un graphe metier maison plus simple et plus controlable
- architecture cible :
  - source : `mem0`
  - extraction : GPT
  - stockage : SQLite
  - restitution : contexte viewer compact pour le prompt du bot

Decision Graphiti actuelle :
- pas d'installation d'Ollama sur le serveur Linux
- le provider cible pour l'ingestion Graphiti reste plutot Ollama sur le PC Windows
- comme le PC Windows n'est pas allume en permanence, ce provider doit etre traite comme opportuniste/batch, pas comme une dependance permanente Linux
- mode recommande :
  - reverse tunnel SSH Windows -> Linux
  - port local Linux `127.0.0.1:11434`
  - usage uniquement pendant les sessions d'import Graphiti

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
- definir le mode d'acces Linux -> Ollama Windows le plus robuste pour les imports Graphiti batch
- benchmarker au moins un modele plus leger ou plus adapte pour l'ingestion Graphiti
- nettoyer le bruit de logs Kuzu `index already exists` si le workflow est conserve
- relancer un import Graphiti court instrumente (`--limit 1`) avec un modele alternatif
- definir le schema SQLite du graphe metier maison
- definir le format JSON d'extraction GPT pour les faits viewer
- preparer un premier pipeline `mem0 -> GPT -> SQLite`
- implementer le mergeur `GPT JSON -> SQLite`
- definir ensuite le builder `SQLite -> prompt context`
- definir le prompt GPT de production
- implementer le builder `SQLite -> prompt context`
- transmettre a Windows le contrat V1 du contexte viewer compact
- brancher ensuite une nouvelle source de contexte cote bot Windows
- redemarrer `mem0-api` sur l'hote pour charger le nouvel endpoint admin Homegraph
- surveiller les retours Windows sur la qualite reelle du `text_block`
- automatiser si besoin l'appel GPT pour eviter l'etape manuelle

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
- Graphiti cote Linux a atteint :
  - venv dediee validee
  - Kuzu local valide
  - export viewer mem0 valide
  - import `--dry-run` valide
  - reverse tunnel Windows -> Linux valide
  - Ollama Windows vu depuis Linux
  - import reel demarre
- blocage restant Graphiti :
  - performance d'ingestion insuffisante avec `gemma:7b`
- nouvelle direction prioritaire :
  - graphe metier maison
  - doc de cadrage : `graphe_metier_maison_v1.md`
  - socle technique Linux : `homegraph/`
  - endpoint admin local : `GET /admin/homegraph/users/{user_id}/context`
  - mergeur initial : `homegraph/merge_extraction.py`
  - builder contexte compact : `homegraph/build_viewer_context.py`
- si Windows rencontre une erreur reelle sur `search` ou `remember`, il faut remonter :
  - code HTTP
  - body JSON
  - horodatage
  - payload simplifie envoye
