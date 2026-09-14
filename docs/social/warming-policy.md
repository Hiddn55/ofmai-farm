# Politique de chauffe — ce qu'un compte a le droit de faire chaque jour de sa vie

> **Nature** : reference
> **Statut** : en vigueur — §1 à §7 et §9 sont recopiés du code au 2026-09-14 ; §8, §10 et §11 sont des décisions que le code n'applique pas encore (tâches dans `build-plan.md`)
> **À jour au** : 2026-09-14
> **Répond à** : quels plafonds, quels rythmes et quels gestes gouvernent la chauffe d'un compte de personnage, ce qui arrête une session, et quand un compte passe en production (`api_mode`)
> **Code concerné** : fork ofmai-farm `gitd/farm/policy.py` (source des chiffres), `gitd/farm/warm.py`, `gitd/farm/human.py`, `gitd/farm/ledger.py`, `gitd/farm/planner.py`, `gitd/farm/skillkit.py`, `gitd/farm/health.py`, `gitd/farm/cli.py`, `gitd/skills/ofmai_instagram/actions/core.py`, `gitd/skills/ofmai_tiktok/actions/core.py`, `gitd/skills/ofmai_instagram/workflows/__init__.py`, `gitd/skills/ofmai_tiktok/workflows/__init__.py`, `tests/test_farm_policy.py`, `tests/test_farm_warm.py` ; OFMAI : `SocialCommentPool` (`bridge-ofmai-farm.md`, à créer)

`gitd/farm/policy.py` porte en docstring « Mirrors docs/social/warming-policy.md » : ce fichier et ce module disent la même chose ; s'ils divergent, on corrige l'un ou l'autre dans le même commit, et `sh scripts/farm_tests.sh` est la preuve exécutable. Les chiffres sont des **plafonds**, jamais des cibles. Ce que l'appareil, le proxy et le compte doivent être avant le jour 1 : `account-creation.md`, `infrastructure-geelark-proxies.md`. Ce qui se publie et par où : `publishing.md`. Signaux collectifs et canaris : `health-canaries.md`. Règles absolues : `rules.md`.

## 1. Phases et jours

`day_of_life = (aujourd'hui − created_on) + 1` en date locale du compte (`farm_accounts.timezone`, défaut `America/New_York`) ; `created_on` est la date de `accounts add` sauf `--created-on`. `phase_for_day(d, platform)` :

| Phase | Instagram | TikTok (`PHASE_EXTRA_DAYS["tiktok"] = 3`) | Ce que le compte fait |
|---|---|---|---|
| `consume` | jours 1-3 | jours 1-6 | regarde seulement : feed, stories, une ou deux recherches de niche |
| `light` | jours 4-7 | jours 7-13 | premiers likes et enregistrements, 3 follows au plus, aucun commentaire |
| `network` | jours 8-14 | jours 14-23 | follows, premiers commentaires, premiers posts (3 par semaine) |
| `cruise` | jour 15 et après | jour 24 et après | régime de croisière ; candidat à `api_mode` (§10) |

Bornes du code : `d ≤ 3 + extra` → consume, `d ≤ 7 + 2·extra` → light, `d ≤ 14 + 3·extra` → network, sinon cruise (`test_phases_instagram_and_tiktok_offsets`). X et Reddit n'existent pas dans le fork (`add_account` refuse toute plateforme autre que `instagram` / `tiktok`) : ils suivent le calendrier Instagram (`extra = 0`) jusqu'à preuve du contraire, et ne chauffent que sur l'appareil, jamais par API (R17, incident @potter_society) [à vérifier lors de la création des skills `ofmai_x` / `ofmai_reddit`, `build-plan.md`]. Reddit suit ce calendrier pour la **chauffe**, mais son premier post est gouverné par `publishing.md` §5 (compte ≥ 31 jours **et** karma ≥ 100), pas par la phase : le cap `posts_per_week = 3` de `network` n'y autorise rien.

## 2. Caps par action et par phase

