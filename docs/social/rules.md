# Règles absolues — machine M1 (armée de personnages)

> **Nature** : reference
> **Statut** : en vigueur
> **À jour au** : 2026-09-14
> **Répond à** : Quelles règles ne se négocient jamais sur la ferme de personnages, pourquoi chacune existe, et ce qui se passe quand elle est violée.
> **Code concerné** : `.claude/rules/product.md`, `lib/core/host.ts`, `lib/generation/content-classification.ts`, `app/api/generate-image/route.ts`, `app/api/generate-easy/route.ts`, `app/api/generate-sfw-image/route.ts`, `app/api/attribution/route.ts`, `lib/kyc/rekognition.ts`, `lib/core/discord-alerts.ts` — fork ofmai-farm : `gitd/farm/policy.py`, `gitd/farm/ledger.py`, `gitd/farm/health.py`, `gitd/farm/warm.py`, `gitd/farm/planner.py`, `gitd/farm/cli.py`, `gitd/farm/human.py`, `gitd/skills/ofmai_instagram/workflows/__init__.py`, `gitd/skills/ofmai_tiktok/workflows/__init__.py`, `gitd/skills/checkpoint.py`, `gitd/routers/skills.py`, `gitd/routers/scheduler.py`

Une règle = une ligne : l'énoncé, **pourquoi**, **si violée**. Les chiffres sont ceux du code au 2026-09-14 ; quand une règle n'est pas encore appliquée par du code, la ligne le dit et renvoie à `build-plan.md`. Le détail d'exploitation vit dans les autres fichiers du dossier (`warming-policy.md`, `publishing.md`, `health-canaries.md`, …) : ici on ne l'explique pas, on le fixe.

Sources des décisions : brief M1 du 2026-09-14 (§12 « règles absolues »), `documentation/business/growth/machine-x10-2026-09.md` (§ Règles), `documentation/business/growth/plan-21-jours-x10-abonnes-2026-09.md` (§4 social, DM IG, agences), `.claude/rules/product.md`.

## 1. Personnages et consentement

- **R1 — Aucun clone d'une vraie personne sans ses photos uploadées par elle-même et une identité vérifiée.** Pourquoi : un visage réel sans consentement est un deepfake ; le parcours existant l'impose déjà pour `AICharacter.characterOrigin = "real_person"` (`prisma/schema.prisma`) : identité + liveness + questionnaire de consentement, puis face-match Rekognition ≥ `FACE_MATCH_THRESHOLD = 90` (`lib/kyc/rekognition.ts`), décrit dans `documentation/characters/nsfw-kyc-compliance.md`. « Jamais de clone depuis des photos publiques sans autorisation signée » (plan 21 jours, § agences). Si violée : personnage supprimé, médias purgés de S3, comptes qui les ont publiés passés en `accounts disable` définitif, post-mortem daté dans `docs/social/decisions/`.

- **R2 — Les six personnages M1 sont synthétiques (`characterOrigin = "ai_native"`) ; le radar (`TrackedInfluencer`, `ScrapedPost`) sert à choisir niches, hashtags et hooks, jamais comme image de référence.** Pourquoi : l'identité est tenue par le Soul / LoRA du personnage, pas par une ressemblance empruntée ; une « inspiration » à partir d'une créatrice réelle est un R1 déguisé. Si violée : l'asset est rejeté par la QA identité (`content-pipeline.md`) et le lot entier est jeté.

## 2. Divulgation IA

- **R3 — Chaque compte dit qu'il est une IA, dans la forme exigée par sa plateforme, avant son premier post.** TikTok : toggle « AI-generated content » à chaque publication (élément `aigc_toggle` de `gitd/skills/ofmai_tiktok/elements.yaml`, tapé par `PostVideoAction` via `_tap_text(xml, "AI-generated content")` sans vérification du résultat, `tested_on: []`) et paramètre AIGC de l'API Content Posting en `api_mode` [à vérifier : nom exact du paramètre dans `tiktok_prepare_publish`]. Instagram et X : mention « AI » dans la bio, `#AI` dans les légendes [à vérifier : disponibilité du label IA natif d'Instagram depuis l'app]. Fanvue : badge « AI creator » [à vérifier]. Reddit : seulement dans des subs qui acceptent l'IA, flair « AI » quand il existe. Pourquoi : TikTok retire l'AIGC non étiqueté et sanctionne le compte ; la persona ne se cache pas — le comment-to-DM répond justement « 100 % IA, faite sur OFMAI ». Si violée : post supprimé par nous dans l'heure, compte mis en pause 48 h (`accounts disable`), aucune reprise tant que le mécanisme de label n'est pas confirmé sur l'appareil (live stream Ghost).

