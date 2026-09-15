# Personas — fiche, six personnages, Fanvue, link-in-bio, bios, compte de marque

> **Nature** : reference
> **Statut** : en vigueur — vagues 1 et 2 construites le 2026-09-15. Existent : côté ferme `gitd/farm/*.py`, les skills `ofmai_{instagram,tiktok,x,reddit}` et `ofmai_signup_*`, le pont et les règles collectives (390 tests) ; côté OFMAI `lib/social/*`, `app/api/farm/*`, `app/api/admin/social/*`, les six fiches persona et le schéma de la banque (350 tests). Restent à faire : la vérification des sélecteurs sur un appareil (E4, aucun `tested_on` rempli), les pages publiques, le comment-to-DM, et les trois tâches de cibles radar E3.7 / E7.5 / E7.6.
> **À jour au** : 2026-09-15
> **Répond à** : qui sont les six personnages de M1, à quoi ressemble leur fiche, lesquels se déclarent IA et où, où pointent leurs liens, comment ils se présentent sur chaque plateforme et sur Fanvue, et où tout cela vit dans le repo
> **Code concerné** : `lib/social/personas/*.yaml` et `lib/social/personas.ts` (à créer), `app/c/[slug]/page.tsx` (à créer), `app/api/farm/personas/[characterId]/route.ts` (à créer), `prisma/schema.prisma` (`AICharacter` — `publicSlug` et `isPublic` à ajouter —, `TrackedInfluencer`, `ScrapedPost` ; `SocialAccount` et `SocialCommentPool` à créer), `lib/core/admin-guard.ts`, `lib/core/host.ts`, `lib/analytics/utm.ts`, `lib/radar/niche-labels.ts`, `lib/characters/character-create-catalog.ts`, `app/api/admin/instagram/replicate-image/route.ts`, `app/api/admin/instagram/replicate-video/route.ts`, `lib/billing/pricing.ts`, `app/[seoLanding]/page.tsx`, `app/api/auth/[...nextauth]/route.ts`, `app/layout.tsx` ; fork `gitd/farm/models.py`, `gitd/farm/human.py`

La fiche persona est le seul endroit où l'on dit **qui** est un personnage : sa voix, ses interdits, son calendrier, ses comptes, ses liens et s'il se déclare IA (`disclosed`). Son **physique** vit déjà dans `AICharacter` (`physical_profil`, `soulId`, `lora_name`) et n'est jamais recopié ici. Ce que la ferme en reçoit passe par `GET /api/farm/personas/{character_id}` (`bridge-ofmai-farm.md` §3.5) ; ce qu'on en génère est dans `content-pipeline.md` ; les gestes de publication et le routage des subs Reddit dans `publishing.md` ; les règles absolues dans `rules.md`.

## 1. Format de la fiche

Un fichier YAML par personnage, `slug` = `utm_content` = `/c/<slug>` = nom du fichier. Pas de secret (R9), pas de média (R33), ASCII pur pour tout ce qui sera tapé sur l'appareil (R12 : `HumanInput.type_text` de `gitd/farm/human.py` supprime tout caractère `> 127`).

