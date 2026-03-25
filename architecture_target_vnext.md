# Architecture Cible — Tolabot vNext

## Objet

Ce document fixe la cible d'architecture pour la refacto en cours du bot Windows.

Il sert a :
- guider la decomposition du runtime du bot
- eviter que `bot_ollama.py` redevienne un monolithe
- unifier les interfaces entre memoire, decision, web et generation
- preparer la trajectoire long terme vers un bot plus contextuel, plus temporel et capable d'interventions spontanees
- garder ouverte une cible finale de packaging en executable unique (`tolabot.exe`)

Ce document decrit une cible.
Il ne signifie pas que tout doit etre implemente d'un coup.

---

## Objectif Produit

Tolabot doit a terme etre capable de :
- repondre naturellement dans le chat
- rebondir sur des questions avec contexte recent et memoire durable
- garder une continuite de conversation par viewer et par chaine
- tenir compte du temps :
  - contexte recent
  - faits durables
  - signaux devenus obsoletes
- intervenir parfois de lui-meme de facon cadree
- rester debuggable et gouvernable

Le systeme doit donc separer clairement :
- la perception
- la memoire courte
- la memoire longue
- la decision
- la composition du prompt
- la generation
- la memorisation post-reponse

---

## Vue Cible

```text
Entrants Twitch/EventSub/Admin/Timers
    ->
Perception
    ->
Classification / Normalisation
    ->
Arbitrage
    -> collecte selective ->
Memoire courte
Memoire longue
Web
    ->
Composition du contexte
    ->
Generation LLM
    ->
Post-traitement
    ->
Sortie chat / abstention / memorisation
```

---

## Blocs Cibles

### 1. Perception

Role :
- recevoir tous les evenements entrants
- les normaliser dans un format interne unique

Entrees typiques :
- message chat Twitch
- evenement EventSub
- signal admin local
- timer interne
- eventuelle activation spontanee

Sortie cible :

```json
{
  "event_id": "evt_...",
  "type": "chat_message",
  "channel": "streamer",
  "author": "viewer_a",
  "timestamp": "2026-03-25T18:00:00Z",
  "text": "@anneaunimouss tu penses quoi de Valheim ?",
  "reply_to": null,
  "metadata": {}
}
```

Contraintes :
- aucune logique metier lourde
- pas d'appel memoire ici
- pas d'appel LLM ici

Mapping probable :
- `bot_ollama.py`
- `twitchio`
- `eventsub`

### 2. Memoire Courte

Role :
- stocker le contexte conversationnel recent et borne

Composants probables :
- buffer recent du chat
- `conversation_graph`
- `facts_memory`
- memoire locale specialisee viewer/thread

Ce que cette couche doit faire :
- fournir du contexte recent a forte valeur conversationnelle
- expirer vite
- rester petite et explicable

Ce qu'elle ne doit pas faire :
- se faire passer pour une memoire durable
- piloter la decision globale a elle seule

### 3. Memoire Longue

Role :
- fournir la matiere durable et semi-durable

Sources actuelles ou cibles :
- `homegraph`
- `mem0`
- profil de chaine
- faits consolides

Contrat recommande pour chaque source :

```json
{
  "source_id": "homegraph",
  "available": true,
  "priority": 80,
  "confidence": 0.74,
  "stale": false,
  "text_block": "Contexte viewer: ...",
  "meta": {
    "viewer_id": "twitch:streamer:viewer:alice"
  }
}
```

Pourquoi ce contrat compte :
- toutes les sources deviennent comparables
- l'arbitrage peut raisonner en termes de priorite, confiance, fraicheur et cout
- le runtime reste mince

### 4. Decision / Arbitrage

C'est le vrai coeur du bot.

Role :
- decider si le bot doit agir
- decider comment il doit agir
- decider quelles sources de contexte doivent etre consultees

Exemples de decisions :
- repondre
- ne pas repondre
- faire une recherche web
- memoriser seulement
- attendre plus de contexte
- faire une intervention spontanee

Contrat recommande :

```json
{
  "decision": "reply",
  "rule_id": "viewer_question_with_context",
  "needs_short_memory": true,
  "needs_long_memory": true,
  "needs_web": false,
  "allow_spontaneous": false,
  "reply_style": "natural",
  "reason": "viewer addressed bot with contextual question"
}
```

Invariants :
- `rule_id` doit toujours etre present
- une decision doit etre loggable et rejouable
- la couche d'arbitrage ne doit pas directement construire le prompt final

Ce qui peut rester declaratif :
- regles sociales simples
- web routing stable
- petits triggers metier robustes

Ce qui doit rester code :
- arbitrage contextuel complexe
- scoring
- fusion multi-sources
- gestion de priorites dynamiques

### 5. Composition du Contexte

Role :
- prendre la decision
- interroger les bonnes sources
- construire un contexte final propre pour le LLM

Entrees :
- `DecisionResult`
- sources de contexte unifiees
- message courant
- eventuel web context

Sortie cible :

```json
{
  "system_block": "...",
  "viewer_block": "...",
  "conversation_block": "...",
  "web_block": "...",
  "style_block": "...",
  "source_trace": [
    "local_specialized",
    "homegraph",
    "mem0"
  ]
}
```

Regle importante :
- cette couche fusionne
- elle ne redecide pas

