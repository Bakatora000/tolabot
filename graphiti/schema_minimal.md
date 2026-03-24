# Schema Minimal Graphiti V1

## Intent

Ce schema vise une premiere base graphe simple, lisible, et compatible avec du stewarding manuel.

## Nodes

### Viewer

Champs minimaux :
- `viewer_login`
- `channel_login`
- `display_name` optionnel
- `first_seen_at` optionnel
- `last_seen_at` optionnel

### Game

Champs minimaux :
- `name`
- `normalized_name`
- `first_seen_at` optionnel
- `last_seen_at` optionnel

### Topic

Champs minimaux :
- `name`
- `normalized_name`
- `category` optionnel
- `first_seen_at` optionnel
- `last_seen_at` optionnel

## Edges

### PLAYS

Source :
- `Viewer`

Target :
- `Game`

Champs possibles :
- `confidence`
- `first_seen_at`
- `last_seen_at`

### TALKS_ABOUT

Source :
- `Viewer`

Target :
- `Topic`

Champs possibles :
- `confidence`
- `first_seen_at`
- `last_seen_at`

### INTERACTS_WITH

Source :
- `Viewer`

Target :
- `Viewer`

Champs possibles :
- `interaction_type` optionnel
- `confidence`
- `first_seen_at`
- `last_seen_at`

## Regles V1

- pas d'ontologie trop riche des le debut
- pas de schema animal/personnage/objet trop detaille
- privilegier la stabilite semantique
- conserver un lien clair entre episode source et fait derive
- preferer peu de types mais propres
