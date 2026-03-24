# Contexte Codex — poste Windows (bot Twitch + Ollama + client mem0 distant)

## Objectif
Ce dépôt contient un bot Twitch Python qui tourne sur **mon PC Windows**. Le bot se connecte avec un **compte Twitch secondaire** à **ma propre chaîne Twitch**, écoute le chat, et répond uniquement quand il est mentionné avec `@nom_du_bot`.

Aujourd'hui, le bot utilise :
- TwitchIO / EventSub pour écouter le chat
- Ollama **en local sur mon PC** pour générer les réponses
- une **mémoire locale courte** stockée dans `chat_memory.json`

Je veux désormais **ajouter une vraie couche mémoire distante** via **mem0**, hébergée sur **mon serveur Linux cloud (CCX33)**. Le bot Windows devra donc :
- continuer à écouter le chat Twitch
- continuer à appeler Ollama en local
- **appeler une API HTTP distante** exposée sur mon serveur Linux pour lire/écrire la mémoire mem0

Le code doit rester simple, maintenable et compatible avec mon projet actuel.

---

## État actuel du dépôt
Fichiers importants déjà présents dans ce projet :
- `bot_ollama.py` : runtime Twitch principal
- `bot_logic.py` : logique pure, sanitation, prompts, mémoire locale, heuristiques
- `ollama_client.py` : appel HTTP vers Ollama local
- `bot_config.py` : lecture de la config `.env`
- `manage_bot.py` : commandes utilitaires / admin
- `chat_memory.json` : mémoire locale courte actuelle

Comportement actuel notable :
- le bot ne répond que si un message contient la mention du bot
- il applique un cooldown global et par viewer
- il détecte certaines charades/devinettes
- il garde un contexte local viewer/global avec expiration
- il appelle `ask_ollama(...)` avec `viewer_context` et `global_context`

---

## Cible fonctionnelle
Je veux faire évoluer le bot pour utiliser une mémoire distante mem0 **sans casser le comportement actuel**.

### Règle produit
Quand un message mentionne le bot :
1. le bot nettoie/analyse le message
2. il décide s'il doit répondre
3. **avant l'appel à Ollama**, il récupère un contexte mémoire pertinent depuis l'API mem0 distante
4. il injecte ce contexte dans le prompt Ollama
5. il génère la réponse avec Ollama local
6. **après** la réponse, il envoie à l'API mem0 les informations utiles à mémoriser

---

## Contraintes techniques importantes
- **Le bot reste sur Windows**
- **Ollama reste en local sur Windows**
- **mem0 ne tourne pas sur Windows** : il sera derrière une API sur mon serveur Linux
- le bot ne doit **pas dépendre directement** d'une installation locale mem0
- il faut passer par des appels HTTP vers mon serveur
- les secrets/config doivent venir du `.env`
- il faut prévoir des timeouts et une gestion d'erreur propre
- si l'API mémoire distante tombe, le bot doit **continuer à fonctionner** avec un mode dégradé

---

## Ce que je veux que tu implémentes côté Windows
Je veux que tu modifies le dépôt pour introduire une couche cliente claire pour la mémoire distante.

### Architecture souhaitée
Créer un module dédié, par exemple :
- `memory_client.py`

Ce module devra encapsuler les appels HTTP vers mon serveur Linux.

### Fonctions attendues
Prévoir au minimum des fonctions du style :
- `get_memory_context(channel: str, viewer: str, message: str) -> dict`
- `store_memory_turn(channel: str, viewer: str, user_message: str, bot_reply: str | None, metadata: dict | None = None) -> None`
- `healthcheck_memory_api() -> bool`

Tu peux ajuster les noms/signatures si c'est plus propre, mais l'intention doit rester la même.

---

## Contrat d'API attendu côté Windows
Le bot Windows doit appeler une API HTTP distante. Prévois le code client en partant de ce contrat.

### 1) Healthcheck
- `GET /health`
- réponse attendue :
```json
{ "status": "ok" }
```

### 2) Récupération de contexte mémoire
- `POST /memory/context`
- payload JSON :
```json
{
  "channel": "nom_de_la_chaine",
  "viewer": "pseudo_viewer",
  "message": "message utilisateur courant",
  "limit": 8
}
```

