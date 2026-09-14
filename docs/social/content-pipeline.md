# Pipeline de contenu — la banque `ContentAsset`

> **Nature** : reference
> **Statut** : à vérifier
> **À jour au** : 2026-09-14
> **Répond à** : comment OFMAI produit, contrôle, re-rend, légende et stocke les médias que la ferme publie pour chaque personnage
> **Code concerné** : `prisma/schema.prisma` (modèles `ContentAsset` / `ContentAssetVariant` à créer), `app/api/admin/generate-batch/route.ts`, `app/api/generate-sfw-image/route.ts`, `app/api/hot-sfw/generate/route.ts`, `app/api/generate-image/route.ts`, `app/api/webhooks/higgsfield-soul-image/route.ts`, `app/api/webhooks/seedance/route.ts`, `lib/providers/higgsfield.ts`, `lib/providers/seedance.ts`, `lib/providers/grok.ts`, `lib/kyc/rekognition.ts`, `lib/storage/s3.ts`, `lib/storage/thumbnails.ts`, `lib/generation/content-policy.ts`, `lib/billing/pricing.ts`, `lib/radar/refresh.ts`, `lib/hot-sfw/presets.ts`, `lib/social/` (à créer)

Ce fragment décrit le côté OFMAI de la chaîne : de l'idée au fichier prêt à publier. Ce que la ferme en fait (file de contenu, événements retour) est dans `bridge-ofmai-farm.md` ; les gestes de publication par plateforme dans `publishing.md` ; les personas dans `personas.md` ; les tâches de construction dans `build-plan.md`.

## 1. Les cinq garanties

1. **L'identité est tenue par construction** : chaque média sort d'un moteur qui reçoit le Soul (SFW) ou le LoRA (NSFW) du personnage. Jamais de face-swap, jamais de « même visage » (`rules.md`).
2. **En base, des clés S3, jamais des URLs** ; lecture par `signUrlSafe(key)` (`lib/storage/s3.ts`, TTL `S3_SIGNED_URL_TTL`, défaut `10800` s).
3. **3 générés pour 1 gardé** : chaque slot de production produit 3 candidats, la QA en garde au plus 1.
4. **Un fichier par post** : une variante re-rendue par plateforme, `sha256` unique, filigrane sur toute version publique.
5. **Rien de NSFW ne rejoint une variante `instagram` ou `tiktok`** : `ContentAsset.contentType = "sfw"` est une condition d'entrée, pas un filtre d'affichage.

## 2. Schéma Prisma proposé

Deux modèles : le **master** (sortie brute d'un moteur, porteur de la QA) et ses **variantes** (un rendu par plateforme, porteur de la légende et de l'usage). Conventions de `.claude/rules/prisma.md` : `cuid()`, `createdAt` + `updatedAt`, camelCase. `ContentType` est l'enum existant (`sfw | nsfw`).

