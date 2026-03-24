# Homegraph Workflow V1

## But

Rendre reproductible la chaine :

`mem0 export -> payload GPT -> prompt GPT -> extraction JSON -> merge SQLite -> viewer context`

## Etapes

### 1. Export mem0 viewer

```bash
env MEM0_ADMIN_KEY=... python3 graphiti/export_viewer_memories.py twitch:streamer:viewer:alice --output homegraph/payloads/alice_export.json
```

### 2. Construire le payload Homegraph

```bash
python3 homegraph/build_viewer_payload.py homegraph/payloads/alice_export.json --output homegraph/payloads/alice_gpt_payload.json
```

### 3. Construire le prompt GPT pret a l'emploi

```bash
python3 homegraph/build_extraction_prompt.py homegraph/payloads/alice_gpt_payload.json --output homegraph/payloads/alice_prompt.txt
```

### 4. Faire produire l'extraction JSON par GPT

Sortie attendue :
- un JSON conforme au contrat `homegraph/extraction_output_example.json`

Exemple de fichier :
- `homegraph/payloads/alice_extraction.json`

### 5. Merger dans SQLite

```bash
python3 homegraph/merge_extraction.py homegraph/payloads/alice_extraction.json --model-name gpt-5 --source-ref mem0-export:twitch:streamer:viewer:alice
```

### 6. Construire le contexte viewer compact

```bash
python3 homegraph/build_viewer_context.py --viewer-id twitch:streamer:viewer:alice
```

### 7. Ou le recuperer via l'admin API locale

```bash
curl -sS \
  -H 'X-Admin-Key: ...' \
  http://127.0.0.1:8000/admin/homegraph/users/twitch:streamer:viewer:alice/context
```

## Statut

Workflow reproductible V1 :
- defini
- scripts Linux en place
- il manque seulement l'appel GPT automatise si on veut le faire sans intervention humaine

