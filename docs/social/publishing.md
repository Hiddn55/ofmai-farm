# Publication — app ou API, geste par geste, par plateforme

> **Nature** : reference
> **Statut** : à vérifier — les workflows `post_video` existent dans le fork mais n'ont jamais tourné sur un appareil (`tested_on: []`) et ignorent le drapeau `aigc_label` de la file ; rien n'existe pour X, Reddit, le comment-to-DM ni les réponses
> **À jour au** : 2026-09-14
> **Répond à** : pour chaque geste (post, story, réponse à un commentaire, DM entrant, like en retour) et chaque plateforme, qui l'exécute (le téléphone du personnage ou une API depuis le Mac mini), avec quelles limites, à quelle heure, avec quel lien
> **Code concerné** : fork `gitd/skills/ofmai_instagram/workflows/__init__.py`, `gitd/skills/ofmai_instagram/elements.yaml`, `gitd/skills/ofmai_tiktok/workflows/__init__.py`, `gitd/skills/ofmai_tiktok/elements.yaml`, `gitd/farm/policy.py`, `gitd/farm/planner.py`, `gitd/farm/models.py`, `gitd/farm/health.py` ; OFMAI `lib/ingest/instagram-proxy.ts`, `lib/analytics/utm.ts`, `app/api/attribution/route.ts`, `app/api/farm/` (à créer), `scripts/social/` (à créer), `.claude/workflows/growth-content-army.js` (à créer) ; outils MCP `tiktok_connect`, `tiktok_accounts`, `tiktok_prepare_publish`, `tiktok_publish`, `tiktok_publish_status`, `media_upload`, `media_import_url`

Ce fichier ne décrit que le geste de publication et les réponses. Le média arrive prêt, **avec sa légende et son drapeau `aigc_label`** (`content-pipeline.md`), par la file `GET /api/farm/queue` (`bridge-ofmai-farm.md`) : la ferme ne génère rien et n'écrit rien (§1.1, §1.2) ; les caps et phases sont dans `warming-policy.md` ; les liens sont mesurés selon `metrics-attribution.md` ; les interdits sont dans `rules.md` (R2, R3, R12, R15, R16, R21-R24).

## 1. La décision : qui fait quoi

| Geste | Instagram | TikTok en chauffe | TikTok en `api_mode` | X | Reddit |
|---|---|---|---|---|---|
| Post (Reel / vidéo / image) | appareil, `post_video` | appareil, `post_video` | API via MCP (§3) | API v2 (§4) | API (§5) |
| Story | appareil, `post_story` à créer (élément `your_story` existe, aucun workflow) | pas de stories dans le skill | — | — | — |
| Réponse à un commentaire sous son post | appareil, `comment_reply` à créer | appareil, `comment_reply` à créer | appareil (consommation légère) | API, `reply.in_reply_to_tweet_id` | API, `POST /api/comment` |
| DM entrant | comment-to-DM Meta (§8) + `dm_reply` sur l'appareil à créer | `dm_reply` sur l'appareil à créer | idem | pas de réponse automatique en V1 | pas de réponse automatique en V1 |
| Like en retour (le commentaire reçu) | appareil, dans `comment_reply` | appareil, dans `comment_reply` | appareil | appareil seulement (skill `ofmai_x` à créer) | jamais (règle Reddit sur la manipulation de votes) |
| Like / follow / commentaire chez les autres (chauffe) | appareil, `warm_session` | appareil, `warm_session` | appareil, `warm_session` | appareil, skill à créer | appareil, skill à créer |

Pourquoi ce partage :

- **Instagram reste sur l'appareil** : l'API Graph exige un compte Business relié à une Page et une revue Meta de 2-4 semaines (décision du brief) ; le workflow `post_video` existe déjà.
- **TikTok passe à l'API après la chauffe** : l'appareil est plafonné à `POST: 1` par jour et `posts_per_week` 0/0/3/7 (`gitd/farm/policy.py` l. 68, 140) ; l'API accepte 13 posts par 24 h, pose le label IA par `is_aigc` = `aigc_label` de la publication (§1.1) et renvoie un `publish_id`. Tant qu'un compte est en `api_mode = 1`, `planner.tick` le saute (`gitd/farm/planner.py` l. 85) : la consommation légère est planifiée à part (`warming-policy.md`).
- **X et Reddit publient par API** : aucun skill `ofmai_x` / `ofmai_reddit` n'existe (`gitd/farm/cli.py` ne connaît que `instagram` et `tiktok`) ; une API officielle renvoie l'id du post (indispensable à `metrics_pull` et aux canaris, `health-canaries.md`) et accepte l'Unicode. Le risque n'est pas l'API, c'est l'IP : d'où la sortie par l'IP statique du personnage (R21).
- **Les likes et follows ne passent jamais par une API** : c'est exactement ce qui a fait bloquer @potter_society (R16). Répondre sous son propre post est une écriture, comme le post ; liker et suivre restent des gestes de scroll, sur l'appareil.
- **Répondre à un DM n'est jamais spontané** : un DM part uniquement après une action de l'utilisateur (commentaire, message reçu).

### 1.1 Divulgation IA : 3 personnages sur 6, Fanvue toujours

Sur Instagram, TikTok, X et Reddit, **3 personnages se déclarent IA** (mention en bio, `#AI` ou « AI » dans la légende, toggle AIGC TikTok / `is_aigc: true`) et **3 ne le font pas** — aucune mention, aucun toggle, aucun `#AI` — pour comparer les deux groupes (vues, inscrits, payants par groupe : `metrics-attribution.md`). Deux groupes, deux noms, les mêmes partout : `declared` = `sierra` (fitness), `camila` (latina), `hana` (asiatique) ; `undeclared` = `skyler` (bimbo), `riley` (e-girl), `vera` (gothique) — slugs de `personas.md` §3.2 (seule source, **à valider**), groupe dérivé du booléen `disclosed` de la fiche. **Sur Fanvue, les six sont déclarés** (badge « AI creator », obligatoire), quel que soit le groupe.

