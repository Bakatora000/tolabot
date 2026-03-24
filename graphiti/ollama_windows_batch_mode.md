# Graphiti Batch Mode — Linux Graphiti + Ollama Windows

## Principe

Le serveur Linux heberge :
- Graphiti
- Kuzu
- les scripts d'export/import

Le PC Windows heberge :
- Ollama
- les modeles lourds

Le PC Windows n'etant pas allume en permanence, Ollama Windows ne doit pas devenir une dependance runtime permanente du serveur Linux.

Le bon modele est donc :
- **mode batch opportuniste**
- tunnel SSH inverse uniquement pendant une session d'ingestion Graphiti

---

## Pourquoi ce choix

Le PC Windows est la meilleure machine pour les modeles :
- 64 Go RAM
- 16 Go VRAM

Le serveur Linux doit rester leger :
- pas d'Ollama installe localement
- pas d'exposition publique d'un provider LLM
- pas de service Graphiti permanent dependant de Windows

---

## Topologie

Pendant une session batch :

```text
Windows Ollama 127.0.0.1:11434
        ^
        | reverse SSH tunnel
        v
Linux   127.0.0.1:11434
        ^
        |
Graphiti import offline
```

Hors session batch :
- le tunnel n'existe pas
- Graphiti reste installe mais n'importe rien
- rien ne casse cote Linux

---

## Commande Tunnel Recommandee

Depuis Windows :

```bash
ssh -N ^
  -o ExitOnForwardFailure=yes ^
  -o ServerAliveInterval=30 ^
  -o ServerAliveCountMax=3 ^
  -R 127.0.0.1:11434:127.0.0.1:11434 ^
  vhserver@linux-host
```

Point important :
- `127.0.0.1:` cote `-R` est volontaire
- ainsi, le port reverse n'est accessible que localement sur Linux

---

## Config Graphiti Cible

Dans `graphiti/.env.example`, la cible recommandee est :

```env
GRAPHITI_LLM_API_KEY=ollama
GRAPHITI_LLM_BASE_URL=http://127.0.0.1:11434/v1
GRAPHITI_LLM_MODEL=llama3.3:7b

GRAPHITI_EMBEDDING_API_KEY=ollama
GRAPHITI_EMBEDDING_BASE_URL=http://127.0.0.1:11434/v1
GRAPHITI_EMBEDDING_MODEL=nomic-embed-text
```

Cela suppose que le tunnel batch est ouvert.

---

## Sequence D'Usage

### 1. Cote Windows

- demarrer le PC Windows
- lancer Ollama
- verifier que le modele chat live continue de fonctionner si necessaire
- verifier que les modeles Graphiti sont presents

Modeles recommandes :
- chat live : `qwen3.5`
- Graphiti LLM : `llama3.3:7b`
- Graphiti embeddings : `nomic-embed-text`

Exemple :

```bash
ollama pull llama3.3:7b
ollama pull nomic-embed-text
```

### 2. Ouvrir le tunnel reverse

Depuis Windows :

```bash
ssh -N ^
  -o ExitOnForwardFailure=yes ^
  -o ServerAliveInterval=30 ^
  -o ServerAliveCountMax=3 ^
  -R 127.0.0.1:11434:127.0.0.1:11434 ^
  vhserver@linux-host
```

### 3. Verifier cote Linux

```bash
curl http://127.0.0.1:11434/api/tags
curl http://127.0.0.1:11434/v1/models
```

Si cela repond :
- Linux voit bien Ollama Windows via le tunnel

### 4. Lancer l'import Graphiti

Dans `(.venv-graphiti)` :

```bash
python graphiti/export_viewer_memories.py twitch:streamer:viewer:alice
python graphiti/import_viewer_memories.py graphiti/imports/alice.json --dry-run
python graphiti/import_viewer_memories.py graphiti/imports/alice.json
```

### 5. Fin de session

- fermer le tunnel SSH
- le serveur Linux revient a un etat autonome

---

## Contraintes

- si Windows est eteint, aucun import Graphiti reel ne doit etre lance
- Graphiti ne doit pas etre transforme en service systemd dependant du tunnel
- l'import doit rester manuel / batch tant que le workflow n'est pas stabilise

---

## Recommandation Finale

Pour la phase actuelle :
- **oui** a Graphiti sur Linux
- **oui** a Ollama sur Windows
- **oui** a un reverse tunnel SSH batch
- **non** a une dependance permanente du serveur Linux vers le PC Windows
