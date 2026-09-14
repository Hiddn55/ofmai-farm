# Architecture de M1 — composants, flux, processus, secrets, pannes

> **Nature** : reference
> **Statut** : à vérifier — les composants marqués « existe » ont été lus dans le code au 2026-09-14 ; le pont, la banque, les workflows et les skills X/Reddit n'existent pas encore
> **À jour au** : 2026-09-14
> **Répond à** : quels systèmes composent la machine M1, où tourne chaque processus, comment un asset circule de sa génération au rapport du matin, où vit chaque secret, et ce qui se passe quand un maillon tombe
> **Code concerné** : OFMAI `instrumentation.ts`, `lib/core/internal-url.ts`, `lib/core/host.ts`, `lib/core/discord-alerts.ts`, `lib/storage/s3.ts`, `lib/analytics/posthog-server.ts`, `lib/ingest/instagram-proxy.ts`, `lib/ingest/replication-batch.ts`, `lib/providers/image-replicate.ts`, `lib/providers/video-replicate.ts`, `lib/providers/gemini.ts`, `lib/billing/pricing.ts`, `app/api/admin/instagram/replicate-image/route.ts`, `app/api/admin/instagram/replicate-video/route.ts`, `app/api/admin/replication-batch/route.ts`, `app/api/internal/log-digest/route.ts`, `.claude/loop/notify.mjs`, `.claude/workflows/daily-fix.js`, `.claude/skills/prod/prod.sh`, `docker-compose.yml` ; fork ofmai-farm `run.py`, `gitd/config.py`, `gitd/app.py`, `gitd/mcp_server.py`, `gitd/models/base.py`, `gitd/services/scheduler_service.py`, `gitd/services/admin_auth.py`, `gitd/services/device_context.py`, `gitd/skills/checkpoint.py`, `gitd/farm/policy.py`, `gitd/farm/planner.py`, `gitd/farm/cli.py`, `gitd/farm/skillkit.py`

Ce fichier est la carte. Le contrat du pont est dans `bridge-ofmai-farm.md`, la banque dans `content-pipeline.md`, les chiffres de chauffe dans `warming-policy.md`, la santé dans `health-canaries.md`, les gestes par plateforme dans `publishing.md`, les téléphones et proxies dans `infrastructure-geelark-proxies.md`, la mesure dans `metrics-attribution.md`, les interdits dans `rules.md`, les tâches dans `build-plan.md`.

## 1. Schéma

```
┌────────── OFMAI — prod, derrière Cloudflare, 3 nœuds Tailscale (platform/prod-access.md) ──────────┐
│ ofmai.ai (SFW, crons)   hotofmai.ai (NSFW)   Postgres 17 (nœud bdd)   S3 hiddn2 / hiddn2-public    │
│ User · Subscription · Generation · AICharacter                  masters, variantes, filigranes     │
│ ContentAsset · SocialAccount · SocialPublication · FarmEvent                          (à créer)    │
│ /api/farm/{accounts,queue,comments,personas,publications,events}                      (à créer)    │
└────────────────────────────────────────────────────────────────────────────────────────────────────┘
        ▲ HTTPS sortant seulement          ▲ webhooks des moteurs                 ▲ visiteurs avec UTM
        │ x-farm-secret                    │ (Soul, Seedance, Lustify…)           │
┌─────────────── Mac mini, Paris ────────────────┐      ┌──────────────── SaaS et cloud ────────────────┐
│ python3 run.py           :5055 REST+dashboard  │      │ GeeLark : 6 téléphones + 1 observateur        │
│   └ scheduler (tick 30 s, 1 job/téléphone)     │ ADB  │   proxy IPRoyal : IP statique ISP US          │
│ gitd.mcp_server          :8002 (optionnel)     │─────▶│   + mobile collant ; apps IG/TikTok/X/Reddit  │
│ gitd.farm.cli daemon     planner, 60 s         │      │ TikTok Content Posting via MCP Higgsfield     │
│ gitd.farm.cli bridge     à créer, 300 s        │      │ API X · API Reddit (par l'IP statique)        │
│ growth-*.js ×4 (launchd) workflows, à créer    │      │ ManyChat (comment-to-DM) [à vérifier]         │
│ SQLite data/gitd.db (ledger, jobs, outbox)     │      │ Fanvue · PostHog EU · Discord (webhook)       │
│ entrée : SSH seulement (Nathan, Thaïlande)     │      │                                               │
└────────────────────────────────────────────────┘      └───────────────────────────────────────────────┘
```

Deux règles structurent tout : **la ferme tire, OFMAI ne pousse jamais** (le Mac mini n'a pas d'entrée publique) et **OFMAI est la source de vérité** des personnages, des assets, des légendes et des publications ; le fork l'est du ledger et de la santé instantanée (`bridge-ofmai-farm.md` §1).

## 2. Composants