La source de vérité est le champ `disclosed` de la fiche persona (`personas.md`) : il commande les bios et la rédaction des légendes côté OFMAI, et il est **figé publication par publication** dans `SocialPublication.aigcLabel` à la mise en file. La ferme, elle, ne lit jamais la fiche au moment du post : elle lit le champ `aigc_label` de l'item de `GET /api/farm/queue` (`bridge-ofmai-farm.md` §3.2), qu'elle recopie tel quel dans `params.aigc_label` (appareil, §2) ou dans `is_aigc` (API, §3) ; il ne se déduit jamais du texte de la légende. Ce que le groupe commande, geste par geste :

| Geste | `declared` (`disclosed = true`) | `undeclared` (`disclosed = false`) |
|---|---|---|
| Légende (écrite côté OFMAI, §1.2) | contient `#AI` ou « AI » | ne contient ni `#AI`, ni « AI », ni « made on OFMAI » |
| Bio | mention « AI » (`personas.md`) | aucune mention |
| Filigrane du média (`content-pipeline.md` §6) | `@<handle> · AI` | `@<handle>` seul |
| TikTok sur l'appareil (`post_video`, §2) | `params.aigc_label = true` → toggle « AI-generated content » activé, précondition de « Post » | `params.aigc_label = false` → toggle **jamais touché** |
| TikTok par API (§3) | `is_aigc: true` | `is_aigc: false` |
| X (§4, §7) | « AI » dans la légende, mention OFMAI permise dès J15 | ni « AI » ni mention OFMAI, lien Fanvue seul |
| Reddit (§5) | subs `creators` et `fans`, flair « AI » du sub quand il existe | subs `fans` seulement (un post « making-of » est une divulgation), et **jamais un sub dont le flair IA est obligatoire** (§5) |
| Comment-to-DM Instagram (§8) | actif dès J15 | jamais configuré |
| « are you real? » (§9) | « 100% AI, and proud of it » (pool `reply_ai`) | commentaire ignoré, pool `reply_ai` vide |

Un personnage non déclaré ne nie jamais être une IA : il ne répond pas à la question, c'est tout. **`disclosed` ne change pas pendant le test** (les métriques par groupe seraient faussées), sauf deux cas : (a) un compte `undeclared` sanctionné par la plateforme pour contenu IA non étiqueté se déclare dans l'heure — bascule individuelle, `disclosed_since` daté, et ce compte sort de la comparaison (`metrics-attribution.md` §8.3) ; (b) la décision de J21, qui peut déclarer les six (fin du test). Dans les deux cas, le changement passe par la fiche persona et redescend par la file, jamais par une légende ou un réglage posé à la main sur l'appareil.

### 1.2 La légende arrive avec l'asset : la ferme ne l'écrit pas, ne la modifie pas

La légende est écrite **côté OFMAI** par le workflow de contenu (`content-pipeline.md` §7 : un modèle de langage avec la fiche persona — voix, tics, interdits — et les règles de la plateforme cible — longueur, hashtags, pas de lien, tag NSFW, mention IA selon `disclosed`), en s'inspirant de la légende du post source du radar ; elle passe l'agent conformité (aucun nom de fournisseur, jamais « même visage », `content-pipeline.md` §8) et elle est **stockée avec l'asset** (`ContentAssetVariant.caption`, figée dans `SocialPublication.caption` à la mise en file). Elle arrive à la ferme dans le champ `caption` de chaque item de `GET /api/farm/queue`, déjà ASCII quand `channel = device` (`bridge-ofmai-farm.md` §3.2).

La ferme la poste **telle quelle** : `post_video` la reçoit en paramètre et la tape (`HumanInput.type_text`), le publieur API la passe dans `description` (TikTok), `text` (X) ou `title` (Reddit). Aucun code de la ferme ni du publieur ne compose, complète, tronque, traduit ni « améliore » une légende ; il n'ajoute ni hashtag, ni `#AI`, ni lien. Une légende vide est refusée avant tout geste (`PostReelAction.precondition` / `PostVideoAction.precondition` renvoient `False` sans `caption` ; côté API → `failed`, `error = "missing_caption"`), jamais remplacée par un texte de repli. Les seuls autres textes publiés par la ferme, les réponses aux commentaires (§9), viennent eux aussi d'OFMAI : pools `SocialCommentPool` servis par `GET /api/farm/comments` (`bridge-ofmai-farm.md` §3.4), jamais d'une rédaction sur le Mac mini.

## 2. Sur l'appareil : `post_video`, ce qui existe et ce qui manque

