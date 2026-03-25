# Homegraph V2 — Couche Liens

## Objet

Cette V2 ajoute a `homegraph` une vraie couche de liens explicites, sans introduire Neo4j pour le moment.

But :
- mieux representer les relations utiles au bot
- rester compatible avec SQLite
- enrichir le contexte viewer sans faire exploser la complexite
- preparer une evolution future vers une couche graphe plus riche si besoin

La V1 sait deja stocker :
- profils viewer
- facts viewer
- relations viewer -> cible

La V2 ne remplace pas la V1.
Elle la rend plus relationnelle, plus temporelle et plus reusable.

---

## Pourquoi Une V2

Limite actuelle de la V1 :
- les faits sont utiles
- les relations existent
- mais elles restent trop "plates"

Exemples de besoins mal couverts aujourd'hui :
- `viewer A` revient souvent sur `K7VHS`
- `viewer A` connait probablement `viewer B`
- `viewer A` joue a `Valheim` dans un contexte `no-death`
- `viewer A` n'aime pas `Enshrouded` mais aime `Valheim`
- un `running gag` relie plusieurs viewers
- un sujet est fort pour un viewer sur une periode donnee puis s'affaiblit

Ce qu'on veut capturer :
- les liens eux-memes
- leur force
- leur fraicheur
- leur statut
- leur provenance

---

## Principe Produit

On garde trois niveaux :

1. **Profil**
- resume court et long du viewer

2. **Facts**
- informations viewer-centric utiles au prompt

3. **Links**
- liens explicites entre entites
- support principal de la V2

---

## Types D'Entites Cibles

La V2 ne cherche pas un graphe universel.
Elle cherche un graphe utile au bot.

Types minimaux :
- `viewer`
- `game`
- `topic`
- `running_gag`
- `trait`
- `stream_mode`
- `object`

Exemples :
- `viewer:karramelle`
- `game:World of Warcraft`
- `topic:K7VHS`
- `running_gag:K7VHS_divine_joke`
- `stream_mode:no_death`
- `object:long_bow`

---

## Tables V2 Recommandees

### 1. `graph_entities`

But :
- centraliser les cibles reifiees
- eviter de tout laisser en `target_id_or_value` libre

Champs proposes :
- `entity_id`
- `entity_type`
- `canonical_name`
- `aliases_json`
- `status`
- `created_at`
- `updated_at`

Exemples :
- `entity_id=game:valheim`
- `entity_type=game`
- `canonical_name=Valheim`

### 2. `viewer_links`

But :
- table coeur de la V2
- stocker les liens explicites entre un viewer et une entite ou un autre viewer

Champs proposes :
- `link_id`
- `viewer_id`
- `target_entity_id`
- `target_fallback_value`
- `relation_type`
- `strength`
- `confidence`
- `status`
- `polarity`
- `evidence_count`
- `first_seen_at`
- `last_seen_at`
- `valid_from`
- `valid_to`
- `source_memory_ids_json`
- `source_excerpt`
- `last_reviewed_at`
- `review_state`
- `created_at`
- `updated_at`

Exemples de `relation_type` :
- `plays`
- `likes`
- `dislikes`
- `talks_about`
- `returns_to`
- `knows`
- `jokes_about`
- `interacts_with`
- `uses_build_style`
- `plays_in_mode`
- `owns`

Exemples de `polarity` :
- `positive`
- `negative`
- `neutral`
- `uncertain`

### 3. `link_evidence`

But :
- garder la traçabilite fine sans alourdir chaque lien

Champs proposes :
- `evidence_id`
- `link_id`
- `memory_id`
- `excerpt`
- `weight`
- `created_at`

Cette table permet :
- audit
- edition future
- recalcul du `strength`

### 4. `viewer_link_rollups` optionnelle

But :
- cache materialise si un jour la construction du contexte devient trop lourde

Champs proposes :
- `viewer_id`
- `rollup_json`
- `updated_at`

Pour la V2 immediate :
- pas necessaire
- calcul a la volee recommande tant que le volume reste faible

---

## Evolution Des Tables Existantes

### `viewer_relations`

Deux options :

#### Option A — migration douce
- garder `viewer_relations`
- ajouter `viewer_links`
- utiliser `viewer_links` pour les nouveaux usages riches
- conserver `viewer_relations` comme compatibilite / historique

#### Option B — migration franche
- migrer `viewer_relations` vers `viewer_links`
- deprecier progressivement `viewer_relations`

Recommendation :
- **Option A**

Pourquoi :
- moins de casse
- migration progressive
- meilleure compatibilite avec le runtime actuel

### `viewer_facts`

On garde cette table.

Role V2 :
- facts viewer-centric utiles au prompt
- liens riches dans `viewer_links`

Exemple :
- fact : `build_style = prefere les builds efficaces`
- link : `viewer -> game:Satisfactory [plays]`

---

## Semantique De La Force D'Un Lien

V2 introduit une notion utile :
- `strength`

But :
- separer la confiance du modele et l'intensite observee

Exemple :
- `confidence=0.72` : on n'est pas totalement certain
- `strength=0.91` : le motif revient souvent

Interpretation :
- `confidence` = fiabilite de l'extraction / fusion
- `strength` = poids pratique pour le resume viewer

