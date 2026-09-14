# Mesure et attribution de M1 — UTM, vérité prod, PostHog, rapport Discord, seuils

> **Nature** : reference
> **Statut** : à vérifier
> **À jour au** : 2026-09-14
> **Répond à** : Comment on sait, chaque matin, ce que chaque plateforme et chaque personnage rapportent en inscrits et en payants, où vivent les liens, quelle décision tombe à J4, J7 et J14, et ce que le test de divulgation IA (groupe `declared` = `sierra`, `camila`, `hana` ; groupe `undeclared` = `skyler`, `riley`, `vera`) se lit à J14 et décide à J21.
> **Code concerné** : `lib/analytics/utm.ts`, `app/api/attribution/route.ts`, `prisma/schema.prisma` (User, Subscription, Generation, AICharacter ; `SocialAccount`, `SocialPublication`, `SocialPostMetric` à créer), `lib/analytics/posthog-server.ts`, `lib/analytics/analytics.ts`, `components/PostHogProvider.tsx`, `app/r/[code]/route.ts`, `lib/core/discord-alerts.ts`, `.claude/loop/notify.mjs`, `.claude/skills/prod/`, `lib/social/personas/*.yaml` et `scripts/social/groups.sql` (à créer), fork `gitd/farm/warm.py`, `gitd/farm/skillkit.py`, `gitd/farm/models.py`, `gitd/routers/scheduler.py`

Trois couches, chacune avec un rôle et un seul : les **UTM** disent d'où vient un visiteur ; la **base de prod** (`User` × `Subscription`) dit qui a payé — c'est la seule vérité pour les décisions ; **PostHog** sert à voir où le funnel casse entre les deux. Les métriques de plateforme (vues, impressions, upvotes) viennent de la ferme et servent aux seuils de rythme, jamais aux décisions d'argent. Ce que la ferme mesure côté santé est dans `health-canaries.md` ; le contrat des événements retour est dans `bridge-ofmai-farm.md`. Une quatrième lecture traverse les trois : la comparaison des deux groupes de personnages, **`declared`** et **`undeclared`** sur les réseaux (§8), qui a sa propre requête, ses propres dates (lecture à J14, décision à J21) et sa propre décision.

## 1. Schéma UTM

Les clés restent les cinq clés standard, parce que `components/PostHogProvider.tsx` ne persiste que `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term` et `fbclid` (clé localStorage `ofmai_<param>`, TTL 30 jours), et que `app/api/attribution/route.ts` ne lit que ces champs (tronqués à 255 caractères).

| Clé | Valeur pour M1 | Règle |
|---|---|---|
| `utm_source` | `instagram` · `tiktok` · `x` · `reddit` (+ `fanvue` pour le lien « made with » de la page Fanvue, hors seuils) | une valeur par plateforme, en minuscules, jamais d'abréviation ni `ig-organic` (`ig` est réécrit en `meta`, voir plus bas) — valeur tranchée ici, reprise par `rules.md` R24 |
| `utm_medium` | `bio` · `dm` · `comment` · `post` · `profile` · `social` | la surface où le lien était posé (`profile` = page Fanvue) ; `social` est la valeur par défaut quand la surface est inconnue |
| `utm_campaign` | `army-2026-09` | une valeur par vague de M1, changée seulement quand le plan change (nouvelle vague = nouvelle valeur) |
| `utm_content` | `<personnage>` (slug de la fiche persona, ex. `sierra`) | **toujours renseigné** : c'est la clé de lecture par personnage, et par groupe de divulgation (§8 : le groupe se déduit du slug, jamais d'un paramètre UTM supplémentaire) |
| `utm_term` | `<sub reddit>` · `<hashtag>` · `<ScrapedPost.id du post source>` | facultatif, pour départager des variantes à l'intérieur d'un personnage |

Construction : `appendUtm(url, {source, medium, campaign, content, term})` dans `lib/analytics/utm.ts` — elle préserve les paramètres existants et accepte un chemin relatif (résolu contre `NEXTAUTH_URL`, sinon `https://ofmai.ai`). Exemples :

```
https://ofmai.ai/?utm_source=tiktok&utm_medium=bio&utm_campaign=army-2026-09&utm_content=sierra
https://ofmai.ai/?utm_source=instagram&utm_medium=dm&utm_campaign=army-2026-09&utm_content=riley
https://hotofmai.ai/?utm_source=reddit&utm_medium=comment&utm_campaign=army-2026-09&utm_content=vera&utm_term=r_aiart
https://hotofmai.ai/?utm_source=x&utm_medium=bio&utm_campaign=army-2026-09&utm_content=camila
```

### Comment la source est résolue à l'inscription (vérifié dans `app/api/attribution/route.ts`)

`resolveSource` écrit `User.signupSource` une seule fois (first-touch, la route répond `alreadySet` ensuite) :

1. `fbclid` présent **ou** `utm_source` ∈ {`facebook`, `fb`, `instagram`, `ig`, `meta`, `facebook.com`, `instagram.com`} → `"meta"` ;
2. `utm_medium` = `email` ou `utm_source` = `email` → `"email"` ;
3. `User.referredBy` renseigné → `"referral"` ;
4. sinon `utm_source` tel quel → `"tiktok"`, `"x"`, `"reddit"` passent inchangés ;
5. sinon `"organic"`.

**Conséquence** : un inscrit venu d'Instagram organique a aujourd'hui `signupSource = "meta"`, confondu avec les pubs Meta. Le plan 21 jours prévoyait à J4 un garde `utm_medium` qui empêche cette réécriture ; au 2026-09-14 il **n'est pas dans le code** (la fonction ne lit `utmMedium` que pour `email`). Décision : ce garde est la tâche E10.1 de `build-plan.md`, en **vague 1**, déployée avant le premier lien posé (jour 8 au plus tôt) ; `utm_source=instagram` est utilisé dès le départ, jamais `ig-organic`. Deux règles, valables même après le déploiement :

