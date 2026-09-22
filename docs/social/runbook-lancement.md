# Lancer les chauffes — Mac mini, pas à pas

> **Statut** : écrit le 2026-09-22 pour le premier lancement ; à jour du code de ce jour
> **Répond à** : que faut-il sur le Mac mini, dans quel ordre, et comment on sait que ça tourne
> **Prérequis humains** : les comptes existent (`account-creation.md`), la clé API GeeLark est dans le Trousseau du Mac mini sous le service `geelark-api-key`

## 1. Ce qui tourne, et qui fait quoi

Deux processus, sur la même machine, en permanence :

| Processus | Commande | Rôle |
|---|---|---|
| Serveur Ghost (avec le moteur de jobs) | `python3 run.py` (port 5055) | exécute la file `job_queue` : pour chaque téléphone nommé dans la file, lance `gitd/skills/_run_skill.py` |
| Planificateur de la ferme | `python -m gitd.farm.cli daemon` | toutes les 60 s : pour chaque compte activé, met en file les sessions du jour (heures dérivantes, jour de repos, heures calmes) et les passes de réponses |

Le ledger nomme un téléphone par son **profil GeeLark** (`sierra-us`). Au lancement d'une session, `_run_skill.py` démarre ce téléphone, active ADB, lit l'`ip:port` du jour, se connecte et se logue (`gitd/farm/geelark.py`, `ensure_online`), relance le `glogin` toutes les 7 min pendant la session (`KeepAlive`), et **éteint le téléphone à la fin** (`FARM_GEELARK_STOP_AFTER=1`, défaut — un téléphone cloud est facturé à la minute). Rien à connecter à la main.

## 2. Préparer le Mac mini (une fois, ≈ 30 min)

```sh
# 1. le fork et son environnement
git clone <dépôt ofmai-farm> ~/ofmai-farm && cd ~/ofmai-farm
python3.11 -m venv .venv && .venv/bin/pip install -e ".[llm]"      # [llm] = SDK Anthropic (étage agent, score Explore)
brew install android-platform-tools                                  # adb

# 2. la clé GeeLark, jamais dans un fichier (R9)
security add-generic-password -a farm -s geelark-api-key -w '<clé API GeeLark>'

# 3. l'environnement de la ferme (dans ~/.zshrc ou un fichier sourcé par launchd)
export GEELARK_APP_ID=DLOTO4D5HB4GVMQH4DYLND6YSG          # l'id d'application GeeLark (pas un secret)
export FARM_GEELARK_PROFILE_IDS=637420301105234213        # sierra-us ; ajouter les autres ids, séparés par des virgules
export FARM_GEELARK_STOP_AFTER=1                          # éteindre le téléphone après chaque session
export FARM_OFMAI_BASE_URL=https://ofmai.ai               # le pont (commentaires, cibles radar, événements)
security add-generic-password -a farm -s ofmai-farm-secret -w '<secret du pont>'
security add-generic-password -a farm -s ofmai-anthropic-key -w '<clé API Anthropic>'   # étage agent + score Explore ; sans elle les deux sont des no-op (ou ANTHROPIC_API_KEY dans l'env)

# 4. vérifier
cd ~/ofmai-farm && PYTHONPATH=. .venv/bin/python -m gitd.farm.cli devices list
PYTHONPATH=. .venv/bin/python -c "from gitd.farm import geelark; print(geelark.profile_by_name('sierra-us')['id'])"
sh scripts/farm_tests.sh                                  # la suite doit être verte
```

Les ids de profil : `python -c "from gitd.farm import geelark; print([(p['serialName'], p['id']) for p in geelark.call('/open/v1/phone/list', {'page':1,'pageSize':50})['data']['items']])"`.

## 3. Inscrire un compte au ledger (le jour où il existe)

```sh
PYTHONPATH=. .venv/bin/python -m gitd.farm.cli accounts add instagram @sierra.cole \
  --device sierra-us --tz America/Los_Angeles --created-on 2026-09-22 \
  --character sierra --niche "@gymshark,@whitneyysimmons,@…,#gymgirl,#fitcheck" --role persona --market us
```

- `--device` = le nom du profil GeeLark, pas un `ip:port`.
- `--tz` = le fuseau **du téléphone** (`adb shell getprop persist.sys.timezone`), qui est celui de la ville du proxy (R20).
- `--niche` : les `@pseudo` sont les comptes de la niche pour la chauffe orientée (`warming-policy.md` §7 bis) — 10 à 30 comptes tirés du radar tant que `GET /api/farm/targets` n'alimente pas la table `farm_targets` ; les `#` gardent le détour de recherche classique.
- `--created-on` = la date de création du compte : le jour 1 de la politique en découle.
- Même commande pour `tiktok` et `reddit`. Jamais l'explorateur (`explorer-us`), jamais l'observateur.

`scripts/farm_register_personas.sh <date>` fait les six d'un coup une fois sa table remplie.

## 4. Lancer

```sh
cd ~/ofmai-farm
nohup python3 run.py > logs/server.log 2>&1 &                                   # serveur + moteur de jobs
nohup env PYTHONPATH=. .venv/bin/python -m gitd.farm.cli daemon > logs/planner.log 2>&1 &   # planificateur
PYTHONPATH=. .venv/bin/python -m gitd.farm.cli plan instagram @sierra.cole       # les heures du jour
```

Test immédiat, sans attendre le créneau : `PYTHONPATH=. .venv/bin/python -m gitd.farm.cli run instagram @sierra.cole --minutes 5` — démarre le téléphone, fait une session de 5 min, l'éteint, et imprime `Data: {"videos": …, "likes": …}`.

## 5. Savoir que ça tourne

- `python -m gitd.farm.cli accounts list` et `budget instagram @sierra.cole` : ce qui a été dépensé aujourd'hui.
- L'onglet Scheduler du serveur (`http://<mac-mini>:5055`) : les jobs `farm`, leurs logs, la ligne `Data: {...}` de chaque session.
- `data/unknown_screens/` : les écrans où la session s'est arrêtée (arbre + capture) ; une alerte Discord part au même moment.
- `data/explore/<plateforme>/<compte>/` : la capture d'Explore de fin de session et son score de niche (si `ANTHROPIC_API_KEY`).
- Arrêt d'urgence : `python -m gitd.farm.cli stop` (crée `data/farm/STOP`, tue les jobs en cours) ; reprise : `start`.

## 6. Ce qui n'est pas encore prouvé au 2026-09-22

Le keep-alive `glogin` sur une session de 12 min et plus (mesure T1 du `build-plan.md` §14) ; la liste « suivis » du bloc Reels (T2) ; l'étage agent sur un vrai écran inconnu (T6). Le reste de la liste : `build-plan.md` §14.
