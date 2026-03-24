# Admin Interface V1 — UI Windows + tunnel SSH

## Objectif

Fournir une interface d'administration de la memoire distante sans exposer un `/admin` public sur Internet.

Le principe retenu :
- une API d'administration reste cote Linux, au plus pres des donnees
- cette API admin n'ecoute que sur `127.0.0.1`
- une interface locale cote Windows ouvre automatiquement un tunnel SSH
- l'UI Windows appelle ensuite l'API admin via `http://127.0.0.1:<port-local>`

Ce choix evite :
- une exposition publique de l'admin
- une edition directe de Qdrant/SQLite depuis Windows
- une dependance immediate a Tailscale

---

## Architecture V1

### Linux

Nouveau composant logique :
- `admin-api` FastAPI

Bind :
- `127.0.0.1:9000`

Responsabilites :
- lecture admin de la memoire
- suppression ciblee
- purge par viewer
- export JSON
- import JSON controle
- edition manuelle limitee

Source de verite :
- backend memoire existant
- eventuellement un petit module admin dedie au-dessus de `memory_service/backend.py`

### Windows

Nouveau composant logique :
- UI d'administration locale

Options de forme possibles :
- app web locale legere
- ou petite app desktop Python

Pour la V1, le plus simple est :
- une app locale Python dans `windows_bot/`
- serveur UI local sur `127.0.0.1`
- ouverture automatique d'un tunnel SSH au lancement

Tunnel attendu :

```text
Windows localhost:9000 -> SSH -> Linux 127.0.0.1:9000
```

Exemple de commande :

```bash
ssh -L 9000:127.0.0.1:9000 vhserver@server
```

---

## Pourquoi ce choix

### Avantages

- pas d'interface admin exposee publiquement
- pas besoin d'un VPN pour la V1
- logique admin gardee cote Linux
- acces simple depuis le PC Windows
- surface d'attaque reduite
- evolution facile vers Tailscale plus tard si besoin

### Contraintes

- le tunnel SSH doit etre vivant pendant l'usage
- il faut une cle SSH ou une auth SSH stable cote Windows
- l'UI doit gerer proprement les erreurs reseau et la reconnexion

---

## Perimetre Fonctionnel V1

### Fonctions a inclure

- verifier l'etat du tunnel SSH
- verifier l'etat de l'admin API
- lister les viewers connus
- rechercher dans la memoire d'un viewer
- voir les souvenirs recents d'un viewer
- supprimer un souvenir par `id`
- purger toute la memoire d'un viewer
- exporter la memoire d'un viewer en JSON
- importer/restaurer un export JSON

### Fonctions a exclure de la V1

- edition directe de Qdrant
- edition SQL manuelle
- edition libre de tous les champs internes `mem0`
- auth multi-utilisateur complexe
- RBAC
- edition en masse

---

## Edition manuelle V1.1

L'edition manuelle est faisable, mais il faut la cadrer.

Regle recommandee :
- ne jamais modifier Qdrant directement
- modifier la donnee source via l'API admin
- laisser le backend recreer la representation memoire si necessaire

Edition manuelle raisonnable :
- ajouter un souvenir manuel
- corriger le texte d'un souvenir
- corriger certaines metadonnees
- marquer un souvenir comme epingle
- marquer un souvenir comme ignore

Cela suppose d'ajouter un petit stockage d'etat admin si `mem0` ne porte pas nativement tous ces attributs.

---

## Endpoints Admin Linux Proposes

Tous ces endpoints doivent rester disponibles uniquement sur l'API admin liee a `127.0.0.1`.

### Sante

- `GET /health`

### Exploration

- `GET /users`
  - liste des `user_id` connus
  - filtres possibles : `channel`, `viewer`, pagination

- `GET /users/{user_id}/recent`
  - souvenirs recents

- `POST /users/{user_id}/search`
  - recherche textuelle/semantique

- `GET /users/{user_id}/stats`
  - volume estime
  - dernier acces
  - dernier souvenir

### Operations

- `DELETE /memories/{memory_id}`
  - suppression ciblee

- `DELETE /users/{user_id}`
  - purge viewer complete

- `POST /users/{user_id}/export`
  - export JSON

- `POST /users/{user_id}/import`
  - reimport JSON

- `POST /users/{user_id}/remember`
  - ajout manuel d'un souvenir

### Edition V1.1

- `PATCH /memories/{memory_id}`
  - correction de texte ou metadonnees

---

## Auth Admin

Le tunnel SSH reduit fortement l'exposition, mais il ne doit pas etre l'unique barriere.

Pour la V1 :
- cle admin distincte de `MEM0_API_KEY`
- header dedie, par exemple `X-Admin-Key`
- stockee seulement dans les `.env` locaux

Plus tard :
- session admin
- mot de passe local
- ou SSO si besoin

---

## Comportement de l'UI Windows

Au lancement :
1. verifier si un tunnel local repond deja
2. si non, lancer `ssh -L`
3. tester `GET /health` sur `http://127.0.0.1:9000`
4. afficher l'etat de connexion

Pendant l'usage :
- surveiller le process SSH
- gerer la reconnexion
- afficher clairement les erreurs reseau

A la fermeture :
- fermer proprement le process SSH lance par l'app

---

## Ecrans V1

### Tableau de bord

- etat du tunnel
- etat de l'API admin
- nombre de viewers connus
- acces rapide export/purge

### Liste viewers

- recherche par `user_id`
- filtre par channel
- tri par activite recente

### Fiche viewer

- resume
- recent
- recherche
- export
- purge

### Detail souvenir

- texte
- score si disponible
- metadonnees
- suppression
- edition manuelle en V1.1

---

## Structure de Code Recommandee

### Linux

Ajouter par exemple :
- `admin_service/`
- `admin_service/app.py`
- `admin_service/auth.py`
- `admin_service/models.py`
- `admin_service/backend.py`

Ou bien :
- integrer un sous-routeur admin dans `memory_service/` si on veut minimiser les fichiers

### Windows

Ajouter par exemple :
- `windows_bot/admin_ui.py`
- `windows_bot/admin_tunnel.py`
- `windows_bot/admin_client.py`
- `windows_bot/test_admin_tunnel.py`

---

## Ordre d'Implementation Recommande

### Etape 1

Linux :
- creer une `admin-api` locale minimale
- `GET /health`
- `GET /users`
- `GET /users/{user_id}/recent`
- `DELETE /users/{user_id}`

### Etape 2

Windows :
- helper tunnel SSH
- verif de sante
- ecran minimal viewers + recent

### Etape 3

Linux :
- export/import JSON
- suppression ciblee par `memory_id`

### Etape 4

Windows :
- UI export/purge/delete

### Etape 5

Edition manuelle controlee :
- ajout manuel
- patch limite texte/metadonnees

---

## Decisions Recommandees

- garder l'API bot publique separee de l'API admin
- ne pas exposer `/admin` publiquement pour la V1
- ne pas manipuler Qdrant/SQLite directement depuis Windows
- utiliser le tunnel SSH comme transport prive
- garder une auth admin distincte meme a travers le tunnel

---

## Criteres De Validation

La V1 est consideree valide si :
- l'UI Windows ouvre le tunnel SSH automatiquement
- l'admin API Linux n'est pas accessible publiquement
- l'UI peut lister les viewers
- l'UI peut afficher `recent`
- l'UI peut purger un viewer
- l'UI peut exporter et reimporter un viewer
- toutes les operations sensibles sont journalisees