| Composant | Rôle dans M1 | Où | État |
|---|---|---|---|
| OFMAI (Next.js 16, Prisma, S3) | réplique les posts du radar avec le personnage comme sujet (seule source de contenu, aucun prompt libre ; le Soul n'intervient qu'en mode `style` — `lib/providers/image-replicate.ts` l. 92 `useSoul = mode === "style" && soulReady`), contrôle chaque rendu par Gemini, écrit les légendes, tient la banque et la file, reçoit les événements, attribue les inscrits, alerte | 3 machines : `ofmai` (ofmai.ai, déployée par Coolify), `hotofmai` (VPS Hostinger séparé), `bdd` (Postgres 17 sur le serveur Coolify) ; accès SSH par le serveur Coolify en `-J`, Cloudflare devant les deux domaines | existe ; routes `app/api/farm/*`, `lib/social/`, tables sociales à créer |
| Mac mini de Paris | héberge tout ce qui touche un téléphone : Ghost, module farm, pont, workflows Claude ; un clone du repo OFMAI pour les workflows et le skill `prod` | Paris ; Nathan y accède en SSH depuis la Thaïlande | existe [à vérifier : repo OFMAI cloné, `adb`, Python ≥ 3.10 installés] |
| Ghost (fork `ofmai-farm`, upstream android-agent v1.5.1) | serveur FastAPI + Uvicorn, scheduler par téléphone, moteur de skills, checkpoints humains, dashboard Vue, serveur MCP | Mac mini | existe |
| Module farm `gitd/farm/` | politique de chauffe, ledger, planner, skills `ofmai_instagram` / `ofmai_tiktok`, 39 tests | Mac mini, même SQLite que Ghost | existe ; `bridge.py`, skills X/Reddit, `comment_reply`/`dm_reply` à créer |
| GeeLark | téléphones Android cloud : un par personnage, plus un observateur ; ADB + API + RPA (plan Base, 29,9 $/mois/téléphone, brief §2) ; GPS, fuseau, langue, région alignés sur le proxy | cloud GeeLark, piloté en ADB depuis le Mac mini | compte à ouvrir ; aucun code ne parle à GeeLark |
| IPRoyal | par téléphone : une IP statique résidentielle ISP US (2,40 $/IP/mois, jamais changée) et un mobile en session collante (5,20 $/Go) même État (brief §3) ; l'IP statique sert aussi aux appels API X/Reddit depuis le Mac mini | configuré dans GeeLark ; côté Mac mini, format `user:pass@host:port` ou `host:port:user:pass` (`lib/ingest/instagram-proxy.ts`) | compte existant ; rien dans le fork (`grep proxy gitd/farm/` : vide) |
| API TikTok (Content Posting) via le connecteur MCP `higgsfield` | publication en `api_mode` : `tiktok_connect` → `tiktok_accounts` → `media_import_url` → `tiktok_prepare_publish` → `tiktok_publish` → `tiktok_publish_status` ; un `connector_id` par compte (`tiktok_connect` accepte un `name` distinct pour un second compte) ; quotas du connecteur 5 posts/min et 13 posts/24 h glissants ; `is_aigc` (booléen **optionnel** dans le schéma de `tiktok_prepare_publish` et de `tiktok_publish`, relu le 2026-09-14 : seuls `connector_id`, `mode` et `media_type` sont exigés) est toujours renseigné chez nous, depuis l'`aigc_label` de l'item de file (§3 étape 6) ; le média doit être hébergé chez le fournisseur (`media_import_url`, ≤ 50 Mo) | connecteur claude.ai, appelé depuis un workflow Claude sur le Mac mini ; compte différent de celui de l'app (`HIGGSFIELD_API_KEY`) | existe (outils vérifiés) ; aucun compte connecté |
| ManyChat (ou équivalent) | comment-to-DM Meta : un commentaire « real / how / ai / tool » déclenche un DM « 100 % IA, faite sur OFMAI, 15 crédits offerts » ; 200 DM/h max, réponse seulement à une action de l'utilisateur (brief §7) | SaaS, connecté au compte Instagram du personnage | rien dans le code [à vérifier : plan, API, compte Business requis] |
| Fanvue | page créatrice IA du personnage, premier lien du link-in-bio, badge « AI creator » [à vérifier] ; côté OFMAI `lib/fanvue/` couvre l'App Store et le billing, pas les pages créatrices | SaaS | pages à créer (`personas.md`) |
| PostHog | funnel visiteur → inscrit → génération → paiement, découpé par UTM ; instance EU, projet 130897 (`metrics-attribution.md` §4) | SaaS | existe ; aucun événement social |
| Discord | alertes santé et checkpoints (`sendDiscordAlert`, `lib/core/discord-alerts.ts`) ; rapport quotidien (`.claude/loop/notify.mjs`, tronqué à 1 900 caractères) | webhook | existe ; rien de social n'y est branché, rien dans le fork |

## 3. Flux de bout en bout

```
radar ──▶ réplication ──▶ banque ──▶ file ──▶ ferme ──▶ post ──▶ métriques ──▶ OFMAI (attribution, rapport)
 OFMAI     OFMAI           OFMAI      OFMAI    Mac mini  téléphone  téléphone/    prod + PostHog + Discord
 (Scraped-  (routes         (contrôle  (Social- (bridge,  ou API     API/observ.
  Post,      replicate-*,    Gemini,    Publica- planner,
  outlier-   webhooks)       légende,   tion +   scheduler)
  Score)                     S3)        aigcLabel)
```

