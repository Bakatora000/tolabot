# Bot Twitch + LLM

Bot Twitch francophone qui :
- lit les messages mentionnant `@anneaunimouss`
- envoie la demande a Ollama ou OpenAI
- renvoie la reponse dans le chat
- garde une memoire locale courte des echanges recents
- peut preparer une integration memoire distante via mem0

Doc interne utile pour la structure runtime :
- [runtime_architecture.md](C:/Users/xuanp/BotTwitch/tolabot/windows_bot/runtime_architecture.md)

## Prerequis

- Windows
- Python 3.11+
- soit Ollama installe localement avec un modele disponible, par exemple `qwen3.5:latest`
- soit une cle API OpenAI pour utiliser un modele mini
- une application Twitch avec `client_id` et `client_secret`

## Installation

Installe les dependances :

```powershell
pip install -r requirements.txt
```

## Configuration

Copie `.env.example` vers `.env`, puis remplis :

```env
TWITCH_CLIENT_ID=
TWITCH_CLIENT_SECRET=
TWITCH_BOT_ID=
TWITCH_OWNER_ID=
TWITCH_TOKEN=oauth:
TWITCH_CHANNEL=

LLM_PROVIDER=ollama
OLLAMA_URL=http://localhost:11434/api/chat
OLLAMA_MODEL=qwen3.5:latest
OPENAI_CHAT_MODEL=gpt-5-mini
OPENAI_WEB_SEARCH_ENABLED=false
OPENAI_WEB_SEARCH_MODE=auto
WEB_SEARCH_ENABLED=false
WEB_SEARCH_PROVIDER=searxng
WEB_SEARCH_MODE=auto
SEARXNG_BASE_URL=http://127.0.0.1:8888
WEB_SEARCH_TIMEOUT_SECONDS=8
WEB_SEARCH_MAX_RESULTS=5
MEM0_ENABLED=false
MEM0_API_BASE_URL=https://your-mem0-api.example.com/api/memory
MEM0_API_KEY=
MEM0_TIMEOUT_SECONDS=10
MEM0_VERIFY_SSL=true
MEM0_CONTEXT_LIMIT=5
MEM0_FALLBACK_LOCAL=true
GLOBAL_COOLDOWN_SECONDS=2
USER_COOLDOWN_SECONDS=8
MESSAGE_QUEUE_MAX_SIZE=6
MESSAGE_QUEUE_MAX_AGE_SECONDS=25
CHAT_MEMORY_TTL_HOURS=10
DEBUG_CHAT_MEMORY=false
```

Notes :
- `TWITCH_CHANNEL` est la chaine cible
- `TWITCH_OWNER_ID` est l'identifiant Twitch de cette chaine
- `TWITCH_BOT_ID` est l'identifiant Twitch du compte bot
- `TWITCH_TOKEN` est le token OAuth du bot
- `LLM_PROVIDER=ollama` garde le mode local actuel
- `LLM_PROVIDER=openai` fait passer le bot par l'API OpenAI
- `OPENAI_WEB_SEARCH_ENABLED=true` autorise l'outil web search quand `LLM_PROVIDER=openai`
- `OPENAI_WEB_SEARCH_MODE=auto` l'active seulement sur les questions qui semblent demander de l'info recente ou web
- `OPENAI_WEB_SEARCH_MODE=always` le force sur toutes les requetes OpenAI
- `OPENAI_WEB_SEARCH_MODE=off` le coupe meme si `OPENAI_WEB_SEARCH_ENABLED=true`
- `WEB_SEARCH_ENABLED=true` active une recherche web externe pour enrichir surtout Ollama/Qwen
- `WEB_SEARCH_PROVIDER=searxng` utilise une instance SearXNG locale ou auto-hebergee
- `WEB_SEARCH_MODE=auto` ne cherche que pour des questions externes du type actualite, meteo, prix, president, date de sortie
- `SEARXNG_BASE_URL` pointe vers ton instance locale, par exemple `http://127.0.0.1:8888`
- `CHAT_MEMORY_TTL_HOURS` controle la duree de conservation de la memoire de chat
- `DEBUG_CHAT_MEMORY=true` affiche le contexte reinjecte dans les logs
- `MEM0_ENABLED=true` active le client HTTP vers l'API memoire distante
- `MEM0_FALLBACK_LOCAL=true` conserve la memoire locale comme secours si l'API distante echoue
- `MESSAGE_QUEUE_MAX_SIZE` limite le nombre de messages en attente quand le chat accelere
- `MESSAGE_QUEUE_MAX_AGE_SECONDS` ignore un message devenu trop ancien dans la file
- `ADMIN_UI_ENABLED=true` active l'UI admin locale Windows
- `ADMIN_API_LOCAL_URL` est l'URL locale atteinte via tunnel SSH
- `MEM0_ADMIN_KEY` est la cle d'auth admin distincte de `MEM0_API_KEY`
- `ADMIN_SSH_HOST` et `ADMIN_SSH_USER` servent a ouvrir le tunnel SSH
- le tunnel V1 attendu est `localhost:9000 -> SSH -> 127.0.0.1:8000`
- `OPENAI_REVIEW_ENABLED=true` active l'analyse de souvenirs via OpenAI
- `OPENAI_API_KEY` est la cle API OpenAI
- `OPENAI_CHAT_MODEL=gpt-5-mini` est un bon choix pour remplacer Ollama a cout modere
- `OPENAI_WEB_SEARCH_ENABLED=true` peut aider sur les questions d'actualite ou d'information externe, mais ajoute de la latence et du cout
- `WEB_SEARCH_ENABLED=true` avec `WEB_SEARCH_PROVIDER=searxng` permet d'ajouter un contexte web a Qwen sans cout API par requete LLM
- `OPENAI_REVIEW_MODEL=gpt-5-mini` est un bon choix pour une revue structuree a cout modere
- `OPENAI_REVIEW_MAX_RECORDS` limite le nombre de souvenirs envoyes a l'analyse pour reduire les tokens
- `OPENAI_REVIEW_TIMEOUT_SECONDS=90` laisse plus de marge pour les exports plus gros

