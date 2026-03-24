# Contexte Codex — serveur Linux (service mem0 pour bot Twitch)

## Objet

Ce document est destiné a Codex qui travaillera sur le serveur Linux cloud.

Le but n'est pas de faire tourner le bot Twitch complet sur Linux.
Le bot Twitch principal tourne sur un PC Windows.

Le serveur Linux doit heberger :
- un service HTTP expose sur `memory.example.net`
- qui encapsule mem0
- et qui sert de backend memoire distant pour le bot Windows

Le bot Windows ne doit jamais parler directement a mem0.
Il doit parler uniquement a cette API HTTP.

---

## Etat du projet global

Le zip fourni contient le code actuel du bot Windows.

Le bot Windows :
- utilise TwitchIO / EventSub
- utilise Ollama en local sur Windows
- possede deja une logique de memoire locale et de gestion de contexte
- doit evoluer pour utiliser mem0 distant a la place de `chat_memory.json` quand mem0 est active

Le serveur Linux :
- ne gere pas Twitch
- ne gere pas Ollama
- ne gere que la couche memoire

---

## Decision d'architecture

Stack memoire retenue :
- **Mem0 OSS**
- **Qdrant** pour la partie vectorielle / recherche
- **SQLite history** selon le chemin recommande par la doc Mem0 OSS

