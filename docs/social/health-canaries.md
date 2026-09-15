# Santé des comptes : signaux, canaris de shadowban, machine d'états, kill-switches

> **Nature** : reference
> **Statut** : à vérifier — la détection écran, la machine d'états et `clear-health` sont dans le code du fork ; les canaris, les règles collectives, l'escalade Discord et le tableau de bord farm n'existent pas encore
> **À jour au** : 2026-09-14
> **Répond à** : comment la ferme sait qu'un compte est en danger, ce qu'elle fait toute seule, ce qu'elle laisse à un humain, et comment on voit tout ça
> **Code concerné** : fork ofmai-farm `gitd/farm/health.py`, `gitd/farm/policy.py` (§ Health state machine), `gitd/farm/ledger.py`, `gitd/farm/warm.py`, `gitd/farm/skillkit.py`, `gitd/farm/planner.py`, `gitd/farm/cli.py`, `gitd/farm/models.py`, `gitd/skills/checkpoint.py`, `gitd/routers/scheduler.py`, `frontend/src/views/SchedulerView.vue`, `tests/test_farm_health.py`, `tests/test_farm_policy.py`, `tests/test_farm_ledger.py` ; OFMAI `lib/core/discord-alerts.ts`, `.claude/loop/notify.mjs`, `app/api/farm/events` (à créer, `bridge-ofmai-farm.md`), `lib/social/health.ts` (à créer)

Les règles absolues sont fixées dans `rules.md` (R16, R18, R25-R32) ; ce fichier dit comment elles s'exécutent. Le transport des signaux vers OFMAI est dans `bridge-ofmai-farm.md` (événement `health_signal`, champ `paused_until`), le relevé des vues dans `metrics-attribution.md` (§5.2, table `farm_post_metrics`), les chiffres de chauffe dans `warming-policy.md`, la configuration du profil observateur dans `infrastructure-geelark-proxies.md`.

## 1. Signaux existants : `gitd/farm/health.py`

`detect(platform, screen_text)` fait une recherche regex insensible à la casse sur le dump XML (ou le texte OCR) de l'écran et renvoie le signal **le plus grave** présent, dans l'ordre `_ORDER = ("suspended", "logged_out", "verification", "action_blocked")`, sous la forme `HealthSignal(kind, matched)` ; `None` si l'écran est propre. Seules deux plateformes ont des motifs : `instagram` et `tiktok`. Un `platform` inconnu (`x`, `reddit`) renvoie toujours `None` — à ajouter avec les skills X/Reddit (`build-plan.md`).

| Plateforme | `kind` | Motifs (regex de `_PATTERNS`, recopiés à l'identique) |
|---|---|---|
| instagram | `action_blocked` | `action blocked` · `try again later` · `we limit how often` · `we restrict certain` · `you.?re temporarily blocked` · `couldn.?t (like\|follow\|comment\|post)` |
| instagram | `verification` | `confirm it.?s you` · `suspicious login` · `verify your (phone\|email\|account\|identity)` · `enter the confirmation code` · `help us confirm` · `we.?ve detected unusual activity` · `add your phone number` |
| instagram | `logged_out` | `text="log in"` · `content-desc="log in"` · `create new account` · `forgot password` |
| instagram | `suspended` | `your account has been (suspended\|disabled)` · `we suspended your account` · `we disabled your account` · `you can.?t use instagram` |
| tiktok | `action_blocked` | `tapping too fast` · `too many attempts` · `you.?re (liking\|following\|commenting) too` · `try again later` · `maximum number of` |
| tiktok | `verification` | `verify to continue` · `drag the slider` · `select 2 objects` · `unusual activity` · `verify your (phone\|email\|account)` · `enter (the )?\d-digit code` |
| tiktok | `logged_out` | `text="log in"` · `sign up for tiktok` · `log in to tiktok` |
| tiktok | `suspended` | `account (is\|has been) (temporarily \|permanently )?(suspended\|banned)` · `we banned your account` · `community guidelines violation` |

Où c'est appelé (vérifié) : uniquement dans `run_session()` (`gitd/farm/warm.py`), via `check_health(xml)` — après `open_feed`, à chaque tour de boucle, après une visite de profil, après un commentaire. Un signal → `ledger.signal(kind, matched)` (ligne `farm_signals` + transition d'état, §3) → sortie de la boucle → `WarmSessionAction.execute` renvoie `success=False, error="health signal: <kind>"` (`gitd/farm/skillkit.py`). Les popups de `skill.yaml` ne sont pas des signaux : « Health signals … are matched by gitd/farm/health.py, not here ».