## Generation du token Twitch

Pour generer ou mettre a jour automatiquement le token du bot :

```powershell
py .\manage_bot.py get-token
```

Le script met a jour automatiquement :
- `TWITCH_TOKEN`
- `TWITCH_BOT_ID`

## Lancement

En console :

```powershell
py .\manage_bot.py run-ollama
```

En arriere-plan :

```powershell
py .\manage_bot.py run-bg-ollama
```

Statut du process de fond :

```powershell
py .\manage_bot.py status-bg
```

Arret :

```powershell
py .\manage_bot.py stop-bg
```

Redemarrage :

```powershell
py .\manage_bot.py restart-bg
```

## Diagnostic

Verifier la config :

```powershell
py .\manage_bot.py status
```

Diagnostic global :

```powershell
py .\manage_bot.py diagnose
```

Verifier le token Twitch :

```powershell
py .\manage_bot.py validate-token
```

Verifier l'API memoire distante :

```powershell
py .\manage_bot.py memory-health
```

Verifier l'API admin locale :

```powershell
py .\manage_bot.py admin-health
```

Lancer l'UI admin locale :

```powershell
py .\manage_bot.py run-admin-ui
```

Dans l'UI admin, les actions suivantes existent maintenant :
- `Exporter ce viewer` : export brut complet
- `Exporter pour revue` : export compact optimise tokens
- `Analyser avec GPT` : analyse structuree via OpenAI
- `Purger ce viewer`
- `Valider` / `Refuser` : staging visuel des propositions de revue
- `Commit` : applique en lot uniquement les propositions acceptees

Workflow review actuel :
- selection d'un viewer
- export brut ou export compact `review`
- analyse GPT avec severite reglable
- validation admin visuelle proposition par proposition
- `Commit` global pour appliquer les `delete` / `rewrite`

Actions appliquees au commit :
- `delete` : suppression de la memoire cible
- `rewrite` : creation du nouveau souvenir puis suppression de l'ancien
- `keep` / `review` : aucune mutation backend

Limites volontaires du POC :
- pas d'action `merge` pour le moment
- `OPENAI_REVIEW_MAX_RECORDS=15` a `20` recommande pour limiter latence et tokens

Lister les modeles Ollama detectes :

```powershell
py .\manage_bot.py ollama-models
```

## Memoire distante mem0

Le bot peut maintenant etre configure pour parler a une API memoire distante compatible avec le contrat du service Linux sur `memory.example.net`.

Dans l'etat actuel :
- mem0 sert de memoire generale durable, reutilisable d'un live a l'autre
- le bot lit mem0 avant Ollama pour les cas generaux
- le bot ecrit dans mem0 apres reponse pour les echanges generaux utiles

Architecture retenue :
- mem0 : memoire longue, semantique, cross-live
- memoire locale : fils courts et cas specialises

