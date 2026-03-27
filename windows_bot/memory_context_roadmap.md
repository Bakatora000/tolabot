# Roadmap Memoire Contextuelle Et Temporelle

## Objet

Ce document sert de guide court pour CodexWindows.

Objectif produit vise :
- suivre une discussion entre plusieurs viewers
- comprendre a qui le bot repond vraiment
- garder une continuite de contexte sur quelques tours
- reutiliser une memoire longue utile sans polluer le prompt
- preparer plus tard des interventions spontanees cadrées

Le principe cle :
- ne pas ajouter "plus de memoire" indistinctement
- mieux separer memoire courte, memoire longue et arbitrage

---

## Priorites Recommandees

Ordre de travail conseille :

1. memoire courte multi-utilisateurs
2. builder de contexte de thread
3. arbitrage appuye sur ce contexte
4. temporalite reelle dans `homegraph`
5. politique de promotion memoire

Pourquoi cet ordre :
- le plus gros manque actuel pour "suivre une discussion" est la memoire courte
- la memoire longue existe deja mais n'est pas le facteur limitant principal
- l'arbitrage ne sera fiable que si le contexte recent est meilleur

---

## Chantier 1 — Memoire Courte Multi-Utilisateurs

### But

Donner au runtime une representation exploitable des derniers tours de discussion.

### Attendu

Pour chaque message recent, garder au minimum :
- `message_id`
- `channel`
- `author`
- `timestamp`
- `text`
- `mentions`
- `reply_to`
- `target_users`
- `is_bot_addressed`

### Fichiers probables

- [conversation_graph.py](/home/vhserver/bt/windows_bot/conversation_graph.py)
- [facts_memory.py](/home/vhserver/bt/windows_bot/facts_memory.py)
- [runtime_types.py](/home/vhserver/bt/windows_bot/runtime_types.py)
- [bot_ollama.py](/home/vhserver/bt/windows_bot/bot_ollama.py)

### Resultat attendu

Le runtime doit pouvoir repondre a des questions du type :
- qui parle en ce moment
- a qui on repond
- quel sujet est actif sur les derniers tours
- quelle question reste ouverte

### Test produit

Si 3 viewers discutent de Valheim et qu'un seul mentionne `@anneaunimouss`, le bot doit :
- recuperer les derniers tours utiles
- comprendre le sujet courant
- repondre au bon sous-fil

---

## Chantier 2 — Builder De Contexte De Thread

### But

Construire un bloc compact de discussion recente a injecter au prompt.

### Contrat recommande

Ajouter un builder du genre :

```python
build_thread_context(channel, current_event) -> ContextSourceResult | None
```

Avec une sortie comparable aux autres sources :

```json
{
  "source_id": "thread_context",
  "available": true,
  "priority": 95,
  "confidence": 0.9,
  "stale": false,
  "text_block": "...",
  "meta": {
    "participants": ["alice", "bob"],
    "turn_count": 8
  }
}
```

### Contenu utile

Le `text_block` doit resumer :
- le sujet recent
- les participants importants
- la derniere question pertinente
- le dernier tour adresse au bot
- eventuellement une correction ou un desaccord recent

### Fichiers probables

- [context_sources.py](/home/vhserver/bt/windows_bot/context_sources.py)
- [runtime_types.py](/home/vhserver/bt/windows_bot/runtime_types.py)
- nouveau module conseille : [thread_context.py](/home/vhserver/bt/windows_bot/thread_context.py)

### Test produit

Quand un viewer demande :
- "et du coup pour Valheim tu en penses quoi ?"

le bot doit savoir que "du coup" refere a la discussion recente, pas a un souvenir ancien ou a une recherche web inutile.

---

## Chantier 3 — Arbitrage Appuye Sur Le Contexte

### But

Ne plus decider uniquement sur le dernier message brut.

### Direction

L'arbitre doit raisonner avec :
- l'evenement normalise
- le contexte de thread
- les sources longues disponibles
- le besoin ou non de web

### Regles utiles a ajouter

- `reply_when_addressed_with_context`
- `reply_when_followup_in_active_thread`
- `skip_when_context_too_weak`
- `store_only_when_memory_instruction`
- `web_only_when_question_is_time_sensitive`

