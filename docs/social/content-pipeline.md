# Pipeline de contenu — la banque `ContentAsset`

> **Nature** : reference
> **Statut** : à vérifier
> **À jour au** : 2026-09-14
> **Répond à** : comment OFMAI réplique les posts du radar avec chaque personnage, contrôle le résultat par Gemini, le re-rend, le légende et le stocke pour la ferme
> **Code concerné** : `prisma/schema.prisma` (modèles `ContentAsset` / `ContentAssetVariant` / `ContentSource` à créer ; `ScrapedPost`, `TrackedInfluencer`, `ReplicationBatch`, `BatchItem` existants), `app/api/admin/replication-batch/route.ts`, `app/api/admin/instagram/replicate-image/route.ts`, `app/api/admin/instagram/replicate-video/route.ts`, `lib/ingest/replication-batch.ts`, `lib/ingest/instagram-ingest.ts`, `lib/providers/image-replicate.ts`, `lib/providers/video-replicate.ts`, `lib/providers/gemini.ts`, `lib/providers/seedream.ts`, `lib/providers/wavespeed-video.ts`, `app/api/webhooks/edit-image/route.ts`, `app/api/webhooks/kling-motion/route.ts`, `app/api/webhooks/seedance-edit/route.ts`, `app/api/webhooks/higgsfield-soul-image/route.ts`, `lib/radar/refresh.ts`, `app/api/radar/route.ts`, `lib/billing/pricing.ts`, `lib/storage/s3.ts`, `lib/storage/thumbnails.ts`, `lib/generation/content-policy.ts`, `lib/social/` (à créer)

Ce fragment décrit le côté OFMAI de la chaîne : du post source du radar au fichier prêt à publier. Le radar est la **seule** source de contenu : ni banque de prompts, ni scènes préécrites, ni amorces d'accroche. Ce que la ferme en fait (file de contenu, événements retour) est dans `bridge-ofmai-farm.md` ; les gestes de publication par plateforme dans `publishing.md` ; les personas dans `personas.md` ; les tâches de construction dans `build-plan.md`.

## 1. Les cinq garanties

1. **Le radar est la seule source.** Chaque master est la réplication d'un `ScrapedPost` (carrousel `mediaType = "image"` ou reel `mediaType = "video"`) de la niche du personnage, avec le personnage comme sujet. Les six personnages sont synthétiques ; un post du radar est une référence de scène, de cadrage et de concept, jamais un visage à reproduire.
2. **L'identité est tenue par construction** : les routes de réplication reçoivent les références du personnage (`sfwFaceUrl`, `sfwFrontUrl`, `sfwBackUrl`) ou son Soul ; le contrôle Gemini (§5) vérifie ensuite que c'est bien lui. Jamais « même visage » (`rules.md`).
3. **Une réplication par post source, deux tentatives au plus** : une réplication plus une relance, soit **2 générations au total** par couple (personnage, post source) — `ContentAsset.attempt` vaut 1 puis 2, **jamais 3**. Gemini décide `keep | retry | reject` ; un `retry` relance une seule fois ; après deux échecs le post est `exhausted` pour ce personnage (`ContentSource`, §2) et n'est plus jamais re-sélectionné pour lui. C'est la seule lecture du « 2 tentatives » dans le dossier : `bridge-ofmai-farm.md` et `build-plan.md` la reprennent telle quelle.
4. **Un post source n'est consommé qu'une fois** : `@@unique([characterId, scrapedPostId])` sur `ContentSource`, et exclusion globale de tout post déjà réservé par un autre personnage (§4.1).
5. **En base, des clés S3, jamais des URLs** (`signUrlSafe(key)`, `lib/storage/s3.ts`, TTL `S3_SIGNED_URL_TTL`, défaut `10800` s) ; un fichier par post (`sha256` unique, filigrane sur toute version publique, §6) ; `contentType = "sfw"` est une condition d'entrée pour `instagram` / `tiktok`, pas un filtre d'affichage.

## 2. Schéma Prisma de la banque (référence du dossier)

