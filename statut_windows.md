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
- `memory-health` OK sur l'URL publique `https://memory.example.net/api/memory/health`
- code source Windows migre dans `windows_bot/` du repo partage

Taches Windows connues :

| id | status | notes |
|---|---|---|
| W1 | REVIEW | client HTTP mem0, config `.env`, diagnostic `memory-health` et test unitaire dedie prets |
| W2 | REVIEW | lecture memoire distante branchee avant Ollama avec fallback local |
| W3 | REVIEW | ecriture memoire distante branchee apres generation, non bloquante |
| W4 | REVIEW | `.env.example`, `README.md`, `test_memory_client.py` et `test_bot_runtime.py` mis a jour |
| W5 | DONE | test reel mem0 valide en bout en bout contre l'API publique Linux |
| W6 | REVIEW | UI admin Windows locale avec tunnel SSH auto vers l'API admin Linux montee dans le service memoire principal |

Sous-decoupage recommande pour W6 :

| id | status | notes |
|---|---|---|
| W6.1 | REVIEW | config locale admin Windows ajoutee dans `windows_bot/.env.example` et `windows_bot/bot_config.py` |
| W6.2 | REVIEW | `windows_bot/admin_tunnel.py` implemente pour ouvrir, verifier et fermer un tunnel SSH local |
| W6.3 | REVIEW | `windows_bot/admin_client.py` implemente pour appeler l'admin API Linux via `127.0.0.1` |
| W6.4 | REVIEW | `windows_bot/admin_ui.py` implemente pour une UI locale minimale : etat tunnel, etat API, liste viewers, recent |
| W6.5 | REVIEW | tests Windows ajoutes pour le helper tunnel et le client admin |
| W6.6 | REVIEW | validation reelle faite pour tunnel SSH, port local, auth admin et reachability `/admin/health`; operations avancees encore a valider en reel |

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
- `POST /search` -> `200` pour `user_id=twitch:streamer:viewer:streamer`
- `POST /remember` -> `200` pour `user_id=twitch:streamer:viewer:streamer`
- insertion Qdrant observee cote Linux

Conclusion cote Windows :
- la memoire distante est reellement utilisee par le bot
- le routage public `/api/memory` est bon
- le TLS public est maintenant correct

Point de fonctionnement actuel :
- fallback local toujours actif par choix de prudence
- mem0 utilisee en priorite pour la memoire generale durable
- memoire locale conservee pour les fils courts specialises, notamment charades/devinettes
- file FIFO globale bornee en place avec priorite streamer et expiration configurable

Piste validee pour la suite :
- l'admin ne sera pas exposee publiquement
- une UI locale Windows ouvrira un tunnel SSH vers le service memoire principal Linux sur `127.0.0.1:8000`
- reference de design : `admin_interface_v1.md`

Pivot runtime Linux pris en compte :
- pas de process admin separe en prod V1
- routes admin montees dans le service memoire principal
- base locale Windows retenue : `http://127.0.0.1:9000`
- routes attendues : `/admin/health`, `/admin/users`, `/admin/users/{user_id}/recent`, `DELETE /admin/users/{user_id}`

Ordre d'implementation cote Windows :
1. helper tunnel SSH
2. client HTTP admin
3. ecran local minimal viewers + recent
4. actions `purge`, `delete`, `export`, `import` une fois l'API admin Linux disponible

---

## Validation Reelle Admin V1

Tests executes cote Windows :

```powershell
py -m unittest test_admin_client.py test_admin_tunnel.py
py .\manage_bot.py run-admin-ui
```

Constats :
- tests unitaires `admin_client` et `admin_tunnel` : OK
- tunnel SSH Windows -> Linux : OK apres enregistrement de la cle d'hote et activation d'une cle SSH non interactive pour `BatchMode=yes`
- port local `127.0.0.1:9000` : OK
- auth admin `X-Admin-Key` : OK
- route admin Linux `/admin/health` joignable via tunnel : OK
- UI locale Windows demarre et affiche :
  - `Tunnel: OK`
  - `Port local: OK`
  - `Admin API: OK`

Conclusion :
- la chaine complete Windows -> tunnel SSH -> service memoire Linux -> routes `/admin/*` fonctionne en reel
- la V1 actuelle reste minimale cote interface

Prochain lot UI cote Windows :
1. viewers cliquables
2. panneau `recent` utile
3. bouton `refresh`
4. bouton `purge viewer`
5. puis `search`, `delete memory`, `export`, `import`