**Trou vérifié** : `PostReelAction` et `PostVideoAction` (`gitd/skills/ofmai_*/workflows/__init__.py`) n'appellent jamais `health.detect` — un « Action Blocked » sur l'écran de publication passe inaperçu et le job finit en `success=False` sans signal. À corriger dans `build-plan.md` : `check_health` avant `Share`/`Post` et après.

`zero_reach(view_counts, posts=3)` : vrai si les `posts` derniers posts ont chacun **≤ 2 vues** (`all(v <= 2 for v in tail)`, et il faut au moins `posts` valeurs). Test `test_zero_reach_heuristic` : `[120, 80, 0, 1, 2]` → vrai, `[120, 80, 0, 1, 40]` → faux, `[0, 1]` → faux. La fonction n'est appelée nulle part et le `kind = "shadowban"` que `HealthSignal` prévoit (« raised by analytics, not by screen ») n'est jamais émis : c'est le §2.

## 2. Canaris de shadowban depuis le profil observateur

Un shadowban ne s'affiche pas à l'écran du compte : il se voit **de l'extérieur**. Le canari est un relevé fait depuis le **profil observateur** — un profil GeeLark à part, sur son propre proxy, **jamais connecté à un compte de personnage** (`infrastructure-geelark-proxies.md`) — comparé à une référence. Il produit soit `visible = 1/0`, soit des vues à 24 h comparées à la médiane du compte.

Rien de ce paragraphe n'est codé. Il définit ce que le workflow `canary_check` (un par skill, à créer à côté de `metrics_pull` de `metrics-attribution.md` §5.2) doit faire, et ce que le module `gitd/farm/canary.py` (à créer) décide.

| Plateforme | Procédure sur l'observateur | Quand | Référence | Verdict `shadowban` si |
|---|---|---|---|---|
| Reddit | ouvrir `old.reddit.com/r/<sub>/new/` déconnecté, chercher le post par son titre dans les 25 premiers ; puis ouvrir l'URL du post : `[removed]` ou « Sorry, this post was removed » → `removed = 1` [à vérifier : rendu déconnecté exact] | **T+30 min** après chaque post (l'automod agit tout de suite) et T+24 h | aucune (binaire) | post invisible dans `new` **sans** être `removed` sur 2 posts de suite du même compte |
| X | **pas de canari depuis l'observateur** (décision V1 : la recherche X exige une session [à vérifier], et l'observateur reste déconnecté de tout). La visibilité se mesure par les impressions du compte lui-même : `impression_count` par `publish-api.ts --metrics` (E8.2, palier Basic) ou, en accès Free, écran « Voir les statistiques » sur l'appareil (`metrics-attribution.md` §5.2) | T+24 h ± 2 h par post | médiane des impressions à 24 h des 10 derniers posts du compte | 3 posts de suite < 10 % de la référence |
| TikTok | (a) recherche du `@handle` dans l'app déconnectée : le profil doit sortir ; (b) vues à 24 h lues **sur l'appareil du personnage** (grille du profil, `metrics_pull`) | (a) 1×/jour par compte ; (b) T+24 h ± 2 h par post | médiane des vues à 24 h des 10 derniers posts du compte (≥ 5 posts sinon médiane de la plateforme sur 7 j, tous personnages) | `zero_reach(views)` vrai, **ou** 3 posts de suite < 10 % de la référence, **ou** profil introuvable 2 jours de suite |
| Instagram | (a) recherche du `@handle` déconnecté : profil proposé ; (b) ouvrir `instagram.com/<handle>/` : le Reel du jour est dans la grille ; (c) lectures à 24 h depuis l'appareil du personnage | (a)(b) 1×/jour par compte ; (c) T+24 h ± 2 h | idem TikTok | mêmes règles que TikTok ; un mur de connexion sur (b) n'est pas un signal (limite Instagram déconnecté [à vérifier]) |

