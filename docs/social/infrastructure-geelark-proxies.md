# Infrastructure — téléphones GeeLark et proxies IPRoyal (runbook)

> **Nature** : reference
> **Statut** : à vérifier — runbook écrit avant la première mise en service ; les points que la doc GeeLark / IPRoyal ne confirme pas sont marqués [à vérifier]
> **À jour au** : 2026-09-22 (§7 bis)
> **Répond à** : comment on monte, relie et maintient un téléphone virtuel par personnage (compte GeeLark, profil, proxy, ADB depuis le Mac mini, enregistrement dans Ghost et dans le ledger), ce que ça coûte, et quoi faire quand ça casse
> **Code concerné** : fork ofmai-farm `gitd/config.py`, `gitd/bots/common/adb.py`, `gitd/farm/geelark.py`, `gitd/skills/_run_skill.py`, `gitd/services/device_context.py`, `gitd/routers/phone.py`, `gitd/models/phone.py`, `gitd/farm/ledger.py`, `gitd/farm/models.py`, `gitd/farm/planner.py`, `gitd/farm/cli.py`, `gitd/farm/policy.py`, `gitd/farm/health.py`, `gitd/skills/gmail_utils.py`, `docs/TROUBLESHOOTING.md` ; OFMAI `lib/ingest/instagram-proxy.ts`, `scripts/radar/TODO.md`, `.claude/loop/notify.mjs`

Les composants et leurs flux sont dans `architecture.md` ; les règles réseau non négociables (R18-R21) dans `rules.md` ; la création des comptes sur le téléphone dans `account-creation.md` ; les canaris qui utilisent le profil observateur dans `health-canaries.md` ; les tâches à coder dans `build-plan.md`. Ici : le matériel virtuel et le réseau, du compte GeeLark au serial ADB enregistré dans `farm_accounts`.

## 1. Qui sait quoi

| Composant | Sait | Ne sait pas |
|---|---|---|
| GeeLark (cloud phone) | modèle, Android, région, langue, fuseau, GPS, proxy du profil ; expose un endpoint ADB (`ip:port` + code) quand le téléphone tourne | rien d'OFMAI, rien du ledger |
| IPRoyal | **une seule** adresse par personnage : statique résidentielle ISP US, trafic illimité, posée une fois et jamais changée | sur quel téléphone elle est posée |
| Mac mini (Paris) — Ghost | `adb -s <serial>` pour tout (`Device(serial)`, `gitd/bots/common/adb.py`), table `phones` (`serial`, `nickname`, `model`, `wifi_ip`, `wifi_port`, `connection_type` — `gitd/models/phone.py`), un job actif par téléphone (`docs/features/scheduler.md`) | proxy, GeeLark : `grep -ri "proxy\|geelark\|iproyal" gitd/farm/` ne renvoie rien |
| Fork `gitd/farm/` | `farm_accounts.device_serial` (un compte par plateforme et par serial, `ledger.add_account()`), `timezone` (défaut `America/New_York`), `created_on` | l'adresse IP du téléphone, le proxy, le profil GeeLark |
| OFMAI | `SocialAccount.deviceSerial`, `timezone`, `role` (`persona \| brand \| observer \| explorer`) — `bridge-ofmai-farm.md` §5.1 ; le pont ne transporte jamais d'identifiant proxy ou GeeLark | — |

Conséquence : **le seul lien entre les trois mondes est le serial ADB** (`ip:port` côté GeeLark = `phones.serial` côté Ghost = `farm_accounts.device_serial` côté farm = `SocialAccount.deviceSerial` côté OFMAI). Tout le reste (id de profil GeeLark, proxy) vit dans un registre local du Mac mini, hors repo (§4.3).

## 2. Compte GeeLark

- **Plan** : Base — API, ADB et RPA sont inclus (page « API » et glossaire « Android Debug Bridge » de geelark.com). ADB est disponible sur Android 9, 11, 12, 13, 14 et 15 ; le téléphone doit être **démarré** avant d'activer ADB, l'activation est asynchrone (attendre ≈ 3 s avant de lire ip/port/code).
- **Tarif** : le brief budgète **29,9 $/mois par téléphone en illimité**. Revue GoLogin (mise à jour 2026-09-01) : location dédiée 24,90 $/mois + 5 $ pour Android 14 = 29,90 $, sans plafond quotidien, −10 % (90 j), −20 % (180 j), −30 % (360 j) ; abonnement Base 13 $/mois (20 profils, 60 min incluses) ; hors location, 0,007 $/min plafonné à 1 $/jour/téléphone (1,20 $ selon une autre source). La page officielle `geelark.com/pricing` n'a pas pu être lue (contenu tronqué) [à vérifier avant l'achat : prix exact du plan Base, prix de la location dédiée par version Android, existence du plafond journalier].
- **Décision** : les 6 téléphones de personnages sont en **location dédiée 24/7** (un téléphone qui ne s'éteint jamais est un vrai téléphone ; l'endpoint ADB ne bouge pas ; pas de « redémarrage » quotidien visible par les apps). L'observateur (§6.1) est en facturation à la minute : ≈ 10 min/jour.
- **Token API** : Trousseau macOS du Mac mini, même mécanisme que `ofmai-discord-webhook` dans `.claude/loop/notify.mjs` :

```sh
security add-generic-password -a ofmai -s ofmai-geelark-token -w '<token>'   # une fois
export GEELARK_TOKEN="$(security find-generic-password -s ofmai-geelark-token -w)"
npm install -g geelark-cli@latest            # CLI officielle, github.com/GeeLark/geelark-cli
geelark-cli config init --token "$GEELARK_TOKEN" && geelark-cli auth status
```

