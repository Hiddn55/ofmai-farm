# Ferme M1 — état du projet et reprise à froid

> **Nature** : état + point d'entrée
> **À jour au** : 2026-10-01
> **Répond à** : où en est la ferme, ce qui marche, ce qui ne marche pas, ce qui reste, et **comment une conversation neuve, sans aucun contexte, reprend le travail**.
> **Règle** : ce fichier est réécrit à chaque séance de travail. Le code fait foi ; ce qui n'a pas été vu tourner sur un téléphone est marqué **non prouvé**.

## 1. Le projet en dix lignes

OFMAI vend de la génération d'images et de vidéos IA à des créateurs et des agences OFM. Pour multiplier par dix les abonnés payants, on construit une **armée de six personnages synthétiques** (Sierra, Camila, Hana, Skyler, Riley, Vera) qui publient sur Instagram, TikTok, Reddit et X et ramènent du trafic vers OFMAI / Fanvue.

Chaque personnage vit sur **son propre téléphone virtuel** (GeeLark, cloud, Android 13) derrière **sa propre IP résidentielle statique** (IPRoyal) avec **sa propre boîte mail** (Proton, créée sur le téléphone) et **sa propre ligne US** (US Mobile). Un téléphone = un personnage = tous ses comptes.

Le logiciel qui pilote les téléphones est **ofmai-farm**, un fork de « Ghost in the Droid » (`gitd/`) : des *skills* scriptés (pas des agents) tapent sur l'écran par ADB en lisant l'arbre d'accessibilité (`uiautomator dump`). Un compte neuf est d'abord **chauffé** deux semaines (regarder, liker, suivre, orienté vers la niche) avant de publier ; le contenu vient du **radar** d'OFMAI (comptes de la niche) et est répliqué avec le personnage comme sujet.

Deux dépôts : `ofmai` (la plateforme, Next.js) et `ofmai-farm` (la ferme, Python). **Toute la doc de la ferme est ici, `ofmai-farm/docs/social/`**, index dans `INDEX.md`.

## 2. Où en est-on (2026-09-23)

### Ça marche (vu tourner sur un téléphone)