Reference officielle :
- [Mem0 OSS overview](https://docs.mem0.ai/open-source/overview)

Ce serveur doit donc heberger au minimum :
- le service API HTTP
- mem0
- Qdrant
- le stockage persistant necessaire

---

## Domaine et exposition reseau

Le domaine retenu pour l'API est :

- `memory.example.net`

Exposition attendue :
- reverse proxy HTTPS
- certificat TLS valide

Approche pragmatique attendue :
- Nginx ou Caddy
- Certbot si Nginx est choisi

Ce n'est pas du "reverse DNS".
Le besoin est un **reverse proxy HTTP(S)**.

---

## Contrat d'API

Le contrat a suivre est dans :

- `contrat_api_bot_mem0.md`

Ce contrat est maintenant la source de verite pour :
- les endpoints
- l'authentification
- les payloads JSON
- la convention `user_id`
- les exemples d'appel

---

## Convention d'identite retenue

Format retenu :

- `user_id = twitch:<channel_login>:viewer:<viewer_login>`

Exemple :

- `twitch:streamer:viewer:alice`

En complement, les metadonnees doivent contenir quand utile :
- `channel`
- `viewer`
- `source`
- `message_id`
- `session_id` optionnel

Objectif :
- memoire persistante individuelle par viewer
- reutilisable d'un live a l'autre
- sans melanger tous les viewers dans une seule memoire de chaine

---

## Ce que le backend memoire doit stocker

Le systeme memoire doit accepter :
- des souvenirs relativement stables
- des fragments de chat bruts quand ils sont juges utiles

Ce n'est pas uniquement une base de "faits utilisateur".
On veut aussi pouvoir retenir des elements utiles d'une discussion de live.

Exemples de contenus a supporter :
- preference explicite d'un viewer
- contexte rappelable plus tard
- morceau utile d'une conversation
- information recurente sur un viewer

Il faut en revanche :
- limiter la taille des textes
- dedupliquer raisonnablement
- eviter l'explosion de volume

---

## Politique de recherche memoire

Le bot Windows utilisera `/search` :
- avant certaines reponses Ollama
- notamment sur les messages de rappel du type :
  - "tu te souviens de..."
  - "on avait parle de..."
  - "hier tu m'avais dit..."

Donc le backend Linux doit privilegier :
- une recherche rapide
- des resultats textuels simples a reinjecter
- un schema de reponse stable

Le bot Windows fera l'orchestration du prompt.
Le backend Linux ne doit pas faire de logique de prompt.

---

## Politique de fallback

Decision retenue :
- si mem0 est active et utilisable, elle remplace la memoire locale JSON
- la memoire locale actuelle ne doit pas devenir la source principale

Le bot Windows pourra garder une tolerance aux pannes,
mais l'objectif fonctionnel est bien que mem0 devienne la memoire de reference.

---

## Endpoints attendus

Le service Linux doit exposer a minima :

- `GET /health`
- `POST /search`
- `POST /remember`
- `POST /forget`

Optionnel mais recommande :

- `POST /recent`

Format, auth et erreurs :
- voir `contrat_api_bot_mem0.md`

---

## Authentification

Auth simple par cle statique :

Header obligatoire :

```http
X-API-Key: <MEM0_API_KEY>
```

Comportement attendu :
- 401 si le header est absent
- 403 si la cle est invalide

---

## Exigences de robustesse

Le service Linux doit :
- valider les payloads
- ne jamais renvoyer de stacktrace brute
- journaliser proprement
- renvoyer des JSON stables
- gerer les cas mem0 indisponible / Qdrant indisponible

Journalisation attendue :
- endpoint
- statut HTTP
- duree
- `user_id` si present

---

## Idempotence / deduplication

Sujet a traiter cote Linux :
- `metadata.message_id` peut servir de cle d'idempotence pratique

Recommandation pragmatique :
- eviter de stocker deux fois le meme souvenir si on recoit le meme `message_id`
- au minimum pour `/remember`

Ce n'est pas strictement obligatoire pour le MVP,
mais c'est fortement recommande pour eviter les doublons si le client Windows reessaie.

---

## Choix techniques attendus cote Linux

Attendu :
- Python
- service HTTP simple et maintenable
- schema clair
- config via variables d'environnement
- logs lisibles

Choix raisonnables acceptables :
- FastAPI ou Flask
- systemd pour faire tourner le service
- Qdrant local ou conteneurise
- reverse proxy Nginx

Priorite :
- simplicite
- stabilite
- lisibilite
- faible surface de surprise

---

## Variables d'environnement minimales cote Linux

Base minimale attendue :

```env
MEM0_API_KEY=xxxxxxxxxxxxxxxx
MEM0_DEFAULT_LIMIT=5
MEM0_HOST=127.0.0.1
MEM0_PORT=8000
LOG_LEVEL=INFO
```

Probablement necessaires en pratique aussi :
- configuration mem0
- configuration Qdrant
- chemins de persistance
- eventuellement `OPENAI_API_KEY` ou autre provider si requis par la config mem0 choisie

Codex Linux doit verifier la doc mem0 OSS et proposer une configuration compatible avec :
- Mem0 OSS
- Qdrant
- SQLite history

---

## Ce qu'on attend de Codex cote Linux

Le travail cote Linux doit produire :

1. un service HTTP conforme au contrat
2. une integration mem0 propre
3. une persistance correcte
4. un deploiement simple sur le serveur
5. un mode d'execution durable (`systemd`)
6. une exposition HTTPS sur `memory.example.net`

---

## Livrables attendus cote Linux

Au minimum :
- code du service API
- fichier(s) de config ou `.env.example`
- instructions de lancement local
- unite `systemd` si pertinente
- configuration reverse proxy proposee
- notes de deploiement

---

## Contraintes importantes

Ne pas faire :
- un couplage direct bot Windows <-> mem0 SDK
- une logique metier Twitch cote Linux
- une dependance inutile a l'historique de notre conversation locale

Faire :
- une API nette
- des entrees/sorties strictes
- une architecture facile a debug
- une configuration lisible

---

## Point de vigilance principal

La convention correcte a appliquer est celle du contrat revise :

- `user_id = twitch:<channel_login>:viewer:<viewer_login>`

---

## Resume executif

Tu travailles sur un backend memoire Linux pour un bot Twitch qui tourne sur Windows.

Le backend doit :
- exposer une API HTTP securisee
- encapsuler mem0 OSS
- utiliser Qdrant + SQLite history
- servir une memoire persistante par viewer
- etre deployable derriere `memory.example.net`

Le zip du bot Windows est la pour contexte d'integration,
pas pour faire tourner le bot lui-meme sur Linux.
