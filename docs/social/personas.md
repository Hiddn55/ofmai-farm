# Personas — fiche, six personnages, Fanvue, link-in-bio, bios, compte de marque

> **Nature** : reference
> **Statut** : à vérifier — format écrit avant le build : aucune fiche n'est lue par du code, aucune page `/c/<slug>`, aucune route `app/api/farm/personas/*` n'existe
> **À jour au** : 2026-09-14
> **Répond à** : qui sont les six personnages de M1, à quoi ressemble leur fiche, où pointent leurs liens, comment ils se présentent sur chaque plateforme et sur Fanvue, et où tout cela vit dans le repo
> **Code concerné** : `lib/social/personas/*.yaml` et `lib/social/personas.ts` (à créer), `app/c/[slug]/page.tsx` (à créer), `app/api/farm/personas/[characterId]/route.ts` (à créer), `prisma/schema.prisma` (`AICharacter`, `TrackedInfluencer`, `ScrapedPost` ; `SocialAccount` et `SocialCommentPool` à créer), `lib/core/host.ts`, `lib/analytics/utm.ts`, `lib/radar/niche-labels.ts`, `lib/characters/character-create-catalog.ts`, `app/[seoLanding]/page.tsx`, `app/api/auth/[...nextauth]/route.ts`, `app/layout.tsx`, `scripts/generation/seed-ultra-loras.ts` ; fork `gitd/farm/models.py`, `gitd/farm/human.py`

La fiche persona est le seul endroit où l'on dit **qui** est un personnage : sa voix, ses interdits, son calendrier, ses comptes et ses liens. Son **physique** vit déjà dans `AICharacter` (`physical_profil`, `soulId`, `lora_name`) et n'est jamais recopié ici. Ce que la ferme en reçoit passe par `GET /api/farm/personas/{character_id}` (`bridge-ofmai-farm.md` §3.5) ; ce qu'on en génère est dans `content-pipeline.md` ; les gestes de publication et le routage des subs Reddit dans `publishing.md` ; les règles absolues dans `rules.md`.

## 1. Format de la fiche

Un fichier YAML par personnage, `slug` = `utm_content` = `/c/<slug>` = nom du fichier. Pas de secret (R10), pas de média (R34), ASCII pur pour tout ce qui sera tapé sur l'appareil (R13 : `HumanInput.type_text` de `gitd/farm/human.py` supprime tout caractère `> 127`).

| Bloc | Champs | Qui le lit |
|---|---|---|
| `slug`, `ofmai` | `character_id`, `soul_id`, `lora_name`, `trigger_word` (= colonnes `AICharacter`) | banque `ContentAsset`, pont |
| `identity` | `name`, `age`, `origin`, `city`, `timezone` (= `farm_accounts.timezone`), `market`, `language`, `signature` (2 traits + 1 trait décalé), `backstory` ≤ 80 mots, `visual_anchor`, `brand_colors` | légendes, réponses, page publique |
| `niche` | `radar` (clé `TrackedInfluencer.niche`, libellés dans `lib/radar/niche-labels.ts`), `theme`, `vehicle`, `foxy_categories`, `hashtags_niche` (CSV = `farm_accounts.niche`, recherches de détour) | programmateur, planner |
| `voice` | `tone`, `writing`, `reply_tone`, `emoji` | légendes, `comment_reply` / `dm_reply` |
| `vocabulary`, `forbidden_words` | mots qu'elle emploie ; mots interdits **en plus** de `rules.md` R11-R12 et de `checkPromptPolicy` | agent conformité (`content-pipeline.md` §8) |
| `calendar` | `mon` … `sun` → pilier Foxy + format + hook | programmateur (`content-pipeline.md` §10) |
| `comment_pools` | par plateforme, ASCII, jamais de lien ; la fiche en contient une amorce (≥ 20), le stock vivant est dans `SocialCommentPool` : **≥ 60 disponibles par personnage et par plateforme, réapprovisionnement sous 20** par le workflow quotidien (`warming-policy.md` §8) | `SocialCommentPool` (`kind = comment`) → `GET /api/farm/comments?kind=comment` |
| `reply_pools` | par plateforme, trois pools ASCII — `ai` (« yes, 100% AI »), `thanks`, `question` — ≥ 30 lignes par pool, jamais de lien | `SocialCommentPool` (`kind = reply_ai \| reply_thanks \| reply_question`) → `GET /api/farm/comments?kind=reply_*`, workflow `comment_reply` (E3.2) |
| `accounts` | par plateforme : `handle`, `content_type`, `channel` (`device` \| `api`, valeurs du pont), `bio`, `subs_*` pour Reddit | `SocialAccount`, `accounts add`, `GET /api/farm/personas` |
| `links` | link-in-bio par host, boutons avec UTM, `dm_offer` | page `/c/<slug>`, bios, comment-to-DM |
| `hashtags` | par plateforme + `always: ["#AI"]` | légendes |
| `visual_refs` | clés S3 (refs, moodboard, filigrane) | page publique, QA identité |

