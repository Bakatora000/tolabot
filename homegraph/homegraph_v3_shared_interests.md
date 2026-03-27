# Homegraph V3 — Liens Partages Et Proximite Inter-Viewers

## Objet

Cette V3 prolonge `homegraph v2` pour mieux relier les graphes viewers entre eux
sur des gouts, sujets, modes de jeu et avis communs.

But produit :
- mieux visualiser les communautes naturelles du chat
- mieux construire un contexte social et thematique pour le bot
- rendre la vue graphe plus lisible que du multi-hop brut
- preparer des suggestions du type :
  - "ce viewer ressemble a ..."
  - "ce viewer partage surtout ..."
  - "ce groupe tourne autour de Valheim/no-death"

Cette V3 reste compatible avec SQLite.
Elle ne suppose pas Neo4j.

---

## Probleme Actuel

Aujourd'hui, `homegraph` sait surtout exprimer :
- `viewer -> game`
- `viewer -> topic`
- `viewer -> stream_mode`
- `viewer -> viewer`

Ce qui manque encore :
- des **liens partages** entre viewers
- des **projections** entre entites
- des **clusters thematiques** lisibles

Consequence :
- les graphes restent viewer-centric
- cliquer sur une entite comme `Valheim` donne vite un graphe trop large ou trop pauvre
- on voit mal qui partage quoi avec qui

---

## Idee Cle

Ne pas ajouter un gros graphe plus complexe.

Ajouter plutot deux couches :

1. **liens projetes entite -> entite**
- ex. `game:valheim -> stream_mode:no_death`
- ex. `game:satisfactory -> topic:automation`

2. **liens resumes viewer -> viewer**
- ex. `viewer:a -> viewer:b [shares_interest_with: valheim]`
- ex. `viewer:a -> viewer:b [shares_mode_with: no_death]`
- ex. `viewer:a -> viewer:b [shares_dislike_with: enshrouded]`

---

## Trois Niveaux De Graphe

### Niveau 1 — Liens Bruts

Ce qui existe deja en V2 :
- `viewer -> entity`

Exemples :
- `viewer:expevay -> game:valheim [plays]`
- `viewer:arthii_tv -> stream_mode:hardcore [likes]`
- `viewer:karramelle -> game:enshrouded [dislikes]`

### Niveau 2 — Liens Projetes

Nouveaute V3 :
- `entity -> entity`

Exemples :
- `game:valheim -> stream_mode:no_death [co_occurs_with]`
- `game:valheim -> stream_mode:cauchemar [co_occurs_with]`
- `game:satisfactory -> topic:automation [co_occurs_with]`
- `game:valheim -> topic:no_death [co_occurs_with]`

### Niveau 3 — Liens Resumes Viewer-Viewer

Nouveaute V3 :
- `viewer -> viewer`

Exemples :
- `viewer:expevay -> viewer:arthii_tv [shares_interest_with: valheim]`
- `viewer:expevay -> viewer:karramelle [shares_interest_with: valheim]`
- `viewer:a -> viewer:b [shares_dislike_with: enshrouded]`

---

## Types De Liens V3

### Entite -> Entite

Relation types recommandes :
- `co_occurs_with`
- `commonly_played_in_mode`
- `commonly_discussed_with`
- `commonly_associated_with`

Exemples :
- `game:valheim -> stream_mode:no_death [commonly_played_in_mode]`
- `game:valheim -> topic:no_death [commonly_associated_with]`
- `game:satisfactory -> topic:automation [commonly_discussed_with]`

### Viewer -> Viewer

Relation types recommandes :
- `shares_interest_with`
- `shares_mode_with`
- `shares_topic_with`
- `shares_dislike_with`
- `shares_playstyle_with`
- `shares_running_gag_with`

Exemples :
- `viewer:expevay -> viewer:arthii_tv [shares_interest_with]`
- `viewer:expevay -> viewer:karramelle [shares_interest_with]`

---

## Nouvelles Tables Possibles

### 1. `entity_links`

But :
- stocker les projections entre entites

Champs proposes :
- `entity_link_id`
- `source_entity_id`
- `target_entity_id`
- `relation_type`
- `strength`
- `confidence`
- `evidence_count`
- `viewer_count`
- `first_seen_at`
- `last_seen_at`
- `source_viewer_ids_json`
- `source_memory_ids_json`
- `created_at`
- `updated_at`

### 2. `viewer_similarity_links`

But :
- stocker des proximités viewer-viewer exploitable par l'UI et le contexte

Champs proposes :
- `similarity_link_id`
- `source_viewer_id`
- `target_viewer_id`
- `relation_type`
- `score`
- `confidence`
- `shared_entities_json`
- `shared_modes_json`
- `shared_topics_json`
- `shared_opinions_json`
- `first_seen_at`
- `last_seen_at`
- `created_at`
- `updated_at`