- Une seule personne (Nathan) connaît le mot de passe du compte GeeLark ; l'assistant n'utilise que le token. 2FA du compte GeeLark : activée, code sur le téléphone physique de Nathan [à vérifier : GeeLark propose-t-il la 2FA].

## 3. Un profil par personnage

Un profil GeeLark = un personnage = un téléphone = une identité réseau (R8, `rules.md`). Nom du profil = slug de la fiche persona + marché (`personas.md` §3.2) : `sierra-us`, `camila-us`, `hana-us`, `skyler-us`, `riley-us`, `vera-us`. Le même nom devient `phones.nickname` dans Ghost (§5.3).

| Champ GeeLark | Valeur | Pourquoi / règle |
|---|---|---|
| Nom | `<slug>-us` | même chaîne partout (Ghost, registre local, `utm_content`) |
| Type d'appareil | un modèle grand public courant aux États-Unis, **un modèle différent par personnage** | deux personnages sur le même modèle + même version = même empreinte ; liste des modèles offerts [à vérifier dans l'UI] |
| Android | **13** (ADB supporté 9-15 ; `netType` supporté sur 12, 13 et 15) | la version retenue doit accepter `netType` = 0, ce qui exclut la 14 [à vérifier dans l'API GeeLark] ; même version pour toute la durée de vie |
| Région | **Auto-match** sur le proxy statique | GeeLark aligne alors fuseau, GPS et langue système sur l'IP (blog « cloud-phone-proxy », « GeeLark 101 ») |
| Langue | `en-US` (résultat de l'Auto-match sur une IP US ; vérifier) | les `elements.yaml` des deux skills sont écrits sur les libellés en-US (`docs/FARM.md`) |
| Fuseau | celui de la ville de l'IP statique | **doit être identique** à `farm_accounts.timezone` (`accounts add --tz`) : `plan_sessions()` et `QUIET_HOURS = range(1, 7)` calculent dans ce fuseau (R15, R20) |
| GPS | ville de l'IP statique | ne se règle jamais à la main |
| Proxy | l'**unique** IP statique ISP du personnage (§4) | posée **avant** le premier démarrage ; elle ne change plus jamais ensuite (R18), aucun « Change proxy » sur un profil en service |
| Réseau déclaré | **Wi-Fi** — `netType` = 0 à la création | l'adresse est une connexion domestique : un téléphone qui se dit en 4G tout en sortant par une IP résidentielle fixe est incohérent |

Création (CLI) — `proxyInformation` accepte une URL `socks5://user:pass@host:port` (exemple du README) ; HTTP [à vérifier] :

```sh
geelark-cli phone create --region "us" --mobile-type "Android 13" \
  --data '[{"profileName":"sierra-us","proxyInformation":"socks5://USER:PASS@HOST:PORT","netType":0}]'
# netType 0 = Wi-Fi (Android 12, 13, 15) — obligatoire, l'adresse est résidentielle fixe
# [à vérifier] : code de région US exact (l'exemple du README est "sgp"), champ Auto-match dans --data
```

Après création, dans l'UI : **Check proxy** doit afficher une IP de sortie US, la ville attendue et « connected ». Puis, une fois ADB relié (§5) :

```sh
adb -s "$SERIAL" shell getprop persist.sys.timezone     # ex. America/New_York
adb -s "$SERIAL" shell getprop persist.sys.locale       # en-US
adb -s "$SERIAL" shell settings get secure location_mode   # 3 = high accuracy [à vérifier sur GeeLark]
adb -s "$SERIAL" shell getprop ro.product.model
```

**Ne changent jamais** sur la vie du profil : modèle, version Android, région, langue, fuseau, IP statique. **Jamais « New cloud phone »** sur un profil en service : GeeLark remplace l'appareil et efface ses données (note de version v1.8.0) — pour la plateforme c'est un compte qui apparaît sur un second téléphone. Rayon d'un `suspended` (même règle que R18, `health-canaries.md` S5, `account-creation.md` §9) : au **1ᵉʳ** `suspended` sur un téléphone, seule la plateforme concernée est abandonnée sur ce téléphone (30 j sans nouvelle inscription sur cette plateforme), le profil et l'IP restent ; au **2ᵉ** `suspended` sur le même téléphone dans les 30 j, toute plateforme, téléphone et IP entrent en quarantaine `QUARANTINE_DAYS = 30` (`gitd/farm/policy.py`), tous les comptes sont `disable`, puis le profil est **supprimé** et l'IP rendue, jamais recyclés pour un autre personnage ; le personnage repart sur un nouveau profil et de nouveaux comptes.

**Le choix de la ville n'est pas libre** : IPRoyal est en rupture sur la plupart des villes américaines. On achète d'abord les sept adresses parmi les villes réellement disponibles le jour de l'achat, puis on aligne la ville, le GPS, le fuseau et la fiche persona (`personas.md` §3.2) sur l'adresse obtenue — jamais l'inverse. Les villes de `personas.md` §3.2 sont donc des souhaits, pas des engagements ; le fuseau qui en découle est celui qui part dans `accounts add --tz` (R20). À titre indicatif, la répartition visée : Los Angeles (`sierra-us`), San Francisco (`hana-us`), Las Vegas (`skyler-us`), Seattle (`riley-us`) → `America/Los_Angeles` ; Miami (`camila-us`) → `America/New_York` ; Chicago (`vera-us`) → `America/Chicago`. L'observateur (§6.1) prend un État qu'aucun personnage n'occupe ; l'explorateur (§6.2) prend ce qui reste en stock.

## 4. Proxies IPRoyal par profil

### 4.1 L'adresse unique d'un personnage

Un personnage = **une seule adresse**, et elle sert à tout. Le volet mobile du brief est supprimé (décision 3 de `00-brief-decisions.md`, qui porte les raisons) : il n'y a plus de proxy « dehors », plus de session collante, plus de bascule.

| | Statique résidentielle ISP US, trafic illimité |
|---|---|
| Prix (page pricing IPRoyal, relevé le 2026-09-15) | **2,70 $/IP pour 30 jours** (2,55 $ sur 60 j, 2,40 $ sur 90 j) |
| Sert à | **tout, sans exception** : création du compte Google, inscriptions aux plateformes, vérifications, chauffe, scroll, réponses, posts, et les appels d'API X et Reddit depuis le Mac mini (R21) ; Auto-match région/fuseau/GPS |
| Ne change | **jamais** (R18) : posée une fois avant le premier démarrage, elle se retire avec le personnage |
| Localisation | une ville prise dans le stock réellement disponible à l'achat (§3) ; définit le fuseau et le GPS du compte |
| Partage | une IP par personnage, jamais partagée, jamais réutilisée |

Format des entrées, identique à ce que `lib/ingest/instagram-proxy.ts` accepte : `http://user:pass@host:port`, `user:pass@host:port`, `host:port:user:pass`. Choix de l'État et de la ville à l'achat, dans ce que le dashboard IPRoyal affiche en stock ce jour-là.

**Le compte IPRoyal existant ne sert pas aux personnages.** `scripts/radar/TODO.md` (vérifié le 2026-09-04) : 10 entrées ISP statiques, port 12323, AS7849 RingSquared (Springfield MA) et AS20012 Interworks (Mesa AZ), déjà utilisées par le scraping (`INSTAGRAM_PROXY_URLS`, `ONLYSTATS_PROXY_URLS`) et documentées en **429** sur l'API web Instagram (`documentation/explore/instagram-system.md` § Failed alternatives). On achète 7 IP neuves en vague 0 (6 personnages + observateur), puis une **huitième avant la vague 3** pour le profil explorateur (§6.2, ville indifférente) : 8 au total ; une des 10 anciennes peut, au pire, servir à l'observateur déconnecté [à vérifier].

### 4.2 Une adresse posée une fois, et plus jamais touchée

- **Aucune bascule de proxy, nulle part.** L'entrée IPRoyal d'un profil GeeLark est posée avant le premier démarrage (§3) et n'est plus jamais modifiée : ni pour créer un compte, ni pour une vérification, ni pour une session de post (R18).
- **« Change proxy » est interdit sur un profil en service.** Une IP qui change est le motif « suspicious login », et GeeLark peut rejouer l'Auto-match et déplacer fuseau et GPS sous les pieds du compte (R20). C'est R19, réécrite en ce sens le 2026-09-15 : une seule adresse par personnage, jamais touchée sur un profil en service. GeeLark recommande lui-même de ne pas changer de proxy sans raison (blog « cloud-phone-proxy »).
- **Jamais comme contournement** d'une adresse morte (§9) ni d'un signal santé : un compte en `cooldown` / `verification_required` ne change pas d'IP, on attend le retour de la même adresse.
- Conséquence côté code : **aucun script de bascule à écrire** (`build-plan.md`), et le workflow de publication (`publishing.md`) ne touche jamais au réseau avant un `post_video`.

### 4.3 Où vivent les identifiants proxy

Jamais dans le repo, jamais dans `farm_accounts.notes`, jamais dans un `config_json` de job (R9 : la SQLite de Ghost n'est pas chiffrée et son REST n'a pas d'authentification). Trousseau macOS du Mac mini, une entrée par proxy, valeur au format `host:port:user:pass` :

```sh
security add-generic-password -a ofmai -s ofmai-proxy-sierra-static -w 'HOST:PORT:USER:PASS'
```

Registre local `~/.ofmai/farm/phones.json` (chmod 600, hors repo) : `{ "sierra": { "geelark_profile_id": "…", "serial": "IP:PORT", "timezone": "America/Los_Angeles", "static": "ofmai-proxy-sierra-static", "role": "persona" } }` — une entrée par slug (`sierra`, `camila`, `hana`, `skyler`, `riley`, `vera`, `observer`, `explorer`), et elle ne contient que des **noms** d'entrées Trousseau, pas de valeurs. Les appels API X / Reddit qui doivent sortir par l'IP statique du personnage (R21, `publishing.md`) lisent la même entrée Trousseau.

## 5. ADB depuis le Mac mini et enregistrement dans Ghost

### 5.1 Relier un téléphone

Flux GeeLark (glossaire ADB + note v1.8.0) : démarrer le téléphone → activer ADB → lire ip/port/code → `adb connect` → `glogin`. Exemple (d'après la doc GeeLark, un seul téléphone, même `ip:port` dans les deux commandes) : `adb connect 124.71.210.176:20899` puis `adb -s 124.71.210.176:20899 shell glogin f850ef` (le port n'est pas 5555 malgré le glossaire ; il est propre à chaque téléphone [à vérifier : stable entre deux démarrages ?]).

```sh
ID=<geelark_profile_id>
geelark-cli phone start --ids "$ID"
sleep 5
geelark-cli phone adb set-status --ids "$ID" --open
sleep 3
geelark-cli phone adb get-info --ids "$ID"        # → ip, port, code   [à vérifier : noms exacts des champs]
SERIAL="$IP:$PORT"
adb connect "$SERIAL"
adb -s "$SERIAL" shell glogin "$CODE"
adb devices -l                                     # "$SERIAL  device  model:…"
adb -s "$SERIAL" shell getprop ro.product.model
```

`adb devices` doit lister le serial avec l'état `device` : `list_connected()` (`gitd/bots/common/adb.py`) ne retient que cette ligne, et `Device.adb()` lève `ADBError` sur tout exit non nul (offline, unauthorized, serial inconnu). Le Mac mini garde `DEFAULT_DEVICE` (`gitd/config.py`, env) sur le serial de l'**observateur** : `get_device()` sans serial lève `RuntimeError("Multiple devices connected…")` dès qu'il y a deux téléphones, et les outils du dashboard qui lisent `settings.default_device` (`gitd/routers/bot.py`, `explorer.py`) ne doivent jamais tomber sur un personnage.

### 5.2 Ce que Ghost fait avec un serial réseau

`GET /api/phone/devices` (`gitd/routers/phone.py`) lit `adb devices -l`, reconnaît un serial contenant `:` comme WiFi, écrit ou met à jour `phones` (`serial`, `model`, `wifi_ip`, `wifi_port`, `connection_type = "wifi"`, `first_seen`, `last_seen`). À chaque appel de cet endpoint, au plus une fois par 30 s, `_try_wifi_reconnect()` relance `adb connect ip:port` pour chaque ligne `phones` absente de `adb devices`. Deux limites : (1) rien ne l'appelle si personne n'ouvre le dashboard → un `launchd` sur le Mac mini interroge l'endpoint chaque minute ; (2) **`glogin` n'est pas rejoué** — après une coupure, la reconnexion se fait sans le code [à vérifier : le shell reste-t-il authentifié ?]. D'où le script `scripts/farm_adb_connect.sh` du fork (à créer, `build-plan.md`) : pour chaque entrée de `~/.ofmai/farm/phones.json`, `adb connect` + `glogin` si le serial manque, puis `GET /api/phone/devices`.

```sh
curl -s http://127.0.0.1:5055/api/phone/devices | python3 -m json.tool
curl -s -X POST http://127.0.0.1:5055/api/phone/nickname -H 'content-type: application/json' \
  -d '{"serial":"IP:PORT","nickname":"sierra-us"}'
curl -s "http://127.0.0.1:5055/api/phone/health/IP:PORT"   # model, android_version, apps IG/TikTok/Gmail/Chrome, keyboard, screen_on
```

Les endpoints `POST /api/phone/wireless/{connect,disconnect}` (`{"ip","port"}` / `{"device"}`) existent aussi ; `wireless/enable` (mode `tcpip 5555` d'un téléphone USB) ne concerne pas GeeLark. Le port-forward Portal (`adb -s <serial> forward tcp:<18000+…> tcp:8080`, `_ensure_portal_forward`) fonctionne sur un transport TCP en théorie ; sans Portal, `dump_xml()` retombe sur `uiautomator dump` (≈ 2 s), suffisant pour une session de chauffe. Portal n'est pas installé sur les téléphones de personnages en V1 (une app de plus, inconnue des utilisateurs normaux) [à vérifier : coût réel des 2 s par lecture dans `warm.py`].

### 5.3 Enregistrer le compte dans le ledger

```sh
python -m gitd.farm.cli accounts add instagram @sierra.cole --device IP:PORT --tz America/Los_Angeles \
  --character <AICharacter.id> --niche "gymgirl,fitnessmotivation,losangeles,morningroutine"
python -m gitd.farm.cli accounts list      # platform, handle, serial, day, phase, health
```

`add_account()` (`gitd/farm/ledger.py`) refuse un second compte de la même plateforme sur le même serial (`ValueError("device … already carries …")`) et valide le fuseau (`ZoneInfo(timezone)`). Le planner enfile ensuite chaque session avec `phone_serial=acc.device_serial` (`gitd/farm/planner.py`), et le scheduler Ghost garantit un seul job actif par téléphone. Plateformes acceptées aujourd'hui : `instagram` et `tiktok` seulement (`cli.py`, `ledger.py`) ; X et Reddit sont dans `build-plan.md`.

**Si le serial change** (téléphone redémarré côté GeeLark avec un nouvel `ip:port` [à vérifier]) : aucune commande CLI ne met à jour `device_serial` ; en attendant `accounts set-device` (`build-plan.md`) :

```sh
sqlite3 data/gitd.db "UPDATE farm_accounts SET device_serial='NEW_IP:PORT' WHERE device_serial='OLD_IP:PORT';
                      UPDATE phones SET serial='NEW_IP:PORT', wifi_ip='NEW_IP', wifi_port=PORT WHERE serial='OLD_IP:PORT';"
```

et mettre à jour `~/.ofmai/farm/phones.json` puis `SocialAccount.deviceSerial` côté OFMAI (`bridge-ofmai-farm.md` §3.1).

### 5.4 Accès distant

Ghost écoute sur `0.0.0.0:5055` (`gitd/config.py`) **sans authentification** (sauf `GITD_ADMIN_TOKEN` sur `POST /api/skills/install`, `.env.example`). Le port n'est jamais exposé : pare-feu macOS fermé, accès depuis la Thaïlande en SSH avec tunnel (`ssh -L 5055:127.0.0.1:5055 -L 6175:127.0.0.1:6175 <mac-mini>`), dashboard sur `http://localhost:6175`. Le flux vidéo d'un téléphone se regarde dans l'onglet Phone Agent (MJPEG en repli, `docs/TROUBLESHOOTING.md`) — c'est par là qu'un humain voit un écran de vérification avant un `clear-health` (R26).

## 6. Profils sans personnage : observateur et explorateur

Deux profils ne portent aucun personnage, n'entrent jamais dans `farm_accounts` et ne sont jamais planifiés. Ils ont chacun leur propre adresse statique, jamais celle d'un personnage.

### 6.1 Profil observateur

- Un **septième profil** `observer-us`, même construction (§3), **proxy statique propre**, dans un État différent de tous les personnages, jamais une IP de personnage.
- Apps installées (§7) mais **jamais connecté** à aucun compte : il regarde un profil public Instagram, un sub Reddit (`new`), une vidéo TikTok, exactement comme un inconnu. Pas de canari X (la recherche X exige une session, décision V1 dans `health-canaries.md` §2 : la visibilité X se lit sur les impressions du compte). C'est la seule façon de mesurer un shadowban ; la mesure depuis le compte lui-même est biaisée.
- Facturation à la minute (§2) : le workflow de canaris démarre le téléphone, lit, l'arrête — ≈ 10 min/jour, ≈ 2-3 $/mois. Il est démarré/arrêté par `geelark-cli phone start|stop`, donc son `ip:port` peut changer : le script de connexion (§5.2) le relie à chaque tour [à vérifier : stabilité du port].
- Enregistré dans Ghost (`phones.nickname = observer-us`) et dans `DEFAULT_DEVICE` ; **pas** dans `farm_accounts` (pas de handle, `add_account` en exige un) ; côté OFMAI une ligne `SocialAccount` avec `role = "observer"`, `handle = "observer-us"`, `characterId = null` (`bridge-ofmai-farm.md` §5.1).
- Jamais utilisé pour un checkpoint, un login ou une publication ; son adresse ne bouge pas plus que celle d'un personnage (§4.2).

### 6.2 Profil explorateur (huitième profil, sacrificiel)

- Un **huitième profil** `explorer-us`, même construction (§3), **sa propre adresse statique** (§4, une huitième IP) et **ses propres comptes**, créés à la main sur les quatre plateformes. La ville n'a aucune importance : ce profil ne porte aucun personnage, donc aucun fuseau ni GPS à faire correspondre à une fiche — on prend ce que le fournisseur a en stock ce jour-là.
- **À quoi il sert** : ouvrir et relever les écrans des applications — création de publication, commentaires, boîte de réception, écran de statistiques d'un post — pour corriger les `elements.yaml` des skills (Skill Miner, `build-plan.md` E4.1). La politique de chauffe interdit précisément ces écrans à un compte neuf (`warming-policy.md` §2 : 0 commentaire et 0 post avant `network`, 0 follow en `consume`) : les ouvrir sur le téléphone d'un personnage détruirait sa chauffe et signerait un comportement de robot dès le premier jour.
- **Les repères d'écran appartiennent à l'application, pas au compte** : un `content-desc` ou un `resource-id` relevé sur l'explorateur vaut pour les six personnages, à version d'application égale — c'est bien la version et l'appareil que `tested_on` enregistre (R34), pas le compte.
- **Aucune règle ne s'y applique** : ni caps, ni ratios, ni heures calmes, ni jour de repos, ni pool de commentaires, ni conformité de texte. On y tape et on y ouvre ce qu'on veut. Il ne publie jamais rien d'utile (au plus un média de test supprimé aussitôt), n'a ni fiche persona, ni bio, ni link-in-bio, ni UTM, et n'apparaît dans aucune mesure (`metrics-attribution.md`).
- **Sacrificiel** : s'il est banni, on le remplace, et c'est tout. Pas de quarantaine de téléphone ni d'IP (le rayon d'un `suspended` de §3 ne vaut que pour les personnages), pas de post-mortem, aucun effet sur les règles collectives — ses signaux ne comptent jamais dans `red_accounts()` (`health-canaries.md` §4), sinon un écran d'exploration mettrait toute une plateforme en pause.
- **Jamais dans le ledger** : `ledger.add_account()` le chaufferait, et `--role explorer` est refusé comme `--role observer` (E1.1). Son serial vit dans `FARM_EXPLORER_DEVICE` (`gitd/config.py`, E1.3) à côté de `FARM_OBSERVER_DEVICE`, et côté OFMAI dans une ligne `SocialAccount` `role = "explorer"`, `characterId = null` (`bridge-ofmai-farm.md` §3.1), pour l'inventaire seulement. **Le planificateur ne lui donne jamais de travail** : `planner.tick` ne connaît que les comptes du ledger.
- **Jamais l'IP ni le téléphone d'un personnage, dans aucun sens** : on n'explore pas depuis chez un personnage, et un personnage n'hérite jamais de l'adresse de l'explorateur (R18, R36).
- Facturation : téléphone dédié pendant la vérification des sélecteurs (vague 3), puis à la minute (§2) — il ne se rallume ensuite qu'à chaque mise à jour d'application (R34).

## 7. Installation des apps et compte Google

Ordre, sur l'unique adresse du personnage (§4.1), le jour 0 (aucun compte social avant 24 h, `account-creation.md`) :

1. Premier démarrage : vérifier langue `en-US`, fuseau, heure affichée = heure locale de l'IP.
2. **Compte Google créé sur le téléphone** (Paramètres → Comptes → Ajouter) avec l'email du personnage — c'est l'email de toutes ses inscriptions (brief §4). Google demande souvent un numéro : c'est un checkpoint SMS avec un numéro réel du pool (`account-creation.md`, R25), jamais un numéro virtuel.
3. Play Store : Instagram, TikTok, X, Reddit. **Depuis le Play Store**, pas depuis le catalogue d'APK GeeLark (`geelark-cli phone app install --env-id … --app-version-id …`) : une installation Play Store est ce qu'un utilisateur fait [à vérifier : Play Store présent sur l'image GeeLark choisie ; le catalogue GeeLark passe-t-il par le Play Store ou en sideload].
4. Gmail et Chrome sont attendus : `device_health()` (`gitd/services/device_context.py`) vérifie `com.instagram.android`, `com.zhiliaoapp.musically`, `com.google.android.gm`, `com.android.chrome`, et `gitd/skills/gmail_utils.py` lit les codes reçus dans l'app Gmail de l'appareil (`--device <serial>`, `find_email_by_subject`).
5. Clavier : Gboard, **pas ADBKeyboard** (IME détectable, `docs/features/stealth-mode.md`) ; la ferme ne tape que de l'ASCII (`HumanInput.type_text`, R12). Pas de Portal en V1 (§5.2).
6. Versions : pas de mise à jour automatique des apps (`update_app()` existe, on ne l'appelle pas) ; une mise à jour se fait à la main, puis Skill Miner et `tested_on` (R34, `docs/FARM.md`). Le constat de version TikTok connu du code est `KNOWN_TIKTOK_VERSION = "44.3.3"` (`adb.py`) — la version installée sera plus récente, le warn est attendu.
7. Contrôle : `GET /api/phone/health/<serial>` → `apps.*.installed = true`, `keyboard` = Gboard, `screen_on = true`.

## 7 bis. La session ADB expire

> Mesuré sur `explorer-us` le 2026-09-22 ; ce que GeeLark en dit, vérifié le même jour dans sa doc et son API.

**Ce qu'on observe.** Le `glogin` **expire environ 10 minutes** après avoir été passé. Passé ce délai, la ferme voit l'une de ces deux choses : soit `error: you should run glogin to login first` sur stdout avec un code de sortie 0, soit **plus aucune réponse** — chaque commande adb part en timeout, `glogin` compris, et seul un `adb disconnect` + `adb connect` + `glogin` relance le lien ; juste après cette reconnexion, le transport répond `adb: device offline` quelques secondes. Un `disconnect` sur un lien encore vivant ne fait donc qu'aggraver les choses (152 s perdues sur une session de 159 s le jour de la mesure).

**Ce que GeeLark documente.** Rien sur la durée de vie du code, et aucun moyen de l'allonger :

- L'article « ADB » du centre d'aide (`https://help.geelark.com/ADB-1600be7d9e418006b80cf649bcdc80ad`) : activer ADB sur le profil, démarrer le profil, lire « IP address for connection » et « Connection code » sur l'icône 🔗, puis `adb connect <ip:port>` et `adb -s <ip:port> shell glogin <code>`. Il liste ensuite quelques commandes courantes et la commande root par version d'Android (`su` en 11, `dgs` en 12/13/15, `vu` en 14/16). **Pas un mot sur une validité, une expiration, un keep-alive, une liste blanche d'IP ou un autre mode d'authentification.**
- L'API (`https://openapi.geelark.com`, référence publique sur `open.geelark.com`, miroir lisible : `https://github.com/aruxojuyu665/GeeLark-API-Docs`, fichiers `api-reference/cloud-phone-api-reference/adb/set-adb-status.md` et `get-adb-information.md`) : `POST /open/v1/adb/setStatus` ne prend que `ids` et `open` (booléen) ; `POST /open/v1/adb/getData` ne prend que `ids` et renvoie par téléphone `id`, `ip`, `port`, `pwd`. **Aucun champ de durée, d'échéance ou de TTL, ni en entrée ni en sortie.** Les seules contraintes écrites : ADB sur Android 9/11/12/13/14/15, téléphone démarré avant `setStatus`, activation asynchrone (« attendre environ 3 secondes » avant `getData`) ; codes d'erreur 42002 (téléphone éteint, champs vides), 49001 (ADB désactivé), 49002 (matériel sans ADB).
- La CLI officielle (`https://github.com/GeeLark/geelark-cli`, `cmd/phone/adb.go`) n'expose que `phone adb set-status --ids … --open` et `phone adb get-info --ids …`, avec exactement ces corps de requête. Rien de plus.
- Les pages marketing (`https://www.geelark.com/glossary/android-debug-bridge/`, `https://www.geelark.com/blog/geelark-v180-adb-bulk-changing-proxies-change-ip-url-new-cloud-phone-with-one-click/`, `https://www.geelark.com/blog/cloud-phone-app-automation`) répètent la même procédure ; la seule règle de cycle de vie écrite est qu'**arrêter le téléphone coupe ADB** et invalide l'ancienne commande de connexion.

Conclusion : le délai de 10 minutes est une propriété non documentée du service, on ne peut ni le régler ni le désactiver, et le mot de passe `pwd` est stable tant que le téléphone tourne (le même `getData` le rend à chaque appel). Il n'y a pas non plus de paramètre côté client à essayer (`adb keepalive`, `ADB_…`) : l'expiration est côté téléphone GeeLark, pas côté transport adb. Ce qu'on ne sait pas : si le compteur part du `glogin` ou du dernier ordre adb (mesure §« reste à mesurer »).

**Ce que fait le code.** Deux couches, dans `gitd/farm/geelark.py`, toutes deux inertes quand `GEELARK_APP_ID` et `FARM_GEELARK_PROFILE_IDS` ne sont pas posés (`configured()`), donc sur une ferme de vrais téléphones et dans les tests :

1. **Préventif — `KeepAlive`** (`start_keepalive([serial])`, lancé par `gitd/skills/_run_skill.py` juste après `install_repair()` et arrêté à la sortie du process via `atexit`). Un thread daemon repasse `adb -s <serial> shell glogin <pwd>` sur le lien **vivant** toutes les `GEELARK_ADB_KEEPALIVE_S` secondes (défaut 420 = 7 min, sous les 10 mesurées ; `0` désactive), le premier dès le démarrage puisqu'on ne sait pas de quand date le dernier login. **Jamais de `disconnect`** : c'est ce qui met le lien hors ligne. Le mot de passe est relu à chaque rafraîchissement via `getData` (cache si l'API est en panne) et n'apparaît jamais dans un log, même par le texte d'une exception. Un `glogin` qui part en timeout n'est pas réessayé au tour suivant : c'est un lien gelé, donc l'affaire de la couche 2.
2. **Réactif — `relogin(serial, reason)`**, inchangé, accroché dans `Device._run` (`gitd/bots/common/adb.py`) : `hang` → disconnect + connect + glogin ; `expired` → glogin seul ; `offline` → attendre puis glogin. Il reste le filet si le keep-alive rate un tour ; quand il réussit, il remet le compteur du keep-alive à zéro (`touch()`), pour ne pas doubler le `glogin`.

Coût attendu : un `glogin` (< 1 s) toutes les 7 minutes au lieu de 20 à 150 s de réparation au milieu d'un geste — c'est ce qui doit ramener les sessions de chauffe de 3 posts en 3 minutes à leur rythme nominal.

**Reste à mesurer sur un téléphone** (à faire par Nathan, l'explorateur étant occupé) : une session de 12 minutes avec le keep-alive actif et `GEELARK_ADB_KEEPALIVE_S` à sa valeur par défaut — attendu : zéro `[geelark] … session repaired` dans les logs, deux lignes `keep-alive: … login refreshed` ; puis, si ça tient, la même session avec un intervalle de 9 min (marge) et une autre avec 11 min (doit casser : confirme que c'est bien `glogin` qui recharge le compteur et non le trafic adb). Si le compteur repart à chaque commande adb, le keep-alive est inutile en session et n'a de sens qu'entre deux sessions ; si le `glogin` sur un lien vivant à 7 min ne suffit pas (l'expiration serait liée à la connexion TCP et non au login), il faudra passer à une reconnexion planifiée entre deux gestes, ce qui est un autre chantier.

**Mesuré le 2026-09-22 (explorateur, port du jour 20188)** : lien tenu **13 min** avec la relance préventive (`KeepAlive`, `glogin` toutes les 7 min, sans reconnexion) — **zéro réparation**, deux relances, chaque commande à 0,1 s. Le téléphone avait été démarré par `ensure_online("explorer-us")` en 12 s. Reste à mesurer (T1 du `build-plan.md` §14) : l'intervalle limite (9 puis 11 min) pour savoir si c'est le `glogin` qui remet le compteur à zéro.

## 8. Coûts mensuels (6 personnages + 1 observateur + 1 explorateur)

| Poste | Unité | Quantité | Mensuel |
|---|---|---|---|
| GeeLark, abonnement Base | 13 $/mois (revue GoLogin ; 5 $ selon une autre source) [à vérifier] | 1 | 13 $ |
| GeeLark, téléphone dédié 24/7 | 29,9 $/tél (brief ; 24,90 + 5 $ Android 14 selon la revue — les profils sont en Android 13, le supplément pourrait ne pas s'appliquer [à vérifier à l'achat]) | 6 | 179,4 $ |
| GeeLark, observateur à la minute | 0,007 $/min, ≈ 10 min/jour | 1 | ≈ 2-3 $ |
| GeeLark, explorateur (§6.2) | dédié 29,9 $/mois pendant la vérification des sélecteurs (vague 3, ≈ 1 mois), puis à la minute (≈ 1 $/mois hors mise à jour d'app) | 1 | 29,9 $ puis ≈ 1 $ |
| IPRoyal, IP statique ISP US, trafic illimité | 2,70 $/IP (30 j) | 8 (6 personnages + observateur + explorateur) | 21,6 $ |
| GeeLark + IPRoyal, profil « brand » (compte de marque, `personas.md` §7) — si retenu en vague 0 plutôt que le téléphone de Nathan | 29,9 $ + 2,70 $ | 0-1 | 0 ou ≈ 33 $ |
| **Total** | | | **≈ 218 $/mois ≈ 36 $/personnage** en régime établi (explorateur à la minute) ; **≈ 246 $** le mois de la vague 3, où l'explorateur est dédié ; ≈ 251 $ / ≈ 279 $ avec le profil brand |

Le poste « mobile collant » a disparu (décision 3 du brief) : ≈ 31 $/mois en moins, et 2,40 $ était le tarif 90 jours, pas le tarif mensuel. Avec les 8 téléphones en location 24/7 : ≈ 274 $/mois. Le plan Machine ×10 réserve « comptes/proxies 550 € » sur 21 jours (`documentation/business/growth/machine-x10-2026-09.md`) : l'infrastructure tient dedans, le contenu non (`content-pipeline.md` §9 : ≈ 210 à 720 $/mois de génération au besoin réel — 3 masters gardés par jour et par personnage —, jusqu'à ≈ 1 400 $/mois au plafond de production de 6 assets). Le coût par payant se calcule avec `metrics-attribution.md` §7.

## 9. Pannes courantes

| Symptôme | Cause probable | Réponse |
|---|---|---|
| Job `failed` avec `ADBError … device offline` / serial absent de `adb devices` ; le planner saute les slots (`LATE_TOLERANCE_MINUTES = 20`, jamais rattrapés) | coupure réseau Mac mini ↔ GeeLark, téléphone arrêté, ou `adb` local en vrac | `adb kill-server && adb start-server && adb devices` (`docs/TROUBLESHOOTING.md`) ; `geelark-cli phone start --ids …` si arrêté ; `adb connect` + `glogin` ; vérifier que `_try_wifi_reconnect` tourne (`GET /api/phone/devices`). Les sessions manquées **ne se rejouent pas** : le budget du jour reste tel quel (`farm_actions`) |
| `unauthorized`, `run glogin to login first`, ou commandes adb qui ne répondent plus ~10 min après le dernier login | le login `glogin` a expiré (§7 bis) | en session, `Device` répare seul (`relogin`) et le keep-alive évite d'y arriver ; à la main : `geelark-cli phone adb get-info` → `adb -s … shell glogin <code>` ; si tout pend, `adb disconnect` + `adb connect` d'abord |
| Serial changé (`ip:port` nouveau) | redémarrage du téléphone côté GeeLark | §5.3 (SQL `farm_accounts` + `phones`, registre local, `SocialAccount.deviceSerial`) |
| Check proxy en échec, apps sans réseau, sessions en `error` avec `videos = 0` (`WarmSessionAction` → `success=False`) | proxy statique mort ou identifiants révoqués | **Ne jamais remplacer l'IP statique par une autre** (R18) : ticket IPRoyal, `accounts disable` sur tous les comptes du téléphone tant que le proxy n'est pas revenu, `accounts enable` ensuite. Il n'existe aucune adresse de secours, et c'est voulu (§4.2) |
| IPRoyal a changé l'IP statique derrière la même entrée | remplacement côté fournisseur | traiter comme un déménagement : attendre le signal `verification` éventuel (`_PATTERNS`, `health.py`), humain sur l'écran, `clear-health` ; noter la date dans `~/.ofmai/farm/phones.json` |
| Réseau tombé pendant un `post_video` | adresse ou lien ADB coupés en cours de job | le job finit `success=False` ; si « Share » a été tapé, `ambiguous=true` → `needs_human`, jamais de relance auto (`bridge-ofmai-farm.md` §7) |
| Écran « Confirm it's you », « verify to continue », « add your phone number », « enter the 6-digit code » | vérification de la plateforme (`verification`, `apply_signal` → `VERIFICATION`, `can_run() = False`) | humain : flux vidéo, code SMS du pool réel, puis `python -m gitd.farm.cli accounts clear-health <platform> @<handle>` (R25, R26) |
| Fuseau ou GPS du téléphone ≠ `farm_accounts.timezone` | Auto-match mal appliqué à la création du profil, ou profil recréé | corriger dans le profil (Custom) avant toute session ; le compte ne tourne pas tant que `getprop persist.sys.timezone` ≠ `--tz` (R20) |
| Téléphone arrêté par GeeLark (plafond journalier atteint, abonnement échu, maintenance) ; proposition « New cloud phone » | facturation à la minute au lieu de la location, ou incident GeeLark | `phone start` ; vérifier le mode de facturation du profil ; **refuser « New cloud phone »** sur un profil en service (§3) ; si l'appareil est perdu, le personnage repart de zéro sur un nouveau profil et ses comptes sont abandonnés |
| Token CLI refusé (`auth status` KO) | token révoqué, 2FA GeeLark | régénérer dans le dashboard GeeLark, `security add-generic-password … -U`, `geelark-cli config init` |
| `/sdcard` plein, `post_video` « gallery item not found » | médias poussés par le pont non purgés | `adb -s … shell df /sdcard` ; purge de `/sdcard/DCIM/Camera/` hors session ; le pont doit supprimer après `posted` (`bridge-ofmai-farm.md` §6, étape 4) |
| Job bloqué en `running` | sous-processus mort | le scheduler détecte les orphelins au tick suivant (30 s) ; sinon `POST /api/scheduler/queue/<qid>/kill` |
| Écran éteint / verrouillé, taps sans effet | veille | `adb -s … shell input keyevent KEYCODE_WAKEUP` ; désactiver le verrouillage dans les réglages Android du profil [à vérifier : comportement de veille des téléphones GeeLark] |

Toute panne qui laisse un compte hors service plus d'une heure remonte sur Discord (R32) ; aucune alerte n'existe côté fork aujourd'hui, elle passe par le pont (`health-canaries.md`, `build-plan.md`).

## 10. Avant de mettre un téléphone en service

- Profil nommé `<slug>-us`, modèle unique, Android fixé, Auto-match sur l'IP statique ; Check proxy vert, ville et État attendus.
- `getprop persist.sys.timezone` = `--tz` du `accounts add` ; `persist.sys.locale` = `en-US`.
- ADB relié (`adb devices` → `device`), `glogin` fait, `phones.nickname` posé, `GET /api/phone/health/<serial>` : quatre apps installées, Gboard, écran allumé.
- Entrée Trousseau `ofmai-proxy-<slug>-static` créée (une seule par personnage) ; ligne dans `~/.ofmai/farm/phones.json` ; rien de tout ça dans le repo ni dans `farm_accounts.notes`.
- `DEFAULT_DEVICE` = serial de l'observateur, jamais d'un personnage.
- Avant la vague 3 seulement : profil `explorer-us` créé avec sa propre adresse (§6.2), ses quatre comptes sacrificiels ouverts à la main, `FARM_EXPLORER_DEVICE` posé ; aucune session de chauffe n'y tourne et aucun écran des applications n'est exploré depuis le téléphone d'un personnage (R36).
- `netType` = 0 (Wi-Fi) sur le profil : le téléphone ne se déclare jamais en réseau mobile derrière une adresse résidentielle fixe (§3).
- 24 h de vie sur l'adresse du personnage avant la première inscription (`account-creation.md`) ; le compte n'entre dans le ledger qu'après (`created_on` = jour 1 de `phase_for_day()`).
- Aucun « Change proxy » n'est prévu, ni le jour 0 ni jamais (§4.2).
