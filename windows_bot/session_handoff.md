# Session Handoff Windows

Date:
- 2026-03-27

## Etat utile

Branche locale:
- `main`

Dernier commit Windows pousse avant ce handoff:
- `9d77d2d` `Refine Homegraph V3 viewer navigation`

Worktree volontairement non propre:
- `architecture_components_yed.graphml`
- `windows_bot/session_handoff.md`
- `windows_bot/memory_context_roadmap.md`

## Ce qui est stabilise cote Windows

Mode cible:
- full Windows pour la memoire utile
- SQLite local pour memoire durable viewer
- SQLite local pour `homegraph`
- plus de dependance Linux active dans le runtime normal ou l'admin normal

Admin UI:
- separation `Global` / `Data Steward`
- actions viewer sur chaque carte
- icones SVG pour `editer / exporter / review export / purge`
- bandeau d'analyse GPT en cours
- navigation verrouillee pendant analyse GPT
- panneaux `Recent` et `Edition` repliables

Graph 3D:
- taille dynamique
- labels permanents au-dessus des noeuds
- legende dynamique
- souris stable:
  - gauche rotation
  - droite pan
  - drag de noeud actif
- plus de double import Three.js
- plus de refocus camera automatique parasite

Homegraph UI:
- clic viewer connu => ouvre le viewer
- clic viewer ambigu Homegraph => reste en navigation Homegraph
- clic entite => Homegraph centre
- pour Homegraph centre, l'UI garde la composante connectee au centre
- mode local supporte:
  - `entity_focus`
  - `multihop`
- profondeur Homegraph reglable

GPT -> Homegraph:
- `Analyser avec GPT` genere aussi un enrichissement Homegraph
- validation locale supportee
- preview `dry_run` supportee
- merge final supporte
- bouton `Fusionner dans Homegraph` doit se desactiver au premier clic

## Invariants a ne pas casser

1. Viewer Homegraph ambigu
- ne jamais convertir automatiquement `viewer:k7vhs` en `twitch:<channel>:viewer:k7vhs`
- ne jamais router un viewer ambigu vers la vue mem0 juste parce qu'un label matche

2. Requetes Homegraph centrees
- ne pas envoyer `viewer` / `user_id` quand `center_node_id` est utilise
- sinon Windows peut reappliquer un filtre viewer V1 et casser la vue centree

3. Detaills panneau graphe
- un clic sur un noeud Homegraph ne doit pas afficher un JSON puis revenir au tip par defaut
- si la reponse locale renvoie un centre absent, l'UI doit retomber proprement sur la vue viewer au lieu d'effacer brutalement l'etat

4. Merge Homegraph
- le bouton de merge ne doit pas etre spammable
- garder un verrou UI local pendant la requete

5. Memoire admin UI
- suppression memoire scopiee par `user_id + memory_id`
- eviter tout flux ambigu qui opere sur le mauvais viewer

## Etat produit reel

Le goulot principal n'est plus le rapatriement Linux.

La prochaine session doit plutot se concentrer sur:
- qualite des donnees `homegraph.sqlite3`
- reconstruction des graphes viewers pauvres quand la base ne contient plus que le profil
- qualite conversationnelle du runtime (`thread_context`, arbitrage, prompt)

## Fichiers Windows les plus sensibles

- [admin_ui.py](C:/Users/xuanp/BotTwitch/tolabot/windows_bot/admin_ui.py)
- [admin_client.py](C:/Users/xuanp/BotTwitch/tolabot/windows_bot/admin_client.py)
- [openai_review_client.py](C:/Users/xuanp/BotTwitch/tolabot/windows_bot/openai_review_client.py)
- [test_admin_ui.py](C:/Users/xuanp/BotTwitch/tolabot/windows_bot/test_admin_ui.py)
- [test_admin_client.py](C:/Users/xuanp/BotTwitch/tolabot/windows_bot/test_admin_client.py)

## Reprise minimale

Si nouvelle session:
- commencer par relire ce fichier
- puis verifier l'etat de `admin_ui.py` et `admin_client.py`
- puis verifier la qualite reelle des donnees SQLite locales
- puis reprendre soit la qualite Homegraph, soit le contexte conversationnel