Règles communes :

- Le canari tourne **dans une fenêtre de session normale** de l'observateur (jamais `QUIET_HOURS = range(1, 7)` du fuseau du compte observé), avec les mêmes primitives humanisées (`gitd/farm/human.py`) — un observateur qui ouvre 40 profils à la chaîne à 3 h du matin est lui-même un signal.
- Le résultat s'écrit dans `farm_post_metrics` (colonnes de `metrics-attribution.md` §5.2, `source = "observer"`) avec une colonne à ajouter : `visible` (0/1, NULL si non relevé). Le seuil « 10 % de la référence » est un point de départ [à calibrer sur les 20 premiers posts par plateforme] ; il vit dans `canary.py` (`SHADOWBAN_RATIO = 0.10`, `SHADOWBAN_STREAK = 3`), pas dans un prompt.
- Un verdict positif appelle `FarmSession.signal("shadowban", matched="<règle> …")` sur le compte **observé** (pas sur l'observateur, qui n'est pas dans le ledger) → état `SHADOWBAN_SUSPECT` 7 jours (§3) → événement `health_signal` vers OFMAI (`bridge-ofmai-farm.md` §4.1).
- Le retrait d'un post Reddit n'est pas un shadowban : c'est un strike sur le sub (§4).
- L'observateur n'est pas un `farm_accounts` : `ledger.add_account()` le chaufferait et refuse `--role observer` (E1.1, `test_add_account_rejects_role_observer`). Son serial vit dans la config du fork (`FARM_OBSERVER_DEVICE`, `gitd/config.py`, à créer E1.3) et côté OFMAI dans `SocialAccount.role = "observer"` (`bridge-ofmai-farm.md` §3.1) pour la lecture seule ; le pont ne le recopie jamais. Il est facturé à la minute : `growth-farm-watch.js` le démarre, le relie, enfile les `canary_check`, l'éteint (`build-plan.md` §12).

## 3. Machine d'états (`policy.Health`, recopiée du code)

```text
                 action_blocked                        expiration (now ≥ until) → ok,
   ┌──────────────────────────────▶ COOLDOWN ──────────▶ phase_override CONSERVÉ
   │                                 48 h, une phase en arrière
   │        shadowban (§2)
  OK ─────────────────────────────▶ SHADOWBAN_SUSPECT ─▶ idem, override = consume
   │        verification
   ├──────────────────────────────▶ VERIFICATION_REQUIRED ─┐
   │        logged_out                                     │  jamais d'expiration :
   ├──────────────────────────────▶ LOGGED_OUT ────────────┤  `accounts clear-health`
   │        suspended                                      │  par un humain (§6)
   └──────────────────────────────▶ SUSPENDED (until = +30 j, informatif) ─┘
```

| Signal (`apply_signal`) | `status` | `until` | `phase_override` | `can_run(now)` |
|---|---|---|---|---|
| `action_blocked` | `cooldown` | `now + COOLDOWN_HOURS` (48 h) | phase **précédant** `natural_phase` (`consume` reste `consume`) | `now ≥ until` |
| `shadowban` | `shadowban_suspect` | `now + SHADOWBAN_DAYS` (7 j) | `consume` | `now ≥ until` |
| `verification` | `verification_required` | `None` | inchangé | `False` |
| `logged_out` | `logged_out` | `None` | inchangé | `False` |
| `suspended` | `suspended` | `now + QUARANTINE_DAYS` (30 j) | `None` | `False` (la quarantaine est informative, « device + IP quarantined 30 days ») |
| autre `kind` | inchangé | — | — | — |

Détails vérifiés dans `gitd/farm/ledger.py` :