Trois modèles : la **source consommée** (le verrou : un post du radar par personnage, jamais deux fois), le **master** (sortie brute d'une route de réplication, porteur du contrôle Gemini) et ses **variantes** (un rendu par plateforme, porteur de la légende). Conventions de `.claude/rules/prisma.md` : `cuid()`, `createdAt` + `updatedAt`, camelCase. `ContentType` est l'enum existant (`sfw | nsfw`).

**Ce schéma fait foi.** `build-plan.md` (E6.1) le recopie tel quel — les trois noms de modèles, les noms de champs et les contraintes d'unicité — il ne le réinvente pas ; toute divergence se corrige dans `build-plan.md`, pas ici.

```prisma
/// Sources consommées : une ligne par couple (personnage, post radar), créée
/// AVANT l'appel de réplication et jamais supprimée. Pas de FK vers ScrapedPost :
/// lib/radar/refresh.ts purge les posts après PURGE_AFTER_DAYS = 180 j et la
/// ligne doit survivre (« plus jamais pour ce personnage »).
model ContentSource {
  id              String   @id @default(cuid())
  characterId     String
  scrapedPostId   String                        // ScrapedPost.id
  sourceShortcode String                        // ScrapedPost.shortcode (@unique côté radar) : audit après purge
  attempts        Int      @default(0)          // 0, 1 ou 2 — jamais plus
  status          String   @default("reserved") // reserved | kept | exhausted
  lastAssetId     String?                       // dernier ContentAsset produit pour ce couple
  createdAt       DateTime @default(now())
  updatedAt       DateTime @updatedAt

  character AICharacter @relation(fields: [characterId], references: [id], onDelete: Cascade)

  @@unique([characterId, scrapedPostId]) // un post consommé ne l'est plus jamais par le même personnage
  @@index([scrapedPostId])               // exclusion globale : « déjà pris par un autre personnage »
  @@index([characterId, status])
}

model ContentAsset {
  id              String      @id @default(cuid())
  characterId     String
  sourcePostId    String               // ScrapedPost.id répliqué — jamais null : le radar est la seule source
  attempt         Int         @default(1) // 1 ou 2 : rang de la tentative pour ce couple (personnage, post)
  generationId    String?     @unique  // Generation renvoyée par la route de réplication (parent pour une vidéo)
  kind            String               // "image" | "video" = ScrapedPost.mediaType
  contentType     ContentType          // toujours "sfw" en V1 : les routes de réplication ne produisent que du SFW (§4.2)
  replicateMode   String               // "faithful" | "style" | "adapt" (§4.2)
  masterKey       String?              // clé S3 bucket privé = Generation.imageUrl / videoUrl ; null tant que le webhook n'a pas fini
  durationSeconds Float?
  sourcePrompt    String?     @db.Text // Generation.prompt écrit par la route (Grok ou Gemini) : audit et légende
  phash           String?              // 64 bits hex du master (frame à 0,5 s pour une vidéo) — anti-doublon de rendu, §5.6
  qaDecision      String?              // keep | retry | reject — décision recalculée par le code depuis qaJson (§5.5)
  qaScore         Float?               // overall_score 0-100 renvoyé par Gemini
  qaJson          Json?                // réponse Gemini complète (§5.4)
  qaDuplicateOf   String?              // id du ContentAsset le plus proche sous le seuil de Hamming
  qaStatus        String      @default("pending")   // pending | passed | rejected
  qaReason        String?              // engine_failed | identity | anatomy | motion | render | duplicate | compliance
  status          String      @default("candidate") // candidate | kept | rejected | retired
  createdAt       DateTime    @default(now())
  updatedAt       DateTime    @updatedAt

  character AICharacter          @relation(fields: [characterId], references: [id], onDelete: Cascade)
  variants  ContentAssetVariant[]

  @@unique([characterId, sourcePostId, attempt]) // deux tentatives au plus, jamais deux assets pour la même
  @@index([characterId, status, createdAt(sort: Desc)])
  @@index([sourcePostId])
}

model ContentAssetVariant {
  id               String    @id @default(cuid())
  assetId          String
  platform         String    // "instagram" | "tiktok" | "x" | "reddit" ("telegram" réservé à M2)
  format           String    // "reel" | "feed" | "story" | "tiktok" | "tweet" | "reddit_post"
  width            Int
  height           Int
  durationSeconds  Float?
  s3Key            String    // social/<characterId>/variants/<platform>/<variantId>.<ext>
  sha256           String    @unique // hash du fichier rendu : jamais deux posts avec le même fichier
  watermarked      Boolean   @default(true)
  caption          String    @db.Text // ASCII pur si publication sur l'appareil (§7)
  hashtags         String[]  @default([])
  compliance       String    @default("pending") // pending | passed | failed
  complianceReason String?
  status           String    @default("rendering") // rendering | ready | retired — l'usage vit sur SocialPublication
  createdAt        DateTime  @default(now())
  updatedAt        DateTime  @updatedAt

  asset ContentAsset @relation(fields: [assetId], references: [id], onDelete: Cascade)

  @@unique([assetId, platform])
  @@index([platform, status, createdAt])
}
```

Ajouter `contentAssets ContentAsset[]` et `contentSources ContentSource[]` sur `AICharacter`. Aucun champ persona ici : la fiche vit dans `personas.md` (et sa table, si elle est créée, dans `build-plan.md`). Après édition du schéma : `docker exec ofmai-app npx prisma generate && docker exec ofmai-app npx prisma db push --skip-generate && docker restart ofmai-app`.

Cycle de vie : source `reserved → kept | exhausted` (`attempts` passe à 1 puis 2, jamais 3) ; master `candidate → kept | rejected` (Gemini décide, §5) ; variante `rendering → ready` ; `retired` quand un humain retire un contenu. Deux champs voisins à ne pas confondre : `ContentSource.attempts` est le **compteur** de générations dispatchées pour le couple (0, 1 ou 2), `ContentAsset.attempt` le **rang** de la tentative qui a produit cet asset (1 ou 2) — d'où `@@unique([characterId, sourcePostId, attempt])` : une ligne `ContentAsset` par tentative, jamais une ligne mise à jour en place. Il n'existe **ni** champ `sourceStatus` **ni** statut `unusable` : l'état de la source vit sur `ContentSource.status` (`reserved | kept | exhausted`), et le rapport du contrôle Gemini s'appelle `qaJson` (pas `qaReport`). L'**usage** d'une variante (`queued → claimed → posted | failed | needs_human | cancelled`, compte, `postId`, job Ghost) n'est pas ici : il vit sur `SocialPublication` (`bridge-ofmai-farm.md` §5.1), une seule machine d'états par post. Une variante ne se publie qu'une fois par compte (`@@unique([variantId, socialAccountId])` sur `SocialPublication`) et un fichier n'existe qu'une fois (`sha256 @unique`) ; `@@unique([assetId, platform])` garantit un seul rendu par plateforme et par master.

## 3. Arborescence S3

Les masters restent là où les webhooks de réplication les écrivent ; la banque les référence, elle ne les copie pas. Les médias sources sont lus sur le R2 public du radar par `sourceUrlFor()` (`lib/ingest/replication-batch.ts` l. 23-28 : `r2VideoKey` d'abord, puis `s3Key`, puis `cdnMediaUrl`), et chaque route en garde une copie privée.

```
hiddn2 (privé, signUrlSafe à la lecture)
├── instagram-replicate/src/<userId>/<ts>.jpg          copie de l'image source (startImageReplicate, l. 124)
├── instagram-replicate/video-src/<userId>/<ts>.mp4    copie du reel source (startFaithfulReplicate l. 94, startAdaptReplicate l. 362)
├── instagram-replicate/frame/<userId>/<ts>.jpg        1re frame du reel, mode faithful (l. 103)
├── edits/result/<userId>/<generationId>.png           master image — webhook edit-image l. 76 (faithful ; style sans Soul)
├── sfw-images/result/<userId>/<generationId>.png      master image — webhook higgsfield-soul-image l. 68 (style avec Soul prêt)
├── instagram-replicate/video/<userId>/<parentId>.mp4  master vidéo — finalizeReplicatedVideo (faithful et adapt)
└── social/<characterId>/
    ├── variants/<platform>/<variantId>.{jpg,mp4}      rendus par plateforme, filigranés — servis à la ferme signés
    └── qa/<assetId>.png                               frame à 0,5 s pour le phash vidéo, purgeable

R2 public du radar (r2PublicUrl, lib/storage/r2.ts)
└── ScrapedPost.r2VideoKey / r2ImageKeys[]             médias sources — jamais recopiés dans la banque

hiddn2-public (public, Cache-Control immutable 1 an — PUBLIC_CACHE_CONTROL)
└── social/
    ├── watermarks/<characterId>.png                   filigrane du personnage, généré une fois (§6)
    └── <characterId>/preview/<variantId>.webp         aperçus de la page publique (putPublicObject / copyKeyToPublicBucket)
```

`<userId>` est le **compte admin** OFMAI (nathannzenou@gmail.com, `User.type = "admin"`), propriétaire des six `AICharacter`. Les trois points d'entrée de réplication exigent que le personnage appartienne à l'appelant (`char.userId !== userId → 404`, `image-replicate.ts` l. 81, `video-replicate.ts` l. 71 et l. 348) et ne débitent rien quand l'appelant est admin (`isAdmin = user.type === "admin"`, `creditsCharged: 0`, `free: true`). `POST /api/admin/replication-batch` passe par `requireAdmin()` (`lib/core/admin-guard.ts` l. 19-31), qui ne connaît que la session NextAuth : pour un workflow tournant sur le Mac mini sans navigateur, E6.6 ajoute `requireAdminOrInternalKey()` sur le patron `x-internal-key` de `app/api/admin/generate-batch/route.ts` l. 36-41, avec `INTERNAL_API_USER_ID` = l'id du compte admin (`architecture.md` §6).

## 4. Réplication depuis le radar : sélection et routes

### 4.1 Sélection des posts sources

Requête Prisma directe sur `ScrapedPost` (pas `GET /api/radar`, qui trie sur `ourScore` et pagine pour l'écran ; son `buildWhere()`, `app/api/radar/route.ts` l. 32-60, sert de modèle) :

- `niche = <niche du personnage>` (`ScrapedPost.niche`, dénormalisée depuis `TrackedInfluencer.niche`) et `influencer.market = "US"`.
- carrousels : `mediaType = "image"` et `NOT r2ImageKeys isEmpty` ; reels : `mediaType = "video"` et `r2VideoKey ≠ null`. Seuls les posts dont le média est rapatrié sur R2 sont répliquables (`sourceUrlFor()`, §3).
- fenêtre **`postedAt ≥ now − 30 jours`** (`source.window_days: 30` de la fiche persona), élargie à **60 jours** — et à rien de plus — seulement s'il reste moins de **3 × n** candidats dans la fenêtre de 30 j (`source.window_days_max: 60`). Formulation unique du dossier : `personas.md` §1, `build-plan.md` E6.2 et `architecture.md` §3 (étape 1) reprennent celle-ci mot pour mot.
- tri `outlierScore desc, nulls last` (instantané figé à l'import : vues du reel / médiane du compte), `ourScore desc` en second critère.
- **comptes réels ou IA indifféremment** (`TrackedInfluencer.accountType = "ia" | "reelle"`). Préférence, jamais restriction : à score égal à ± 10 %, le post d'un compte `"ia"` passe devant parce qu'il est plus facile à reproduire. (Le brief écrit « ai_native » ; cette valeur est celle de `AICharacter.characterOrigin`, pas un champ du radar.)
- `replicationStatus = "pending"` : `runBatch` passe le post à `"replicated"` après dispatch (`lib/ingest/replication-batch.ts` l. 111-113), c'est déjà un marqueur global d'usage.
- exclusion de tout `scrapedPostId` présent dans `ContentSource`, **quel que soit le personnage** (vérification globale) ; puis, ceinture et bretelles, `@@unique([characterId, scrapedPostId])` refuse l'insertion pour ce personnage.
- reels : `durationSeconds ≤ 15` (au-delà, `seedanceDuration()` tronque à 15 s en `adapt` et le prix `faithful` grimpe linéairement) ; carrousels : seule la couverture `r2ImageKeys[0]` est répliquée, un carrousel = un master [à valider : répliquer les N images].

Ordre d'écriture, dans une transaction : `ContentSource.create({ characterId, scrapedPostId, sourceShortcode, status: "reserved", attempts: 1 })` — l'unicité est le verrou — puis appel de réplication, puis `ContentAsset.create({ sourcePostId, attempt: 1, generationId })`. Un échec de dispatch (`ReplicateError` / `Httpish`) laisse la source en `reserved` avec `attempts: 1` : il compte comme une tentative.

### 4.2 Les routes appelées

Trois points d'entrée, tous asynchrones (route → `Generation` `processing` → webhook → clé S3 → `completed`), tous gratuits pour le compte admin (§3).

**Lot** — `POST /api/admin/replication-batch` (`app/api/admin/replication-batch/route.ts`, `requireAdmin()`) : `{ "postIds": ["<ScrapedPost.id>"], "characterIds": ["<un seul id>"], "mode": "clone" | "inspired", "quality": "standard" | "high", "withVoice": false, "language": null }`. La route exige un personnage `status = "ready"` avec `sfwFaceUrl`, `sfwFrontUrl`, `sfwBackUrl` (l. 79), crée `ReplicationBatch` + un `BatchItem` par post avec un personnage **tiré au hasard** dans le pool (`pickCharacter`, l. 121 — d'où un seul personnage par lot), répond `201 { batchId, totalItems, invalid }` et lance `runBatch(batch.id, admin.userId)` en `after()` (l. 127). `runBatch` (`lib/ingest/replication-batch.ts` l. 34-131) résout la cible par `resolveReplicationTarget(mode, mediaType)` (`lib/ingest/instagram-ingest.ts` l. 71-83) : `clone` → `faithful` (image et vidéo) ; `inspired` → `style` (image) / `adapt` (vidéo). Chaque item est isolé (un échec ne bloque pas le lot), `BatchItem.generationId` est écrit, le lot finit `completed | partial`. Suivi : `GET /api/admin/replication-batch/<id>` renvoie chaque item avec `generationId`, `status` et `previewUrl` signée.

**Unitaire** — `POST /api/admin/instagram/replicate-image` `{ imageUrl, characterId, mode: "faithful" | "style" }` → `startImageReplicate()` (`lib/providers/image-replicate.ts` l. 67) ; `POST /api/admin/instagram/replicate-video` `{ videoUrl, characterId, mode: "faithful" | "adapt", quality, withVoice, language, durationHint }` → `startFaithfulReplicate()` (`lib/providers/video-replicate.ts` l. 66) ou `startAdaptReplicate()` puis `runAdaptPipeline()` en `after()` (l. 339, l. 444). Même moteur que le lot, sans `BatchItem` ni bascule de `replicationStatus` ; c'est la route de la seconde tentative (§5.5), avec l'URL R2 du post en `imageUrl` / `videoUrl`.

| Cible | Fonction et prompt | Moteur (jamais nommé au public) | Sortie |
|---|---|---|---|
| image `faithful` | `startImageReplicate` : `grokService.buildPromptFromReferenceImage(source, physical_profil, "clone")`, repli `buildFaithfulPrompt` ; 3 images = source + face + front | `getEditModel()` → `flux-2-klein-9b-edit` (défaut, `REPLICATE_EDIT_MODEL`), taille `1984x2992` via `editSafeSize` | webhook `edit-image` → `edits/result/…png` |
| image `style` | idem, mode `"inspired"` ; Soul prêt (`soulId` + `soulStatus = "ready"`) → `generateSoulImage` 3:4 1080p, seed aléatoire ; sinon modèle d'édition avec face + front + back | `higgsfield-soul` ou `flux-2-klein-9b-edit` | webhook `higgsfield-soul-image` → `sfw-images/result/…png`, ou `edit-image` |
| vidéo `faithful` | `startFaithfulReplicate` : 1re frame (`extractFirstFrame`) → enfant image `flux-2-klein-9b-edit` (face + front) → `onFrameEditResolved` → `submitKlingMotion` (mouvement du reel source, `keepOriginalSound: true`) | `kwaivgi/kling-v3.0-pro/motion-control` (`lib/providers/wavespeed-video.ts` l. 15) | webhook `kling-motion` → `finalizeReplicatedVideo` → `instagram-replicate/video/…mp4` |
| vidéo `adapt` | `startAdaptReplicate` → `geminiService.buildVideoPrompt` (skill `INFLUENCER_VIDEO_SKILL_SYSTEM`) → `submitSeedanceVideoEdit` (reel source + face/front/back), durée `seedanceDuration()` 4-15 s, `720p` par défaut (l. 140) | `bytedance/seedance-2.0/video-edit` (l. 20) | webhook `seedance-edit` → `finalizeReplicatedVideo` → même clé |

Choix du mode (à valider) : compte `"ia"` → `clone` (la scène est déjà synthétique, la copie fidèle est la plus proche du post qui a marché) ; compte `"reelle"` → `inspired` (scène et cadrage re-décrits puis re-générés : on reproduit un concept, pas des pixels). `withVoice = false` en V1 (aucune voix clonée sur les six). `quality = "standard"` ; `"high"` (25 cr / 5 s) seulement si Gemini rejette pour netteté [à calibrer].

Tout ce qui sort est `contentType = "sfw"` : `classifyContent("flux-2-klein-9b-edit")` et `classifyContent("seedance-2.0")` renvoient `sfw` (`lib/generation/content-classification.ts` l. 14-19), le chemin Soul force `"sfw"`. Il n'y a **pas** de chemin NSFW dans la réplication radar : en V1, X et Reddit reçoivent les mêmes masters SFW re-rendus (§6) ; une banque NSFW est hors périmètre de ce fichier.

### 4.3 Prix (`lib/billing/pricing.ts`)

Constantes `COSTS` : `INSTAGRAM_IMAGE_REPLICATE = 3` cr (l. 25) ; `VIDEO_REPLICATE_FAITHFUL_STD_PER_5S = 15`, `VIDEO_REPLICATE_FAITHFUL_HD_PER_5S = 25`, `VIDEO_REPLICATE_ADAPT_PER_5S = 21` (l. 57-59) ; voix `HOT_SFW_VOICE_CHANGE_POST = 2`. Formule vidéo `calculateVideoReplicateCost({ mode, quality, durationSeconds, withVoice })` = `ceil(per5s × max(0.8, durée/5) + voix)` (l. 462-477) ; la durée est celle du reel source (`probeDurationSeconds`, repli `durationHint`, sinon 5). Pour le compte admin rien n'est débité et rien n'est remboursé sur échec (`failVideoReplicate` ne rembourse que si `creditsCharged > 0`, l. 496-498 ; webhook `edit-image` l. 132-142). Le coût réel est donc le cash fournisseur, pas les crédits.

| Réplication | Crédits (route utilisateur) | Cash (OFMAI `documentation/business/couts-reels.md` §3) |
|---|---|---|
| image `faithful`, ou `style` sans Soul | 3 | 0,016 $ (`flux-2-klein-9b/edit`) |
| image `style` avec Soul | 3 | non documenté [à vérifier] |
| vidéo `faithful` standard, 5 / 10 / 15 s | 15 / 30 / 45 | 0,84 / 1,68 / 2,52 $ (Kling 0,84 $ / 5 s) |
| vidéo `faithful` high, 5 s | 25 | [à vérifier] |
| vidéo `adapt`, 5 / 10 / 15 s | 21 / 42 / 63 | 1,50 / 3,00 / 4,50 $ (video-edit 720p, facturé entrée + sortie) |

## 5. Contrôle qualité par Gemini

Un seul contrôle sémantique, par Gemini, sur chaque master `completed` ; avant lui, deux filtres à 0 $. Les outils de KYC (`lib/kyc/` : comparaison de visages, détection IA, vision « anatomie ») servent à vérifier des utilisateurs, pas des rendus : ils ne sont pas appelés ici.

**Ce §5 porte le contrat du contrôle Gemini** — nom de méthode, signature, system prompt, format de sortie, seuils, période du cron, algorithme de hash. `build-plan.md` (E6.3) s'y aligne ; il ne propose pas d'autre nom ni d'autre format.

### 5.1 Ordre, exécuté par le cron `social-qa` (à créer, `app/api/cron/social-qa/route.ts`, **toutes les 2 min** via `instrumentation.ts` — période unique du dossier)

| # | Contrôle | Où | Résultat |
|---|---|---|---|
| 1 | Échec moteur : `Generation.status = "failed"` (webhooks `edit-image`, `kling-motion`, `seedance-edit`, `higgsfield-soul-image` statut `nsfw` ou `failed`) | lecture de `Generation` | `qaReason = engine_failed`, compte comme une tentative |
| 2 | Doublon de rendu : phash du master à distance de Hamming ≤ 10 d'un `ContentAsset.phash` du personnage sur 90 j [à calibrer] | `lib/social/phash.ts` (à créer, §5.6) | `qaReason = duplicate`, `qaDuplicateOf` |
| 3 | Gemini : même personne, anatomie, mouvement, rendu, décision | `geminiService.reviewGeneratedMedia()` (à créer, §5.2) | `qaDecision`, `qaScore`, `qaJson` |

### 5.2 Client

`lib/providers/gemini.ts` est un client REST minimal de l'API Generative Language : clé `GEMINI_API_KEY` (`apiKey()`, l. 14-18 — déjà en prod, le mode `adapt` en dépend), modèle `GEMINI_MODEL` (défaut `gemini-2.5-flash`, l. 12), objet exporté `geminiService` avec une seule méthode aujourd'hui, `buildVideoPrompt({ videoBuffer, mimeType, systemPrompt, userInstruction })` (l. 86-131) : upload par l'API Files (`uploadVideo`, l. 27), attente `ACTIVE` (`waitActive`, l. 66), `generateContent` avec `systemInstruction` + partie `fileData`, `temperature: 0.4`, texte en sortie. Les deux helpers sont privés au module.

À ajouter dans le même fichier (E6.3) : **`geminiService.reviewGeneratedMedia({ mediaBuffer, mimeType, kind: "image" | "video", referenceImages: Buffer[], characterProfile })`** — c'est le nom et la signature, il n'y en a pas d'autre (pas de `reviewMedia`, pas de `systemPrompt` passé par l'appelant : le system prompt est une **constante** versionnée dans `lib/social/qa-prompt.ts`, §5.3, et le profil du personnage voyage dans `characterProfile`). Même `uploadVideo` / `waitActive` pour une vidéo, `inlineData` base64 pour les images (références puis master), `systemInstruction` = `QA_SYSTEM_PROMPT` (§5.3), `generationConfig: { temperature: 0, responseMimeType: "application/json" }` [à vérifier : `responseSchema` disponible sur le modèle choisi], parse JSON strict, une relance sur JSON invalide. Si Gemini est indisponible, `qaReason = engine_failed` et la tentative est consommée : le contrôle **échoue fermé** (on ne garde jamais un master non contrôlé), à l'inverse de `checkSfwPromptSafety` (§8). Références envoyées : `sfwFaceUrl`, `sfwFrontUrl`, `sfwBackUrl` via `downloadPublicObject`, dans cet ordre ; master via `downloadFromS3(masterKey)`. Le message utilisateur porte `kind`, `physical_profil` et la durée pour une vidéo.

### 5.3 System prompt (constante `QA_SYSTEM_PROMPT` de `lib/social/qa-prompt.ts`, texte complet, envoyé tel quel)

Constant et versionné dans le code : il ne dépend ni du personnage, ni de la plateforme, ni de la tentative. Toute évolution est un changement de fichier, daté, avec re-calibrage des seuils (§5.5).

```text
You are the quality-control reviewer of an AI content pipeline. You receive:
1. One to three REFERENCE images of a synthetic character (face close-up, full-body front, full-body back), always sent first.
2. One CANDIDATE media: an image or a short video generated to show that same character in a new scene.
3. A short text profile of the character (hair, skin tone, build, distinctive marks).

Your job is to decide whether the candidate can be published on the character's social accounts. Answer with ONE JSON object and nothing else: no prose, no markdown fences.

Evaluate, in this order:

A. SAME PERSON. Is the subject of the candidate the same person as the references? Compare the face (eye shape and spacing, nose, lips, jawline, eyebrows), the body morphology (height impression, shoulders, waist-to-hip ratio, bust, limb proportions), skin tone, hair color and texture, and every distinctive mark listed in the profile (freckles, moles, tattoos, piercings, scars). Hairstyle, makeup, clothing, pose and lighting are allowed to differ: a different haircut is fine, a different person is not. If the face is not visible (back shot, cropped), judge on morphology and marks only and lower your confidence. For a video, the subject must stay the same person in every part of the clip.

B. ANATOMY. Look for: wrong number of fingers or toes, fused or extra fingers, hands or feet with impossible joints, extra or missing limbs, limbs of impossible length or bending the wrong way, a second face or a duplicated body part, duplicated or mismatched eyes, misshapen teeth or too many teeth, mirrored or garbled text, an object merging with a hand, clothing merging with skin, floating accessories. Report every issue with its location.

C. MOTION (video only). Look for non-human movement or physics: limbs or hair sliding instead of moving, the face or body morphing between frames, a limb passing through another limb, through clothing or through the body, an outfit that changes color or shape during the clip, background objects that appear, vanish or warp, jitter or frozen frames, mechanical lip or eye movement, a camera move no phone could make. Ignore ordinary compression artifacts. For an image, set "motion" to null.

D. RENDER. Note visible blur, heavy noise, watermarks or logos, text burned into the frame, or a frame that is obviously a screenshot of another platform's interface.

Scoring:
- same_person.confidence: 0-100, how sure you are that it IS the same person. 90 or more means you would swear to it. Below 50 means it is probably someone else.
- severity per section: "none"; "minor" (a viewer scrolling at speed would not notice: a slightly odd knuckle, a hair strand clipping); "moderate" (a careful viewer notices: a sixth finger half hidden, a short morph in one part of the clip); "major" (anyone notices: extra limb, wrong person, outfit change, second face).
- overall_score: 0-100. Start from 100. Subtract 40 if same_person.verdict is "different", 20 if "uncertain". Subtract 5 per minor issue, 15 per moderate issue, 40 per major issue, across anatomy, motion and render. Never go below 0.

Decision:
- "keep": verdict "same" with confidence >= 80, no moderate or major issue anywhere, overall_score >= 75.
- "reject": verdict "different", or confidence < 50, or any major issue. Rejecting means the source scene does not work for this character; it will not be retried.
- "retry": everything else (uncertain identity, moderate issues, overall_score 50-74). Retrying means the same scene will be generated again once.

Rules:
- Be strict on identity and anatomy, lenient on style. A plain but correct image is "keep"; a beautiful image of the wrong person is "reject".
- Never write "same face" in your reasons; write "same person" or "same identity".
- Do not judge attractiveness, clothing choices or taste. Do not flag nudity or suggestiveness: that is checked elsewhere.
- Write reasons as short factual sentences a human can verify in five seconds, and locate each issue ("left hand, bottom right"; "seconds 3-4").
- If the candidate cannot be read (corrupt file, blank frame), set verdict "uncertain", overall_score 0, decision "retry", and say why in summary.
```

### 5.4 Format de sortie

```json
{
  "kind": "image | video",
  "same_person": { "verdict": "same | uncertain | different", "confidence": 0, "face_visible": true, "reasons": ["…"] },
  "anatomy": { "severity": "none | minor | moderate | major", "issues": [{ "what": "…", "where": "…", "severity": "…" }] },
  "motion":  { "severity": "none | minor | moderate | major", "issues": [{ "what": "…", "where": "seconds a-b", "severity": "…" }] },
  "render":  { "severity": "none | minor | moderate | major", "issues": [{ "what": "…", "where": "…", "severity": "…" }] },
  "overall_score": 0,
  "decision": "keep | retry | reject",
  "summary": "one sentence"
}
```

`motion` vaut `null` pour une image. La réponse entière est stockée dans `qaJson` ; `qaScore = overall_score` ; `qaReason` = première section fautive dans l'ordre `identity` (verdict ≠ `same`) → `anatomy` → `motion` → `render`.

**Ce format fait foi** : il n'y a ni champ `score` ni tableau `reasons[]` à la racine — le score est `overall_score`, la phrase de synthèse est `summary`, et chaque section (`same_person`, `anatomy`, `motion`, `render`) porte sa `severity` et ses `issues`. La décision `keep | retry | reject` renvoyée par Gemini est indicative : le code la recalcule (§5.5) et la range dans `qaDecision`.

### 5.5 Seuils et décision (recalculés par le code, `lib/social/qa-decision.ts`, à créer)

Le `decision` de Gemini est indicatif ; le code recalcule depuis les champs et journalise tout désaccord :

- **keep** : `verdict = "same"` **et** `confidence ≥ 80` **et** aucune sévérité `moderate` / `major` **et** `overall_score ≥ 75` → asset `kept`, `qaStatus = passed`, source `kept`.
- **reject** : `verdict = "different"` **ou** `confidence < 50` **ou** une sévérité `major` → asset `rejected`, source `exhausted` sans seconde tentative (la scène ne convient pas à ce personnage).
- **retry** : tout le reste → asset `rejected` ; si `attempts = 1`, source `attempts = 2` et relance par la route unitaire (§4.2), même mode, le lendemain au plus tard — la relance crée une **nouvelle** ligne `ContentAsset` à `attempt = 2` ; si `attempts = 2`, source `exhausted` et **aucune troisième génération n'est jamais dispatchée** pour ce couple.
- `engine_failed` compte comme un `retry` ; `duplicate` compte comme un `reject` (re-générer la même scène redonnerait le même rendu).

Seuils à calibrer sur les 50 premiers masters revus à la main (`build-plan.md`) ; on resserre `confidence` avant de toucher au reste. Les fichiers des masters `rejected` restent 30 j sur S3 puis un cron de purge (patron `app/api/cron/cleanup-scraped-media`).

### 5.6 Hash perceptuel : ne jamais poster deux fois le même rendu

`lib/social/phash.ts` (à créer) : **pHash DCT — un seul algorithme dans tout le dossier, jamais un dHash** — sharp → niveaux de gris 32×32 → DCT 8×8 → 64 bits hex, distance de Hamming, calculé sur le master (image) ou sur la frame à 0,5 s (`extractVideoFrame`, `lib/storage/thumbnails.ts` l. 44, déposée sous `social/<characterId>/qa/<assetId>.png`). sharp 0.34.5 est dans `node_modules` (importé par `lib/storage/thumbnails.ts`) mais absent des `dependencies` de `package.json` : à déclarer (E6.3). Ce n'est pas un contrôle d'identité : son seul rôle est d'empêcher qu'un même rendu, ou un rendu quasi identique (deux réplications du même concept), sorte deux fois sur les comptes d'un personnage. Les variantes d'un même master gardent un `phash` proche par construction (§6) : le contrôle se fait sur les masters, jamais sur les variantes.

Coût : 0 $ pour les étapes 1-2 ; Gemini ≈ 0,002 $ par image et ≈ 0,005 $ par vidéo de 10 s au tarif public de `gemini-2.5-flash` [à vérifier : absent de `documentation/business/couts-reels.md`] ; 0 crédit facturé.

## 6. Re-rendu par plateforme et filigrane

But : un fichier différent par post (`sha256` distinct garanti) et une empreinte perceptuelle légèrement décalée entre variantes d'un même master (recadrage, grain, durée). Le `phash` reste proche par construction — c'est justement ce qui sert au contrôle doublon du §5, calculé sur le **master**, pas sur les variantes.

Outils : `ffmpeg-static` 5.3.0 (`package.json`) pour la vidéo, sharp pour l'image. Le rendu tourne côté OFMAI (webhook ou cron), jamais sur le Mac mini : la ferme reçoit un fichier fini.

| Plateforme | Format | Dimensions | Durée | Conteneur |
|---|---|---|---|---|
| Instagram | reel / story | 1080×1920 (9:16) | 5-15 s | MP4 H.264 + AAC, 30 fps |
| Instagram | feed | 1080×1350 (4:5) | — | JPEG q 88-93 |
| TikTok | tiktok | 1080×1920 (9:16) | 5-15 s | MP4 H.264 ; photos JPEG/WebP (API, `publishing.md`) |
| X | tweet | 1080×1350 ou 720×1280 | ≤ 140 s | JPEG ≤ 5 Mo / MP4 [à vérifier limites X] |
| Reddit | reddit_post | 1080×1350 ou 1080×1920 | ≤ 15 min | JPEG / MP4 [à vérifier limites Reddit] |

Variation par variante, tirée d'un `rng` seedé par `sha256(variantId)` (reproductible, patron `_seed` de `gitd/farm/policy.py`) : recadrage 1-3 % sur un bord, décalage de départ 0,1-0,4 s, grain `noise=alls=4..8`, `eq` luminosité/saturation ±1,5 %, CRF 20-23, EXIF supprimé.

```bash
# vidéo : recadrage + grain + trim + filigrane, sortie 1080×1920
ffmpeg -ss 0.23 -i master.mp4 -i watermark.png -filter_complex \
  "[0:v]crop=iw*0.985:ih*0.985:iw*0.01:ih*0.005,scale=1080:1920:flags=lanczos,\
   noise=alls=6:allf=t,eq=brightness=0.01:saturation=1.012[v];\
   [v][1:v]overlay=W-w-36:H-h-120:format=auto" \
  -t 5.0 -c:v libx264 -crf 22 -preset medium -pix_fmt yuv420p -r 30 -c:a aac -b:a 128k \
  -map_metadata -1 -movflags +faststart variant.mp4
```

Image : `sharp(master).extract(crop).resize(1080, 1350).modulate({ brightness: 1.01, saturation: 1.012 }).composite([{ input: watermark, gravity: "southeast" }]).jpeg({ quality: 91 }).withMetadata(false)`.

Filigrane : un PNG par personnage, dont le texte suit le groupe de divulgation de la fiche persona — **`@<handle> · AI` si `disclosed: true`, `@<handle>` seul si `disclosed: false`**. Un « AI » filigrané sur une non déclarée serait une divulgation et casserait le test 3 sur 6 (`personas.md`, `rules.md` R2). Blanc à 55 % d'opacité, 36 px de marge, généré une fois par sharp depuis un SVG et déposé sur `hiddn2-public/social/watermarks/<characterId>.png` (jamais dans `public/`, règle « aucun média dans le repo »). Le texte est figé à la génération du PNG : si un personnage bascule de groupe (cas prévu par `metrics-attribution.md` §8.3, `disclosed_since` daté), le filigrane est regénéré avant le post suivant. Appliqué à **toutes** les variantes (`watermarked = true`) ; le master reste vierge. Même règle dans `build-plan.md` E6.4 et pour la photo de profil (`account-creation.md`). `drawtext` de ffmpeg n'est pas utilisé : dépend d'une police embarquée dans le binaire statique [à vérifier].

## 7. Légendes

**Qui écrit** : le workflow de contenu côté OFMAI (`growth-content-army.js`, phase « Rendu et légendes », `build-plan.md`) — un agent modèle de langage, un appel par variante, au moment du rendu. La ferme ne rédige rien : elle poste `ContentAssetVariant.caption` et `hashtags` tels quels (`bridge-ofmai-farm.md` §3). Pas de méthode serveur tant que le workflow suffit ; si une route en a besoin, elle s'appelle `grokService.writeSocialCaption()` et vit dans `lib/providers/grok.ts`.

**Avec quoi** (entrée de l'agent, dans cet ordre) :
1. la fiche persona (`personas.md` : `voice`, `tone`, `vocabulary`, `forbidden_words`, `links`, `disclosed`) — la voix vient de la fiche, jamais du prompt image ;
2. la légende du post source, `ScrapedPost.caption` (jointure par `ContentAsset.sourcePostId`) : inspiration d'angle et de ton, **jamais recopiée** — si plus de la moitié des 80 premiers caractères coïncide, l'agent réécrit [à calibrer] ;
3. `ContentAsset.sourcePrompt` (ce que montre l'image ou le clip) ;
4. les règles de la plateforme cible (table ci-dessous) ;
5. la mention IA selon le groupe du personnage (`disclosed`, test 3 sur 6 de `personas.md`) : `true` → « AI » ou `#AI` dans la légende ; `false` → aucune mention, sur aucune des quatre plateformes. Un flair « AI » exigé par un sub Reddit est une divulgation au même titre qu'un `#AI` : il suit la même règle (table ci-dessous). Fanvue, déclaré pour les six, n'est pas alimenté par cette table.

Contraintes lues dans le code de la ferme : `HumanInput.type_text` (`gitd/farm/human.py`, `def type_text` l. 209, `ord(ch) > 127` l. 221) **supprime tout caractère non ASCII** — une légende publiée sur l'appareil (Instagram, TikTok en chauffe) est ASCII pur, sans emoji ni accent ; `PostReelAction` / `PostVideoAction` enregistrent `caption[:40]` dans `farm_actions`. Les chemins API (TikTok en `api_mode`, X, Reddit) acceptent l'Unicode.

| Plateforme | Longueur | Hashtags | Mention IA | Lien |
|---|---|---|---|---|
| Instagram | ≤ 2 200 car. [à vérifier], 1-3 lignes | 3-5 : niche du compte (`farm_accounts.niche`) ; `#AI` si `disclosed` | `#AI` dans la légende et mention en bio si `disclosed`, sinon rien | aucun (link-in-bio, `publishing.md`) |
| TikTok | ≤ 2 200 car. [à vérifier] | 3-4 ; `#AI` si `disclosed` | toggle AIGC + `#AI` si `disclosed`, sinon rien (`publishing.md`) | aucun |
| X | ≤ 280 car. | 0-2 | « AI » dans le texte ou la bio si `disclosed` | Fanvue + mention OFMAI |
| Reddit | titre ≤ 300 car. [à vérifier] | aucun | flair IA seulement si `disclosed` ; un sub dont le flair IA est **obligatoire** n'est jamais `active` pour un personnage `disclosed: false` (`publishing.md` §5) | selon la classification du sub (`publishing.md`) |

**Relecture** : l'agent conformité (§8) relit `caption` + `hashtags` avant `ready` : aucun nom de fournisseur, jamais « même visage », pas d'URL, de prix ni de crédits sur IG/TikTok, `sfw` seulement sur IG/TikTok, mention IA cohérente avec `disclosed`. `failed` → l'agent réécrit (deux essais), puis la variante reste `rendering` et remonte dans le rapport du jour.

**Stockage** : `ContentAssetVariant.caption` + `hashtags` + `compliance = "passed"` → `status = "ready"` → `SocialPublication` (file du pont) ; `GET /api/farm/queue` sert `caption` et `hashtags` avec la clé S3 signée (`bridge-ofmai-farm.md` §3). Règles de forme : jamais deux légendes identiques pour un même personnage sur 30 j (comparaison exacte sur `caption` avant insertion) ; jamais de prix, de « gratuit », ni d'appel à cliquer sur IG/TikTok.

## 8. Agent conformité

Deux étages, exécutés sur la légende et les hashtags (avant `ready`) et sur tout texte de persona publié (bio, commentaires des pools). Les prompts de génération ne passent pas ici : ils sont écrits par Grok ou Gemini à l'intérieur des routes de réplication (§4.2) et ne sont jamais publiés. Une variante `compliance = "failed"` n'atteint jamais la ferme. Module `lib/social/compliance.ts` **à créer**, test `lib/social/compliance.test.ts` sur le patron de `lib/generation/content-policy.test.ts`.

Étage 1, déterministe :
- `checkPromptPolicy(text)` (`lib/generation/content-policy.ts`, `CONTENT_POLICY_BLOCKLIST` EN + FR, exigée par les PSP) → rejet immédiat sur `matched`.
- Fournisseurs : constante `PROVIDER_NAMES` de `lib/social/compliance.ts` (seule source, citée par `rules.md` R10) = `higgsfield`, `seedance`, `seedream`, `wavespeed`, `modal`, `lustify`, `krea`, `grok`, `gemini`, `openai`, `elevenlabs`, `kling`, `flux`, `geelark`, `iproyal`, `ghost`, `nowpayments`, `centrobill`, `bophub`, `manychat`, `didit`, `hive`, `x\.ai`, plus les noms des outils de KYC listés par R10 ; regex construite avec des bornes de mot (`\b(?:…)\b`, insensible à la casse) pour ne pas rejeter « ghosted » ou « modal window » → rejet sur correspondance. Le nom d'un produit OFMAI (« Ultra », « Clone de voix ») est autorisé.
- Clone : `same face|même visage|face ?swap|deepfake` → rejet (le produit est un clone complet : même morphologie, même corps).
- Plateformes SFW : pour `platform ∈ {instagram, tiktok}`, `contentType` doit être `sfw` **et** la regex d'`isExplicitNsfw` (locale à `app/api/generate-sfw-image/route.ts` l. 59, à extraire dans `lib/generation/`) ne doit rien trouver dans la légende.
- Mention IA cohérente avec `disclosed` (§7) : `disclosed = true` → `#AI` ou le mot « AI » obligatoire sur IG/TikTok/X, sinon rejet `no_ai_disclosure` ; `disclosed = false` → toute mention IA est rejetée `unexpected_ai_disclosure`, pour ne pas fausser le test 3 sur 6. Sur Reddit la divulgation passe par le flair du sub et non par le texte : un flair IA obligatoire est une divulgation, donc un sub qui l'exige (`SocialSubreddit.flairId` requis pour le `kind` visé) n'est jamais `active` pour un personnage `disclosed: false` — filtre posé à la classification du sub (`publishing.md` §5), pas ici.
- Pas de nombre de crédits ni d'URL dans une légende IG/TikTok (les liens vivent en bio).

Étage 2, LLM : `grokService.checkSfwPromptSafety(text)` (`lib/providers/grok.ts` l. 332) sur la légende — attention, la fonction **échoue ouverte** (`riskScore: 0`, `reason: "check_unavailable"` sans clé ou en cas d'erreur) : l'étage 1 est le vrai verrou.

## 9. Volumes et coût par asset

**Ce §9 fait foi pour les volumes** : `warming-policy.md` §11 et `infrastructure-geelark-proxies.md` le citent, ils ne recalculent rien. En une phrase : **8 variantes pour 8 posts depuis 3 masters gardés (≈ 4 réplications) par jour et par personnage ; 6 assets = plafond de production, pas une cible.**

Le volume se déduit des caps de `warming-policy.md` §11, pas du brief : par jour et par personnage en cruise, Instagram 1 (appareil) + TikTok 2 + X 3 (`API_POSTS_PER_DAY = {"tiktok": 2, "x": 3, "reddit": 2}`, à coder — E8.3) + Reddit 2 = **8 posts** (+ 1 story Instagram, E3.4). Variantes par master gardé : reel répliqué → les 4 plateformes ; image répliquée → `tiktok` (photo, API), `x`, `reddit`, et `instagram/feed` seulement quand `post_photo` existe (E3.6). Besoin quotidien : **3 masters gardés** — 1 vidéo (4 variantes : IG reel, TikTok, X, Reddit) + 2 images (4 variantes : TikTok 1, X 2, Reddit 1) — soit 8 variantes pour 8 posts ; la story reprend une variante image. Les « 6 assets/jour/personnage » du brief sont un **plafond de production** (2 vidéos + 4 images : marge pour les rejets de conformité, les stories et les remplacements), pas une cible. Stock de sécurité par plateforme = **3 × cap de `warming-policy.md` §11** : Instagram 3, TikTok 6, X 9, Reddit 6 variantes `ready` par personnage ; le workflow quotidien ne produit que ce qui manque pour revenir à ce stock. Tant qu'E3.6 n'est pas livré, le programmateur ne rend pas de variante `instagram/feed`.

Tentatives : avec une réplication par post source et au plus une relance (§5.5 : 2 générations au total, jamais 3), et une probabilité de `keep` à la première tentative `p₁` [à calibrer ; hypothèse 70 %], un master gardé coûte en moyenne **≈ 1,3 réplication** et **≈ 1,1 post source** (les `reject` et les doubles échecs épuisent la source). Trois masters par jour = ≈ 4 réplications (1,3 vidéo + 2,6 images) et ≈ 3,3 posts sources, soit **≈ 100 posts sources par personnage et par mois** : la niche doit en fournir autant sur la fenêtre de 30 j du §4.1, sinon elle s'élargit à 60 j (chiffres du brief : 17 032 posts pour 108 niches en prod, ≈ 158 par niche toutes dates confondues [à vérifier en prod, niche par niche, avant de figer les six]).

Coûts cash (OFMAI `documentation/business/couts-reels.md` §3 ; §4.3 ci-dessus ; Gemini §5.6), par master **gardé** (× 1,3 réplication, × 1,3 contrôle Gemini) :

| Master gardé | Réplication × 1,3 | Gemini × 1,3 | Total cash | Crédits (route utilisateur ; 0 en admin) |
|---|---|---|---|---|
| Image, `faithful` ou `style` sans Soul | 1,3 × 0,016 $ | 0,003 $ | **≈ 0,02 $** | 1,3 × 3 ≈ 4 cr |
| Image, `style` avec Soul | [à vérifier] | 0,003 $ | [à vérifier] | ≈ 4 cr |
| Vidéo `faithful` standard, reel de 5 s / 10 s | 1,3 × 0,84 / 1,68 $ | 0,006 $ | **≈ 1,10 / 2,19 $** | ≈ 20 / 39 cr |
| Vidéo `adapt`, reel de 5 s / 10 s | 1,3 × 1,50 / 3,00 $ | 0,006 $ | **≈ 1,96 / 3,91 $** | ≈ 27 / 55 cr |
| Re-rendu + filigrane + légende | — | — | ≈ 0 $ (sharp et ffmpeg locaux ; la légende est écrite par le modèle du workflow, non compté ici) | 0 |

Par personnage et par jour, au besoin réel (1 vidéo + 2 images gardées) : de **≈ 1,15 $** (reels de 5 s, `clone`) à **≈ 3,95 $** (reels de 10 s, `adapt`) ; pour 6 personnages **≈ 7 à 24 $/jour, ≈ 210 à 720 $/mois**. Au plafond du brief (2 vidéos + 4 images) : ≈ 2,3 à 7,9 $ par personnage, ≈ 14 à 47 $/jour, ≈ 420 à 1 400 $/mois. Plus de 95 % du cash est de la vidéo : les deux leviers sont la **durée du reel source** (préférer les reels ≤ 10 s à score égal, §4.1) et la part de `clone` (0,84 $ / 5 s) contre `adapt` (1,50 $ / 5 s) ; le nombre de tentatives n'en est pas un, il est borné à 2.

Les phases de chauffe consomment moins : `posts_per_week` vaut 0 en CONSUME et LIGHT, 3 en NETWORK, 7 en CRUISE, avec un cap POST de 1/jour (`gitd/farm/policy.py` l. 65-68, 140) — l'écart avec le volume de cruise est tranché dans `warming-policy.md` §11. La banque produit donc à plein régime seulement pour les comptes en cruise ; avant, le stock de 3 × cap par plateforme suffit.

## 10. Le programmateur : choix des posts sources

Une seule source, le radar (`TrackedInfluencer` + `ScrapedPost` ; 2 898 comptes, 108 niches, 17 032 posts en prod d'après le brief [à vérifier]). Le programmateur est l'agent du workflow quotidien (`POST /api/admin/social/plan`, E6.6), déterministe par `rng` seedé `sha256(characterId, date)` — deux appels le même jour donnent le même tirage :

1. Lire le déficit de stock par plateforme (§9) → nombre de masters vidéo et image à produire aujourd'hui (≤ 6), moins les secondes tentatives déjà dues (§5.5).
2. Requête du §4.1 sur la niche du personnage, deux listes (reels, carrousels), 20 candidats chacune, triées `outlierScore desc`, préférence `accountType = "ia"` à score égal, préférence reels ≤ 10 s à score égal (§9). Le filtre « décollage » de l'écran radar (`authorFollowers < BREAKOUT_MAX_FOLLOWERS = 50 000` et `ourScore > BREAKOUT_MIN_OUTLIER = 3`, `lib/radar/refresh.ts` l. 14-15) est un second tri, pas un filtre : un post d'un gros compte qui a explosé reste une bonne scène.
3. Retirer : tout post déjà dans `ContentSource` (tous personnages), `replicationStatus ≠ "pending"`, tout post du même `influencerId` qu'un post consommé par ce personnage depuis 14 j (on ne copie pas un seul compte) [à valider], reels > 15 s.
4. Prendre les N premiers de chaque liste ; pour chacun, `ContentSource.create` (réservation, §4.1) puis `POST /api/admin/replication-batch` avec `characterIds: [id]` et `postIds` — **un lot par mode** (`clone` pour les posts de comptes `"ia"`, `inspired` pour les comptes `"reelle"`, §4.2), parce que `mode` est global au lot.
5. Écrire les `ContentAsset` (`sourcePostId`, `attempt: 1`, `replicateMode`, `generationId` lu dans `GET /api/admin/replication-batch/<id>`), statut `candidate` ; le cron `social-qa` (§5) prend le relais.
6. Les secondes tentatives passent par les routes unitaires (§4.2) avec l'URL R2 du post (`r2PublicUrl(r2VideoKey)` ou `r2ImageKeys[0]`), le lendemain au plus tard, `attempt: 2`.

## 11. Ce qui n'existe pas encore

Ce qui existe : les trois routes de réplication et leur moteur (`runBatch`, `startImageReplicate`, `startFaithfulReplicate`, `startAdaptReplicate`), les quatre webhooks de sortie, le marqueur global `ScrapedPost.replicationStatus`, le radar et ses scores, le client Gemini (`geminiService.buildVideoPrompt`, clé `GEMINI_API_KEY`), la gratuité admin (`user.type === "admin"`).

Ce qui n'existe pas : aucun modèle `ContentSource`, `ContentAsset`, `ContentAssetVariant` ; aucun `lib/social/` (`phash`, `qa-prompt`, `qa-decision`, compliance, watermark) ; aucune route `app/api/admin/social/*` ni cron `social-qa` ; aucun hachage perceptuel dans le code (`grep phash|perceptual|dhash` sur `lib/` et `app/` : rien) ; aucune méthode `geminiService.reviewGeneratedMedia` (le client ne sait que produire un prompt texte à partir d'une vidéo, et ses helpers d'upload sont privés) ; aucun filigrane ; `requireAdmin()` ne connaît que la session NextAuth (E6.6) ; `POST /api/admin/replication-batch` tire le personnage au hasard dans le pool et applique un `mode` à tout le lot (d'où un personnage et un mode par lot, §10) ; aucun champ `disclosed`. Les six personnages n'existent pas encore : chacun doit être `status = "ready"` sur le compte admin avec `sfwFaceUrl`, `sfwFrontUrl`, `sfwBackUrl` et `physical_profil` (condition des routes de réplication), et un Soul `ready` pour le mode `style` (`personas.md`, `build-plan.md`, epic personnages). Les tâches, l'ordre et les tests sont dans `build-plan.md` ; le contrat de livraison à la ferme dans `bridge-ofmai-farm.md`.
