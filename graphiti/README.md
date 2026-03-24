# Graphiti V1 — Linux local-only

## Objet

Ce dossier prepare une V1 Graphiti locale sur le serveur Linux.

Objectif :
- experimentation offline
- aucun endpoint public
- aucun couplage runtime avec le bot Windows
- aucun impact sur `mem0-api`

Graphiti est traite ici comme une brique separee, derivee de mem0.

---

## Choix Technique Recommande

### Backend graphe

Choix V1 recommande :
- `graphiti-core[kuzu]`

Pourquoi :
- Kuzu est supporte nativement par Graphiti
- stockage local par fichier
- aucun daemon reseau supplementaire
- aucun port public
- bien aligne avec une phase locale/offline

Pourquoi ne pas choisir Neo4j/FalkorDB en V1 :
- ajout d'un service de base dedie
- plus de surface ops
- inutile pour une premiere phase d'experimentation locale

### Isolation

Choix recommande :
- environnement Python separe
- dossier dedie `graphiti/`
- data dediee sous `graphiti/data/`

Proposition :
- venv : `/home/vhserver/bt/.venv-graphiti`
- DB Kuzu : `/home/vhserver/bt/graphiti/data/graphiti.kuzu`

### LLM / embeddings

Graphiti requiert un LLM et un embedder pour l'ingestion.

Choix V1 recommande :
- installation locale de Graphiti d'abord
- ingestion offline ensuite seulement
- provider local recommande plus tard : Ollama via API OpenAI-compatible

Remarque :
- Graphiti par defaut vise OpenAI
- le projet indique explicitement un support Kuzu et un support Ollama local
- pour rester cohérent avec le cadrage "local-only", il vaut mieux eviter de rendre V1 dependante d'une API distante

---

## Installation Recommandee

### Requirements

Voir `graphiti/requirements.txt`.

Base proposee :
- `graphiti-core[kuzu]==0.28.2`

### Venv dediee

```bash
cd /home/vhserver/bt
python3 -m venv .venv-graphiti
source .venv-graphiti/bin/activate
pip install -r graphiti/requirements.txt
```

### Telemetry

Par prudence ops :

```bash
export GRAPHITI_TELEMETRY_ENABLED=false
```

---

## Variables D'Environnement V1

Voir `graphiti/.env.example`.

Variables recommandees :
- `GRAPHITI_TELEMETRY_ENABLED=false`
- `GRAPHITI_KUZU_DB_PATH=/home/vhserver/bt/graphiti/data/graphiti.kuzu`
- `GRAPHITI_WORKDIR=/home/vhserver/bt/graphiti`
- `GRAPHITI_IMPORT_DIR=/home/vhserver/bt/graphiti/imports`

Variables LLM locales a ajouter plus tard si ingestion activee :
- `GRAPHITI_LLM_BASE_URL`
- `GRAPHITI_LLM_MODEL`
- `GRAPHITI_EMBEDDING_BASE_URL`
- `GRAPHITI_EMBEDDING_MODEL`

---

## Topologie Linux Reelle

Graphiti V1 ne doit pas :
- ecouter publiquement
- etre reverse-proxy par Nginx
- partager un stockage avec mem0
- devenir une dependance de `mem0-api`

Topologie retenue :
- `mem0-api` reste inchange
- Graphiti s'execute en local seulement
- requetes/tests possibles seulement :
  - sur la machine Linux
  - ou via tunnel SSH plus tard si necessaire

---

## Pipeline D'Ingestion V1

Flux recommande :

1. exporter un viewer depuis mem0
2. produire un fichier intermediaire relisible
3. relire/filtrer manuellement
4. transformer en episodes Graphiti
5. ingerer dans Graphiti
6. journaliser ce qui a ete cree

La V1 ne doit pas envoyer brut toute la memoire mem0 vers Graphiti.

---

## Fichier Intermediaire Recommande

Format JSON simple, un fichier par viewer.

Exemple :

```json
{
  "user_id": "twitch:streamer:viewer:arthii_tv",
  "channel": "streamer",
  "viewer": "arthii_tv",
  "memories": [
    {
      "id": "mem_xxx",
      "memory": "Le viewer dit etre un builder sur Satisfactory.",
      "created_at": "2026-03-24T10:00:00Z",
      "metadata": {
        "source": "twitch_chat"
      }
    }
  ]
}
```

Ce format permet :
- stewarding manuel
- transformation deterministe
- audit facile

---

## Schema Minimal Recommande

### Nodes

- `Viewer`
- `Game`
- `Topic`

### Edges

- `PLAYS`
- `TALKS_ABOUT`
- `INTERACTS_WITH`

### Champs temporels

Quand possible :
- `first_seen_at`
- `last_seen_at`
- `valid_at`
- `invalid_at`

---

## Consultation Future

Une future couche Linux pourra proposer des helpers du type :
- `get_viewer_profile(viewer)`
- `get_viewer_topics(viewer)`
- `get_viewer_links(viewer)`
- `build_graph_prompt_context(viewer)`

Le but n'est pas d'envoyer le graphe brut au modele.
Le but est d'extraire un resume contextuel compact.

---

## Etat V1 Recommande

Le bon jalon V1 est :
- Graphiti installe localement
- DB Kuzu locale creee
- aucun port public
- import manuel d'un petit lot de viewers
- documentation claire du schema et du pipeline

Le bon jalon V2 seulement ensuite :
- requetes de consultation plus riches
- eventuel tunnel SSH
- usage indirect dans les prompts
