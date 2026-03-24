# Contexte Linux — Graphiti V1

## Objet

Ce document cadre un nouveau chantier experimental :
- deploiement de Graphiti sur le serveur Linux qui heberge deja `mem0-api`
- usage initial **offline / local only**
- aucune exposition publique
- aucune integration live immediate dans le bot Twitch

Le but n'est pas de remplacer mem0.
Le but est de construire une **couche graphe temporelle** derivee des souvenirs mem0, pour explorer ensuite des usages de consultation plus contextuels.

---

## Positionnement Produit

Repartition retenue :

- `mem0`
  - memoire conversationnelle durable par viewer
  - utile directement au bot
  - source de verite pratique pour les souvenirs textuels

- `Graphiti`
  - representation relationnelle / temporelle derivee
  - structure de communaute
  - entites, relations, evolution dans le temps
  - usage initial experimental et offline

Graphiti ne doit pas etre branche en ecriture temps reel dans le bot pour l'instant.

---

## Perimetre V1

V1 attendue :
- installation locale de Graphiti sur le serveur Linux
- configuration locale uniquement
- acces uniquement depuis la machine Linux, ou via tunnel SSH plus tard si necessaire
- aucun endpoint public Nginx
- aucun impact sur le service mem0 public existant

V1 ne demande pas :
- ingestion live du chat Twitch
- exposition publique
- integration directe au prompt Ollama
- pipeline automatique complet de stewarding

---

## Contraintes D'Architecture

Topologie actuelle a respecter :
- `mem0-api` existe deja sur Linux
- `mem0-api` reste la brique memoire principale
- Graphiti doit etre ajoute comme service/brique separee ou environnement separe, sans casser mem0

Contraintes fortes :
- pas d'exposition publique de Graphiti
- pas de conflit avec Qdrant/path ou autres stockages existants
- pas de dependance runtime du bot Windows vers Graphiti pour cette phase
- pas de regression sur `mem0-api`

Recommandation :
- Graphiti accessible localement seulement
- bind sur `127.0.0.1`
- ports documentes mais non publies
- service systemd separe si necessaire

---

## Source Des Donnees

Source V1 retenue :
- exports mem0 par viewer

Le flux cible est :

1. export mem0 viewer
2. transformation en objets exploitables pour Graphiti
3. eventuel stewarding manuel
4. ingestion dans Graphiti

La source initiale n'est donc pas le chat brut Twitch.
La source initiale est la memoire mem0 deja nettoyee ou semi-nettoyee.

---

## Schema Conceptuel Minimal

Pour une premiere base graphe, on veut rester minimal.

### Entites

- `Viewer`
- `Game`
- `Topic`

### Relations

- `PLAYS`
  - ex: viewer -> game

- `TALKS_ABOUT`
  - ex: viewer -> topic

- `INTERACTS_WITH`
  - ex: viewer -> viewer

### Temporalite

Quand c'est possible, conserver :
- date d'apparition
- date/derniere observation
- statut actif / expire si Graphiti le supporte naturellement

---

## Exemples De Transformation

Exemples d'entrees mem0 :

- `Le viewer joue aussi à World of Warcraft.`
  - entites :
    - Viewer(viewer_a)
    - Game(World of Warcraft)
  - relation :
    - `PLAYS`

- `Le viewer dit être un builder sur Satisfactory.`
  - entites :
    - Viewer(viewer_b)
    - Game(Satisfactory)
    - Topic(builder)
  - relations :
    - `PLAYS`
    - `TALKS_ABOUT` ou attribut selon le schema final

- `Le viewer a mentionné que Dame_Gaby est un bouledogue français.`
  - V1 :
    - probablement `Topic(Dame_Gaby)` plutot qu'un schema animal/personnage plus riche

---

## Stewarding

Le besoin de stewarding existe aussi pour Graphiti.
Il est meme critique.

Le graphe ne doit pas etre alimente par :
- troll evident
- injures
- questions ephemeres
- interactions trop contextuelles
- running jokes non stabilises

V1 attendue :
- pipeline compatible avec du stewarding manuel
- pas de commit aveugle de tout export mem0 vers Graphiti

Ce qu'il faut prevoir :
- une etape de transformation explicite
- des objets ou fichiers intermediaires relisibles
- des logs de ce qui est cree dans Graphiti

---

## Consultation Future A Prevoir

Meme si V1 est surtout un deploiement + base d'ingestion, il faut penser des maintenant a la couche de consultation.

Usages cibles plus tard :

- `get_viewer_profile(viewer)`
  - jeux lies
  - sujets lies
  - relations simples

- `get_viewer_links(viewer)`
  - viewers associes
  - relations frequentes / notables

- `get_viewer_topics(viewer)`
  - sujets recurrents

- `build_graph_prompt_context(viewer)`
  - resume graphe court utilisable ensuite dans un prompt Ollama

Important :
- on n'envoie pas le graphe brut au modele
- on veut une couche de resume/requete exploitable

---

## Livrables Linux Attendus

Pour CodexLinux, les livrables utiles de cette phase sont :

1. document de choix technique Graphiti
   - package / version / mode d'installation
   - stockages utilises
   - contraintes de fonctionnement

2. installation locale de Graphiti
   - isolee du runtime mem0 existant
   - documentee

3. convention de deploiement
   - bind local
   - service systemd si necessaire
   - variables d'environnement

4. proposition de pipeline d'ingestion V1
   - depuis export mem0
   - vers Graphiti

5. proposition de schema minimal
   - entites
   - relations
   - timestamps / temporalite

6. recommandations de consultation
   - quelles requetes/extractions exposer plus tard

---

## Non-Objectifs

Ne pas faire dans cette phase :

- brancher Graphiti au bot Windows en production
- exposer Graphiti publiquement
- remplacer mem0
- construire un moteur de stewarding automatique complet
- ingerer tout le chat historique sans filtrage

---

## Questions Techniques A Trancher Cote Linux

CodexLinux peut proposer et documenter :

1. mode exact de deploiement Graphiti
   - lib Python integree
   - service dedie
   - process ponctuel offline

2. stockage utilise par Graphiti
   - base relationnelle / graphe / autre
   - impact ops

3. isolation vis-a-vis de mem0
   - environnements Python
   - dependances
   - ports
   - systemd

4. format d'import V1
   - JSON intermediaire simple
   - ou pipeline Python direct

---

## Recommandation Pragmatique

Le bon chemin pour V1 est probablement :

1. installer Graphiti localement
2. valider qu'il tourne localement sans exposition publique
3. definir un schema minimal `Viewer / Game / Topic`
4. produire un petit importeur offline depuis un export mem0
5. verifier que quelques viewers peuvent etre injectes proprement
6. documenter la future couche de consultation

Autrement dit :
- deploiement local d'abord
- ingestion offline ensuite
- exploitation dans les prompts plus tard seulement

---

## Resume Court Pour CodexLinux

On veut ajouter Graphiti sur le serveur Linux **comme couche experimentale locale**.

Objectif :
- construire une base graphe temporelle derivee de mem0
- sans exposition publique
- sans impact sur mem0-api
- avec un schema simple et un pipeline d'ingestion offline

Le resultat attendu de cette phase n'est pas un usage live.
Le resultat attendu est une base propre pour experimentation future et consultation contextuelle.
