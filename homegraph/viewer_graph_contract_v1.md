# Viewer Graph Contract V1

## Objet

Definir un contrat JSON minimal et stable pour une vue graphe 2D/3D cote Windows, alignee sur `homegraph v2`.

But :
- fournir un sous-graphe filtre par viewer
- rester stable meme si `homegraph` evolue
- ne pas imposer de logique metier lourde au front

Le payload est volontairement simple :
- `nodes`
- `links`
- `stats`
- `meta`

## Portee

V1 produit un sous-graphe **centre sur un viewer** :
- 1 noeud racine `viewer`
- des noeuds cibles relies a ce viewer
- des liens viewer -> cible

Ce n'est pas encore un graphe global multi-hop.

## Structure

```json
{
  "ok": true,
  "viewer_id": "twitch:streamer:viewer:alice",
  "generated_at": "2026-03-26T10:00:00+00:00",
  "source": "homegraph_graph_v1",
  "meta": {
    "root_node_id": "viewer:twitch:streamer:viewer:alice",
    "filtered_by_viewer": true,
    "profile_last_updated_at": "2026-03-26T09:45:00+00:00",
    "stable_node_kinds": ["viewer", "game", "topic", "running_gag", "trait", "stream_mode", "object"],
    "stable_link_kinds": ["plays", "likes", "dislikes", "talks_about", "returns_to", "knows", "compliments", "jokes_about", "interacts_with", "uses_build_style", "plays_in_mode", "owns"]
  },
  "stats": {
    "node_count": 6,
    "link_count": 5,
    "node_kinds": {
      "viewer": 1,
      "game": 2,
      "stream_mode": 2,
      "object": 1
    },
    "link_kinds": {
      "plays": 1,
      "dislikes": 1,
      "likes": 2,
      "owns": 1
    }
  },
  "nodes": [
    {
      "id": "viewer:twitch:streamer:viewer:alice",
      "label": "Alice",
      "kind": "viewer",
      "color": "#4F46E5",
      "detail": "Resume court optionnel"
    }
  ],
  "links": [
    {
      "source": "viewer:twitch:streamer:viewer:alice",
      "target": "game:valheim",
      "kind": "plays",
      "label": "plays",
      "color": "#2563EB",
      "weight": 0.95,
      "detail": "status=active | polarity=positive | evidence=3"
    }
  ]
}
```

## Noeuds

Champs minimaux :
- `id`
- `label`
- `kind`

Champs optionnels :
- `color`
- `detail`

### Kinds de noeuds stables V1

- `viewer`
- `game`
- `topic`
- `running_gag`
- `trait`
- `stream_mode`
- `object`

Notes :
- `viewer` est toujours le noeud racine du sous-graphe
- des kinds additionnels peuvent apparaitre plus tard
- le front Windows doit tolerer un `kind` inconnu sans planter

## Liens

Champs minimaux :
- `source`
- `target`
- `kind`

Champs optionnels :
- `label`
- `color`
- `weight`
- `detail`

### Kinds de liens stables V1

- `plays`
- `likes`
- `dislikes`
- `talks_about`
- `returns_to`
- `knows`
- `compliments`
- `jokes_about`
- `interacts_with`
- `uses_build_style`
- `plays_in_mode`
- `owns`

Notes :
- le front Windows doit tolerer un `kind` inconnu
- `weight` represente un score pratique de rendu
- en V1, `weight` vient plutot de `strength`, sinon de `confidence`

## Stats

`stats` est un resume utile au front pour :
- afficher des compteurs
- filtrer
- valider le payload

Champs V1 :
- `node_count`
- `link_count`
- `node_kinds`
- `link_kinds`

## Meta

`meta` sert a la stabilite du contrat et au debuggage.

Champs V1 :
- `root_node_id`
- `filtered_by_viewer`
- `profile_last_updated_at`
- `stable_node_kinds`
- `stable_link_kinds`
- `filters_applied`

## Production Cote Linux

Le sous-graphe viewer peut deja etre produit cote Linux :

### Script local

```bash
python3 homegraph/build_viewer_graph.py --viewer-id twitch:streamer:viewer:alice
```

### Endpoint admin local

```bash
GET /admin/homegraph/users/{user_id}/graph
```

Filtres optionnels deja supportes :
- `include_uncertain=true|false`
- `min_weight=<float>`
- `max_links=<int>`

Exemple :

```bash
GET /admin/homegraph/users/{user_id}/graph?include_uncertain=false&min_weight=0.7&max_links=8
```

Auth :
- `X-Admin-Key`

Topologie attendue pour Windows :
- meme tunnel admin que pour le contexte compact
- base URL locale Windows : `http://127.0.0.1:9000`

## Intention Produit

Cette V1 doit suffire pour :
- une vue 3D/2D filtree par viewer
- clic sur un noeud
- clic sur un lien
- affichage de details
- filtrage par kinds

Sans recablage majeur plus tard, si `homegraph v2` devient plus riche.
