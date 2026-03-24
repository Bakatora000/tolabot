# Pilotage Projet — Bot Windows ↔ mem0 Linux

## Mode d'emploi

Ce fichier sert de tableau de pilotage entre :
- Codex Windows
- Codex Linux
- l'utilisateur

Chaque intervenant doit :
- lire ce fichier au debut de sa session
- utiliser `statut_linux.md` pour le suivi operationnel Linux
- utiliser `statut_windows.md` pour le suivi operationnel Windows
- ne mettre ici que les decisions structurantes, l'etat global et les handoffs utiles
- ne pas supposer qu'une demande orale a ete vue par l'autre instance

---

## Source De Verite

Documents de reference :
- contrat API : `contrat_api_bot_mem0.md`
- contexte Linux : `context_codex_linux_mem0.md`
- contexte Windows : `context_codex_windows.md`
- contexte Graphiti Linux : `context_codex_linux_graphiti.md`
- depot Git partage : `git@github.com:Bakatora000/tolabot.git`
- suivi Linux : `statut_linux.md`
- suivi Windows : `statut_windows.md`

Convention d'identite figée :
- `user_id = twitch:<channel_login>:viewer:<viewer_login>`

Infra cible figée :
- domaine : `memory.example.net`
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

Etat courant synthetique :
- Linux : API HTTP validee en backend `file` et `mem0`, TLS/routage OK, service `systemd` actif
- Windows : client mem0 et branchements runtime en place, validation reelle faite contre l'API Linux, code partage versionne dans `windows_bot/`
- Linux : Graphiti V1 locale validee jusqu'au premier import reel via Ollama Windows batch; chantier maintenant mis en veille
- Linux : nouvelle voie prioritaire ouverte pour un graphe metier maison `mem0 + GPT + SQLite`

---

## Suivi Operationnel

Le detail des taches et validations a ete deplace vers :
- `statut_linux.md`
- `statut_windows.md`

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
- summary: contrat API et contexte Linux maintenant alignes; `user_id` par viewer et domaine `memory.example.net` figes
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
  - `deploy/nginx/memory.example.net.conf`
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

### 2026-03-23
- from: Codex Linux
- to: utilisateur / Codex Windows
- summary: validation runtime reelle terminee aussi en backend `mem0`; API testee en HTTP sur `/health`, `/remember`, `/search`, `/recent`, `/forget` avec `mem0ai`, SQLite history, Qdrant local par `path` et `fastembed`
- files:
  - `memory_service/backend.py`
  - `memory_service/config.py`
  - `.env.example`
  - `README.md`
  - `pilotage_projet_mem0.md`
- next_action:
  - Linux: choisir si la prod reste sur Qdrant local par `path` ou passe sur un service Qdrant dedie
  - Windows: peut continuer l'integration cliente sans attendre un backend theorique, le contrat HTTP et le backend mem0 etant maintenant verifies en bout en bout

### 2026-03-23
- from: Codex Linux
- to: utilisateur / Codex Windows
- summary: reorganisation du suivi pour limiter les conflits Git; le pilotage central reste leger et le suivi operationnel est separe entre `statut_linux.md` et `statut_windows.md`
- files:
  - `pilotage_projet_mem0.md`
  - `statut_linux.md`
  - `statut_windows.md`
- next_action:
  - Linux: ecrire principalement dans `statut_linux.md`
  - Windows: ecrire principalement dans `statut_windows.md`

### 2026-03-23
- from: Codex Linux
- to: utilisateur / Codex Windows
- summary: mise en service reelle terminee sur l'hote Linux; `mem0-api.service` actif, certificat TLS `memory.example.net` valide, routage public `/api/memory/` operationnel
- files:
  - `statut_linux.md`
  - `deploy/systemd/mem0-api.service`
  - `deploy/nginx/memory.example.net.conf`
- next_action:
  - Windows: poursuivre les tests reels du bot contre `https://memory.example.net/api/memory`
  - Linux: surveiller les erreurs remontant de Windows et ajuster seulement si necessaire

### 2026-03-24
- from: Codex Windows
- to: utilisateur / Codex Linux
- summary: code du bot Windows migre dans `windows_bot/` du depot partage; architecture hybride mem0 + memoire locale specialisee stabilisee; file FIFO globale bornee avec priorite streamer ajoutee
- files:
  - `windows_bot/`
  - `README.md`
  - `statut_windows.md`
- next_action:
  - Windows: continuer les tests reels de charge chat et ajuster TTL/file si necessaire
  - Linux: aucune action immediate requise hors suivi normal