| Bloc | Champs | Qui le lit |
|---|---|---|
| `slug`, `ofmai` | `character_id`, `soul_id`, `lora_name`, `trigger_word` (= colonnes `AICharacter`) | banque `ContentAsset`, pont |
| `identity` | `name`, `age`, `birthday`, `origin`, `city`, `timezone` (= `farm_accounts.timezone`), `market`, `language`, `disclosed`, `disclosed_since`, `signature` (2 traits + 1 trait décalé), `backstory` ≤ 80 mots, `visual_anchor`, `brand_colors` | légendes, réponses, page publique, **inscriptions** (`account-creation.md`) |
| `identity.birthday` | date ISO `AAAA-MM-JJ`, cohérente avec `age`, jamais un 1ᵉʳ janvier ni une date connue, un jour et un mois différents d'une fiche à l'autre. **Les quatre plateformes demandent une date complète à l'inscription**, pas un âge : c'est cette valeur qui est tapée à l'écran (paramètre `birthday` des skills `ofmai_signup_*`, `account-creation.md` §6) et c'est elle qu'il faudra ressortir pour une vérification ou une récupération de compte, des mois plus tard. `age` reste dans la fiche parce qu'il sert aux textes (bio « sierra, 25, la ») ; il se recalcule depuis `birthday`, il ne le remplace pas | `account-creation.md` §6.0-§6.4, bios (§6), page publique |
| `identity.disclosed` | `true` \| `false` — le personnage se déclare IA sur Instagram, TikTok, X et Reddit (bio, `#AI`, pool `ai`, comment-to-DM, et label AIGC figé à la mise en file) ; 3 fiches sur 6 à `true` (§3.3) ; sans effet sur Fanvue, toujours déclaré (§4) ; ne change pas pendant le test, hors les deux exceptions de §3.3 | bios, légendes (`content-pipeline.md`), `SocialPublication.aigcLabel` au moment de la mise en file, pont (`disclosed` dans `GET /api/farm/personas`), `metrics-attribution.md` (groupes `declared` / `undeclared`) |
| `identity.disclosed_since` | date ISO ou `null` — renseignée seulement quand un personnage bascule en cours de test (§3.3) ; ses données antérieures restent dans son groupe d'origine jusqu'à cette date | `metrics-attribution.md` §8.3, pont (`bridge-ofmai-farm.md` §3.5) |
| `niche` | `radar` (clé `TrackedInfluencer.niche`, libellés dans `lib/radar/niche-labels.ts`), `theme`, `vehicle`, `hashtags_niche` (CSV = `farm_accounts.niche`, repli des recherches de détour), `source` (fenêtre `window_days` / `window_days_max`, tri `outlierScore`, `account_type`, `media` = `ScrapedPost.mediaType` `video` \| `image`) — le radar est la seule source de contenu (`content-pipeline.md` §2) **et la source des cibles de chauffe** : `niche.radar` dit dans quelle niche du radar puiser les comptes que le personnage suit et les profils qu'il visite (`warming-policy.md` §8.2, `GET /api/farm/targets`) | programmateur, planner, sélection des posts source, sélection des cibles de suivi |
| `voice` | `tone`, `writing`, `reply_tone`, `emoji` | légendes, `comment_reply` / `dm_reply` |
| `vocabulary`, `forbidden_words` | mots qu'elle emploie ; mots interdits **en plus** de `rules.md` R10-R11 et de `checkPromptPolicy` | agent conformité (`content-pipeline.md` §8) |
| `calendar` | `mon` … `sun` → format du jour (`reel` = réplication vidéo, `carousel` = réplication d'image) + plateformes ; le sujet vient du post radar sélectionné, jamais d'un preset | programmateur (`content-pipeline.md` §10) |
| `comment_pools` | par plateforme, ASCII, jamais de lien ; la fiche en contient une amorce (≥ 20), le stock vivant est dans `SocialCommentPool` : **≥ 60 disponibles par personnage et par plateforme, réapprovisionnement sous 20** par le workflow quotidien (`warming-policy.md` §8) | `SocialCommentPool` (`kind = comment`) → `GET /api/farm/comments?kind=comment` |
| `reply_pools` | par plateforme, trois pools ASCII — `ai` (« yes, 100% AI », **seulement si `disclosed: true`**), `thanks`, `question` — ≥ 30 lignes par pool, jamais de lien | `SocialCommentPool` (`kind = reply_ai \| reply_thanks \| reply_question`) → `GET /api/farm/comments?kind=reply_*`, workflow `comment_reply` (E3.2) |
| `accounts` | par plateforme : `handle`, `content_type`, `channel` (`device` \| `api`, valeurs du pont), `bio`, `subs_*` pour Reddit | `SocialAccount`, `accounts add`, `GET /api/farm/personas` |
| `links` | link-in-bio par host, boutons avec UTM, `dm_offer` | page `/c/<slug>`, bios, comment-to-DM |
| `hashtags` | par plateforme + `always: ["#AI"]` si `disclosed: true`, `always: []` sinon | légendes |
| `visual_refs` | clés S3 (refs, moodboard, filigrane) | page publique, QA identité |

## 2. Exemple complet : Sierra (fitness)

Source : proposition à valider par Nathan (nom, pseudo, bio, ville). Personnage **neuf**, créé from scratch sur le compte admin avec le builder (`lib/characters/character-create-catalog.ts` : `ORIGINS` `mixed_race`, `BODIES` `athletic`, `HAIR_COLORS` `brown`, `HAIR_CUTS` `ponytail`, `EYE_COLORS` `hazel`, `FACE_FEATURES` `beauty_mark` ; aucun tatouage). Groupe de divulgation : **`declared`** (`disclosed: true`, §3.3). Les cinq autres fiches suivent le même format ; une fiche `disclosed: false` diffère sur les points listés en fin de section.

```yaml
# lib/social/personas/sierra.yaml
slug: sierra                                # = utm_content, = /c/sierra
ofmai:
  character_id: null                        # AICharacter.id — cree from scratch sur le compte admin (§3.2)
  soul_id: null                             # AICharacter.soulId (SFW, Instagram/TikTok)
  lora_name: null                           # AICharacter.lora_name (NSFW, X/Reddit)
  lora_ultra: null                          # AICharacter.loraUltra (NSFW, moteur Ultra)
  trigger_word: null                        # AICharacter.triggerWord, rempli par le pipeline LoRA
  public_slug: sierra                       # AICharacter.publicSlug (a creer), isPublic = true (§5)
identity:
  name: Sierra                              # a valider
  age: 25
  birthday: "2001-08-26"                    # date complete exigee a l'inscription sur les 4 plateformes ;
                                            # tapee telle quelle (param birthday, account-creation.md §6)
  origin: mixed                             # jamais de nationalite precise en public
  city: Los Angeles, CA                     # = Etat du proxy statique (infrastructure-geelark-proxies.md)
  timezone: America/Los_Angeles             # = farm_accounts.timezone = fuseau GeeLark (R20)
  market: US
  language: en-US
  disclosed: true                           # groupe "declared" du test 3/6 (§3.3) ; Fanvue declare quoi qu'il arrive
  disclosed_since: null                     # date ISO seulement si bascule en cours de test (§3.3)
  signature: "disciplined, sunny, zero drama ; trait decale : rate ses reveils du dimanche"
  backstory: >-
    Grew up playing every sport in a small California town, moved to LA to
    coach. Trains at 6am, eats the same breakfast every day, laughs at her own
    form checks. Says she is an AI character whenever someone asks.
  visual_anchor: athletic build, brown hair in a high ponytail, hazel eyes, beauty mark under the left eye, no tattoos
  brand_colors: ["#F4F1EA", "#1E1E1E", "#E07A3F"]
niche:
  radar: fitness                            # TrackedInfluencer.niche ; 160 comptes (145 US), 432 videos, 4 decollages (§3.1)
                                            # sert aussi de vivier de cibles de chauffe (warming-policy.md §8.2)
  theme: 6am club, gym mirror, meal prep, LA sun
  vehicle: [gym mirror, morning run, smoothie bar, beach workout, studio stretch]
  hashtags_niche: "gymgirl,fitnessmotivation,losangeles,morningroutine"
  source:                                   # la seule source de contenu (content-pipeline.md §2)
    window_days: 30                         # postedAt >= now - 30 jours
    window_days_max: 60                     # elargi a 60 jours seulement si moins de 3 x n candidats
    order_by: outlierScore                  # ScrapedPost.outlierScore, decroissant
    account_type: any                       # TrackedInfluencer.accountType "ia" | "reelle" ; "ia" prefere a egalite
    media: [video, image]                   # ScrapedPost.mediaType : reels (replicate-video) et carrousels (replicate-image)
voice:
  tone: upbeat, precise, encouraging, never preachy
  writing: lowercase, 1-2 short sentences, numbers when she can (reps, miles, minutes), hashtags on their own line
  reply_tone: answers like a training partner, thanks in three words, never argues, never explains the tech
  emoji: none on device (ASCII) ; at most one on API channels
vocabulary:
  uses: [6am club, form check, rest day, "fuel, not diet", "no filter, just AI"]
  never: [babe, daddy, free, credits, price, real girl, "link in bio" inside a post, skinny, "lose weight fast"]
forbidden_words: ["same face", "real person", "deepfake", onlyfans, fansly, "my agency"]
calendar:                                   # format du jour ; le sujet vient du post radar selectionne, jamais d'un preset
  mon: {format: reel, platforms: [instagram, tiktok]}        # reel = ScrapedPost.mediaType "video"
  tue: {format: carousel, platforms: [instagram]}             # carousel = mediaType "image"
  wed: {format: reel, platforms: [instagram, tiktok]}
  thu: {format: carousel, platforms: [instagram, x]}
  fri: {format: reel, platforms: [instagram, tiktok, x]}
  sat: {format: reel, platforms: [tiktok, reddit]}
  sun: {format: carousel, platforms: [instagram]}             # le jour de repos du ledger l'emporte s'il tombe ici
comment_pools:                              # ASCII pur (R12), amorce >= 20 lignes par plateforme ; stock vivant >= 60 dans SocialCommentPool
  instagram:
    - "that form though"
    - "ok the lighting in this gym"
    - "need this playlist asap"
    - "saved for tomorrow's session"
  tiktok:
    - "the transition though"
    - "how is the gym that empty"
    - "this sound with this set"
  x:                                        # commentaires de chauffe a partir de network (warming-policy.md §7)
    - "this thread is the whole mood"
    - "saving this for later"
    - "ok the framing on this"
  reddit:                                   # le karma vient d'ici (publishing.md §5)
    - "the composition on this is really clean"
    - "what lens did you use for this"
    - "this is the best one in the sub this week"
    - "saved, thanks for sharing the process"
reply_pools:                                # reponses sous ses propres posts, ASCII, >= 30 lignes par pool (comment_reply, E3.2) ; pool ai present car disclosed: true
  instagram:
    ai: ["yes, 100% AI and proud of it", "all AI, made on ofmai", "not real, and that is the point"]
    thanks: ["thank you", "you are sweet", "appreciate it"]
    question: ["la, most days", "no filter, just AI", "answered in my bio"]
  tiktok:
    ai: ["yep, fully AI", "AI character, made on ofmai"]
    thanks: ["thanks!!", "you made my day"]
    question: ["all in my bio", "asked and answered: AI"]
accounts:
  instagram: {handle: sierra.cole, content_type: sfw, channel: device,
              bio: "sierra, 25, la\nAI character, made on ofmai\n6am club"}
  tiktok:    {handle: sierra.cole, content_type: sfw, channel: device,   # api a partir du cruise (publishing.md)
              bio: "sierra | 25 | la | AI character made on ofmai"}
  x:         {handle: sierracole_ai, content_type: nsfw, channel: api, sensitive_media: true,
              bio: "sierra. 25. la. AI character (virtual), made on OFMAI. 18+ only. links below"}
  reddit:    {handle: sierra_cole_ai, content_type: nsfw, channel: api,
              bio: "AI-generated character (virtual), 18+. Everything is on my profile.",
              subs_creators: [], subs_fans: []}          # classification des subs : publishing.md
  fanvue:    {handle: sierracole, ai_creator_badge: true, public_layer: sfw}
links:
  link_in_bio_sfw: "https://ofmai.ai/c/sierra?utm_source=<plateforme>&utm_medium=bio&utm_campaign=army-2026-09&utm_content=sierra"
  link_in_bio_hot: "https://hotofmai.ai/c/sierra?utm_source=<plateforme>&utm_medium=bio&utm_campaign=army-2026-09&utm_content=sierra"
  buttons:                                  # la page recopie les utm_* de sa query sur chaque bouton
    - {label: "my page", to: "https://www.fanvue.com/sierracole"}
    - {label: "create your own", to: "/ai-characters/create"}
  dm_offer: "https://ofmai.ai/?utm_source=instagram&utm_medium=dm&utm_campaign=army-2026-09&utm_content=sierra"
  dm_text: "hey! yes, i am 100% AI, a character made on OFMAI. you can build yours, 15 free credits to start: {dm_offer}"
hashtags:
  always: ["#AI"]                           # [] si disclosed: false
  instagram: ["#gymgirl", "#fitnessmotivation", "#losangeles", "#morningroutine"]
  tiktok: ["#aiinfluencer", "#gymtok", "#la"]
  x: []
  reddit: []
visual_refs:                                # cles S3, jamais de fichier dans le repo (§8)
  refs_prefix: social/<characterId>/refs/           # bucket prive hiddn2 : copie des 3 refs SFW du builder, reference du controle Gemini (content-pipeline.md §5)
  moodboard_prefix: social/<characterId>/moodboard/  # bucket prive hiddn2
  preview_prefix: social/<characterId>/preview/      # bucket public hiddn2-public (page /c/sierra)
  watermark: social/watermarks/<characterId>.png     # bucket public (content-pipeline.md §6)
```

`<plateforme>` est remplacé au moment de poser le lien (`instagram`, `tiktok`, `x`, `reddit`) ; `dm_text` reste en une phrase, sans nom de fournisseur, et l'offre « 15 crédits » est le bonus d'inscription existant (`app/api/auth/[...nextauth]/route.ts` l. 114-135 : `purchasedCredits: 15`, « Welcome credits ») — rien à construire.

Une fiche `disclosed: false` (Skyler, Riley, Vera, §3.3) diffère sur cinq points, et seulement ceux-là : `hashtags.always: []` ; pas de pool `reply_pools.*.ai` ; bios sans « AI » ni « made on ofmai » (§6) ; pseudos sans `ai` ; `dm_text` et `dm_offer` absents (aucun comment-to-DM). `fanvue.ai_creator_badge` reste `true`.

## 3. Les six personnages

### 3.1 Ce que dit le radar (prod, 2026-09-14)

```bash
bash .claude/skills/prod/prod.sh sql "SELECT niche, count(*) AS comptes, count(*) FILTER (WHERE market='US') AS us,
  round(percentile_cont(0.5) WITHIN GROUP (ORDER BY \"medianViews\")::numeric) AS med_views_compte,
  round(percentile_cont(0.5) WITHIN GROUP (ORDER BY followers)::numeric) AS med_followers
  FROM \"TrackedInfluencer\" WHERE status='active' GROUP BY niche ORDER BY comptes DESC" --limit 45
bash .claude/skills/prod/prod.sh sql "SELECT niche, count(*) AS videos,
  count(*) FILTER (WHERE \"ourScore\" > 3 AND \"authorFollowers\" < 50000) AS decollages,
  round(percentile_cont(0.5) WITHIN GROUP (ORDER BY views)::numeric) AS med_views_video
  FROM \"ScrapedPost\" WHERE \"mediaType\"='video' AND views IS NOT NULL GROUP BY niche ORDER BY decollages DESC" --limit 45
```

« Décollage » = `ourScore > 3` et `authorFollowers < 50 000`, les seuils `BREAKOUT_MIN_OUTLIER` / `BREAKOUT_MAX_FOLLOWERS` de `lib/radar/refresh.ts`.

| Niche (`TrackedInfluencer.niche`) | Comptes (US) | Vues méd./compte | Abonnés méd. | Vidéos | Décollages | Vues méd./vidéo |
|---|---|---|---|---|---|---|
| `tatouee` | 218 (178) | 26 580 | 170 332 | 413 | 7 | **343 436** |
| `bimbo` | 211 (179) | 57 352 | 162 707 | 420 | 8 | 287 516 |
| `latina` | 191 (157) | **107 811** | 359 843 | 402 | 1 | 219 623 |
| `bbw-curvy` | 169 (150) | 85 139 | 557 081 | 412 | 5 | 179 052 |
| `fitness` | 160 (145) | 76 125 | 311 930 | 432 | 4 | 261 733 |
| `e-girl` | 157 (132) | 39 762 | **86 041** | 452 | **22** | 147 544 |
| `cosplay-gaming` | 154 (147) | 62 242 | 251 439 | 389 | 5 | 199 960 |
| `asiatique` | 147 (137) | 25 918 | 163 573 | 347 | 5 | 207 748 |
| `gothique` | 107 (99) | 12 846 | 96 176 | 388 | 11 | 140 948 |
| `cosplay` | 102 (99) | 15 750 | 119 137 | 335 | 9 | 79 294 |
| `arabe` | 28 (17) | 20 378 | 67 453 | 301 | **25** | 23 516 |

`tatouee` et toute niche composée `tatouee …` sont **exclues par décision** (tenue des tatouages d'une génération à l'autre trop difficile) ; `arabe` n'est plus retenue. Deuxième lecture, locale : `scripts/radar/out/niches_ranked.csv` (colonne `score`) donne gothique 62,5, latina 44,6, asiatique 43,1, bimbo 39,9, fitness 30,0, e-girl 21,0 [à vérifier : le fichier date du dernier run local, pas de la prod].

### 3.2 Les six

Six personnages **tous neufs**, un par niche, créés from scratch sur le **compte admin OFMAI** (nathannzenou@gmail.com). Aucun personnage existant n'est réutilisé. Noms, pseudos, bios, villes et ancres visuelles ci-dessous sont des **propositions à valider par Nathan** (disponibilité des pseudos à vérifier sur chaque plateforme, 2 replis par pseudo).

| Slug | Nom (à valider) | Pseudo IG / TikTok (à valider) | Ancre visuelle proposée (builder, `character-create-catalog.ts`) | Niche radar | Ville / fuseau | `disclosed` (§3.3) |
|---|---|---|---|---|---|---|
| `sierra` | Sierra Cole | `sierra.cole` | `mixed_race`, `athletic`, `brown` `ponytail`, `hazel`, `beauty_mark` sous l'œil gauche | `fitness` | Los Angeles, CA / `America/Los_Angeles` | `true` |
| `camila` | Camila Reyes | `camila.reyes` | `latina`, `slim_thick`, `black` `long_wavy`, `brown`, petites créoles or | `latina` | Miami, FL / `America/New_York` | `true` |
| `hana` | Hana Lee | `hana.lee.ai` | `east_asian`, `slim`, `black` `long_straight` à frange, `brown`, lumière douce, minimal | `asiatique` | San Francisco, CA / `America/Los_Angeles` | `true` |
| `skyler` | Skyler Rae | `skylerrae` | `caucasian`, `curvy`, `platinum` `long_straight`, `blue`, lèvres glossy, ongles longs, rose partout | `bimbo` | Las Vegas, NV / `America/Los_Angeles` | `false` |
| `riley` | Riley Vex | `rileyvex` | `caucasian`, `slim`, `colored` (mi-noir mi-rose) `medium`, `gray`, eyeliner ailé, `piercings` (septum), setup gaming ; non asiatique | `e-girl` | Seattle, WA / `America/Los_Angeles` | `false` |
| `vera` | Vera Blackwood | `verablackwood` | `caucasian` (peau très claire), `slim`, `black` `long_straight`, `gray`, lèvres sombres, `piercings` (nez), bagues argent | `gothique` | Chicago, IL / `America/Chicago` | `false` |

Aucun tatouage sur les six (même la gothique) : c'est la raison de l'exclusion de `tatouee`, on ne réintroduit pas le problème par une autre niche. Bios Instagram courtes proposées (ASCII, tapées sur l'appareil, R12 ; les autres plateformes en §6) :

| Slug | Bio (à valider) |
|---|---|
| `sierra` | `sierra, 25, la / AI character, made on ofmai / 6am club` |
| `camila` | `camila, 24, miami / AI character, made on ofmai / sun, salsa, sunsets` |
| `hana` | `hana, 23, sf / AI character, made on ofmai / soft light only` |
| `skyler` | `skyler, 24, vegas / pink is a personality / new every day` |
| `riley` | `riley, 22, seattle / online too much / new every day` |
| `vera` | `vera, 25, chicago / black on black / new every day` |

Dates de naissance (`identity.birthday`, §1), cohérentes avec l'âge au 2026-09-15, jours et mois tous différents, aucun 1ᵉʳ janvier, aucune date connue — c'est ce qui est tapé à l'inscription sur les quatre plateformes et ce qu'il faudra retrouver pour une vérification ou une récupération de compte :

| Slug | Âge | `birthday` |
|---|---|---|
| `sierra` | 25 | `2001-08-26` |
| `camila` | 24 | `2002-07-09` |
| `hana` | 23 | `2003-05-22` |
| `skyler` | 24 | `2001-11-06` |
| `riley` | 22 | `2004-02-27` |
| `vera` | 25 | `2000-10-18` |

Plateformes pour les six : Instagram + TikTok (SFW, Soul, → ofmai.ai) ; X + Reddit (18+, LoRA, → hotofmai.ai / Fanvue) ; Fanvue (déclaré IA pour les six). Marché : US pour tous (proxy, GPS, fuseau et langue alignés, R20) ; la ville de la fiche est l'État du proxy statique.

Pourquoi ces six niches :

- **Radar prod (§3.1)** : une fois `tatouee` exclue, ce sont six des huit premières niches en nombre de comptes — `bimbo` 211 comptes / 287 516 vues méd. par vidéo ; `latina` 191 / 219 623 et la plus grosse audience par compte (107 811) ; `fitness` 160 / 261 733 ; `e-girl` 157 et **22 décollages** sur 452 vidéos, le plus haut du radar, face aux plus petits comptes en place (86 041 abonnés médians) : la niche où un compte neuf perce, TikTok-native ; `asiatique` 147 / 207 748 ; `gothique` 107 et 11 décollages, deuxième du radar. `bbw-curvy` et `cosplay-gaming` écartées : comptes en place énormes (557 081 abonnés médians pour la première) et 5 décollages chacune.
- **Six ancres visuelles disjointes** : cheveux brun / noir ondulé / noir à frange / platine / coloré / noir sur peau claire ; corps `athletic` / `slim_thick` / `slim` / `curvy` / `slim` / `slim` ; aucun hashtag de détour en commun. `riley` non asiatique pour ne pas chevaucher `e-girl asiatique` (59 comptes) ni `hana`.
- **Deux familles de look** : naturel (fitness, latina, asiatique) et « fait » (bimbo, e-girl, gothique — `documentation/notes/ofm-playbook/01-niche-persona.md`, P4 : le look « fait » plombe la conversion). Le test de divulgation (§3.3) place une famille dans chaque groupe.

Prérequis avant tout compte : chaque personnage est créé from scratch dans le builder du compte admin (`/ai-characters/create`, `creationMethod = "create"`, `intents ["sfw","nsfw"]` → 3 refs SFW `sfwFaceUrl` / `sfwFrontUrl` / `sfwBackUrl` et `physical_profil`), puis Soul `ready` **et** LoRA `ready` (pipelines dans `documentation/characters/character-nsfw-soul-pipeline.md` ; `CHAR_SOUL_TRAINING 17` cr, `CHAR_LORA_TRAINING 50` cr, `CHAR_SOUL_MIGRATE 15` cr dans `lib/billing/pricing.ts`, 0 cr par le chemin admin [à vérifier]). Les six personnages sont synthétiques ; un post du radar est une référence de scène, jamais un visage à reproduire.

### 3.3 Divulgation IA : test 3 sur 6 (répartition à valider)

Sur Instagram, TikTok, X et Reddit, **trois personnages se déclarent IA et trois ne le font pas**, pour comparer vues, inscrits et payants par groupe (`metrics-attribution.md` : groupes `declared` / `undeclared`, dérivés du booléen `disclosed` de la fiche ; `utm_content` reste le slug). Sur Fanvue, **les six sont déclarés** (badge « AI creator », obligatoire, §4). Le flag est `identity.disclosed` dans la fiche, voyage dans le payload du pont (`GET /api/farm/personas`, `bridge-ofmai-farm.md` §3.5) et décide, côté OFMAI, du `#AI` dans la légende et de `SocialPublication.aigcLabel` **au moment de la mise en file**. Au moment du post, ni l'appareil ni l'API ne relisent la fiche : ils recopient `params.aigc_label` (booléen), que le pont a recopié depuis le champ `aigc_label` de l'item de `GET /api/farm/queue` (`bridge-ofmai-farm.md` §3.2, `publishing.md`).

| Groupe | Personnages (à valider) | Bio | TikTok | Légendes | `reply_pools.*.ai` | Comment-to-DM | Pseudo |
|---|---|---|---|---|---|---|---|
| `declared` (`disclosed: true`) | Sierra (fitness), Camila (latina), Hana (asiatique) | « AI character, made on ofmai » | `aigc_label: true` à chaque post, toggle posé et confirmé | `#AI` (`hashtags.always`) | actif (« yes, 100% AI ») | actif (`dm_text`, §6) | peut porter `.ai` / `_ai` |
| `undeclared` (`disclosed: false`) | Skyler (bimbo), Riley (e-girl), Vera (gothique) | aucune mention IA | `aigc_label: false`, toggle jamais touché | pas de `#AI` | pool absent : une question « is this AI? » reste sans réponse, jamais de démenti [à valider] | inactif : `real / ai / how / tool` ne déclenchent rien [à valider] | jamais `ai` dans le pseudo |

Pourquoi cette répartition : une niche de chaque famille de look (§3.2) dans chaque groupe serait plus propre, mais le brief propose naturel = déclaré, « fait » = non déclaré ; toute autre répartition 3/3 convient.

`disclosed` **ne change pas pendant le test**, sauf deux cas et seulement eux : (a) un compte non déclaré sanctionné par la plateforme pour contenu IA non étiqueté bascule individuellement — `disclosed: true`, `disclosed_since` daté, et le compte sort de la comparaison (`metrics-attribution.md` §8.3) ; (b) la décision de J21, qui peut déclarer les six. Lecture à J14, décision à J21, aux seuils de `metrics-attribution.md` §8.3 ; le résultat décide de la règle pour les personnages suivants.

## 4. Page Fanvue

- **Un compte maître = l'opérateur** (Nathan, pièce d'identité vérifiée par Fanvue) ; les personnages sont des profils IA rattachés au maître (OFMAI `documentation/notes/ofm-playbook/02-comptes-setup.md` §1 : « You only need an ID to create the main account… multiple AI accounts that are linked », 2 sources sur 25) [à vérifier dans le dashboard Fanvue : profil enfant par personnage, ou un compte par personnage sous la même pièce d'identité]. Aucun personnage n'a de pièce d'identité propre.
- **Badge « AI creator »** déclaré à l'inscription (même source : « Fanvue impose la divulgation, AI Creator à l'inscription »), jamais retiré, **pour les six** — `disclosed` ne joue que sur les réseaux (§3.3), Fanvue est toujours déclaré. Le nom affiché est le prénom seul ; la bio Fanvue est la bio X en version longue (§6).
- **Couche publique SFW** : avatar, bannière (format long, corps entier), bio, 10-15 posts gratuits lifestyle / maillot ; le 18+ uniquement derrière l'abonnement ou le PPV. C'est la condition pour que le bouton Fanvue soit acceptable depuis un link-in-bio Instagram / TikTok (R23 : jamais de « Fanvue 18+ » depuis une origine SFW) [à vérifier : Meta suit les redirections jusqu'à la destination finale, la couche publique doit rester SFW en permanence].
- **Structure de l'offre** : page gratuite (« sorting machine », consensus du playbook) + PPV ; pas d'abonnement payant en V1 (minimum Fanvue 3,99 $ d'après le playbook [à vérifier], commission 15 %). Stock de lancement par personnage : 30 posts SFW + 10 PPV NSFW sortis de la banque (`content-pipeline.md`), tous filigranés, identité tenue par le Soul / la LoRA.
- **Lien « made with »** vers ofmai.ai avec `utm_source=fanvue&utm_medium=profile&utm_content=<slug>` (`metrics-attribution.md` §2). Les revenus Fanvue ne comptent pas dans les seuils J4 / J7 / J14.
- **Interdits** : image de vérification à pancarte, likes achetés ou groupes like-for-like (playbook, § « non recommandé »), contenu 18+ d'un personnage sans sa LoRA OFMAI.
- URL de profil : `https://www.fanvue.com/<handle>` [à vérifier : le code ne connaît que `/app-store/details/<uuid>` et `/signup`, `lib/fanvue/fanvue-deeplinks.ts`].

## 5. Link-in-bio

Décision : **pas d'agrégateur**, une page auto-hébergée `app/c/[slug]/page.tsx` servie sur les deux hosts. Raisons (OFMAI `documentation/notes/ofm-playbook/02-comptes-setup.md` §1.6) : Instagram suit les redirections des agrégateurs jusqu'à la destination finale ; plusieurs agrégateurs ont été bannis ; domaine propre + redirection JavaScript (le crawler Meta n'exécute pas le JS) ; écran 18+ obligatoire côté HOT. Et cela lève le [à vérifier] de `metrics-attribution.md` §2 : notre page relaie la query string à ses boutons.

- `/c/` et pas `/<slug>` : `app/[seoLanding]/page.tsx` est le segment dynamique racine et renvoie 404 pour tout slug absent de son registre ; un `/sierra` entrerait en collision.
- **Réservée aux personnages du compte admin** : `AICharacter.publicSlug` (`String? @unique`) et `isPublic` (`Boolean @default(false)`) sont à ajouter au schéma (absents aujourd'hui, vérifié). Ils ne se posent que par une route admin gardée par `requireAdmin()` (`lib/core/admin-guard.ts` : session + `User.type === "admin"`), et `app/c/[slug]/page.tsx` ne sert qu'une ligne `isPublic = true` dont le propriétaire est `type = "admin"` — un personnage d'utilisateur n'a jamais de page publique, même par URL devinée (404, pas 403, pour ne rien révéler). Galerie SFW sur ofmai.ai, galerie NSFW sur hotofmai.ai derrière la gate 18+.
- Par host (`isSFWHost`, `lib/core/host.ts`) : **ofmai.ai** → vitrine SFW : portrait (`AICharacter.sfwFaceUrl`, bucket public), trois boutons — « my page » (Fanvue, couche publique SFW), « create your own » (`/ai-characters/create`), l'autre réseau SFW du personnage ; la ligne « 100 % AI character, made on OFMAI » n'apparaît que si `disclosed: true`, et pour une fiche `disclosed: false` le bouton « create your own » disparaît aussi [à valider : la page vit sur ofmai.ai, qui dit déjà « IA » dans son titre — Nathan tranche si les trois non déclarés pointent plutôt directement vers Fanvue] ; **hotofmai.ai** → gate 18+ (choix mémorisé en `localStorage`, `try/catch`), puis Fanvue, « create the same (18+) » (même règle `disclosed`), X.
- UTM : le lien de bio porte `utm_source=<plateforme>&utm_medium=bio&utm_campaign=army-2026-09&utm_content=<slug>` (`instagram` pour Instagram, tranché dans `metrics-attribution.md` §1 ; le garde E10.1 est déployé avant le premier lien) ; la page recopie `utm_*` sur chaque bouton avec `appendUtm()` (`lib/analytics/utm.ts`), navigation par JS, jamais de 302 serveur.
- Aperçus : `social/<characterId>/preview/*.webp` sur `hiddn2-public` (`content-pipeline.md` §3). Rien de NSFW n'est rendu sur ofmai.ai, même derrière un clic (R4).
- Moment de pose du lien et du texte de bio : `account-creation.md` ; jamais de lien ailleurs qu'en bio avant le cruise (R22).

## 6. Bios par plateforme et divulgation IA

| Plateforme | Limite [à vérifier] | Divulgation si `disclosed: true` | Exemple déclaré (Sierra) | Exemple non déclaré (Skyler) | Tapée sur l'appareil |
|---|---|---|---|---|---|
| Instagram | 150 car. | « AI character » en bio, `#AI` en légende, auto-déclaration IA à la publication [à vérifier depuis l'app] | `sierra, 25, la / AI character, made on ofmai / 6am club` | `skyler, 24, vegas / pink is a personality / new every day` | oui → ASCII |
| TikTok | 80 car. | toggle AIGC à chaque post (`aigc_label` de la file, R2-R3) + mention en bio | `sierra \| 25 \| la \| AI character made on ofmai` | `skyler \| 24 \| vegas \| pink is a personality` | oui → ASCII |
| X | 160 car. | « AI character (virtual) » en bio, réglage média sensible activé **avant** le premier post, nom et bio neutres (`lib/seo/academy/platforms.ts`, leçon X) | `sierra. 25. la. AI character (virtual), made on OFMAI. 18+ only. links below` | `skyler. 24. vegas. 18+ only. links below` | oui → ASCII |
| Reddit | 200 car. | « AI-generated character » en bio ; flair / tag IA du sub quand il existe (`publishing.md`) | `AI-generated character (virtual), 18+. Everything is on my profile.` | `24, vegas, 18+. Everything is on my profile.` | oui → ASCII |
| Fanvue | — | badge « AI creator » **pour les six** + bio longue (80-120 mots, backstory + « made on OFMAI ») | version longue de la bio X | idem : badge et « made on OFMAI » même pour une fiche `disclosed: false` | non (navigateur) |

Règles : une bio, une photo de profil, un pseudo **différents** par compte et par personnage (playbook §1.11 : des comptes bannis pour des highlights identiques) ; jamais « OnlyFans », « Fansly », « agency », ni un prix ; jamais « same face » ni un nom de fournisseur (R10-R11) ; le mot « ofmai » en bio est du texte, pas un lien ; sur X, rien de suggestif dans le nom, la bio, l'avatar ou la bannière (ils s'affichent hors du réglage sensible). Le playbook note qu'une agence retire « AI » de ses bios (tristanmodelify) : c'est exactement ce que le test 3/6 mesure (§3.3) — trois personnages déclarés, trois non, Fanvue toujours déclaré ; la décision est dans la fiche (`identity.disclosed`), jamais prise compte par compte, et un personnage non déclaré ne nie jamais être une IA : il ne répond pas à la question.

Comment-to-DM (Instagram, API officielle Meta via ManyChat ou équivalent, `publishing.md`) : **pour les fiches `disclosed: true` seulement**, un commentaire contenant `real`, `how`, `ai` ou `tool` déclenche `dm_text` de la fiche, 200 DM/h max, jamais sans action de l'utilisateur, lien `dm_offer` (`utm_medium=dm`). Pour les trois autres, aucun automate n'est branché sur ces mots-clés [à valider].

## 7. Compte de marque OFMAI par plateforme

| Plateforme | Handle | État | Rôle |
|---|---|---|---|
| Instagram | `@ofmai_app` | existe (`app/layout.tsx` l. 179, `sameAs`) | making-of, résultats, réponses aux « how » |
| TikTok | `@ofmai.app` | à créer [à vérifier disponibilité] | idem, coupes des clips des **personnages déclarés** seulement, avec label AIGC |
| X | `@ofmai_ai` | à créer | making-of + liens hotofmai.ai |
| Reddit | `u/ofmai_official` | à créer | subs créateurs / art IA seulement |

Modèle : une ligne `SocialAccount` par compte avec `role = "brand"`, `characterId = null`, `contentType = sfw` sauf X (`bridge-ofmai-farm.md` §5.1) ; **hors chauffe** : ligne `farm_accounts` facultative (`accounts add … --role brand`, `enabled = 0`, jamais planifiée par `planner.tick`, E1.1), aucune session ; publication depuis l'appareil de Nathan ou par API depuis le Mac mini, sur un profil GeeLark « brand » avec sa propre IP (décision de la vague 0 : profil `brand-us` + IP ≈ 32 $/mois, ou le téléphone de Nathan) — jamais le téléphone ni l'IP d'un personnage (R8, R18). La marque ne tague et ne reprend en coupes que les personnages `disclosed: true` (un tag de marque, ou un clip étiqueté IA sur le compte de marque, appliqué à un personnage non déclaré casse le test, §3.3) ; un personnage ne tague jamais la marque (le lien ne va que dans un sens). Liens sortants : `utm_source=<plateforme>&utm_medium=post&utm_campaign=army-2026-09&utm_content=brand`. Le contenu de marque suit `rules.md` comme le reste : aucun nom de fournisseur dans un making-of, jamais « même visage ».

## 8. Où la fiche vit

```
lib/social/
├── personas/                 sierra.yaml, camila.yaml, hana.yaml, skyler.yaml, riley.yaml, vera.yaml
├── personas.ts               loadPersona(slug), personaForCharacter(characterId), toFarmPersona(p)
├── personas.test.ts          les 6 fiches valident le schéma ; `birthday` au format `AAAA-MM-JJ`, cohérent avec `age`, jamais un 1ᵉʳ janvier, jour et mois uniques d'une fiche à l'autre ; ASCII des pools et bios `device` ; aucun mot de R10-R11 ; `disclosed` cohérent (aucune bio ni pseudo avec « AI », `hashtags.always: []`, pas de pool `ai` ni de `dm_text` quand `false` ; tout cela présent quand `true`) ; 3 fiches `disclosed: true` à la création, tout écart daté par `disclosed_since` (§3.3) ; `fanvue.ai_creator_badge: true` sur les 6
└── compliance.ts             (content-pipeline.md §8)
app/c/[slug]/page.tsx         page publique / link-in-bio (§5)
app/api/farm/personas/[characterId]/route.ts   sous-ensemble servi à la ferme (bridge §3.5)
```

- Schéma validé avec `zod` (`package.json` : `^4.2.1`) ; parseur YAML : `js-yaml` est dans `node_modules` mais absent des `dependencies` [à vérifier : transitif] — l'ajouter, ou écrire les fiches en `.ts` typés si on préfère zéro dépendance.
- `toFarmPersona()` ne renvoie que `handles`, `bio`, `niche`, `disclosed`, `disclosed_since`, `forbidden_words`, `reply_tone`, `links` : la ferme ne voit ni le calendrier ni les pools entiers (ils passent par `GET /api/farm/comments`) ; `disclosed` lui sert aux bios et aux réponses, jamais au toggle AIGC — celui-ci suit `params.aigc_label`, recopié depuis l'item de file (§3.3, `bridge-ofmai-farm.md` §3.2).
- `SocialCommentPool` est **alimentée** depuis `comment_pools` et `reply_pools` par un script idempotent (`scripts/social/seed-comment-pools.ts`, clé `(characterId, platform, kind, text)`), jamais lue depuis le YAML à chaud ; le réapprovisionnement quotidien (≥ 60 / sous 20) est fait par `growth-content-army.js`, phase Pools.
- Médias : rien dans `lib/social/` ni `public/`, et aucun dossier local : les six sont créés from scratch, leurs références sont les 3 refs SFW du builder (`AICharacter.sfwFaceUrl` / `sfwFrontUrl` / `sfwBackUrl`, bucket public) et le dataset du Soul. `refs_prefix` en est une copie sur le bucket privé, image de référence du contrôle Gemini (`content-pipeline.md` §5).

```bash
# refs d'un personnage vers le bucket privé, une fois AICharacter créé (<characterId> = son id)
aws s3 cp "s3://hiddn2-public/<clé de sfwFaceUrl>"  "s3://hiddn2/social/<characterId>/refs/face.png"   # [à vérifier : clé exacte derrière sfwFaceUrl]
aws s3 cp "s3://hiddn2-public/<clé de sfwFrontUrl>" "s3://hiddn2/social/<characterId>/refs/front.png"
aws s3 cp "s3://hiddn2-public/<clé de sfwBackUrl>"  "s3://hiddn2/social/<characterId>/refs/back.png"
```

Les aperçus publics et le filigrane suivent `content-pipeline.md` §3 et §6 (`putPublicObject`, `copyKeyToPublicBucket` de `lib/storage/s3.ts`). Identifiants de comptes (emails, mots de passe, codes) : `account-creation.md`, jamais dans une fiche (R9).

## 9. Ce qui n'existe pas encore (renvoi `build-plan.md`)

- Aucune fiche, aucun `lib/social/`, aucune page `/c/<slug>`, aucune route `app/api/farm/personas/*`, aucun modèle `SocialAccount` / `SocialCommentPool` ; `AICharacter.publicSlug` / `isPublic` absents du schéma.
- Personnages : les six à créer from scratch sur le compte admin (Soul + LoRA) ; noms, pseudos (disponibilité, 2 replis), bios, villes et répartition `disclosed` (3/6) à valider par Nathan.
- Fanvue : aucun profil, badge et rattachement au compte maître à vérifier dans le dashboard.
- Comptes de marque TikTok, X, Reddit ; flux comment-to-DM.
- Le stock de pools (≥ 60 disponibles par personnage et par plateforme, réapprovisionné sous 20 ; pools de réponses ≥ 30 par pool) et les cinq autres fiches complètes : produits par le workflow quotidien à partir de ce format, validés par `lib/social/compliance.ts` avant insertion.

## 10. Ajouter un personnage (runbook, ≈ 3 h humaines étalées sur 10 jours)

1. **Niche** : les deux requêtes de §3.1 (skill `prod`), hors tatouage ; décision de Nathan : nom, handle + 2 replis, ville / fuseau, marché, `disclosed` (le groupe garde son équilibre 3/3 tant que le test de §3.3 court).
2. **`AICharacter`** sur le compte admin (nathannzenou@gmail.com ; `INTERNAL_API_USER_ID` de `app/api/admin/generate-batch/route.ts` doit désigner ce même utilisateur [à vérifier en prod], `content-pipeline.md` §3) : création from scratch dans le builder (`/ai-characters/create`, `intents ["sfw","nsfw"]`), jamais d'upload ; puis `soulStatus = ready` (cron `poll-souls`), LoRA `ready`, `physical_profil` renseigné — ≈ 1 jour (`documentation/characters/character-nsfw-soul-pipeline.md`).
3. `lib/social/personas/<slug>.yaml` (§1-2) puis `npm test -- lib/social/personas`.
4. Refs et moodboard sur `hiddn2/social/<characterId>/` (§8), filigrane généré (`lib/social/watermark.ts`, `content-pipeline.md` §6).
5. `POST /api/admin/social/accounts` ×4 (`status: creating`, un par plateforme).
6. `npx -y tsx scripts/social/seed-comment-pools.ts <slug>`.
7. Téléphone (`infrastructure-geelark-proxies.md` §3-4, §10) : profil GeeLark `<slug>-us`, **une** adresse IPRoyal statique neuve (ville prise dans le stock disponible ce jour-là, la fiche s'aligne ensuite), entrée Trousseau `ofmai-proxy-<slug>-static`, ligne `phones.json` — achat par Nathan.
8. SIM du personnage (`account-creation.md` §5).
9. J0 (`account-creation.md` §6.0), puis `growth-account-onboard.js` ×4 sur 8 jours (`build-plan.md` §12).
10. Fanvue : profil IA + 30 SFW / 10 PPV depuis la banque (Nathan, navigateur) avant le jour 8 (§4).
11. `growth-content-army.js --characters <slug>` dès la première variante `ready`.
12. `infrastructure-geelark-proxies.md` §8 : + ≈ 36 $/mois ; §3.2 de ce fichier mis à jour.
