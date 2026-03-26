# Homegraph Workflow V2

## But

Rendre reproductible la chaine :

`mem0 export -> payload GPT -> prompt GPT V2 -> extraction JSON avec links -> merge SQLite -> viewer context`

La V2 ajoute explicitement une couche `links`.

## Raccourci

Les trois premieres etapes peuvent maintenant etre preparees en une commande :

```bash
env MEM0_ADMIN_KEY=... python3 homegraph/prepare_viewer_extraction.py twitch:streamer:viewer:alice --version v2
```

Cela produit :
- l'export mem0 viewer
- le payload Homegraph GPT
- le prompt V2 pret a envoyer a GPT

## Etapes

### 1. Export mem0 viewer

```bash
env MEM0_ADMIN_KEY=... python3 graphiti/export_viewer_memories.py twitch:streamer:viewer:alice --output homegraph/payloads/alice_export.json
```

### 2. Construire le payload Homegraph

```bash
python3 homegraph/build_viewer_payload.py homegraph/payloads/alice_export.json --output homegraph/payloads/alice_gpt_payload.json
```

### 3. Construire le prompt GPT V2

```bash
python3 homegraph/build_extraction_prompt.py homegraph/payloads/alice_gpt_payload.json --version v2 --output homegraph/payloads/alice_prompt_v2.txt
```

Template utilise :
- `homegraph/extraction_prompt_v2.md`

### 4. Faire produire l'extraction JSON par GPT

Sortie attendue :
- un JSON conforme au contrat V2
- avec `facts`
- avec `relations`
- et si pertinent avec `links`

Exemple de structure :
- `homegraph/extraction_output_example.json`

Exemple de fichier produit :
- `homegraph/payloads/alice_extraction_v2.json`

### 5. Merger dans SQLite

```bash
python3 homegraph/merge_extraction.py homegraph/payloads/alice_extraction_v2.json --model-name gpt-5 --source-ref mem0-export:twitch:streamer:viewer:alice
```

Le merge V2 fait maintenant :
- upsert du profil viewer
- upsert des facts
- upsert des relations V1
- upsert des entites V2
- upsert des liens V2
- upsert des evidences de liens

### 6. Construire le contexte viewer compact

```bash
python3 homegraph/build_viewer_context.py --viewer-id twitch:streamer:viewer:alice
```

Le builder :
- conserve le contrat Windows actuel
- mais peut deja s'appuyer sur les `links` V2 pour enrichir le contexte

### 7. Ou le recuperer via l'admin API locale

```bash
curl -sS \
  -H 'X-Admin-Key: ...' \
  http://127.0.0.1:8000/admin/homegraph/users/twitch:streamer:viewer:alice/context
```

## Statut

Workflow reproductible V2 :
- prompt V2 disponible
- merge `links` disponible
- builder compatible V2 disponible
- automatisation de l'appel GPT encore a faire
