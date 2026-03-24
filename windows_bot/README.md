# Bot Twitch + Ollama

Bot Twitch francophone qui :
- lit les messages mentionnant `@anneaunimouss`
- envoie la demande a Ollama
- renvoie la reponse dans le chat
- garde une memoire locale courte des echanges recents
- peut preparer une integration memoire distante via mem0

## Prerequis

- Windows
- Python 3.11+
- Ollama installe localement
- un modele Ollama deja disponible, par exemple `qwen3.5:latest`
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

OLLAMA_URL=http://localhost:11434/api/chat
OLLAMA_MODEL=qwen3.5:latest
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
- `CHAT_MEMORY_TTL_HOURS` controle la duree de conservation de la memoire de chat
- `DEBUG_CHAT_MEMORY=true` affiche le contexte reinjecte dans les logs
- `MEM0_ENABLED=true` active le client HTTP vers l'API memoire distante
- `MEM0_FALLBACK_LOCAL=true` conserve la memoire locale comme secours si l'API distante echoue
- `MESSAGE_QUEUE_MAX_SIZE` limite le nombre de messages en attente quand le chat accelere
- `MESSAGE_QUEUE_MAX_AGE_SECONDS` ignore un message devenu trop ancien dans la file

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

Lister les modeles Ollama detectes :

```powershell
py .\manage_bot.py ollama-models
```

## Memoire distante mem0

Le bot peut maintenant etre configure pour parler a une API memoire distante compatible avec le contrat du service Linux sur `olala.expevay.net`.

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

Si `MEM0_ENABLED=false`, le bot continue d'utiliser uniquement la memoire locale actuelle.

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
