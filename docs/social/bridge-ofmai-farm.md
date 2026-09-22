# Pont OFMAI ↔ ferme : contrat d'API, tables, reprise

> **Nature** : reference
> **Statut** : à vérifier — contrat écrit avant le build ; aucune route `app/api/farm/*`, aucun module `gitd/farm/bridge.py` n'existe encore
> **À jour au** : 2026-09-15
> **Répond à** : comment la ferme (Mac mini, Ghost + `gitd/farm/`) reçoit le contenu, les légendes, les commentaires, les cibles du radar et les fiches persona d'OFMAI, et comment OFMAI reçoit en retour les posts, les métriques, les signaux santé et les résumés de session
> **Code concerné** : OFMAI `app/api/farm/` (à créer), `app/api/internal/log-digest/route.ts` (patron d'auth), `lib/storage/s3.ts`, `lib/core/discord-alerts.ts`, `prisma/schema.prisma` ; fork `gitd/farm/models.py`, `ledger.py`, `planner.py`, `skillkit.py`, `warm.py`, `gitd/services/admin_auth.py`, `gitd/services/_job_helpers.py`, `gitd/skills/ofmai_instagram/workflows/__init__.py`, `gitd/skills/ofmai_tiktok/workflows/__init__.py`

Vue d'ensemble des composants : `architecture.md`. Chiffres de chauffe : `warming-policy.md`. Contenu et QA : `content-pipeline.md`. Règles santé collectives : `health-canaries.md`. Ce fichier ne décrit que le transport entre les deux systèmes.

## 1. Principes

- **La ferme tire, OFMAI ne pousse jamais.** Le Mac mini de Paris n'a pas d'entrée publique ; tout appel HTTP part du Mac mini vers OFMAI. Les endpoints FastAPI du fork (port 5055, `gitd/config.py`) ne servent qu'aux humains et aux workflows qui tournent sur le Mac mini, via SSH. Le serveur du fork est FastAPI, pas Flask (`docs/features/scheduler.md` est périmé sur ce point).
- **OFMAI est la source de vérité** des personnages, des assets (clés S3, jamais d'URL en base, invariant 3 de `CLAUDE.md`), des légendes, des pools de commentaires, des cibles de chauffe tirées du radar (§3.7) et des publications planifiées. Le fork est la source de vérité du ledger (`farm_actions`, `farm_signals`) et de la santé instantanée d'un compte.
- **La ferme ne génère rien et n'écrit rien.** Tout média vient de la banque `ContentAsset` d'OFMAI (une réplication par post du radar, contrôlée par Gemini avant la mise en file, `content-pipeline.md`) ; toute légende est celle figée sur la variante par le workflow de contenu. Le contrat ne transporte donc ni prompt, ni moteur, ni paramètre de relance de rendu : le `retry` du fork (§6, §7) rejoue une **publication**, jamais un rendu. Chaque asset porte `source_post_id` (le `ScrapedPost.id` répliqué, `ContentAsset.sourcePostId`, unique par personnage) et chaque personnage porte `disclosed` (groupe de divulgation IA, décision C5 du brief : groupe `declared` = `sierra`, `camila`, `hana` ; groupe `undeclared` = `skyler`, `riley`, `vera`, sur Instagram, TikTok, X et Reddit ; Fanvue est hors pont, les six y sont déclarés). Chaque publication porte `aigc_label`, figé à la mise en file sur `SocialPublication.aigcLabel` : c'est lui, et jamais la fiche persona relue au moment du post, qui commande le toggle AIGC sur l'appareil et `is_aigc` en `api_mode`.
- **Rien n'est perdu si un côté tombe** : côté OFMAI, une publication reste `queued` tant qu'elle n'a pas été réclamée ; côté fork, tout événement sortant est écrit dans une boîte d'envoi locale avant d'être envoyé.
- **Deux clés d'idempotence** : `(variantId, socialAccountId)` unique pour une publication (jamais deux fois la même variante sur le même compte ; un master rendu pour quatre plateformes donne quatre variantes, donc quatre publications), `eventId` unique pour un événement retour.
- Le contrat ne transporte jamais de nom de fournisseur ni d'identifiant proxy/GeeLark : ces données restent dans `infrastructure-geelark-proxies.md` et la config locale du Mac mini.

## 2. Authentification et secrets

| Sens | En-tête | Variable | Où elle vit |
|---|---|---|---|
| ferme → OFMAI (`/api/farm/*`) | `x-farm-secret` | `FARM_BRIDGE_SECRET` | env prod OFMAI (Coolify) ; Trousseau macOS du Mac mini : `security find-generic-password -s ofmai-farm-secret -w` (même mécanisme que `ofmai-discord-webhook` dans `.claude/loop/notify.mjs`) |
| humain/workflow → fork (`/api/farm/*` FastAPI) | `X-Ghost-Admin-Token` ou `Authorization: Bearer` | `GITD_ADMIN_TOKEN` | env du process Ghost sur le Mac mini ; `gitd/services/admin_auth.py` `require_admin_token` existe déjà (comparaison `hmac.compare_digest`, refus si la variable est vide) — aujourd'hui posé uniquement sur `POST /api/skills/install` |

Côté OFMAI, la garde recopie le patron de `app/api/internal/log-digest/route.ts` : secret lu à la requête, `401 {error: "Unauthorized"}` si la variable est absente **ou** si l'en-tête diffère ; comparaison en temps constant (`crypto.timingSafeEqual`). Les routes farm ne passent pas par la session NextAuth ni par `requireAdmin()`, et ne sont pas filtrées par le host (`lib/core/host.ts`) : c'est le champ `content_type` de l'asset qui dit sur quelle plateforme il peut aller. URL de base côté Mac mini : `FARM_OFMAI_BASE_URL=https://ofmai.ai` — le nœud qui porte `CRON_ENABLED=true` ; `ofmai` (Coolify) et `hotofmai` (VPS) sont deux machines qui partagent le Postgres du nœud `bdd` (`architecture.md` §2, `documentation/platform/prod-access.md`), et les routes farm ne sont pas filtrées par host. Le rate limiting de `middleware.ts` (60 requêtes/min par IP sur `/api/`, l. 37) exempte `/api/farm/*` (E7.2) : un tick du pont fait jusqu'à une trentaine d'appels depuis une seule IP.

## 3. OFMAI → ferme (routes Next.js, `app/api/farm/`)

Toutes en `withLogging("farm-<nom>", handler)` (`lib/core/with-logging.ts`), réponses JSON, erreurs `{error}`.

### 3.1 `GET /api/farm/accounts`

Liste des comptes sociaux attendus par personnage, pour que `python -m gitd.farm.cli accounts add` et le planner restent alignés sur OFMAI.

```json
{"accounts":[{"id":"sa_01","character_id":"cmf…","platform":"instagram","handle":"sierra.cole",
  "role":"persona","market":"US","timezone":"America/Los_Angeles","content_type":"sfw",
  "disclosed":true,"disclosed_since":null,
  "niche":"fitness,ootd,gymgirl","api_mode":false,"paused_until":null,"link_in_bio":"https://…"}]}
```

`role` ∈ `persona | brand | observer | explorer` ; `paused_until` porte le kill-switch de plateforme décidé côté OFMAI (`health-canaries.md`). Le fork copie `paused_until` dans `farm_accounts` (colonne à ajouter, §5.2) et `planner.tick` saute le compte tant que `now < paused_until`, en plus du test `health_state(acc).can_run(now)` déjà présent. Un compte `role = observer` ou `role = explorer` est renvoyé pour la lecture seule et **jamais recopié dans `farm_accounts`** (`ledger.add_account()` le chaufferait ; leurs serials vivent dans `FARM_OBSERVER_DEVICE` et `FARM_EXPLORER_DEVICE` — `health-canaries.md` §2, `infrastructure-geelark-proxies.md` §6, R36 ; le planificateur ne leur donne jamais de travail) ; un `role = brand` peut y entrer avec `enabled = 0` (E1.1), jamais planifié. `api_mode` est la source de vérité côté OFMAI (`SocialAccount.apiMode`, `PATCH /api/admin/social/accounts/{id}`) : le pont l'écrase dans `farm_accounts.api_mode` à chaque tick. `disclosed` est le flag du **personnage** (fiche persona, `personas.md`, lu à la requête par `personaForCharacter(characterId)`, `lib/social/personas.ts`), recopié sur chacun de ses comptes : la ferme l'applique aux **bios** (mention IA ou non) et à rien d'autre — le toggle AIGC suit `aigc_label` de l'item de file (§3.2), jamais ce flag relu au moment du post. Règle unique de bascule, la même que `metrics-attribution.md` §8.3 : **`disclosed` ne change pas pendant le test, sauf (a) un compte non déclaré sanctionné par la plateforme pour contenu IA non étiqueté : bascule individuelle, `disclosed_since` daté, le compte sort de la comparaison ; (b) la décision de J21 qui peut déclarer les six.** `disclosed_since` accompagne toujours `disclosed` dans le payload : `null` tant que le personnage n'a pas basculé, date ISO ensuite. Dans tous les exemples de ce fichier, le personnage fitness sert d'exemple : slug `sierra`, handle `@sierra.cole`, « Sierra Cole » (`personas.md` §3.2, à valider par Nathan).

### 3.2 `GET /api/farm/queue?platform=instagram&handle=sierra.cole&limit=3&channel=device`

Paramètres : `platform`, `handle`, `limit` (défaut 3), `channel=device|api` (défaut `device`). Sans `handle`, tous les comptes du `channel` demandé ; les comptes `apiMode` et les plateformes `x`/`reddit` ne sortent qu'avec `channel=api` (c'est l'appel de `growth-publish-api.js`, `build-plan.md` §12). Publications `queued` (ou `claimed` par le même demandeur, bail non expiré) dont `scheduled_at ≤ now + 30 min`, triées par `scheduled_at` ; rien pour une plateforme `paused`/`cut`, rien pour un compte `health ≠ ok`, jamais une publication Reddit avant `day_of_life ≥ 31` et karma ≥ 100 (`publishing.md` §5). La clé S3 est signée **à la demande** par `signUrlSafe(key)` (`lib/storage/s3.ts`, TTL `S3_SIGNED_URL_TTL`, défaut `10800` s = 3 h) ; la clé brute n'est jamais renvoyée.

```json
{"items":[{"publication_id":"pub_9f","variant_id":"cv_9f","asset_id":"ca_31","source_post_id":"cmf…","character_id":"cmf…","platform":"instagram",
  "handle":"sierra.cole","channel":"device","format":"reel","scheduled_at":"2026-09-15T13:40:00-07:00",
  "caption":"post-run glow. yes it's AI, made on ofmai.ai #AI #fitness",
  "media":{"url":"https://hiddn2.s3….mp4?X-Amz-Algorithm=…","kind":"video","content_type":"video/mp4",
           "sha256":"…","bytes":4182233,"duration_s":9.0,"aspect":"9:16"},
  "disclosed":true,"aigc_label":true,"content_type":"sfw"}]}
```

- `source_post_id` = `ContentAsset.sourcePostId`, le `ScrapedPost.id` du post du radar répliqué pour produire l'asset (unique par personnage, `content-pipeline.md` §2). Informatif pour la ferme (traçabilité dans `farm_publications`, tableau de bord) ; la ferme n'en tire aucune décision.
- `aigc_label` est `SocialPublication.aigcLabel`, **figé à la mise en file** sur le `disclosed` du personnage à cet instant : c'est la seule source du toggle AIGC sur l'appareil et de `is_aigc` en `api_mode`, jamais la fiche persona relue au moment du post (une bascule de `disclosed`, §3.1, ne touche donc pas une publication déjà en file). `disclosed` est repris dans l'item pour l'audit et les bios, la ferme n'en tire aucune décision de label. La mention IA dans `caption` a déjà été mise, ou non, par le workflow de contenu selon `disclosed` (l'exemple ci-dessus est `sierra`, groupe `declared`) : la ferme poste la légende telle quelle.
- `channel` ∈ `device` (workflow Ghost `post_video` / `post_photo` / `post_story` selon `format`, §6 étape 3) | `api` (compte en `api_mode` : TikTok via l'API officielle, X et Reddit via leurs API, exécutés par `growth-publish-api.js` sur le Mac mini, `publishing.md`). Les deux canaux suivent le même cycle claim → posted.
- `caption` est déjà ASCII pour `channel=device` : `HumanInput.type_text` (`gitd/farm/human.py`) supprime tout caractère non ASCII. Le contrôle de conformité de la légende est fait avant la mise en file (`content-pipeline.md`), pas ici.
- `sha256` sert à vérifier le fichier après téléchargement et à ne pas le re-télécharger si déjà présent sur le Mac mini.

### 3.3 `POST /api/farm/queue/{publication_id}/claim`

Body `{"device_serial":"R58N1234"}` — le serial ADB pour `channel=device`, la chaîne `api:<hostname>` (ex. `api:macmini`) pour le publieur API ; `SocialPublication.claimedBy` reçoit la valeur telle quelle. Passe la publication en `claimed`, `claim_expires_at = now + 60 min`. Réponses : `200 {ok, claim_expires_at, media: {url…}}` (URL re-signée fraîche) ; `200` aussi si le même demandeur re-réclame (idempotent) ; `409 {error: "claimed_by_other"}` si un autre appareil tient un bail vivant ; `410 {error: "not_queued"}` si déjà `posted`/`cancelled`. Un bail expiré revient à `queued` paresseusement lors du prochain `GET /api/farm/queue` (pas de cron dédié).

### 3.4 `GET /api/farm/comments?character_id=cmf…&platform=instagram&kind=comment&n=10`

`kind ∈ {comment, reply_ai, reply_thanks, reply_question}` (défaut `comment`). Renvoie `n` textes non encore utilisés du pool du personnage pour ce `kind`, ASCII, marqués `reserved_until = now + 24 h` : `{"comments":[{"id":"cp_1","kind":"comment","text":"the light in this one!!"}, …]}`. Le planner (`gitd/farm/planner.py` `job_config`) passe les `comment` dans `params.comments` (séparés par `\n`, format attendu par `WarmSessionAction`, `gitd/farm/skillkit.py`) — aujourd'hui `job_config` ne passe que `handle`, `minutes`, `niche` ; le job `comment_reply` (E3.2) reçoit `params.replies_ai`, `params.replies_thanks`, `params.replies_question` (`\n`-séparés, 5 chacun). La consommation réelle est remontée par le résumé de session (§4.1, `comments_used` + `replies_used`) ; un texte non consommé redevient disponible à l'expiration de la réservation.

### 3.5 `GET /api/farm/personas/{character_id}`

Sous-ensemble de la fiche persona (`personas.md`) utile sur l'appareil : `handles` par plateforme, `bio` par plateforme (déjà écrite selon le groupe de divulgation), `disclosed`, `disclosed_since` (`null`, ou la date ISO de la bascule prévue par la règle de §3.1), `niche` (hashtags de détour), `forbidden_words`, `reply_tone`, `links`. Ces deux champs ne servent qu'aux **bios** et au pool `reply_ai` ; le label d'un post vient de `aigc_label` (§3.2). Lecture seule, sans cache côté fork au-delà d'une journée.

### 3.6 `PATCH /api/farm/publications/{publication_id}`

Correction manuelle après un cas `needs_human` (§7) : body `{"status":"posted","post_id":"…","post_url":"…"}` ou `{"status":"cancelled"}`. Même secret ; refus `409` si la publication est `queued` ou `claimed` (on ne court-circuite pas un bail vivant). Côté admin (session ou `x-internal-key`, E7.2), `PATCH /api/admin/social/accounts/{id} {"status":"banned"}` annule (`cancelled`) toute publication `queued`/`claimed` du compte ; leurs variantes restent `ready` et réutilisables sur le compte de remplacement — runbook `health-canaries.md` §10.

### 3.7 `GET /api/farm/targets?character=sierra&platform=instagram&limit=30`

Les portes de la chauffe orientée (`warming-policy.md` §7 bis, décision du 2026-09-22) : les meilleurs comptes du **radar** dans la niche du personnage. Depuis le 2026-09-22, la route existe (`app/api/farm/targets/route.ts`, `lib/social/bridge-targets.ts`) et le partage des rôles est l'inverse de §3.4 : **OFMAI classe, la ferme se souvient.** Aucune réservation, aucune table d'usage côté OFMAI (l'ancien projet `SocialTargetUse` / réservation 24 h est abandonné) : la ferme redemande la même liste et pioche dedans ce qui n'est pas en refroidissement (`farm_targets`, §5.2).

Paramètres : `character` (le **slug** de la fiche, `sierra`, ou l'`AICharacter.id` — la ferme n'a que le second, `farm_accounts.character_id`), `platform` ∈ `instagram | tiktok`, `limit` (défaut 30, maximum 100). Même secret que les autres routes ; `400` sur une plateforme hors radar, `404` pour un personnage sans fiche.

Sélection côté OFMAI : `TrackedInfluencer` où `niche` = `niche.radar` de la fiche persona (`personas.md` §1), `platform` = celle demandée, `status = "active"`, `enabled = true`. Tri : d'abord le marché du personnage quand la donnée le porte (`identity.market` → `TrackedInfluencer.market` : `US`→`US`, `FR`→`FR`, `LATAM`→`Latino`, `EU` sans préférence) — sans exclure les autres, une niche pauvre en comptes US rend quand même une liste pleine ; puis le **score de performance du radar** (le meilleur multiplicateur `ourScore` des posts du compte, celui que la fiche créateur affiche en « best outlier ») ; puis les abonnés. Liste identique d'un appel à l'autre tant que le radar ne bouge pas.

```json
{"targets":[{"handle":"lena.trains","platform":"instagram","followers":48210,"score":4.2,"niche":"fitness"}]}
```

- `handle` est le pseudo nu, minuscule, sans `@` (`TrackedInfluencer.handle`) : c'est ce que la session tape dans la recherche de l'application.
- **Le radar n'indexe qu'Instagram** (`TrackedInfluencer.platform`, défaut `instagram`) : sur `tiktok` la route rend une liste vide tant que le radar ne porte pas cette plateforme, et la session retombe sur les `@pseudos` tapés à la main puis sur le hashtag. `x` et `reddit` ne sont pas acceptés (`400`) : pas d'influenceuse à suivre, le détour `r/<niche>` reste la règle (`warming-policy.md` §7).
- Niche vide sur cette plateforme : liste vide, jamais une erreur.
- La ferme ne lit jamais `TrackedInfluencer` : elle ne voit que ce payload (`architecture.md` §1 : le Mac mini ne parle jamais à la base de prod).
- Côté ferme : `bridge.fetch_targets(db, client, account)` appelle la route et écrit chaque pseudo dans `farm_targets` en `source = radar` (un pseudo déjà connu garde son historique, seul `last_seen` bouge). Le tick le fait à l'étape 6 bis quand le compte a moins de 5 portes jouables et que la dernière liste date de plus de 24 h ; une session dont la table est encore vide le fait elle-même une fois (`skillkit.session_niche`). Sans pont configuré : rien ne change, les `@pseudos` de `farm_accounts.niche` restent les portes.
- Consommation remontée dans `session_summary` : `targets_used` (§4.1), les pseudos réellement ouverts — la même liste que `farm_targets.last_played` vient de recevoir.

## 4. Ferme → OFMAI : `POST /api/farm/events`

Un seul endpoint, lot de 1 à 100 événements, corps ≤ 256 Ko. Chaque événement porte un `event_id` (uuid4 généré par le fork au moment de l'écriture dans `farm_outbox`, §5.2), `kind`, `at` (ISO, fuseau du compte), `platform`, `handle`, et un `payload` propre au `kind`. Réponse `200 {"accepted":[…event_id], "duplicates":[…], "rejected":[{event_id, error}]}` ; un lot n'est jamais refusé en bloc pour un seul événement invalide. Un `event_id` déjà reçu est renvoyé dans `duplicates` sans rien réécrire.

### 4.1 Les cinq `kind`

| `kind` | Quand | `payload` |
|---|---|---|
| `posted` | `PostReelAction` / `PostVideoAction` après `session.record(policy.POST, …)` et postcondition vraie | `{publication_id, variant_id, asset_id, source_post_id, post_id: null \| "…", post_url: null \| "…", channel}` — `source_post_id` est recopié de l'item de file (§3.2), pour l'audit ; `post_id` est `null` sur l'appareil aujourd'hui (aucun id récupéré par les workflows), renseigné pour `channel=api` |
| `post_failed` | le job `post_video` se termine en `success=False`, ou le job est `timeout`/`killed` par le scheduler Ghost | `{publication_id, error, attempt, ambiguous: bool}` — `ambiguous=true` si « Share »/« Post » a été tapé mais la postcondition est fausse |
| `metrics` | relevé à 24, 72 et 168 h (par l'appareil, l'API ou le profil observateur, `health-canaries.md`, `metrics-attribution.md` §5.2) | `{publication_id, post_id, at_hours: 24\|72\|168, source: "device"\|"api"\|"observer", views, likes, comments, shares, saves, impressions, score, upvote_ratio, removed: bool, visible: bool\|null, sub, raw?}` — champs non relevés = `null` ; `at_hours` remplace l'ancien `day: 1\|3\|7` (même unité que `farm_post_metrics.at_hours`, aucune correspondance à maintenir) |
| `health_signal` | `FarmSession.signal()` (`gitd/farm/ledger.py`) vient d'écrire un `farm_signals` ; ou `accounts clear-health --reason` (`health-canaries.md` §6) | `{signal_kind: "action_blocked"\|"verification"\|"logged_out"\|"suspended"\|"shadowban"\|"cleared", matched, new_health: "ok"\|"cooldown"\|"verification_required"\|"shadowban_suspect"\|"logged_out"\|"suspended", health_until, phase_override, session_id}` (valeurs de `policy.Health` ; `cleared` → `new_health = ok`) |
| `session_summary` | fin de `WarmSessionAction.execute` (et des workflows `comment_reply` / `dm_reply`) | le dict `Data:` du run : `SessionStats.as_dict()` (`videos, likes, saves, visits, follows, comments, detours, seconds, health, error`) + `handle, day_of_life, phase, profile_seed`, plus `session_id`, `comments_used: [text…]`, `replies_used: [text…]` et `targets_used: [handle…]` (les cibles du radar réellement ouvertes, §3.7) — à ajouter : `warm.py` tire le commentaire par `comments.pop(rng.randrange(len(comments)))`, l'ordre n'est donc pas prévisible sans le remonter |

Sur réception, OFMAI : `posted` → `SocialPublication.status = posted`, `postedAt`, `postId` ; `post_failed` → `failed` (+ `attempts`), `ambiguous=true` → statut `needs_human` et alerte Discord `sendDiscordAlert({level:"warn", route:"farm/events"})` (`lib/core/discord-alerts.ts`) ; `metrics` → upsert `SocialPostMetric`, et `removed = true` sur une publication Reddit incrémente `SocialSubreddit.removals` pour ce sub et ce personnage (`publishing.md` §5, E8.5) ; `health_signal` → `SocialAccount.health/healthUntil` (`cleared` → `ok`), puis évaluation des règles collectives ; `session_summary` → `FarmSessionLog` + `SocialCommentPool.usedAt` pour chaque `comments_used` / `replies_used` + `SocialTargetUse.usedAt` pour chaque `targets_used` (§3.7), et mise à jour de `SocialAccount.status` : `warming` si `phase ∈ {consume, light, network}`, `cruise` si `phase = cruise` — jamais en arrière ; `paused` et `banned` ne sont posés que par un humain (`PATCH /api/admin/social/accounts/{id}`). Les événements PostHog serveur (`captureServerEvent`, `lib/analytics/posthog-server.ts`) sont émis ici, jamais par le fork : catalogue dans `metrics-attribution.md`.

## 5. Tables

### 5.1 Côté OFMAI (`prisma/schema.prisma`, à ajouter)

`ContentAsset` et `ContentAssetVariant` sont définis dans `content-pipeline.md` §2 ; le pont ne lit que `ContentAsset.id/characterId/kind/contentType/qaStatus/sourcePostId` (`sourcePostId` = `ScrapedPost.id` du post du radar répliqué, `@@unique([characterId, sourcePostId])` : un post n'est répliqué qu'une fois par personnage — à construire, `ScrapedPost.replicationStatus` est global et sans personnage dans `prisma/schema.prisma`) et `ContentAssetVariant.id/s3Key/sha256/format/caption/hashtags/compliance` (le master n'a que `masterKey` et `phash` ; le fichier publié est toujours une variante). Rien de ce qui suit n'existe aujourd'hui (aucun modèle `ContentAsset`, `SocialAccount`, `SocialPublication` dans le schéma).

```prisma
model SocialAccount {
  id            String   @id @default(cuid())
  characterId   String?                 // null pour role = brand
  platform      String                  // instagram | tiktok | x | reddit | telegram
  handle        String
  role          String   @default("persona") // persona | brand | observer | explorer
  market        String   @default("US")
  timezone      String   @default("America/New_York")
  contentType   ContentType @default(sfw)
  deviceSerial  String?
  farmAccountId Int?                    // farm_accounts.id côté fork
  apiMode       Boolean  @default(false)
  status        String   @default("creating") // creating | warming | cruise | paused | banned
  health        String   @default("ok")  // mêmes valeurs que policy.Health
  healthUntil   DateTime?
  pausedUntil   DateTime?               // kill-switch plateforme (health-canaries.md)
  linkInBio     String?
  createdAt     DateTime @default(now())
  updatedAt     DateTime @updatedAt
  @@unique([platform, handle])
  @@index([characterId, platform])
}

model SocialPublication {
  id              String   @id @default(cuid())
  variantId       String                      // ContentAssetVariant.id : le fichier publié
  assetId         String                      // ContentAsset.id, dénormalisé pour le payload
  sourcePostId    String                      // = ContentAsset.sourcePostId (ScrapedPost.id), dénormalisé pour le payload et l'audit
  socialAccountId String
  platform        String
  channel         String   @default("device") // device | api
  format          String                      // = ContentAssetVariant.format : reel | feed | story | tiktok | tweet | reddit_post → choix du workflow (§6, étape 3)
  renderKey       String                      // = ContentAssetVariant.s3Key
  sha256          String                      // = ContentAssetVariant.sha256
  caption         String                      // = ContentAssetVariant.caption, figée à la mise en file
  aigcLabel       Boolean                     // = disclosed du personnage au moment de la mise en file (fiche persona, C5), figé ici : seule source du toggle AIGC sur l'appareil et de is_aigc en api_mode ; pas de défaut : 3 personnages sur 6 ne se déclarent pas
  scheduledAt     DateTime
  status          String   @default("queued") // queued | claimed | posted | failed | needs_human | cancelled
  claimedBy       String?
  claimExpiresAt  DateTime?
  attempts        Int      @default(0)
  postId          String?
  postUrl         String?
  postedAt        DateTime?
  error           String?
  createdAt       DateTime @default(now())
  @@unique([variantId, socialAccountId])        // idempotence variante + compte
  @@index([status, scheduledAt])
}

model SocialPostMetric {
  id            String   @id @default(cuid())
  publicationId String
  atHours       Int                             // 24 | 72 | 168 (= farm_post_metrics.at_hours)
  source        String                          // device | api | observer
  views         Int      @default(0)
  likes         Int      @default(0)
  comments      Int      @default(0)
  shares        Int      @default(0)
  saves         Int      @default(0)
  impressions   Int?                            // X
  score         Int?                            // Reddit
  upvoteRatio   Float?                          // Reddit
  removed       Boolean  @default(false)        // Reddit : retrait (→ SocialSubreddit.removals)
  visible       Boolean?                        // canari observateur ; null si non relevé
  sub           String?                         // nom du sub sans "r/"
  at            DateTime @default(now())
  @@unique([publicationId, atHours, source])
}

model SocialCommentPool {
  id            String   @id @default(cuid())
  characterId   String
  platform      String?                         // null = toutes
  kind          String   @default("comment")    // comment | reply_ai | reply_thanks | reply_question
  text          String                          // ASCII
  reservedUntil DateTime?
  usedAt        DateTime?
  usedByHandle  String?
  @@index([characterId, platform, kind, usedAt])
}

// ABANDONNE le 2026-09-22 (§3.7) : la memoire des cibles jouees vit dans farm_targets, cote ferme (§5.2). Jamais cree.
model SocialTargetUse {                         // cibles du radar deja servies a un compte (§3.7)
  id              String   @id @default(cuid())
  socialAccountId String
  characterId     String
  platform        String
  handle          String                        // TrackedInfluencer.handle : nu, minuscule, sans "@"
  reservedUntil   DateTime?
  usedAt          DateTime?                     // pose par targets_used du session_summary
  at              DateTime @default(now())
  @@unique([socialAccountId, handle])           // jamais deux fois la meme cible sur le meme compte
  @@index([characterId, platform, usedAt])
}

model FarmSessionLog {                          // une ligne par session_summary
  id              String   @id @default(cuid())
  socialAccountId String
  sessionId       String   @unique
  day             Int                           // day_of_life
  phase           String
  videos          Int      @default(0)
  likes           Int      @default(0)
  saves           Int      @default(0)
  visits          Int      @default(0)
  follows         Int      @default(0)
  comments        Int      @default(0)
  detours         Int      @default(0)
  seconds         Float    @default(0)
  health          String?
  error           String?
  profileSeed     Int
  commentsUsed    String[] @default([])
  repliesUsed     String[] @default([])
  targetsUsed     String[] @default([])         // handles du radar ouverts pendant la session (§3.7)
  at              DateTime @default(now())
  @@index([socialAccountId, at])
}

model FarmEvent {                                 // boîte de réception brute, jamais purgée avant 90 j
  id         String   @id @default(cuid())
  eventId    String   @unique                    // idempotence
  kind       String
  platform   String
  handle     String
  payload    Json
  at         DateTime
  receivedAt DateTime @default(now())
  @@index([kind, receivedAt])
}
```

`SocialSubreddit` (et `SocialSubredditRemoval`) sont définis dans `publishing.md` §5 (E8.5). Après modification du schéma : régénération dans le conteneur, commandes dans `.claude/rules/prisma.md`.

### 5.2 Côté fork (`gitd/farm/models.py`, SQLite `data/gitd.db`)

Existant : `farm_accounts`, `farm_actions`, `farm_signals` (`models.py`), `farm_planned` (`planner.py`), créées par `Base.metadata.create_all` dans `ledger.init()` / `planner.init()`. À ajouter, dans le même mécanisme (pas d'Alembic) ; les colonnes nouvelles sur `farm_accounts` passent par une liste `_ADDITIVE_COLUMNS` propre au farm, sur le modèle de `gitd/models/base.py` `ensure_additive_columns()` :

| Table / colonne | Rôle |
|---|---|
| `farm_accounts.ofmai_account_id` (TEXT) | `SocialAccount.id`, posé par `accounts add --ofmai-id` ou par `farm sync` |
| `farm_accounts.role` (TEXT, défaut `persona`) | `persona \| brand` — jamais `observer` (E1.1) ; un `brand` n'est jamais planifié |
| `farm_accounts.market` (TEXT, défaut `US`) | marché du personnage (`SocialAccount.market`) |
| `farm_accounts.paused_until` (TEXT ISO local) | copie de `paused_until` (§3.1), lu par `planner.tick` |
| `farm_accounts.disclosed` (INTEGER 0/1, défaut 0) | copie de `disclosed` (§3.1), rafraîchie à chaque tick ; lue par les workflows de **bio** (`account-creation.md`) seulement — le toggle AIGC suit `params.aigc_label` de l'item de file (§3.2), jamais cette colonne |
| `farm_publications` | `publication_id` UNIQUE, `account_id`, `asset_id`, `source_post_id` (informatif, §3.2), `scheduled_at` (local), `local_path` (fichier sur le Mac mini), `device_path` (chemin poussé sur l'appareil), `status` (`claimed \| staged \| posting \| posted \| failed \| needs_human`), `job_id` (→ `job_queue.id`), `attempts`, `last_error`, `at` |
| `farm_outbox` | `event_id` UNIQUE (uuid4), `account_id`, `kind`, `payload_json`, `created_at`, `sent_at` NULL, `attempts`, `next_try_at`, `last_error`, `dead` (0/1) |
| `farm_comment_cache` | `comment_id` (OFMAI), `account_id`, `text`, `fetched_at`, `used_at` NULL |
| `farm_targets` (depuis le 2026-09-22) | `account_id`, `handle` (nu, minuscule), `platform`, `source` (`radar \| following \| manual`), `first_seen`, `last_seen` (dernière fois qu'OFMAI l'a servi), `last_played` NULL, `plays` ; UNIQUE `(account_id, handle)`. La mémoire de la chauffe orientée (§3.7, `warming-policy.md` §7 bis) : `ledger.pick_targets(db, account, n, cooldown_days=14)` rend les pseudos jamais joués ou joués il y a plus de 14 jours, radar d'abord, puis `following` (`ledger.record_discovered`, les comptes croisés dans une liste « suivis »), puis `manual` ; ordre mélangé avec la graine `(compte, jour)` du budget, donc identique d'une session à l'autre le même jour, et `ledger.mark_played` retire au fil de la journée ce qui a été ouvert. Ce n'est pas un cache à la `farm_comment_cache` : rien n'expire, on ne consomme pas, on refroidit |

Écriture atomique : `FarmSession.record(POST)` / `FarmSession.signal()` et l'insertion dans `farm_outbox` se font dans le même `db.commit()` — un événement ne peut pas exister sans sa ligne de ledger, ni l'inverse.

## 6. Processus côté fork : `gitd/farm/bridge.py` (à créer)

Un daemon `python -m gitd.farm.cli bridge [--interval 300]`, à côté de `daemon` (planner) et de `python3 run.py` (Ghost). Client HTTP : `requests` (déjà dans `pyproject.toml`). Chaque tick :

0. Si `data/farm/STOP` existe (kill-switch machine, `health-canaries.md` §4) ou si `is_blocked(platform)` : rien pour cette plateforme.
1. `GET /api/farm/accounts` → met à jour `paused_until`, `api_mode`, `disclosed`, `niche` des `farm_accounts` liés par `ofmai_account_id` (jamais `created_on`, `health`, `phase_override` : le ledger fait foi). `api_mode` vient donc d'OFMAI : un `accounts api-mode` fait à la main est écrasé ici.
2. Pour chaque compte enabled, non en pause, `can_run(now)` vrai, `api_mode = 0` : `GET /api/farm/queue?channel=device` → pour chaque item non présent dans `farm_publications` : `claim`, téléchargement dans `data/farm/media/<publication_id>.<ext>`, contrôle `sha256`, `adb push` vers `/sdcard/DCIM/Camera/` puis scan média (`am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE`) [à vérifier sur GeeLark : intent accepté, dossier indexé par la galerie d'Instagram et de TikTok] ; statut `staged`.
3. À `scheduled_at` ± `LATE_TOLERANCE_MINUTES` (20 min, `planner.py`) : workflow choisi par `format` (§3.2) — `reel` | `tiktok` → `post_video`, `feed` → `post_photo` (Instagram seulement, E3.6), `story` → `post_story` (Instagram, E3.4) ; un format sans workflow sur cette plateforme → `failed` avec `error = "unsupported_format"`, sans claim ni push. `enqueue_job(job_type="skill_workflow", priority=2, config_json={skill, workflow, params: {handle, caption, aigc_label}, farm_publication: publication_id}, trigger="farm")`, statut `posting`. `params.aigc_label` est recopié **tel quel** de l'item de file (§3.2, figé sur `SocialPublication.aigcLabel`) : le pont ne relit jamais la fiche persona ni `farm_accounts.disclosed` à ce moment-là. Aujourd'hui `PostVideoAction` (`gitd/skills/ofmai_tiktok/workflows/__init__.py`) n'accepte que `handle` et `caption` et tape « AI-generated content » sans condition (l. 91, `adapter._tap_text(xml, "AI-generated content")  # toggle if visible` ; la docstring de la classe, l. 37, dit « mandatory for OFMAI characters (TikTok AIGC policy) ») — à changer pour ne taper le toggle que si `params.aigc_label` est vrai, sinon les 3 personnages du groupe `undeclared` seraient étiquetés IA sur TikTok (C5). Les workflows prennent « l'élément le plus récent de la galerie » : c'est pourquoi un seul média est poussé à la fois par appareil, et jamais pendant qu'un job de publication est `running` sur ce téléphone (un job actif par téléphone, `docs/features/scheduler.md`).
4. Lecture du résultat : `_parse_job_result_data(job_id, log_path=…)` (`gitd/services/_job_helpers.py`) sur la ligne `Data: {…}` imprimée par `gitd/skills/_run_skill.py` ; statut `posted` ou `failed`, événement `posted` / `post_failed` dans `farm_outbox`, suppression du fichier local et du fichier sur l'appareil.
5. Vidage de `farm_outbox` : lots de ≤ 100 lignes `dead = 0` et `next_try_at ≤ now`, `POST /api/farm/events`.
6. Rafraîchit `farm_comment_cache` pour chaque compte sous 5 commentaires disponibles (`GET /api/farm/comments`, `n=10`, par `kind`) ; 6 bis : `farm_targets` pour chaque compte sous 5 portes jouables dont la dernière liste date de plus de 24 h (`GET /api/farm/targets`, `limit=30`, §3.7, `bridge.fetch_targets`) ; une liste vide n'est pas une erreur (niche vide sur cette plateforme).
7. Relevés : pour chaque `farm_publications.status = posted` dont `posted_at + {24, 72, 168} h ± 2 h` tombe dans un créneau de `plan_sessions()` du compte (jamais `QUIET_HOURS`, jamais le jour de repos) et sans ligne `farm_post_metrics` pour cet `at_hours` : `enqueue_job(phone_serial=device_serial, job_type="skill_workflow", priority=3, config_json={skill, workflow: "metrics_pull", params: {handle, post_ref}}, max_duration_s=600, trigger="farm")`, idempotent par `farm_planned.slot_key = "<account_id>:metrics:<publication_id>:<at_hours>"`. Comptes `api_mode` X/Reddit : relevé par `publish-api.ts --metrics` (E8.2), pas par l'appareil.

Vidage immédiat : `FarmSession.signal()` (et tout `stop` / `platform cut` à la main) appelle `bridge.flush_now()` — un `threading.Event` quand le daemon tourne dans le même processus, sinon le fichier `data/farm/FLUSH` que le daemon teste toutes les 5 s — pour que `health_signal` parte dans la minute (`rules.md` R32) ; le tick de 300 s reste le filet.

Le planner passe `params.comments` depuis `farm_comment_cache` (`\n`-séparés) ; les cibles ne passent pas par le planner : `WarmSessionAction` les tire lui-même de `farm_targets` au départ de la session (`skillkit.session_niche`, §3.7), puis ajoute `session_id`, `comments_used`, `played` et `targets_used` au `Data:` et écrit le `session_summary` dans `farm_outbox` en fin d'`execute` (même transaction que la dernière écriture ledger).

Endpoints FastAPI du fork (nouveau routeur `gitd/routers/farm.py`, préfixe `/api/farm`, `dependencies=[Depends(require_admin_token)]`), pour un humain en SSH ou le tableau de bord : `GET /accounts` (= `accounts list` + `budget`), `POST /accounts/{platform}/{handle}/clear-health`, `POST /accounts/{platform}/{handle}/api-mode`, `GET /publications?status=`, `POST /publications/{publication_id}/retry` (remet `failed` → `staged`), `GET /outbox?dead=1`, `POST /sync` (un tick immédiat). Les endpoints Ghost existants restent la voie pour les logs : `GET /api/scheduler/history/{run_id}/result` renvoie le `Data:` parsé (`gitd/routers/scheduler.py`).

## 7. Échecs et reprise

| Panne | Comportement |
|---|---|
| OFMAI injoignable au tick | log, rien n'est modifié localement ; les publications restent `queued` côté OFMAI, les événements s'accumulent dans `farm_outbox` ; nouvel essai au tick suivant |
| `POST /api/farm/events` en 5xx / timeout | `attempts += 1`, `next_try_at = now + min(30 min, 1 min × 2^attempts)` ; jamais de perte, jamais de doublon (`event_id`) |
| `POST /api/farm/events` en 429 ou 503 | même backoff que le 5xx, jamais `dead` (un 429 viendrait du rate limiting de `middleware.ts` si l'exemption E7.2 manquait, ou d'un challenge Cloudflare) |
| `POST /api/farm/events` en 400 / 404 / 409 / 422 | `dead = 1`, `last_error`, alerte Discord ; 401 = secret cassé → alerte Discord, boucle en pause 15 min |
| URL signée expirée au téléchargement (403, TTL 3 h) | nouveau `claim` (URL re-signée) ; si le bail est perdu (`409`), la publication est abandonnée localement |
| Bail de 60 min expiré avant `posting` | la publication redevient `queued` côté OFMAI ; le fork la re-réclame au tick suivant, `attempts` inchangé |
| Job `post_video` `success=False` avec `ambiguous=false` (« Create tab not found », « gallery item not found », « post budget exhausted for this day/week »…) | `post_failed`, OFMAI passe en `failed` ; `POST /publications/{id}/retry` par un humain ou le workflow de publication, **au plus 2 tentatives** au total (relances de **publication** du même fichier, sans rapport avec l'unique relance de rendu du contrôle Gemini — une réplication + une relance au plus, soit 2 générations au total par couple (personnage, post source), jouées côté OFMAI avant la mise en file, `content-pipeline.md` §5.5) ; l'appareil, pas le média, est en cause dans la plupart des cas |
| « Share » tapé mais postcondition fausse, ou job `timeout`/`killed` après le tap | `ambiguous=true` → `needs_human` des deux côtés, Discord ; **jamais de relance automatique** (un doublon coûte plus qu'un post manqué, et `session.record(policy.POST)` a déjà consommé le budget) ; un humain regarde le profil, puis `retry` ou marque `posted` avec le `post_id` via `PATCH /api/farm/publications/{id}` (OFMAI, même secret) |
| Signal santé pendant un `post_video` | le job s'arrête ; `health_signal` part avant `post_failed` ; la publication est `failed`, le compte n'est plus servi par `GET /api/farm/queue` tant que `health != ok` |
| Fichier manquant sur l'appareil (appareil réinitialisé) | `staged` repasse à `claimed` si `adb shell ls` échoue avant l'enqueue ; nouveau push |
| Redémarrage du daemon | reprise sur l'état de `farm_publications` et `farm_outbox` ; rien en mémoire |

## 8. Exemples

```sh
# Mac mini : file de publication d'un compte, puis réclamation
S=$(security find-generic-password -s ofmai-farm-secret -w)
curl -s -H "x-farm-secret: $S" \
  "$FARM_OFMAI_BASE_URL/api/farm/queue?platform=instagram&handle=sierra.cole&limit=3"
curl -s -X POST -H "x-farm-secret: $S" -H "content-type: application/json" \
  -d '{"device_serial":"R58N1234"}' "$FARM_OFMAI_BASE_URL/api/farm/queue/pub_9f/claim"

# Événements retour (lot de deux)
curl -s -X POST -H "x-farm-secret: $S" -H "content-type: application/json" \
  "$FARM_OFMAI_BASE_URL/api/farm/events" -d '{"events":[
  {"event_id":"3f1c…","kind":"posted","at":"2026-09-15T13:52:10-07:00","platform":"instagram",
   "handle":"sierra.cole","payload":{"publication_id":"pub_9f","variant_id":"cv_9f","asset_id":"ca_31","source_post_id":"cmf…","post_id":null,"post_url":null,"channel":"device"}},
  {"event_id":"7a02…","kind":"health_signal","at":"2026-09-15T18:03:44-07:00","platform":"instagram",
   "handle":"sierra.cole","payload":{"signal_kind":"action_blocked","matched":"try again later",
   "new_health":"cooldown","health_until":"2026-09-17T18:03:44","phase_override":"light","session_id":"9c2d0b4e1a77"}}]}'

# Fork (sur le Mac mini, en SSH) : état du pont
curl -s -H "X-Ghost-Admin-Token: $GITD_ADMIN_TOKEN" http://127.0.0.1:5055/api/farm/publications?status=needs_human
curl -s -X POST -H "X-Ghost-Admin-Token: $GITD_ADMIN_TOKEN" http://127.0.0.1:5055/api/farm/sync
```

## 9. Tests attendus

- OFMAI (vitest, obligatoire pour tout fichier de `lib/` ou `app/api/`) : `app/api/farm/events/route.test.ts` — 401 sans secret, `duplicates` sur un `event_id` rejoué, `needs_human` sur `ambiguous=true`, upsert `SocialPostMetric` ; `app/api/farm/queue/route.test.ts` — une variante déjà `posted` sur un compte ne ressort jamais, `channel=api` ne renvoie que les comptes `apiMode` et X/Reddit, une publication Reddit sous 31 jours ou 100 karma ne sort pas, bail expiré → `queued`, URL signée présente et clé brute absente, `source_post_id` présent sur chaque item, `aigc_label` est celui figé sur `SocialPublication.aigcLabel` (un personnage `undeclared` donne `false` ; une bascule de `disclosed` après la mise en file ne change pas l'item déjà en file), `disclosed` et `disclosed_since` repris de la fiche persona ; `app/api/farm/targets/route.test.ts` — la niche servie est celle de la fiche, une cible déjà servie à ce compte ne ressort jamais, `reddit` rend toujours une liste vide, un pool épuisé rend une liste vide sans erreur, deux appels le même jour rendent la même liste ; `middleware.test.ts` — un 61ᵉ appel `/api/farm/queue` en une minute passe.
- Fork (pytest, patron `tests/test_farm_planner.py`) : `tests/test_farm_bridge.py` — outbox et ledger dans le même commit, backoff, `dead` sur 400/404/409/422 seulement (429/503 → backoff), `paused_until` respecté par `tick`, `STOP` respecté, un seul média poussé par appareil, `comments` et `targets` transmis au job (`farm_target_cache` rafraîchi sous 5, liste vide tolérée), workflow choisi par `format` (`unsupported_format` → `failed` sans claim), `params.aigc_label` recopié de l'item de file (jamais de `farm_accounts.disclosed`) et `aigc_label=false` → `PostVideoAction` ne tape pas « AI-generated content », `test_metrics_pull_enqueued_once_per_horizon`, `flush_now` vide l'outbox sans attendre le tick. Lancement : `sh scripts/farm_tests.sh`.

## 10. Hypothèses

- Les deux relectures du 2026-09-14 divergeaient sur l'unité des métriques (`day: 1|3|7` contre `at_hours: 24|72|168`) et sur l'enum des pools (`comment | reply` contre `comment | reply_ai | reply_thanks | reply_question`) : ce fichier retient `atHours` (même unité que `farm_post_metrics`) et l'enum à quatre valeurs (les trois pools de réponses d'E3.2 ont besoin d'être distingués). Les autres fichiers ont été alignés.
- `disclosed` / `disclosed_since` (par personnage) et `source_post_id` (par asset) sont entrés dans les payloads avec les décisions C2 et C5 du 2026-09-14. Côté Prisma : `sourcePostId` sur `ContentAsset` et `SocialPublication` ; `disclosed` et `disclosed_since` vivent dans la fiche persona, pas dans `SocialAccount` (la fiche fait foi, le pont la recopie) ; seul `aigcLabel`, figé à la mise en file, est stocké sur `SocialPublication`. Le JSON du pont reste en snake_case.