- réponse JSON attendue :
```json
{
  "viewer_context": "texte résumé ou concaténé pour ce viewer",
  "global_context": "texte résumé ou concaténé global canal",
  "items": [
    {
      "id": "...",
      "memory": "...",
      "score": 0.91,
      "metadata": {
        "channel": "...",
        "viewer": "..."
      }
    }
  ]
}
```

### 3) Écriture mémoire
- `POST /memory/turn`
- payload JSON :
```json
{
  "channel": "nom_de_la_chaine",
  "viewer": "pseudo_viewer",
  "user_message": "texte utilisateur nettoyé",
  "bot_reply": "réponse finale envoyée",
  "message_id": "id optionnel",
  "metadata": {
    "source": "twitch",
    "bot": "nom_du_bot"
  }
}
```

- réponse JSON attendue :
```json
{
  "status": "stored"
}
```

---

## Variables d'environnement à prévoir côté Windows
Ajouter au `.env.example` et au chargement de config des variables du style :

```env
MEMORY_API_ENABLED=true
MEMORY_API_BASE_URL=https://mon-serveur.example.com
MEMORY_API_KEY=
MEMORY_API_TIMEOUT_SECONDS=10
MEMORY_API_VERIFY_SSL=true
MEMORY_API_CONTEXT_LIMIT=8
MEMORY_FALLBACK_TO_LOCAL=true
```

Si besoin, tu peux proposer de meilleurs noms, mais garde cette logique :
- activation on/off
- URL de base
- clé API éventuelle
- timeout
- vérification SSL
- limite de résultats
- fallback vers mémoire locale

---

## Comportement attendu en mode dégradé
Si l'API mémoire est indisponible, trop lente ou renvoie une erreur :
- ne pas faire planter le bot
- logger l'incident
- continuer avec le comportement existant
- idéalement, retomber sur `build_chat_context(...)` avec la mémoire locale actuelle si `MEMORY_FALLBACK_TO_LOCAL=true`

---

## Intégration attendue dans le code existant
Je veux une intégration minimalement invasive.

### Avant l'appel à Ollama
Dans `bot_ollama.py`, au moment où le code construit actuellement `chat_context = build_chat_context(...)`, je veux une logique du type :
1. tenter de récupérer un contexte via l'API distante mem0
2. si succès, utiliser ce contexte distant
3. sinon, fallback local

### Après l'appel à Ollama
Après génération de la réponse finale :
- envoyer le tour de conversation à l'API mémoire distante
- cela doit être non bloquant autant que possible, ou au minimum robuste
- en cas d'échec, logger sans casser la réponse Twitch

---

## Style de code attendu
- Python clair, simple, sans sur-ingénierie
- type hints quand c'est utile
- fonctions petites et testables
- logs explicites
- pas de dépendances inutiles
- réutiliser `requests` si possible, déjà utilisé dans le projet

---

## Tests souhaités
Si tu ajoutes des tests, privilégier des tests unitaires simples sur :
- construction des payloads HTTP
- gestion des réponses API
- fallback quand l'API échoue
- intégration du contexte distant dans l'appel à Ollama

Tu peux mocker `requests`.

---

## Ce qu'il faut éviter
- ne pas casser la logique Twitch existante
- ne pas retirer la mémoire locale tant que la mémoire distante n'est pas stable
- ne pas introduire d'async compliqué si ce n'est pas nécessaire
- ne pas coder en dur l'URL du serveur ou les secrets
- ne pas supposer que mem0 tourne localement sur Windows

---

## Résultat attendu
Je veux que le dépôt Windows soit modifié pour que le bot puisse :
- utiliser Ollama localement
- récupérer un contexte mémoire distant depuis mon serveur Linux
- stocker les tours de conversation dans mem0 via cette API
- continuer à fonctionner même si la mémoire distante est HS

Merci de :
1. proposer les fichiers à créer/modifier
2. implémenter le code
3. mettre à jour `.env.example`
4. ajouter un court paragraphe dans `README.md` expliquant la mémoire distante
5. rester cohérent avec l'architecture déjà présente