| Quoi | Preuve | Où |
|---|---|---|
| Cycle de vie d'un téléphone GeeLark par nom de profil : démarrage, ADB, `glogin`, keep-alive 7 min, arrêt en fin de run | sessions du 22 et 23/09, zéro réparation de lien sur 10 min | `gitd/farm/geelark.py`, `gitd/skills/_run_skill.py` |
| Chauffe Instagram complète par le ledger : popups, recherche d'un compte de la niche, ses Reels, sa liste « suivis », un compte découvert, 11 vidéos, 0 action risquée au jour 2 | **session validée le 23/09 00:49 → 00:59 sur `explorer-us` (@jordan.reed.97)** | `gitd/farm/warm.py`, `gitd/skills/ofmai_instagram/` |
| Chauffe TikTok et Reddit geste par geste (like, favori, commentaire, upvote, join…) | explorateur, 22/09 (TikTok 9/10 : le follow n'est pas persisté) | `gitd/skills/ofmai_tiktok/`, `ofmai_reddit/` |
| Chauffe orientée (80 % Reels de comptes connus de la niche / 20 % fil), profondeur 2 sur Instagram, 1 sur TikTok | explorateur, 22/09 et 23/09 | `warm.py`, `warming-policy.md` §7 bis |
| Inscription Reddit et TikTok par skill (email seul / ligne US) — **un compte créé une fois chacun, à moitié à la main** : le code fait les écrans simples, l'humain fait pseudo, genre/intérêts et réglages (Reddit), roue d'anniversaire non éditable, pseudo, éditeur de profil et confidentialité (TikTok) ; le mot de passe scripté (`type_secret`) n'y a pas encore été rejoué | comptes créés sur l'explorateur les 16 et 18/09 | `gitd/skills/ofmai_signup_reddit`, `ofmai_signup_tiktok` |
| **Commentaires écrits devant le post** (décision du 01/10) : la session envoie capture + auteur + légende à OFMAI (`POST /api/farm/comments/compose`), qui répond une ligne dans la voix du personnage, passée par la porte de conformité et journalisée ; sans réponse, pas de commentaire ; les pools de la fiche ne sont plus que des exemples de ton ; **aucune bio ne mentionne l'IA**, pour les six | codé et testé hors téléphone le 01/10 (OFMAI : `compose-comment.ts`, route, `compliance.ts` kinds `comment`/`reply` ; ferme : `composer.py`, `warm.py`, adaptateur Instagram `post_context`) — **non prouvé sur téléphone, et OFMAI non commité** | `bridge-ofmai-farm.md` §3.4 bis, `warming-policy.md` §8.0 |
| Lignes US Mobile activées depuis l'étranger, SMS courts reçus | 18/09 | `numeros-us.md` |
| Boîte Proton d'un personnage créée sur son téléphone, codes lus dans les notifications ; **la restriction Proton « third-party » se lève en validant un e-mail de secours** | 22/09 (Sierra) | `account-creation.md` §4 bis |
| Vitesse d'une étape de skill ≈ 4-6 s (une lecture d'écran par étape, sonde Portal en cache, lien sondé avant toute réparation) | 23/09 : 7 étapes en 33 s au lieu de 1 min 27 | `gitd/skills/base.py`, `gitd/bots/common/adb.py`, `infrastructure-geelark-proxies.md` §7 bis |
| Trois étages devant un écran inconnu (script → agent Claude → humain sur Discord) | codé et testé hors téléphone ; l'étage agent n'a pas de clé sur cette machine | `gitd/farm/unstuck.py`, `advisor.py` |
| Cibles radar (endpoint OFMAI `GET /api/farm/targets`, table `farm_targets`, refroidissement 14 j), score Explore par Claude, juge de niche par l'arbre | codé, tests verts ; **non branché** sur cette machine (`FARM_OFMAI_BASE_URL` absent) ; endpoint OFMAI non commité | `lib/social/bridge-targets.ts`, `gitd/farm/explore_score.py`, `niche.py` |

### Ça ne marche pas (et pourquoi)