- les colonnes brutes `utmSource`, `utmMedium`, `utmContent` sont écrites telles quelles, quelle que soit la résolution : **toute requête de M1 filtre sur `utmSource`, jamais sur `signupSource` seul** ;
- les rapports paid Meta doivent exclure `utmMedium IN ('bio','dm','comment','post','profile','social')` tant que le garde n'est pas déployé, et la requête de contrôle du §3 doit rester à zéro ensuite.

## 2. Où vivent les liens

| Plateforme | Surface | Cible | UTM |
|---|---|---|---|
| Instagram | bio → link-in-bio (Fanvue en premier, puis « crée la même sur OFMAI ») | `ofmai.ai` | `instagram` / `bio` |
| Instagram | DM envoyé par le comment-to-DM (`publishing.md`) | `ofmai.ai` avec l'offre 15 crédits | `instagram` / `dm` |
| TikTok | bio (un seul lien) → link-in-bio | `ofmai.ai` | `tiktok` / `bio` |
| Fanvue (page du personnage) | lien « made with » | `ofmai.ai` | `<plateforme d'origine inconnue>` → `utm_source=fanvue`, `utm_medium=profile` |
| X | bio + mention OFMAI dans les posts | `hotofmai.ai` | `x` / `bio` ou `post` |
| Reddit | profil (bio et liens sociaux) : subs créateurs / art IA → page OFMAI du personnage ; subs de fans → Fanvue (sans lien OFMAI) ; jamais d'URL dans un post (`publishing.md` §5) | `hotofmai.ai` | `reddit` / `bio` (profil) ou `comment` (une réponse à partir du jour 15, `utm_term=r_<sub>`), jamais `post` |

Règles de placement :

- Le lien de bio porte `utm_source=<plateforme>&utm_medium=bio&utm_campaign=army-2026-09&utm_content=<slug>` et la page `/c/<slug>` (auto-hébergée, `personas.md` §5) relaie les `utm_*` de sa query à chacun de ses boutons avec `appendUtm()` — aucun agrégateur tiers.
- La page publique du personnage (« crée la même ») n'existe pas encore dans `app/` — URL et contenu dans `personas.md`, construction dans `build-plan.md`. Tant qu'elle n'existe pas, la cible est la home de l'host, avec les mêmes UTM.
- **Ne pas utiliser `hotofmai.ai/r/<code>` pour M1** : `app/r/[code]/route.ts` redirige vers `new URL("/", req.url)` et **perd la query string**, donc les UTM. Le cookie `ofmai_aff` (30 jours, HOT seulement, `AFFILIATE.COOKIE` dans `lib/billing/affiliate.ts`) sert au programme d'affiliation, pas à l'attribution par personnage. Si un jour on veut les deux, la redirection doit relayer `req.nextUrl.search` (tâche `build-plan.md`).
- Rien de NSFW ne pointe vers `ofmai.ai` et aucun lien `hotofmai.ai` n'apparaît sur Instagram ou TikTok (`rules.md`).

## 3. Vérité en prod : `User` × `Subscription`

Colonnes utilisées (vérifiées dans `prisma/schema.prisma`) : `User.signupSource`, `utmSource`, `utmMedium`, `utmCampaign`, `utmContent`, `utmTerm`, `createdAt` ; `Subscription.userId` (unique), `status` (`active`, `cancelling`, `expired`, `retry`), `plan` (`starter`, `pro`, `business`, `agency`), `billingInterval`, `price` (montant mensuel **ou** total annuel), `provider` (`internal` | `fanvue`) ; `Generation.userId`, `status` (`completed`), `contentType`.

Tout passe par le skill `prod` (lecture seule, journalisé dans `~/.ofmai/prod-audit.log`) : `SELECT`/`WITH` uniquement, 30 s max, 200 lignes par défaut, `--json` pour enchaîner.

```bash
bash .claude/skills/prod/prod.sh check          # obligatoire en début de session : vérifie que le tunnel parle à la base de prod
bash .claude/skills/prod/prod.sh sql "<requête>" --json --limit 500
```

Inscrits de la veille (jour UTC) par source × surface × personnage :

```sql
SELECT "utmSource" AS source, "utmMedium" AS surface, "utmContent" AS personnage, "signupSource", count(*) AS inscrits
FROM "User"
WHERE "createdAt" >= date_trunc('day', now() - interval '1 day')
  AND "createdAt" <  date_trunc('day', now())
  AND "utmSource" IN ('instagram', 'tiktok', 'x', 'reddit')
GROUP BY 1, 2, 3, 4
ORDER BY inscrits DESC;
```

Payants cumulés depuis le premier jour de publication (remplacer la date) — la seule requête qui autorise une décision :

```sql
SELECT u."utmSource" AS source, u."utmContent" AS personnage,
       count(*) AS inscrits,
       count(*) FILTER (WHERE s.status = 'active') AS abonnes_actifs,
       count(*) FILTER (WHERE s.status IN ('active', 'cancelling', 'retry')) AS abonnes_tous,
       coalesce(sum(s.price) FILTER (WHERE s.status = 'active' AND s."billingInterval" = 'monthly'), 0) AS mrr_mensuels,
       coalesce(sum(s.price) FILTER (WHERE s.status = 'active' AND s."billingInterval" = 'annual'), 0) AS total_annuels
FROM "User" u
LEFT JOIN "Subscription" s ON s."userId" = u.id
WHERE u."createdAt" >= '2026-09-21'
  AND u."utmSource" IN ('instagram', 'tiktok', 'x', 'reddit')
GROUP BY 1, 2
ORDER BY abonnes_actifs DESC, inscrits DESC;
```