### 2026-03-24
- from: Codex Windows
- to: utilisateur / Codex Linux
- summary: validation reelle admin V1 cote Windows terminee; tunnel SSH, auth admin, port local et reachability `/admin/health` fonctionnent en bout en bout. La suite est principalement UI/ergonomie cote Windows.
- files:
  - `windows_bot/admin_tunnel.py`
  - `windows_bot/admin_client.py`
  - `windows_bot/admin_ui.py`
  - `windows_bot/manage_bot.py`
  - `windows_bot/test_admin_client.py`
  - `windows_bot/test_admin_tunnel.py`
  - `statut_windows.md`
- next_action:
  - Windows: enrichir l'UI locale avec viewers cliquables, `recent`, `refresh`, `purge viewer`
  - Linux: aucune action immediate requise tant que les routes `/admin/*` restent stables

### 2026-03-24
- from: Codex Linux
- to: utilisateur / Codex Windows
- summary: phase Graphiti Linux V1 initialement structuree dans le repo; recommendation retenue a ce stade : `graphiti-core[kuzu]` dans une venv separee, local-only, sans exposition publique et avec pipeline d'ingestion offline depuis exports mem0.
- files:
  - `context_codex_linux_graphiti.md`
  - `graphiti/README.md`
  - `graphiti/requirements.txt`
  - `graphiti/.env.example`
  - `graphiti/schema_minimal.md`
  - `graphiti/export_format_viewer_memory.json`
- next_action:
  - Linux: valider l'installation locale de Graphiti dans une venv isolee
  - Linux: preparer un premier import offline test depuis un export mem0 viewer

### 2026-03-24
- from: Codex Linux
- to: utilisateur / Codex Windows
- summary: Graphiti Linux V1 a progresse jusqu'a une base technique reelle : `.venv-graphiti` validee, Kuzu local initialise, export mem0 viewer -> JSON valide, import Graphiti `--dry-run` valide. Le blocage restant est l'absence d'un provider LLM/embedder joignable depuis Linux pour faire l'import reel.
- files:
  - `graphiti/validate_local_kuzu.py`
  - `graphiti/export_viewer_memories.py`
  - `graphiti/import_viewer_memories.py`
  - `graphiti/README.md`
  - `graphiti/.env.example`
- next_action:
  - Linux: definir un mode batch robuste Linux -> Ollama Windows
  - Windows: aucune action immediate requise tant que ce mode batch n'est pas choisi

### 2026-03-24
- from: Codex Linux
- to: utilisateur / Codex Windows
- summary: architecture retenue pour Graphiti V1 reel : pas d'Ollama sur Linux. Le provider cible est Ollama sur Windows, joint depuis Linux uniquement via reverse tunnel SSH batch/opportuniste. Aucun couplage permanent ne doit etre introduit entre le serveur Linux et le PC Windows.
- files:
  - `graphiti/README.md`
  - `graphiti/ollama_windows_batch_mode.md`
  - `graphiti/.env.example`
- next_action:
  - Windows: preparer une session batch avec Ollama + reverse tunnel
  - Linux: verifier la reachability de `127.0.0.1:11434` puis lancer un premier import Graphiti reel

### 2026-03-24
- from: Codex Windows
- to: utilisateur / Codex Linux
- summary: le POC de revue GPT offline est maintenant fonctionnel cote Windows avec export compact, analyse OpenAI, severite reglable, validation admin visuelle et commit en lot. Les informations sensibles restent non versionnees; la doc partagee reste anonymisee.
- files:
  - `windows_bot/admin_ui.py`
  - `windows_bot/openai_review_client.py`
  - `windows_bot/bot_config.py`
  - `windows_bot/.env.example`
  - `windows_bot/README.md`
  - `statut_windows.md`
  - `contexte_projet_tolabot_mem0.md`
- next_action:
  - Windows: continuer l'ergonomie de l'admin UI si besoin (`search`, suppression unitaire, historique des commits)
  - Linux: aucune action immediate requise pour le POC review actuel

### 2026-03-24
- from: Codex Windows
- to: utilisateur / Codex Linux
- summary: nouveau chantier Graphiti cadre cote documentation. Objectif : deploiement local/offline sur le serveur Linux pour construire une couche graphe temporelle derivee de mem0, sans exposition publique et sans integration live immediate au bot.
- files:
  - `context_codex_linux_graphiti.md`
- next_action:
  - Linux: proposer et documenter le deploiement local de Graphiti, le schema minimal et le pipeline d'ingestion offline depuis mem0
  - Windows: aucune action immediate requise tant que le chantier reste cote Linux

---
