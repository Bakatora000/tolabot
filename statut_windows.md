# Statut Windows — bot Twitch

## Role

Ce fichier est reserve au suivi operationnel de Codex Windows.

Il doit contenir :
- l'etat des taches Windows
- les integrations runtime du bot
- les validations et blocages cote PC Windows
- les points a transmettre a Linux

Il ne doit pas dupliquer toute la source de verite du projet.

---

## Etat Actuel Cote Windows

Derniere synthese connue depuis le depot partage :
- client mem0 branche
- fallback local actif
- tests cibles Windows OK
- validation reelle Windows reussie contre l'API Linux
- configuration `.env` mem0 cote Windows OK
- `memory-health` OK sur l'URL publique `https://olala.expevay.net/api/memory/health`

Taches Windows connues :

| id | status | notes |
|---|---|---|
| W1 | REVIEW | client HTTP mem0, config `.env`, diagnostic `memory-health` et test unitaire dedie prets |
| W2 | REVIEW | lecture memoire distante branchee avant Ollama avec fallback local |
| W3 | REVIEW | ecriture memoire distante branchee apres generation, non bloquante |
| W4 | REVIEW | `.env.example`, `README.md`, `test_memory_client.py` et `test_bot_runtime.py` mis a jour |
| W5 | DONE | test reel mem0 valide en bout en bout contre l'API publique Linux |

---

## Tests Attendus Cote Windows

Ordre conseille :
- `py .\\manage_bot.py memory-health`
- `py .\\manage_bot.py run-ollama`

Avec :
- `MEM0_ENABLED=true`
- la config API Linux correcte

Infos utiles a remonter a Linux si erreur :
- code HTTP
- message d'erreur Python
- extrait log bot
- endpoint concerne
- payload simplifie

---

## Validation Reelle

Test execute cote Windows :

```powershell
py .\manage_bot.py status
py .\manage_bot.py memory-health
```

Constats finaux :
- config mem0 chargee correctement dans le bot Windows
- `MEM0_ENABLED`, `MEM0_API_BASE_URL`, `MEM0_API_KEY` : OK
- `MEM0_VERIFY_SSL=true` fonctionne maintenant
- `py .\manage_bot.py memory-health` : OK
- execution reelle du bot validee avec API publique Linux

Validation croisee Linux observee pendant le test Windows :
- `GET /health` -> `200`
- `POST /search` -> `200` pour `user_id=twitch:expevay:viewer:expevay`
- `POST /remember` -> `200` pour `user_id=twitch:expevay:viewer:expevay`
- insertion Qdrant observee cote Linux

Conclusion cote Windows :
- la memoire distante est reellement utilisee par le bot
- le routage public `/api/memory` est bon
- le TLS public est maintenant correct

Point de fonctionnement actuel :
- fallback local toujours actif par choix de prudence
- mem0 utilisee en priorite pour la memoire generale durable
- memoire locale conservee pour les fils courts specialises, notamment charades/devinettes