### Invariants

- toute decision doit avoir un `rule_id`
- l'arbitrage ne compose pas le prompt
- l'arbitrage demande des sources, il ne les formate pas

### Fichiers probables

- [arbitrator.py](/home/vhserver/bt/windows_bot/arbitrator.py)
- [decision_tree.py](/home/vhserver/bt/windows_bot/decision_tree.py)
- [runtime_types.py](/home/vhserver/bt/windows_bot/runtime_types.py)

### Test produit

Le bot doit distinguer :
- une vraie relance contextuelle
- une phrase ambigue hors contexte
- une instruction memoire
- une question web temporelle

---

## Chantier 4 — Temporalite Reelle Dans Homegraph

### But

Faire remonter au bot les informations durables encore utiles, pas juste les plus faciles a extraire.

### Direction

Exploiter mieux cote Linux puis consommer cote Windows :
- `first_seen_at`
- `last_seen_at`
- `strength`
- `confidence`
- `status`

### Strategie simple

Introduire une idee de poids effectif :

```text
effective_weight = strength * freshness_decay
```

Effets attendus :
- les liens recents remontent mieux
- les vieux signaux faibles se tassent
- les items devenus obsoletes polluent moins `text_block`

### Ce que Windows doit prevoir

Ne pas supposer que la memoire longue est "vraie pour toujours".
Le runtime doit deja raisonner avec :
- `priority`
- `confidence`
- `stale`

### Fichiers probables cote Windows

- [context_sources.py](/home/vhserver/bt/windows_bot/context_sources.py)
- [prompt_composer.py](/home/vhserver/bt/windows_bot/prompt_composer.py)

### Test produit

Un vieux sujet ponctuel ne doit pas prendre le dessus sur une dynamique recente de conversation.

---

## Chantier 5 — Politique De Promotion Memoire

### But

Ne pas envoyer toute information dans la memoire longue.

### Trois classes recommandees

1. ephemere
- utile quelques minutes
- seulement memoire courte

2. session
- utile pour le stream ou la discussion en cours
- peut rester localement plus longtemps

3. durable
- preference stable
- relation recurrente
- sujet vraiment recurrent
- candidat `homegraph` / `mem0`

### Regles initiales simples

- question ponctuelle -> memoire courte seulement
- follow-up de thread -> memoire courte
- preference stable repetee -> `homegraph`
- souvenir semantique durable -> `mem0`

### Fichiers probables

- [arbitrator.py](/home/vhserver/bt/windows_bot/arbitrator.py)
- [bot_ollama.py](/home/vhserver/bt/windows_bot/bot_ollama.py)
- couche de memorisation post-reponse a extraire plus tard

### Test produit

Le bot ne doit pas memoriser comme "durable" une simple blague ou une question jetable d'un soir.

---

## Architecture A Respecter

Les travaux ci-dessus doivent converger vers :

1. perception
2. memoire courte
3. memoire longue
4. arbitrage
5. composition du prompt
6. generation / post-traitement

References :
- [architecture_target_vnext.md](/home/vhserver/bt/architecture_target_vnext.md)
- [runtime_architecture.md](/home/vhserver/bt/windows_bot/runtime_architecture.md)

Le point de vigilance principal :
- ne pas refaire un monolithe dans [bot_ollama.py](/home/vhserver/bt/windows_bot/bot_ollama.py)

---

## Recommandation Immediate

Le prochain chantier le plus rentable est :

1. extraire une vraie source `thread_context`
2. la brancher dans [context_sources.py](/home/vhserver/bt/windows_bot/context_sources.py)
3. faire consommer cette source par [arbitrator.py](/home/vhserver/bt/windows_bot/arbitrator.py)
4. laisser [prompt_composer.py](/home/vhserver/bt/windows_bot/prompt_composer.py) fusionner proprement :
   - `thread_context`
   - `homegraph`
   - `mem0`
   - memoire locale specialisee

Si ce point est bien fait, le bot gagnera plus en "compréhension conversationnelle" qu'avec une nouvelle base ou une nouvelle couche LLM.