Valeurs de `CAPS` dans `policy.py`, par jour et par compte, **avant** le tirage du §4 :

| Phase | likes | saves | follows | comments | posts / semaine | story_views | profile_visits | searches | minutes / jour | sessions / jour |
|---|---|---|---|---|---|---|---|---|---|---|
| `consume` | 0 | 0 | 0 | 0 | 0 | 20 | 4 | 2 | 15-40 | 2-3 |
| `light` | 25 | 6 | 3 | 0 | 0 | 30 | 8 | 3 | 20-50 | 2-3 |
| `network` | 50 | 10 | 12 | 3 | 3 | 40 | 20 | 4 | 30-60 | 2-4 |
| `cruise` | 80 | 15 | 15 | 8 | 7 | 60 | 30 | 5 | 30-60 | 2-4 |

Caps fixés hors tirage (`DailyBudget.build`) : `POST` = 1 par jour dès que `posts_per_week > 0`, sinon 0 (le plafond hebdomadaire est tenu par le ledger, `posts_this_week`, semaine du lundi) ; `VIEW` = 10 000 (borné par le temps de session, pas par le compte) ; `DM_REPLY` = 20 en cruise, 0 avant ; `COMMENT_REPLY` = 20 en network et cruise, 0 avant. Les workflows `comment_reply` / `dm_reply` n'existent pas encore (`docs/FARM.md`, « Not done yet ») : ces deux caps sont réservés. `STORY_VIEW` est budgété sur TikTok mais jamais consommé : le skill TikTok ne connaît que le détour `search` (§7). À coder (E3.4) : une action `STORY_POST` (Instagram seulement, distincte de `POST` et de `STORY_VIEW`), cap 1/jour en `network` et `cruise`, 0 avant, consommée par le workflow `post_story`.

## 3. Ratios tenus à tout instant

`BudgetTracker.allow()` refuse une action si, dans la journée du compte :

- **likes ≤ 15 % des vues** : `MAX_LIKE_PER_VIEW = 0.15` — `count(LIKE) + 1 > 0.15 × max(1, count(VIEW))` → refus. Aucun like avant 7 vues ; 20 vues → 3 likes au plus (`test_like_ratio_never_exceeds_15_percent_of_views`).
- **follows ≤ 30 % des visites de profil** : `MAX_FOLLOW_PER_PROFILE_VISIT = 0.30` — 4 visites → 1 follow, 10 visites → 3. Un follow n'existe que dans la branche « visite de profil » de `run_session` (§7).
- **posts** : `posts_this_week ≥ posts_per_week` → refus, en plus du cap journalier de 1.
- jour de repos (§6) → tout est refusé ; cap du jour atteint → refus (`test_daily_cap_is_hard`).

## 4. Budget quotidien : 40-100 % des caps, déterministe

Chaque matin du compte, `DailyBudget.build(account_key, platform, created_on, day)` tire pour chaque action `floor(cap × U(0,4 ; 1,0))` avec un `random.Random` seedé par `sha256("budget|<platform>:<id>|<AAAA-MM-JJ>")` (`account_key` = `ledger.account_key`, ex. `instagram:3`). Même compte, même date → même budget : rejouer la journée ne donne jamais plus (`test_budget_is_deterministic_and_between_40_and_100_percent_of_caps`). Exemple en cruise : `likes` 80 → entre 32 et 80 ; `comments` 8 → entre 3 et 8. Les minutes et le nombre de sessions sont tirés uniformément dans les plages du §2.

```bash
python -m gitd.farm.cli budget instagram @eva.moore --date 2026-09-20
# @eva.moore instagram — 2026-09-20 — day 20, phase cruise
# sessions: 3 for 47 min total
#   like            12 /  58
#   save             2 /   9
#   follow           1 /  11
#   comment          0 /   5
#   post             0 /   1
#   story_view       7 /  41
#   profile_visit    4 /  19
#   search           1 /   4
#   views           96
```

