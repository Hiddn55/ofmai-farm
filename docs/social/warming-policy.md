# Politique de chauffe — ce qu'un compte a le droit de faire chaque jour de sa vie

> **Nature** : reference
> **Statut** : en vigueur — §1 à §7 et §9 sont recopiés du code au 2026-09-14, à une exception près, signalée sur place : la provenance des requêtes du détour de recherche (§7, étape 7) est la décision de §8.2 ; §8, §10 et §11 sont des décisions que le code n'applique pas encore (tâches dans `build-plan.md`)
> **À jour au** : 2026-09-15
> **Répond à** : quels plafonds, quels rythmes et quels gestes gouvernent la chauffe d'un compte de personnage, d'où viennent les commentaires et les comptes qu'il suit, ce qui arrête une session, et quand un compte passe en production (`api_mode`)
> **Code concerné** : fork ofmai-farm `gitd/farm/policy.py` (source des chiffres), `gitd/farm/warm.py`, `gitd/farm/human.py`, `gitd/farm/ledger.py`, `gitd/farm/planner.py`, `gitd/farm/skillkit.py`, `gitd/farm/health.py`, `gitd/farm/cli.py`, `gitd/skills/ofmai_instagram/actions/core.py`, `gitd/skills/ofmai_tiktok/actions/core.py`, `gitd/skills/ofmai_instagram/workflows/__init__.py`, `gitd/skills/ofmai_tiktok/workflows/__init__.py`, `tests/test_farm_policy.py`, `tests/test_farm_warm.py` ; OFMAI : `TrackedInfluencer` (radar, source des cibles de §8.2), `SocialCommentPool` et `SocialTargetUse` (`bridge-ofmai-farm.md`, à créer)

`gitd/farm/policy.py` porte en docstring « Mirrors docs/social/warming-policy.md » : ce fichier et ce module disent la même chose ; s'ils divergent, on corrige l'un ou l'autre dans le même commit, et `sh scripts/farm_tests.sh` est la preuve exécutable. Les chiffres sont des **plafonds**, jamais des cibles. Ce que l'appareil, le proxy et le compte doivent être avant le jour 1 : `account-creation.md`, `infrastructure-geelark-proxies.md`. Ce qui se publie et par où : `publishing.md`. Signaux collectifs et canaris : `health-canaries.md`. Règles absolues : `rules.md`.

## 1. Phases et jours

`day_of_life = (aujourd'hui − created_on) + 1` en date locale du compte (`farm_accounts.timezone`, défaut `America/New_York`) ; `created_on` est la date de `accounts add` sauf `--created-on`. `phase_for_day(d, platform)` :

| Phase | Instagram | TikTok (`PHASE_EXTRA_DAYS["tiktok"] = 3`) | Ce que le compte fait |
|---|---|---|---|
| `consume` | jours 1-3 | jours 1-6 | regarde seulement : feed, stories, une ou deux recherches de niche |
| `light` | jours 4-7 | jours 7-13 | premiers likes et enregistrements, 3 follows au plus, aucun commentaire |
| `network` | jours 8-14 | jours 14-23 | follows, premiers commentaires, premiers posts (3 par semaine) |
| `cruise` | jour 15 et après | jour 24 et après | régime de croisière ; candidat à `api_mode` (§10) |

Bornes du code : `d ≤ 3 + extra` → consume, `d ≤ 7 + 2·extra` → light, `d ≤ 14 + 3·extra` → network, sinon cruise (`test_phases_instagram_and_tiktok_offsets`). X et Reddit n'existent pas dans le fork (`add_account` refuse toute plateforme autre que `instagram` / `tiktok`) : ils suivent le calendrier Instagram (`extra = 0`) jusqu'à preuve du contraire, et ne chauffent que sur l'appareil, jamais par API (R16, incident @potter_society) [à vérifier lors de la création des skills `ofmai_x` / `ofmai_reddit`, `build-plan.md`]. Reddit suit ce calendrier pour la **chauffe**, mais son premier post est gouverné par `publishing.md` §5 (compte ≥ 31 jours **et** karma ≥ 100), pas par la phase : le cap `posts_per_week = 3` de `network` n'y autorise rien.

## 2. Caps par action et par phase

Valeurs de `CAPS` dans `policy.py`, par jour et par compte, **avant** le tirage du §4 :

| Phase | likes | saves | follows | comments | posts / semaine | story_views | profile_visits | searches | minutes / jour | sessions / jour |
|---|---|---|---|---|---|---|---|---|---|---|
| `consume` | 0 | 0 | 0 | 0 | 0 | 20 | 4 | 8 | 15-40 | 2-3 |
| `light` | 25 | 6 | 3 | 0 | 0 | 30 | 8 | 8 | 20-50 | 2-3 |
| `network` | 50 | 10 | 12 | 3 | 3 | 40 | 20 | 8 | 30-60 | 2-4 |
| `cruise` | 80 | 15 | 15 | 8 | 7 | 60 | 30 | 6 | 30-60 | 2-4 |