Important :
- les charades/devinettes et autres fils multi-messages immediats restent geres prioritairement par la memoire locale
- mem0 ne remplace pas la logique locale de fil actif pour ces cas

## Recherche web locale avec SearXNG

Le bot peut maintenant enrichir le prompt avec un `web_context` externe, utile surtout avec `LLM_PROVIDER=ollama`.

Configuration type :

```env
LLM_PROVIDER=ollama
WEB_SEARCH_ENABLED=true
WEB_SEARCH_PROVIDER=searxng
WEB_SEARCH_MODE=auto
SEARXNG_BASE_URL=http://127.0.0.1:8888
WEB_SEARCH_TIMEOUT_SECONDS=8
WEB_SEARCH_MAX_RESULTS=5
```

Comportement :
- pas de recherche web sur les questions purement conversationnelles du chat
- recherche web seulement sur certaines requetes externes ou recentes en mode `auto`
- si SearXNG ne repond pas, le bot continue normalement sans contexte web

Si `MEM0_ENABLED=false`, le bot continue d'utiliser uniquement la memoire locale actuelle.

## Memoire ciblee du streamer

Le runtime Windows supporte une voie legere de memoire ciblee reservee au streamer.

But :
- permettre au streamer d'ajouter un fait durable sur un viewer cible
- sans attribuer ce souvenir au streamer lui-meme

Exemples :

```text
@anneaunimouss pour info, @viewer_a est feru de defis sur Valheim
@anneaunimouss note que viewer_b aime Valheim et Enshrouded
```

Effet :
- extraction `viewer cible + fait`
- ecriture directe dans mem0 sur le `user_id` du viewer cible
- `source=twitch_owner_targeted_memory`
- pas d'appel Ollama pour cette commande

Contrainte :
- fonctionnalite reservee au streamer

## Memoire conversationnelle

Le bot garde une memoire locale courte :
- par chaine
- par viewer
- avec expiration automatique

Fichier utilise :
- `chat_memory.json`

Voir l'etat de la memoire :

```powershell
py .\manage_bot.py chat-memory-status
```

Vider toute la memoire :

```powershell
py .\manage_bot.py clear-chat-memory
```

Vider la memoire d'un viewer :

```powershell
py .\manage_bot.py clear-chat-memory --viewer alice
```

### Cas pris en charge

- contexte recent par viewer
- conversations en plusieurs messages
- charades/devinettes decoupees en plusieurs etapes
- separation des fils actifs entre deux charades successives

## File d'attente chat

Le bot utilise maintenant une file FIFO bornee pour absorber les pics de messages :
- les mentions du bot sont mises en file plutot que jetees immediatement
- un seul worker traite les messages un par un
- si la file est pleine, le plus ancien message est supprime
- si un message reste trop longtemps en attente, il est ignore

Cette file complete les cooldowns :
- les cooldowns evitent que le bot poste trop vite
- la file evite de perdre brutalement une mention legitime pendant un pic de chat

## Tests

Lancer les tests :

```powershell
python -m unittest test_bot_logic.py test_ollama_client.py test_bot_runtime.py
```

Tests d'integration Windows/Linux en reel :

```powershell
$env:RUN_WINDOWS_LINUX_INTEGRATION="1"
python -m unittest test_windows_linux_integration.py
```

Notes :
- cette suite ouvre le tunnel SSH admin configure dans `.env`
- elle teste l'API admin Linux via `127.0.0.1:9000`
- les checks mem0 publics ne tournent que si `MEM0_ENABLED`, `MEM0_API_BASE_URL` et `MEM0_API_KEY` sont configures
- elle nettoie les souvenirs de test crees pendant l'execution

## Fichiers principaux

- `manage_bot.py` : commandes d'administration et lancement
- `bot_ollama.py` : runtime Twitch principal
- `ollama_client.py` : appels Ollama
- `bot_logic.py` : logique pure, sanitation, memoire, prompt
- `twitch_auth.py` : flux OAuth Twitch

## Depannage rapide

Si le bot ne repond pas :

1. verifie qu'Ollama repond :
```powershell
Invoke-WebRequest http://localhost:11434/api/tags -UseBasicParsing
```

2. verifie le token Twitch :
```powershell
py .\manage_bot.py validate-token
```

3. active les logs de memoire si besoin :
```env
DEBUG_CHAT_MEMORY=true
```

4. vide la memoire si un ancien contexte pollue le comportement :
```powershell
py .\manage_bot.py clear-chat-memory
```