### 6. Generation / Post-traitement

Role :
- appeler Ollama
- nettoyer la sortie
- borner la taille
- appliquer l'attribution correcte quand le web est utilise
- decider quoi memoriser apres coup

Sorties possibles :
- message chat
- silence
- message raccourci
- message rejete si suspect

### 7. Memorisation Post-Reponse

Role :
- envoyer les bons signaux vers les memoires

Exemples :
- mem0 pour la memoire durable
- homegraph pour la consolidation plus tard
- memoire courte locale pour le fil recent

Principe :
- on ne memorise pas tout
- la memorisation doit etre selective et explicable

---

## Pipeline Recommande

Pipeline logique cible :

1. normaliser l'evenement entrant
2. classer l'intention
3. executer l'arbitrage
4. collecter les sources de contexte requises
5. composer le prompt final
6. generer la reponse
7. post-traiter
8. memoriser si pertinent

Le point critique est que chaque etape ait :
- des entrees explicites
- des sorties explicites
- un logging stable

---

## Interfaces Recommandees

### NormalizedEvent

Objet interne unique pour tous les entrants.

### DecisionResult

Objet interne unique pour toute decision.

Champs minimaux recommandes :
- `decision`
- `rule_id`
- `reason`
- `needs_short_memory`
- `needs_long_memory`
- `needs_web`
- `allow_spontaneous`
- `meta`

### ContextSourceResult

Objet standard pour toute source de contexte.

Champs minimaux recommandes :
- `source_id`
- `available`
- `priority`
- `confidence`
- `stale`
- `text_block`
- `meta`

### PromptPlan

Objet qui represente le prompt final avant appel modele.

Champs minimaux recommandes :
- `system_block`
- `viewer_block`
- `conversation_block`
- `web_block`
- `style_block`
- `source_trace`

---

## Interventions Spontanees

Ce point ne doit pas etre traite comme une simple extension de la reponse classique.

Il faudra un arbitrage specifique avec au minimum :
- score d'opportunite
- score de securite
- cooldown global
- cooldown par viewer
- seuil minimal d'intervention
- contexte recent obligatoire

Decision cible possible :

```json
{
  "decision": "spontaneous_reply",
  "rule_id": "spontaneous_reaction_recent_chat",
  "reason": "strong recent topic match and safe opportunity window",
  "allow_spontaneous": true
}
```

Sans ce garde-fou, le bot parlera trop ou mal.

---

## Trajectoire Vers `tolabot.exe`

La cible finale peut etre un executable unique Windows qui embarque :
- runtime bot
- memoire courte
- memoire longue
- stockage local
- admin UI locale
- API locale optionnelle

Pour que cette migration soit possible sans refonte brutale, il faut des frontieres stables.

Ce qui doit etre abstrait des maintenant :
- acces a la memoire longue
- format du contexte viewer
- arbitrage
- composition du prompt
- clients externes

Autrement dit :
- aujourd'hui : API Linux + Windows bot
- demain : runtime Windows unifie
- le code doit deja etre ecrit comme si les sources etaient interchangeables

---

## Mapping Avec L'Existant

Etat actuel plutot sain :
- `decision_tree.json` et `decision_tree.py` pour une premiere couche declarative
- `web_search_client.py` pour le web
- `conversation_graph.py` pour le recent structure
- `facts_memory.py` pour les faits locaux
- `homegraph` cote Linux pour la memoire viewer structuree
- `mem0` pour la memoire durable generale

Direction recommandeee :
- garder `bot_ollama.py` comme orchestrateur mince
- sortir progressivement :
  - classification
  - arbitrage
  - collecte de sources
  - composition du prompt
- ne pas accumuler les decisions metier dans `bot_ollama.py`

---

## Regles D'Implementation

### Ce qui doit etre trace

Chaque reponse ou abstention devrait idealement laisser :
- `event_id`
- `rule_id`
- decision finale
- sources de contexte retenues
- si web : pourquoi
- si memoire longue : quelles sources
- si silence : pourquoi

### Ce qui doit etre teste

Minimum recommande :
- tests table-driven sur les regles declaratives
- tests d'arbitrage
- tests de fusion de contexte
- tests de non-regression sur les faux positifs web
- tests sur les cas de memoire stale / vide

### Ce qu'il faut eviter

- multiplier les cas speciaux caches dans `bot_ollama.py`
- faire du JSON un mini-langage trop opaque
- laisser plusieurs formats concurrents de contexte
- melanger arbitrage et composition du prompt

---

## Ordre De Refacto Recommande

1. stabiliser `DecisionResult` et `ContextSourceResult`
2. faire de `bot_ollama.py` un vrai orchestrateur mince
3. isoler la collecte des sources de contexte
4. isoler la composition du prompt
5. renforcer les tests du moteur declaratif
6. introduire ensuite un arbitrage plus riche
7. enfin seulement, ouvrir la voie aux interventions spontanees

---

## Resume Court

La cible n'est pas seulement un bot qui repond.

La cible est un systeme qui :
- percoit
- arbitre
- selectionne le bon contexte
- compose proprement
- genere
- memorise de facon selective

La refacto Windows actuelle va dans la bonne direction si elle converge vers :
- un orchestrateur mince
- des interfaces stables
- un arbitrage explicite
- des sources de contexte homogenes
- un futur packaging unifie possible
