# Graphe Metier Maison V1

## But

Construire une couche de connaissance simple et controlable au-dessus de `mem0`, sans dependre de Graphiti pour la valeur produit principale.

Objectif :
- mieux resumer chaque viewer
- structurer les faits utiles au bot
- enrichir les prompts envoyes a Ollama
- garder une edition humaine simple via l'admin UI Windows

Cette V1 remplace le besoin produit principal de Graphiti.
Graphiti reste un chantier de labo, non prioritaire.

---

## Principe

Source de verite amont :
- `mem0`

Extraction semantique :
- GPT, en batch ou a la demande

Stockage cible :
- structure maison simple, versionnable et editable

Sortie produit :
- un contexte viewer propre et compact pour le prompt du bot

---

## Pourquoi Ce Choix

Avantages par rapport a Graphiti :
- schema metier explicite
- pas de magie interne opaque
- moins de dependances
- debuggage plus simple
- edition manuelle plus simple
- evolution produit plus rapide

Compromis :
- il faut definir nous-memes le schema et les regles de fusion
- il n'y a pas de moteur temporel generique pret a l'emploi

---

## Entites V1

On ne cherche pas un graphe universel.
On cherche un graphe utile pour le bot.

Entites minimales :
- `viewer`
- `game`
- `topic`
- `preference`
- `fact`
- `relation`

---

## Schema V1

### Viewer

Champs :
- `viewer_id`
- `channel`
- `viewer_login`
- `display_name`
- `summary_short`
- `summary_long`
- `last_updated_at`

### Game

Champs :
- `game_id`
- `name`
- `aliases`

### Topic

Champs :
- `topic_id`
- `name`
- `aliases`

### Fact

Champs :
- `fact_id`
- `viewer_id`
- `kind`
- `value`
- `confidence`
- `status`
- `valid_from`
- `valid_to`
- `source_memory_ids`
- `source_excerpt`
- `last_reviewed_at`
- `review_state`

Exemples de `kind` :
- `plays_game`
- `likes_game`
- `dislikes_game`
- `plays_role`
- `build_style`
- `personality_trait`
- `recurring_topic`
- `social_relation`
- `stream_context`

Exemples de `status` :
- `active`
- `uncertain`
- `obsolete`
- `contradicted`

Exemples de `review_state` :
- `auto`
- `human_validated`
- `human_edited`
- `rejected`

### Relation

Champs :
- `relation_id`
- `viewer_id`
- `target_type`
- `target_id_or_value`
- `relation_type`
- `confidence`
- `valid_from`
- `valid_to`
- `source_memory_ids`

Exemples :
- `viewer -> game : plays`
- `viewer -> topic : likes`
- `viewer -> viewer : knows`

---

## Stockage Recommande V1

Choix recommande :
- SQLite locale cote Linux

Pourquoi :
- simple
- robuste
- editable
- portable
- facile a sauvegarder/exporter

Tables minimales :
- `viewer_profiles`
- `viewer_facts`
- `viewer_relations`
- `graph_jobs`
- `graph_job_items`

On peut ensuite exporter en JSON pour l'UI Windows si besoin.

---

## Pipeline V1

### Etape 1

Recuperer les souvenirs mem0 d'un viewer :
- `recent`
- `search`
- export complet viewer

### Etape 2

Construire un paquet d'analyse :
- `viewer_id`
- liste de souvenirs
- metadonnees utiles

### Etape 3

Envoyer a GPT une consigne stricte :
- extraire uniquement des faits utiles
- produire un JSON valide
- ne pas inventer
- annoter la confiance
- signaler les conflits

### Etape 4

Appliquer une logique de fusion maison :
- creation si nouveau fait
- mise a jour si fait existant proche
- contradiction si conflit
- expiration si ancien fait remplace

### Etape 5

Produire un resume exploitable par le bot :
- top jeux
- top sujets
- preferences fortes
- faits prudents
- contexte recent utile

---

## Format GPT Attendu

Format cible propose :

```json
{
  "viewer_id": "twitch:streamer:viewer:alice",
  "summary_short": "Viewer regulier, parle souvent de jeux de construction et prefere les approches optimisees.",
  "facts": [
    {
      "kind": "plays_game",
      "value": "Satisfactory",
      "confidence": 0.9,
      "status": "active",
      "source_memory_ids": ["mem_a", "mem_b"]
    },
    {
      "kind": "build_style",
      "value": "prefere les usines efficaces",
      "confidence": 0.78,
      "status": "active",
      "source_memory_ids": ["mem_c"]
    }
  ],
  "relations": [
    {
      "target_type": "game",
      "target_id_or_value": "Satisfactory",
      "relation_type": "plays",
      "confidence": 0.9,
      "source_memory_ids": ["mem_a", "mem_b"]
    }
  ],
  "conflicts": [],
  "needs_human_review": []
}
```

---

## Regles Produit Importantes

- ne jamais presenter un fait faible comme une certitude
- garder les faits contradictoires visibles plutot que les ecraser aveuglement
- toujours garder la trace des `source_memory_ids`
- permettre une validation humaine depuis l'admin UI
- preferer peu de faits utiles plutot qu'un gros graphe bruite

---

## Prompt Bot Cible

Le bot n'a pas besoin du graphe brut.
Il a besoin d'un contexte compact.

Exemple de bloc injecte au prompt :

```text
Contexte viewer:
- viewer regulier, ton amical
- joue souvent a Satisfactory
- prefere les builds efficaces
- parle souvent d'automatisation
- confiance faible sur : relation avec tel autre viewer
```

La V1 doit donc produire surtout :
- `summary_short`
- `facts_high_confidence`
- `recent_context`
- `uncertain_points`

---

## Admin UI V1

L'admin Windows pourra a terme :
- lister les viewers
- voir le profil structure
- valider / editer / rejeter un fait
- marquer un fait comme obsolete
- relancer une extraction GPT pour un viewer
- exporter un profil viewer en JSON

---

## Plan De Mise En Oeuvre

### M1

Definir le schema SQLite V1

Etat :
- fait
- implementation initiale dans `homegraph/schema.py`
- initialisation via `homegraph/init_db.py`

### M2

Ajouter un export viewer `mem0 -> payload GPT`

Etat :
- version initiale disponible dans `homegraph/build_viewer_payload.py`

### M3

Ajouter un extracteur `GPT -> JSON structure`

### M4

Ajouter un mergeur `JSON -> SQLite`

### M5

Ajouter un builder `SQLite -> prompt context`

### M6

Ajouter la visualisation/edition minimale dans l'admin UI Windows

---

## Statut

Decision actuelle :
- Graphiti passe en veille
- la voie prioritaire devient un graphe metier maison
- source memoire = `mem0`
- extraction semantique = GPT
- stockage structure = SQLite maison
