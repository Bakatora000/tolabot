# Homegraph V1

Cette brique porte le graphe metier maison du projet.

Objectif :
- partir des souvenirs `mem0`
- produire un profil viewer structure
- stocker les faits/relations utiles en SQLite
- generer ensuite un contexte compact pour le prompt du bot

## Etat Actuel

Disponible :
- schema SQLite V1
- premier socle Homegraph V2 avec couche liens SQLite
- script d'initialisation de base
- script d'inspection simple
- script de construction d'un payload viewer pour extraction GPT
- template de prompt GPT d'extraction
- script de construction du prompt GPT
- script de merge `GPT JSON -> SQLite`
- script de construction du contexte viewer compact

Socle V2 deja pose :
- tables `graph_entities`, `viewer_links`, `link_evidence`
- merge `links` en dual-write avec la V1
- builder de contexte capable d'exploiter les liens V2
- contrat Windows conserve (`text_block`, `summary_short`, etc.)

## Fichiers

- `homegraph/schema.py`
- `homegraph/homegraph_v2_links.md`
- `homegraph/init_db.py`
- `homegraph/inspect_db.py`
- `homegraph/build_viewer_payload.py`
- `homegraph/extraction_prompt_v1.md`
- `homegraph/extraction_prompt_v2.md`
- `homegraph/build_extraction_prompt.py`
- `homegraph/merge_extraction.py`
- `homegraph/extraction_output_example.json`
- `homegraph/build_viewer_context.py`
- `homegraph/viewer_context_contract_v1.md`
- `homegraph/workflow_v1.md`
- `homegraph/workflow_v2.md`

## Initialisation

```bash
python3 homegraph/init_db.py
```

## Inspection

```bash
python3 homegraph/inspect_db.py
```

## Construction D'Un Payload GPT

Depuis un export mem0 viewer :

```bash
python3 homegraph/build_viewer_payload.py graphiti/imports/viewer_a.json
```

Le fichier de sortie est ecrit sous :

```text
homegraph/payloads/<viewer>_gpt_payload.json
```

## Format D'Extraction GPT Attendu

Exemple :

```text
homegraph/extraction_output_example.json
```

## Construction Du Prompt GPT

```bash
python3 homegraph/build_extraction_prompt.py homegraph/payloads/alice_gpt_payload.json
```

Le prompt reutilise :

```text
homegraph/extraction_prompt_v1.md
```

Version V2 avec `links` :

```bash
python3 homegraph/build_extraction_prompt.py homegraph/payloads/alice_gpt_payload.json --version v2
```

Template V2 :

```text
homegraph/extraction_prompt_v2.md
```

## Merge D'Une Extraction GPT

```bash
python3 homegraph/merge_extraction.py homegraph/extraction_output_example.json --model-name gpt-5
```

Ce script :
- upsert le profil viewer
- upsert les facts
- upsert les relations
- upsert aussi les `links` V2 et leurs evidences si presents
- trace l'operation dans `graph_jobs` et `graph_job_items`

## Construction Du Contexte Viewer Compact

```bash
python3 homegraph/build_viewer_context.py --viewer-id twitch:streamer:viewer:alice
```

Sortie :
- JSON sur stdout
- contient un champ `text_block` directement injectable dans le prompt

Le contrat est documente ici :

```text
homegraph/viewer_context_contract_v1.md
```

## Prochaine Etape

- automatiser eventuellement l'appel GPT
- brancher l'appel cote Windows
- preparer `homegraph v2` avec une vraie couche liens sans quitter SQLite
- enrichir progressivement le builder avec davantage de relation types V2 utiles au prompt