Le budget vit dans le ledger, pas dans un prompt (R14) : `FarmSession.record()` écrit une ligne `farm_actions` par action, `spent_on()` les recompte à chaque ouverture de session.

## 5. Sessions : nombre, durée, fenêtres dérivantes, heures calmes

`plan_sessions(budget)` (`policy.py`), déterministe par `sha256("sessions|<account_key>|<date>")` :

- **Nombre** : 2-3 (consume, light) ou 2-4 (network, cruise), tiré au §4.
- **Fenêtres** : `_WINDOWS = [(8, 12), (12, 15), (18, 23), (15, 18)]`, prises dans cet ordre (2 sessions = matin + midi ; 3 = + soir ; 4 = + après-midi), puis un départ uniforme dans la fenêtre **décalé de −90 à +90 min**, borné à 07:05-23:40. Aucune journée ne ressemble à la veille (`test_sessions_avoid_quiet_hours_and_vary_by_day` : plus de 15 heures de départ distinctes sur 26 jours).
- **Durées** : les minutes du jour sont réparties par poids log-normaux (σ = 0,5) ; 10 % des sessions deviennent un « coup d'œil » de 1-2 min.
- **Espacement** : au moins 45 min entre la fin d'une session et le début de la suivante (+0 à 30 min tirés) ; une session repoussée après minuit est supprimée.
- **Heures calmes** : `QUIET_HOURS = range(1, 7)` → rien entre 01:00 et 06:59 locale, ni session, ni post, ni bascule de proxy (R16, R20). Un départ tombant dedans est ramené à 07:05-07:55.