`searches` monte à 8 (puis 6) depuis le 2026-09-22 : il paie aussi les tours de Reels orientés du §7 bis, 2-3 comptes de la niche par session.

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
python -m gitd.farm.cli budget instagram @sierra.cole --date 2026-09-20
# @sierra.cole instagram — 2026-09-20 — day 20, phase cruise
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

Le budget vit dans le ledger, pas dans un prompt (R13) : `FarmSession.record()` écrit une ligne `farm_actions` par action, `spent_on()` les recompte à chaque ouverture de session.

## 5. Sessions : nombre, durée, fenêtres dérivantes, heures calmes

`plan_sessions(budget)` (`policy.py`), déterministe par `sha256("sessions|<account_key>|<date>")` :

- **Nombre** : 2-3 (consume, light) ou 2-4 (network, cruise), tiré au §4.
- **Fenêtres** : `_WINDOWS = [(8, 12), (12, 15), (18, 23), (15, 18)]`, prises dans cet ordre (2 sessions = matin + midi ; 3 = + soir ; 4 = + après-midi), puis un départ uniforme dans la fenêtre **décalé de −90 à +90 min**, borné à 07:05-23:40. Aucune journée ne ressemble à la veille (`test_sessions_avoid_quiet_hours_and_vary_by_day` : plus de 15 heures de départ distinctes sur 26 jours).
- **Durées** : les minutes du jour sont réparties par poids log-normaux (σ = 0,5) ; 10 % des sessions deviennent un « coup d'œil » de 1-2 min.
- **Espacement** : au moins 45 min entre la fin d'une session et le début de la suivante (+0 à 30 min tirés) ; une session repoussée après minuit est supprimée.
- **Heures calmes** : `QUIET_HOURS = range(1, 7)` → rien entre 01:00 et 06:59 locale, ni session, ni post (R15). Un départ tombant dedans est ramené à 07:05-07:55.