Un seul workflow par skill, même signature : `params: {handle, caption}` (`skill.yaml`, `caption` requis ; `caption` = le champ `caption` de l'item de file, recopié sans modification, §1.2 ; le paramètre `aigc_label` reste à ajouter, §1.1 et E3.5 — même nom que dans la file, recopié tel quel par le pont, jamais relu depuis la fiche persona ; seul le workflow TikTok s'en sert, pour le toggle, Instagram n'ayant pas de label IA natif). Il publie **l'élément le plus récent de la galerie** — c'est pourquoi le pont pousse un seul média à la fois par appareil (`bridge-ofmai-farm.md` §6).

```sh
# Mac mini, à la main ; en production c'est le pont qui enqueue le job (trigger "farm")
# caption = la légende reçue de la file, telle quelle ; exemple : Sierra Cole, le personnage fitness, groupe declared (§1.1)
PYTHONPATH=. python gitd/skills/_run_skill.py --skill ofmai_instagram --workflow post_video \
  --device R58N1234 --params '{"handle":"sierra.cole","caption":"post-run glow. yes it is AI, made on ofmai.ai #AI #fitness","aigc_label":true}'
```

Instagram, `PostReelAction` (`gitd/skills/ofmai_instagram/workflows/__init__.py`) : `ledger.open_session("instagram", handle)` → `session.allow(policy.POST)` sinon erreur `post budget exhausted for this day/week` → lancement par `monkey -p com.instagram.android` → `create_tab` (« Create ») → `create_reel` (« REEL ») → `gallery_first_item` → 2× `next_button` → `caption_input` (« Write a caption... ») → `type_text` → back → `share_button_final` (« Share ») → `sleep(8)` → `session.record(policy.POST, caption[:40])`. Postcondition : plus aucun nœud `Share` à l'écran. `max_retries = 1`.

TikTok, `PostVideoAction` (`gitd/skills/ofmai_tiktok/workflows/__init__.py`) : `open_session("tiktok", …)` → `allow(POST)` → `open_feed()` → `create_tab` → `upload_button` (« Upload ») → `gallery_first_item` (sinon tap à 0,17 w / 0,30 h) → jusqu'à 3× « Next » → `caption_input` (« Describe your video ») → `type_text` → back → `_tap_text(xml, "AI-generated content")` **si visible, sans relecture et quel que soit le personnage** (l. 91 : le workflow ne reçoit pas encore `aigc_label`, à corriger, §1.1 et E3.5) → « Post » → `sleep(8)` → `record(POST)`. Postcondition : plus de « Describe your video ».

Ce que le code garantit : le cap `POST` du jour (1), le cap hebdomadaire (`BudgetTracker.allow` refuse si `posts_this_week ≥ posts_per_week`), le jour de repos (tous les caps à 0), la santé (`open_session` lève `PermissionError` si `can_run()` est faux), le refus d'une légende vide (`precondition`), la frappe ASCII (`HumanInput.type_text`, R12 — la légende arrive déjà ASCII, §1.2).

Ce qui manque (tâches dans `build-plan.md`) :

- aucun `adb push` du média ni scan de la galerie : le pont le fait avant d'enqueuer (`bridge-ofmai-farm.md` §6, étape 2) ;
- aucun id de post récupéré : `posted.post_id` est `null` sur l'appareil ; le relevé de métriques se fait donc par la grille du profil (`metrics-attribution.md` §5.2) ;
- le toggle AIGC TikTok n'est ni paramétré ni vérifié : il est tapé dès qu'il est visible, pour tous les personnages. Il faut un paramètre `aigc_label` sur `post_video` — le booléen `aigc_label` de l'item de `GET /api/farm/queue`, recopié par le pont dans `params.aigc_label`, figé sur `SocialPublication.aigcLabel` à la mise en file et jamais relu depuis la fiche persona (§1.1) : toggle activé si `true`, jamais touché si `false`, et l'état du toggle devient une précondition de « Post » (E3.5). Tant que `tested_on` est vide, **un humain regarde chaque post TikTok publié depuis l'appareil** (R3), pour les deux groupes ;
- pas de photo (élément `create_post` « POST » présent dans `elements.yaml`, aucun workflow), pas de story, pas de carrousel : sur l'appareil, aujourd'hui = Reels et vidéos seulement ; les images SFW d'Instagram attendent `post_photo` (E3.6) et les stories `post_story` (E3.4) ; le pont choisit le workflow d'après `SocialPublication.format` (`bridge-ofmai-farm.md` §6, étape 3) ;
- pas de label « IA » natif Instagram (aucun élément) : pour un personnage déclaré, la divulgation passe par `#AI` dans la légende (écrite côté OFMAI, §1.2) et la mention en bio ; pour un personnage non déclaré, rien (§1.1) [à vérifier : position du label « Made with AI » dans l'app au moment du test, et si Instagram le pose de lui-même sur un média détecté comme IA] ;
- les sélecteurs des deux `elements.yaml` sont écrits depuis les labels en-US et jamais testés (`tested_on: []`, R34) ; un appareil en autre langue ne trouve rien.

Premier post possible sur l'appareil : jour 8 sur Instagram (phase `network`), jour 14 sur TikTok (`PHASE_EXTRA_DAYS = {"tiktok": 3}` → network 14-23). Un échec `success=False` non ambigu est relancé au plus une fois par le pont ; « Share » tapé sans postcondition → `needs_human`, jamais de relance (`bridge-ofmai-farm.md` §7).

## 3. TikTok par API (`api_mode`)

Bascule : `PATCH /api/admin/social/accounts/{id} {"apiMode": true}` (E7.2, source de vérité `SocialAccount.apiMode`), recopié par le pont dans `farm_accounts.api_mode` (`gitd/farm/models.py` l. 37) au tick suivant, au plus tôt en phase `cruise` (jour 24 TikTok, `warming-policy.md` §13). Le compte reçoit alors ses publications avec `channel: "api"` dans `GET /api/farm/queue?channel=api` ; l'appareil ne fait plus que de la consommation légère.

Le publieur est l'agent de `growth-publish-api.js` (`build-plan.md` §12), lancé toutes les 3 h entre 07:00 et 23:00 ET, qui appelle les outils du MCP `claude.ai higgsfield`. Préalable vérifié en vague 3 : `claude -p "liste les outils tiktok_*"` sur le Mac mini renvoie `tiktok_connect` [à vérifier : connecteurs claude.ai disponibles en mode non interactif] ; sinon, repli : TikTok reste sur l'appareil (`post_video` avec la précondition AIGC d'E3.5, 1 post/jour, `apiMode` jamais activé) et le cap TikTok de `warming-policy.md` §11 tombe à 1. Un connecteur par personnage : `tiktok_connect` sans `name` pour le premier compte, `name: "tiktok-<slug>"` pour les suivants (l'outil n'accepte un `name` que pour un deuxième compte). Vérifié dans les descriptions d'outils au 2026-09-14 :

| Étape | Outil | Ce qu'il faut savoir |
|---|---|---|
| 0. Connexion (une fois) | `tiktok_connect` → `authorize_url` (expire en ~10 min) | l'URL s'ouvre **dans le navigateur du téléphone du personnage**, connecté au compte, pour que l'octroi OAuth vienne de son IP [à vérifier : l'outil parle d'un navigateur, pas d'un appareil] ; puis `tiktok_accounts` doit montrer `active` ; `error` → `tiktok_reconnect` |
| 1. Hébergement du média | `media_import_url` (HTTPS, ≤ 50 Mo) sur l'URL signée `media.url` de la file (TTL 3 h) ou `media_upload` (PUT présigné puis `media_confirm`) | `tiktok_prepare_publish` exige un asset hébergé chez le fournisseur (domaine source vérifié par TikTok) ; [à vérifier : `media_import_url` renvoie un `media_id`, l'URL à passer en `video_url` s'obtient par `show_medias`] |
| 2. Préparation | `tiktok_prepare_publish` `{connector_id, mode: "DIRECT_POST", media_type: "VIDEO" \| "PHOTO", video_url \| photo_images[], title ≤ 150, description ≤ 4000 (= `caption` de la file, telle quelle), is_aigc: <aigc_label>, privacy_level: "PUBLIC_TO_EVERYONE"}` | renvoie `publish_session_id`, les `privacy_level_options` et `required_confirmations` ; durée, taille et fps sont mesurés ici, avant de consommer un créneau |
| 3. Publication | `tiktok_publish` `{connector_id, publish_session_id, mode, media_type, is_aigc: <aigc_label>, privacy_level, user_confirmed: true, preview_confirmed: true, …}` + chaque drapeau de `required_confirmations` à `true` | renvoie `publish_id` ; `music_sound_id` (de `tiktok_music_trending`) seulement en `DIRECT_POST` |
| 4. Statut | `tiktok_publish_status {connector_id, publish_id}` | quelques minutes de traitement ; le `posted` du pont part quand le statut est final, avec `post_id = publish_id` [à vérifier : l'outil renvoie-t-il l'id public de la vidéo ?] |

Limites du fournisseur, appliquées avant l'appel à TikTok : **5 posts par minute et 13 posts par 24 h glissantes** par compte (plafond TikTok : 6/min, 15/jour) ; refus `code = cadence_burst` ou `cadence_daily` avec `retry_after_seconds` — on attend ce délai, on ne réessaie pas avant. Un brouillon ou un échec ne consomme pas de quota ; un post accepté oui. Médias : photos **JPEG ou WebP** (PNG refusé : le re-rendu de `content-pipeline.md` §6 livre du JPEG/WebP), ≤ 20 Mo, dans 1920×1080 ou 1080×1920, ≤ 35 images ; vidéos **MP4, WebM ou MOV**, ≤ 1 Go, **3-600 s**, ≥ 360 px sur chaque côté, **23-60 fps** (le rendu §6 sort en 30 fps 1080×1920 : conforme).

`is_aigc` (booléen, optionnel dans le schéma des deux outils — vérifié le 2026-09-14) = `aigc_label` de l'item de file, recopié tel quel (§1.1 : `true` pour les trois personnages `declared`, `false` pour les trois `undeclared`), jamais déduit de la légende ni relu depuis la fiche persona ; `commercial_content_disclosure` reste `enabled: false` (on ne vend rien dans le post, le lien est en bio). Notre cadence en `api_mode` est fixée dans `warming-policy.md` §11 ; ce fichier n'impose que le plafond dur de 13/24 h. Deux posts du même compte ne se suivent jamais à moins de **3 h** (`warming-policy.md` §11, appliqué par `POST /api/admin/social/queue`, E6.6). Coût : inclus dans le compte MCP fournisseur, pas de crédit OFMAI ; les publications par API sont enregistrées côté OFMAI (`SocialPublication.channel = "api"`) **et** dans le ledger comme `api_post` via `POST /api/farm/accounts/{p}/{h}/api-post` (E8.3), jamais comme `post`.

## 4. X par API v2, par l'IP statique du personnage

Pourquoi l'IP : un compte X créé et chauffé depuis une IP résidentielle US, puis piloté par API depuis Paris, finit en `verification` (R21). Le publieur tourne sur le Mac mini et sort par le proxy statique du personnage, au format accepté par `lib/ingest/instagram-proxy.ts` (`http://user:pass@host:port`, `user:pass@host:port`, `host:port:user:pass`, `host:port`), avec un `ProxyAgent` undici comme dans ce fichier. [à vérifier : le proxy statique accepte deux clients simultanés — le téléphone et le Mac mini — sur la même IP.]

```sh
# Mac mini : secrets par personnage dans le Trousseau (noms canoniques : architecture.md §6)
security find-generic-password -s ofmai-proxy-<slug>-static -w      # HOST:PORT:USER:PASS (IP statique, la même entrée que GeeLark)
security find-generic-password -s ofmai-social-x-<slug>-oauth -w    # refresh token OAuth 2.0 du compte X
security find-generic-password -s ofmai-x-app -w                 # client_id:client_secret de l'unique app développeur X
```

- Accès : OAuth 2.0 PKCE en contexte utilisateur, scopes `tweet.read tweet.write users.read offline.access` ; **l'autorisation se fait dans le navigateur du téléphone** (même IP que le compte), le refresh token est stocké dans le Trousseau, jamais dans `farm_accounts.notes` ni dans un `config_json` (R9). Une seule app développeur OFMAI (`ofmai-x-app`) pour les 6 personnages ; chaque personnage est un utilisateur distinct de l'app.
- Publier : upload du média (`POST /2/media/upload`, chunké) puis `POST /2/tweets` `{"text": "...", "media": {"media_ids": ["…"]}}` → `data.id` (`text` = `caption` de la file, telle quelle, §1.2) ; `post_url = https://x.com/<handle>/status/<id>`. Répondre : `{"text": "...", "reply": {"in_reply_to_tweet_id": "<id>"}}`. [à vérifier : endpoint média v2 vs v1.1 au moment du build.]
- Coût et paliers [à vérifier sur developer.x.com au moment de l'ouverture du compte] : Free = écriture seule, ≈ 1 500 posts/mois par app et ~17 `POST /2/tweets` par 24 h par utilisateur ; Basic ≈ 200 $/mois = 3 000 posts/mois par utilisateur, 10 000 lectures/mois (`public_metrics`, donc `impression_count`). Décision : **Free au départ** (6 personnages × 3 posts/jour au plus en cruise, `API_POSTS_PER_DAY["x"] = 3`, `warming-policy.md` §11 = 540 posts/mois au plafond), impressions relevées sur l'appareil (`metrics-attribution.md` §5.2) ; passage à Basic seulement si le seuil J4 de X (500 impressions/post après 100 posts) ne peut pas se lire sur écran.
- 18+ : le réglage « médias sensibles » est posé sur l'appareil à la création (`account-creation.md`) ; la légende porte « AI » si le personnage est déclaré, rien sinon (§1.1) ; lien Fanvue à partir du jour 15 seulement, mention OFMAI dans le texte seulement pour un personnage déclaré (§7).
- Arrêt : un `429` sur `POST /2/tweets` arrête le publieur du compte pour la journée et remonte un `health_signal` `action_blocked` par le pont ; un `403` → `needs_human`. Jamais de follow ni de like par API (R16).

## 5. Reddit par API, classification des subs et routage des liens

Même principe réseau que X (IP statique `ofmai-proxy-<slug>-static`). Accès : une app OAuth de type `script` **par personnage** (une app `script` ne sert que les comptes déclarés développeurs de l'app [à vérifier sur reddit.com/prefs/apps] : une app unique de Nathan ne pourrait pas publier au nom de 6 personnages, et les y déclarer depuis Paris lierait les comptes), créée à J15 ou plus tard dans le navigateur du téléphone du personnage (même IP), compte du personnage connecté — geste humain de 10 min, `account-creation.md` §6.4 ; `client_id:client_secret` dans `ofmai-social-reddit-<slug>-oauth`, mot de passe du compte dans `ofmai-social-reddit-<slug>` (grant `password` : il faut les deux, `lib/social/publishers/reddit.ts` refuse un compte auquel l'une manque, E8.2) ; `User-Agent: android:ai.ofmai.social.<slug>:v1 (by /u/<handle>)` ; ≤ 100 requêtes/min par client [à vérifier : conditions commerciales de l'API Data Reddit — notre usage est promotionnel]. Coût : 0 $ sous ce seuil.

Conditions d'entrée, avant tout post (plan 21 jours, action Reddit) : **compte ≥ 31 jours et karma ≥ 100**, quel que soit l'état de la phase — condition posée dans `publish-api.ts` et dans `GET /api/farm/queue`, qui ne sert aucune publication Reddit avant (`warming-policy.md` §10) ; le karma vient des commentaires des sessions de chauffe (cap `comments` 3 en `network`, 8 en `cruise` avant tirage). Posting par `POST /api/submit` : `{sr, kind: "link" | "self" | "image", title ≤ 300, url, nsfw: true, flair_id, sendreplies: true}` → `json.data.id` ; images via un bail `POST /api/media/asset.json` puis `kind: "image"` [à vérifier : chemin semi-documenté]. Réponse : `POST /api/comment {thing_id: "t1_<id>", text}`. Retrait : `GET /api/info?id=t3_<id>` → `removed_by_category` [à vérifier le nom du champ].

Classification, faite par `scripts/social/classify-subs.ts <sub> --character <slug>` (E8.5, via le proxy statique du personnage) et **validée par un humain avant le premier post dans un sub** (`PATCH /api/admin/social/subreddits/{id} {"status":"active"}`, geste de Nathan, `build-plan.md` §13 vague 3), rangée dans une table `SocialSubreddit` (`prisma/schema.prisma`, à créer, E8.5) :

```prisma
model SocialSubreddit {
  id              String   @id @default(cuid())
  name            String   @unique       // "aiart", sans "r/"
  kind            String                 // "creators" | "fans"
  over18          Boolean                // /r/<sub>/about.json → over18
  allowsAi        Boolean                // lu dans /about/rules.json et le wiki
  allowsSelfPromo Boolean
  requiresVerification Boolean           // post de vérification exigé → exclu (une IA ne se vérifie pas)
  minKarma        Int?                   // extrait des règles par l'agent, sinon null
  minAccountAgeDays Int?
  flairId         String?                // /api/link_flair_v2, flair « AI » ou « OC » si exigé
  aiFlairRequired Boolean  @default(false) // le sub impose un flair IA → c'est une divulgation (§1.1)
  rulesText       String   @db.Text
  rulesReadAt     DateTime
  status          String   @default("candidate") // candidate | active | paused | banned
  removals        Int      @default(0)           // tous personnages ; le détail est dans SocialSubredditRemoval
  characterIds    String[] @default([])  // personnages autorisés à y poster
  updatedAt       DateTime @updatedAt
}

model SocialSubredditRemoval {              // un retrait = une ligne, alimentée par metrics.removed (bridge §4.1)
  id            String   @id @default(cuid())
  subId         String
  characterId   String
  publicationId String
  at            DateTime @default(now())
  @@index([subId, characterId])
}
```

Lecture des règles par l'agent : `GET /r/<sub>/about.json` (`over18`, `subscribers`, `submission_type`), `GET /r/<sub>/about/rules.json`, `GET /r/<sub>/api/link_flair_v2`, plus le wiki si les règles y renvoient ; `minKarma` / `minAccountAgeDays` ne sont pas structurés, l'agent les extrait du texte et laisse `null` en cas de doute. Un sub `requiresVerification = true`, `allowsAi = false` ou `over18 = false` pour un asset `nsfw` n'est jamais `active`. Le tag `nsfw: true` est posé sur tout post `contentType = nsfw` et sur tout sub `over18` (R4).

**Un flair IA obligatoire est une divulgation.** Quand les règles du sub imposent le flair « AI » (ou « AI-generated ») sur tout post concerné, l'agent pose `aiFlairRequired = true` : le sub n'est alors jamais `active` pour un personnage `disclosed: false` — ses `characterIds` ne contiennent que des personnages `declared`, et un `undeclared` n'y poste pas, même dans un sub `fans`. Pour un personnage `declared`, le flair exigé est posé (`flair_id`) comme n'importe quelle règle du sub. Un sub sans flair IA obligatoire reste ouvert aux deux groupes selon son `kind` (§1.1, `content-pipeline.md` §7).

Routage (décision du brief, §7) :

| `kind` | Exemples | Ce que dit le post | Où pointe le lien |
|---|---|---|---|
| `creators` (créateurs, art IA, workflows) — **personnages déclarés seulement** (§1.1) | subs d'art IA et de créateurs de contenu IA | le making-of : « made her on OFMAI » sans URL, réponse « link in my profile » | page publique du personnage sur hotofmai.ai, `utm_source=reddit&utm_medium=bio&utm_content=<slug>` (le slug de la fiche persona, `metrics-attribution.md` §1) |
| `fans` — les six personnages, sauf les subs à flair IA obligatoire, réservés aux `declared` (§1.1) | subs de niche 18+ (fitness, latina, gothique…) | le personnage parle en son nom, aucune mention d'outil | Fanvue du personnage, sans lien OFMAI |

Le lien vit **dans le profil Reddit** (bio et liens sociaux : Fanvue en premier ; la page OFMAI ensuite, pour un personnage déclaré seulement, §1.1) — jamais dans le corps d'un post, à tout âge du compte (R22). À partir du jour 15, une URL est permise dans une seule réponse à un commentaire qui la demande, si les règles du sub l'autorisent, avec `utm_medium=comment&utm_term=r_<sub>` (`metrics-attribution.md` §2 : Reddit = `bio` ou `comment`, jamais `post`).

Choix du sub par `publish-api.ts` : parmi `status = active ∧ characterIds ∋ characterId ∧ (kind = fans ∨ disclosed) ∧ (aiFlairRequired = false ∨ disclosed)`, au plus 1 post par sub et par jour, 2 subs différents par jour (`warming-policy.md` §11). Retraits : un `metrics.removed = true` reçu par le pont écrit une `SocialSubredditRemoval` et incrémente `removals` ; 1 retrait → le sub passe `paused` pour le personnage ; 2 retraits sur un même sub → `banned` pour tous (seuil J4, `metrics-attribution.md` §7.2) ; un retrait d'un post qui contenait un lien est traité comme un `action_blocked` du compte (48 h, R22, `health-canaries.md` S6). Jamais d'upvote par API ni sur l'appareil en dehors de la chauffe : Reddit bannit pour manipulation de votes.

## 6. Fenêtres horaires par marché

Sur l'appareil, l'heure n'est pas choisie ici : un post tombe dans un créneau de `plan_sessions()` (`gitd/farm/policy.py`) — fenêtres `_WINDOWS = [(8, 12), (12, 15), (18, 23), (15, 18)]` en heure locale du compte, dérive ±90 min par jour, départs bornés à 07:05-23:40, rien dans `QUIET_HOURS = range(1, 7)`, ≥ 45 min entre deux sessions. Le pont enqueue le job `post_video` à `scheduled_at` ± `LATE_TOLERANCE_MINUTES` (20 min, `planner.py`), à l'intérieur d'un tel créneau.

Par API, rien dans le code ne borne l'heure : le publieur applique la même règle (R15 : jamais entre 01:00 et 06:59 locale) et choisit `scheduled_at` dans les fenêtres ci-dessous (recommandation, pas un chiffre du code) :

| Marché (`SocialAccount.market`) | Fuseau (`farm_accounts.timezone`) | Fenêtres API | Note |
|---|---|---|---|
| US (défaut) | `America/New_York` | 11:00-14:00 et 18:00-22:00 | couvre la côte Ouest à 15:00-19:00 |
| Latino | `America/Mexico_City` | 12:00-14:00 et 19:00-23:00 | |
| FR / EU | `Europe/Paris` | 12:00-14:00 et 19:00-22:00 | un seul marché par personnage |

Le fuseau est le même dans le profil du téléphone, dans `farm_accounts.timezone` et dans `SocialAccount.timezone` (R20). Deux posts du même compte ne se suivent jamais à moins de **3 h** (`warming-policy.md` §11, appliqué par `POST /api/admin/social/queue`, E6.6) ; deux personnages ne publient pas à la même minute sur la même plateforme (le programmateur décale de 7-23 min, `rng` seedé par (personnage, jour) comme dans `content-pipeline.md`).

## 7. Règles de liens

- **Chauffe = zéro lien** dans un post, un commentaire, un DM (phases `consume`, `light`, `network` : jusqu'au jour 14 sur Instagram et X, jour 23 sur TikTok) ; le seul lien est celui de la bio, posé selon `account-creation.md` (R22).
- **Reddit : jamais d'URL dans un post**, à tout âge (§5). **X : à partir du jour 15**, lien Fanvue dans le texte, plus la mention « OFMAI » seulement pour un personnage déclaré (§1.1) ; avant, « link in bio ».
- **Instagram et TikTok : jamais d'URL dans une légende ni un commentaire**, à aucun âge ; le lien est le link-in-bio (Fanvue en premier, puis « make yours on OFMAI » pour un personnage déclaré), `personas.md` [à valider dans `personas.md` : bouton OFMAI et domaine de la page `/c/<slug>` pour un personnage non déclaré]. Une légende avec URL, prix ou nombre de crédits est rejetée par la porte de conformité côté OFMAI (`content-pipeline.md` §8) ; la ferme ne la corrige pas, elle ne la reçoit pas (§1.2).
- **Jamais un lien hotofmai.ai ni Fanvue 18+ depuis Instagram, TikTok ou un DM Meta** (R23) ; jamais un lien ofmai.ai dans un sub `fans`.
- Chaque URL sortante porte `utm_source × utm_medium × utm_campaign=army-2026-09 × utm_content=<slug>` (le slug de la fiche persona : `sierra`, `camila`, `hana`, `skyler`, `riley`, `vera`) construite par `appendUtm()` (`lib/analytics/utm.ts`) ; `utm_source=instagram` pour Instagram (tranché dans `metrics-attribution.md` §1, repris par `rules.md` R24 ; le garde E10.1 est déployé avant le premier lien).
- Aucune réponse à un commentaire ne contient de lien, sur aucune plateforme (§9) ; l'exception Reddit du §5 est la seule.

## 8. Comment-to-DM Instagram (ManyChat ou équivalent)

**Personnages déclarés seulement** (§1.1) : le DM dit « I'm 100% AI », c'est une divulgation. Pour un personnage non déclaré, aucune automatisation n'est créée — les mots-clés ne sont pas configurés, ses commentaires « real / how / ai / tool » restent sans DM.

Mécanisme : l'API officielle Instagram Messaging, par un outil tiers (ManyChat retenu par le brief ; le nom n'apparaît jamais dans un texte publié, R10). Le DM est une **réponse privée à un commentaire** : Meta l'autorise une fois par commentaire, dans les 7 jours [à vérifier] ; il ne part jamais vers quelqu'un qui n'a pas commenté.

Prérequis [à vérifier dans l'outil] : compte Instagram en profil professionnel « Creator », relié à une Page Facebook du personnage seulement si l'outil l'exige, connexion de l'outil depuis le navigateur du téléphone (même IP) — procédure humaine au jour 15, `account-creation.md` §6.5. Activation **au jour 15 au plus tôt** : avant, un DM avec lien viole R22, et un compte de 5 jours relié à une app tierce est un signal.

Configuration, une automatisation par personnage :

- Déclencheur : commentaire sur **tous les posts**, contenant `real`, `how`, `ai`, `tool` (contient, insensible à la casse) ; un seul DM par utilisateur par 24 h ; pas de réponse publique automatique (la réponse publique est faite par `comment_reply`, §9, avec la voix du personnage).
- Message (Unicode permis : c'est l'API, pas `type_text`) — exemple, à décliner par personnage déclaré dans `personas.md` (`links.dm_offer`) :

```text
hey! yes — I'm 100% AI. I was made on OFMAI, and you can make your own in a few minutes.
15 free credits with this link: https://ofmai.ai/?utm_source=instagram&utm_medium=dm&utm_campaign=army-2026-09&utm_content=<slug>
```

- Limites : **200 DM par heure** par compte au maximum (brief) ; **arrêt au premier « Try again later »** (plan 21 jours, action DM IG : restriction = arrêt définitif du canal pour ce compte) ; si l'outil signale une restriction, le compte prend un `health_signal` `action_blocked` par le pont (48 h) et l'automatisation reste coupée jusqu'à `accounts clear-health` (R26).
- Interdit : DM à froid, relance après le premier message, diffusion (broadcast), DM à un utilisateur qui n'a pas commenté, lien hotofmai.ai ou Fanvue 18+, nom de fournisseur, prix autre que « 15 free credits », toute mention de « visage » (R11).
- Les 15 crédits sont le **bonus d'inscription existant**, servi à tout nouvel utilisateur quelle que soit sa provenance (`app/api/auth/[...nextauth]/route.ts` l. 114-135 : `events.createUser` pose `purchasedCredits: 15` et écrit une `CreditHistory { type: "gift", description: "Welcome credits" }`) : **rien à construire**, aucun code ni palier lié à `utm_medium=dm`, le DM le dit tel quel (`build-plan.md` E9). Coût de l'outil : abonnement par compte Instagram connecté [à vérifier le tarif au moment de l'ouverture].
- TikTok n'a pas d'équivalent officiel : la réponse à « is she real? » est un commentaire public (§9), sans lien.

## 9. Réponses aux commentaires, DM entrants, like en retour

Caps du code (`gitd/farm/policy.py` l. 142-143) : `COMMENT_REPLY` = 20/jour en `network` et `cruise`, sinon 0 ; `DM_REPLY` = 20/jour en `cruise`, sinon 0 ; 0 le jour de repos. Les workflows `comment_reply` et `dm_reply` **n'existent pas** (`docs/FARM.md`, « Not done yet ») ; seuls les caps et les éléments sont là : Instagram `comment_input` (« Add a comment… »), `comment_post` ; TikTok `comment_input` (« Add comment... »), `comment_send`.

Voix : les textes sont écrits **côté OFMAI**, par lot, par le workflow de contenu à partir de la fiche persona (`reply_tone`, `forbidden_words`, `bio`, `bridge-ofmai-farm.md` §3.5), passent la porte de conformité (R10, R11) et sont rangés dans `SocialCommentPool` (`kind = reply_ai | reply_thanks | reply_question`) ; la ferme les tire par `GET /api/farm/comments` (`bridge-ofmai-farm.md` §3.4) et les poste tels quels, comme une légende (§1.2). Sur l'appareil ils sont ASCII purs (R12) : pas d'emoji, pas d'accent. Ils ne contiennent **jamais de lien, de prix, de nombre de crédits**, ni « real person », « same face » ; à « are you real? » un personnage déclaré répond « 100% AI, and proud of it » (pool `reply_ai`) puis, sur Instagram, le DM du §8 fait le reste ; un personnage non déclaré ignore le commentaire — son pool `reply_ai` est vide et il ne répond jamais « yes » (§1.1).

Sur l'appareil (Instagram, TikTok) — workflow `comment_reply` à créer, une passe par session de chauffe : ouvrir son dernier post → lire les commentaires (`dump_xml`, `nodes_where`) → pour chacun non encore traité (clé `farm_actions.target = <post>:<auteur>`), `allow(COMMENT_REPLY)` → **like du commentaire** (compté `LIKE`, sous le ratio `MAX_LIKE_PER_VIEW = 0.15` comme tout like) → réponse tapée → `record(COMMENT_REPLY)`. Ordre : les questions d'abord, puis les compliments ; on ignore les insultes et les liens. Un signal de `health.detect` arrête tout (R27).

Par API (X, Reddit) — même cap `COMMENT_REPLY` posé côté OFMAI sur `SocialAccount` tant que `farm_accounts` ne connaît pas ces plateformes [à vérifier après le lot « plateformes » de `build-plan.md`] : lecture des réponses (`GET /2/tweets/search/recent?query=conversation_id:<id>` ; Reddit `GET /comments/<id>.json`), réponse par `POST /2/tweets` avec `reply` ou `POST /api/comment` ; jamais de like par API sur X, jamais de vote sur Reddit.

DM entrants : Instagram → le comment-to-DM couvre le cas utile ; les autres DM sont lus par `dm_reply` (à créer, cap 20, `cruise` seulement), réponse courte sans lien, jamais de conversation au-delà de deux échanges. TikTok → idem `dm_reply`. X et Reddit → pas de réponse automatique en V1 ; un humain lit les messages sur l'appareil une fois par semaine. Tout DM qui demande une photo « perso », un numéro ou une rencontre est ignoré.

Like en retour : uniquement sur l'appareil, dans `comment_reply` ; sur Reddit jamais ; sur X seulement quand un skill `ofmai_x` existera (`build-plan.md`). Un like en retour n'est jamais suivi d'un follow (le follow reste dans la branche `open_author` de `warm.py`, sous son cap).

## 10. Ce qui n'existe pas encore

- Aucune publication par API d'aucune sorte : ni appel aux outils `tiktok_*`, ni client X, ni client Reddit, ni `scripts/social/`, ni phase publication dans un workflow (`daily-fix.js` est le seul workflow).
- `farm_accounts.platform` limité à `instagram | tiktok` (`ledger.add_account`, `cli.py`, `PHASE_EXTRA_DAYS`, `health._PATTERNS`, `planner.SKILL_BY_PLATFORM`) : X et Reddit n'ont ni ledger ni caps ni signaux santé.
- `post_video` sans push du média, sans id de post, jamais testé (`tested_on: []`) ; pas de `post_photo`, `post_story`, `comment_reply`, `dm_reply`, `metrics_pull`.
- Aucun paramètre `aigc_label` sur `post_video` : le toggle « AI-generated content » est tapé dès qu'il est visible, pour tous les personnages, et son état n'est pas vérifié (§1.1, §2, E3.5) ; le publieur API n'existe pas, donc rien ne lit `aigc_label`.
- Aucune table `SocialSubreddit`, aucune lecture des règles d'un sub (dont `aiFlairRequired`), aucun compteur de retraits (E8.5).
- Aucune intégration Meta Messaging ; les 15 crédits sont le bonus d'inscription existant (`build-plan.md` E9), rien à construire.
- Aucune garde horaire côté API, aucun kill-switch de publication côté OFMAI (R31).
- Les entrées Trousseau (`architecture.md` §6) sont à créer ; l'usage partagé d'un proxy statique entre le téléphone et le Mac mini est à valider dans `infrastructure-geelark-proxies.md`.

Les tâches, leur ordre et leurs tests sont dans `build-plan.md`.
