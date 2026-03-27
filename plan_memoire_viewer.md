# Plan de developpement — "Tolabot connait ses viewers"

## Vision

Passer d'un bot qui **retrouve des faits** sur les viewers a un bot qui **les connait** : il sait qui est nouveau, qui est regulier, ce qui a change, et adapte son ton en consequence.

---

## Diagnostic : etat actuel

Le bot dispose de 4 couches de memoire qui ne se parlent pas :

| Couche | Duree de vie | Usage reel |
|--------|-------------|------------|
| `conversation_graph` | 10h TTL | Contexte immediat |
| `facts_memory` | 10h TTL | Faits regex locaux |
| **mem0** (Qdrant) | Permanent | Recherche semantique pure |
| **Homegraph** (SQLite) | Permanent | Extraction offline, jamais mis a jour par le bot |

Apres 10h, le bot perd tout contexte local. Il ne lui reste que mem0 (recherche par similarite, sans notion de temps) et un homegraph fige.

### Ce que le bot ne sait pas faire aujourd'hui

- Distinguer un nouveau viewer d'un habitue
- Savoir quand il a appris quelque chose (pas de temporalite)
- Faire decroitre les faits anciens (un fait de 60 jours = meme poids qu'un fait d'hier)
- Detecter une contradiction ("j'ai arrete Valheim" ne met pas a jour le fait existant)
- Mettre a jour le Homegraph en live (extraction offline uniquement)
- Adapter son ton selon le profil du viewer

---

## Phase 1 — Identite Viewer (fondation)

### Objectif

Le bot sait distinguer un nouveau d'un habitue, et connait la derniere interaction.

### Livrable

Une table `viewer_identity` dans le Homegraph SQLite, alimentee en live par le bot.

```sql
CREATE TABLE IF NOT EXISTS viewer_identity (
    viewer_id          TEXT PRIMARY KEY,
    first_seen_at      TEXT NOT NULL,
    last_seen_at       TEXT NOT NULL,
    interaction_count  INTEGER NOT NULL DEFAULT 0,
    session_count      INTEGER NOT NULL DEFAULT 0,
    status             TEXT NOT NULL DEFAULT 'new'
);
```

### Logique de statut

| Statut | Condition |
|--------|-----------|
| `new` | interaction_count < 3 |
| `regular` | interaction_count >= 3 ET last_seen < 14j |
| `returning` | interaction_count >= 3 ET last_seen > 14j |
| `dormant` | last_seen > 60j |

Un gap > 2h entre deux messages compte comme une nouvelle session.

### Changements cote bot Windows

`runtime_pipeline.py` : a chaque message traite, faire un `UPSERT` HTTP vers le memory_service qui met a jour `viewer_identity`.

Le endpoint est leger : un seul `INSERT ... ON CONFLICT DO UPDATE`.

### Changements cote prompt

Le `ContextSourceResult` du homegraph inclut le statut viewer. Le prompt composer adapte un prefixe :