- **R4 — Un post TikTok publié sans confirmation du toggle ne compte pas comme publié.** Pourquoi : aujourd'hui `PostVideoAction` enchaîne `_tap_text("AI-generated content")` puis `Post` sans relire l'écran ; c'est un pari. Si violée (le pari perdu) : R3. Correction attendue : le toggle devient une précondition de `Post` (`build-plan.md`), et jusque-là un humain regarde chaque post TikTok sur appareil.

## 3. SFW / NSFW par host et par plateforme

- **R5 — Instagram, TikTok, Meta et le compte de marque associé : SFW seulement, contenu produit sur ofmai.ai avec le Soul, liens vers ofmai.ai. X et Reddit : 18+, LoRA NSFW, liens vers hotofmai.ai / Fanvue.** Pourquoi : la séparation est déjà dans le code — `isSFWHost()` (`lib/core/host.ts`, hosts listés par `NEXT_PUBLIC_SFW_HOSTS`, `ofmai.ai` en prod d'après le commentaire du fichier [à vérifier en prod]), `isModelAllowedOnSFWHost(model)` = `classifyContent(model) === "sfw"` avec **modèle inconnu → nsfw** (`lib/generation/content-classification.ts`), 403 dans `app/api/generate-image/route.ts` (l. 35) et `app/api/generate-easy/route.ts` (l. 68-73) sur host SFW ; `app/api/generate-sfw-image/route.ts` refuse un prompt explicite (`isExplicitNsfw`, incrémente `User.sfwFilterBlocks`) et passe `checkPromptPolicy`. Si violée : sur IG/TikTok c'est la voie directe vers la suspension ; sur ofmai.ai c'est le compte PSP. Conséquence : post supprimé dans l'heure, comptes SFW du personnage en pause 48 h, lot bloqué par la porte de conformité.

- **R6 — Un asset `nsfw` ne va jamais vers un compte `instagram` ou `tiktok`.** La vérité est `Generation.contentType` (`classifyContent(model)` à la création) ; la banque `ContentAsset` porte `contentType` et `platform`, et le pont refuse la combinaison (`bridge-ofmai-farm.md`, à construire). Si violée : R5.

- **R7 — Un prompt de génération pour un compte SFW passe `checkPromptPolicy()` (`lib/generation/content-policy.ts`, liste PSP EN + FR) et la vérification d'explicite de `generate-sfw-image`.** Pourquoi : la liste est imposée par les PSP ; on ne la contourne pas en passant par une route admin. Si violée : l'asset est détruit, pas archivé.

## 4. Comptes

- **R8 — Les comptes sont créés sur le téléphone du personnage, jamais achetés, jamais repris, jamais importés.** Pourquoi : un compte acheté porte l'historique d'un autre appareil et d'autres IP, et sa date de création ment à `phase_for_day()` : `farm_accounts.created_on` est le jour 1 de la politique (`gitd/farm/policy.py`). Si violée : le compte n'entre pas dans le ledger ; s'il y est déjà, `accounts disable`, et le profil GeeLark est recréé de zéro (`infrastructure-geelark-proxies.md`).

- **R9 — Un téléphone = un personnage = tous ses comptes = une identité réseau ; un seul compte par plateforme par appareil.** Le code le garantit : `ledger.add_account()` lève `ValueError("device … already carries … account (one per device)")` (test `test_one_account_per_platform_per_device` dans `tests/test_farm_ledger.py`). Pourquoi : deux comptes d'une même plateforme sur un appareil se lient l'un l'autre à la première suspension. Si violée par contournement (SQL direct, deuxième profil) : les deux comptes sont considérés brûlés.

- **R10 — Les identifiants (email, mot de passe, codes de secours) ne sont jamais dans le repo, ni dans `farm_accounts.notes`, ni dans un `config_json` de job.** Pourquoi : la base de Ghost est une SQLite non chiffrée et son REST sur le port 5055 n'a **aucune authentification** (`docs/API_REFERENCE.md`, § Authentication : « No authentication is required »). Où ils vivent : `account-creation.md`. Si violée : mot de passe changé sur l'appareil, ligne purgée, commit réécrit si le repo est touché.

## 5. Texte publié

- **R11 — Aucun nom de fournisseur tiers dans un texte publié : bio, légende, commentaire, DM, page publique, alt-text, réponse.** Higgsfield, Seedance, SeedDream, WaveSpeed, Modal, Krea, Lustify, WAN, Grok, GeeLark, IPRoyal, ManyChat, Rekognition, Didit, Hive, x.ai n'existent pas pour le public. La liste exécutable est la constante `PROVIDER_NAMES` de `lib/social/compliance.ts` (à créer, `content-pipeline.md` §8) : une seule source, ce paragraphe ne fait que la citer. Règle produit (`.claude/rules/product.md`) étendue au social ; les libellés autorisés sont ceux de `userFacingModelLabel()` (`lib/generation/content-classification.ts`) : « Ultra », « HOT SFW », « Photo », « Character ». Si violée : légende réécrite par la porte de conformité avant publication (`content-pipeline.md`) ; déjà publiée → éditée ou supprimée dans l'heure.

- **R12 — Jamais « même visage », « face swap », « deepfake », « visage de … » : on dit « clone », « même morphologie », « même look et même corps ».** Pourquoi : ce n'est pas la technologie, et ça sonne comme une fraude ; 47 occurrences corrigées dans `lib/seo/hot-landing-data.ts` en juillet 2026. Si violée : même porte que R11.

- **R13 — Tout texte tapé sur l'appareil est ASCII pur.** `HumanInput.type_text()` (`gitd/farm/human.py`) saute silencieusement tout caractère `ord(ch) > 127` : accents et emojis disparaissent (« j'adore ta vidéo 🔥 » devient « j'adore ta vido »). Pourquoi : `adb shell input text`. Si violée : le commentaire tronqué se lit comme un bot. Conséquence : les pools de commentaires et légendes destinés à l'appareil sont validés ASCII à la construction ; l'Unicode n'est permis que sur les légendes publiées par API (`publishing.md`).

## 6. Quotas et rythme

- **R14 — Les quotas vivent dans le ledger, jamais dans un prompt, un paramètre de workflow ou une constante de skill.** Les caps sont dans `CAPS` (`gitd/farm/policy.py`), le tirage 40-100 % dans `DailyBudget.build()`, le oui/non dans `BudgetTracker.allow()`, la trace dans `farm_actions` via `FarmSession.record()` (`gitd/farm/ledger.py`). Chaque action comptée de `run_session()` (`gitd/farm/warm.py`) appelle `ledger.allow()` avant d'agir ; `PostReelAction` et `PostVideoAction` appellent `session.allow(policy.POST)`. Pourquoi : un prompt s'oublie, une ligne de ledger non. Si violée : PR refusée ; les tests de référence sont `test_daily_cap_is_hard`, `test_like_ratio_never_exceeds_15_percent_of_views`, `test_follow_ratio_needs_profile_visits` (`tests/test_farm_policy.py`) et `test_cruise_phase_stays_within_caps_and_ratios` (`tests/test_farm_warm.py`).

- **R15 — Ratios et plafonds du code : likes ≤ 15 % des vues (`MAX_LIKE_PER_VIEW = 0.15`), follows ≤ 30 % des visites de profil (`MAX_FOLLOW_PER_PROFILE_VISIT = 0.30`), un post par jour sur l'appareil (`POST: 1`), posts par semaine ≤ `posts_per_week` (0 / 0 / 3 / 7 par phase).** Pourquoi : ce sont les proportions d'un humain qui scrolle. Conséquence : tant que `policy.py` n'est pas modifié, les 6 assets/jour visés en cruise passent par l'API (`api_mode`), pas par l'appareil — arbitrage documenté dans `warming-policy.md` et `publishing.md`, pas ici.

- **R16 — Heures calmes : `QUIET_HOURS = range(1, 7)` en heure locale du compte (`farm_accounts.timezone`, défaut `America/New_York`) — rien entre 01:00 et 06:59, ni session, ni post API, ni bascule de proxy.** `plan_sessions()` borne les départs à 07:05-23:40 et rejette tout slot qui tombe dans la plage. Pourquoi : une Américaine active à 3 h du matin est le signal de bot le plus simple. Trou connu : `python -m gitd.farm.cli run` ne vérifie pas l'heure — l'opérateur le fait. Si violée : la session est arrêtée (`POST /api/scheduler/queue/{qid}/kill`) et le fuseau du compte est revérifié (R21).

- **R17 — Pas de follow en masse, sur aucune plateforme, par aucun moyen.** Incident @potter_society (X, 2026-08-19) : ≈ 90 follows automatisés en une session avec délais 25-45 s, `HTTP 429` isolés dès le 14e follow ignorés, puis `HTTP 403 / code 64` sur `friendships/create.json` — compte bloqué. Règle : un follow n'existe qu'à l'intérieur d'une session de chauffe, après une visite de profil (`warm.py` : le follow est dans la branche `open_author`), sous le cap du jour (`follows` : 0 / 3 / 12 / 15 par phase avant tirage) ; jamais par API. Le premier « try again later », « action blocked », « tapping too fast », « too many attempts » (`_PATTERNS` de `gitd/farm/health.py`) arrête tout. Si violée : `action_blocked` → `COOLDOWN` 48 h et une phase en arrière ; sur X, un action block = compte perdu pour la machine.

- **R18 — Le jour de repos hebdomadaire ne se saute pas.** `DailyBudget.build()` tire un jour par semaine ISO après le jour 3, `BudgetTracker.allow()` refuse tout ce jour-là, `WarmSessionAction.execute()` répond `{"skipped": "rest day"}`. Pourquoi : personne ne scrolle 7 jours sur 7 au même rythme. Si violée (run forcé) : le ledger refuse quand même ; un workflow qui contourne est un bug.

## 7. Réseau

- **R19 — L'IP statique d'un personnage ne change jamais, n'est jamais partagée, et se retire avec lui.** Rayon d'un `suspended`, même règle dans `health-canaries.md` S5, `infrastructure-geelark-proxies.md` §3 et `account-creation.md` §9 : **1ᵉʳ `suspended` sur un téléphone** → la plateforme est abandonnée sur ce téléphone (`accounts disable`, `pm clear <package>`, `SocialAccount.status = banned`, 30 j sans nouvelle inscription sur cette plateforme), les autres comptes du personnage continuent avec un canari quotidien pendant 7 j ; **2ᵉ `suspended` sur le même téléphone dans les 30 j, toute plateforme** → téléphone et IP en quarantaine `QUARANTINE_DAYS = 30` (`gitd/farm/policy.py`), tous les comptes `disable`, puis profil supprimé et IP rendue, jamais réaffectée à un autre personnage ; le personnage repart sur un nouveau profil et de nouveaux comptes. Pourquoi : la plateforme connaît le « domicile » du compte ; en changer = nouvelle empreinte + nouvelle IP = `verification` immédiate et liaison entre les deux identités. Si violée : attendre le signal `verification`, compte en `VERIFICATION`, humain obligatoire (R27). Aucun code du fork ne parle de proxy (grep `proxy|geelark|iproyal` dans `gitd/farm/` : rien) — la configuration vit dans GeeLark (`infrastructure-geelark-proxies.md`).

- **R20 — Le proxy mobile (session collante) ne s'active jamais au milieu d'une action : seulement entre deux sessions, dans le creux ≥ 45 min que `plan_sessions()` garantit.** Pourquoi : une IP qui change pendant un scroll ou un upload est le motif « suspicious login ». Si violée : R19.

- **R21 — GPS, fuseau, langue et région du store sont alignés sur l'IP dans GeeLark, et `farm_accounts.timezone` est le même fuseau.** Pourquoi : R16 et `plan_sessions()` calculent en `farm_accounts.timezone` ; un décalage met les sessions la nuit pour la plateforme. Si violée : le compte ne tourne pas tant que ce n'est pas corrigé.

- **R22 — Les appels API X et Reddit sortent par l'IP statique du personnage (proxy HTTP au format accepté par `lib/ingest/instagram-proxy.ts` : `user:pass@host:port` ou `host:port:user:pass`).** Les publications TikTok en `api_mode` transitent par les serveurs du fournisseur d'API, la règle d'IP ne s'y applique pas ; la connexion OAuth (`tiktok_connect`) se fait depuis le téléphone du personnage [à vérifier]. Si violée : un compte X/Reddit vu depuis le Mac mini de Paris et depuis une IP US le même jour finit en `verification`.

## 8. Liens

- **R23 — Pas de lien dans un post, un commentaire ni un DM pendant la chauffe (phases `consume`, `light`, `network` ; cruise = jour 15 Instagram, jour 24 TikTok).** Le seul lien est le link-in-bio, posé selon `account-creation.md`. Sur Reddit : zéro lien dans un post, à tout âge du compte, arrêt au premier retrait (plan 21 jours, § Reddit). Pourquoi : lien + compte neuf = classifieur spam ; l'automod Reddit supprime les comptes neufs (`base-de-faits-2026-09-13.md`). Si violée : post retiré → traité comme un `action_blocked` (48 h) ; retrait Reddit → sub retiré de la liste du personnage (`publishing.md`).

- **R24 — Jamais un lien hotofmai.ai ni Fanvue 18+ depuis Instagram, TikTok, Meta ou ofmai.ai.** Même règle que les emails : « ne pas envoyer contenu ou lien hotofmai.ai à une origine SFW » (plan 21 jours, § emails). Routage complet des liens par plateforme et par sub dans `publishing.md`. Si violée : suppression dans l'heure ; c'est un motif de bannissement Meta.

- **R25 — Tout lien sortant porte `utm_source ∈ {instagram, tiktok, x, reddit, fanvue}` × `utm_medium ∈ {bio, dm, comment, post, profile, social}` × `utm_campaign=army-2026-09` × `utm_content=<slug du personnage>` (schéma dans `metrics-attribution.md` §1).** Instagram s'écrit `instagram`, jamais `ig` ni `ig-organic`. Piège vérifié : `META_SOURCES` dans `app/api/attribution/route.ts` (l. 19) contient `instagram` et `ig`, et `resolveSource` (l. 21-33) les résout en `signupSource = "meta"` — la case des pubs payantes — parce qu'elle ne lit `utmMedium` que pour `email` ; `utmSource` est toutefois écrit brut. Deux conséquences : (1) le garde `utm_medium` d'E10.1 (`build-plan.md`, vague 1) est déployé **avant** le premier lien posé (jour 8 au plus tôt) — vérification : `SELECT "signupSource" FROM "User" WHERE "utmSource"='instagram' AND "utmMedium"='bio'` ne renvoie jamais `meta` ; (2) toute requête de M1 filtre sur `utmSource`, jamais sur `signupSource` seul. Pourquoi : la vérité des payants est `User.signupSource` × `Subscription`, et la décision Meta de J14 se lit sur `utm_source=meta`. Si violée : `/api/attribution` n'écrit qu'une fois (`alreadySet`, l. 72 : `signupSource` null seulement) → l'erreur est irrécupérable pour ces inscrits ; corriger le lien, dater l'incident dans `metrics-attribution.md`.

```text
https://ofmai.ai/?utm_source=instagram&utm_medium=bio&utm_campaign=army-2026-09&utm_content=eva
https://hotofmai.ai/?utm_source=reddit&utm_medium=comment&utm_campaign=army-2026-09&utm_content=eva&utm_term=r_aiart
```

## 9. Un humain dans la boucle

- **R26 — Captcha, SMS, code email, 2FA, login : jamais résolus par un agent, jamais par un numéro virtuel.** Le mécanisme est le checkpoint Ghost (`gitd/skills/checkpoint.py` : `VALID_REASONS = {"captcha", "sms", "email", "login", "generic"}`, `DEFAULT_TIMEOUT_S = 600`, `0` = attente infinie) : le run passe en `awaiting_human`, un humain fournit le code sur l'appareil puis reprend le run. Limite du code : le checkpoint n'existe que comme step d'un skill enregistré (`RecordedStepAction`), pas dans les `Action` codées du farm — les skills de création de compte sont donc des skills enregistrés ou ajoutent ce support (`build-plan.md`). Pourquoi : résoudre un captcha est exactement ce que la plateforme teste ; un numéro virtuel est déjà dans ses listes. Si violée : le compte est réputé brûlé dès que la plateforme le remarque ; on ne lance pas la chauffe dessus.

```json
{"action": "checkpoint", "reason": "sms", "prompt": "Enter the SMS code on the device, then resume", "timeout_s": 0}
```

Le port 5055 n'est jamais exposé (REST sans authentification) : tous les `curl` de ce fichier passent par un tunnel SSH, `ssh -L 5055:127.0.0.1:5055 <mac-mini>` (`infrastructure-geelark-proxies.md` §5.4).

```bash
# reprise (ou abandon) par un humain ; 409 si le run n'est pas en awaiting_human, 400 si action invalide
curl -X POST http://127.0.0.1:5055/api/skills/runs/<run_id>/resume -H 'Content-Type: application/json' -d '{"action":"resume"}'
curl -X POST http://127.0.0.1:5055/api/skills/runs/<run_id>/resume -H 'Content-Type: application/json' -d '{"action":"abort"}'
```

- **R27 — `accounts clear-health` est un geste humain, après avoir regardé l'écran de l'appareil.** `VERIFICATION`, `LOGGED_OUT` et `SUSPENDED` ne s'effacent jamais seuls (`HealthState.can_run()` → `False`, commentaire du code : « never auto-login ») ; `COOLDOWN` et `SHADOWBAN_SUSPECT` expirent seuls mais `phase_override` reste jusqu'au `clear-health` (`ledger.open_session()`). Pourquoi : la machine ne sait pas ce qu'il y a sur l'écran ; un « réessai » automatique sur un compte en vérification est la façon la plus sûre de le perdre. Si violée (un workflow appelle `clear-health`) : PR refusée ; `farm_signals` est l'audit.

```bash
python -m gitd.farm.cli accounts clear-health instagram @eva.moore   # health=ok, health_until=NULL, phase_override=NULL
python -m gitd.farm.cli accounts disable tiktok @eva.moore           # pause manuelle ; enable pour reprendre
```

- **R28 — Un signal santé arrête la session en cours, sans réessai.** `check_health()` dans `run_session()` appelle `ledger.signal()` puis sort de la boucle ; `WarmSessionAction` renvoie `success=False, error="health signal: …"` ; `planner.tick()` ne planifie plus rien tant que `can_run()` est faux. Pourquoi : chaque action de plus après un avertissement compte double. Si violée : R17.

## 10. Kill-switches et santé collective

- **R29 — Un signal → pause 48 h du compte et une phase en arrière.** Dans le code : `apply_signal("action_blocked")` → `COOLDOWN` jusqu'à `now + COOLDOWN_HOURS (48)`, `phase_override` = phase précédente ; `shadowban` → `SHADOWBAN_SUSPECT` 7 jours (`SHADOWBAN_DAYS`) en `consume` (aucun code n'émet ce signal aujourd'hui : `zero_reach()` n'est appelé nulle part, voir `health-canaries.md`). Si violée : impossible par le planner ; un `run` manuel sur un compte en cooldown est refusé par `open_session()` (`PermissionError "@… is cooldown until …"`).