- `budget_for()` abaisse le budget à `effective_phase(natural) = min(natural, phase_override)` avec le **même seed** (compte, jour) : les caps de la phase forcée, le `day_of_life` réel.
- `FarmSession.signal()` passe à `apply_signal` la phase du **budget courant** (`self.tracker.budget.phase`), déjà abaissée si le compte récupère : un deuxième `action_blocked` recule d'une phase de plus (`network → light → consume`).
- `open_session()` : si `cooldown` / `shadowban_suspect` est expiré, `health = "ok"`, `health_until = NULL`, **`phase_override` conservé** jusqu'à `clear-health` ; sinon `PermissionError("@… is cooldown until …")` ou `"… — a human must act on the device"`. Test : `test_signal_puts_account_in_cooldown_and_blocks_next_session`.
- `planner.tick()` saute tout compte dont `health_state(acc).can_run(now)` est faux, et tout compte `api_mode` (`test_tick_skips_unhealthy_and_api_mode_accounts`).
- Un compte en `consume` forcé ne poste pas : `posts_per_week = 0` dans `CAPS[Phase.CONSUME]` → `caps[POST] = 0`. C'est ce qui fait de `SHADOWBAN_SUSPECT` « 7 days consume-only, no post ».

## 4. Seuils et règles

| # | Règle | Dans le code | À construire |
|---|---|---|---|
| S1 | **Un signal → 48 h de pause du compte** et une phase en arrière | `action_blocked` → `COOLDOWN_HOURS = 48` | `verification`, `logged_out`, `suspended` n'ont **pas** de minuterie : humain obligatoire (§6). Le « 48 h » du brief est le plancher, pas le plafond |
| S2 | Shadowban suspecté → 7 jours consommation seule | `SHADOWBAN_DAYS = 7`, override `consume` | l'émission du signal (§2) |
| S3 | **Deux comptes rouges en 48 h sur une plateforme → plateforme en pause 48 h** | rien | `gitd/farm/collective.py` (ci-dessous) + miroir OFMAI |
| S4 | **Trois comptes `suspended` en 48 h sur une plateforme → plateforme coupée** jusqu'à post-mortem daté dans `docs/social/decisions/` | rien | idem, `cut = 1`, levée manuelle seulement |
| S5 | **L'IP statique ne change jamais** (R18) : une `verification` se résout sur l'appareil, avec la même IP. Rayon d'un `suspended` (même règle dans R18, `infrastructure-geelark-proxies.md` §3, `account-creation.md` §9) : **1ᵉʳ `suspended` sur un téléphone** → la plateforme est abandonnée sur ce téléphone (`accounts disable`, `pm clear <package>`, `SocialAccount.status = banned`, 30 j sans nouvelle inscription sur cette plateforme), les autres comptes du personnage continuent avec un canari quotidien pendant 7 j ; **2ᵉ `suspended` sur le même téléphone dans les 30 j, toute plateforme** → téléphone et IP en quarantaine 30 j, tous les comptes `disable`, profil supprimé, IP rendue jamais réaffectée, le personnage repart sur un nouveau profil et de nouveaux comptes (runbook §10) | `QUARANTINE_DAYS = 30` (informatif) | la quarantaine est un geste GeeLark/IPRoyal manuel (`infrastructure-geelark-proxies.md`) |
| S6 | **Retraits Reddit par sub** : un post retiré = un strike sur le sub pour ce personnage ; 2 strikes sur un sub → sub retiré de sa liste (`publishing.md`), **sans** pause du compte ; un retrait d'un post qui contenait un lien (violation R22) ou un message de modération citant « ban »/« spam » → `action_blocked` (48 h) | rien | `farm_post_metrics.removed` (`metrics-attribution.md`) + compteur par sub dans la fiche persona côté OFMAI |
| S7 | Premier `HTTP 429` sur une API X/Reddit → `action_blocked`, aucun réessai (incident @potter_society, R16) | rien (aucun chemin API) | `ledger.signal_api(account, kind, matched)` — même écriture que `FarmSession.signal`, sans session |
| S8 | Un signal arrête la session en cours, sans réessai (R27) | `check_health` → `break` ; `WarmSessionAction.max_retries = 1` | `check_health` dans `post_video` (§1) |