## 2. Exemple complet : Eva

Source : `/Users/nathannzenou/Documents/project/influenceur lab /characters/eva/profile.md` (identity tag `Eva-MdE`, 24 ans, Middle Eastern, taches de rousseur signature, aucun tatouage, créoles or en goutte, couleurs `#F5E6D3` / `#1A1A1A` / `#C9A96E`, « clean luxury minimalist, Mediterranean summer », « confident, effortlessly chic, sensual but understated ») et `dataset-prompts.md` (9 références studio 2:3, fond `#B8B8B8`).

```yaml
# lib/social/personas/eva.yaml
slug: eva                                   # = utm_content, = /c/eva
ofmai:
  character_id: null                        # AICharacter.id — à créer par upload des 9 refs (§3)
  soul_id: null                             # AICharacter.soulId (SFW, Instagram/TikTok)
  lora_name: null                           # AICharacter.lora_name (NSFW, X/Reddit)
  trigger_word: "ohwx woman eva"            # convention des LoRA du compte admin en prod
identity:
  name: Eva
  age: 24
  origin: Middle Eastern                    # jamais de nationalite precise en public
  city: New York, NY                        # = Etat du proxy statique (infrastructure-geelark-proxies.md)
  timezone: America/New_York                # = farm_accounts.timezone = fuseau GeeLark (R21)
  market: US
  language: en-US
  signature: "confident, effortlessly chic ; trait decale : rit de ses propres photos ratees"
  backstory: >-
    Grew up between the sea and a big city, moved to New York for a part-time
    job in interior design. Coffee before words, sunsets before dinner. Says she
    is an AI character whenever someone asks, and finds it funny that people ask.
  visual_anchor: dense freckles on nose and cheeks, long dark wavy hair, gold teardrop hoops, no tattoos
  brand_colors: ["#F5E6D3", "#1A1A1A", "#C9A96E"]
niche:
  radar: arabe                              # 28 comptes, 25 decollages / 301 videos (§3)
  theme: quiet luxury, Mediterranean summer in the city
  vehicle: [slow morning, cafe, rooftop, beach day, dinner out]
  foxy_categories: [Prestige, Wanderlust, Daily Life, Artsy]
  hashtags_niche: "quietluxury,ootd,nyc,summervibes"
voice:
  tone: warm, understated, a little teasing, never salesy
  writing: lowercase, 1-2 short sentences, no exclamation mark, hashtags on their own line
  reply_tone: answers like a friend, thanks in three words, never argues, never explains the tech
  emoji: none on device (ASCII) ; at most one on API channels
vocabulary:
  uses: [golden hour, slow morning, little black dress, sea salt, "no filter, just AI"]
  never: [babe, daddy, free, credits, price, real girl, "link in bio" inside a post]
forbidden_words: ["same face", "real person", "deepfake", onlyfans, fansly, "my agency"]
calendar:                                   # pilier du jour -> categorie Foxy autorisee
  mon: {pillar: Daily Life, format: reel, hook: REFLET_MIROIR}
  tue: {pillar: Prestige, format: feed}
  wed: {pillar: Wanderlust, format: reel, hook: VUE_ZENITHALE}
  thu: {pillar: Daily Life, format: feed}
  fri: {pillar: Artsy, format: reel, hook: ZOOM_PHYSIQUE}
  sat: {pillar: Prestige, format: reel, hook: ROTATION_180}
  sun: {pillar: Daily Life, format: feed}   # le jour de repos du ledger l'emporte s'il tombe ici
comment_pools:                              # ASCII pur (R13), amorce >= 20 lignes par plateforme ; stock vivant >= 60 dans SocialCommentPool
  instagram:
    - "the light in this one"
    - "ok this outfit is doing everything"
    - "need this coffee order asap"
    - "saved for my next trip"
  tiktok:
    - "the transition though"
    - "how is the weather that good"
    - "this sound with this view"
  x:                                        # commentaires de chauffe a partir de network (warming-policy.md §7)
    - "this thread is the whole mood"
    - "saving this for later"
    - "ok the framing on this"
  reddit:                                   # le karma vient d'ici (publishing.md §5)
    - "the composition on this is really clean"
    - "what lens did you use for this"
    - "this is the best one in the sub this week"
    - "saved, thanks for sharing the process"
reply_pools:                                # reponses sous ses propres posts, ASCII, >= 30 lignes par pool (comment_reply, E3.2)
  instagram:
    ai: ["yes, 100% AI and proud of it", "all AI, made on ofmai", "not real, and that is the point"]
    thanks: ["thank you", "you are sweet", "appreciate it"]
    question: ["nyc, most days", "no filter, just AI", "answered in my bio"]
  tiktok:
    ai: ["yep, fully AI", "AI character, made on ofmai"]
    thanks: ["thanks!!", "you made my day"]
    question: ["all in my bio", "asked and answered: AI"]
accounts:
  instagram: {handle: eva.moore, content_type: sfw, channel: device,
              bio: "eva, 24, nyc\nAI character, made on ofmai\nnew every day"}
  tiktok:    {handle: eva.moore, content_type: sfw, channel: device,   # api a partir du cruise (publishing.md)
              bio: "eva | 24 | nyc | AI character made on ofmai"}
  x:         {handle: evamoore_ai, content_type: nsfw, channel: api, sensitive_media: true,
              bio: "eva. 24. nyc. AI character (virtual), made on OFMAI. 18+ only. links below"}
  reddit:    {handle: eva_moore_ai, content_type: nsfw, channel: api,
              bio: "AI-generated character (virtual), 18+. Everything is on my profile.",
              subs_creators: [], subs_fans: []}          # classification des subs : publishing.md
  fanvue:    {handle: evamoore, ai_creator_badge: true, public_layer: sfw}
links:
  link_in_bio_sfw: "https://ofmai.ai/c/eva?utm_source=<plateforme>&utm_medium=bio&utm_campaign=army-2026-09&utm_content=eva"
  link_in_bio_hot: "https://hotofmai.ai/c/eva?utm_source=<plateforme>&utm_medium=bio&utm_campaign=army-2026-09&utm_content=eva"
  buttons:                                  # la page recopie les utm_* de sa query sur chaque bouton
    - {label: "my page", to: "https://www.fanvue.com/evamoore"}
    - {label: "create your own", to: "/ai-characters/create"}
  dm_offer: "https://ofmai.ai/?utm_source=instagram&utm_medium=dm&utm_campaign=army-2026-09&utm_content=eva"
  dm_text: "hey! yes, i am 100% AI, a character made on OFMAI. you can build yours, 15 free credits to start: {dm_offer}"
hashtags:
  always: ["#AI"]
  instagram: ["#quietluxury", "#nycsummer", "#ootd", "#goldenhour"]
  tiktok: ["#aiinfluencer", "#nyc", "#summer"]
  x: []
  reddit: []
visual_refs:                                # cles S3, jamais de fichier dans le repo (§8)
  refs_prefix: social/<characterId>/refs/           # bucket prive hiddn2 : les 9 eva-ref-*.png
  moodboard_prefix: social/<characterId>/moodboard/  # bucket prive hiddn2
  preview_prefix: social/<characterId>/preview/      # bucket public hiddn2-public (page /c/eva)
  watermark: social/watermarks/<characterId>.png     # bucket public (content-pipeline.md §6)
```

