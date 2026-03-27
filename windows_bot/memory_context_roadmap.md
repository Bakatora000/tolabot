# Roadmap Memoire Contextuelle Et Temporelle

## Priorite encore valide

Ordre recommande:
1. memoire courte multi-utilisateurs
2. `thread_context`
3. arbitrage appuye sur ce contexte
4. temporalite Homegraph
5. promotion memoire

## Pourquoi ce memo existe encore

Ne pas repartir sur "plus de memoire" indistinctement.
Le vrai gain conversationnel vient toujours de:
- meilleur contexte recent
- meilleur arbitrage
- meilleure separation entre memoire courte et memoire durable

## Contrat minimum a garder en tete

Source cible:

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

Le `text_block` doit resumer seulement:
- sujet recent
- participants utiles
- derniere question ouverte
- dernier tour adresse au bot
- correction ou desaccord recent si pertinent

## Invariants runtime

- l'arbitrage decide, il ne compose pas le prompt
- `prompt_composer` fusionne les sources, il ne decide pas
- ne pas refaire un monolithe dans `bot_ollama.py`

## Fichiers probables

- [context_sources.py](C:/Users/xuanp/BotTwitch/tolabot/windows_bot/context_sources.py)
- [runtime_types.py](C:/Users/xuanp/BotTwitch/tolabot/windows_bot/runtime_types.py)
- [arbitrator.py](C:/Users/xuanp/BotTwitch/tolabot/windows_bot/arbitrator.py)
- [prompt_composer.py](C:/Users/xuanp/BotTwitch/tolabot/windows_bot/prompt_composer.py)
- [thread_context.py](C:/Users/xuanp/BotTwitch/tolabot/windows_bot/thread_context.py)

## Etat 2026-03-27

Le rapatriement Linux -> Windows pour la memoire utile est maintenant acte:
- memoire durable viewer sur SQLite local
- `homegraph` sur SQLite local
- runtime Windows et admin Windows sans dependance Linux active

La prochaine session n'a donc plus a recadrer cette migration.

Ce memo reste utile comme garde-fou:
- ne pas perdre la priorite `thread_context`
- ne pas laisser Homegraph/UI faire oublier le besoin conversationnel central
- ne pas compenser un arbitrage faible par "plus de memoire" indistinctement