Définition d'un compte **rouge** pour S3 : une ligne `farm_signals` de `kind ∈ {action_blocked, verification, suspended, shadowban}` datant de moins de 48 h. `logged_out` est exclu (le plus souvent un appareil réinitialisé, pas la plateforme). Deux lignes du **même** compte ne comptent qu'une fois.

`gitd/farm/collective.py` (à créer) — une table et deux fonctions, testées sans appareil :

```text
farm_platforms : platform TEXT PK · paused_until TEXT (ISO local) · cut INTEGER 0/1 · reason TEXT · updated_at TEXT
red_accounts(db, platform, now) -> set[int]      # ids distincts, signaux < 48 h
evaluate(db, platform, now) -> None              # S3 : ≥ 2 → paused_until = now + 48 h ; S4 : ≥ 3 suspended → cut = 1
is_blocked(db, platform, now) -> bool            # cut ou now < paused_until
```

`evaluate()` est appelée par `FarmSession.signal()` juste après l'écriture de `farm_signals` (même commit) ; `is_blocked()` par `planner.tick()` avant `due_slots()` et par le daemon `bridge` avant tout `GET /api/farm/queue` ou publication API. Côté OFMAI, le même calcul sur `FarmEvent` (`kind = health_signal`, 48 h) dans `lib/social/health.ts` pose `SocialAccount.pausedUntil` sur tous les comptes de la plateforme, que le fork recopie dans `farm_accounts.paused_until` (`bridge-ofmai-farm.md` §3.1, §5.2). Chaque côté applique le **plus strict** des deux : la plateforme s'arrête même quand le pont est tombé. Une pause S3 expire seule ; S4 ne se lève que par `platform resume`.