- `new` → "Ce viewer est nouveau sur la chaine."
- `returning` → "Ce viewer n'est pas venu depuis X jours."
- `regular` → pas de mention (c'est le cas normal)

### Critere de validation

Le bot dit "Bienvenue !" a un nouveau et "Ca faisait longtemps !" a un revenant, sans qu'on ait a le coder dans les regles — le LLM le deduit du contexte.

---

## Phase 2 — Decroissance temporelle

### Objectif

Les faits vieux perdent du poids automatiquement. Le bot ne dit plus "tu joues a Valheim" si ca fait 2 mois.

### Livrable

Une fonction `effective_confidence()` utilisee partout ou on lit la confiance d'un fait.

```python
def effective_confidence(base_confidence: float, last_seen_at: datetime, now: datetime) -> float:
    age_days = (now - last_seen_at).days
    if age_days <= 7:
        return base_confidence                    # frais, pleine confiance
    if age_days <= 30:
        return base_confidence * 0.85             # leger recul
    if age_days <= 90:
        return base_confidence * 0.6              # vieillissant
    return base_confidence * 0.3                  # probablement obsolete
```

### Changements

- `homegraph/context.py` : `build_viewer_context_payload()` utilise `effective_confidence()` au lieu de `row["confidence"]` brut, en se basant sur `updated_at` de chaque fait/link
- Le seuil 0.75 reste, mais un fait a 0.86 vieux de 3 mois passe a 0.52 → tombe dans "incertain" au lieu de "confiance haute"
- Les faits "incertains par anciennete" sont presentes differemment : "il y a quelque temps, jouait a Valheim" au lieu de "joue souvent a Valheim"

### Changements cote mem0

`memory_client.py` : ajouter un parametre `recency_boost` optionnel dans `search_memory()` qui tri-poste les resultats par score pondere `score * recency_factor`.

### Critere de validation

Un fait non mentionne depuis 60 jours apparait comme "incertain" dans le contexte, pas comme fait confirme.

---

## Phase 3 — Homegraph vivant (alimentation en live)

### Objectif

Le Homegraph n'est plus une photo figee. Le bot l'alimente apres chaque conversation significative.

### Livrable

Un pipeline d'extraction legere post-reponse, cote memory_service.

### Architecture

```
Bot Windows                    Memory Service Linux
     |                              |
     |-- POST /memory/remember -->  |  (existant, mem0)
     |                              |
     |-- POST /homegraph/ingest --> |  (NOUVEAU)
     |                              |
                                    v
                              extraction heuristique legere
                              (patterns francais, pas de GPT)
                                    v
                              UPSERT dans homegraph SQLite
                              + mise a jour viewer_identity
```

### Endpoint `POST /homegraph/ingest`

- **Input** : `{ viewer_id, user_message, bot_reply, channel, timestamp }`
- **Traitement** : extraction heuristique des `durable_markers` (reutilise la logique de `should_store_in_mem0` + les patterns de `bootstrap_mem0_heuristic.py`)
- **Output** : liste des faits extraits et upsertes, ou `[]` si rien de notable
- **Contrainte** : < 50ms de traitement, pas d'appel LLM

### Ce qui change

- Les champs `last_seen_at` et `evidence_count` des `viewer_links` sont enfin mis a jour en live
- Un fait mentionne a nouveau voit son `updated_at` rafraichi → sa `effective_confidence` remonte
- Un fait mentionne dans 5 conversations differentes accumule un `evidence_count` de 5

### Extension de la confiance (avec Phase 2)

```python
def effective_confidence(base: float, last_seen: datetime, evidence_count: int, now: datetime) -> float:
    age_factor = decay_by_age(last_seen, now)
    evidence_factor = min(1.0, 0.7 + evidence_count * 0.06)  # 1 mention=0.76, 5+=1.0
    return base * age_factor * evidence_factor
```

### Critere de validation

Un viewer dit "je joue a Satisfactory" dans le chat. Des le message suivant, le homegraph contient ce fait. Au bout de 3 mentions sur 3 sessions differentes, le fait passe en confiance haute.

---

## Phase 4 — Correction et contradiction

### Objectif

Quand un viewer contredit un fait existant, le bot le detecte et met a jour sa memoire.

### Livrable

Un detecteur de contradictions dans le pipeline d'ingestion (Phase 3).

### Mecanisme

1. A l'ingestion d'un nouveau fait, chercher les faits existants du meme `kind` pour ce viewer
2. Detecter les patterns de negation :
   - "j'ai arrete X" / "je ne joue plus a X" → invalide `plays_game:X`
   - "en fait je prefere Y" → reduit la confiance de l'ancien, cree le nouveau
   - "non c'est pas vrai" (dans le contexte d'un fait utilise par le bot) → flag le fait comme `disputed`
3. Actions sur contradiction detectee :
   - Fait contredit → `status` passe de `active` a `superseded`, `valid_to` = now
   - Nouveau fait → cree avec `valid_from` = now
   - `viewer_facts` garde l'historique (on ne supprime pas, on invalide)

### Nouveau statut

`superseded` (en plus de `active`, `uncertain`)

### Impact prompt

Les faits `superseded` ne sont plus presentes. Le bot peut mentionner la transition : "Ah tu es passe de Valheim a Satisfactory !"

### Critere de validation

Le viewer dit "j'ai arrete Valheim". Le fait `plays_game:Valheim` passe en `superseded`. Le contexte viewer ne le mentionne plus. Si le viewer reparle de Valheim plus tard, un nouveau fait est cree.

---

## Phase 5 — Profil evolutif et ton adapte

### Objectif

Le bot a une comprehension synthetique de chaque viewer regulier et adapte son style.

### Livrable

Un resume viewer auto-genere periodiquement, et des indicateurs de personnalite.

### Resume viewer

- Declenche quand `interaction_count` franchit un seuil (10, 25, 50) ou quand le profil est `stale` (>7j) et que le viewer revient
- Utilise un appel LLM leger (Ollama local ou GPT) avec tous les faits actifs du viewer comme input
- Produit un `summary_short` (1 phrase) et `summary_long` (3-4 phrases) mis a jour dans `viewer_profiles`

### Indicateurs de personnalite

Nouveaux `kind` dans `viewer_facts` :

| Kind | Exemples |
|------|----------|
| `communication_style` | "pose beaucoup de questions", "partage des builds", "fait des blagues" |
| `engagement_level` | "tres actif", "occasionnel", "spectateur silencieux" |

Calcules par heuristique sur les patterns d'interaction (pas besoin de LLM).

### Impact sur le prompt

Le `viewer_block` du PromptPlan inclut desormais :
- Statut (Phase 1)
- Resume court
- Faits ponderes par recency (Phase 2)
- Style de communication

Le bot peut naturellement adapter son ton : plus didactique avec un "questionneur", plus technique avec un "builder".

### Critere de validation

Pour un viewer regulier ayant 30+ interactions, le bot produit un contexte riche et adapte qui ressemble a ce qu'un streamer humain saurait de ce viewer.

---

## Resume des phases

| Phase | Nom | Pre-requis | Effort |
|-------|-----|-----------|--------|
| **1** | Identite Viewer | Aucun | ~1-2 jours |
| **2** | Decroissance temporelle | Phase 1 | ~1 jour |
| **3** | Homegraph vivant | Phases 1+2 | ~3-4 jours |
| **4** | Correction et contradiction | Phase 3 | ~2-3 jours |
| **5** | Profil evolutif | Phases 1-4 | ~2-3 jours |

Les phases sont cumulatives. Chacune apporte de la valeur seule, mais le vrai saut qualitatif arrive a la **Phase 3** quand le Homegraph devient vivant.

---

## Compatibilite avec l'architecture vNext

Ce plan s'aligne avec `architecture_target_vnext.md` :

- **Phase 1** nourrit la couche "Memoire Longue" avec un signal structurel manquant
- **Phase 2** implemente la temporalite mentionnee dans les objectifs produit ("signaux devenus obsoletes")
- **Phase 3** concretise la "memorisation post-reponse" selective
- **Phase 4** renforce l'arbitrage contextuel
- **Phase 5** enrichit le `viewer_block` du PromptPlan

Le contrat `ContextSourceResult` existant (source_id, priority, confidence, stale) supporte deja ces evolutions sans changement d'interface.