Activation (au moins une génération terminée) par source, pour lire où le funnel casse avant le paiement :

```sql
SELECT u."utmSource" AS source,
       count(DISTINCT u.id) AS inscrits,
       count(DISTINCT g."userId") AS actives,
       round(100.0 * count(DISTINCT g."userId") / greatest(count(DISTINCT u.id), 1), 1) AS pct_actives
FROM "User" u
LEFT JOIN "Generation" g ON g."userId" = u.id AND g.status = 'completed'
WHERE u."createdAt" >= '2026-09-21'
  AND u."utmSource" IN ('instagram', 'tiktok', 'x', 'reddit')
GROUP BY 1;
```

Contrôle de la collision Instagram → `meta` (doit tomber à zéro une fois le garde déployé) :

```sql
SELECT "signupSource", "utmSource", "utmMedium", count(*)
FROM "User"
WHERE "utmSource" IN ('instagram', 'ig') AND "createdAt" >= '2026-09-21'
GROUP BY 1, 2, 3;
```

Lecture : un « payant » = une ligne `Subscription` avec `status = 'active'` sur un `User` dont `utmSource` est une des quatre plateformes. Les packs de crédits (`Transaction.purpose = 'credit_purchase'`, statut payé — le schéma liste `pending, finished, failed, paid` sans dire lequel vaut « encaissé » pour chaque PSP [à vérifier dans `lib/billing/`]) ne comptent pas comme payants dans les seuils, mais entrent dans le revenu du rapport. `SubscriptionHistory.action = 'created'` donne la date du premier paiement si on veut le délai inscription → paiement (83 % le jour même d'après `documentation/business/growth/machine-x10-2026-09.md`).

## 4. PostHog : le funnel, pas la vérité

Instance EU (`eu.posthog.com`, projet 130897, fuseau UTC ; le défaut du code `us.i.posthog.com` dans `lib/analytics/posthog-server.ts` n'est pas celui de la prod — `documentation/platform/posthog-analytics.md`). Événements présents dans le projet au 2026-09-14 (vérifiés par `read-data-schema` du MCP `posthog`) et utiles à M1 :

| Événement | Côté | Propriétés utiles | Émis par |
|---|---|---|---|
| `$pageview` | client | `$utm_source`, `$utm_medium`, `$utm_campaign`, `$utm_content`, `$current_url` | auto |
| `user_signed_up` | client + serveur | client : `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`, `partner`, `referral_code` ; serveur : `$insert_id = signup_<userId>` | `components/PostHogProvider.tsx` (compte < 10 min) ; `events.createUser` de `app/api/auth/[...nextauth]/route.ts` |
| `generation_started` / `generation_completed` / `generation_failed` | client | `type`, `mode`, `character_id`, `cost`, `quantity` | `lib/analytics/analytics.ts` |
| `paywall_shown`, `subscription_modal_opened`, `subscription_plan_selected` | client | `cost`, `balance`, `plan`, `interval`, `price` | `lib/analytics/analytics.ts` |
| `purchase_completed` | serveur | `type` (`subscription` \| `top_up` \| `crm_token_pack`), `revenue`, `currency`, `plan`, `interval`, `provider` (`card` \| `crypto`) | routes PSP et webhooks (liste dans `documentation/platform/posthog-analytics.md`) |
| `subscription_created` / `subscription_upgraded` / `subscription_cancelled` | serveur | `plan`, `previous_plan`, `interval`, `revenue` | idem |

Funnel M1 à créer dans PostHog (recommandation de dashboard, rien n'est codé) : `$pageview` (filtre `$utm_source` ∈ {instagram, tiktok, x, reddit}) → `user_signed_up` → `generation_completed` → `purchase_completed`, découpé par `$initial_utm_source` puis `$initial_utm_content` (`$initial_utm_content` comme propriété personne : [à vérifier] dans l'UI, la doc ne liste que source/medium/campaign). Aucun événement social n'existe côté OFMAI (pas de `social_post_published`, pas de `social_dm_sent`) : les compteurs de posts et de sessions restent dans la ferme et dans le rapport, pas dans PostHog.

Interroger depuis un agent : outil MCP `posthog` (`exec`), `info query-funnel` puis `call query-funnel …` ; pour les UTM par page, `query-web-stats`. Règle : PostHog explique un écart (beaucoup de visiteurs, peu d'inscrits = landing ; beaucoup d'inscrits, peu d'activés = onboarding), la décision se prend sur la requête SQL du §3.

## 5. Métriques de plateforme et relevé par la ferme

### 5.1 Ce que la ferme mesure déjà (fork, vérifié)

- Chaque session de chauffe finit par une ligne `Data: {…}` imprimée par `gitd/skills/_run_skill.py`, parsée par le scheduler et servie par `GET /api/scheduler/history/{run_id}/result` (`gitd/routers/scheduler.py`). Clés (`SessionStats.as_dict()` dans `gitd/farm/warm.py` + `WarmSessionAction.execute` dans `gitd/farm/skillkit.py`) : `videos`, `likes`, `saves`, `visits`, `follows`, `comments`, `detours`, `seconds`, `health`, `error`, `handle`, `day_of_life`, `phase`, `profile_seed` ; un jour de repos renvoie `{skipped: "rest day", day_of_life}`.
- Chaque action comptée est une ligne `farm_actions` (`account_id`, `day` = date locale du compte, `kind`, `target`, `session_id`, `at`) ; chaque signal écran une ligne `farm_signals` (`kind`, `matched`, `session_id`, `at`) — `gitd/farm/models.py`.
- `python -m gitd.farm.cli budget <platform> <handle>` affiche caps du jour vs dépensé ; `accounts list` affiche jour de vie, phase, santé.

Aucun compteur de **vues, impressions ou upvotes** n'est lu aujourd'hui : les `elements.yaml` des deux skills n'ont pas de sélecteur de compteur, `health.zero_reach(view_counts)` existe mais n'est appelé nulle part, et les outils TikTok du MCP Higgsfield ne renvoient qu'un statut de traitement (`tiktok_publish_status`), pas de statistiques.

### 5.2 Ce qu'il faut relever, où, et comment (à construire, `build-plan.md`)

Un workflow Ghost `metrics_pull` par skill, enfilé par le daemon `bridge` (`bridge-ofmai-farm.md` §6, étape 7 — le planner n'enfile que `warm_session`, `gitd/farm/planner.py` l. 79-101) à **24 h ± 2 h, puis 72 h et 168 h** après chaque post, sur l'appareil du personnage, dans un créneau de `plan_sessions()` du compte (jamais en heures calmes ni le jour de repos, `warming-policy.md`), idempotent par `farm_planned.slot_key = "<account_id>:metrics:<publication_id>:<at_hours>"`. Il lit, écrit une ligne `farm_post_metrics` (`publication_id`, `post_id`, `account_id`, `at_hours ∈ {24, 72, 168}`, `source ∈ {device, api, observer}`, `views`, `likes`, `comments`, `shares`, `saves`, `impressions`, `score`, `upvote_ratio`, `removed`, `visible`, `sub`, `raw`, `at`) et pousse l'événement `metrics` vers OFMAI par le pont (`bridge-ofmai-farm.md` §4.1). Comptes `api_mode` X/Reddit : relevé par `scripts/social/publish-api.ts --metrics` (E8.2), pas par l'appareil.

| Plateforme | Métrique de seuil | Où la lire | Comment |
|---|---|---|---|
| Instagram | lectures du Reel, likes, commentaires | grille du profil du compte (compteur superposé) ou écran « Voir les statistiques » du Reel | `dump_xml` + `nodes_where(xml, desc=…)` (`gitd/farm/warm.py`) ; sélecteurs à miner sur l'appareil [à vérifier : `tested_on: []`] |
| TikTok | vues, likes | grille du profil (compteur de vues sur chaque vignette), écran « Analyses » de la vidéo | même mécanique ; en `api_mode`, l'API Display TikTok (`video.list`, `view_count`) exigerait un scope supplémentaire non exposé par le MCP [à vérifier] |
| X | impressions, engagements | écran « Voir les statistiques du post » sur l'appareil du compte (palier Free de l'API, décision `publishing.md` §4) ; API v2 `GET /2/tweets?ids=<id>&tweet.fields=public_metrics` (`impression_count`) seulement après passage à Basic, appelée depuis le Mac mini **par l'IP statique du personnage** | sélecteurs à miner ; pas de canari X depuis l'observateur (`health-canaries.md` §2) |
| Reddit | upvotes, ratio, commentaires, **retrait** | API `GET /api/info?id=t3_<id>` → `score`, `upvote_ratio`, `num_comments`, `removed_by_category` [à vérifier le nom du champ] ; par l'IP statique | les « vues » d'un post ne sont visibles que par l'auteur dans l'app (compteur « Views ») → relevé écran depuis le compte auteur |
| Toutes | visible en déconnecté (canari) | profil observateur (`health-canaries.md`) | hors périmètre de ce fichier |

Les identifiants de post viennent de `publishing.md` (l'id est récupéré à la publication, ce que `post_video` ne fait pas encore). Les médianes des seuils du §7 se calculent sur `farm_post_metrics` à 24 h, par plateforme, sur une fenêtre glissante de 7 jours, en excluant les posts retirés.

## 6. Rapport Discord quotidien

Un seul message par jour, à la fin du workflow `growth-content-army.js` (phase `Rapport`, patron de `.claude/workflows/daily-fix.js` : l'agent de rapport reçoit un objet JSON borné et l'envoie par un script). Le script `scripts/social/daily-report.mjs` [à créer] reprend de `.claude/loop/notify.mjs` la résolution du webhook (`DISCORD_WEBHOOK_URL`, sinon Trousseau macOS `security find-generic-password -s ofmai-discord-webhook -w`) et la troncature à 1 900 caractères. Les alertes santé en temps réel (pause, vérification, suspension) passent par un autre canal : `sendDiscordAlert({level, title, message, route})` de `lib/core/discord-alerts.ts` côté OFMAI (embed, no-op sans `DISCORD_WEBHOOK_URL`), déclenché par le pont — `health-canaries.md`.

Sources du rapport, dans l'ordre : (1) SQL prod du §3 pour la veille UTC et le cumul ; (2) SQLite de la ferme (`data/gitd.db`, tables `farm_accounts`, `farm_actions`, `farm_signals`, `farm_post_metrics`) — la « veille » y est la date locale du compte, pas UTC ; (3) rien de PostHog dans le rapport (trop lent, non décisionnel).

Objet attendu par le script (schéma JSON borné, comme les schémas de `daily-fix.js`) :

```json
{
  "date": "2026-09-25", "jour": 5,
  "prod": { "inscritsVeille": 14, "abonnesVeille": 1, "inscritsCumul": 41, "abonnesCumul": 2, "revenuCumulUsd": 19.98,
            "parSource": [{ "source": "reddit", "inscrits": 9, "abonnes": 1, "parPersonnage": [{ "personnage": "sierra", "inscrits": 6 }] }] },
  "ferme": { "comptes": 24, "sessionsOk": 22, "cooldown": 1, "verification": 0, "loggedOut": 0, "suspended": 0, "reposDuJour": 3 },
  "posts": [{ "plateforme": "reddit", "n": 11, "medianeVues24h": 2300, "retraits": 1, "seuil": "ok" }],
  "divulgation": [{ "groupe": "declared", "inscritsCumul": 24, "abonnesCumul": 1, "vues24hCumul": 96000, "inscritsPour1000Vues": 0.25, "comptesRouges": 0 },
                  { "groupe": "undeclared", "inscritsCumul": 17, "abonnesCumul": 1, "vues24hCumul": 118000, "inscritsPour1000Vues": 0.14, "comptesRouges": 1 }],
  "seuils": [{ "plateforme": "x", "regle": "500 impressions/post après 100 posts", "etat": "en attente", "n": 61 }],
  "humain": ["x @verablack… verification_required depuis 03:12 UTC — clear-health après action (compte undeclared : bascule §8.3 si le signal suit un post)"]
}
```

Rendu (texte brut, pas d'embed, un bloc par ligne de lecture) — exemple illustratif :

```
**M1 — jeu 25/09 (J5)**
Prod J-1 : 14 inscrits · 1 abonné · cumul 41 inscrits / 2 abonnés / 19,98 $
  reddit 9 (sierra 6, vera 3) · x 3 (camila 3) · tiktok 2 (riley 2) · instagram 0
Ferme : 24 comptes · 22 sessions OK · 1 cooldown · 0 verification · 0 suspended · 3 au repos
Posts J-1 : reddit 11 (méd. 2 300 vues, 1 retrait) · x 20 (méd. 640 impr.) · tiktok 8 (méd. 1 900) · ig 8 (méd. 1 100)
Divulgation (cumul, lue à J14, décidée à J21) : declared 24 inscrits / 96 k vues (0,25 ‰) · undeclared 17 / 118 k (0,14 ‰) · rouges 0 vs 1
Seuils : reddit OK · x en attente (61/100 posts) · tiktok/ig — (n < 20)
Humain : x @verablack… verification_required depuis 03:12 UTC — clear-health après action (undeclared : bascule §8.3 si le signal suit un post)
```

Interdits dans le message : nom de fournisseur, handle complet d'un compte encore sain (préfixe suffisant), email d'utilisateur. Un jour sans donnée prod (tunnel tombé) doit le dire explicitement (« prod injoignable »), jamais afficher des zéros.

## 7. KPI et seuils J4 / J7 / J14 (J21 : test de divulgation, §8)

Convention de lecture : **J1 = premier jour de publication de la plateforme**, pas le calendrier du plan (les comptes chauffent d'abord : `posts_per_week` vaut 0 en `CONSUME` et `LIGHT`, 3 en `NETWORK`, 7 en `CRUISE` dans `gitd/farm/policy.py`, donc rien n'est publié avant le jour 8 sur Instagram et le jour 14 sur TikTok). Les seuils prod se lisent en UTC, les seuils de plateforme sur `farm_post_metrics` à 24 h.

### 7.1 Hypothèses du plan (par post, « estimé » = à valider sur les trois premiers jours)

Source : page « Machine ×10 » (artifact lié dans `documentation/business/growth/machine-x10-2026-09.md`), section M1.

| Plateforme | Vues / impressions par post | Clics vers le site | Visite → inscrit | Inscrit → payant |
|---|---|---|---|---|
| Reddit | 4 000 | 1 % | 15 % | 3 % |
| X | 1 200 | 0,5 % | 15 % | ≈ 3 % |
| TikTok / Instagram | 3 000 | 0,3 % | 15 % | 3 % |

La base « 120 payants sur 21 jours » suppose 12 personnages et 30 comptes (Reddit 430 posts, X 860, TikTok/IG 430). Avec les 6 personnages du brief et un compte par plateforme et par personnage, l'attente proportionnelle est **≈ 60 payants** sur la même durée (dérivation de ce fichier, pas un chiffre du plan). Ce qui doit être vrai pour tenir la base : 4 000 vues médianes par post Reddit et au plus 3 comptes bannis sur 21 jours.

### 7.2 Seuils et décisions

| Quand | Plateforme | Seuil (lecture) | Décision | Source |
|---|---|---|---|---|
| J4 | Reddit | médiane < 1 500 vues par post à 24 h, **ou** 2 retraits sur un même sub | on change de subs (classification dans `publishing.md`), **pas de rythme** | brief M1 du 2026-09-14 §11 (repris de l'artifact Machine ×10, absent de `documentation/business/growth/machine-x10-2026-09.md`) [à vérifier] |
| J4 | X | < 500 impressions par post après 100 posts (cumul de la plateforme) | passer à 2 posts/jour par compte, le reste du budget en réponses aux gros comptes | brief M1 §11, même réserve [à vérifier] |
| J4 | TikTok / IG | médiane < 1 000 vues par clip après 20 clips | changer de posts source dans le radar (tranche d'`outlierScore` plus haute, autre `mediaType`, `content-pipeline.md`), pas de rythme — **proposé**, absent des plans | ce fichier |
| tout moment | toutes | 3 comptes bannis en 48 h sur une plateforme | plateforme coupée (`api_mode` et planner arrêtés pour tous les comptes de la plateforme) | brief M1 §11 [à vérifier] ; mécanique dans `health-canaries.md` |
| tout moment | toutes | 1 signal santé sur un compte | pause 48 h du compte (`COOLDOWN_HOURS = 48`) ; 2 comptes rouges en 48 h sur une plateforme → pause de la plateforme | `health-canaries.md` |
| J7 | X | < 5 000 impressions cumulées | 1 post/jour par compte | plan 21 jours, action « X 18+ » |
| J7 | X | ≥ 1 inscrit `utmSource = 'x'` attendu | sinon on vérifie le lien de bio et la landing avant tout autre changement | plan 21 jours, « Assets + attribution » |
| J7 | Reddit | go / no-go définitif : 0 retrait sur les subs retenus, comptes non bannis | no-go = Reddit sort de M1 jusqu'à la vague suivante | plan 21 jours, J7 |
| J14 | X | < 5 inscrits `utmSource = 'x'` (cumul) | stop X | plan 21 jours, J14 |
| J14 | Reddit | 0 ban **et** ≥ 50 visiteurs `utm_source=reddit` (PostHog `$pageview`) | sinon stop Reddit | plan 21 jours, J14 |
| J14 | toutes | une plateforme sous son seuil **deux lectures de suite** | coupée, budget réalloué à celles qui tiennent ; celles qui tiennent sont doublées | Machine ×10, §5 et §7 |
| J14 | social (x + reddit + …) | < 20 inscrits au total | tout stopper sauf les annuaires (règle globale, énoncée J10 dans le plan) | plan 21 jours |

Garde-fou statistique (plan 21 jours, §3) : **aucune décision de go/no-go ou de CPA sous n < 5 payants ou < 200 expositions** ; en dessous on continue ou on coupe sur le coût, jamais sur un taux. Le coût par payant se calcule avec `documentation/business/couts-reels.md` (coût par asset dans `content-pipeline.md` §9 — une réplication par post source du radar, une relance au plus, soit 2 générations au total par couple (personnage, post source) ; prix des routes de réplication dans `lib/billing/pricing.ts` : `INSTAGRAM_IMAGE_REPLICATE = 3` cr, `VIDEO_REPLICATE_FAITHFUL_STD_PER_5S = 15`, `VIDEO_REPLICATE_FAITHFUL_HD_PER_5S = 25`, `VIDEO_REPLICATE_ADAPT_PER_5S = 21`, durée facturée `ceil(prix × max(0,8, s/5))` par `calculateVideoReplicateCost` ; comptes et proxies dans `infrastructure-geelark-proxies.md`).

### 7.3 KPI suivis chaque jour (dans le rapport) et leur seuil d'alerte

| KPI | Calcul | Alerte |
|---|---|---|
| Inscrits par plateforme et par personnage | SQL §3, veille et cumul | un personnage à 0 inscrit sur 7 jours de publication → revue de sa fiche et de ses liens (`personas.md`) |
| Payants par plateforme | SQL §3, `Subscription.status = 'active'` | — (lecture J14 seulement) |
| Activation | `pct_actives` SQL §3 | < 30 % sur une source à n ≥ 50 inscrits → problème de landing (comparer à 32 % visiteur→inscrit et 5,7 % inscrit→abonné mesurés, `documentation/business/growth/base-de-faits-2026-09-13.md`) |
| Médiane de vues à 24 h par plateforme | `farm_post_metrics`, 7 jours glissants | seuils J4 ci-dessus |
| Retraits Reddit | `farm_post_metrics.removed` | 2 sur un sub → seuil J4 |
| Santé | `farm_accounts.health` ≠ `ok` | chaque ligne va dans « Humain » si `verification_required`, `logged_out`, `suspended` |
| Sessions | `Data:` des runs (`videos`, `likes`, `follows`, `health`, `error`) | `error` avec 0 vidéo sur 2 sessions de suite → sélecteurs à re-miner (`account-creation.md`, Skill Miner) |
| Divulgation : inscrits pour 1 000 vues et comptes rouges, par groupe | SQL §8, cumul | affiché tous les jours, **lu** à J14, **décidé** à J21 (§8.3) ; un compte `undeclared` sanctionné pour contenu IA non étiqueté → bascule individuelle, `disclosed_since` daté, sortie de la comparaison (§8.3, exception (a)) |

## 8. Test de divulgation IA : `declared` contre `undeclared`

Décision du 2026-09-14 (`00-brief-decisions.md`, C5) : sur Instagram, TikTok, X et Reddit, **trois personnages se déclarent IA** (mention en bio, toggle AIGC TikTok, `#AI`) et **trois ne le font pas**, pour mesurer ce que la divulgation coûte ou rapporte. Sur Fanvue les six sont déclarés (badge « AI creator » obligatoire) : les inscrits `utm_source=fanvue` sont hors test. Répartition (slugs de `personas.md` §3.2, marqués « à valider » par Nathan ; si un nom change, seules les fiches et `scripts/social/groups.sql` changent) :

| Groupe | Personnages (niche radar) | Ce que le flag pilote |
|---|---|---|
| `declared` | `sierra` (fitness), `camila` (latina), `hana` (asiatique) | bio « AI » (`personas.md` §6), filigrane `@<handle> · AI`, `SocialPublication.aigcLabel = true` figé à la mise en file, `hashtags.always = ["#AI"]`, mention IA dans la légende (`content-pipeline.md`, C7) |
| `undeclared` | `skyler` (bimbo), `riley` (e-girl), `vera` (gothique) | aucune mention IA sur les quatre réseaux : ni bio, ni légende, ni filigrane « AI », ni flair IA obligatoire sur Reddit ; `aigcLabel = false` ; Fanvue déclarée quand même |

Le flag vit dans la fiche persona (`disclosed: true | false`, plus `disclosed_since: <date>` quand un personnage bascule) et voyage dans le payload du pont (`GET /api/farm/accounts`, `GET /api/farm/personas/{character_id}`, `bridge-ofmai-farm.md` §3) : la ferme ne décide jamais elle-même de cocher ou non le toggle, et ne relit pas la fiche au moment du post — le toggle suit `aigc_label`, figé sur `SocialPublication.aigcLabel` à la mise en file (`bridge-ofmai-farm.md` §3.2).

Règle unique de bascule, la même que `bridge-ofmai-farm.md` §3.1 : **`disclosed` ne change pas pendant le test, sauf (a) un compte non déclaré sanctionné par la plateforme pour contenu IA non étiqueté : bascule individuelle, `disclosed_since` daté, le compte sort de la comparaison ; (b) la décision de J21 qui peut déclarer les six.** Un seul libellé de groupe partout — `declared` / `undeclared`, dérivé du booléen `disclosed` de la fiche : clé `divulgation[].groupe` du rapport (§6), `scripts/social/groups.sql`, `lib/social/disclosure.ts`. Côté mesure, le groupe se déduit du slug (`utm_content` en prod, `AICharacter.publicSlug` pour les métriques de posts — colonne à créer, C1) par une seule table de correspondance, `scripts/social/groups.sql`, recopiée dans chaque requête ci-dessous et vérifiée égale aux fiches par un test de `lib/social/personas` (`build-plan.md`).

### 8.1 Métriques comparées

Toujours **par groupe et par plateforme** (les six niches ne se valent pas : comparer `declared` à `undeclared` toutes plateformes confondues mélangerait l'effet de la niche et celui de la mention), cumul depuis le premier jour de publication de la plateforme :

| Métrique | Ce qu'elle mesure | Source | Lecture |
|---|---|---|---|
| Médiane de vues à 24 h par post | la distribution : la plateforme montre-t-elle moins un contenu étiqueté IA ? | `SocialPostMetric` (= `farm_post_metrics`) à `atHours = 24`, hors observateur et posts retirés | J14 |
| Engagement = (likes + commentaires) / vues | l'accueil du public averti ou non | idem | J14 |
| **Inscrits pour 1 000 vues** | la conversion : la mention « IA » attire-t-elle ou repousse-t-elle vers OFMAI ? | inscrits `User.utmContent` du groupe ÷ vues à 24 h cumulées du groupe (même plateforme) × 1 000 | J14, J21 |
| Payants / inscrit, revenu par groupe | la qualité des inscrits | `Subscription.status = 'active'`, `price` | J21 (garde-fou du §7.2) |
| Comptes rouges, retraits, bans par groupe | le prix du silence : un contenu IA non étiqueté peut être retiré ou sanctionné | `SocialAccount.health`, `SocialPostMetric.removed`, `farm_signals` | tous les jours, J14 |
| Coût par payant par groupe | ce que coûte réellement chacune des deux stratégies | assets gardés du groupe × coût par asset (`content-pipeline.md` §9) ÷ payants | J21 |

Correction secondaire, facultative : rapporter la médiane de vues du personnage à la médiane de sa niche dans le radar (`personas.md` §3, `TrackedInfluencer` × `ScrapedPost`) pour lisser l'écart de niche [à vérifier : les médianes du radar sont Instagram, pas TikTok ni X]. Le vrai contrôle est la permutation de la vague suivante (§8.3).

### 8.2 Requêtes (skill `prod`, à ranger dans `scripts/social/divulgation.sql`)

Inscrits, activés, payants par groupe × plateforme — existe dès le premier lien posé :

```sql
WITH groupes(personnage, groupe) AS (VALUES                       -- = scripts/social/groups.sql (slugs personas.md §3.2)
  ('sierra', 'declared'), ('camila', 'declared'), ('hana', 'declared'),
  ('skyler', 'undeclared'), ('riley', 'undeclared'), ('vera', 'undeclared')),
actives AS (SELECT "userId" FROM "Generation" WHERE status = 'completed' GROUP BY 1)
SELECT g.groupe, u."utmSource" AS plateforme,
       count(*) AS inscrits,
       count(a."userId") AS actives,
       count(*) FILTER (WHERE s.status = 'active') AS abonnes_actifs,
       coalesce(sum(s.price) FILTER (WHERE s.status = 'active' AND s."billingInterval" = 'monthly'), 0) AS mrr_mensuels,
       round(100.0 * count(*) FILTER (WHERE s.status = 'active') / greatest(count(*), 1), 2) AS pct_payants
FROM "User" u
JOIN groupes g ON g.personnage = u."utmContent"
LEFT JOIN "Subscription" s ON s."userId" = u.id
LEFT JOIN actives a ON a."userId" = u.id
WHERE u."createdAt" >= '2026-09-21'
  AND u."utmSource" IN ('instagram', 'tiktok', 'x', 'reddit')
GROUP BY 1, 2
ORDER BY 2, 1;
```

Vues, engagement, retraits par groupe × plateforme — après le pont (`SocialPostMetric`, `bridge-ofmai-farm.md` §5.1) et `AICharacter.publicSlug` (C1) :

```sql
WITH groupes(personnage, groupe) AS (VALUES ('sierra', 'declared'), ('camila', 'declared'), ('hana', 'declared'),
  ('skyler', 'undeclared'), ('riley', 'undeclared'), ('vera', 'undeclared')),
posts AS (
  SELECT g.groupe, sa.platform AS plateforme, coalesce(m.views, m.impressions, 0) AS vues, m.likes, m.comments, m.removed
  FROM "SocialPostMetric" m
  JOIN "SocialPublication" p ON p.id = m."publicationId"
  JOIN "SocialAccount" sa ON sa.id = p."socialAccountId"
  JOIN "AICharacter" c ON c.id = sa."characterId"
  JOIN groupes g ON g.personnage = c."publicSlug"
  WHERE m."atHours" = 24 AND m.source <> 'observer' AND p."postedAt" >= '2026-09-21')
SELECT groupe, plateforme, count(*) AS posts,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY vues) FILTER (WHERE NOT removed) AS mediane_vues_24h,
       sum(vues) AS vues_24h_cumul,
       round(100.0 * sum(likes + comments) / greatest(sum(vues), 1), 2) AS pct_engagement,
       count(*) FILTER (WHERE removed) AS retraits
FROM posts
GROUP BY 1, 2
ORDER BY 2, 1;
```

`inscrits_pour_1000_vues = inscrits × 1000 / vues_24h_cumul`, joint sur (`groupe`, `plateforme`) dans `scripts/social/daily-report.mjs` (clé `divulgation` du §6). Les vues à 24 h sous-estiment les vues totales, de la même façon dans les deux groupes : c'est le dénominateur retenu, pas les relevés à 72 h ou 168 h. Comptes rouges cumulés : `farm_signals` × `farm_accounts.character_id` (SQLite de la ferme, mêmes ids `AICharacter`), un compte compté une fois par jour de signal. PostHog : deux cohortes sur `$initial_utm_content` ∈ slugs de chaque groupe [à vérifier : propriété personne disponible, §4], utiles pour voir où le funnel diverge, jamais pour décider.

### 8.3 Lecture à J14, décision à J21

Convention : J1 = premier jour de publication (§7). Garde-fou du §7.2 appliqué **par groupe** : sous 5 payants ou 200 expositions dans un groupe, aucun taux ne décide. Avec les hypothèses du §7.1 (≈ 60 payants sur 21 jours pour six personnages), on attend ≈ 30 payants par groupe à J21 : assez pour voir un écart de 2× sur les payants, pas 30 % ; la décision J21 se prend donc d'abord sur **inscrits pour 1 000 vues** (centaines d'inscrits par groupe) et sur la **santé**, les payants confirmant ou infirmant. Écart minimal retenu : **30 %** (proposé — en dessous, à ces effectifs, c'est du bruit).

- **Tous les jours — exception (a), règle santé, pas une lecture** : un compte `undeclared` dont un post est retiré ou signalé pour contenu IA non étiqueté, ou qui prend un signal `verification_required` / `suspended` dans la journée qui suit un post, **se déclare dans l'heure** (bio + `disclosed: true`, `disclosed_since` daté du jour ; les publications mises en file après cette date portent `aigcLabel = true`, celles déjà en file gardent le label figé à leur mise en file, `bridge-ofmai-farm.md` §3.2). La bascule est **individuelle** — les deux autres comptes `undeclared` ne bougent pas — et le compte **sort de la comparaison** ; ses données antérieures restent au groupe `undeclared` jusqu'à `disclosed_since`. Un compte rouge le reste 48 h (`health-canaries.md`) quel que soit son groupe.
- **J14 (lecture, aucune décision)** : les six lignes du tableau §8.1 par plateforme, dans le rapport. Une seule réserve : si le groupe `undeclared` cumule **≥ 2 comptes rouges** sur 14 jours contre 0 dans `declared`, la décision (b) est **avancée** et les six se déclarent sans attendre J21 — le risque de perdre un compte chauffé 14 jours (`account-creation.md`) vaut plus que le gain qu'on cherche. Sinon on ne change rien, même si un groupe est devant.
- **J21 (décision — exception (b))**, garde-fou atteint dans les deux groupes :
  1. `undeclared` fait **≥ +30 % d'inscrits pour 1 000 vues sur au moins deux plateformes**, payants/inscrit non inférieur, santé équivalente → on garde le partage ; la vague suivante (`utm_campaign` nouvelle valeur) **permute** les groupes (mêmes niches, mention inversée) pour séparer l'effet niche de l'effet mention ; l'extension à d'autres personnages est une décision de Nathan, jamais automatique.
  2. Écart < 30 % dans les deux sens, **ou** `declared` devant → **les six se déclarent** (fin du test) ; la divulgation devient la règle de la vague suivante et `rules.md` est mis à jour dans le même changement.
  3. Garde-fou non atteint dans un groupe → pas de décision sur un taux ; on prolonge d'une semaine (lecture J28) sans rien changer, sauf l'exception (a) du premier point.

Dans tous les cas, ce qui se déclare se déclare **par compte et par plateforme** dans la forme exigée par la plateforme (`publishing.md`) ; le badge Fanvue ne bouge jamais.

## 9. Ce qui n'existe pas encore (renvoi `build-plan.md`)

- Garde `utm_medium ∈ {bio, dm, comment, post, profile, social}` dans `resolveSource` (`app/api/attribution/route.ts`, E10.1, vague 1) — sans lui, Instagram compte comme Meta.
- Relais de la query string dans `app/r/[code]/route.ts` si les liens affiliés doivent un jour porter des UTM.
- Table `farm_post_metrics` + workflow `metrics_pull` par skill (enfilé par le daemon `bridge`, étape 7) + sélecteurs de compteurs dans `gitd/skills/ofmai_instagram/elements.yaml` et `gitd/skills/ofmai_tiktok/elements.yaml`.
- Événement `metrics` du pont et sa table Prisma (`bridge-ofmai-farm.md`).
- `scripts/social/daily-report.mjs` (avec la clé `divulgation`) et la phase `Rapport` de `.claude/workflows/growth-content-army.js`.
- Champ `disclosed` / `disclosed_since` des fiches persona (`lib/social/personas/*.yaml`), sa recopie dans les payloads du pont et dans `SocialPublication.aigcLabel` (figé à la mise en file), `AICharacter.publicSlug` (C1), et `scripts/social/groups.sql` avec le test qui le compare aux fiches.
- `lib/social/disclosure.ts` : les libellés `declared` / `undeclared` dérivés de `disclosed`, et les seuils du §8.3 (écart 30 % sur ≥ 2 plateformes, garde-fou n ≥ 5 payants / 200 expositions par groupe, lecture J14, décision J21, prolongation J28) lus depuis ce module plutôt que réécrits dans le rapport (`build-plan.md` E10.5).
- Aucune requête SQL de ce fichier n'est enregistrée dans `scripts/` : les mettre dans `scripts/social/*.sql` (`divulgation.sql` pour le §8) pour que le rapport et les lectures J7 / J14 / J21 utilisent la même.