Le planner (`python -m gitd.farm.cli daemon`, `planner.tick` chaque 60 s) enfile un job Ghost `skill_workflow` (`priority = 2`, `trigger = "farm"`, `max_duration_s = (minutes + GRACE_MINUTES 10) × 60`) quand `start ≤ now ≤ start + LATE_TOLERANCE_MINUTES (20)` ; un créneau plus vieux est **sauté, jamais rattrapé** (rattraper a l'air robotique). Un créneau = une clé `farm_planned.slot_key = "<account_id>:<start>"`, donc un redémarrage ne double jamais une session. Le scheduler Ghost tient un seul job actif par téléphone et tue le job au-delà de `max_duration_s` (SIGTERM puis SIGKILL). `WarmSessionAction` reçoit `minutes` du créneau ; à 0 (lancement manuel `run`), il prend `session_minutes / sessions`.

```bash
python -m gitd.farm.cli plan tiktok @sierra.cole --date 2026-09-22
# 09:47   19 min
# 13:58    2 min
# 20:31   26 min
```

## 6. Jour de repos

Un jour par semaine ISO, choisi par `sha256("rest|<account_key>|<année, semaine>")`, jamais pendant les trois premiers jours de vie (`rest_day = weekday == rest_weekday and dol > 3`). Ce jour-là : tous les caps à 0, 0 minute, 0 session, `plan` répond `no session (rest day)`, `WarmSessionAction` répond `{"skipped": "rest day", "day_of_life": …}` et `allow()` refuse tout (R17). Décision : une publication par API (§10) respecte aussi le jour de repos — le workflow de publication lit `budget_for()` avant de poster [à coder, `build-plan.md`].

## 7. Ce que fait une session (`warm.py`)

`run_session(adapter, human, ledger, cfg)` : « une personne ouvre l'application pendant N minutes ». Chaque session tire une `SessionProfile` (`human.py`) — tremblement de tap 4-9 px, tenue 70-130 ms, vitesse de frappe, 1-5 % de fautes corrigées, temps de lecture — et garde cette signature jusqu'au bout. Ordre pour chaque vidéo :

1. **Contrôle santé** sur le dump XML (`health.detect`) : un signal arrête tout (§9). Si le feed est perdu, `back_to_feed()` (4 retours arrière puis l'onglet Reels / Home) ; toujours perdu → `error = "lost the feed"`.
2. **Regarder** (`human.watch()`) : 10-28 % de vidéos zappées en 0,6-1,5 s ; 4-14 % de « lingering » 12-60 s ; le reste 1,5-20 s autour de 4-9 s. Une ligne `farm_actions` `view`.
3. **Liker** : propension de la phase × `allow(LIKE)` ; les deux skills double-tapent la vidéo 6 fois sur 10, sinon le bouton « Like » ; jamais de dé-like (« Liked » / « Unlike » présent → rien).
4. **Enregistrer** : Instagram « More options » → « Save » ; TikTok « Favorites ».
5. **Visiter le profil de l'auteur** (`open_author`), lire la bio (`pause(2.5)`), nouveau contrôle santé, **follow** seulement ici et seulement si `allow(FOLLOW)` ; retour au feed. C'est la branche « auteur du feed », inchangée ; les profils tirés du radar entrent, eux, par le détour de recherche (§8.2).
6. **Commenter** : un texte tiré au hasard du pool (`comments.pop(...)`, jamais deux fois le même dans la session), pause « réflexion » `1.5`, saisie caractère par caractère (ASCII pur, R12), contrôle santé après. Sans pool, la branche n'existe pas.
7. **Détour** toutes les `DETOUR_EVERY = (12, 30)` vidéos : `search` (Instagram : onglet Search, requête, Entrée, 1-3 défilements de 1,5-4 s ; TikTok : loupe, requête sans `#`) compte un `search` ; `stories` (Instagram seulement : Home, une story qui n'est pas « Your story », 2-6 taps de 2-6 s) compte un `story_view`. **Deux recherches sur trois visent un compte du radar** de la niche du personnage (§8.2), la troisième reste un hashtag de `niche` (`farm_accounts.niche` = `hashtags_niche` de la fiche, ex. `gymgirl,fitnessmotivation,losangeles,morningroutine` pour `sierra`) — c'est le comportement d'aujourd'hui, conservé parce qu'une session qui ne cherche que des pseudos est elle-même une signature.
8. **Poser le téléphone** : `PHONE_DOWN_RATE = 0.03` par vidéo, `PHONE_DOWN_S = (20.0, 90.0)` secondes sans rien faire.
9. **Vidéo suivante** : swipe vertical avec dérive latérale, amplitude 40-68 % de l'écran, 150-1 200 ms — jamais un `input tap` nu (`test_instagram_warm_session_runs_against_fake_device`).

Propensions par phase (`PROPENSITY`, avant le oui/non du ledger) :

| Phase | like | save | visite de profil | follow si visite | comment |
|---|---|---|---|---|---|
| `consume` | 0 | 0 | 0,02 | 0 | 0 |
| `light` | 0,09 | 0,03 | 0,05 | 0,25 | 0 |
| `network` | 0,11 | 0,04 | 0,07 | 0,35 | 0,04 |
| `cruise` | 0,12 | 0,04 | 0,08 | 0,30 | 0,05 |

**X et Reddit (skills à créer, E3.1)** — le `PlatformAdapter` de `warm.py` est écrit pour un feed vidéo ; sur ces deux apps, l'unité de `VIEW` est une **carte de post** du fil `For you` (X) / `Home` (Reddit), `watch()` inchangé ; `like` = cœur (X) / upvote (Reddit, sous le cap `likes`, jamais hors chauffe : manipulation de votes) ; `save` = signet (X) / « Save » (Reddit) ; `open_author` = profil de l'auteur (X) / profil de l'auteur, jamais le sub (Reddit) ; `follow` = Follow (X) / « Join » du sub du post (Reddit), sous le cap `follows` et seulement dans la branche `open_author` (R16) ; `comment` = pool ASCII, jamais sur X avant `network` ; détours : `search` uniquement (`#<niche>` sur X, `r/<niche>` puis onglet `Hot` sur Reddit), pas de `stories` ; santé : motifs `_PATTERNS["x"]` / `["reddit"]` d'E3.1.

**Ce qui met fin à une session** : le temps écoulé (`deadline`) ; un signal santé (`stats.health`, `success = False`, `error = "health signal: …"`) ; `feed not reachable` à l'ouverture ; `lost the feed` ; une exception (`stats.error`, la session rend quand même ses compteurs) ; le timeout du scheduler ; un `POST /api/scheduler/queue/<qid>/kill` humain. Chaque session finit par une ligne `Data:` reprise dans l'onglet Scheduler de Ghost :

```json
{"videos": 118, "likes": 9, "saves": 2, "visits": 6, "follows": 2, "comments": 1, "detours": 4,
 "seconds": 1462.3, "health": null, "error": null,
 "handle": "sierra.cole", "day_of_life": 20, "phase": "cruise", "profile_seed": 733120544}
```

## 7 bis. La chauffe orientée : apprendre la niche à l'algorithme (décision du 2026-09-22)

Une session qui ne fait que défiler le fil prouve qu'on est humain ; elle n'apprend rien à Instagram sur **ce qu'on veut voir**. Or c'est ce que l'algorithme utilisera pour pousser nos propres Reels vers leur audience. La chauffe est donc *orientée* : consommer, dès le jour 1, exactement le contenu de la niche du personnage, et le mesurer.

**Proportion.** ≈ 80 % du temps d'une session dans des Reels de la niche, ≈ 20 % dans le fil et les stories (la boucle du §7, inchangée). Dans le code : tous les `ORIENTED_EVERY = (3, 6)` posts du fil, un tour orienté (`warm.py`).

**Un tour orienté** = une *porte d'entrée* sur un compte de la niche, puis « se perdre » : 5-10 Reels de ce compte, 5-20 s chacun, ~12 % de likes ; puis, une fois sur deux, sa liste « suivis » → un des huit premiers comptes → ses Reels (profondeur 2, `_lose_time_in_a_followed_account`) ; le compte découvert entre dans `farm_targets` (source `following`). Le viewer se quitte par Back, jamais en glissant vers le flux Reels général. **Prouvé sur l'explorateur le 2026-09-22** : Instagram (`@gymshark` → page de résultats → profil → onglet Reels → Reels → suivis → `@allismeltzer` → ses Reels) et TikTok (`@gymshark` → résultats, onglet Users → profil → vidéos). Deux pièges du relevé : un Reel qui joue ne se laisse pas lire par `uiautomator` (un tap le met en pause, sinon on regarde à l'aveugle) ; TikTok entoure les pseudos de marques bidi invisibles (`\u2068gymshark\u2069`).

**Les portes, par phase.**
- *Jours 1-7* : uniquement des comptes **connus** de la niche (liste radar, entrées `@pseudo` de `farm_accounts.niche`), par la **recherche** : 2-3 par session, jamais deux fois le même dans la session ni deux fois de suite dans la journée. Onglet Reels et Explore : jamais — tant que l'algorithme ne connaît pas la niche, ce sont du bruit qui dilue le signal.
- *Jours 8-14* (à coder) : l'onglet Reels et le Reel cliqué dans le fil s'ajoutent, mais on ne s'attarde que si le Reel est de la niche — auteur dans le radar (élargi aux comptes découverts), ou mots / hashtags de la niche dans la légende, lus dans l'arbre d'accessibilité ; sinon on passe. Les comptes connus restent la majorité.
- *Jour 15+* (à coder) : le flux Reels et Explore deviennent la source principale si le score Explore le permet ; sinon on reste en régime « comptes connus ». Un rappel de comptes connus chaque jour.
- La porte de chaque session est tirée au sort parmi celles autorisées ; jamais le même enchaînement deux sessions de suite.

**D'où viennent les comptes** (depuis le 2026-09-22). Deux sources, dans cet ordre :

1. **Le radar d'OFMAI.** `GET /api/farm/targets?character=<slug ou id>&platform=instagram&limit=30` (`bridge-ofmai-farm.md` §3.7) rend les 30 meilleurs comptes actifs de la niche du personnage (`niche.radar` de la fiche), marché du personnage d'abord, puis score de performance du radar, puis abonnés — pseudos nus, sans `@`. Le pont (`bridge.fetch_targets`) les écrit dans la table `farm_targets` de la ferme (`account_id`, `handle`, `platform`, `source`, `first_seen`, `last_seen`, `last_played`, `plays` ; unique par compte et pseudo) en `source = radar`. Le tick redemande quand il reste moins de 5 portes jouables et que la liste date de plus de 24 h ; une session dont la table est vide demande elle-même une fois.
2. **Les comptes découverts** : ceux que le bloc « suivis » (à coder) croise pendant un tour entrent par `ledger.record_discovered` en `source = following`.

Au départ de chaque session, `skillkit.session_niche` tire 2-3 portes par `ledger.pick_targets(db, account, n, cooldown_days=14)` — jamais un pseudo joué depuis moins de **14 jours**, radar avant `following` avant les pseudos tapés à la main, dans un ordre mélangé avec la graine `(compte, jour)` du budget (§4) — et les place en tête de la liste `niche` sous la forme `@pseudo`, devant ce que `farm_accounts.niche` contient. La boucle de `warm.py` ne change pas : elle ne voit qu'une liste de `@pseudos` et de `#hashtags`. En fin de session, chaque porte ouverte (`SessionStats.played`) passe par `ledger.mark_played` : `last_played` daté, `plays` incrémenté, et le pseudo sort du tirage jusqu'à la fin du refroidissement — donc jamais deux fois la même porte dans la journée, ni le même enchaînement deux sessions de suite. Elle part aussi dans `session_summary` sous `targets_used`.

Repli : sans pont configuré, ou si OFMAI ne répond pas, ou si le radar n'a rien sur cette plateforme (TikTok aujourd'hui), les `@pseudos` donnés à la main dans `accounts add --niche` (`@gymshark,@…,#gymgirl`) restent les portes, exactement comme avant ; un pseudo manuel joué entre lui aussi dans `farm_targets` (`source = manual`) et subit le même refroidissement. Les `#` gardent le détour de recherche classique.

**Mesure** (depuis le 2026-09-22, `gitd/farm/explore_score.py`) : en fin de session Instagram, après le relevé de karma et sous la même règle R27 (rien après un signal de santé), `WarmSessionAction` ouvre l'onglet « Search and explore », attend le chargement de la grille, garde la capture sous `data/explore/<plateforme>/<pseudo>/<AAAAMMJJ-HHMMSS>.png`, puis demande à un modèle (vision, `claude-opus-5`, l'image en base64 + la niche décrite depuis `farm_accounts.niche` et l'identifiant du personnage) la part de la page qui est du contenu de la niche : un entier 0-100 et une phrase, en JSON, lus strictement (`parse_score`). Le score part dans `session_summary` sous `explore_niche_score` (entier, ou `null` si le modèle n'a pas répondu lisiblement) avec `explore_shot` (chemin de la capture) ; puis retour au fil par l'onglet Home et `back_to_feed`. Sans `ANTHROPIC_API_KEY` (ou `FARM_ADVISOR=1` avec un profil `ant auth login`), rien ne se passe : ni capture, ni clé dans l'événement — même porte que l'advisor du §4 bis des sélecteurs. Aucune erreur de cette mesure ne fait échouer la session. Validation à l'œil au début (les captures sont là pour ça). Passage au régime jour 15+ : score ≥ 60 sur 3 sessions de suite. TikTok n'est pas mesuré : son écran de recherche est une liste de suggestions, pas une grille personnalisée.

**TikTok** : même schéma — recherche et profils d'abord, « Pour toi » ensuite. Reddit : pas de Reels ; rejoindre les subs de la niche et y voter/commenter joue ce rôle.

## 8. Ce que la plateforme sert à une session : commentaires et cibles du radar

### 8.1 Pools de commentaires par persona

Le code attend `params.comments` (ASCII, un par ligne, `WarmSessionAction`), mais `planner.job_config` ne passe que `handle`, `minutes`, `niche` : **aujourd'hui aucune session ne commente**. Le pool vit côté OFMAI (`SocialCommentPool` : `characterId`, `platform`, `text`, `reservedUntil`, `usedAt`, `usedByHandle`), est servi par `GET /api/farm/comments?character_id=…&platform=…&n=10` et remonte dans `session_summary.comments_used` (`bridge-ofmai-farm.md` §3.4, §4.1).

Règles d'un commentaire :

- ASCII pur, 2 à 8 mots, minuscules acceptées, pas d'emoji (`type_text` les supprime), pas de lien, pas de `@`, pas de `#`, pas de prix ni de « free ».
- Réagit au **visuel** (lumière, lieu, tenue, geste), jamais au corps de l'autre, jamais une question sur « real » ; aucune mention d'OFMAI ni d'IA sur le contenu des autres (un commentaire promotionnel est du spam, R22) ; aucun nom de fournisseur, jamais « same face » (R10, R11).
- Écrit dans la voix de la fiche persona (`personas.md`) par l'agent du workflow quotidien, passé par l'étage 1 de conformité (`content-pipeline.md` §8), puis inséré dans `SocialCommentPool`.
- Stock : ≥ 60 textes disponibles par personnage et par plateforme ; réapprovisionné dès que le stock passe sous 20 ; un texte n'est jamais réutilisé sur le même compte à moins de 30 jours (`usedAt`) ; réservation 24 h à la livraison, rendue si non consommée.
- Consommation réelle : `comments` 3/jour en network, 8/jour en cruise avant tirage (§2), propension 0,04-0,05 par vidéo : une session de 25 min en pose 0 à 2.

Exemple pour Sierra (fitness : upbeat, précise, encourageante, jamais moralisatrice ; niche `gymgirl,fitnessmotivation,losangeles,morningroutine`) — les quatre premières lignes sont l'amorce `comment_pools.instagram` de sa fiche (`personas.md` §2) :

```text
that form though
ok the lighting in this gym
need this playlist asap
saved for tomorrow's session
the 6am club is real
this warmup looks brutal
adding this to leg day
that gym is spotless
the tempo on those reps
rest day earned after this
```

### 8.2 Comptes à suivre et profils à visiter : le radar, par niche

**Décision (2026-09-15)** : pendant la chauffe, les comptes qu'un personnage suit et les profils qu'il visite ne sont plus ce que le hasard d'un hashtag lui met sous la main — ils sont **tirés du radar d'OFMAI, pour la niche du personnage**.

Aujourd'hui, la session cherche `#<niche>` et suit ce qui tombe (§7, étapes 5 et 7) : le voisinage d'un compte neuf est alors le produit d'une page de hashtag, où se mélangent spam, comptes morts et gros comptes hors sujet. Or la plateforme possède déjà **≈ 2 900 comptes d'influenceuses classés par niche** (`TrackedInfluencer`, champ `niche`, avec les six libellés exacts des personnages : 160 comptes en `fitness`, 191 en `latina`, 147 en `asiatique`, 211 en `bimbo`, 157 en `e-girl`, 107 en `gothique` — `personas.md` §3.1). C'est plus crédible qu'un hashtag, et ça place le personnage dans le bon voisinage dès le premier jour, ce qui aide l'algorithme à le catégoriser.

| | Règle |
|---|---|
| Source | `TrackedInfluencer` où `niche` = `niche.radar` de la fiche persona (`personas.md` §1), `market = "US"`, `status = "active"`, `enabled = true` |
| Qui sert | OFMAI, `GET /api/farm/targets?character=…&platform=…&limit=30` (`bridge-ofmai-farm.md` §3.7, en place depuis le 2026-09-22) ; le pont les écrit dans `farm_targets` et `skillkit.session_niche` les place en tête de la liste `niche` de chaque session (§7 bis, « D'où viennent les comptes ») |
| Où ça entre dans la session | le **détour de recherche** (§7, étape 7) : deux recherches sur trois tapent le pseudo d'une cible au lieu d'un hashtag, ouvrent son profil, lisent la bio, font défiler la grille. Cela consomme un `search` et un `profile_visit` ; le **follow** n'a lieu que si `allow(FOLLOW)` passe, ratio ≤ 30 % des visites tenu comme partout (§3) |
| Ce qui ne change pas | la branche « auteur du feed » (§7, étape 5) : le reste du budget `profile_visit` et `follow` continue d'y passer. Au bout de quelques jours, le feed lui-même est devenu celui de la niche |
| Volume | plafond `searches` 2 / 3 / 4 / 5 par phase, donc **5 cibles par jour au plus** : une niche de 107 à 211 comptes couvre le mois de chauffe entier, ce qui est exactement ce qu'on lui demande |
| À égalité | `accountType = "reelle"` d'abord — l'inverse de la sélection de **contenu**, qui préfère `"ia"` (`content-pipeline.md` §4.1) : on reproduit une scène plus facilement depuis un compte IA, mais on ne se construit pas un voisinage fait de clones |
| Jamais deux fois | la mémoire est côté ferme, pas côté OFMAI : `farm_targets.last_played` (`bridge-ofmai-farm.md` §5.2), `ledger.pick_targets` ne rend jamais un pseudo joué depuis moins de 14 jours (§7 bis). Pas de réservation : OFMAI ne fait que classer |
| Consommation | remontée dans le résumé de session : `targets_used: [handle…]`, à côté de `comments_used` (`bridge-ofmai-farm.md` §4.1) |
| Pool épuisé | la route rend une liste vide et le détour retombe sur le hashtag de niche : le comportement d'aujourd'hui est le repli, jamais une erreur |

Limites, assumées et à surveiller :

- **Le radar n'indexe qu'Instagram** (`TrackedInfluencer.platform`, défaut `instagram`). Sur **TikTok** et **X**, la cible est servie comme une *requête de recherche* (le pseudo) : si l'application ne rend rien, la session retombe sur le hashtag [à vérifier sur les 20 premières cibles : taux de recouvrement des pseudos entre Instagram, TikTok et X]. Sur **Reddit**, la route rend toujours une liste vide — il n'y a pas d'influenceuse à suivre, le détour `r/<niche>` puis l'onglet `Hot` reste la règle (§7, paragraphe X et Reddit).
- Suivre une cible ne veut pas dire la commenter : les commentaires restent tirés du pool (§8.1) et ne mentionnent jamais OFMAI ni l'IA sur le contenu d'un autre (R22).
- On ne suit **jamais en masse** : la cible ne change rien aux caps ni aux ratios, et le premier « action blocked » arrête tout (R16, incident @potter_society).
- Le radar est une liste de comptes, pas de personnes à imiter : R1 tient — un compte du radar donne un voisinage, un post du radar donne une scène, jamais un visage.

## 9. Santé : machine d'états et effets sur la phase

`health.detect(platform, xml)` cherche des motifs en-US dans le dump XML après chaque étape (`_PATTERNS`, Instagram et TikTok) et rend le plus grave présent : `suspended` > `logged_out` > `verification` > `action_blocked`. `FarmSession.signal()` écrit `farm_signals` puis `policy.apply_signal()` :

| Statut (`policy.Health`) | Signal | Durée | `phase_override` | Reprise |
|---|---|---|---|---|
| `ok` | — | — | aucun (ou celui hérité) | — |
| `cooldown` | `action_blocked` : « action blocked », « try again later », « we limit how often », « tapping too fast », « too many attempts »… | `COOLDOWN_HOURS = 48` | la phase **précédant** la phase naturelle (cruise → network, network → light, light → consume) | automatique à l'échéance ; l'override reste |
| `verification_required` | `verification` : « confirm it's you », « suspicious login », « verify to continue », « drag the slider », « enter the confirmation code »… | illimitée | inchangé | un humain agit sur l'appareil (checkpoint, R25), puis `clear-health` |
| `shadowban_suspect` | `shadowban` : émis par l'analytique, jamais par l'écran ; `zero_reach(view_counts)` = les 3 derniers posts à ≤ 2 vues, **appelé nulle part aujourd'hui** (`health-canaries.md`) | `SHADOWBAN_DAYS = 7` | `consume` (regarder seulement, aucun post) | automatique ; l'override reste |
| `logged_out` | `logged_out` : « log in », « create new account », « sign up for tiktok » | illimitée | inchangé | un humain (« never auto-login »), puis `clear-health` |
| `suspended` | `suspended` : « your account has been suspended », « we banned your account », « community guidelines violation »… | `QUARANTINE_DAYS = 30` | aucun | jamais (`can_run` = False) ; appareil et IP en quarantaine 30 jours (R18) |

Effets :

- Le signal **arrête la session** (R27) et `planner.tick` ne planifie plus rien tant que `HealthState.can_run(now)` est faux ; `open_session()` lève `PermissionError("@… is cooldown until …")` ou `"… — a human must act on the device"`, y compris pour un `run` manuel.
- `effective_phase = min(phase naturelle, phase_override)` ; `ledger.budget_for()` reconstruit le budget avec les **caps de la phase forcée**, même seed, vrai `day_of_life` (`test_signal_puts_account_in_cooldown_and_blocks_next_session`).
- `cooldown` et `shadowban_suspect` expirés → `health = ok` à la session suivante, mais `phase_override` reste jusqu'à `accounts clear-health` (geste humain, R26). Un compte sorti de cooldown rechauffe donc une phase en dessous tant que personne n'a regardé l'écran.
- Deux comptes rouges en 48 h sur une plateforme → pause de la plateforme ; trois `suspended` en 48 h → plateforme coupée : règles collectives **hors code** (`health-canaries.md`, R29, R30).

```bash
python -m gitd.farm.cli accounts list                                # day, phase, health=…, [disabled], [api]
python -m gitd.farm.cli accounts clear-health instagram @sierra.cole   # ok, health_until NULL, phase_override NULL
python -m gitd.farm.cli accounts disable tiktok @sierra.cole           # pause manuelle
```

## 10. Passage en `api_mode`

Deux notions à ne pas confondre : `channel` (`bridge-ofmai-farm.md` §3.2) dit par où part **une publication** (`device` = workflow `post_video`, `api`) ; `api_mode` (`farm_accounts.api_mode`) dit le **régime de sessions** du compte. La source de vérité d'`api_mode` est OFMAI : `PATCH /api/admin/social/accounts/{id} {"apiMode": true}` (E7.2), recopié dans `farm_accounts.api_mode` par le pont à chaque tick (`bridge-ofmai-farm.md` §6, étape 1) ; la commande CLI `accounts api-mode <plateforme> <handle> on|off` ne sert qu'en mode dégradé, pont arrêté, ou sur un appareil de test, et est écrasée au tick suivant.

| Plateforme | Chauffe sur l'appareil | Premiers posts (`network`, 3 / semaine) | Posts en `cruise` | `api_mode` |
|---|---|---|---|---|
| Instagram | oui, toute la vie du compte | `post_video` (Reel depuis la galerie) | `post_video`, 1 / jour, 7 / semaine (+ 1 story, E3.4) | **jamais** (API Graph exclue) |
| TikTok | oui | `post_video` ; toggle « AI-generated content » posé et confirmé seulement si `params.aigc_label` est vrai (personnage `declared`), jamais touché pour un `undeclared` (R2, R3) | API Content Posting via le MCP Higgsfield (`tiktok_connect`, `tiktok_prepare_publish`, `tiktok_publish`, 13 posts / jour côté API, notre cap §11) | `PATCH … {"apiMode": true}` au passage en cruise, après la checklist §13 |
| X | oui (skill à créer) | API officielle depuis le Mac mini, par l'IP statique du personnage (R21) | idem, cap §11 | idem au passage en cruise |
| Reddit | oui (skill à créer) | `post_video` jamais ; publication API seulement à `day_of_life ≥ 31` **et** karma ≥ 100 (relevé par `metrics_pull` / écran profil), condition posée dans `publish-api.ts` et dans `GET /api/farm/queue` (aucune publication Reddit servie avant) — le cap `posts_per_week` du ledger ne suffit pas ; zéro lien dans le post (R22) | idem, cap §11 | idem au passage en cruise |

Ce qui change **aujourd'hui dans le code** quand `api_mode = 1` : `planner.tick` saute le compte (`if acc.api_mode: continue`) — plus aucune session ; `accounts list` affiche `[api]` ; `post_video` n'est plus enfilé ; la publication par API est décrite dans `publishing.md`. Aucune publication par API n'existe encore, ni le routage par l'IP statique.

Ce que la décision du brief exige (« l'appareil ne fait plus que de la consommation légère ») et que le code doit apprendre (`build-plan.md`) : en `api_mode`, le planner continue à planifier des sessions avec les caps ci-dessous, et la publication API appelle `open_session().allow(POST)` / `record(POST)` comme le fait `PostReelAction`, pour que le quota reste dans le ledger (R13).

| Régime | likes | saves | follows | comments | posts appareil | story_views | profile_visits | searches | minutes / jour | sessions / jour |
|---|---|---|---|---|---|---|---|---|---|---|
| `api_mode` (cible) | 25 | 6 | 0 | 0 | 0 | 30 | 8 | 3 | 20-50 | 2-3 |

Soit les caps `light` sans follow ni commentaire ; `COMMENT_REPLY` et `DM_REPLY` (20) restent sur l'appareil pour répondre sous ses propres posts quand les workflows existeront.

## 11. Arbitrage : 1 post / jour sur l'appareil contre 6 assets / jour / personnage

`policy.py` plafonne l'appareil à `POST = 1` / jour et `posts_per_week` 3 (network) / 7 (cruise) ; le brief vise 6 assets / jour / personnage et le plan ×10 « 2-4 posts / jour / compte ». Les trois sont compatibles parce qu'un asset n'est pas un post (un master gardé est re-rendu en plusieurs variantes qui servent plusieurs plateformes, `content-pipeline.md` §6 et §9 : **8 variantes prêtes par jour** depuis 3 masters gardés) et parce que le volume passe par l'API, jamais par l'appareil :

| Compte | Canal en cruise | Cap / jour (décision) | Cap / semaine |
|---|---|---|---|
| Instagram | appareil | 1 (`POST`, inchangé) | 7 (`posts_per_week`) |
| TikTok | API | 2 | 14 |
| X | API | 3, puis 2 si < 500 impressions / post après 100 posts, 1 à J7 (`metrics-attribution.md` §7) | 21 |
| Reddit | API | 2, sur deux subs différents | 14 |

Total par personnage en cruise : jusqu'à 8 posts / jour (+ 1 story Instagram sur l'appareil, E3.4), soit **8 variantes tirées de 3 masters gardés** (1 vidéo + 2 images, ≈ 4 réplications ; la story reprend une variante image) ; les « 6 assets / jour / personnage » du brief sont un **plafond de production**, pas une cible (`content-pipeline.md` §9). Le cap API se tient dans le ledger via une table par **plateforme** dans `policy.py` — `API_POSTS_PER_DAY = {"tiktok": 2, "x": 3, "reddit": 2}`, 0 hors cruise, posée par `DailyBudget.build` dans `caps[API_POST]` (un cap par phase dans `PhaseCaps` ne peut pas porter des valeurs par plateforme) — et une action `API_POST` distincte de `POST` [à coder, E8.3]. Règles communes aux deux canaux : jamais en heures calmes, jamais le jour de repos, au moins 3 h entre deux posts d'un même compte (appliqué par `POST /api/admin/social/queue`, E6.6), et 3 ou 4 posts / jour seulement après que les seuils J7 tiennent — **jamais sur l'appareil**, dont les chiffres ne bougent pas (R14).

## 12. Exemples de journée par phase

Chiffres illustratifs, tirés dans les plages du code ; les vrais dépendent du seed `(compte, date)`.

**Instagram, jour 2 (`consume`)** — budget : 2 sessions, 27 min ; `story_view` 20 → 13, `profile_visit` 4 → 2, `search` 2 → 1, tout le reste 0. `plan` : `09:47 19 min`, `20:12 8 min`. La session du matin regarde ≈ 110 reels, fait un détour stories (4 taps) et une recherche `#gymgirl`, pose le téléphone deux fois ; zéro like, zéro follow. `Data:` `{"videos": 112, "likes": 0, "saves": 0, "visits": 1, "follows": 0, "comments": 0, "detours": 2, …}`.

**Instagram, jour 6 (`light`)** — `likes` 25 → 17, `saves` 6 → 3, `follows` 3 → 2, `story_view` 30 → 19, `profile_visit` 8 → 5, `search` 3 → 2 ; 3 sessions, 41 min : `08:31 2 min` (coup d'œil), `13:05 24 min`, `21:40 15 min`. Sur 150 vues, 9-14 likes (ratio 15 % jamais dépassé), 1 follow après la 4e visite de profil, aucun commentaire (propension 0).

**TikTok, jour 16 (`network`)** — `likes` 50 → 33, `saves` 10 → 6, `follows` 12 → 7, `comments` 3 → 2, `post` 1 (si moins de 3 cette semaine), `profile_visit` 20 → 13, `search` 4 → 3 ; 3 sessions, 50 min. Un `post_video` à 12:40 (légende ASCII, toggle AIGC selon `params.aigc_label` de l'item de file), 2 commentaires du pool posés dans l'après-midi, détours par recherche uniquement.

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
- [ ] Profil complet : bio de la fiche persona pour cette plateforme — mention « AI » pour un personnage `declared` (`disclosed: true`), **aucune** mention pour un `undeclared` ; sur Fanvue les six sont déclarés quoi qu'il arrive (`personas.md` §4) —, link-in-bio avec les UTM du personnage (`personas.md`, `metrics-attribution.md`), aucun lien hotofmai.ai sur Instagram / TikTok (R23).
- [ ] `tested_on` non vide dans `skill.yaml` du skill du compte (R34) et deux sessions consécutives sans `error` à 0 vidéo.
- [ ] Pool de commentaires ≥ 60 textes disponibles pour ce personnage et cette plateforme (§8), stock de variantes `ready` au niveau de sécurité du §9 de `content-pipeline.md` (3 × le cap de §11 : Instagram 3, TikTok 6, X 9, Reddit 6).
- [ ] TikTok seulement : OAuth (`tiktok_connect`) réalisé depuis le téléphone du personnage [à vérifier], premier post API publié avec `is_aigc` (`tiktok_prepare_publish`) = `aigc_label` de l'item de file, soit `true` pour un `declared` et `false` pour un `undeclared`, et relu à 24 h depuis l'observateur, puis `PATCH /api/admin/social/accounts/{id} {"apiMode": true}` (E7.2) — recopié dans `farm_accounts.api_mode` par le pont ; `accounts api-mode` seulement si le pont est arrêté.
- [ ] Discord reçoit les alertes (`DISCORD_WEBHOOK_URL`) et quelqu'un peut atteindre l'appareil dans l'heure (R32).

Un point non coché = le compte reste en cruise sur l'appareil, aux caps du §2 ; on ne force rien.
