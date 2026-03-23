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
- validation reelle Windows demarree contre l'API Linux
- configuration `.env` mem0 cote Windows OK
- `memory-health` echoue actuellement sur l'URL publique `https://olala.expevay.net/api/memory/health`

Taches Windows connues :

| id | status | notes |
|---|---|---|
| W1 | REVIEW | client HTTP mem0, config `.env`, diagnostic `memory-health` et test unitaire dedie prets |
| W2 | REVIEW | lecture memoire distante branchee avant Ollama avec fallback local |
| W3 | REVIEW | ecriture memoire distante branchee apres generation, non bloquante |
| W4 | REVIEW | `.env.example`, `README.md`, `test_memory_client.py` et `test_bot_runtime.py` mis a jour |
| W5 | BLOCKED | test reel `memory-health` bloque par l'exposition publique Linux |

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

## Validation Reelle En Cours

Test execute cote Windows :

```powershell
py .\manage_bot.py status
py .\manage_bot.py memory-health
```

Constats :
- config mem0 chargee correctement dans le bot Windows
- `MEM0_ENABLED`, `MEM0_API_BASE_URL`, `MEM0_API_KEY` : OK
- avec `MEM0_VERIFY_SSL=true`, erreur TLS :
  - `SSLCertVerificationError`
  - `certificate verify failed: Hostname mismatch, certificate is not valid for 'olala.expevay.net'`
- avec `MEM0_VERIFY_SSL=false`, l'appel ne retourne pas du JSON API

Test brut execute :

```powershell
py -c "import requests; r=requests.get('https://olala.expevay.net/api/memory/health', headers={'X-API-Key':'...'}, verify=False, timeout=10); print(r.status_code); print(r.text)"
```

Resultat observe :
- HTTP `200`
- body commencant par `<!DOCTYPE html>`

Interpretation cote Windows :
- l'URL publique `/api/memory/health` renvoie actuellement une page HTML, pas le service FastAPI mem0
- il y a aussi un probleme TLS distinct sur le certificat servi pour `olala.expevay.net`

Blocage courant :
- reverse proxy / routage public `/api/memory/*`
- certificat TLS invalide pour le hostname `olala.expevay.net`

Attendu cote Linux avant reprise des tests Windows :
- `GET https://olala.expevay.net/api/memory/health` doit renvoyer du JSON API
- certificat valide pour `olala.expevay.net`
