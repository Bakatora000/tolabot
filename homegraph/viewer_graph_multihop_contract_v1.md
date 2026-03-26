# Viewer Graph Multihop Contract V1

## Objet

Definir un contrat JSON stable pour un sous-graphe `homegraph` multi-hop, exploitable par la vue 3D Windows sans logique metier supplementaire cote front.

But :
- partir d'un noeud central explicite
- explorer son voisinage a profondeur limitee
- garder un payload compact, borne et lisible
- rester compatible avec la V1 `nodes / links / stats / meta`

Ce contrat complete `viewer_graph_contract_v1.md` :
- V1 = ego graph centre sur un viewer
- multihop V1 = sous-graphe borne centre sur n'importe quel noeud stable

## Portee

Le backend produit un sous-graphe borne autour d'un noeud central :
- `center_node_id`
- profondeur maximale `max_depth`
- taille maximale `max_nodes`
- taille maximale `max_links`

Le front Windows ne calcule pas lui-meme les hops :
- il affiche ce que renvoie le backend
- il peut demander un nouveau sous-graphe centre sur un noeud clique

## Route Cible

Proposition de route admin :

```text
GET /admin/homegraph/graph
```

Parametres requis :
- `center_node_id`

Parametres optionnels :
- `max_depth=<int>`
- `max_nodes=<int>`
- `max_links=<int>`
- `include_uncertain=true|false`
- `min_weight=<float>`

Exemple :

```text
GET /admin/homegraph/graph?center_node_id=viewer:twitch:expevay:viewer:expevay&max_depth=2&max_nodes=32&max_links=40&include_uncertain=false&min_weight=0.7
```

Compatibilite :
- la route V1 viewer-centrique peut rester en place
- cette route multihop est une capacite additionnelle

## Structure

```json
{
  "ok": true,
  "generated_at": "2026-03-26T10:00:00+00:00",
  "source": "homegraph_graph_multihop_v1",
  "meta": {
    "root_node_id": "viewer:twitch:expevay:viewer:expevay",
    "center_node_id": "viewer:twitch:expevay:viewer:expevay",
    "max_depth": 2,
    "truncated": false,
    "filters_applied": {
      "include_uncertain": false,
      "min_weight": 0.7,
      "max_nodes": 32,
      "max_links": 40
    },
    "stable_node_kinds": ["viewer", "game", "topic", "running_gag", "trait", "stream_mode", "object"],
    "stable_link_kinds": ["plays", "likes", "dislikes", "talks_about", "returns_to", "knows", "compliments", "jokes_about", "interacts_with", "uses_build_style", "plays_in_mode", "owns"]
  },
  "stats": {
    "node_count": 12,
    "link_count": 14,
    "node_kinds": {
      "viewer": 3,
      "game": 2,
      "stream_mode": 2,
      "topic": 3,
      "object": 2
    },
    "link_kinds": {
      "plays": 2,
      "likes": 4,
      "interacts_with": 2,
      "plays_in_mode": 2,
      "owns": 1,
      "returns_to": 3
    }
  },
  "nodes": [
    {
      "id": "viewer:twitch:expevay:viewer:expevay",
      "label": "expevay",
      "kind": "viewer",
      "color": "#4F46E5",
      "detail": "Viewer centre"
    },
    {
      "id": "game:valheim",
      "label": "Valheim",
      "kind": "game",
      "color": "#2563EB",
      "detail": "Jeu fortement relie"
    }
  ],
  "links": [
    {
      "source": "viewer:twitch:expevay:viewer:expevay",
      "target": "game:valheim",
      "kind": "plays",
      "label": "plays",
      "color": "#2563EB",
      "weight": 0.95,
      "detail": "status=active | evidence=3"
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

Kinds stables attendus :
- `viewer`
- `game`
- `topic`
- `running_gag`
- `trait`
- `stream_mode`
- `object`

Le front doit tolerer un `kind` inconnu.

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

Kinds stables attendus :
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

Le front doit tolerer un `kind` inconnu.

## Meta

Champs recommandes :
- `root_node_id`
- `center_node_id`
- `max_depth`
- `truncated`
- `filters_applied`
- `stable_node_kinds`
- `stable_link_kinds`

Notes :
- `root_node_id` designe le noeud d'origine logique de l'exploration
- `center_node_id` designe le noeud effectivement demande pour ce sous-graphe
- `truncated=true` signale qu'une coupe a ete appliquee par `max_nodes` ou `max_links`

## Regles De Construction

Principes recommandes cote backend :
- expansion par couches BFS jusqu'a `max_depth`
- tri des liens candidats par score pratique avant coupe
- coupe deterministe si `max_nodes` ou `max_links` sont atteints
- conservation prioritaire des liens forts / fiables / actifs

Score pratique suggere :
- `strength` si present
- sinon `confidence`
- sinon poids par defaut

## Comportement Attendu Cote Windows

La vue 3D doit pouvoir :
- charger un sous-graphe centre sur un viewer
- recliquer sur un noeud et demander un nouveau sous-graphe centre sur ce noeud
- rester lisible grace a `max_depth`, `max_nodes`, `max_links`
- afficher les details du noeud ou du lien selectionne

La vue Windows ne doit pas supposer :
- un graphe global complet
- une exploration infinie
- l'existence de tous les voisins possibles

## Cas Produit Vises

Exemples attendus :
- cliquer `Valheim` dans le graphe d'un viewer et voir aussi d'autres viewers ou modes lies a `Valheim`
- cliquer `Dame_Gaby` et voir ses relations utiles dans le sous-graphe borne
- cliquer un `stream_mode` et voir les viewers / jeux / objets relies

## Compatibilite

Le payload reste compatible avec la vue actuelle :
- `nodes`
- `links`
- `stats`
- `meta`

Donc :
- un front V1 peut deja afficher ce payload sans tout connaitre du multihop
- un front plus riche peut exploiter `center_node_id`, `max_depth` et `truncated`

## Intention

Cette V1 multihop doit permettre :
- une vraie exploration interactive dans la vue 3D
- sans forcer un passage immediat a Neo4j
- en restant sur SQLite et un backend borne, deterministe et debuggable