`strength` peut dependre de :
- recurrence
- recence
- nombre de sources
- coherence entre souvenirs

---

## Temporalite

La V2 doit mieux gerer le temps.

Champs importants :
- `first_seen_at`
- `last_seen_at`
- `valid_from`
- `valid_to`
- `status`

Exemples de `status` :
- `active`
- `fading`
- `obsolete`
- `contradicted`
- `uncertain`

Exemples d'usage :
- un viewer parlait beaucoup de `Valheim` il y a 4 mois mais plus maintenant
- un running gag etait fort sur une periode, puis a disparu
- une relation sociale est seulement supposee, pas validee

---

## Exemples Concrets

### Exemple 1 — jeu principal

```json
{
  "viewer_id": "twitch:streamer:viewer:arthii_tv",
  "target_entity_id": "game:satisfactory",
  "relation_type": "plays",
  "strength": 0.88,
  "confidence": 0.91,
  "status": "active",
  "polarity": "positive"
}
```

### Exemple 2 — sujet recurrent

```json
{
  "viewer_id": "twitch:streamer:viewer:raptormekhong",
  "target_entity_id": "topic:k7vhs",
  "relation_type": "returns_to",
  "strength": 0.79,
  "confidence": 0.75,
  "status": "active",
  "polarity": "neutral"
}
```

### Exemple 3 — aversion

```json
{
  "viewer_id": "twitch:streamer:viewer:expevay",
  "target_entity_id": "game:enshrouded",
  "relation_type": "dislikes",
  "strength": 0.81,
  "confidence": 0.84,
  "status": "active",
  "polarity": "negative"
}
```

### Exemple 4 — relation sociale faible

```json
{
  "viewer_id": "twitch:streamer:viewer:arthii_tv",
  "target_entity_id": "viewer:sarahp79",
  "relation_type": "compliments",
  "strength": 0.42,
  "confidence": 0.63,
  "status": "uncertain",
  "polarity": "positive"
}
```

---

## Impact Sur Le Builder De Contexte

La V2 ne doit pas changer brutalement le contrat Windows.

On conserve :
- `text_block`
- `summary_short`
- `facts_high_confidence`
- `recent_relevant`
- `uncertain_points`

Mais le builder pourra mieux prioriser :
- jeux forts
- sujets recurrents
- aversions claires
- relations sociales saillantes
- modes de jeu saillants

Exemple de rendu V2 :

```text
Contexte viewer:
- Joue souvent a Satisfactory et aime les builds efficaces.
- Revient souvent sur K7VHS.
- N'apprecie pas Enshrouded.
- S'interesse aux runs no-death.
```

---

## Impact Sur L'Extraction GPT

La sortie GPT V2 peut rester proche de la V1, mais avec une section `links`.

Format cible :

```json
{
  "viewer_id": "twitch:streamer:viewer:alice",
  "summary_short": "Viewer regulier, parle souvent de Satisfactory et d'optimisation.",
  "facts": [],
  "relations": [],
  "links": [
    {
      "target_type": "game",
      "target_value": "Satisfactory",
      "relation_type": "plays",
      "strength": 0.88,
      "confidence": 0.9,
      "status": "active",
      "polarity": "positive",
      "source_memory_ids": ["mem_a", "mem_b"]
    }
  ],
  "conflicts": [],
  "needs_human_review": []
}
```

La logique de merge Linux fera ensuite :
- resolution de l'entite cible
- upsert dans `graph_entities`
- upsert du lien dans `viewer_links`
- creation d'evidences

---

## Migration Recommandee

### Phase 1 — schema seulement

- ajouter les nouvelles tables
- ne pas casser le builder actuel

### Phase 2 — merge dual-write

- continuer d'alimenter `viewer_facts`
- commencer a alimenter `viewer_links`

### Phase 3 — builder enrichi

- enrichir `build_viewer_context.py` pour exploiter les liens
- sans changer le contrat Windows

### Phase 4 — nettoyage

- reevaluer si `viewer_relations` reste utile tel quel
- sinon planifier une convergence

---

## Ce Qu'On Ne Fait Pas En V2

- pas de Neo4j
- pas de moteur graphe distribue
- pas de requetes graphe complexes multi-sauts
- pas de recalcul temps reel a chaque message
- pas de cache lourd tant que le volume reste petit

La V2 doit rester :
- simple
- auditable
- SQLite-compatible
- incrementale

---

## Recommendation Finale

Pour Tolabot, la bonne prochaine etape n'est pas d'ajouter une nouvelle base.

La bonne prochaine etape est :
- finir d'abord la refacto Windows structurelle
- puis faire `homegraph v2` avec une vraie couche liens sur SQLite

Sequence recommandee :
1. stabiliser `arbitrator`, `context_sources`, `prompt_composer`
2. geler le contrat de consommation du contexte viewer
3. ajouter les tables V2 `graph_entities`, `viewer_links`, `link_evidence`
4. enrichir le merge et le builder

Cette voie donne :
- de meilleurs liens
- de meilleurs resumes
- moins de complexite qu'une pile `Qdrant + Neo4j + PostgreSQL`
- et une transition plus saine vers un futur runtime unifie