1. **Sélection dans le radar** (OFMAI). Le radar est la seule source de contenu : pour la niche du personnage (`ScrapedPost.niche`, dénormalisée depuis `TrackedInfluencer.niche`), le workflow quotidien prend les meilleurs posts par `ScrapedPost.outlierScore` sur une **fenêtre glissante de 30 jours** (`postedAt ≥ now − 30 j`), élargie à **60 jours** seulement si la niche compte moins de 3 × n candidats (`personas.md` `window_days: 30` / `window_days_max: 60`, `content-pipeline.md` §4.1), comptes `TrackedInfluencer.accountType` `ia` ou `reelle` indifféremment (`ia` préféré à score égal : plus facile à reproduire ; un post du radar est une référence de scène, jamais un visage à reproduire), et **jamais déjà consommés par ce personnage** : le verrou est `ContentSource`, une ligne par couple (personnage, post radar), unicité `(characterId, scrapedPostId)` ; l'asset porte `sourcePostId` et `attempt`, unicité `(characterId, sourcePostId, attempt)` (à créer, `content-pipeline.md` §2). Le seul marqueur existant est global : `runBatch()` (`lib/ingest/replication-batch.ts`) passe `ScrapedPost.replicationStatus` à `replicated` quel que soit le personnage.
2. **Réplication** (OFMAI). Une réplication par post source, avec le personnage comme sujet, par les routes de réplication radar — et rien d'autre (aucun prompt libre) : carrousel (`mediaType = "image"`) → `POST /api/admin/instagram/replicate-image` (`imageUrl`, `characterId`, `mode: faithful | style`) → `startImageReplicate()` (`lib/providers/image-replicate.ts` : édition d'image avec les photos de référence SFW du personnage `sfwFaceUrl` / `sfwFrontUrl` / `sfwBackUrl`, webhook `/api/webhooks/edit-image` ; en mode `style` seulement, Soul si `soulStatus = ready`, webhook `/api/webhooks/higgsfield-soul-image`) ; reel (`mediaType = "video"`) → `POST /api/admin/instagram/replicate-video` (`videoUrl`, `characterId`, `mode: faithful | adapt`, `quality: standard | high`, `withVoice`) → `lib/providers/video-replicate.ts` (`faithful` : première image éditée puis mouvement du reel transféré, webhooks `edit-image` → `kling-motion` ; `adapt` : prompt écrit par `geminiService.buildVideoPrompt()` puis édition vidéo, webhook `seedance-edit`). L'entrée par lot depuis le radar existe déjà : `POST /api/admin/replication-batch` (`postIds`, `characterIds`, `mode: clone | inspired`, `quality`, `withVoice`, `language` ; pool limité aux personnages de l'admin en `status = ready` avec les 3 références SFW) → `runBatch()` en `after()`, un `BatchItem` par post, URL source `r2PublicUrl(r2VideoKey)` sinon `signUrlSafe(s3Key)` sinon `cdnMediaUrl` (vérifié le 2026-09-14 dans `lib/ingest/replication-batch.ts` l. 23-28 : `sourceUrlFor()` ne lit jamais `ScrapedPost.r2ImageKeys` — un carrousel stocké sur R2 seul n'a donc pas d'URL source et l'item finit en `failed` « no source media available » ; à corriger avant de répliquer des carrousels). Chaque route crée une `Generation` en `processing`, dispatche, répond ; le webhook du moteur écrit la clé S3 et passe en `completed` (invariant 1 de `CLAUDE.md`). **Auth** : les trois routes n'acceptent qu'une session NextAuth (`replicate-*` : tout utilisateur connecté ; `replication-batch` : `requireAdmin()`), aucune ne lit `x-internal-key` — à ajouter pour un appel depuis le Mac mini (§6, E6.6). **Coût** (`lib/billing/pricing.ts`) : `INSTAGRAM_IMAGE_REPLICATE` = 3 cr ; vidéo par `calculateVideoReplicateCost()` sur `VIDEO_REPLICATE_FAITHFUL_STD_PER_5S` = 15, `VIDEO_REPLICATE_FAITHFUL_HD_PER_5S` = 25, `VIDEO_REPLICATE_ADAPT_PER_5S` = 21 par tranche de 5 s (`durMult = max(0.8, durée/5)`, arrondi au supérieur, `+ HOT_SFW_VOICE_CHANGE_POST` = 2 avec la voix). **Le compte admin n'est jamais débité** : `user.type === "admin"` saute contrôle, débit et remboursement dans les deux modules (`creditsCharged: 0`) ; le coût réel des six personnages est donc celui des moteurs, pas des crédits. Détail : `content-pipeline.md`.
3. **Contrôle et banque** (OFMAI). Chaque rendu `completed` passe le **contrôle Gemini** (`lib/providers/gemini.ts`, `GEMINI_API_KEY`, `GEMINI_MODEL` défaut `gemini-2.5-flash` ; `geminiService` n'expose aujourd'hui que `buildVideoPrompt()`, l'envoi d'une vidéo par la Files API existe — méthode de contrôle à créer) : `geminiService.reviewGeneratedMedia({ mediaBuffer, mimeType, kind, referenceImages, characterProfile })` reçoit le rendu, les images de référence du personnage et un system prompt constant versionné dans `lib/social/qa-prompt.ts` → réponse JSON (`content-pipeline.md` §5.4) : `overall_score`, `summary`, puis les sections `same_person` (visage, morphologie, marques), `anatomy` (mains, doigts, membres, proportions, dents, yeux), `motion` (vidéo : glissement, morphing, membre qui traverse, changement de tenue) et `render`, chacune avec `severity` et `issues` ; décision `keep | retry | reject` recalculée par le code. `keep` → `ContentAsset.status = kept` ; `retry` → nouvelle réplication du même post source, **2 tentatives au plus**, puis le post est marqué inutilisable pour ce personnage ; `reject` → idem, sans réessai. Le hash perceptuel (`phash`) ne sert qu'à ne pas poster deux fois le même rendu. Puis re-rendu par plateforme + filigrane → `ContentAssetVariant` sous `social/<characterId>/variants/<platform>/` → **légende écrite côté OFMAI** par le workflow de contenu (un modèle de langage avec la fiche persona — voix, tics, interdits — et les règles de la plateforme cible : longueur, hashtags, pas de lien, tag NSFW, mention IA seulement si `disclosed = true`), en s'inspirant de `ScrapedPost.caption` du post source → relue par l'agent conformité (aucun nom de fournisseur, jamais « même visage ») → stockée avec la variante `ready` → `SocialPublication` en `queued` avec `scheduledAt`, la légende finale et le flag `aigcLabel` figé sur le `disclosed` de la fiche persona **au moment de la mise en file** (`bridge-ofmai-farm.md` §3.5). La ferme poste la légende telle quelle, elle n'écrit rien. Détail : `content-pipeline.md`, `publishing.md`.
4. **File** (OFMAI → Mac mini). Le daemon `bridge` fait `GET /api/farm/queue?platform=&handle=&limit=3` avec `x-farm-secret` ; chaque item porte la clé S3 de la variante, son `sha256`, la légende finale, `disclosed` et `aigc_label` (figé à la mise en file, jamais relu depuis la fiche persona au moment du post). Il réclame chaque item (`POST /api/farm/queue/{id}/claim`, bail 60 min), télécharge l'URL signée (`signUrlSafe`, TTL `S3_SIGNED_URL_TTL`, défaut `10800` s), vérifie `sha256`, pousse le fichier sur le téléphone en ADB, statut `staged`. Détail : `bridge-ofmai-farm.md` §3 et §6.
5. **Ferme** (Mac mini → téléphone). Le planner (`python -m gitd.farm.cli daemon`) transforme les slots du jour en jobs `skill_workflow` `warm_session` (priorité 2, `trigger="farm"`, `max_duration_s = (minutes + 10) × 60`) ; le bridge enfile un job `post_video` / `post_photo` / `post_story` selon `SocialPublication.format` à `scheduled_at` ± 20 min (`LATE_TOLERANCE_MINUTES`), et les `metrics_pull` à 24 / 72 / 168 h (`bridge-ofmai-farm.md` §6). Le scheduler Ghost (thread, tick 30 s, un job actif par téléphone) lance `gitd/skills/_run_skill.py` en sous-processus ; la ligne `Data: {…}` du log est parsée et servie par `GET /api/scheduler/history/{run_id}/result`.
6. **Post**. Canal `device` : Instagram toujours, TikTok pendant la chauffe (workflow `post_video`, média « le plus récent de la galerie », toggle AIGC posé seulement si `params.aigc_label` est vrai, best effort). Canal `api` : TikTok en `api_mode` par le connecteur MCP (`is_aigc`, booléen optionnel de `tiktok_prepare_publish`, renseigné depuis l'`aigc_label` de l'item de file), X et Reddit par leurs API depuis le Mac mini à travers l'IP statique du personnage. La ferme ne modifie jamais la légende reçue. Arbitrage app/API par geste : `publishing.md`.
7. **Retour** (Mac mini → OFMAI). Tout événement est d'abord écrit dans `farm_outbox` (même commit que la ligne de ledger), puis envoyé par lots à `POST /api/farm/events` : `posted`, `post_failed`, `health_signal`, `session_summary`, `metrics`. `event_id` unique = idempotence. Détail : `bridge-ofmai-farm.md` §4.
8. **Métriques**. Workflow `metrics_pull` à 24 / 72 / 168 h (écran du téléphone, `publish-api.ts --metrics` pour X/Reddit, ou profil observateur pour les canaris de shadowban) → `farm_post_metrics` → événement `metrics` → `SocialPostMetric`, rattaché au personnage et donc à son flag `disclosed`. Détail : `metrics-attribution.md` §5, `health-canaries.md`.
9. **OFMAI ferme la boucle**. Les visiteurs arrivent avec `utm_source` × `utm_content=<personnage>` (schéma tranché dans `metrics-attribution.md` §1 : `instagram`, jamais `ig-organic`) ; `POST /api/attribution` écrit `User.utmSource/utmContent` une seule fois ; la vérité des payants est `User` × `Subscription` lue par le skill `prod` ; PostHog explique les écarts ; la phase `Rapport` du workflow poste un message Discord par jour, avec vues, inscrits et payants comparés entre les deux groupes `declared` et `undeclared`, dérivés du booléen `disclosed` de la fiche persona (`metrics-attribution.md` §8) ; un `health_signal` reçu déclenche `sendDiscordAlert` dans la minute (`rules.md` R32).

## 4. Processus qui tournent sur le Mac mini

| Processus | Commande | Période / port | Rôle | État |
|---|---|---|---|---|
| Serveur Ghost | `python3 run.py` (charge `.env` du fork) | `0.0.0.0:5055` ; scheduler `_stop_flag.wait(30)` | REST, dashboard Vue (9 onglets), scheduler, checkpoints, flux vidéo des téléphones | existe |
| Serveur MCP Ghost | `python3 -m gitd.mcp_server` ; stdio via `.mcp.json` (`android-agent-mcp`) | HTTP `127.0.0.1:8002/mcp` | laisser un agent Claude piloter un téléphone à la main (Skill Miner, création de compte, checkpoint) | existe, optionnel |
| Planner farm | `python -m gitd.farm.cli daemon --interval 60` | 60 s | slots → jobs `warm_session` ; saute `api_mode`, santé non `ok`, slots plus vieux que 20 min | existe |
| Pont farm | `python -m gitd.farm.cli bridge --interval 300` | 300 s | file, claim, push, `post_video`, outbox, cache de commentaires | à créer (`bridge-ofmai-farm.md` §6) |
| Workflow quotidien | `.claude/workflows/growth-content-army.js` (patron `daily-fix.js` : `meta`, phases, `agent()` à schéma JSON, `parallel()`), lancé par launchd via `claude -p` (E12.0, `build-plan.md` §12) | 10:00 Paris, une fois par jour | génération, QA, légendes, mise en file, pools, rapport Discord | à créer (`build-plan.md`) |
| Publieur API | `.claude/workflows/growth-publish-api.js` → outils MCP `tiktok_*` et `npx -y tsx scripts/social/publish-api.ts` (X, Reddit, par le proxy statique du personnage) | toutes les 3 h entre 07:00 et 23:00 ET (launchd, E12.0) | publications `channel=api`, quota ledger, métriques 24/72/168 h | à créer (E8, §12) |
| Veille ferme | `.claude/workflows/growth-farm-watch.js` | toutes les heures (launchd, E12.0) | santé, canaris sur l'observateur, règles collectives, escalade Discord ; ne relance rien | à créer (§12) |
| Tunnel prod | `bash .claude/skills/prod/prod.sh check` puis `sql …` | à la demande | SQL lecture seule pour le rapport (`metrics-attribution.md` §3) | existe |
| ADB | `sh scripts/farm_adb_connect.sh` (E1.3, launchd chaque minute) : `adb connect <hôte>:<port>` + `glogin` par téléphone, puis `adb -s <hôte>:<port> …` (`device_context.py` utilise déjà des serials `ip:5555`) | permanent | lien Mac mini → GeeLark | [à vérifier : GeeLark expose bien ADB en TCP, `MEDIA_SCANNER_SCAN_FILE` accepté] |
| Sauvegarde | `scripts/farm_backup.sh` (E1.5) | 04:30 Paris (launchd) | SQLite + `phones.json` + noms d'entrées Trousseau → `s3://hiddn2/farm-backups/` | à créer |

Après un redémarrage du Mac mini : **rien à taper** — les `.plist` launchd `ai.ofmai.farm.{ghost,planner,bridge,adb-connect,backup}` (E1.6, `KeepAlive`) et `ai.ofmai.growth.*` (E12.0) relancent tout, à condition que l'ouverture de session automatique de l'utilisateur opérateur soit activée (sans session ouverte, le Trousseau `login` est verrouillé et `security find-generic-password` échoue : bridge sans secret, alertes muettes). Vérification en moins de 5 min :

```bash
launchctl list | grep ai.ofmai                        # 5 lignes farm + les workflows
curl -s 127.0.0.1:5055/api/health                     # Ghost debout
adb devices                                           # 7 serials en état `device`
python -m gitd.farm.cli accounts list                 # jour de vie, phase, health, [disabled], [api]
tail -n 5 ~/Library/Logs/ofmai-farm/bridge.log        # un tick bridge après le redémarrage
curl -s "127.0.0.1:5055/api/skills/runs?limit=5"      # tout run awaiting_human orphelin → POST …/resume {"action":"abort"} avant toute relance
```

Rien n'est en mémoire entre deux démarrages : `job_queue`, `farm_planned`, `farm_publications`, `farm_outbox` vivent dans `data/gitd.db` (SQLite, WAL, `gitd/models/base.py`) ; le scheduler Ghost récupère les jobs orphelins au démarrage.

## 5. Ports et réseau

| Port | Machine | Service | Exposition |
|---|---|---|---|
| 22 | Mac mini, nœuds prod | SSH | prod : `ssh -J` via le serveur Coolify (`platform/prod-access.md`) ; Mac mini : [à vérifier : Tailscale ou port ouvert] |
| 443 | ofmai.ai, hotofmai.ai | Next.js derrière Cloudflare | public ; seule surface qu'appelle le Mac mini (`FARM_OFMAI_BASE_URL`) |
| 5055 | Mac mini | Ghost REST + dashboard (`gitd/config.py` `port: int = 5055`) | **sans authentification** hors `GITD_ADMIN_TOKEN` sur `POST /api/skills/install` ; ne jamais exposer : `docs/API_REFERENCE.md` « No authentication is required » |
| 8002 | Mac mini | MCP HTTP `/mcp` (`gitd/mcp_server.py`) | localhost |
| 5555 | téléphones | ADB TCP (`adb tcpip 5555` dans `device_context.py`) | GeeLark : hôte et port fournis par GeeLark [à vérifier] |
| 3000 / 5433 | poste de dev | Next dev / Postgres dev (`docker-compose.yml`) | dev seulement ; la prod écoute `PORT` (défaut 3000) en loopback pour ses propres crons (`lib/core/internal-url.ts`) |

Sens des flux : Mac mini → OFMAI (HTTPS), Mac mini → téléphones (ADB), Mac mini → API X/Reddit (HTTPS par le proxy statique), Mac mini → connecteur MCP (HTTPS), OFMAI → Discord/PostHog/S3/moteurs (HTTPS). Aucun flux entrant vers le Mac mini en dehors de SSH.

## 6. Où vit chaque secret

| Secret | Variable | Où | Consommé par |
|---|---|---|---|
| Base prod, crons, digest de logs | `DATABASE_URL`, `CRON_SECRET` (en-tête `x-cron-secret`), `LOG_DIGEST_SECRET` | env prod OFMAI (Coolify), `CRON_ENABLED=true` sur un seul conteneur | `instrumentation.ts`, `app/api/cron/*`, `app/api/internal/log-digest/route.ts` |
| Pont ferme → OFMAI | `FARM_BRIDGE_SECRET` (en-tête `x-farm-secret`) ; côté Mac mini Trousseau `security find-generic-password -s ofmai-farm-secret -w` ; `FARM_OFMAI_BASE_URL=https://ofmai.ai` (nœud qui porte `CRON_ENABLED=true` ; les deux hosts partagent la base, §2) | env prod OFMAI + Trousseau du Mac mini | `app/api/farm/*`, `gitd/farm/bridge.py` — à créer |
| Routes admin appelées par les workflows (Mac mini, sans navigateur) | `INTERNAL_API_KEY` (en-tête `x-internal-key`), `INTERNAL_API_USER_ID` (= id du compte opérateur, propriétaire des 6 `AICharacter`) — patron existant de `app/api/admin/generate-batch/route.ts` l. 34-41 ; Trousseau `ofmai-internal-api-key` | env prod OFMAI + Trousseau | `lib/core/admin-guard.ts` `requireAdminOrInternalKey()` (E6.6), `app/api/admin/social/*` |
| S3 | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `S3_BUCKET_NAME` (`hiddn2`), `S3_PUBLIC_BUCKET` (`hiddn2-public`), `S3_REGION`, `S3_SIGNED_URL_TTL`, `CDN_PUBLIC_URL` | env prod OFMAI | `lib/storage/s3.ts` |
| Moteurs et contrôle | `HIGGSFIELD_API_KEY`, `HIGGSFIELD_API_SECRET`, `HIGGSFIELD_API_HOST` (Soul) ; `WAVESPEED_API_KEY` (clips, mouvement, édition vidéo) ; `XAI_API_KEY` (Grok : prompts de réplication, légendes, conformité) ; `GEMINI_API_KEY`, `GEMINI_MODEL` (défaut `gemini-2.5-flash` : prompt du mode `adapt` et contrôle qualité des rendus, §3) ; `BACKEND_URL` + `WEBHOOK_SECRET` (URL de rappel des moteurs) | env prod OFMAI | `lib/providers/*`, `lib/providers/gemini.ts` |
| Fanvue | `FANVUE_APP_UUID`, `FANVUE_WEBHOOK_SECRET`, `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `OAUTH_REDIRECT_URI`, `NEXT_PUBLIC_FANVUE_ORIGIN` | env prod OFMAI | `lib/fanvue/` (App Store et billing, pas les pages des personnages) |
| PostHog | `NEXT_PUBLIC_POSTHOG_KEY`, `NEXT_PUBLIC_POSTHOG_HOST` (le défaut du code est `https://us.i.posthog.com`, la prod est en EU) | env prod OFMAI | `lib/analytics/posthog-server.ts`, `components/PostHogProvider.tsx` |
| Discord | `DISCORD_WEBHOOK_URL` ; sur le Mac mini, Trousseau `ofmai-discord-webhook` ; côté fork, env `FARM_DISCORD_WEBHOOK_URL` sinon la même entrée Trousseau | env prod OFMAI + Trousseau | `lib/core/discord-alerts.ts`, `.claude/loop/notify.mjs`, `scripts/social/daily-report.mjs` (à créer), `gitd/farm/alerts.py` `notify(level, title, message)` (à créer, E2.1) |
| Host SFW | `NEXT_PUBLIC_SFW_HOSTS=ofmai.ai` | env prod du nœud `ofmai` | `lib/core/host.ts` |
| Proxies côté serveur Next | `INSTAGRAM_PROXY_URLS` (scraping radar, sans lien avec les téléphones) | env prod OFMAI | `lib/ingest/instagram-proxy.ts` |
| Ghost | `GITD_ADMIN_TOKEN` (en-tête `X-Ghost-Admin-Token` ou `Authorization: Bearer`), `ANTHROPIC_API_KEY`, `DEFAULT_DEVICE` (`.env.example` du fork) | `.env` du fork sur le Mac mini, chargé par `run.py` | `gitd/services/admin_auth.py`, agent chat |
| Prod en lecture | mot de passe `claude_readonly` : Trousseau `ofmai-prod-db-readonly` ; clé SSH habituelle ; en routine cloud `OFMAI_PROD_DB_PASSWORD`, `OFMAI_PROD_SSH_KEY` | Trousseau du Mac | `.claude/skills/prod/prod.sh` |
| GitHub (PR des workflows) | Trousseau `ofmai-github-token` | Trousseau du Mac | `.claude/workflows/daily-fix.js` |
| Proxies IPRoyal, profils téléphone | identifiants proxy `HOST:PORT:USER:PASS` par profil | console GeeLark + Trousseau `ofmai-proxy-<slug>-static` / `-mobile` (lus par le publieur X/Reddit) | GeeLark, `scripts/social/publish-api.ts` ; jamais dans `farm_accounts` ni dans un `config_json` de job (`rules.md` R9) |
| Comptes sociaux (email, mot de passe, SIM, codes de secours) | — | Trousseau `ofmai-social-*` (table ci-dessous), second exemplaire dans le gestionnaire de Nathan (`account-creation.md` §8) ; jamais le repo ni la SQLite non chiffrée du fork | un humain, au checkpoint |
| OAuth TikTok de chaque compte | — | chez le fournisseur du connecteur MCP ; `tiktok_reconnect` quand le connecteur passe en `error` | workflow de publication |
| Sauvegarde du fork | clés IAM de l'utilisateur `farm-backup` (`s3:PutObject` sur `hiddn2/farm-backups/*` seulement) | Trousseau `ofmai-aws-backup` (`ACCESS:SECRET`) | `scripts/farm_backup.sh` (E1.5) |
| ManyChat | token [à vérifier] | SaaS | — |

**Trousseau du Mac mini — noms canoniques**, repris mot pour mot par les autres fichiers (`security find-generic-password -s <nom> -w`) :

| Entrée | Contenu | Consommé par |
|---|---|---|
| `ofmai-farm-secret` | `FARM_BRIDGE_SECRET` | `gitd/farm/bridge.py`, `curl` du pont |
| `ofmai-discord-webhook` | URL du webhook | `notify.mjs`, `daily-report.mjs`, `gitd/farm/alerts.py` |
| `ofmai-github-token` | PAT GitHub | `daily-fix.js` |
| `ofmai-geelark-token` | token API GeeLark | `geelark-cli` |
| `ofmai-internal-api-key` | `INTERNAL_API_KEY` | workflows `growth-*` → `app/api/admin/social/*` |
| `ofmai-aws-backup` | `ACCESS:SECRET` de l'IAM `farm-backup` | `scripts/farm_backup.sh` |
| `ofmai-prod-db-readonly` | mot de passe `claude_readonly` | `.claude/skills/prod/prod.sh` |
| `ofmai-proxy-<slug>-static`, `ofmai-proxy-<slug>-mobile` | `HOST:PORT:USER:PASS` | GeeLark (à la main), `publish-api.ts` |
| `ofmai-social-gmail-<slug>` | mot de passe Gmail (`-a <email>`) | humain, J0 |
| `ofmai-social-sim-<slug>` | `PIN=…;PUK=…` (`-a <numéro>`) | humain, checkpoint `sms` |
| `ofmai-social-<plateforme>-<slug>` | mot de passe du compte (`-a <email>`) | humain, checkpoint `login` |
| `ofmai-social-<plateforme>-<slug>-recovery` | codes de secours si 2FA imposée | humain |
| `ofmai-social-x-<slug>-oauth` | refresh token OAuth 2.0 du compte X | `lib/social/publishers/x.ts` |
| `ofmai-social-reddit-<slug>-oauth` | `client_id:client_secret` de l'app `script` du personnage | `lib/social/publishers/reddit.ts` |
| `ofmai-x-app` | `client_id:client_secret` de l'unique app développeur X | `lib/social/publishers/x.ts` |

Côté OFMAI il n'existe pas de `.env.example` ; la liste des variables de prod se lit avec `bash .claude/skills/prod/prod.sh env sfw --diff-dev` (noms et longueurs, jamais les valeurs).

## 7. Modes de panne et reprise

| Panne | Ce qui se passe | Reprise |
|---|---|---|
| Mac mini éteint ou déconnecté | plus aucune session ni post sur appareil ; les publications restent `queued` côté OFMAI ; les comptes perdent leur rythme (pas de rattrapage : un slot plus vieux que `LATE_TOLERANCE_MINUTES = 20` est sauté) ; les baux de claim expirent après 60 min et redeviennent `queued` | launchd relance tout (E1.6) ; les cinq commandes de vérification du §4 ; abandonner tout run `awaiting_human` orphelin avant de laisser le planner tourner |
| Session macOS fermée / Trousseau verrouillé | `security find-generic-password` échoue : bridge sans secret (401 en boucle), `alerts.py` muet, publieur sans proxy | ouverture de session automatique de l'utilisateur opérateur (Réglages › Utilisateurs, décision FileVault datée, vague 0) ; en attendant, ouvrir la session à la main |
| Ghost tombe, planner et bridge debout | `enqueue_job` écrit dans `job_queue` mais rien n'est lancé ; un job `running` au moment du crash est marqué orphelin au redémarrage, son log est dans `/tmp/sched_job_<id>.log` | `python3 run.py` ; un `post_video` interrompu après le tap « Share » est `ambiguous` → `needs_human` (`bridge-ofmai-farm.md` §7) |
| OFMAI injoignable (déploiement, Cloudflare, 5xx) | le bridge ne modifie rien localement ; `farm_outbox` s'accumule avec backoff `min(30 min, 1 min × 2^attempts)` ; les sessions de chauffe continuent (elles ne dépendent pas d'OFMAI) | rien à faire ; au retour, le lot part au tick suivant ; `event_id` évite les doublons |
| Secret du pont cassé (401) | alerte Discord, boucle du bridge en pause 15 min | reposer `FARM_BRIDGE_SECRET` des deux côtés (Coolify + Trousseau), redémarrer le bridge |
| Téléphone GeeLark hors ligne, ADB perdu | le job échoue (`device not found`), `post_failed` avec `ambiguous=false`, la santé du compte ne bouge pas ; `staged` repasse à `claimed` si `adb shell ls` échoue | `adb connect` ; outil MCP `device_health` / `fix_device_health` ; au plus 2 tentatives par publication |
| Proxy statique en panne | l'appareil n'a plus de réseau ; ne **jamais** remplacer l'IP (`rules.md` R18) | `accounts disable` le temps du ticket IPRoyal ; `enable` au retour de la même IP |
| Bascule mobile pendant une action | motif « suspicious login » | interdit par construction : la bascule n'a lieu que dans le creux ≥ 45 min entre deux sessions (`plan_sessions`, `rules.md` R19) |
| Checkpoint humain non résolu | run en `awaiting_human`, `DEFAULT_TIMEOUT_S = 600` → `timed_out` (relançable) ; `0` = attente infinie | un humain fournit le code sur l'appareil puis `POST /api/skills/runs/{id}/resume` ; alerte Discord dans la minute (R32) |
| Signal santé sur un compte | session arrêtée sans réessai ; `action_blocked` → `COOLDOWN` 48 h (`COOLDOWN_HOURS`) et une phase en arrière ; `shadowban` → 7 j (`SHADOWBAN_DAYS`) ; `suspended` → quarantaine 30 j (`QUARANTINE_DAYS`) ; `verification` / `logged_out` / `suspended` → un humain | `health-canaries.md` ; `accounts clear-health` après avoir regardé l'écran (R26) |
| Deux comptes rouges en 48 h sur une plateforme | pause de la plateforme — décision du brief, absente du code | manuel aujourd'hui : `accounts disable` sur chaque compte, `POST /api/scheduler/queue/{id}/kill` ; règle collective à coder (`build-plan.md`) |
| URL signée expirée au téléchargement (403 après 3 h) | nouveau `claim` (URL re-signée) ; `409` si un autre appareil tient le bail → abandon local | automatique |
| Connecteur TikTok en `error` (token expiré ou révoqué) | plus de publication API pour ce compte ; le planner continue la consommation légère | `tiktok_reconnect` → `authorize_url` (expire en ~10 min) ouverte par un humain **depuis le téléphone du personnage** [à vérifier], puis `tiktok_accounts` doit dire `active` |
| Quota API TikTok atteint | `cadence_burst` (5/min) ou `cadence_daily` (13/24 h) avec `retry_after_seconds` | attendre exactement ce délai ; les échecs et brouillons ne consomment pas le quota |
| Crons OFMAI muets | `CRON_ENABLED` absent ou posé sur plusieurs conteneurs, ou self-call via le FQDN (incident du 26/08/2026, `lib/core/internal-url.ts`) | `prod.sh logs sfw --since 1h --grep Cron` ; vérifier `INTERNAL_BASE_URL` / `PORT` |
| SQLite du fork perdue | ledger, jobs, outbox, publications disparaissent ; les dates `created_on` aussi → la politique repart au jour 1 | sauvegarde quotidienne (`scripts/farm_backup.sh`, E1.5 : `data/gitd.db` + `~/.ofmai/farm/phones.json` + `.env` sans valeurs + noms d'entrées Trousseau → `s3://hiddn2/farm-backups/<AAAA-MM-JJ>.tar.gz`, 14 j) ; **restauration** : `launchctl unload` des plists farm → `aws s3 cp` de l'archive → `sqlite3 data/gitd.db ".restore '/tmp/gitd.db'"` → `phones.json` remis → `accounts list` comparé à `GET /api/farm/accounts` → `launchctl load` → `POST /api/farm/sync` ; les `farm_planned` du jour perdus ne se rejouent pas. Test de restauration une fois avant la vague 3, puis chaque mois (§9) |
| Discord muet | `sendDiscordAlert` est un no-op sans `DISCORD_WEBHOOK_URL` ; un compte en `verification` attend sans que personne le sache | vérifier la variable en prod et le Trousseau du Mac mini avant tout lancement (`rules.md` §13) |

## 8. Ce qui n'existe pas encore

Rien n'est codé de ce qui relie les composants entre eux : routes `app/api/farm/*`, tables sociales Prisma, `lib/social/`, `gitd/farm/bridge.py`, tables `farm_publications` / `farm_outbox` / `farm_comment_cache` / `farm_post_metrics`, skills `ofmai_x` / `ofmai_reddit`, workflow `metrics_pull`, les quatre workflows `growth-*.js`, `scripts/social/daily-report.mjs`, règles collectives et kill-switches, supervision launchd (E1.6, E12.0), sauvegarde SQLite (E1.5). Les comptes GeeLark, les profils, les proxies et les connecteurs TikTok sont à ouvrir. L'ordre, les critères d'acceptation et les tests sont dans `build-plan.md`.

## 9. Exploitation quotidienne : qui regarde quoi, quand

Les comptes vivent en heure de l'Est (`_WINDOWS` 08:00-23:40 ET = 19:00-10:40 à Bangkok, 14:00-05:40 à Paris) : une seule personne ne peut pas tenir « un humain dans l'heure » (`health-canaries.md` §5).

| Rôle | Qui | Fait | Ne fait jamais |
|---|---|---|---|
| Nathan (Bangkok, UTC+7) | fondateur | décisions J4/J7/J14 et décision du test de divulgation à J21 (lecture J14, `metrics-attribution.md` §8.3), achats (GeeLark, IPRoyal, SIM), validation des subs et des textes de DM ; checkpoints et `clear-health` sur la plage **18:00-00:00 ET** (05:00-11:00 Bangkok) | — |
| Assistant Paris | personne nommée (SSH + Discord + SIM physique) | checkpoints, SMS, `clear-health --reason`, `resume`, canaris à regarder sur la plage **08:00-17:00 ET** (14:00-23:00 Paris) | décisions J4/J7/J14 et J21, `platform resume` après S4 |
| Agents (workflows §12 de `build-plan.md`) | launchd | tout le reste | `clear-health`, `resume`, `platform resume`, `accounts api-mode` (R26) |

Quotidien : 10:00 Paris `growth-content-army.js` → 10:15 lecture du rapport Discord (Nathan à 15:15 Bangkok) ; chaque heure `growth-farm-watch.js` → chaque ligne « Humain » est traitée **dans l'heure** par la personne de garde sur la plage ; 07:00-23:00 ET `growth-publish-api.js` toutes les 3 h. Un checkpoint ou une `verification_required` non traité en 2 h par la personne de garde remonte à l'autre (message Discord direct).

Hebdomadaire (lundi, Paris) : DM X/Reddit lus sur l'appareil (`publishing.md` §9) ; stock de variantes `ready` ≥ 3 × cap par plateforme (`content-pipeline.md` §9) ; `tested_on` re-rempli après toute mise à jour d'app (R34) ; sauvegarde de la veille présente sur S3. Mensuel : test de restauration (§7).

Décisions J4/J7/J14, puis J21 pour la divulgation : lues par Nathan sur le rapport du jour J (`metrics-attribution.md` §7, et §8.3 pour le test `declared` / `undeclared`), écrites dans `docs/social/decisions/AAAA-MM-<plateforme>-<decision>.md` (dossier à créer à la première décision), listées dans `INDEX.md`.