- **R30 — Deux comptes rouges en 48 h sur une même plateforme → pause de toute la plateforme.** Décision du brief M1 (§10), **absente du code** : `planner.tick()` ne connaît aucune règle inter-comptes (`build-plan.md`). Geste manuel en attendant : `accounts disable` sur chaque compte de la plateforme, `kill` des jobs en cours. Pourquoi : deux signaux rapprochés sur la même plateforme sont un motif, pas une coïncidence — c'est la plateforme qui a changé de seuil, pas nos comptes. Si violée : le troisième signal est en général un `suspended`.

- **R31 — Trois comptes `suspended` en 48 h sur une plateforme → plateforme coupée pour la machine.** Décision du brief (§11), absente du code. Aucun nouveau compte sur cette plateforme avant un post-mortem daté dans `docs/social/decisions/` ; IP et appareils en quarantaine 30 jours (R19). Si violée : on brûle le stock de personnages sur une plateforme qui nous a déjà identifiés.

- **R32 — Il existe un kill-switch par plateforme et un par machine, actionnable par un humain en une commande.** Aujourd'hui : arrêter le daemon (`python -m gitd.farm.cli daemon`) arrête toute planification future ; les jobs déjà en file se tuent un par un ; la publication par API côté OFMAI n'a pas encore d'interrupteur (`build-plan.md`). Pourquoi : la première heure après un signal collectif décide du nombre de comptes perdus. Si violée (pas d'interrupteur au moment où il faut) : R30 et R31 se jouent à la main, compte par compte.

