# Pilotage Projet — Bot Windows ↔ mem0 Linux

## Mode d'emploi

Ce fichier sert de tableau de pilotage entre :
- Codex Windows
- Codex Linux
- l'utilisateur

Chaque intervenant doit :
- lire ce fichier au debut de sa session
- mettre a jour uniquement les sections utiles
- laisser des statuts explicites
- ne pas supposer qu'une demande orale a ete vue par l'autre instance

Statuts autorises :
- `TODO`
- `IN_PROGRESS`
- `BLOCKED`
- `REVIEW`
- `DONE`

Colonnes a maintenir :
- `owner`
- `status`
- `depends_on`
- `last_update`

Regle de base :
- si une tache depend d'un autre chantier, elle passe en `BLOCKED`
- si une tache est terminee mais attend validation ou integration, elle passe en `REVIEW`
- quand une tache est terminee et ne demande plus rien, elle passe en `DONE`

---

## Source De Verite

Documents de reference :
- contrat API : `contrat_api_bot_mem0.md`
- contexte Linux : `context_codex_linux_mem0.md`
- contexte Windows : `context_codex_windows.md`
- depot Git partage : `git@github.com:Bakatora000/tolabot.git`

Convention d'identite figée :
- `user_id = twitch:<channel_login>:viewer:<viewer_login>`

Infra cible figée :
- domaine : `olala.expevay.net`
- backend memoire : `Mem0 OSS + Qdrant + SQLite history`
- bot principal : Windows
- Ollama : Windows local
- service memoire : Linux

---

## Etat Global

Objectif courant :
- mettre en place un backend memoire mem0 sur Linux
- brancher ensuite le bot Windows sur cette API

Decision produit :
- quand mem0 est active et stable, elle devient la memoire principale
- la memoire locale JSON reste seulement un fallback de secours

---

## Taches

| id | task | owner | status | depends_on | last_update | notes |
|---|---|---|---|---|---|---|
| L1 | Concevoir le service HTTP Linux conforme au contrat API | Codex Linux | DONE | none | 2026-03-23 | MVP FastAPI code en place et valide en execution locale sur backend `file` pour `/health`, `/search`, `/remember`, `/forget`, `/recent`. |
| L2 | Choisir et configurer l'integration mem0 + Qdrant + SQLite history | Codex Linux | IN_PROGRESS | L1 | 2026-03-23 | Abstraction backend et configuration mem0 posees. Validation reelle mem0/Qdrant encore a faire sur environnement installe. |
| L3 | Preparer l'exposition HTTPS sur `olala.expevay.net` | Codex Linux | REVIEW | L1 | 2026-03-23 | Gabarit Nginx fourni. Certificat TLS et mise en service restent a appliquer sur l'hote cible. |
| L4 | Fournir procedure de deploiement Linux (`systemd`, config, reverse proxy) | Codex Linux | REVIEW | L1,L2,L3 | 2026-03-23 | `README.md`, `.env.example`, unite `systemd` et gabarit Nginx ajoutes. Validation runtime encore necessaire. |
| W1 | Preparer le client HTTP mem0 cote Windows | Codex Windows | REVIEW | L1 | 2026-03-23 | `memory_client.py` cree dans le depot Windows courant, config mem0 ajoutee a `bot_config.py`, diagnostic `memory-health` ajoute a `manage_bot.py`, `.env.example` et `README.md` mis a jour. En attente d'integration runtime. |
| W2 | Integrer la lecture memoire distante avant Ollama | Codex Windows | REVIEW | W1,L1 | 2026-03-23 | Lecture mem0 branchee avant `ask_ollama(...)` avec fallback local si mem0 indisponible ou desactive |
| W3 | Integrer l'ecriture memoire distante apres generation | Codex Windows | REVIEW | W1,L1 | 2026-03-23 | Ecriture mem0 branchee pour tours utiles et indices partiels, sans bloquer la reponse Twitch si l'API echoue |
| W4 | Mettre a jour `.env.example`, `README.md`, tests | Codex Windows | REVIEW | W1,W2,W3 | 2026-03-23 | `.env.example`, `README.md`, `test_memory_client.py` et `test_bot_runtime.py` mis a jour; validation reelle encore attendue |

---

## Blocages

Utiliser cette section seulement pour des blocages reels.

Format :
- `date` - `owner` - `blocker` - `action attendue`

Aucun pour l'instant.

---

## Handoffs

Format obligatoire :
- `date`
- `from`
- `to`
- `summary`
- `files`
- `next_action`

### 2026-03-23
- from: utilisateur
- to: Codex Linux
- summary: lecture du contexte Linux et du contrat API revise
- files:
  - `contrat_api_bot_mem0.md`
  - `context_codex_linux_mem0.md`
- next_action:
  - analyser et proposer l'implementation du service Linux

### 2026-03-23
- from: Codex Windows
- to: Codex Linux
- summary: contrat API et contexte Linux maintenant alignes; `user_id` par viewer et domaine `olala.expevay.net` figes
- files:
  - `contrat_api_bot_mem0.md`
  - `context_codex_linux_mem0.md`
