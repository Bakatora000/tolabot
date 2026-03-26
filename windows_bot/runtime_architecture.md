# Architecture Runtime Windows

Cette note documente la structure interne actuelle du runtime Windows apres la refacto.

## But

Le point d'entree [bot_ollama.py](C:/Users/xuanp/BotTwitch/tolabot/windows_bot/bot_ollama.py) ne doit plus porter toute la logique du bot. La cible est :
- un orchestrateur mince
- des contrats internes stables
- une composition de prompt separee
- une collecte de contexte homogene
- un pipeline runtime testable hors integration Twitch complete

## Modules clefs

### [bot_ollama.py](C:/Users/xuanp/BotTwitch/tolabot/windows_bot/bot_ollama.py)

Responsabilites restantes :
- etat du bot
- integration TwitchIO
- acces aux structures memoire chargees en RAM
- couture entre les callbacks du bot et le pipeline

Le fichier ne doit plus recevoir de nouvelles branches metier sauf urgence.

### [runtime_pipeline.py](C:/Users/xuanp/BotTwitch/tolabot/windows_bot/runtime_pipeline.py)

Point principal du pipeline runtime.

Il porte maintenant :
- parsing et filtrage des messages entrants
- dispatch entrant immediat ou via file
- gestion de file
- dispatch des decisions non-modele
- pipeline modele
- resolution du contexte runtime
- resolution web SearXNG
- persistance locale et distante
- resume de chaine

### [runtime_types.py](C:/Users/xuanp/BotTwitch/tolabot/windows_bot/runtime_types.py)

Contient les contrats internes stables.

Objets principaux :
- `NormalizedEvent`
- `DecisionResult`
- `ContextSourceResult`
- `PromptPlan`
- `RuntimeContextBundle`
- `MessagePreparation`
- `RuntimePipelineDeps`
- `QueuedMessageContext`

### [arbitrator.py](C:/Users/xuanp/BotTwitch/tolabot/windows_bot/arbitrator.py)

Produit la decision runtime explicite.

Exemples de decisions :
- `channel_summary`
- `refuse_memory_instruction`
- `store_only`
- `social_reply`
- `skip_reply`
- `model_reply`

Chaque decision doit rester observable avec :
- `decision`
- `rule_id`
- `reason`

### [context_sources.py](C:/Users/xuanp/BotTwitch/tolabot/windows_bot/context_sources.py)

Homogeneise les sources de contexte.

Sources usuelles :
- `local_specialized`
- `local_viewer_thread`
- `conversation_graph`
- `facts_memory`
- `alias_resolution`
- `recent_focus`
- `mem0`
- `web`

### [prompt_composer.py](C:/Users/xuanp/BotTwitch/tolabot/windows_bot/prompt_composer.py)

Point unique de composition du prompt.

Il prend une decision et un ensemble de sources, puis produit un `PromptPlan`. Il ne doit pas re-decider.

## Contrats internes

### `DecisionResult`

Objet d'arbitrage principal.

Champs utiles :
- `decision` : action a prendre
- `rule_id` : identifiant stable de la regle
- `reason` : raison humaine/loggable
- `needs_web` : indique si un contexte web est requis
- `meta` : drapeaux additionnels de pipeline

Le runtime doit logger `decision` et `rule_id`.

### `ContextSourceResult`

Represente une source de contexte candidate.

Champs utiles :
- `source_id`
- `priority`
- `confidence`
- `stale`
- `text_block`

Le pipeline peut ainsi trier, tracer et composer sans connaitre la source concrete.

### `PromptPlan`

Represente la composition finale du prompt, deja decoupee en blocs :
- `system_block`
- `viewer_block`
- `conversation_block`
- `web_block`
- `style_block`
- `source_trace`

### `RuntimePipelineDeps`

Regroupe les callbacks dont le pipeline runtime a besoin pour persister et reconstruire le contexte.

Contrats actuellement exposes :
- `persist_local_turn_fn`
- `persist_local_and_remote_turn_fn`
- `remember_remote_turn_fn`
- `build_runtime_context_bundle_fn`

Le but est d'eviter la repetition de lambdas inline dans le runtime principal.

### `QueuedMessageContext`

Regroupe l'etat utile pour traiter un message sorti de la file :
- message de queue
- canal
- message prepare
- decision
- dependances runtime

## Flux cible

Le flux nominal d'un message mentionnant le bot est maintenant :

1. parsing du message entrant
2. filtrage rapide
3. mise en file ou traitement direct
4. preparation du message
5. arbitrage
6. si besoin, collecte du contexte
7. si besoin, resolution web
8. composition du prompt
9. appel modele
10. post-traitement
11. persistance

## Tests

Couverture principale actuelle :
- [test_bot_runtime.py](C:/Users/xuanp/BotTwitch/tolabot/windows_bot/test_bot_runtime.py)
- [test_runtime_types.py](C:/Users/xuanp/BotTwitch/tolabot/windows_bot/test_runtime_types.py)
- [test_runtime_pipeline.py](C:/Users/xuanp/BotTwitch/tolabot/windows_bot/test_runtime_pipeline.py)
- [test_context_sources.py](C:/Users/xuanp/BotTwitch/tolabot/windows_bot/test_context_sources.py)
- [test_prompt_composer.py](C:/Users/xuanp/BotTwitch/tolabot/windows_bot/test_prompt_composer.py)

## Discipline de refacto

Regles a garder :
- ne pas rajouter de branches metier directes dans [bot_ollama.py](C:/Users/xuanp/BotTwitch/tolabot/windows_bot/bot_ollama.py)
- garder `rule_id` stable et loggable
- faire entrer les nouvelles sources memoire via `ContextSourceResult`
- garder la composition du prompt hors de l'arbitrage
- preserver les seams de test patches sur `bot_ollama.py` tant que la suite runtime en depend

## Compatibilite Homegraph

La cible Linux `Homegraph v2` peut enrichir le contexte plus tard sans recabler le runtime Windows si :
- le contrat `ContextSourceResult` reste stable
- `PromptPlan` reste le point unique de composition
- le runtime continue de consommer du contexte via des sources homogenes plutot que via une structure memoire speciale
