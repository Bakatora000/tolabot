# Homegraph Viewer Context V1

## But

Definir le contrat du contexte viewer compact que Windows pourra injecter avant l'appel a Ollama.

Cette spec fige :
- le format exact
- la taille cible
- la strategie de fraicheur
- le mode d'acces Linux

---

## Format Exact

Format de sortie recommande :

```json
{
  "ok": true,
  "viewer_id": "twitch:streamer:viewer:alice",
  "generated_at": "2026-03-24T18:30:00Z",
  "source": "homegraph_v1",
  "staleness": {
    "profile_last_updated_at": "2026-03-24T17:10:00Z",
    "is_stale": false
  },
  "context": {
    "summary_short": "Viewer regulier, parle souvent de jeux de construction et d'optimisation.",
    "facts_high_confidence": [
      "joue souvent a Satisfactory",
      "prefere les builds efficaces"
    ],
    "recent_relevant": [
      "a reparle recentement d'automatisation"
    ],
    "uncertain_points": [
      "possible interet pour Factorio"
    ]
  },
  "text_block": "Contexte viewer:\n- viewer regulier, parle souvent de jeux de construction et d'optimisation\n- joue souvent a Satisfactory\n- prefere les builds efficaces\n- a reparle recentement d'automatisation\n- incertain : possible interet pour Factorio"
}
```

Champ important pour Windows :
- `text_block`

Windows peut l'injecter tel quel dans le prompt, sans avoir besoin de reconstruire la presentation.

---

## Regles De Construction

### `summary_short`

Source :
- `viewer_profiles.summary_short`

Fallback :
- `aucun`

### `facts_high_confidence`

Source :
- `viewer_facts`

Filtres :
- `status = active`
- `confidence >= 0.75`
- limiter aux faits les plus utiles au prompt

Ordre recommande :
- `plays_game`
- `likes_game`
- `build_style`
- `personality_trait`
- `recurring_topic`
- autres ensuite

### `recent_relevant`

Source V1 :
- `viewer_facts` actifs avec `updated_at` recent

Heuristique V1 :
- top 2 faits actifs les plus recents non deja retenus dans `facts_high_confidence`

### `uncertain_points`

Source :
- `viewer_facts`

Filtres :
- `status = uncertain`
  ou
- `confidence < 0.75`

Limiter a 2 ou 3 points max.

---

## Taille Cible

Objectif :
- `text_block` compact
- utile sans noyer le prompt

Contraintes V1 :
- cible normale : 300 a 600 caracteres
- plafond dur : 900 caracteres
- `summary_short` : max 160 caracteres
- `facts_high_confidence` : max 4 lignes
- `recent_relevant` : max 2 lignes
- `uncertain_points` : max 2 lignes

Si le contexte depasse le plafond :
- couper d'abord `recent_relevant`
- puis couper `uncertain_points`
- puis limiter `facts_high_confidence`

---

## Strategie De Fraicheur

V1 retenue :
- calcul a la volee
- pas de cache obligatoire

Pourquoi :
- implementation plus simple
- volume attendu faible
- pas de risque de desynchronisation cache/SQLite au debut

Champ utile :
- `profile_last_updated_at`
- `is_stale`

Heuristique V1 pour `is_stale` :
- `true` si `viewer_profiles.last_updated_at` manque
- `true` si dernier update > 7 jours
- sinon `false`

Une strategie de cache pourra venir plus tard si :
- l'appel devient frequent
- ou si on expose le contexte via API

---

## Mode D'Acces

V1 retenue :
- script local Linux

Script cible :
- `python3 homegraph/build_viewer_context.py --viewer-id twitch:streamer:viewer:alice`

Sortie :
- JSON sur stdout

Pourquoi :
- tres simple a tester
- aucun endpoint public a ajouter
- Windows pourra ensuite decider :
  - de l'appeler via SSH ponctuel
  - ou de demander une future exposition admin locale

Evolution probable V2 :
- endpoint admin local non public :
  - `GET /admin/homegraph/users/{user_id}/context`

Mais ce n'est pas requis pour commencer cote Windows.

---

## Priorite D'Injection Cote Bot

Ordre recommande :
1. memoire locale specialisee critique
2. contexte homegraph compact
3. contexte mem0 retrieval

Raison :
- homegraph apporte un profil viewer stable et compact
- mem0 apporte le retrieval plus contextuel du moment

---

## Statut

Decision V1 :
- format compact fige
- taille cible figee
- calcul a la volee retenu
- acces par script local Linux retenu

