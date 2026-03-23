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
- validation reelle contre l'API Linux encore attendue cote Windows

Taches Windows connues :

| id | status | notes |
|---|---|---|
| W1 | REVIEW | client HTTP mem0, config `.env`, diagnostic `memory-health` et test unitaire dedie prets |
| W2 | REVIEW | lecture memoire distante branchee avant Ollama avec fallback local |
| W3 | REVIEW | ecriture memoire distante branchee apres generation, non bloquante |
| W4 | REVIEW | `.env.example`, `README.md`, `test_memory_client.py` et `test_bot_runtime.py` mis a jour |

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