### 3. `viewer_similarity_rollups` optionnelle

But :
- materialiser un resume compact par viewer si besoin de perf

Champs proposes :
- `viewer_id`
- `rollup_json`
- `updated_at`

---

## Si On Veut Rester Minimal

Version minimaliste recommandee :

- ne pas creer tout de suite `viewer_similarity_rollups`
- commencer avec seulement :
  - `entity_links`
  - `viewer_similarity_links`

Et meme plus minimal au debut :
- calcul a la volee depuis `viewer_links`
- puis materialisation plus tard si utile

---

## Comment Calculer Les Liens Partages

### Regle 1 — Jeu Partage

Si deux viewers ont :
- `viewer -> game:X [plays]`

Alors on peut projeter :
- `viewer:A <-> viewer:B [shares_interest_with]`

Poids suggere :
- base `+3`
- plus `strength` commun moyen
- plus bonus si recent

### Regle 2 — Mode Partage

Si deux viewers ont :
- `viewer -> stream_mode:no_death`

Alors :
- `viewer:A <-> viewer:B [shares_mode_with]`

Poids suggere :
- base `+2`

### Regle 3 — Avis Partage

Si deux viewers ont :
- `viewer -> game:enshrouded [dislikes]`

Alors :
- `viewer:A <-> viewer:B [shares_dislike_with]`

Poids suggere :
- base `+2`

### Regle 4 — Topic Partage

Si deux viewers reviennent souvent sur :
- `topic:automation`
- `topic:k7vhs`

Alors :
- `viewer:A <-> viewer:B [shares_topic_with]`

Poids suggere :
- base `+1`

### Regle 5 — Projection Entite

Si plusieurs viewers relient :
- `game:valheim`
et
- `stream_mode:no_death`

Alors :
- `game:valheim -> stream_mode:no_death [commonly_played_in_mode]`

---

## Score De Proximite Viewer-Viewer

Forme simple recommandee :

```text
score =
  3 * shared_games
  + 2 * shared_modes
  + 2 * shared_dislikes
  + 1 * shared_topics
  + freshness_bonus
```

Puis :
- normalisation 0-1
- seuil minimum pour afficher

Objectif :
- ne pas montrer tous les viewers voisins
- montrer seulement les proximités utiles

---

## Fraicheur Et Obsolescence

Un lien partage doit etre temporel.

Il faut tenir compte de :
- `last_seen_at`
- recence des evidences
- nombre de viewers encore actifs sur ce lien

Exemples :
- `shared_interest_with: valheim` peut rester fort
- `shared_topic_with: K7VHS` peut s'affaiblir

Recommendation :
- `effective_score = score * freshness_decay`

---

## Vues Produit Utiles

### Vue 1 — Shared Game

Exemple :
- centre : `game:valheim`
- viewers qui y jouent
- modes de jeu associes
- sujets proches

### Vue 2 — Similar Viewers

Exemple :
- centre : `viewer:expevay`
- viewers les plus proches
- raison du rapprochement :
  - Valheim
  - no_death
  - Enshrouded

### Vue 3 — Shared Opinion

Exemple :
- centre : `game:enshrouded`
- viewers qui l'apprecient ou le rejettent

### Vue 4 — Shared Topic

Exemple :
- centre : `topic:automation`
- viewers lies
- jeux associes

---

## Impact Pour Le Bot

Cette V3 n'est pas qu'un sujet d'UI.

Elle aiderait aussi le prompt :
- "ce viewer ressemble a Expevay sur Valheim/no-death"
- "ce viewer partage le gout build/automation"
- "ce viewer a des avis proches d'autres viewers connus"

Cela permet :
- des reponses plus naturelles
- des rapprochements sociaux credibles
- une meilleure contextualisation des viewers peu documentes

---

## Implementation Recommandee

### Etape 1

Ajouter un script de projection :
- lit `viewer_links`
- calcule `entity_links`
- calcule `viewer_similarity_links`

Pas encore dans le runtime bot.

### Etape 2

Ajouter une route admin lecture seule :
- `GET /admin/homegraph/users/{user_id}/similarity`
- ou
- `GET /admin/homegraph/graph?center_node_id=...&mode=shared_interest`

### Etape 3

Utiliser ces resultats dans :
- la vue admin
- le `text_block`
- puis plus tard l'arbitrage du bot

---

## Recommandation Immediate

Le prochain plus petit pas utile n'est pas une nouvelle base.

C'est :

1. calculer des projections `game -> stream_mode/topic`
2. calculer des liens viewer-viewer simples par jeu/mode commun
3. exposer une vue admin dediee "shared_interest"

Cela donnerait rapidement :
- un graphe plus lisible
- des clusters viewers plus naturels
- une meilleure base pour la memoire contextuelle du bot