| Quoi | Cause connue | Conséquence |
|---|---|---|
| **Inscription Instagram par skill : 0 réussite en 3 essais (22/09 21:36, 23/09 00:12, 00:23)** | (a) le balayage générique de popups du moteur tape le `CANCEL` du dialogue « Set date » après l'étape qui suit le mot de passe ; ma correction ne couvrait que l'après-porte, pas l'après-tap ; (b) le mois tapé d'un bloc (`Aug`) donne avril : la roue complète sur un préfixe et perd la rafale, il faut taper lettre par lettre (prouvé à la main) ; (c) sur l'écran du nom, « Next » tourne en « Loading » et revient (non compris) ; (d) le premier écran a changé de libellé (« Get started ») ; (e) `am start` ne résout pas l'intent sur GeeLark, il faut `monkey` | `sierracole@proton.me` est probablement grillée pour Instagram (deux formulaires abandonnés à 20 min d'écart). Le téléphone `sierra-us` doit se reposer quelques jours |
| **Inscription Reddit de Sierra : refusée 5 fois le 23/09 (20:00 → 20:34)** — code mail accepté, pseudo `sierra_cole_ai` libre, mot de passe envoyé, et à chaque envoi « We had some trouble getting to Reddit » | l'appel de création est refusé depuis `sierra-us` (IP IPRoyal 162.210.67.145) alors que reddit.com répond en HTTP 200 depuis le téléphone ; l'explorateur (autre IP IPRoyal) avait créé un compte le 16/09. **Cause inconnue.** Quatre suspects, aucun prouvé : l'IP du profil, l'appareil, l'adresse Proton, le rythme des gestes du skill. Nathan écarte l'IP (l'explorateur est aussi chez IPRoyal et passe) et soupçonne Proton ou la façon dont le skill crée le compte. **Test décidé le 23/09, à la main, un seul changement à la fois** : (1) `camila-us` + un mail jetable **non-Proton** (alias Gmail), inscription faite par Nathan ; (2) si ça passe, `sierra-us` + le même type de mail jetable, à la main. Lecture : (1) échoue → téléphone/IP en cause, Proton hors de cause ; (1) passe et (2) échoue → l'IP ou l'appareil de `sierra-us` ; les deux passent → Proton ou les gestes du skill. Aucune boîte Proton ne sert au test, pour ne pas en griller une. L'adresse utilisée sur l'explorateur le 16/09 n'est pas écrite dans le relevé | pas de compte Reddit pour Sierra ; le mot de passe Reddit du Trousseau a été régénéré le 23/09 (l'ancien était apparu en clair dans le champ pseudo : la porte « pseudo » du skill s'est fermée sur le mauvais écran et le step `type_secret` a tapé dans le champ visible — **à comprendre avant de rejouer un skill d'inscription**) |
| **Les téléphones GeeLark échouent à l'attestation Google (Play Integrity) — mesuré le 2026-10-01 sur `explorer-us` (Android 13) : `MEETS_BASIC_INTEGRITY`, `MEETS_DEVICE_INTEGRITY` et `MEETS_STRONG_INTEGRITY` tous en échec** | un téléphone GeeLark est une instance Android émulée sur serveur ; Google ne certifie pas l'appareil, et toute app qui exige cette preuve le voit. Conséquences observées : **l'app Reddit refuse l'inscription et la connexion** (deux téléphones, « We had some trouble getting to Reddit »), alors que **reddit.com dans Chrome passe** (compte `u/No-Wall5197` créé le 01/10 sur `camila-us`, pseudo à changer une seule fois en `camila_reyes_ai`) ; **TikTok** répond « Maximum number of attempts reached » avec un code juste, deux fois à 1 h d'écart (refus déguisé probable) ; **Instagram passe** (captcha + suspension levée aussitôt, `@camilia.reyes02` créé le 01/10 par numéro, sans mail). **Même résultat sur un profil Android 15 neuf (`integrity-a15`, Xiaomi MIX Fold 2, créé et testé le 01/10) : les trois niveaux en échec — c'est GeeLark tout entier, pas la version d'Android.** Le choix GeeLark + IPRoyal a été fait sans ce test : erreur de méthode, à ne pas répéter — **tester l'attestation avant tout nouvel achat d'infrastructure** | GeeLark reste valable pour Instagram (app) et Reddit (web) ; TikTok : web à tester, sinon un vrai téléphone ; ne plus acheter de profil ni d'IP tant que ce n'est pas tranché |
| Le budget minutes d'une session n'est pas respecté | les parcours orientés ne regardent pas le chrono en cours de route | 5 min demandées → 10 min 22 s |
| Les corrections ont été validées par des tests **simulés**, pas par un passage sur l'explorateur | méthode | c'est ce qui a coûté l'adresse mail : **plus jamais un vrai compte avant un passage complet sur l'explorateur** |
| Commits de la ferme bloqués depuis cette session | le garde-fou d'OFMAI (`.claude/hooks/commit-gate.mjs`) juge l'arbre OFMAI (tests cassés d'un autre chantier) sur tout `git commit` lancé par l'assistant | Nathan commite lui-même (`git commit` dans `ofmai-farm`, tout est indexé) |
| TikTok : le follow n'est pas persisté | non compris | sans effet avant le jour 7 |
| Étage agent inactif | pas de `ANTHROPIC_API_KEY` ni `ofmai-anthropic-key` dans le Trousseau de cette machine | les alertes Discord partent sans passage par l'agent |

### Ce qui reste (dans l'ordre)

0. **Le test Reddit à la main** (tableau ci-dessus) : il dit si le blocage vient du téléphone, de Proton ou du skill, et donc quoi corriger en premier.
1. **Inscription Instagram** : corriger les cinq points ci-dessus dans `gitd/skills/base.py` (balayage générique désactivé quand le skill liste ses popups ; mois lettre par lettre ; `text_any` déjà en place ; `monkey` déjà en place), puis **prouver le parcours complet sur l'explorateur avec une boîte mail neuve**, chrono en main (cible : ≈ 30 s de skill entre deux portes humaines ; seules portes : code mail, captcha, SMS). Seulement ensuite, Sierra, avec une **nouvelle** boîte Proton (recovery validée avant tout).
1 bis. **Prouver le compositeur sur l'explorateur** : une session Instagram en phase network avec `FARM_OFMAI_BASE_URL` posé, relire les `FarmEvent comment_composed` dans l'admin, puis seulement les vrais comptes. Committer côté OFMAI (route + `lib/social`).
2. Respecter le budget minutes en cours de parcours orienté (`warm.py`).
3. Poser `FARM_OFMAI_BASE_URL` + `ofmai-farm-secret` et committer l'endpoint OFMAI (`app/api/farm/targets`, `lib/social/bridge-targets*`) pour que les cibles viennent du radar.
4. Clé Anthropic dans le Trousseau (`ofmai-anthropic-key`) pour l'étage agent et le score Explore.
5. Mac mini : cloner, venv, `adb`, clé GeeLark dans le Trousseau, daemon en service (`runbook-lancement.md`).
6. Les cinq autres personnages : les téléphones existent ; restent les boîtes mail (Proton avec recovery d'abord, **ou un autre fournisseur si le test Reddit à la main met Proton en cause**), les lignes US Mobile, les fiches alignées sur les villes des proxies, les inscriptions J0.
7. Rampe jours 8-14 / 15+ (onglet Reels, tri par auteur radar ou légende), validation à l'œil des premiers scores Explore.
8. Publication : `post_photo` / `post_story` / `post_video`, label AIGC, `dm_reply` / `comment_reply` avec de vrais messages.
9. Le reste de `build-plan.md` §14.

## 3. Reprendre à froid (conversation neuve, zéro contexte)

**Lire, dans cet ordre** : ce fichier → `INDEX.md` → `rules.md` (les 36 règles) → `runbook-lancement.md` (les commandes) → `warming-policy.md` §7 bis (la chauffe orientée) → `infrastructure-geelark-proxies.md` §5 et §7 bis (le lien ADB) → `account-creation.md` §4 (les skills d'inscription). Les `screens-*.md` sont les relevés écran par écran, à ouvrir quand un skill échoue sur un écran.

**Machine** : le dépôt `ofmai-farm` (fork Ghost), Python dans `.venv`, `adb` sur le PATH. Variables : `GEELARK_APP_ID=DLOTO4D5HB4GVMQH4DYLND6YSG` (à exporter à chaque commande), `FARM_OFMAI_BASE_URL` (à poser). Secrets, **jamais dans un fichier** : Trousseau macOS — `geelark-api-key`, `ofmai-social-<plateforme>-<slug>` (mots de passe des comptes), `ofmai-anthropic-key`, `ofmai-discord-webhook`, `ofmai-farm-secret`.

**Téléphones GeeLark** (profils, nommés par personnage) : `sierra-us` (Sierra, ligne et boîte Proton en place ; **le numéro de sa ligne US Mobile est dans le Trousseau, entrée `ofmai-social-sim-sierra`**, lisible par `security find-generic-password -s ofmai-social-sim-sierra -w` — jamais écrit dans un fichier du dépôt), `explorer-us` (le profil sacrificiel : on y explore les écrans et on y prouve les skills ; Instagram connecté en `@jordan.reed.97`, inscrit au ledger le 23/09), et les six autres profils, **tous créés sur GeeLark avec chacun son IP IPRoyal, tous éteints** : `camila-us`, `hana-us`, `skyler-us`, `riley-us`, `vera-us` (personnages, sans boîte mail ni ligne ni compte à ce jour) et `observer-us` (canaris, jamais de compte de personnage). Un téléphone cloud est facturé à la minute : **l'éteindre en fin de séance** (les runs le font seuls, `FARM_GEELARK_STOP_AFTER=1` par défaut). L'adresse `ip:port` change à chaque démarrage : toujours passer par le nom du profil.

**Commandes de base** (depuis `ofmai-farm`, `PYTHONPATH=.`) :

```sh
# une session de chauffe maintenant (démarre le téléphone, chauffe, l'éteint)
GEELARK_APP_ID=… PYTHONPATH=. .venv/bin/python -m gitd.farm.cli run instagram @jordan.reed.97 --minutes 5
# inscrire un compte au ledger (la base locale des comptes à chauffer)
PYTHONPATH=. .venv/bin/python -m gitd.farm.cli accounts add instagram @handle --device <profil> --tz America/Los_Angeles --created-on AAAA-MM-JJ --niche "@compte1,@compte2,#tag"
# une inscription (portes humaines : code mail, captcha, SMS — jamais un agent)
GEELARK_APP_ID=… PYTHONPATH=. .venv/bin/python -u gitd/skills/_run_skill.py --skill ofmai_signup_instagram --workflow recorded --device <profil> --params '{"slug":"…","email":"…","handle":"…","name":"…","birthday":"AAAA-MM-JJ","bio_line1":"…","bio_line2":"…","bio_line3":"…"}'
# le serveur Ghost (API + flux vidéo du téléphone : http://localhost:5055/api/phone/stream?device=<ip:port>&fps=1)
GEELARK_APP_ID=… .venv/bin/python run.py
# répondre à une porte humaine d'un run
curl -X POST localhost:5055/api/phone/type -H 'Content-Type: application/json' -d '{"device":"<ip:port>","text":"123456"}'
curl -X POST localhost:5055/api/skills/runs/<run_id>/resume -H 'Content-Type: application/json' -d '{"action":"resume"}'
# les tests
.venv/bin/python -m pytest tests -q
```

**Les logs d'un run** sont sur stdout avec l'heure de chaque étape (`_run_skill.py`, `FARM_QUIET=1` pour taire) : c'est le chronomètre.

## 4. Les règles apprises à la dure (à ne pas réapprendre)

1. **Aucun essai sur un vrai compte tant que le skill n'a pas fait le parcours complet, d'une traite, sur l'explorateur.** Des tests unitaires verts sur des écrans simulés ne prouvent rien : ils ont laissé passer trois bugs de suite sur l'inscription Instagram.
2. **Le lien ADB GeeLark ne décroche pas tout seul** (6 min au repos sans un « offline », reconnexion en 0,1 s). Ce qui le met hors ligne une minute, c'est une reconnexion lancée pendant qu'une commande tourne encore sur le téléphone. Sonder le lien (`shell echo`) avant de réparer ; ne jamais reconnecter un lien qui répond.
3. **Un seul `uiautomator dump` à la fois par téléphone** : deux dumps concurrents s'entretuent ou pendent 25 s. Pas de flux vidéo ni d'appel API qui lit l'écran pendant qu'un run lit l'écran.
4. **Lire l'écran une fois par étape** et réutiliser l'arbre ; la sonde Droidrun Portal coûte 2 s par lecture sur un téléphone qui n'a pas l'app.
5. **Le balayage générique de popups (« cancel », « skip », « not now » n'importe où) est interdit sur un parcours de création** : il ferme les dialogues qu'on vient d'ouvrir.
6. **Une roue de date Android se tape** (un appui rend la valeur éditable), **le mois lettre par lettre**.
7. **Un compte abandonné en cours d'inscription grille son adresse mail** : ne relancer une inscription que quand le skill est prouvé, et jamais deux fois de suite sur la même adresse.
8. Boîte Proton : **valider un e-mail de secours avant toute inscription**, sinon les codes des plateformes n'arrivent jamais.
9. Mots de passe et codes ne transitent **jamais** par un paramètre, un log, un message ou un fichier : Trousseau, tapé par le step `type_secret` ou par un humain.
10. Éteindre le téléphone en fin de séance et le dire.
