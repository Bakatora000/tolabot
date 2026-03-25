# Tolabot

Bot Twitch francophone avec memoire contextuelle, recherche web selective, interface d'administration locale et trajectoire vers une memoire plus structuree.

Le projet ne se resume pas a `mem0`.
`mem0` est seulement un composant de la memoire longue actuelle.

Aujourd'hui, Tolabot est organise autour de deux ensembles :
- `windows_bot/` : le runtime principal du bot sur Windows
- `memory_service/` : le service memoire/admin sur Linux

---

## Vue d'ensemble

Tolabot vise a :
- repondre naturellement dans le chat Twitch
- garder un contexte recent borne
- reutiliser une memoire durable cross-live
- enrichir certaines reponses avec du web quand c'est pertinent
- fournir une UI admin locale pour inspecter et nettoyer la memoire
- converger a terme vers un bot plus contextuel, plus temporel, et potentiellement plus autonome

En pratique, le runtime Windows combine deja :
- Ollama local pour la generation
- memoire courte locale
- graphe conversationnel local
- faits locaux structures
- `homegraph` pour un contexte viewer compact
- `mem0` pour la memoire durable generale
- SearXNG pour les questions externes ou recentes

---

## Composants Principaux

### `windows_bot/`

Runtime principal du bot Twitch.

Responsabilites actuelles :
- reception des messages Twitch
- arbitrage initial
- collecte du contexte local et distant
- recherche web selective
- composition du prompt
- appel a Ollama
- memorisation post-reponse
- UI admin locale Windows

Modules notables :
- `bot_ollama.py` : orchestrateur runtime
- `arbitrator.py` : premieres decisions explicites du bot
- `decision_tree.py` + `decision_tree.json` : couche declarative pour certains triggers et routages
- `conversation_graph.py` : memoire conversationnelle locale
- `facts_memory.py` : faits locaux structures
- `context_sources.py` : representation unifiee des sources de contexte
- `prompt_composer.py` : composition explicite du prompt
- `admin_ui.py` : interface admin locale

### `memory_service/`

Service Linux expose publiquement pour la memoire distante.

Responsabilites actuelles :
- API memoire publique du bot
- API admin locale accessible via tunnel SSH
- backend `mem0` avec Qdrant local + SQLite history
- listing / export / purge / recherche de memoires
- exposition du contexte `homegraph` au bot Windows

Routes publiques principales :
- `GET /api/memory/health`
- `POST /api/memory/search`
- `POST /api/memory/remember`
- `POST /api/memory/forget`
- `POST /api/memory/recent`

Routes admin locales principales :
- `GET /admin/health`
- `GET /admin/users`
- `GET /admin/users/{user_id}/recent`
- `DELETE /admin/users/{user_id}`
- `GET /admin/homegraph/users/{user_id}/context`

### `homegraph/`

Voie produit actuelle pour enrichir le prompt avec un contexte viewer compact.

Pipeline vise :
- source : `mem0`
- extraction : GPT
- stockage : SQLite
- restitution : `text_block` viewer compact

Etat actuel :
- pipeline Linux en place
- endpoint admin expose au bot Windows
- alimentation encore progressive viewer-par-viewer

### `graphiti/`

Piste experimentale mise en veille pour la voie produit principale.

Pourquoi :
- chaine technique validee
- mais ingestion trop lourde/lente dans la forme actuelle

Le repo conserve cette piste comme laboratoire, pas comme composant prioritaire du produit.

---

## Flux Principal

1. Un viewer mentionne `@anneaunimouss` sur Twitch.
2. `windows_bot` normalise l'evenement et arbitre.
3. Le runtime collecte le contexte utile :
- memoire locale specialisee
- conversation graph local
- faits locaux
- `homegraph`
- `mem0`
- web via SearXNG si necessaire
4. Le prompt est compose puis envoye a Ollama sur Windows.
5. La reponse est post-traitee puis envoyee dans le chat.
6. Les memoires utiles sont mises a jour localement et/ou a distance.

---

## Etat Produit Actuel

Ce qui est deja reellement en place :
- bot Windows operationnel
- Ollama local en usage reel
- memoire distante `mem0` validee en bout en bout
- admin UI Windows via tunnel SSH
- recherche web selective via SearXNG
- `homegraph` consomme en runtime comme source de contexte supplementaire
- debut de refacto Windows vers une architecture plus modulaire :
  - `runtime_types`
  - `arbitrator`
  - `context_sources`
  - `prompt_composer`

Direction architecture actuelle :
- garder `bot_ollama.py` comme orchestrateur
- sortir progressivement l'arbitrage et la composition hors du monolithe runtime
- preparer une trajectoire vers un futur package unifie type `tolabot.exe`

---

## Structure Du Repo

- `windows_bot/` : bot Twitch Windows, admin UI, arbitrage, memoire locale
- `memory_service/` : service memoire/admin Linux
- `homegraph/` : graphe metier maison pour le contexte viewer
- `graphiti/` : chantier experimental mis en veille
- `deploy/` : gabarits systemd / Nginx / deploiement Linux
- `architecture_active.txt` : photographie de l'architecture actuellement en service
- `architecture_target_vnext.md` : cible de refacto pour le bot plus contextuel / temporel
- `admin_api_contract_v1.md` : contrat admin local
- `admin_interface_v1.md` : cadrage de l'UI admin Windows

---

## Documentation A Lire En Priorite

Pour comprendre le produit global :
- `architecture_active.txt`
- `architecture_target_vnext.md`
- `contexte_projet_tolabot_mem0.md`

Pour le runtime Windows :
- `windows_bot/README.md`
- `statut_windows.md`

Pour la memoire Linux :
- `deploy/DEPLOYMENT.md`
- `statut_linux.md`
- `admin_api_contract_v1.md`

Pour `homegraph` :
- `graphe_metier_maison_v1.md`
- `homegraph/README.md`
- `homegraph/workflow_v1.md`

---

## Demarrage Rapide

### Bot Windows

Voir :
- `windows_bot/README.md`

En bref :
- config `.env`
- Ollama local
- `py .\manage_bot.py run-ollama`

### Service memoire Linux

En bref :
- `cp .env.example .env`
- regler `MEM0_API_KEY`
- lancer `uvicorn main:app --host 127.0.0.1 --port 8000`

La procedure de deploiement durable est documentee dans :
- `deploy/DEPLOYMENT.md`

---

## Cap Long Terme

Le but n'est pas seulement un bot qui repond.

Le but est un systeme qui sait :
- percevoir
- arbitrer
- selectionner le bon contexte
- reutiliser une memoire durable
- tenir compte du temps
- et plus tard intervenir spontanement avec des garde-fous stricts

La cible d'architecture pour cette evolution est documentee ici :
- `architecture_target_vnext.md`