```bash
# jobs en file / en cours, puis kill d'un job ; kill-switch machine : stop / start (health-canaries.md §4)
curl -s http://127.0.0.1:5055/api/scheduler/queue
curl -X POST http://127.0.0.1:5055/api/scheduler/queue/<qid>/kill
python -m gitd.farm.cli stop      # crée data/farm/STOP, lu par planner.tick et bridge.tick, puis kill des jobs running (à créer, E5.3)
python -m gitd.farm.cli start     # retire le fichier
```

- **R33 — Tout signal santé, tout checkpoint, tout kill-switch remonte sur Discord dans la minute.** Côté OFMAI : `sendDiscordAlert({ level, title, message, route?, error? })` (`lib/core/discord-alerts.ts`, env `DISCORD_WEBHOOK_URL`, silencieux sans elle). Côté fork : rien aujourd'hui (grep `discord` dans `gitd/` : seule une étiquette d'app dans `services/device_context.py`) — les signaux santé passent par le pont vers OFMAI qui alerte (`bridge-ofmai-farm.md`) ; pour tenir « dans la minute », `FarmSession.signal()` déclenche un vidage immédiat de l'outbox (`bridge.flush_now()`, `bridge-ofmai-farm.md` §6), le tick de 300 s n'étant que le filet ; les checkpoints, eux, alertent dans la seconde depuis le fork (`gitd/farm/alerts.py`, E2.1). Pourquoi : Nathan est en Thaïlande, le Mac mini à Paris ; sans alerte, un compte en `VERIFICATION` attend des jours. Si violée : chaque heure de retard sur un checkpoint est un `timed_out` (600 s par défaut) puis un login expiré.