`<plateforme>` est remplacé au moment de poser le lien (`instagram`, `tiktok`, `x`, `reddit`) ; `dm_text` reste en une phrase, sans nom de fournisseur, et l'offre « 15 crédits » est le bonus d'inscription existant (`app/api/auth/[...nextauth]/route.ts` l. 114-135 : `purchasedCredits: 15`, « Welcome credits ») — rien à construire.

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

### 3.2 Les six

| Slug | Nom | Identité visuelle (vérifiée sur `face.png` / `profile.md`) | Niche radar | Ville / fuseau | État OFMAI en prod (compte admin) |
|---|---|---|---|---|---|
| `kelly` | Kelly | blonde, yeux verts pailletés d'or, taches de rousseur, hâlée | `fitness` | Los Angeles, CA / `America/Los_Angeles` | `cmpzdheu1000do822tglsbgak` : Soul `ready` + LoRA (`ohwx woman Kelly`), `intents {sfw,nsfw}` |
| `tal` | Tal | brune, yeux noisette, taches de rousseur denses, sourcils épais, créoles or | `latina` [à valider par Nathan] | Miami, FL / `America/New_York` | `AICharacter` **`test`** `cmo2p80r603nws71zi6mkkvg1` : LoRA, pas de Soul (`scripts/generation/seed-ultra-loras.ts` l. 32-33 : « la LoRA du personnage "test" s'appelle "Tal" ») ; `loraUltraStatus` vide [à vérifier] |
| `eva` | Eva (`Eva-MdE`) | brune, yeux noisette, taches de rousseur signature, aucun tatouage | `arabe` | New York, NY / `America/New_York` | **aucune ligne** : la ligne `eva` `cmn92qq3x013zpj1zzrvwu13j` est une autre identité (`physical_profil` : « vivid blue eyes … zero freckles ») ; à créer par upload |
| `roxy` [nom à valider] | Roxy | manches tatouées, brune, piercing nez | `tatouee` | Austin, TX / `America/Chicago` | à créer from scratch (`BODY_FEATURES = ["tattoos"]` dans `lib/characters/character-create-catalog.ts`) |
| `lexi` [nom à valider] | Lexi | e-girl : cheveux mi-noir mi-rose, eyeliner, setup gaming, non asiatique | `e-girl` | Seattle, WA / `America/Los_Angeles` | à créer from scratch |
| `hana` [nom à valider] | Hana | asiatique, longs cheveux noirs, lumière douce, minimal | `asiatique` | San Francisco, CA / `America/Los_Angeles` | à créer from scratch |

Plateformes pour les six : Instagram + TikTok (SFW, Soul, → ofmai.ai) ; X + Reddit (18+, LoRA, → hotofmai.ai / Fanvue) ; Fanvue. Marché : US pour tous (proxy, GPS, fuseau et langue alignés, R21) ; la ville de la fiche est l'État du proxy statique.

Pourquoi ces trois nouvelles niches, dans cet ordre :

- **Tatouée** : première niche du radar en comptes (218) et en vues médianes par vidéo (343 436). Attribut visuel permanent qui la sépare des trois existantes — Kelly, Tal et Eva ont **toutes trois** les taches de rousseur pour ancre (`physical_profil` de Kelly : « ANCHOR: dense natural freckles »). Risque propre : la tenue des tatouages d'une génération à l'autre → 20 images de test et QA identité avant validation (`content-pipeline.md` §5).
- **E-girl** : 22 décollages sur 452 vidéos, le plus haut de tout le radar, face aux plus petits comptes en place (86 041 abonnés médians) : la niche où un compte neuf perce. TikTok-native. Non asiatique pour ne pas chevaucher `e-girl asiatique` (59 comptes) ni Hana.
- **Asiatique** : 207 748 vues médianes par vidéo, 147 comptes, aucun hashtag de détour en commun avec les cinq autres. Retenue devant `bimbo` (211 / 287 516 / 8) parce que Kelly occupe déjà la blonde et parce que le look « fait » plombe la conversion (`documentation/notes/ofm-playbook/01-niche-persona.md`, P4). Remplaçantes : `bimbo` pour Hana, `gothique` (11 décollages) pour Lexi ; `bbw-curvy` écartée (abonnés médians 557 081 : les comptes en place sont énormes, 5 décollages).
- Existantes : Kelly → `fitness` (261 733 vues méd./vidéo, le look Californie) ; Tal → `latina` (la plus grosse audience par compte, 107 811, mais 1 seul décollage : Tal joue le volume, pas la percée) ; Eva → `arabe` (« Middle Eastern » de `profile.md` ; petite niche mais 25 décollages / 301 vidéos, le meilleur ratio du radar).

Prérequis avant tout compte : chaque personnage a un Soul `ready` **et** une LoRA (pipelines dans `documentation/characters/character-nsfw-soul-pipeline.md` ; `CHAR_SOUL_TRAINING 17` cr, `CHAR_LORA_TRAINING 50` cr, `CHAR_SOUL_MIGRATE 15` cr, 0 cr par le chemin admin [à vérifier]). Eva entre par upload de ses 9 `eva-ref-*.png` (`creationMethod = "upload"`, `characterOrigin = "ai_imported"`) — sa LoRA locale `zimage_character_ohwx_v1.safetensors` n'est pas au format OFMAI (`lora_name` SDXL / `loraUltra` Krea 2) et ne sert pas. Tal n'a pas de Soul : migration ou entraînement sur ses `face/front/back.png`. Les six sont `ai_native` ou `ai_imported`, jamais `real_person` (R1-R2).

## 4. Page Fanvue

- **Un compte maître = l'opérateur** (Nathan, pièce d'identité vérifiée par Fanvue) ; les personnages sont des profils IA rattachés au maître (`ofm-playbook/02-comptes-setup.md` §1 : « You only need an ID to create the main account… multiple AI accounts that are linked », 2 sources sur 25) [à vérifier dans le dashboard Fanvue : profil enfant par personnage, ou un compte par personnage sous la même pièce d'identité]. Aucun personnage n'a de pièce d'identité propre : c'est ce qui rend R1 tenable.
- **Badge « AI creator »** déclaré à l'inscription (même source : « Fanvue impose la divulgation, AI Creator à l'inscription »), jamais retiré (R3). Le nom affiché est le prénom seul ; la bio Fanvue est la bio X en version longue (§6).
- **Couche publique SFW** : avatar, bannière (format long, corps entier), bio, 10-15 posts gratuits lifestyle / maillot ; le 18+ uniquement derrière l'abonnement ou le PPV. C'est la condition pour que le bouton Fanvue soit acceptable depuis un link-in-bio Instagram / TikTok (R24 : jamais de « Fanvue 18+ » depuis une origine SFW) [à vérifier : Meta suit les redirections jusqu'à la destination finale, la couche publique doit rester SFW en permanence].
- **Structure de l'offre** : page gratuite (« sorting machine », consensus du playbook) + PPV ; pas d'abonnement payant en V1 (minimum Fanvue 3,99 $ d'après le playbook [à vérifier], commission 15 %). Stock de lancement par personnage : 30 posts SFW + 10 PPV NSFW sortis de la banque (`content-pipeline.md`), tous filigranés, identité tenue par le Soul / la LoRA.
- **Lien « made with »** vers ofmai.ai avec `utm_source=fanvue&utm_medium=profile&utm_content=<slug>` (`metrics-attribution.md` §2). Les revenus Fanvue ne comptent pas dans les seuils J4 / J7 / J14.
- **Interdits** : image de vérification à pancarte, likes achetés ou groupes like-for-like (playbook, § « non recommandé »), contenu 18+ d'un personnage sans sa LoRA OFMAI.
- URL de profil : `https://www.fanvue.com/<handle>` [à vérifier : le code ne connaît que `/app-store/details/<uuid>` et `/signup`, `lib/fanvue/fanvue-deeplinks.ts`].

## 5. Link-in-bio

Décision : **pas d'agrégateur**, une page auto-hébergée `app/c/[slug]/page.tsx` servie sur les deux hosts. Raisons (`02-comptes-setup.md` §1.6) : Instagram suit les redirections des agrégateurs jusqu'à la destination finale ; plusieurs agrégateurs ont été bannis ; domaine propre + redirection JavaScript (le crawler Meta n'exécute pas le JS) ; écran 18+ obligatoire côté HOT. Et cela lève le [à vérifier] de `metrics-attribution.md` §2 : notre page relaie la query string à ses boutons.

- `/c/` et pas `/<slug>` : `app/[seoLanding]/page.tsx` est le segment dynamique racine et renvoie 404 pour tout slug absent de son registre ; un `/eva` entrerait en collision.
- Par host (`isSFWHost`, `lib/core/host.ts`) : **ofmai.ai** → vitrine SFW : portrait (`AICharacter.sfwFaceUrl`, bucket public), « 100 % AI character, made on OFMAI », trois boutons — « my page » (Fanvue, couche publique SFW), « create your own » (`/ai-characters/create`), l'autre réseau SFW du personnage ; **hotofmai.ai** → gate 18+ (choix mémorisé en `localStorage`, `try/catch`), puis Fanvue, « create the same (18+) », X.
- UTM : le lien de bio porte `utm_source=<plateforme>&utm_medium=bio&utm_campaign=army-2026-09&utm_content=<slug>` (`instagram` pour Instagram, tranché dans `metrics-attribution.md` §1 ; le garde E10.1 est déployé avant le premier lien) ; la page recopie `utm_*` sur chaque bouton avec `appendUtm()` (`lib/analytics/utm.ts`), navigation par JS, jamais de 302 serveur.
- Aperçus : `social/<characterId>/preview/*.webp` sur `hiddn2-public` (`content-pipeline.md` §3). Rien de NSFW n'est rendu sur ofmai.ai, même derrière un clic (R5).
- Moment de pose du lien et du texte de bio : `account-creation.md` ; jamais de lien ailleurs qu'en bio avant le cruise (R23).

## 6. Bios par plateforme et divulgation IA

| Plateforme | Limite [à vérifier] | Divulgation | Exemple (Eva) | Tapée sur l'appareil |
|---|---|---|---|---|
| Instagram | 150 car. | « AI character » en bio, `#AI` en légende, auto-déclaration IA à la publication [à vérifier depuis l'app] | `eva, 24, nyc / AI character, made on ofmai / new every day` | oui → ASCII |
| TikTok | 80 car. | toggle AIGC à chaque post (R3-R4) + mention en bio | `eva \| 24 \| nyc \| AI character made on ofmai` | oui → ASCII |
| X | 160 car. | « AI character (virtual) » en bio, réglage média sensible activé **avant** le premier post, nom et bio neutres (`lib/seo/academy/platforms.ts`, leçon X) | `eva. 24. nyc. AI character (virtual), made on OFMAI. 18+ only. links below` | oui → ASCII |
| Reddit | 200 car. | « AI-generated character » en bio ; flair / tag IA du sub quand il existe (`publishing.md`) | `AI-generated character (virtual), 18+. Everything is on my profile.` | oui → ASCII |
| Fanvue | — | badge « AI creator » + bio longue (80-120 mots, backstory + « made on OFMAI ») | version longue de la bio X | non (navigateur) |

Règles : une bio, une photo de profil, un pseudo **différents** par compte et par personnage (playbook §1.11 : des comptes bannis pour des highlights identiques) ; jamais « OnlyFans », « Fansly », « agency », ni un prix ; jamais « same face » ni un nom de fournisseur (R11-R12) ; le mot « ofmai » en bio est du texte, pas un lien ; sur X, rien de suggestif dans le nom, la bio, l'avatar ou la bannière (ils s'affichent hors du réglage sensible). Le playbook note qu'une agence retire « AI » de ses bios (tristanmodelify) : décision contraire ici, prise dans le brief (décision 7) — la persona ne se cache pas, le comment-to-DM répond justement « 100 % IA ».

Comment-to-DM (Instagram, API officielle Meta via ManyChat ou équivalent, `publishing.md`) : un commentaire contenant `real`, `how`, `ai` ou `tool` déclenche `dm_text` de la fiche, 200 DM/h max, jamais sans action de l'utilisateur, lien `dm_offer` (`utm_medium=dm`).

## 7. Compte de marque OFMAI par plateforme

| Plateforme | Handle | État | Rôle |
|---|---|---|---|
| Instagram | `@ofmai_app` | existe (`app/layout.tsx` l. 179, `sameAs`) | making-of, résultats, réponses aux « how » |
| TikTok | `@ofmai.app` | à créer [à vérifier disponibilité] | idem, coupes des clips des personnages avec label AIGC |
| X | `@ofmai_ai` | à créer | making-of + liens hotofmai.ai |
| Reddit | `u/ofmai_official` | à créer | subs créateurs / art IA seulement |

Modèle : une ligne `SocialAccount` par compte avec `role = "brand"`, `characterId = null`, `contentType = sfw` sauf X (`bridge-ofmai-farm.md` §5.1) ; **hors chauffe** : ligne `farm_accounts` facultative (`accounts add … --role brand`, `enabled = 0`, jamais planifiée par `planner.tick`, E1.1), aucune session ; publication depuis l'appareil de Nathan ou par API depuis le Mac mini, sur un profil GeeLark « brand » avec sa propre IP (décision de la vague 0 : profil `brand-us` + IP ≈ 32 $/mois, ou le téléphone de Nathan) — jamais le téléphone ni l'IP d'un personnage (R9, R19). La marque peut taguer les personnages ; un personnage ne tague jamais la marque (le lien ne va que dans un sens, la divulgation passe par « made on ofmai » en bio). Liens sortants : `utm_source=<plateforme>&utm_medium=post&utm_campaign=army-2026-09&utm_content=brand`. Le contenu de marque suit `rules.md` comme le reste : aucun nom de fournisseur dans un making-of, jamais « même visage ».

## 8. Où la fiche vit

```
lib/social/
├── personas/                 eva.yaml, kelly.yaml, tal.yaml, roxy.yaml, lexi.yaml, hana.yaml
├── personas.ts               loadPersona(slug), personaForCharacter(characterId), toFarmPersona(p)
├── personas.test.ts          les 6 fiches valident le schéma ; ASCII des pools et bios `device` ; aucun mot de R11-R12
└── compliance.ts             (content-pipeline.md §8)
app/c/[slug]/page.tsx         page publique / link-in-bio (§5)
app/api/farm/personas/[characterId]/route.ts   sous-ensemble servi à la ferme (bridge §3.5)
```

- Schéma validé avec `zod` (`package.json` : `^4.2.1`) ; parseur YAML : `js-yaml` est dans `node_modules` mais absent des `dependencies` [à vérifier : transitif] — l'ajouter, ou écrire les fiches en `.ts` typés si on préfère zéro dépendance.
- `toFarmPersona()` ne renvoie que `handles`, `bio`, `niche`, `forbidden_words`, `reply_tone`, `links` : la ferme ne voit ni le calendrier ni les pools entiers (ils passent par `GET /api/farm/comments`).
- `SocialCommentPool` est **alimentée** depuis `comment_pools` et `reply_pools` par un script idempotent (`scripts/social/seed-comment-pools.ts`, clé `(characterId, platform, kind, text)`), jamais lue depuis le YAML à chaud ; le réapprovisionnement quotidien (≥ 60 / sous 20) est fait par `growth-content-army.js`, phase Pools.
- Médias : rien dans `lib/social/` ni `public/`. Les dossiers locaux (`Marketing/communication/character/{kelly,Tal}`, `influenceur lab/characters/eva/{references,lifestyle}`) sont la source de l'upload, pas une référence d'exécution.

```bash
# refs d'Eva vers le bucket privé, une fois AICharacter créé (<characterId> = son id)
aws s3 cp "/Users/nathannzenou/Documents/project/influenceur lab /characters/eva/references/" \
  "s3://hiddn2/social/<characterId>/refs/" --recursive --exclude "*" --include "eva-ref-*.png"
```

Les aperçus publics et le filigrane suivent `content-pipeline.md` §3 et §6 (`putPublicObject`, `copyKeyToPublicBucket` de `lib/storage/s3.ts`). Identifiants de comptes (emails, mots de passe, codes) : `account-creation.md`, jamais dans une fiche (R10).

## 9. Ce qui n'existe pas encore (renvoi `build-plan.md`)

- Aucune fiche, aucun `lib/social/`, aucune page `/c/<slug>`, aucune route `app/api/farm/personas/*`, aucun modèle `SocialAccount` / `SocialCommentPool`.
- Personnages : Eva et Tal sans Soul (Eva sans ligne du tout) ; Roxy, Lexi, Hana à créer ; noms, handles et disponibilité des pseudos à valider par Nathan.
- Fanvue : aucun profil, badge et rattachement au compte maître à vérifier dans le dashboard.
- Comptes de marque TikTok, X, Reddit ; flux comment-to-DM.
- Le stock de pools (≥ 60 disponibles par personnage et par plateforme, réapprovisionné sous 20 ; pools de réponses ≥ 30 par pool) et les bios des cinq autres personnages : produits par le workflow quotidien à partir de ce format, validés par `lib/social/compliance.ts` avant insertion.

## 10. Ajouter un personnage (runbook, ≈ 3 h humaines étalées sur 10 jours)

1. **Niche** : les deux requêtes de §3.1 (skill `prod`), décision de Nathan : nom, handle + 2 replis, ville / fuseau, marché.
2. **`AICharacter`** sur le compte opérateur (`INTERNAL_API_USER_ID`, `content-pipeline.md` §3) : upload des références **depuis le poste de Nathan** (les dossiers `Marketing/communication/character/*` et `influenceur lab/characters/*` sont hors repo et absents du Mac mini) ou création from-scratch ; puis `soulStatus = ready` (cron `poll-souls`), LoRA `ready`, `physical_profil` renseigné — ≈ 1 jour (`documentation/characters/character-nsfw-soul-pipeline.md`).
3. `lib/social/personas/<slug>.yaml` (§1-2) puis `npm test -- lib/social/personas`.
4. Refs et moodboard sur `hiddn2/social/<characterId>/` (§8), filigrane généré (`lib/social/watermark.ts`, `content-pipeline.md` §6).
5. `POST /api/admin/social/accounts` ×4 (`status: creating`, un par plateforme).
6. `npx -y tsx scripts/social/seed-comment-pools.ts <slug>`.
7. Téléphone (`infrastructure-geelark-proxies.md` §3-4, §10) : profil GeeLark `<slug>-us`, 2 proxies IPRoyal neufs, entrées Trousseau, ligne `phones.json` — achat par Nathan.
8. SIM du personnage (`account-creation.md` §5).
9. J0 (`account-creation.md` §6.0), puis `growth-account-onboard.js` ×4 sur 8 jours (`build-plan.md` §12).
10. Fanvue : profil IA + 30 SFW / 10 PPV depuis la banque (Nathan, navigateur) avant le jour 8 (§4).
11. `growth-content-army.js --characters <slug>` dès la première variante `ready`.
12. `infrastructure-geelark-proxies.md` §8 : + ≈ 40 $/mois ; §3.2 de ce fichier mis à jour.