- next_action:
  - demarrer l'implementation du service memoire Linux

### 2026-03-23
- from: Codex Linux
- to: utilisateur / Codex Windows
- summary: lecture du contexte validee; comprehension correcte de la separation Windows/Linux et des points d'integration cote bot Windows
- files:
  - `contrat_api_bot_mem0.md`
  - `context_codex_linux_mem0.md`
  - archive du bot Windows
- next_action:
  - Linux: construire le MVP du service HTTP conforme au contrat avec `GET /health`, `POST /search`, `POST /remember`
  - Windows: attendre la materialisation du service ou la confirmation du schema final implemente

### 2026-03-23
- from: Codex Linux
- to: utilisateur / Codex Windows
- summary: MVP Linux cree dans ce workspace avec API FastAPI conforme au contrat, auth `X-API-Key`, backend fichier fonctionnel pour dev local, et squelette backend mem0 configurable
- files:
  - `main.py`
  - `memory_service/app.py`
  - `memory_service/backend.py`
  - `memory_service/config.py`
  - `memory_service/models.py`
  - `.env.example`
  - `README.md`
  - `deploy/systemd/mem0-api.service`
  - `deploy/nginx/olala.expevay.net.conf`
- next_action:
  - Linux: valider en execution reelle les endpoints HTTP puis brancher/ajuster mem0 + Qdrant sur environnement installe
  - Windows: peut commencer a cibler le contrat stabilise des endpoints et la config `MEM0_API_BASE_URL` / `MEM0_API_KEY`

### 2026-03-23
- from: Codex Linux
- to: utilisateur / Codex Windows
- summary: depot GitHub partage initialise et pousse sur `main`; le fichier de pilotage peut maintenant servir de support commun entre les deux environnements
- files:
  - `pilotage_projet_mem0.md`
- next_action:
  - Linux: continuer la validation runtime du service memoire
  - Windows: cloner ou synchroniser `tolabot`, puis faire les mises a jour de suivi directement dans le depot partage

### 2026-03-23
- from: Codex Linux
- to: utilisateur / Codex Windows
- summary: validation runtime locale terminee en backend `file`; endpoints principaux conformes au contrat observes en HTTP reelle avec auth `X-API-Key` et idempotence `message_id`
- files:
  - `memory_service/app.py`
  - `memory_service/backend.py`
  - `pilotage_projet_mem0.md`
- next_action:
  - Linux: passer a la validation de l'integration reelle `mem0` + Qdrant
  - Windows: peut commencer l'integration cliente contre le contrat deja valide en mode HTTP

### 2026-03-23
- from: Codex Windows
- to: utilisateur / Codex Linux
- summary: W1 cote Windows est implemente dans le depot du bot existant; client HTTP mem0, config `.env`, diagnostic `memory-health` et test unitaire dedie sont prets. L'integration dans le runtime Twitch/Ollama n'est pas encore branchee.
- files:
  - `C:\Users\xuanp\BotTwitch\memory_client.py`
  - `C:\Users\xuanp\BotTwitch\bot_config.py`
  - `C:\Users\xuanp\BotTwitch\manage_bot.py`
  - `C:\Users\xuanp\BotTwitch\.env.example`
  - `C:\Users\xuanp\BotTwitch\README.md`
  - `C:\Users\xuanp\BotTwitch\test_memory_client.py`
- next_action:
  - Windows: brancher la lecture memoire distante avant l'appel Ollama
  - Windows: brancher l'ecriture memoire distante apres la reponse
  - Linux: poursuivre la validation runtime reelle du service et de l'integration mem0/Qdrant

### 2026-03-23
- from: Codex Windows
- to: utilisateur / Codex Linux
- summary: lecture et ecriture mem0 sont maintenant branchees dans le runtime du bot Windows. Le fallback local reste actif pour ne pas casser les fils de charade et la tolerance aux pannes. Validation reelle contre l'API Linux encore necessaire.
- files:
  - `C:\Users\xuanp\BotTwitch\bot_ollama.py`
  - `C:\Users\xuanp\BotTwitch\test_bot_runtime.py`
- next_action:
  - Windows: tester `memory-health` puis un echange reel avec `MEM0_ENABLED=true`
  - Linux: valider le service en execution reelle, surtout `POST /search` et `POST /remember`

---

## Regles De Mise A Jour

Quand Codex Linux termine une etape :
- mettre la tache en `REVIEW` ou `DONE`
- ajouter un handoff
- citer les fichiers crees/modifies

Quand Codex Windows termine une etape :
- meme regle

Quand l'utilisateur tranche une decision :
- l'ajouter dans `Source De Verite` si elle est structurelle

---

## File De Validation

Utiliser cette section pour les points qui doivent etre relus avant integration.

- API Linux conforme au contrat
- convention `user_id` par viewer respectee partout
- auth `X-API-Key` coherente
- timeout et fallback propres cote Windows
- HTTPS valide sur `olala.expevay.net`