## 11. Médias et code

- **R34 — Aucun média dans le repo ; en base et dans le pont, des clés S3, jamais des URL.** `signUrlSafe(key)` (`lib/storage/s3.ts`, l. 236) signe à la lecture ; bucket privé `hiddn2` (`S3_BUCKET_NAME`) pour les assets, `hiddn2-public` (`S3_PUBLIC_BUCKET`) seulement pour ce qui est public sans authentification ; toute version publiée porte le filigrane (`content-pipeline.md`). Pourquoi : invariant 3 de `CLAUDE.md` ; une URL signée expire et une URL brute dans un `config_json` de job Ghost expose le bucket sur un REST sans authentification (R10). Si violée : PR refusée ; une clé privée exposée est supprimée et l'asset regénéré.

- **R35 — Aucun skill ne tourne sur un compte réel tant que `tested_on` de son `skill.yaml` est vide.** État au 2026-09-14 : `tested_on: []` sur `ofmai_instagram` et `ofmai_tiktok` ; procédure de `docs/FARM.md` (« Selectors are not verified yet ») : Skill Miner sur chaque app depuis le Mac mini, ids corrigés dans `elements.yaml`, `warm_session --minutes 2` sous live stream, puis `tested_on` rempli ; content-desc d'abord, resource-id ensuite, jamais de coordonnées. Pourquoi : un sélecteur faux tape le mauvais bouton — sur un écran de publication, c'est « Share » sur le mauvais média ou « Follow » en boucle (R17). Si violée : session tuée, la journée du compte est considérée dépensée (les lignes `farm_actions` existent).