```prisma
model ContentAsset {
  id              String      @id @default(cuid())
  characterId     String
  generationId    String?     @unique  // Generation d'origine ; null si master importé à la main
  kind            String               // "image" | "video"
  contentType     ContentType          // sfw → instagram/tiktok ; nsfw → x/reddit, jamais l'inverse
  masterKey       String               // clé S3 bucket privé (= Generation.imageUrl / videoUrl)
  durationSeconds Float?
  sourceKind      String               // "foxy" | "radar" | "hook" | "preset" | "manual"
  sourceRef       String?              // id Foxy, ScrapedPost.id, id de preset, variable de hook
  sourcePrompt    String      @db.Text // prompt réellement envoyé au moteur (après remix identité)
  hook            String?              // ROTATION_180 | REFLET_MIROIR | VUE_ZENITHALE | ZOOM_PHYSIQUE
  batchId         String               // sha256(characterId, date, slot) : les 3 candidats d'un slot
  phash           String?              // 64 bits hex du master (frame à 0,5 s pour une vidéo)
  qaIdentity      Float?               // similarité Rekognition 0-100
  qaAnatomy       Float?               // 0-1, vision
  qaDuplicateOf   String?              // id du ContentAsset le plus proche sous le seuil de Hamming
  qaStatus        String      @default("pending")   // pending | passed | rejected
  qaReason        String?              // identity | anatomy | duplicate | engine_refused | compliance
  status          String      @default("candidate") // candidate | kept | rejected | retired
  createdAt       DateTime    @default(now())
  updatedAt       DateTime    @updatedAt

  character AICharacter          @relation(fields: [characterId], references: [id], onDelete: Cascade)
  variants  ContentAssetVariant[]

  @@index([characterId, status, createdAt(sort: Desc)])
  @@index([characterId, sourceKind, sourceRef])
  @@index([batchId])
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

Ajouter `contentAssets ContentAsset[]` sur `AICharacter`. Aucun champ persona ici : la fiche vit dans `personas.md` (et sa table, si elle est créée, dans `build-plan.md`). Après édition du schéma : `docker exec ofmai-app npx prisma generate && docker exec ofmai-app npx prisma db push --skip-generate && docker restart ofmai-app`.

Cycle de vie : master `candidate → kept | rejected` (la QA décide) ; variante `rendering → ready` ; `retired` dans les deux cas quand un humain retire un contenu. L'**usage** d'une variante (`queued → claimed → posted | failed | needs_human | cancelled`, compte, `postId`, job Ghost) n'est pas ici : il vit sur `SocialPublication` (`bridge-ofmai-farm.md` §5.1), une seule machine d'états par post. Une variante ne se publie qu'une fois par compte (`@@unique([variantId, socialAccountId])` sur `SocialPublication`) et un fichier n'existe qu'une fois (`sha256 @unique`) ; `@@unique([assetId, platform])` garantit un seul rendu par plateforme et par master.

## 3. Arborescence S3

Les masters restent là où les webhooks existants les écrivent ; la banque les référence, elle ne les copie pas.

```
hiddn2 (privé, signUrlSafe à la lecture)
├── sfw-images/result/<userId>/<generationId>.png   master image SFW — webhook higgsfield-soul-image l. 68
├── hot-sfw/raw/<userId>/<generationId>.mp4         master clip SFW — webhook seedance l. 100, toujours conservé
├── hot-sfw/final/<userId>/<generationId>.mp4       seulement si voice change (l. 202) — pas utilisé ici
├── <clé du webhook image-generation>               master image NSFW [à vérifier : dérivée de l'URL fournisseur, l. 157]
└── social/<characterId>/
    ├── variants/<platform>/<variantId>.{jpg,mp4}   rendus par plateforme, filigranés — servis à la ferme signés
    └── qa/<assetId>.png                            frame extraite pour la QA vidéo, purgeable

hiddn2-public (public, Cache-Control immutable 1 an — PUBLIC_CACHE_CONTROL)
└── social/
    ├── watermarks/<characterId>.png                filigrane du personnage, généré une fois (§6)
    └── <characterId>/preview/<variantId>.webp      aperçus de la page publique (putPublicObject / copyKeyToPublicBucket)
```

`<userId>` est l'utilisateur OFMAI **opérateur** = `INTERNAL_API_USER_ID` (env prod), propriétaire des 6 `AICharacter` : c'est l'utilisateur que prend `app/api/admin/generate-batch/route.ts` (l. 34-41) quand l'appel porte l'en-tête `x-internal-key = INTERNAL_API_KEY` — le seul moyen pour un workflow tournant sur le Mac mini, sans navigateur ni cookie NextAuth, d'appeler les routes admin (`architecture.md` §6, E6.6). Les routes utilisateur vérifient la propriété (`where: { id: characterId, userId: session.user.id }`), le batch admin non (`findUnique({ where: { id } })`, l. 84).

## 4. Génération : routes et moteurs

Trois chemins, tous asynchrones (route → `Generation` en `processing` → webhook → clé S3 → `completed`).

### 4.1 Images SFW (Instagram, TikTok) — Soul

Route de production : `POST /api/admin/generate-batch` (`requireAdmin()`, aucun crédit débité, `unitCost: 0`). Exige `soulId` et `soulStatus === "ready"` sinon 400 `has no ready Soul`. Chaque prompt passe par `grokService.remixSoulPrompt(prompt, physical_profil)` (ne réécrit que l'identité du sujet, le Soul tient le visage) puis `generateSoulImage()` (`lib/providers/higgsfield.ts`), modèle `higgsfield-soul`, `metadata.batch_source = "admin_mass_gen"`.

```json
POST /api/admin/generate-batch
{ "contentType": "sfw", "characterIds": ["<AICharacter.id>"], "resolution": "1080p",
  "prompts": [{ "prompt": "<prompt Foxy ou radar>", "tags": ["Daily Life"], "style_id": null }] }
```

Limites lues dans la route : ratio **fixé à `2:3`** (`toSoulAspectRatio("2:3")`, l. 78) ; résolution `1080p` par défaut (`720p` seulement si demandé) ; prompts mélangés (Fisher-Yates) ; `style_id` = `GENERAL_STYLE_ID` (`3db34ab5-3439-4317-9e03-08dc30852e69`) → `enhancePrompt: false`. Pour du 9:16 ou 4:5, la route utilisateur `POST /api/generate-sfw-image` accepte `aspect ∈ {post 1:1, story 9:16, portrait 4:5, landscape 16:9}` (`ASPECT_RATIO_MAP`, `lib/providers/gpt-image-edit.ts`), `quantity ≤ 5`, `resolution`, `soulStyleKey`, `enhance` — mais débite `SFW_IMAGE_SOUL_1080 = 2` cr (`SFW_IMAGE_SOUL_720 = 1`). Décision : ajouter `aspect` au batch admin plutôt que de payer en crédits (`build-plan.md`). Repli GPT (`gpt-image-2-edit`) exclu : 68,2 % d'échec sur 90 j (`documentation/generation/models-inventory.csv`).

Webhook `app/api/webhooks/higgsfield-soul-image` : statut `nsfw` du fournisseur → génération `failed` sans remboursement (l. 103-112). Ces refus comptent dans les 3 candidats.

### 4.2 Clips SFW — vidéo Hot SFW

Route : `POST /api/hot-sfw/generate` (`hasPremiumAccess` requis, `userConcept` requis, preset optionnel). Modèle `seedance-2.0`, `submitSeedanceT2V()` avec jusqu'à 9 références (`sfwFaceUrl`, `sfwFrontUrl`, `sfwBackUrl` recopiées sous `hot-sfw/ref/<userId>/<ts>_<i>.png`). Durée clampée 4-15 s (`seedanceDuration()`), ratio `9:16` par défaut, résolution **`720p`** pour nous (défaut route `480p` ; règle mémoire : rushes en 720p, une seule résolution par vidéo).

```json
POST /api/hot-sfw/generate
{ "characterId": "<id>", "presetId": "mirror_selfie_ootd", "userConcept": "<scène + hook>",
  "resolution": "720p", "durationSeconds": 5, "aspectRatio": "9:16" }
```

Coût crédits : `calculateHotSfwVideoCost` = `ceil(15 × mult × max(0.8, durée/5))`, mult 480p ×1, 720p ×2, 1080p ×5 → **30 cr** (5 s 720p), 60 cr (10 s). La route débite le compte opérateur : soit il reçoit un solde bonus, soit le dispatch est factorisé dans `lib/hot-sfw/` pour un appel admin sans crédit (`build-plan.md`). Sortie : `hot-sfw/raw/<userId>/<genId>.mp4` (voix désactivée : pas de `final/`). Les 9 presets `category: "social"` de `lib/hot-sfw/presets.ts` sont utilisables tels quels : `mirror_selfie_ootd`, `bikini_pool_day`, `workout_gym_thirst_trap`, `walk_away_back_shot`, `mirror_butt_check`, `outfit_transition`, `grwm_hot_final`, `halloween_cosplay`, `hotel_balcony_sunset`.

### 4.3 Images NSFW (X, Reddit) — LoRA

Batch admin : `POST /api/admin/generate-batch` avec `{ "contentType": "nsfw", "characterIds": [...], "prompts": [{ "prompt", "tags" }] }` → modèle `image-nsfw` (`STANDARD_IMAGE_MODEL`), `submitLustifyImage()`, `metadata.mode = "admin-batch"`. Route utilisateur : `POST /api/generate-image` (`quantity ≤ 4`, `IMAGE_BASE = 1` cr, 403 sur host SFW, prompt vide refusé). Ultra (`image-nsfw-krea2`, 5 cr) seulement si `isUltraReady(character)` ; pas nécessaire pour un post social. Pas de clip NSFW en V1 : WAN est écarté (`couts-reels.md` §7) et le seul chemin vidéo est `seedance-2.0`, classé `sfw`. X et Reddit reçoivent les images NSFW et une re-coupe des clips SFW.

## 5. Contrôle qualité et « 3 pour 1 »

Une passe par candidat, dans cet ordre (le premier échec suffit, on ne paie pas la suite) :

| Contrôle | Fonction | Entrée | Seuil | Coût |
|---|---|---|---|---|
| Refus moteur | webhook `higgsfield-soul-image` statut `nsfw` / `failed` | — | rejet `engine_refused` | 0 $ |
| Doublon | `lib/social/phash.ts` **à créer** (sharp 0.34.5, présent dans `node_modules`, importé par `lib/storage/thumbnails.ts`, absent des `dependencies` de `package.json` : à déclarer, E6.3) | master ou frame | distance de Hamming ≤ 10 contre les `phash` du personnage sur 90 j [à calibrer] | 0 $ |
| Identité | `compareFaces(selfie, target, threshold)` (`lib/kyc/rekognition.ts`) | source = `sfwFaceUrl` via `downloadPublicObject`, cible = master via `downloadFromS3` ; vidéo : `extractVideoFrame(video)` (`lib/storage/thumbnails.ts`, frame à 0,5 s) | `FACE_MATCH_THRESHOLD = 90` est calibré pour le KYC ; proposer 85 pour un master généré [à calibrer sur 50 images validées à la main] | 0,001 $ |
| Anatomie | `grokService.checkGeneratedAnatomy(imageUrl)` **à créer** dans `lib/providers/grok.ts`, sur le patron de `generateCharacterPhysicalProfile(imageUrls)` (vision) — aucune fonction dédiée n'existe aujourd'hui | image ou frame | score ≥ 0,8 ; mains, doigts, membres, texte incrusté, second visage | ≈ 0,002 $ |

`qaReason` prend la première cause d'échec. Sur les candidats `passed`, on garde celui de plus forte `qaIdentity` ; les autres passent `rejected` (le fichier S3 reste 30 j puis cron de purge, patron `app/api/cron/cleanup-scraped-media`). `detectAiGenerated` (`lib/kyc/hive.ts`) n'a pas sa place ici : on sait déjà que c'est de l'IA.

Chiffres de `couts-reels.md` §9 : 0,001 $ identité, 0 $ doublon, 0,002 $ anatomie ; 0 crédit facturé.

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

Filigrane : un PNG par personnage, `@<handle>` + « AI », blanc à 55 % d'opacité, 36 px de marge, généré une fois par sharp depuis un SVG et déposé sur `hiddn2-public/social/watermarks/<characterId>.png` (jamais dans `public/`, règle « aucun média dans le repo »). Appliqué à **toutes** les variantes (`watermarked = true`) ; le master reste vierge. `drawtext` de ffmpeg n'est pas utilisé : dépend d'une police embarquée dans le binaire statique [à vérifier].

## 7. Légendes par persona et par plateforme

La légende est produite au moment du rendu, une par variante, par l'agent du workflow quotidien (`build-plan.md`, `growth-content-army.js`) à partir de la fiche persona (`personas.md` : voix, ton, interdits, liens) et de `sourcePrompt`. Pas de nouvelle méthode Grok tant que le workflow suffit ; si une route serveur en a besoin, elle s'appelle `grokService.writeSocialCaption()` et vit dans `lib/providers/grok.ts`.

Contraintes lues dans le code de la ferme : `HumanInput.type_text` (`gitd/farm/human.py`, `def type_text` l. 209, `ord(ch) > 127` l. 221) **supprime tout caractère non ASCII** — une légende publiée sur l'appareil (Instagram, TikTok en chauffe) est ASCII pur, sans emoji ni accent ; `PostReelAction` / `PostVideoAction` enregistrent `caption[:40]` dans `farm_actions`. Les chemins API (TikTok en `api_mode`, X, Reddit) acceptent l'Unicode.

| Plateforme | Longueur | Hashtags | Divulgation IA | Lien |
|---|---|---|---|---|
| Instagram | ≤ 2 200 car. [à vérifier], 1-3 lignes | 3-5 : `hashtags` = niche du compte (`farm_accounts.niche`) + `#AI` | `#AI` dans la légende, mention en bio | aucun (link-in-bio, `publishing.md`) |
| TikTok | ≤ 2 200 car. [à vérifier] | 3-4 + `#AI` | toggle AIGC (obligatoire) + `#AI` | aucun |
| X | ≤ 280 car. | 0-2 | « AI » dans le texte ou la bio | Fanvue + mention OFMAI |
| Reddit | titre ≤ 300 car. [à vérifier] | aucun | tag/flair du sub si exigé | selon la classification du sub (`publishing.md`) |

Règles de forme : jamais deux légendes identiques pour un même personnage sur 30 j (comparaison exacte sur `caption` avant insertion) ; jamais de prix, de « gratuit », ni d'appel à cliquer sur IG/TikTok ; la voix vient de la fiche, pas du prompt image.

## 8. Agent conformité

Deux étages, exécutés sur le prompt (avant génération) puis sur la légende et les hashtags (avant `ready`). Une variante `compliance = "failed"` n'atteint jamais la ferme. Module `lib/social/compliance.ts` **à créer**, test `lib/social/compliance.test.ts` sur le patron de `lib/generation/content-policy.test.ts`.

Étage 1, déterministe :
- `checkPromptPolicy(text)` (`lib/generation/content-policy.ts`, `CONTENT_POLICY_BLOCKLIST` EN + FR, exigée par les PSP) → rejet immédiat sur `matched`.
- Fournisseurs : constante `PROVIDER_NAMES` de `lib/social/compliance.ts` (seule source, citée par `rules.md` R11) = `higgsfield`, `seedance`, `seedream`, `wavespeed`, `modal`, `lustify`, `krea`, `grok`, `gemini`, `openai`, `elevenlabs`, `kling`, `geelark`, `iproyal`, `ghost`, `nowpayments`, `centrobill`, `bophub`, `manychat`, `rekognition`, `didit`, `hive`, `x\.ai` ; regex construite avec des bornes de mot (`\b(?:…)\b`, insensible à la casse) pour ne pas rejeter « ghosted » ou « modal window » → rejet sur correspondance. Le nom d'un produit OFMAI (« Ultra », « Clone de voix ») est autorisé.
- Clone : `same face|même visage|face ?swap|deepfake|face of|looks like <prénom réel>` → rejet.
- Plateformes SFW : pour `platform ∈ {instagram, tiktok}`, `contentType` doit être `sfw` **et** la regex d'`isExplicitNsfw` (locale à `app/api/generate-sfw-image/route.ts` l. 59, à extraire dans `lib/generation/`) ne doit rien trouver dans prompt ni légende.
- Divulgation : `#AI` ou le mot « AI » présent dans la légende IG/TikTok/X, sinon rejet `no_ai_disclosure`.
- Pas de nombre de crédits ni d'URL dans une légende IG/TikTok (les liens vivent en bio).

Étage 2, LLM : `grokService.checkSfwPromptSafety(prompt)` (`lib/providers/grok.ts` l. 332) sur les prompts SFW — attention, la fonction **échoue ouverte** (`riskScore: 0`, `reason: "check_unavailable"` sans clé ou en cas d'erreur) : l'étage 1 est le vrai verrou.

## 9. Volumes et coût par asset

Le volume se déduit des caps de `warming-policy.md` §11, pas du brief : par jour et par personnage en cruise, Instagram 1 (appareil) + TikTok 2 + X 3 + Reddit 2 = **8 posts** (+ 1 story Instagram, E3.4). Variantes par master gardé : image SFW → `instagram` (`feed`, seulement quand `post_photo` existe, E3.6) + `tiktok` (photo, API) ; image NSFW → `x` + `reddit` ; clip SFW → les 4 plateformes (§4.3). Besoin quotidien : **≈ 4 assets gardés** — 1 clip SFW (4 variantes), 1 image SFW (1-2), 2 images NSFW (3 : X ×2, Reddit ×1) — soit 8 variantes pour 8 posts. Les « 6 assets/jour/personnage (4 images, 2 clips) » du brief sont un **plafond de production** (marge pour les rejets de conformité, les stories et les remplacements), pas une cible. Stock de sécurité par plateforme = **3 × cap de `warming-policy.md` §11** : Instagram 3, TikTok 6, X 9, Reddit 6 variantes `ready` par personnage ; le workflow quotidien ne produit que ce qui manque pour revenir à ce stock. Tant qu'E3.6 (`post_photo`) n'est pas livré, le programmateur ne rend pas de variante `instagram/feed`.

Coûts cash (`couts-reels.md` §3-§5, §9), par asset **gardé** :

| Asset gardé | Génération ×3 | QA ×3 | Total cash | Crédits (route utilisateur) |
|---|---|---|---|---|
| Image SFW, Soul 1080p | non documenté (`couts-reels.md` §5 : « — ») [à vérifier] | 0,009 $ | ≈ 0,01 $ + Soul | 3 × 2 = 6 cr, 0 en batch admin |
| Image NSFW, Lustify | 3 × 0,088 $ | 0,009 $ | **0,27 $** | 3 × 1 cr, 0 en batch admin |
| Clip SFW 5 s 720p | 3 × 1,20 $ | 0,009 $ | **3,61 $** | 3 × 30 = 90 cr |
| Clip SFW 10 s 720p | 3 × 2,40 $ | 0,009 $ | **7,21 $** | 3 × 60 = 180 cr |
| Re-rendu + filigrane + légende | — | — | ≈ 0,001 $ (Grok texte) | 0 |

Par personnage et par jour, au besoin réel (clips de 5 s) : 1 × 3,61 + 2 × 0,27 + 1 × Soul ≈ **4,2 $ + Soul** ; pour 6 personnages ≈ **25 $/jour ≈ 750 $/mois**. Au plafond du brief (2 clips, 2 images SFW, 2 images NSFW) : ≈ 7,8 $ + Soul par personnage, ≈ 47 $/jour ≈ 1 400 $/mois, dont 93 % de vidéo. C'est le constat de `couts-reels.md` §5 : « l'image est bon marché, la vidéo est le seul poste qui coûte » ; le seul levier est le nombre de secondes par clip, pas le nombre de candidats.

Les phases de chauffe consomment moins : `posts_per_week` vaut 0 en CONSUME et LIGHT, 3 en NETWORK, 7 en CRUISE, avec un cap POST de 1/jour (`gitd/farm/policy.py` l. 65-68, 140) — l'écart avec le volume de cruise est tranché dans `warming-policy.md` §11. La banque produit donc à plein régime seulement pour les comptes en cruise ; avant, le stock de 3 × cap par plateforme suffit.

## 10. Sources d'inspiration et choix du programmateur

Trois sources, chacune avec un identifiant stable rangé dans `sourceKind` / `sourceRef` :

**Foxy** — source versionnée dans le repo, sans média : `lib/social/data/foxy/prompts.json` (400 prompts SFW paraphrasés : Daily Life 160, Prestige 128, Wanderlust 109, Bold & Playful 105, Fit & Active 105, Artsy 80, Character Play 75, Seasonal 64), `prompts-nsfw.json` (200) et `tag-mapping.txt`, copiés depuis `Marketing/foxy-scraper/` (E6.6, étape 0) — le dossier `Marketing/` n'est **pas suivi par git** (`git ls-files Marketing` : 0 fichier) et n'existe ni dans l'image Docker de prod (le `Dockerfile` ne copie que `prisma`, `public`, `.next/standalone`, `.next/static`) ni sur le Mac mini. `sourceRef = "foxy:<index>"`. La source complète `Marketing/foxy-scraper/foxy_cleaned.json` (`stats.kept = 1994` prompts en `explicitnessLevel = 1`, 1 073 en `explicitnessLevel = 4`, `byTag` en 8 catégories : `luxury` 1 304, `lifestyle` 1 275, `daring` 1 082, `active` 821, `travel` 782, `artistic` 315, `cosplay` 277, `seasonal` 125 ; entrées `{ id, type, mediaType, imageUrl, videoUrl, videoPreviewUrl, prompt, tags, explicitnessLevel }`) reste hors repo, source d'un import ultérieur. Règle : `explicitnessLevel = 1` → SFW, `4` → NSFW seulement [à vérifier sur un échantillon]. Les prompts décrivent une autre femme : ils passent par `remixSoulPrompt` (§4.1) ou, en NSFW, par `rewritePromptForCharacter` (`lib/providers/grok.ts` l. 1332).

**Radar** — `ScrapedPost` filtré par `niche` du personnage, `mediaType`, trié `ourScore desc` ; « décollage » = `authorFollowers < BREAKOUT_MAX_FOLLOWERS (50 000)` et `ourScore > BREAKOUT_MIN_OUTLIER (3)` (`lib/radar/refresh.ts` l. 14-15, `GET /api/radar?niche=&breakout=1`). Un reel inspire un **prompt neuf** (description par vision, puis prompt Seedance T2V à 1,20 $/5 s) ; le mode « adapt » de `/replicate-video` (video-edit, `VIDEO_REPLICATE_ADAPT_PER_5S = 21` cr, facturé entrée + sortie) reste réservé à la réplication, pas à la production (`couts-reels.md` §6).

**Hooks** — constantes de `lib/social/hooks.ts` (E6.6) : `ROTATION_180`, `REFLET_MIROIR`, `VUE_ZENITHALE`, `ZOOM_PHYSIQUE`, chacune avec son texte d'ouverture de 3-4 s, recopiées depuis `Marketing/communication/hooks_pattern_interruption.md` (hors repo, même raison que Foxy). Le hook s'écrit dans les 2-3 premières secondes du prompt vidéo et se range dans `ContentAsset.hook`.

**Presets** — les 9 presets `social` (§4.2), `sourceKind = "preset"`, `sourceRef = id`.

Choix par le programmateur (agent du workflow quotidien, décisions reproductibles par `rng` seedé `sha256(characterId, date)`) :

1. Lire le pilier du jour dans la fiche persona (`personas.md` : calendrier par jour de semaine) → catégorie Foxy autorisée.
2. Tirer les slots : images SFW 50 % Foxy / 30 % radar / 20 % preset ; clips 40 % preset / 40 % radar / 20 % Foxy ; un hook sur un clip sur deux, jamais deux fois le même hook de suite.
3. Exclure tout `sourceRef` déjà utilisé par ce personnage depuis 60 j (`@@index([characterId, sourceKind, sourceRef])`), et toute catégorie identique à la veille.
4. Passer chaque prompt par l'étage 1 de conformité (§8) avant de lancer les 3 candidats.
5. Écrire `batchId`, `sourceKind`, `sourceRef`, `hook` sur les 3 `ContentAsset` du slot, statut `candidate`.

## 11. Ce qui n'existe pas encore

Rien de cette banque n'est codé : aucun modèle `ContentAsset`, aucun `lib/social/`, aucune route `app/api/admin/social/*`, aucun hachage perceptuel ni contrôle anatomique (`grep phash|perceptual|dhash` : seulement `couts-reels.md`), aucun filigrane, aucun paramètre `aspect` sur le batch admin. `compareFaces` n'est appelé que par le KYC (`app/api/ai-characters/draft/kyc/verify-images/route.ts`). Eva n'a pas de ligne `AICharacter` (LoRA local `zimage_character_ohwx_v1.safetensors`, 9 références, 23 images lifestyle) et Kelly / Tal n'ont que `face/front/back.png` (+ 23 images de dataset pour Kelly) : leur Soul et leur LoRA OFMAI sont un prérequis (`build-plan.md`, epic personnages). Les tâches, l'ordre et les tests sont dans `build-plan.md` ; le contrat de livraison à la ferme dans `bridge-ofmai-farm.md`.