Le planner (`python -m gitd.farm.cli daemon`, `planner.tick` chaque 60 s) enfile un job Ghost `skill_workflow` (`priority = 2`, `trigger = "farm"`, `max_duration_s = (minutes + GRACE_MINUTES 10) × 60`) quand `start ≤ now ≤ start + LATE_TOLERANCE_MINUTES (20)` ; un créneau plus vieux est **sauté, jamais rattrapé** (rattraper a l'air robotique). Un créneau = une clé `farm_planned.slot_key = "<account_id>:<start>"`, donc un redémarrage ne double jamais une session. Le scheduler Ghost tient un seul job actif par téléphone et tue le job au-delà de `max_duration_s` (SIGTERM puis SIGKILL). `WarmSessionAction` reçoit `minutes` du créneau ; à 0 (lancement manuel `run`), il prend `session_minutes / sessions`.

```bash
python -m gitd.farm.cli plan tiktok @eva.moore --date 2026-09-22
# 09:47   19 min
# 13:58    2 min
# 20:31   26 min
```

## 6. Jour de repos

Un jour par semaine ISO, choisi par `sha256("rest|<account_key>|<année, semaine>")`, jamais pendant les trois premiers jours de vie (`rest_day = weekday == rest_weekday and dol > 3`). Ce jour-là : tous les caps à 0, 0 minute, 0 session, `plan` répond `no session (rest day)`, `WarmSessionAction` répond `{"skipped": "rest day", "day_of_life": …}` et `allow()` refuse tout (R18). Décision : une publication par API (§10) respecte aussi le jour de repos — le workflow de publication lit `budget_for()` avant de poster [à coder, `build-plan.md`].

## 7. Ce que fait une session (`warm.py`)

`run_session(adapter, human, ledger, cfg)` : « une personne ouvre l'application pendant N minutes ». Chaque session tire une `SessionProfile` (`human.py`) — tremblement de tap 4-9 px, tenue 70-130 ms, vitesse de frappe, 1-5 % de fautes corrigées, temps de lecture — et garde cette signature jusqu'au bout. Ordre pour chaque vidéo :

1. **Contrôle santé** sur le dump XML (`health.detect`) : un signal arrête tout (§9). Si le feed est perdu, `back_to_feed()` (4 retours arrière puis l'onglet Reels / Home) ; toujours perdu → `error = "lost the feed"`.
2. **Regarder** (`human.watch()`) : 10-28 % de vidéos zappées en 0,6-1,5 s ; 4-14 % de « lingering » 12-60 s ; le reste 1,5-20 s autour de 4-9 s. Une ligne `farm_actions` `view`.
3. **Liker** : propension de la phase × `allow(LIKE)` ; les deux skills double-tapent la vidéo 6 fois sur 10, sinon le bouton « Like » ; jamais de dé-like (« Liked » / « Unlike » présent → rien).
4. **Enregistrer** : Instagram « More options » → « Save » ; TikTok « Favorites ».
5. **Visiter le profil de l'auteur** (`open_author`), lire la bio (`pause(2.5)`), nouveau contrôle santé, **follow** seulement ici et seulement si `allow(FOLLOW)` ; retour au feed.
6. **Commenter** : un texte tiré au hasard du pool (`comments.pop(...)`, jamais deux fois le même dans la session), pause « réflexion » `1.5`, saisie caractère par caractère (ASCII pur, R13), contrôle santé après. Sans pool, la branche n'existe pas.
7. **Détour** toutes les `DETOUR_EVERY = (12, 30)` vidéos : `search` (Instagram : onglet Search, `#<niche>`, Entrée, 1-3 défilements de 1,5-4 s ; TikTok : loupe, requête sans `#`) compte un `search` ; `stories` (Instagram seulement : Home, une story qui n'est pas « Your story », 2-6 taps de 2-6 s) compte un `story_view`. La requête vient de `niche` (`farm_accounts.niche`, ex. `fitness,ootd,gymgirl`).
8. **Poser le téléphone** : `PHONE_DOWN_RATE = 0.03` par vidéo, `PHONE_DOWN_S = (20.0, 90.0)` secondes sans rien faire.
9. **Vidéo suivante** : swipe vertical avec dérive latérale, amplitude 40-68 % de l'écran, 150-1 200 ms — jamais un `input tap` nu (`test_instagram_warm_session_runs_against_fake_device`).

Propensions par phase (`PROPENSITY`, avant le oui/non du ledger) :

| Phase | like | save | visite de profil | follow si visite | comment |
|---|---|---|---|---|---|
| `consume` | 0 | 0 | 0,02 | 0 | 0 |
| `light` | 0,09 | 0,03 | 0,05 | 0,25 | 0 |
| `network` | 0,11 | 0,04 | 0,07 | 0,35 | 0,04 |
| `cruise` | 0,12 | 0,04 | 0,08 | 0,30 | 0,05 |

**X et Reddit (skills à créer, E3.1)** — le `PlatformAdapter` de `warm.py` est écrit pour un feed vidéo ; sur ces deux apps, l'unité de `VIEW` est une **carte de post** du fil `For you` (X) / `Home` (Reddit), `watch()` inchangé ; `like` = cœur (X) / upvote (Reddit, sous le cap `likes`, jamais hors chauffe : manipulation de votes) ; `save` = signet (X) / « Save » (Reddit) ; `open_author` = profil de l'auteur (X) / profil de l'auteur, jamais le sub (Reddit) ; `follow` = Follow (X) / « Join » du sub du post (Reddit), sous le cap `follows` et seulement dans la branche `open_author` (R17) ; `comment` = pool ASCII, jamais sur X avant `network` ; détours : `search` uniquement (`#<niche>` sur X, `r/<niche>` puis onglet `Hot` sur Reddit), pas de `stories` ; santé : motifs `_PATTERNS["x"]` / `["reddit"]` d'E3.1.

**Ce qui met fin à une session** : le temps écoulé (`deadline`) ; un signal santé (`stats.health`, `success = False`, `error = "health signal: …"`) ; `feed not reachable` à l'ouverture ; `lost the feed` ; une exception (`stats.error`, la session rend quand même ses compteurs) ; le timeout du scheduler ; un `POST /api/scheduler/queue/<qid>/kill` humain. Chaque session finit par une ligne `Data:` reprise dans l'onglet Scheduler de Ghost :

```json
{"videos": 118, "likes": 9, "saves": 2, "visits": 6, "follows": 2, "comments": 1, "detours": 4,
 "seconds": 1462.3, "health": null, "error": null,
 "handle": "eva.moore", "day_of_life": 20, "phase": "cruise", "profile_seed": 733120544}
```

## 8. Pools de commentaires par persona

Le code attend `params.comments` (ASCII, un par ligne, `WarmSessionAction`), mais `planner.job_config` ne passe que `handle`, `minutes`, `niche` : **aujourd'hui aucune session ne commente**. Le pool vit côté OFMAI (`SocialCommentPool` : `characterId`, `platform`, `text`, `reservedUntil`, `usedAt`, `usedByHandle`), est servi par `GET /api/farm/comments?character_id=…&platform=…&n=10` et remonte dans `session_summary.comments_used` (`bridge-ofmai-farm.md` §3.4, §4.1).

Règles d'un commentaire :

- ASCII pur, 2 à 8 mots, minuscules acceptées, pas d'emoji (`type_text` les supprime), pas de lien, pas de `@`, pas de `#`, pas de prix ni de « free ».
- Réagit au **visuel** (lumière, lieu, tenue, geste), jamais au corps de l'autre, jamais une question sur « real » ; aucune mention d'OFMAI ni d'IA sur le contenu des autres (un commentaire promotionnel est du spam, R23) ; aucun nom de fournisseur, jamais « same face » (R11, R12).
- Écrit dans la voix de la fiche persona (`personas.md`) par l'agent du workflow quotidien, passé par l'étage 1 de conformité (`content-pipeline.md` §8), puis inséré dans `SocialCommentPool`.
- Stock : ≥ 60 textes disponibles par personnage et par plateforme ; réapprovisionné dès que le stock passe sous 20 ; un texte n'est jamais réutilisé sur le même compte à moins de 30 jours (`usedAt`) ; réservation 24 h à la livraison, rendue si non consommée.
- Consommation réelle : `comments` 3/jour en network, 8/jour en cruise avant tirage (§2), propension 0,04-0,05 par vidéo : une session de 25 min en pose 0 à 2.

Exemple pour Eva (chic méditerranéen, assurée, sobre ; niche `fitness,ootd`) :

```text
this light is unreal
ok the earrings
need this whole outfit
summer in one frame
the hair tho
effortless as always
where is this??
that palette is everything
form check: perfect
golden hour did its job
```

## 9. Santé : machine d'états et effets sur la phase

`health.detect(platform, xml)` cherche des motifs en-US dans le dump XML après chaque étape (`_PATTERNS`, Instagram et TikTok) et rend le plus grave présent : `suspended` > `logged_out` > `verification` > `action_blocked`. `FarmSession.signal()` écrit `farm_signals` puis `policy.apply_signal()` :

| Statut (`policy.Health`) | Signal | Durée | `phase_override` | Reprise |
|---|---|---|---|---|
| `ok` | — | — | aucun (ou celui hérité) | — |
| `cooldown` | `action_blocked` : « action blocked », « try again later », « we limit how often », « tapping too fast », « too many attempts »… | `COOLDOWN_HOURS = 48` | la phase **précédant** la phase naturelle (cruise → network, network → light, light → consume) | automatique à l'échéance ; l'override reste |
| `verification_required` | `verification` : « confirm it's you », « suspicious login », « verify to continue », « drag the slider », « enter the confirmation code »… | illimitée | inchangé | un humain agit sur l'appareil (checkpoint, R26), puis `clear-health` |
| `shadowban_suspect` | `shadowban` : émis par l'analytique, jamais par l'écran ; `zero_reach(view_counts)` = les 3 derniers posts à ≤ 2 vues, **appelé nulle part aujourd'hui** (`health-canaries.md`) | `SHADOWBAN_DAYS = 7` | `consume` (regarder seulement, aucun post) | automatique ; l'override reste |
| `logged_out` | `logged_out` : « log in », « create new account », « sign up for tiktok » | illimitée | inchangé | un humain (« never auto-login »), puis `clear-health` |
| `suspended` | `suspended` : « your account has been suspended », « we banned your account », « community guidelines violation »… | `QUARANTINE_DAYS = 30` | aucun | jamais (`can_run` = False) ; appareil et IP en quarantaine 30 jours (R19) |

Effets :

- Le signal **arrête la session** (R28) et `planner.tick` ne planifie plus rien tant que `HealthState.can_run(now)` est faux ; `open_session()` lève `PermissionError("@… is cooldown until …")` ou `"… — a human must act on the device"`, y compris pour un `run` manuel.
- `effective_phase = min(phase naturelle, phase_override)` ; `ledger.budget_for()` reconstruit le budget avec les **caps de la phase forcée**, même seed, vrai `day_of_life` (`test_signal_puts_account_in_cooldown_and_blocks_next_session`).
- `cooldown` et `shadowban_suspect` expirés → `health = ok` à la session suivante, mais `phase_override` reste jusqu'à `accounts clear-health` (geste humain, R27). Un compte sorti de cooldown rechauffe donc une phase en dessous tant que personne n'a regardé l'écran.
- Deux comptes rouges en 48 h sur une plateforme → pause de la plateforme ; trois `suspended` en 48 h → plateforme coupée : règles collectives **hors code** (`health-canaries.md`, R30, R31).

```bash
python -m gitd.farm.cli accounts list                                # day, phase, health=…, [disabled], [api]
python -m gitd.farm.cli accounts clear-health instagram @eva.moore   # ok, health_until NULL, phase_override NULL
python -m gitd.farm.cli accounts disable tiktok @eva.moore           # pause manuelle
```

## 10. Passage en `api_mode`

Deux notions à ne pas confondre : `channel` (`bridge-ofmai-farm.md` §3.2) dit par où part **une publication** (`device` = workflow `post_video`, `api`) ; `api_mode` (`farm_accounts.api_mode`) dit le **régime de sessions** du compte. La source de vérité d'`api_mode` est OFMAI : `PATCH /api/admin/social/accounts/{id} {"apiMode": true}` (E7.2), recopié dans `farm_accounts.api_mode` par le pont à chaque tick (`bridge-ofmai-farm.md` §6, étape 1) ; la commande CLI `accounts api-mode <plateforme> <handle> on|off` ne sert qu'en mode dégradé, pont arrêté, ou sur un appareil de test, et est écrasée au tick suivant.

| Plateforme | Chauffe sur l'appareil | Premiers posts (`network`, 3 / semaine) | Posts en `cruise` | `api_mode` |
|---|---|---|---|---|
| Instagram | oui, toute la vie du compte | `post_video` (Reel depuis la galerie) | `post_video`, 1 / jour, 7 / semaine (+ 1 story, E3.4) | **jamais** (API Graph exclue) |
| TikTok | oui | `post_video`, toggle « AI-generated content » confirmé (R4) | API Content Posting via le MCP Higgsfield (`tiktok_connect`, `tiktok_prepare_publish`, `tiktok_publish`, 13 posts / jour côté API, notre cap §11) | `PATCH … {"apiMode": true}` au passage en cruise, après la checklist §13 |
| X | oui (skill à créer) | API officielle depuis le Mac mini, par l'IP statique du personnage (R22) | idem, cap §11 | idem au passage en cruise |
| Reddit | oui (skill à créer) | `post_video` jamais ; publication API seulement à `day_of_life ≥ 31` **et** karma ≥ 100 (relevé par `metrics_pull` / écran profil), condition posée dans `publish-api.ts` et dans `GET /api/farm/queue` (aucune publication Reddit servie avant) — le cap `posts_per_week` du ledger ne suffit pas ; zéro lien dans le post (R23) | idem, cap §11 | idem au passage en cruise |

Ce qui change **aujourd'hui dans le code** quand `api_mode = 1` : `planner.tick` saute le compte (`if acc.api_mode: continue`) — plus aucune session ; `accounts list` affiche `[api]` ; `post_video` n'est plus enfilé ; la publication par API est décrite dans `publishing.md`. Aucune publication par API n'existe encore, ni le routage par l'IP statique.

Ce que la décision du brief exige (« l'appareil ne fait plus que de la consommation légère ») et que le code doit apprendre (`build-plan.md`) : en `api_mode`, le planner continue à planifier des sessions avec les caps ci-dessous, et la publication API appelle `open_session().allow(POST)` / `record(POST)` comme le fait `PostReelAction`, pour que le quota reste dans le ledger (R14).

| Régime | likes | saves | follows | comments | posts appareil | story_views | profile_visits | searches | minutes / jour | sessions / jour |
|---|---|---|---|---|---|---|---|---|---|---|
| `api_mode` (cible) | 25 | 6 | 0 | 0 | 0 | 30 | 8 | 3 | 20-50 | 2-3 |

Soit les caps `light` sans follow ni commentaire ; `COMMENT_REPLY` et `DM_REPLY` (20) restent sur l'appareil pour répondre sous ses propres posts quand les workflows existeront.

## 11. Arbitrage : 1 post / jour sur l'appareil contre 6 assets / jour / personnage

`policy.py` plafonne l'appareil à `POST = 1` / jour et `posts_per_week` 3 (network) / 7 (cruise) ; le brief vise 6 assets / jour / personnage et le plan ×10 « 2-4 posts / jour / compte ». Les trois sont compatibles parce qu'un asset n'est pas un post (un clip re-rendu sert plusieurs plateformes, `content-pipeline.md` §6 et §9 : 16 variantes prêtes par jour) et parce que le volume passe par l'API, jamais par l'appareil :

| Compte | Canal en cruise | Cap / jour (décision) | Cap / semaine |
|---|---|---|---|
| Instagram | appareil | 1 (`POST`, inchangé) | 7 (`posts_per_week`) |
| TikTok | API | 2 | 14 |
| X | API | 3, puis 2 si < 500 impressions / post après 100 posts, 1 à J7 (`metrics-attribution.md` §7) | 21 |
| Reddit | API | 2, sur deux subs différents | 14 |

Total par personnage en cruise : jusqu'à 8 posts / jour (+ 1 story Instagram sur l'appareil, E3.4), depuis ≈ 4 assets gardés (`content-pipeline.md` §9). Le cap API se tient dans le ledger via une table par **plateforme** dans `policy.py` — `API_POSTS_PER_DAY = {"tiktok": 2, "x": 3, "reddit": 2}`, 0 hors cruise, posée par `DailyBudget.build` dans `caps[API_POST]` (un cap par phase dans `PhaseCaps` ne peut pas porter des valeurs par plateforme) — et une action `API_POST` distincte de `POST` [à coder, E8.3]. Règles communes aux deux canaux : jamais en heures calmes, jamais le jour de repos, au moins 3 h entre deux posts d'un même compte (appliqué par `POST /api/admin/social/queue`, E6.6), et 3 ou 4 posts / jour seulement après que les seuils J7 tiennent — **jamais sur l'appareil**, dont les chiffres ne bougent pas (R15).

## 12. Exemples de journée par phase

Chiffres illustratifs, tirés dans les plages du code ; les vrais dépendent du seed `(compte, date)`.

**Instagram, jour 2 (`consume`)** — budget : 2 sessions, 27 min ; `story_view` 20 → 13, `profile_visit` 4 → 2, `search` 2 → 1, tout le reste 0. `plan` : `09:47 19 min`, `20:12 8 min`. La session du matin regarde ≈ 110 reels, fait un détour stories (4 taps) et une recherche `#gymgirl`, pose le téléphone deux fois ; zéro like, zéro follow. `Data:` `{"videos": 112, "likes": 0, "saves": 0, "visits": 1, "follows": 0, "comments": 0, "detours": 2, …}`.

**Instagram, jour 6 (`light`)** — `likes` 25 → 17, `saves` 6 → 3, `follows` 3 → 2, `story_view` 30 → 19, `profile_visit` 8 → 5, `search` 3 → 2 ; 3 sessions, 41 min : `08:31 2 min` (coup d'œil), `13:05 24 min`, `21:40 15 min`. Sur 150 vues, 9-14 likes (ratio 15 % jamais dépassé), 1 follow après la 4e visite de profil, aucun commentaire (propension 0).

**TikTok, jour 16 (`network`)** — `likes` 50 → 33, `saves` 10 → 6, `follows` 12 → 7, `comments` 3 → 2, `post` 1 (si moins de 3 cette semaine), `profile_visit` 20 → 13, `search` 4 → 3 ; 3 sessions, 50 min. Un `post_video` à 12:40 (légende ASCII, toggle AIGC), 2 commentaires du pool posés dans l'après-midi, détours par recherche uniquement.

**Instagram, jour 20 (`cruise`)** — `likes` 80 → 58, `saves` 15 → 9, `follows` 15 → 11, `comments` 8 → 5, `post` 1, `story_view` 60 → 41, `profile_visit` 30 → 19, `search` 5 → 4 ; 4 sessions, 55 min entre 07:50 et 23:10 ; un Reel posté sur l'appareil dans la fenêtre de midi.

**TikTok, jour 30 (`cruise`, `api_mode`)** — aujourd'hui : aucune session (le planner saute le compte), 2 posts par API à 11:20 et 19:05. Cible §10 : 2-3 sessions légères en plus (25 likes, 0 follow, 0 commentaire).

**Jour de repos (n'importe quelle phase après le jour 3)** — `plan` → `2026-09-24: no session (rest day)` ; aucun post, ni appareil ni API.

## 13. Checklist de fin de chauffe (entrée en cruise, puis `api_mode`)

- [ ] `accounts list` : `day ≥ 15` (Instagram) ou `≥ 24` (TikTok), `phase cruise`, `health=ok`, ni `[disabled]` ni `phase_override` (sinon `clear-health` après avoir regardé l'écran).
- [ ] Aucune ligne `farm_signals` sur les 7 derniers jours et ratios tenus dans `farm_actions` :

```bash
sqlite3 data/gitd.db "select kind, count(*) from farm_actions where account_id = 3 and day >= date('now', '-7 day') group by kind"
sqlite3 data/gitd.db "select kind, matched, at from farm_signals where account_id = 3 and at >= datetime('now', '-7 day')"
```

- [ ] Au moins 3 posts publiés sur l'appareil pendant `network`, aucun retiré, chacun visible depuis le profil observateur déconnecté (`health-canaries.md`).
- [ ] Profil complet : mention « AI » en bio, link-in-bio avec les UTM du personnage (`personas.md`, `metrics-attribution.md`), aucun lien hotofmai.ai sur Instagram / TikTok (R24).
- [ ] `tested_on` non vide dans `skill.yaml` du skill du compte (R35) et deux sessions consécutives sans `error` à 0 vidéo.
- [ ] Pool de commentaires ≥ 60 textes disponibles pour ce personnage et cette plateforme (§8), stock de variantes `ready` ≥ 3 jours (`content-pipeline.md` §9).
- [ ] TikTok seulement : OAuth (`tiktok_connect`) réalisé depuis le téléphone du personnage [à vérifier], premier post API publié avec le paramètre AIGC et relu à 24 h depuis l'observateur, puis `PATCH /api/admin/social/accounts/{id} {"apiMode": true}` (E7.2) — recopié dans `farm_accounts.api_mode` par le pont ; `accounts api-mode` seulement si le pont est arrêté.
- [ ] Discord reçoit les alertes (`DISCORD_WEBHOOK_URL`) et quelqu'un peut atteindre l'appareil dans l'heure (R33).

Un point non coché = le compte reste en cruise sur l'appareil, aux caps du §2 ; on ne force rien.