- **R36 — Les 39 tests farm sont verts avant tout commit sur le fork, et tout changement de `warm.py` ou d'un skill passe un dry run `FARM_FAST=1`.** Pourquoi : ces tests sont la référence exécutable de chaque chiffre de ce fichier ; `FARM_FAST=1` rejoue une session complète sans téléphone (horloge virtuelle de `gitd/farm/skillkit.py`). Si violée : commit annulé.

```bash
sh scripts/farm_tests.sh                                                   # PYTHONPATH=. pytest tests/test_farm_*.py -q
FARM_FAST=1 PYTHONPATH=. python -m pytest tests/test_farm_skills.py -q     # les deux skills, bout en bout, sans appareil
```

## 12. Ce que le code garantit aujourd'hui, ce qu'il ne garantit pas

| Règle | Appliquée par | Trou à combler (`build-plan.md`) |
|---|---|---|
| R1, R2 | KYC `real_person` (Didit + Rekognition) sur OFMAI | QA identité des assets générés (CompareFaces n'est utilisé que par le KYC) |
| R3, R4 | `_tap_text("AI-generated content")` best effort | vérification du toggle, `tested_on` vide sur les deux skills |
| R5, R6, R7 | `isSFWHost`, `isModelAllowedOnSFWHost` → 403, `checkPromptPolicy`, `isExplicitNsfw` | `ContentAsset.contentType` × `platform` refusé par le pont |
| R9 | `ledger.add_account()` ValueError | plateformes limitées à `instagram` / `tiktok` (`cli.py`, `ledger.py`, `PHASE_EXTRA_DAYS`, `_PATTERNS`, `SKILL_BY_PLATFORM`) |
| R11, R12, R13 | `type_text` ASCII (R13) | agent de conformité des légendes et pools (R11, R12) |
| R14, R15, R18 | `policy.py` + `ledger.py`, 39 tests (`sh scripts/farm_tests.sh`) | — |
| R16 | `plan_sessions()` | `cli run` sans garde horaire ; publication API sans garde |
| R17 | caps `follows`, `health.detect` | aucun suivi de 429 côté API (X, Reddit) |
| R19-R22 | rien dans le fork | tout est dans GeeLark / IPRoyal, voir `infrastructure-geelark-proxies.md` |
| R23-R25 | `META_SOURCES` documenté ici | générateur de légendes sans URL avant cruise ; matrice UTM dans le pont |
| R26, R27, R28 | checkpoint (skills enregistrés seulement), `clear-health` CLI, `check_health` | checkpoint dans les `Action` codées ; skills de création de compte |
| R29 | `apply_signal`, `open_session` | signal `shadowban` jamais émis |
| R30-R33 | rien | règles collectives, kill-switches, Discord depuis le pont |
| R34 | `signUrlSafe`, deux buckets | filigrane ; le pont transporte des clés, pas des URL |
| R35 | rien (`tested_on: []`) | Skill Miner sur le Mac mini, `tested_on` rempli |
| R36 | `scripts/farm_tests.sh` | — |

## 13. Avant de lancer quoi que ce soit

- Le compte est dans le ledger (`accounts list`), son `timezone` est celui de GeeLark, son proxy statique est celui de sa création.
- `budget <platform> <handle>` montre la phase attendue ; `health=ok` ; pas de `[disabled]`.
- La légende et les commentaires du jour ont passé la porte de conformité (R11, R12), sont ASCII s'ils vont sur l'appareil (R13), sans URL avant cruise (R23), avec les bons `utm_*` (R25).
- L'asset est `sfw` si la plateforme est Instagram ou TikTok (R6).
- Discord reçoit les alertes (`DISCORD_WEBHOOK_URL` posée) et quelqu'un peut atteindre l'appareil dans l'heure (R26, R33).
- Il est entre 07:00 et 00:59 heure locale du compte (R16).
- Le skill du compte a un `tested_on` non vide (R35).

## 14. Commandes de contrôle

```bash
python -m gitd.farm.cli accounts list                    # jour de vie, phase, health, [disabled], [api]
python -m gitd.farm.cli budget instagram @eva.moore      # caps du jour vs dépensé, REST DAY le cas échéant
python -m gitd.farm.cli plan instagram @eva.moore        # heures et durées des sessions du jour
curl -s http://127.0.0.1:5055/api/scheduler/status       # un job actif par téléphone (tunnel SSH, infrastructure-geelark-proxies.md §5.4)
curl -s "http://127.0.0.1:5055/api/skills/runs?limit=50" # runs récents, dont ceux en awaiting_human
```

Ces commandes lisent ; les seules écritures humaines prévues par ce fichier sont `accounts add`, `accounts enable|disable`, `accounts clear-health`, `stop|start`, `platform pause|resume|cut`, `POST …/resume` et `POST …/kill`. Le passage en `api_mode` se fait côté OFMAI (`PATCH /api/admin/social/accounts/{id} {"apiMode": true}`, recopié dans `farm_accounts.api_mode` par le pont) ; `accounts api-mode` (CLI) ne sert qu'en mode dégradé, pont arrêté, et est écrasé au tick suivant (`warming-policy.md` §10).