Kill-switch par machine (R31, E5.3) : fichier `data/farm/STOP` sur le Mac mini, testé à chaque tick par `planner.tick` et `bridge.tick` (qui n'enfilent plus rien) ; `python -m gitd.farm.cli stop` le crée **puis** tue chaque job `running` par `POST /api/scheduler/queue/{qid}/kill` ; `start` retire le fichier. Test : `tests/test_farm_planner.py::test_stop_file_respected`.

```bash
python -m gitd.farm.cli platform pause tiktok --hours 48     # S3 à la main (à créer)
python -m gitd.farm.cli platform cut tiktok --reason "3 suspended"   # S4
python -m gitd.farm.cli platform resume tiktok               # levée humaine

Deux routes, une par côté, complémentaires — les deux sont nécessaires pour rouvrir vraiment :
`POST /api/farm/platform/{p}/resume` (fork, `X-Ghost-Admin-Token`) rouvre `farm_platforms` et laisse le planner
reprendre ; `POST /api/admin/social/platforms/{p}/resume` (OFMAI, `requireAdminOrInternalKey`) remet
`SocialPlatformState` à `open` et efface les `SocialAccount.pausedUntil` encore à venir — sans elle, un `cut`
laisse une pause de dix ans que rien ne lève côté plateforme et la file reste vide. Idempotente, elle renvoie
`stillRed` / `stillSuspended` : ce que S3/S4 voient encore dans la fenêtre de 48 h, c'est-à-dire ce que l'humain
passe outre, et qui peut redéclencher la règle au signal suivant.
python -m gitd.farm.cli stop                                 # tout, tout de suite
```

## 5. Escalade humaine : Discord

Nathan est en Thaïlande, le Mac mini à Paris : sans alerte, un compte en `verification_required` attend des jours (R32). Deux chemins, un par côté.

**OFMAI (existe)** : `sendDiscordAlert({ level: "warn" | "error" | "critical", title, message, route?, error? })` dans `lib/core/discord-alerts.ts` — embed coloré (orange / rouge / rouge foncé), champs Environment, Hostname, Timestamp, Route ; **no-op sans `DISCORD_WEBHOOK_URL`**, jamais bloquant. Aujourd'hui aucun appel social ; le handler de `POST /api/farm/events` (`bridge-ofmai-farm.md` §4) l'appelle à la réception :

| Événement reçu | `level` | Qui agit, sous combien de temps |
|---|---|---|
| `health_signal` avec `new_health = cooldown` | `warn` | personne ; lecture au rapport du matin |
| `health_signal` avec `new_health = shadowban_suspect` | `warn` | humain regarde le canari (§2) dans la journée |
| `health_signal` avec `new_health ∈ {verification_required, logged_out}` | `error` | humain sur l'appareil **dans l'heure** (live stream Ghost, code SMS/email, R25) puis `clear-health` |
| `health_signal` avec `new_health = suspended` | `critical` | humain : `accounts disable`, quarantaine appareil + IP, vérifier S4 |
| S3 déclenchée (pause plateforme) | `critical` | humain vérifie les deux comptes, décide de `platform resume` ou d'attendre |
| S4 déclenchée (plateforme coupée) | `critical` | post-mortem daté avant toute reprise |
| `post_failed` avec `ambiguous = true` | `warn` | humain regarde le profil, `retry` ou `PATCH …/publications/{id}` (`bridge-ofmai-farm.md` §7) |

```ts
await sendDiscordAlert({
  level: "error",
  title: "Santé farm : instagram @sierra.cole → verification_required",
  message: "matched « confirm it's you » · session 9c2d0b4e1a77 · phase_override light · un humain doit agir sur R58N1234",
  route: "farm/events",
});
```

**Fork (n'existe pas)** : `grep -rni discord gitd docs` ne trouve que l'étiquette d'app `"com.discord": "Discord"` dans `gitd/services/device_context.py`. Il faut `gitd/farm/alerts.py` (à créer) : `notify(level, title, message)` qui poste sur le webhook lu dans `FARM_DISCORD_WEBHOOK_URL`, sinon Trousseau macOS `security find-generic-password -s ofmai-discord-webhook -w` — exactement la résolution de `.claude/loop/notify.mjs` — texte brut tronqué à 1 900 caractères. Il sert **seulement** à ce qui ne transite pas par OFMAI : un checkpoint `awaiting_human` (`gitd/skills/checkpoint.py`, `set_state("awaiting_human", {reason, prompt, success, timeout_s})`, `DEFAULT_TIMEOUT_S = 600`), un `POST /api/farm/events` en 401 ou injoignable depuis plus de 15 min (`bridge-ofmai-farm.md` §7), un `stop`/`platform cut` lancé à la main. Les signaux santé eux-mêmes passent par OFMAI pour n'être alertés qu'une fois.

Contenu d'un message d'alerte : plateforme, handle, nouvel état, `matched`, serial de l'appareil, action attendue. Jamais de nom de fournisseur, jamais d'identifiant (R9, R10). Le rapport quotidien (comptes par état, ligne « Humain ») est décrit dans `metrics-attribution.md` §6.

## 6. `accounts clear-health` : le geste humain

Code (`gitd/farm/cli.py`, `cmd_accounts`) : `acc.health = "ok"`, `acc.health_until = None`, `acc.phase_override = None`, `db.commit()`, puis `ok: <platform> @<handle> clear-health`. Aucune vérification de l'état courant, aucune ligne `farm_signals` (l'audit du **retour** à `ok` n'existe pas), plateformes limitées à `instagram | tiktok` (`choices` de l'argparse).

```bash
# 1. regarder l'écran (Ghost, port 5055, réseau local ou tunnel SSH)
curl -s "http://127.0.0.1:5055/api/skills/runs?device=R58N1234&limit=5"     # dernier run, awaiting_human ?
# 2. résoudre sur l'appareil : code SMS/email, « This was me », reconnexion — jamais un changement d'IP (S5)
# 3. remettre le compte en état
python -m gitd.farm.cli accounts clear-health instagram @sierra.cole
# 4. vérifier la phase et le budget du jour avant la prochaine session
python -m gitd.farm.cli budget instagram @sierra.cole
```

Quand **ne pas** effacer : après `suspended` (le compte est perdu : `accounts disable`, quarantaine S5) ; pendant un `shadowban_suspect` avant le 7ᵉ jour, sauf si le canari du jour montre le profil visible **et** des vues revenues au-dessus de 50 % de la référence ; après un `logged_out` sans avoir compris pourquoi (session expirée ≠ appareil réinitialisé ≠ mot de passe changé par la plateforme). Un `cooldown` expiré n'a pas besoin de `clear-health` pour reprendre, mais il en a besoin pour **retrouver sa phase naturelle** (`phase_override` conservé, §3).

Ajouts prévus (`build-plan.md`) : `--reason "…"` obligatoire, qui écrit une ligne `farm_signals` de `kind = "cleared"` (ignorée par `apply_signal`, donc sans effet d'état) et pousse un `health_signal` `new_health = "ok"` vers OFMAI (extension du contrat, `signal_kind = "cleared"`) ; l'endpoint `POST /api/farm/accounts/{platform}/{handle}/clear-health` du routeur `gitd/routers/farm.py` sous `X-Ghost-Admin-Token` (`bridge-ofmai-farm.md` §6), pour agir en SSH depuis la Thaïlande sans shell Python.

## 7. Tableau de bord

**Ce que l'onglet Scheduler de Ghost montre déjà** (`frontend/src/views/SchedulerView.vue`, 2 079 lignes) : « 24-Hour Timeline » (canvas, `GET /api/scheduler/timeline`), « Schedules » (CRUD `/api/schedules`), badge « Queue », « Recent Runs » ; un clic sur un run ouvre le panneau de détail qui charge `GET /api/scheduler/history/{run_id}/result` — le JSON `Data: {…}` imprimé par `gitd/skills/_run_skill.py` (l. 302) et parsé par `_parse_job_result_data` (`gitd/services/_job_helpers.py`), affiché en `<pre>` pour un skill générique. C'est là qu'on lit `videos, likes, saves, visits, follows, comments, detours, seconds, health, error, handle, day_of_life, phase, profile_seed` d'une session `trigger = farm`. Attention : `GET /api/scheduler/account-health` et `/account-switch` (`gitd/services/account_health.py`) concernent la table `tiktok_accounts` de Ghost amont, **pas** le ledger farm.

**Ce qui manque** — un panneau « Farm » (même onglet, ou onglet dédié) nourri par le routeur `gitd/routers/farm.py` (`bridge-ofmai-farm.md` §6) :

| Bloc | Source | Colonnes |
|---|---|---|
| Plateformes | `GET /api/farm/health` (à créer, lit `farm_platforms` + `farm_signals` 48 h) | plateforme · comptes · rouges/48 h · `paused_until` · `cut` · dernier canari |
| Comptes | `GET /api/farm/accounts` | plateforme · handle · appareil · jour de vie · phase naturelle / effective · `health` · `health_until` · `phase_override` · `paused_until` · `api_mode` · dernier signal (`kind`, `matched`, `at`) |
| Canaris | `farm_post_metrics` (`source = observer`) | 3 derniers posts : vues 24 h vs référence, `visible`, `removed` |
| Actions | `POST …/clear-health`, `POST …/platform/{p}/resume` | boutons sous `X-Ghost-Admin-Token`, jamais sans |

Et pour le SSH : `python -m gitd.farm.cli health` (à créer) — une ligne par plateforme, puis une ligne par compte dont `health ≠ ok` ou `paused_until` futur, dans l'ordre de `_ORDER`. Côté OFMAI, une page admin `app/admin/social` sur `SocialAccount` / `FarmEvent` est renvoyée à `build-plan.md`.

## 8. Ce qui n'existe pas encore

- Motifs `x` et `reddit` dans `_PATTERNS` ; `check_health` dans `post_video` ; plateformes `x`/`reddit` dans `cli.py`, `ledger.add_account`, `PHASE_EXTRA_DAYS`, `SKILL_BY_PLATFORM`.
- Émission de `shadowban` : `gitd/farm/canary.py`, workflow `canary_check` par skill, profil observateur (`FARM_OBSERVER_DEVICE`), colonne `farm_post_metrics.visible`.
- `gitd/farm/collective.py` + table `farm_platforms`, `is_blocked()` dans `planner.tick` et le daemon bridge, `data/farm/STOP`, commandes `platform pause|cut|resume`, `stop|start`, `health` ; miroir `lib/social/health.ts` côté OFMAI.
- `gitd/farm/alerts.py` ; appels `sendDiscordAlert` dans `app/api/farm/events`.
- `clear-health --reason`, `kind = "cleared"`, endpoint REST.

Tests attendus : fork `tests/test_farm_collective.py` (2 rouges → pause, 2 signaux du même compte → rien, 3 `suspended` → `cut`, `logged_out` ignoré, pause expirée → reprise, `cut` jamais levé seul), extension de `tests/test_farm_health.py` (motifs X/Reddit, `canary.decide()` sur les trois règles TikTok/IG, `zero_reach` branché), `tests/test_farm_planner.py` (`is_blocked` respecté, `test_stop_file_respected`), `tests/test_farm_alerts.py` (E2.1) ; OFMAI `lib/social/health.test.ts` (mêmes cas sur `FarmEvent`) et `app/api/farm/events/route.test.ts` (un `health_signal` `verification_required` déclenche un `sendDiscordAlert` de niveau `error`, un `cooldown` un `warn`, un `suspended` un `critical`). Lancement fork : `sh scripts/farm_tests.sh`.

<!-- Numérotation : il n'y a pas de §9 (section retirée le 2026-09-14). Ne pas renuméroter la section ci-dessous : « health-canaries.md §10 » est cité tel quel par INDEX.md, account-creation.md, bridge-ofmai-farm.md et build-plan.md. -->

## 10. Retirer un compte banni (runbook)

Déclencheur : `health_signal` `suspended` (alerte `critical`, §5) ou un écran de suspension vu par un humain. Neuf étapes, dans l'ordre ; rien n'est automatique.

1. **Fork** : `python -m gitd.farm.cli accounts disable <plateforme> @<handle>` puis `adb -s <serial> shell pm clear <package>` (session de l'app effacée ; le compte n'est pas supprimé côté plateforme).
2. **OFMAI** : `PATCH /api/admin/social/accounts/{id} {"status":"banned"}` — la route annule (`cancelled`) toute `SocialPublication` `queued`/`claimed` du compte ; leurs variantes restent `ready`, réutilisables sur le compte de remplacement (`bridge-ofmai-farm.md` §3.6, E7.2). Vérification : `GET /api/farm/queue?platform=<p>&handle=<h>` est vide.
3. **Reddit** : retirer le `characterId` des `SocialSubreddit` concernés (`PATCH /api/admin/social/subreddits/{id}`, E8.5).
4. **TikTok** : connecteur laissé en `error`, jamais `tiktok_reconnect` ; **Instagram** : couper l'automatisation comment-to-DM dans l'outil (`publishing.md` §8).
5. **GeeLark / IPRoyal** selon S5 : 1ᵉʳ `suspended` → rien sur le profil, 30 j sans nouvelle inscription sur cette plateforme ; 2ᵉ → tous les comptes `disable`, profil supprimé après 30 j, IP rendue (`infrastructure-geelark-proxies.md` §3).
6. **Trousseau** : `security delete-generic-password -s ofmai-social-<p>-<slug>` et `-oauth` ; dans `~/.ofmai/farm/phones.json`, ligne `banned: {"<p>": "<date>"}`.
7. Note datée dans `farm_accounts.notes` (motif, `matched`, date), pas d'identifiant.
8. **Remplacement**, 30 j plus tard : `growth-account-onboard.js` (`build-plan.md` §12) avec un nouveau handle (handles 2/3 de la fiche persona), même téléphone si S5 le permet, nouvelle ligne `SocialAccount` (`status: creating`).
9. Alerte Discord `critical` déjà partie ; une ligne dans le rapport du lendemain (`metrics-attribution.md` §6, bloc « Humain ») et, si S4 est proche (2 `suspended` en 48 h sur la plateforme), post-mortem daté dans `docs/social/decisions/` avant tout nouveau compte.
