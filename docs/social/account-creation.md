# Création des comptes — procédure par plateforme, checkpoints humains, ledger

> **Nature** : reference
> **Statut** : à vérifier — procédure écrite avant le build : aucun skill de création de compte n'existe dans le fork (`gitd/skills/ofmai_signup_*` à créer), le ledger n'accepte que `instagram` et `tiktok`, les libellés d'écran des quatre apps ne sont pas minés
> **À jour au** : 2026-09-15
> **Répond à** : comment on crée, règle et enregistre chaque compte d'un personnage sur son téléphone, ce que fait le skill Ghost et où un humain intervient, avec quel numéro, où vont les identifiants, et quand on abandonne un compte
> **Code concerné** : fork `gitd/farm/cli.py`, `gitd/farm/ledger.py`, `gitd/farm/policy.py`, `gitd/farm/health.py`, `gitd/farm/warm.py`, `gitd/skills/checkpoint.py`, `gitd/skills/base.py` (`RecordedStepAction`, `RecordedWorkflow`), `gitd/skills/_run_skill.py`, `gitd/services/skill_creation.py`, `gitd/services/device_context.py`, `gitd/routers/skills.py`, `gitd/routers/phone.py`, `gitd/models/skill_compat.py`, `gitd/skills/play_store/`, `gitd/skills/ofmai_instagram/skill.yaml`, `gitd/skills/ofmai_tiktok/skill.yaml` ; OFMAI `prisma/schema.prisma` (`SocialAccount`, à créer — `bridge-ofmai-farm.md`)

Le téléphone, le proxy et le fuseau sont préparés selon `infrastructure-geelark-proxies.md` ; le handle, le nom, la bio et la photo viennent de la fiche `personas.md` ; ce que le compte fait ensuite est dans `warming-policy.md` ; les règles citées (R1-R2, R7, R9-R13, R15-R16, R18-R20, R22, R25-R27, R32, R34) sont dans `rules.md`. Ce fichier ne couvre que le jour 0 (email) et le jour de création de chaque compte, jusqu'à sa première session de chauffe.

## 1. Principes

- **Créé sur le téléphone du personnage, jamais acheté** (R7). Le jour de création est le jour 1 de `phase_for_day()` (`gitd/farm/policy.py`) : `farm_accounts.created_on` doit être la date locale réelle de l'inscription.
- **Un compte par plateforme par téléphone** : `ledger.add_account()` lève `ValueError("device … already carries … account (one per device)")` (`gitd/farm/ledger.py`).
- **Une seule adresse, du jour 0 à la dernière inscription** : le compte Google de J0, les 24 h de vie qui suivent, puis chaque inscription de J1 à J7, ses codes et ses premiers réglages passent tous par l'unique IP statique résidentielle du personnage. Aucune bascule de proxy, à aucun moment : une IP qui change est le motif « suspicious login » (R18). Détail de l'adresse et du profil : `infrastructure-geelark-proxies.md` §4 et §7, contrôles avant mise en service §10.
- **Tout ce qui est tapé l'est sur ce téléphone**, par le skill ou par un humain à travers Ghost. Jamais de connexion au compte depuis un navigateur du Mac mini ou de Thaïlande : l'IP de Paris ou de Bangkok un jour de création est le motif « suspicious login ».
- **Un humain à chaque porte** : captcha, SMS, code email, mot de passe. Le skill s'arrête, l'humain agit, le skill reprend (§4). Jamais de numéro virtuel (R25).
- **Aucun nom de fournisseur** dans un nom, une bio ou une réponse (R10) ; **la bio est celle de la fiche persona pour cette plateforme** (`personas.md` §6), posée avant le premier post : mention « AI » si `disclosed: true`, aucune mention si `disclosed: false` ; « 18+ » sur X et Reddit dans les deux cas (R2). Le label AIGC, lui, se pose post par post (§6.2, `publishing.md` §1.1), jamais comme réglage de compte.

## 2. Avant de créer quoi que ce soit

- Profil GeeLark du personnage prêt (IP statique posée et vérifiée, `netType` = 0 / Wi-Fi, GPS/fuseau/langue/région alignés, `adb devices` voit le serial) — `infrastructure-geelark-proxies.md`.
- Fiche persona validée : `handle` (+ 2 handles de repli), nom affiché, **date de naissance complète** (`identity.birthday` de la fiche, format `AAAA-MM-JJ`, ≥ 18 ans — `personas.md` §1 : les quatre plateformes demandent une date, pas un âge, et il faudra la retrouver des mois plus tard pour une vérification ou une récupération de compte), bio par plateforme passée par la porte de conformité (`content-pipeline.md` §8), photo de profil = une variante SFW filigranée de la banque (`content-pipeline.md` §6 : filigrane `@<handle> · AI` si `disclosed: true`, `@<handle>` seul sinon), poussée dans la galerie **par l'humain juste avant le run** (le pont n'existe pas au jour 1 et ne pousse que des `SocialPublication`) : `adb -s <serial> push <variante.jpg> /sdcard/DCIM/Camera/ && adb -s <serial> shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file:///sdcard/DCIM/Camera/<fichier>` (même commande que `bridge-ofmai-farm.md` §6, étape 2).
- Mot de passe généré et rangé **avant** d'être tapé (§8) ; SIM du personnage identifiée (§5).
- Skill de création avec `tested_on` non vide (R34) : un skill enregistré rejoué sur un vrai compte avec des libellés faux tape à côté.
- Un humain disponible pendant toute la fenêtre : la création se lance dans la première fenêtre de session de la politique, **08:00-12:00 heure du compte** (`_WINDOWS[0]` de `policy.py`), soit 19:00-23:00 à Bangkok et 14:00-18:00 à Paris pour un compte `America/New_York` ; pour Sierra (`America/Los_Angeles`, fiche persona), 22:00-02:00 à Bangkok et 17:00-21:00 à Paris. Jamais entre 01:00 et 06:59 locales (R15).

## 3. Ordre de création par téléphone

Un seul compte par jour par téléphone, un jour sur deux : une identité neuve qui ouvre quatre inscriptions le même après-midi est une ferme, pas une personne. Entre deux créations, le téléphone vit (sessions de chauffe du compte précédent, `warming-policy.md`).

| Jour | Geste | Qui | Durée |
|---|---|---|---|
| J0 | mise en route du profil, compte Gmail, installation des quatre apps | humain (dashboard Ghost, §6.0) | 20-30 min |
| J1 | Instagram | skill `ofmai_signup_instagram` + checkpoints | 10-15 min |
| J3 | TikTok | skill `ofmai_signup_tiktok` + checkpoints | 10-15 min |
| J5 | X | skill `ofmai_signup_x` + checkpoints — **seulement une fois le ledger étendu** (§7) | 10-15 min |
| J7 | Reddit | skill `ofmai_signup_reddit` + checkpoints — idem | 10 min |

Six téléphones : décaler les J0 de deux jours entre personnages pour qu'un humain n'ait jamais plus de deux créations (donc deux à quatre checkpoints) le même jour. Un compte X ou Reddit ne se crée pas tant que `cli.py` refuse la plateforme : un compte hors ledger n'a ni budget ni santé (R13), et le laisser dormir des semaines sans activité est pire que le créer plus tard.

## 4. Le mécanisme commun : skill enregistré + checkpoint

### 4.1 Le skill

Chaque création est un **skill enregistré** (`kind: hard`, `workflows/recorded.json`), parce que le checkpoint humain n'existe que comme step de `RecordedStepAction` (`gitd/skills/base.py`), pas dans les classes `Action` codées du farm. Création du squelette depuis le Mac mini, sur le modèle de `gitd/skills/send_gmail_email/` :

```python
from gitd.services.skill_creation import create_recorded_skill
create_recorded_skill(name="ofmai_signup_instagram", app_package="com.instagram.android",
                      steps=open("steps.json").read(), description="Instagram signup by email, human gates")
```

Steps acceptés (`RecordedStepAction.execute`) : `launch`, `tap` (locator `text` / `resource_id` / `content_desc`, repli `x`,`y`), `type`, `key`, `back`, `home`, `swipe`, `long_press`, `open_url`, `launch_intent`, `checkpoint`, `wait`. Les `{placeholder}` sont substitués dans `text`, `package`, `description`, `goal` et `prompt` (`RecordedWorkflow.steps()`). Un `type` ASCII passe par `adb shell input text`, le non-ASCII par `type_unicode` ; les bios restent ASCII (R12). Les `popup_detectors` de `gitd/skills/ofmai_instagram/skill.yaml` (7) et `gitd/skills/ofmai_tiktok/skill.yaml` (8) sont recopiés dans le `skill.yaml` du skill de création correspondant.

**Le mot de passe n'est jamais un paramètre** : `_run_skill.py` `_record_start()` écrit `params_json=json.dumps(params)` dans `skill_runs` (SQLite non chiffrée, REST sans authentification, R9). Il est tapé par l'humain à un checkpoint `login` (§4.2). Paramètres autorisés : `email`, `handle`, `name`, `birthday`, `bio` (`bio_line1` … `bio_line3` sur Instagram, ci-dessous) — du texte public, aucun secret ; `RecordedWorkflow.steps()` substitue n'importe quelle clé de `params`, il n'y a pas de liste blanche dans le code.

**`birthday` est un paramètre, jamais une invention du skill** : sa valeur est `identity.birthday` de la fiche persona (`personas.md` §1), au format `AAAA-MM-JJ`, recopiée telle quelle — **la même date sur le compte Google et sur les quatre plateformes**. Une date qui diffère d'une plateforme à l'autre est une incohérence de plus dans le dossier du personnage, et c'est elle qu'une vérification ou une récupération de compte demandera des mois plus tard. Le skill la tape sur le sélecteur de date (`type` puis `key`, ou trois sélecteurs jour / mois / année selon l'écran [à vérifier sur chaque app]) ; il ne calcule jamais une date à partir de `age`.

**La bio est un paramètre, jamais une décision du skill** : sa valeur est `accounts.<plateforme>.bio` de la fiche persona (`personas.md` §6), déjà écrite selon `disclosed` — avec « AI » pour un personnage déclaré, sans aucune mention IA pour un non déclaré, « 18+ » sur X et Reddit dans les deux cas. Celui qui lance le run recopie la bio de la fiche ; le skill ne compose rien et ne relit pas la fiche au moment de taper. Une bio multi-ligne (Instagram : trois lignes) ne passe pas en un seul `type` — `input_text_arg` (`gitd/bots/common/adb.py`) shell-quote l'argument entier, donc un `\n` arrive littéralement à `adb shell input text` sans créer de retour à la ligne : un paramètre et un `type` par ligne, un `key` ENTER entre deux [à vérifier sur l'app].

Lancement : **directement par le runner, en sous-processus détaché** (à la main : en SSH dans un `tmux` ; par `growth-account-onboard.js` : `nohup … > ~/Library/Logs/ofmai-farm/signup-<slug>-<platform>.log &`, puis suivi par `GET /api/skills/runs?device=<serial>&skill=ofmai_signup_<platform>&limit=1` toutes les 30 s), comme `cmd_run` de `gitd/farm/cli.py` le fait — **jamais** par `POST /api/skills/{name}/run` : vérifié, `gitd/routers/skills.py` l. 405-437 appelle `enqueue_job` sans `max_duration_s`, et `gitd/services/scheduler_service.py` l. 298 applique `or 3600` — le job serait tué après une heure, alors qu'un checkpoint SMS peut attendre plus :

```bash
cd ~/ofmai-farm && PYTHONPATH=. python -u gitd/skills/_run_skill.py \
  --skill ofmai_signup_instagram --workflow recorded --device R58N1234 \
  --params '{"email":"sierra.cole.ai@gmail.com","handle":"sierra.cole","name":"Sierra Cole","birthday":"2001-08-26",
             "bio_line1":"sierra, 25, la","bio_line2":"AI character, made on ofmai","bio_line3":"6am club"}'
# les trois lignes sont la bio Instagram de sierra.yaml : elle est declaree, d'ou le « AI character ».
# Une fiche disclosed: false passe sa propre bio, sans aucune mention IA (personas.md §6).
```

Le runner crée la ligne `skill_runs` (`run_id`), sans laquelle un checkpoint sans condition `success` est **sauté** (`_run_checkpoint` : « no run_id and no success condition — skipping gate »). Une session de chauffe ne doit pas tourner sur le même téléphone pendant ce temps : le compte n'est pas encore dans le ledger, le planner ne le connaît pas, donc rien ne se chevauche.

### 4.2 Le checkpoint

Format du step (`gitd/skills/checkpoint.py` : `VALID_REASONS = {"captcha", "sms", "email", "login", "generic"}`, `DEFAULT_TIMEOUT_S = 600`, `0` = attente infinie ; `success` = `screen_has` ou `url_contains`, poll toutes les 2 s) :

```json
{"action": "checkpoint", "reason": "email",
 "prompt": "Type the 6-digit code sent to {email} on the device (GET /api/phone/notifications), then resume",
 "success": {"screen_has": "Create a password"}, "timeout_s": 0}
```

Ce qui se passe : le run passe en `awaiting_human` (`skill_runs.status`), la ligne `[checkpoint] ⏸ AWAITING HUMAN — email: … (run 42)` sort dans le terminal, le dashboard Ghost affiche la bannière Resume / Abort avec le flux live. Le run reprend au premier des deux : la condition `success` vue à l'écran (l'humain a tapé le code, l'app a avancé) ou l'appel manuel :

```bash
# trouver le run
curl -s "http://127.0.0.1:5055/api/skills/runs?device=R58N1234&skill=ofmai_signup_instagram&limit=3"
# taper sur le téléphone (ASCII ; équivalent : adb -s R58N1234 shell input text 482913)
curl -s -X POST http://127.0.0.1:5055/api/phone/type -H 'content-type: application/json' -d '{"device":"R58N1234","text":"482913"}'
# reprendre, ou abandonner ; 409 si le run n'est pas awaiting_human, 400 si action invalide, 404 run inconnu
curl -s -X POST http://127.0.0.1:5055/api/skills/runs/42/resume -H 'content-type: application/json' -d '{"action":"resume"}'
curl -s -X POST http://127.0.0.1:5055/api/skills/runs/42/resume -H 'content-type: application/json' -d '{"action":"abort"}'
```

Le port 5055 n'a aucune authentification : ces appels passent par un tunnel SSH vers le Mac mini (`ssh -L 5055:127.0.0.1:5055 <mac-mini>`, hôte dans `infrastructure-geelark-proxies.md`). `timeout_s: 0` sur toutes les portes de création : un `timed_out` (600 s) laisse une inscription à moitié faite ; la fenêtre du §2 garantit un humain présent. Un `abort` termine le run en `aborted` ; l'écran reste où il est, l'humain finit ou nettoie à la main (§9).

Reasons par porte : `email` (code reçu sur Gmail), `login` (mot de passe tapé par l'humain, jamais transmis), `sms` (code reçu sur la SIM, §5), `captcha` (puzzle ou curseur), `generic` (tout écran imprévu). Aujourd'hui rien n'alerte Discord quand un run passe en `awaiting_human` (R32, `build-plan.md`) : pendant la création, l'humain regarde le terminal.

### 4.3 Lire un code email sans quitter l'app

`GET /api/phone/notifications/R58N1234` (`get_notifications` dans `gitd/services/device_context.py` : `dumpsys notification --noredact`, renvoie `[{package, title, text}]`) lit le code dans la notification Gmail sans mettre l'app d'inscription en arrière-plan. Conditions : notifications Gmail activées sur le profil et aperçu du contenu autorisé [à vérifier sur GeeLark]. Ne pas utiliser `gmail_utils.check_gmail_inbox_most_recent()` (`gitd/skills/gmail_utils.py`) pendant un run : `_launch_gmail` fait `am force-stop` puis relance Gmail au premier plan, l'app d'inscription perd l'écran. Reddit envoie un **lien** de vérification, pas un code : l'humain ouvre la notification, tape le lien, revient à l'app par les récents, puis `resume`.

## 5. Pool de numéros réels

Décision de départ (brief M1 §4) : jamais de numéro virtuel ; des SIM réelles, à définir avec Nathan. Règles fixées ici, le reste est [à définir avec Nathan] :

- **Une SIM prépayée par personnage**, six au total ; une SIM ne sert qu'aux comptes de son personnage (Google + 4 plateformes). Jamais la SIM d'un autre personnage en dépannage : deux comptes vérifiés par le même numéro sont liés.
- Support : un téléphone physique à Paris (l'assistant lit le SMS et le tape via `POST /api/phone/type`) **ou** les six SIM en roaming avec Nathan en Thaïlande (réception SMS d'une prépayée française en roaming [à vérifier par opérateur]). Le relais du code (message Discord privé, canal dédié) est acceptable : la SIM est réelle, seul l'acheminement du code est automatisé.
- Indicatif : celui du marché du personnage (+1) de préférence ; un +33 sur un compte `America/New_York` est un signal faible mais réel [à vérifier sur les deux premiers comptes pilotes].
- Le numéro, le PIN et le PUK vivent dans le Trousseau (§8), jamais dans `farm_accounts.notes` ni dans un prompt.
- Le numéro n'est donné **que si la plateforme l'exige** (bouton « Skip » d'abord) ; l'inscription se fait par email partout.

Procédure à un checkpoint `sms` : (1) le terminal affiche `AWAITING HUMAN — sms` ; (2) l'humain lit le SMS sur la SIM du personnage ; (3) il tape le code par `POST /api/phone/type` ou dans le dashboard ; (4) le run reprend sur `success.screen_has` ou par `resume` ; (5) il note `sms: sim-<personnage> <date> <plateforme>` dans `farm_accounts.notes` (pas le numéro). Un code arrivé après expiration : « Resend » sur l'écran, jamais de nouvelle SIM.

## 6. Procédure par plateforme

Libellés d'écran donnés en en-US ; **aucun n'est vérifié** (`tested_on: []` partout) : Skill Miner sur chaque app avant d'écrire le `recorded.json` (`docs/FARM.md`, « Selectors are not verified yet »).

### 6.0 J0 — le téléphone et l'email

Fait à la main par un humain dans le dashboard Ghost (onglet Phone Agent, flux live) : six fois en tout, un skill ne vaut pas l'investissement.

1. Sur l'**unique** IP statique du personnage, comme tout le reste (`infrastructure-geelark-proxies.md` §4.1 et §7). Réglages → Comptes → Ajouter un compte → Google → Créer un compte → Pour moi. Nom et `identity.birthday` de la fiche persona, la date qui servira ensuite aux quatre inscriptions (`personas.md` §1) ; adresse `<handle>.ai@gmail.com` pour un personnage déclaré (ex. `sierra.cole.ai@gmail.com`), `<handle>@gmail.com` pour un non déclaré (`personas.md` §3.3 : jamais `ai` dans l'identifiant d'un non déclaré) — l'handle exact si Google le laisse ; mot de passe lu dans le Trousseau (§8) et tapé par `POST /api/phone/type`. Google demande en général un numéro sur un appareil neuf [à vérifier] : SIM du personnage (§5). Un contrôle d'identité ou un second refus du numéro → §9.
2. Gmail : ouvrir une fois, accepter les notifications. Vérifier que `GET /api/phone/notifications/<serial>` renvoie la notification du mail de bienvenue Google : c'est le canal des codes du §4.3.
3. Installer les quatre apps par le skill `play_store` (`InstallApp`, param `package`, intent `market://details?id=<package>`, `gitd/skills/play_store/actions/core.py`) : `com.instagram.android`, `com.zhiliaoapp.musically`, `com.twitter.android`, `com.reddit.frontpage`. Aucune n'est ouverte avant son jour.
4. Le téléphone reste allumé 24 h sur son IP statique sans autre action ; à J1 on enchaîne sur la même adresse, sans rien toucher au réseau.

### 6.1 J1 — Instagram (`com.instagram.android`)

Skill `ofmai_signup_instagram`, paramètres `email`, `handle`, `name`, `birthday`, `bio_line1`, `bio_line2`, `bio_line3`. Étapes du `recorded.json` : `launch` → tap « Create new account » → tap « Sign up with email » → `type {email}` → checkpoint `email` (success `screen_has: "Create a password"` [à vérifier]) → checkpoint `login` (mot de passe) → date de naissance `{birthday}` (sélecteur jour / mois / année [à vérifier sur l'app]) → `type {name}` → username `{handle}` (repli : handles 2 et 3 de la fiche si « This username isn't available ») → « I agree » → « Add your phone number » : tap « Skip » s'il existe, sinon checkpoint `sms` → contacts / Facebook / suggestions : « Not now », « Skip » (les détecteurs de popups du skill de chauffe couvrent « Turn on Notifications », « Save Your Login Info », « Allow Instagram to access ») → profil : photo depuis la galerie (l'élément le plus récent, comme `PostReelAction`), nom, bio en trois `type` séparés par un `key` ENTER (`{bio_line1}` … `{bio_line3}`, bio Instagram de la fiche, ASCII, sans lien : avec « AI » pour une déclarée — `sierra, 25, la` / `AI character, made on ofmai` / `6am club` —, sans aucune mention IA pour une non déclarée) → compte public (défaut) → `home`.

Checkpoints attendus : `email` toujours ; `captcha` parfois ; `sms` si le « Skip » n'existe pas. Un écran « Confirm it's you » avec **selfie vidéo** ou pièce d'identité → §9, sans discussion.

Après le skill : §7 (`accounts add instagram`). Pas de lien en bio avant le premier post (R22), c'est-à-dire le jour 8 (`NETWORK`) au plus tôt ; le link-in-bio est posé ce jour-là selon `publishing.md`. Le premier onglet Reels s'ouvre dans la première session de chauffe (`InstagramAdapter.open_feed`), pas à la création.

### 6.2 J3 — TikTok (`com.zhiliaoapp.musically`)

Skill `ofmai_signup_tiktok`. Étapes : `launch` → « Sign up » → « Use phone or email » → onglet « Email » → date de naissance `{birthday}` d'abord (TikTok la demande avant tout le reste) → `type {email}` → « Send code » → checkpoint `email` → checkpoint `login` → username `{handle}` → « Choose your interests » : « Skip » (détecteur existant) → curseur « drag the slider » ou « select 2 objects » (ce sont les motifs `verification` de `gitd/farm/health.py`, ici c'est une porte normale) → checkpoint `captcha` → « Add a bio » : « Not now » (détecteur) → profil : photo, nom, `type {bio}` (bio TikTok de la fiche, ASCII : `sierra | 25 | la | AI character made on ofmai` pour une déclarée, sans mention IA pour une non déclarée) → Privacy : compte public, « Suggest your account to others » désactivé [à vérifier].

Pas de lien en bio : TikTok le conditionne (compte Business ou seuil d'abonnés [à vérifier]) et R22 l'interdit avant cruise (jour 24 sur TikTok, `PHASE_EXTRA_DAYS["tiktok"] = 3`). Le label AIGC se pose **à chaque post pour un personnage déclaré, jamais pour un non déclaré** (`params.aigc_label` recopié de l'item de file, `publishing.md` §1.1) : il n'existe pas de réglage de compte, rien à activer à la création. Après le skill : §7 (`accounts add tiktok`) ; phase consume jours 1-6.

### 6.3 J5 — X (`com.twitter.android`)

Skill `ofmai_signup_x` — **après** le lot « ledger multi-plateforme » de `build-plan.md`. Étapes : `launch` → « Create account » → `type {name}` → « Use email instead » → `type {email}` → date de naissance `{birthday}` (≥ 18 ans, sinon aucun réglage 18+ n'est proposé) → « Next » → checkpoint `email` → checkpoint `login` → photo : « Skip for now » → username `{handle}` → notifications : « Skip » → intérêts : niche du personnage puis « Next » → « Authenticate your account » (puzzle) → checkpoint `captcha` → suggestions de comptes : « Skip » si possible [à vérifier : X impose parfois 1 follow].

Réglages 18+ : Settings and privacy → Privacy and safety → Content you see → « Display media that may contain sensitive content » ON ; → Your posts → « Mark media you post as having material that may be sensitive » ON [à vérifier libellés]. Profil : photo, nom, bio X de la fiche — « AI character (virtual) » **seulement si `disclosed: true`** (`sierra. 25. la. AI character (virtual), made on OFMAI. 18+ only. links below`), aucune mention IA sinon, « 18+ » dans les deux cas —, sans lien avant le premier post ; à partir du premier post, lien Fanvue avec les UTM de `metrics-attribution.md` (`utm_source=x`). Pas de 2FA activée par nous : la session vit sur un seul téléphone qui ne se déconnecte pas, et une reconnexion est déjà un geste humain (`LOGGED_OUT`, R26) ; si X l'impose, 2FA par email, checkpoint `email`. Aucun follow à la création (R16).

### 6.4 J7 — Reddit (`com.reddit.frontpage`)

Skill `ofmai_signup_reddit` — même prérequis que X. Étapes : `launch` → « Sign up » → `type {email}` → « Continue » → username `{handle}` (Reddit propose un nom aléatoire : l'effacer) → checkpoint `login` → captcha → checkpoint `captcha` → onboarding : genre « Skip », intérêts = 3-5 sujets de la niche (c'est de la consommation, pas un follow) → mail « Verify your email » : checkpoint `email` (lien, §4.3).

Réglages : Settings → Account settings → « Show mature content (I'm over 18) » ON ; Profile → Edit → « NSFW: this profile contains adult content » ON ; « Allow people to follow you » ON ; avatar, display name, bio Reddit de la fiche — mention IA **seulement si `disclosed: true`** (`AI-generated character (virtual), 18+. Everything is on my profile.`), aucune mention sinon, « 18+ » dans les deux cas [à vérifier libellés]. Aucun lien de profil ni social link avant le go/no-go (compte ≥ 31 j, karma ≥ 100, `publishing.md` §5) ; zéro lien dans un post, à tout âge (R22). Le tri des subs et le routage des liens sont dans `publishing.md`.

**J15 ou plus — app Reddit `script` du personnage (humain, 10 min, proxy statique)** : dans Chrome du téléphone, compte du personnage connecté, `reddit.com/prefs/apps` → « create another app » → type `script`, nom neutre, redirect `http://localhost` → `client_id:client_secret` dans le Trousseau `ofmai-social-reddit-<slug>-oauth` (§8), jamais dans un fichier du repo [à vérifier : une app `script` ne sert que ses développeurs, d'où une app par personnage — `publishing.md` §5].

### 6.5 J15 — Instagram professionnel et comment-to-DM (humain, 20 min)

Dans l'app : Réglages → Type de compte et outils → Passer en compte professionnel → **Creator**, catégorie « Digital creator » ; aucune page Facebook sauf si l'outil de comment-to-DM l'exige [à vérifier dans l'outil] — dans ce cas, compte Facebook créé sur le téléphone avec l'email du personnage (checkpoint `sms` possible). Puis, depuis Chrome du téléphone (même IP), connexion de l'outil avec le login Instagram (mot de passe lu dans le Trousseau, tapé par `POST /api/phone/type`), activation de l'automatisation de `publishing.md` §8 avec `dm_text` / `dm_offer` de la fiche persona. Note `dm: <date>` dans `farm_accounts.notes`. Jamais avant le jour 15 (R22) ; dépendance d'E9 (`build-plan.md`).

**Pour un personnage `disclosed: false`** : le passage en compte Creator se fait de la même façon, mais **aucun automate n'est branché** — la fiche n'a ni `dm_text` ni `dm_offer` et les mots-clés `real` / `ai` / `how` / `tool` ne déclenchent rien (`personas.md` §3.3).

## 7. Enregistrement dans le ledger

Sur le Mac mini, le jour même de la création, une fois le skill terminé. Chiffres du code : `--tz` par défaut `America/New_York`, `--created-on` par défaut = aujourd'hui **dans le fuseau donné** (`add_account` : `datetime.now(ZoneInfo(timezone)).date()`), donc obligatoire dès qu'on enregistre le lendemain ; `--character` = `AICharacter.id` ; `--niche` = hashtags de détour de la fiche (CSV) ; `--device` = le serial tel que `adb devices` l'affiche (sur GeeLark, un `host:port` [à vérifier]).

```bash
cd ~/ofmai-farm && PYTHONPATH=. python -m gitd.farm.cli accounts add instagram @sierra.cole \
  --device R58N1234 --tz America/Los_Angeles --niche "gymgirl,fitnessmotivation,losangeles,morningroutine" \
  --created-on 2026-09-21 --character cmf0sierra0000000000000
# → registered instagram @sierra.cole on R58N1234 (day 1 = 2026-09-21, tz America/Los_Angeles)
PYTHONPATH=. python -m gitd.farm.cli accounts list      # day 1 consume health=ok
PYTHONPATH=. python -m gitd.farm.cli plan instagram @sierra.cole
```

Refus possibles (`ValueError`) : plateforme hors `("instagram", "tiktok")` (X et Reddit : lot `build-plan.md` — `cli.py` choices, `ledger.add_account`, `PHASE_EXTRA_DAYS`, `health._PATTERNS`, `planner.SKILL_BY_PLATFORM`), handle déjà enregistré, appareil portant déjà un compte de cette plateforme, fuseau inconnu (`ZoneInfo`). Le handle est stocké sans `@` et comparé en minuscules.

Côté OFMAI, la même création crée la ligne `SocialAccount` (`status: creating` → `warming` après `accounts add`, `deviceSerial`, `farmAccountId`) décrite dans `bridge-ofmai-farm.md` §5.1 ; tant que la table n'existe pas, rien n'est saisi côté OFMAI.

### Les premières 24 h : rien d'autre que consume

Dès `accounts add`, le planner (`python -m gitd.farm.cli daemon`) planifie seul les sessions du jour 1 ; **personne ne touche plus l'app** (ni like, ni recherche, ni réglage) en dehors d'un checkpoint. Ce que la phase `CONSUME` autorise (`CAPS[Phase.CONSUME]`, `gitd/farm/policy.py`) : likes 0, saves 0, follows 0, comments 0, posts 0/semaine, story_views 20, profile_visits 4, searches 2, 15-40 min par jour en 2-3 sessions ; chaque cap est tiré entre 40 % et 100 % par (compte, jour) ; propension à visiter un profil 0.02 par vidéo (`PROPENSITY[Phase.CONSUME]`, `gitd/farm/warm.py`) ; pas de jour de repos avant le jour 4 (`dol > 3`) ; jamais 01:00-06:59. Durée de la phase : jours 1-3 sur Instagram, 1-6 sur TikTok. Un signal santé pendant ces sessions arrête tout (R27) ; un `suspended` dans les 72 h → §9.

## 8. Stockage des identifiants

Où : le **Trousseau macOS du Mac mini** (login keychain, chiffré par le système, déverrouillé à l'ouverture de session — d'où l'ouverture de session automatique de l'utilisateur opérateur, `architecture.md` §4 ; FileVault : décision datée, vague 0), même mécanisme que `ofmai-discord-webhook` (`.claude/loop/notify.mjs`), `ofmai-prod-db-readonly` (`.claude/skills/prod/prod.sh`) et `ofmai-farm-secret` (`bridge-ofmai-farm.md`). Noms canoniques dans `architecture.md` §6 : une entrée par secret, par **slug** de personnage (pas par handle, qui peut changer), `ofmai-social-<plateforme>-<slug>` :

```bash
# mot de passe d'un compte : généré, rangé, puis seulement lu au checkpoint login
security add-generic-password -s ofmai-social-instagram-sierra -a sierra.cole.ai@gmail.com -w "$(openssl rand -base64 18)" -U
security add-generic-password -s ofmai-social-gmail-sierra -a sierra.cole.ai@gmail.com -w "$(openssl rand -base64 18)" -U
security add-generic-password -s ofmai-social-sim-sierra -a "+1XXXXXXXXXX" -w "PIN=1234;PUK=…" -U
security find-generic-password -s ofmai-social-instagram-sierra -w         # lecture, à taper via POST /api/phone/type
```

Second exemplaire : le gestionnaire de mots de passe de Nathan, copié à la main après chaque création [à définir : lequel]. Interdits (R9) : le repo, `farm_accounts.notes`, `config_json` d'un job, `params_json` d'un `skill_runs` (d'où le mot de passe par checkpoint, §4.1), Discord, un prompt d'agent. Si un mot de passe a malgré tout transité par un paramètre : le changer sur le téléphone le jour même et supprimer la ligne `skill_runs` concernée. Les codes de secours (2FA imposée par une plateforme) vont dans `ofmai-social-<plateforme>-<slug>-recovery` ; les jetons d'API dans `ofmai-social-x-<slug>-oauth` (refresh token) et `ofmai-social-reddit-<slug>-oauth` (`client_id:client_secret`, §6.4).

## 9. Ce qui fait abandonner un compte

Abandonner = ne pas l'enregistrer (ou `accounts disable` s'il l'est), `adb -s <serial> shell pm clear <package>` pour effacer la session de l'app, une ligne datée dans `farm_accounts.notes` ou dans le journal de création, et **48 h sans nouvelle inscription sur ce téléphone**. On ne supprime pas le compte côté plateforme.

| Signal | Décision |
|---|---|
| Demande de **selfie vidéo** ou de **pièce d'identité** (« Confirm it's you », « verify your identity ») | abandon immédiat : un personnage synthétique n'a pas d'identité à montrer, et tenter serait une fraude (R1, R11) |
| Numéro refusé (« can't be used », « already in use ») ou second numéro exigé | abandon ; la SIM reste celle du personnage, on n'en essaie jamais une autre |
| `suspended` (motifs `_PATTERNS[platform]["suspended"]` de `gitd/farm/health.py`), à la création comme plus tard | règle unique (R18, `health-canaries.md` S5 et §10, `infrastructure-geelark-proxies.md` §3) : **1ᵉʳ `suspended` sur ce téléphone** → la plateforme est abandonnée sur ce téléphone (`accounts disable`, `pm clear`, `SocialAccount.status = banned`, 30 j sans nouvelle inscription sur cette plateforme), les autres comptes du personnage continuent avec un canari quotidien pendant 7 j ; **2ᵉ `suspended` sur le même téléphone dans les 30 j, toute plateforme** → téléphone et IP en quarantaine `QUARANTINE_DAYS = 30`, tous les comptes `disable`, profil supprimé, IP rendue ; le personnage repart sur un nouveau profil |
| Inscription refusée deux fois le même jour (« We couldn't create your account », « Something went wrong ») | on arrête pour la journée ; nouvel essai à J+1, sur la même adresse ; troisième échec → plateforme abandonnée sur ce téléphone 30 jours |
| Captcha échoué 3 fois de suite, ou checkpoint `abort` par l'humain | on arrête pour la journée ; un seul nouvel essai, à J+1 |
| `logged_out` à la première session de chauffe (motifs `logged_out` de `health.py`) | un humain reconnecte une fois via un checkpoint `login` ; si la plateforme exige alors un numéro ou une identité → abandon |
| Google refuse la création du compte email deux fois (numéro, identité) | abandon de l'adresse ; nouvelle adresse à J+1 ; pas d'inscription sociale tant qu'il n'y a pas d'email |
| Handle indisponible | pas un abandon : handles 2 et 3 de la fiche, puis la fiche persona est mise à jour |

Le 429 isolé de l'incident @potter_society (R16) n'a pas d'équivalent à la création : ici, le premier « try again later » ferme la journée, pas la troisième occurrence.

## 10. Ce qui n'existe pas encore (`build-plan.md`)

- Les quatre skills `gitd/skills/ofmai_signup_{instagram,tiktok,x,reddit}/` et leurs `recorded.json` après Skill Miner ; `tested_on` renseigné.
- `x` et `reddit` dans `gitd/farm/cli.py`, `ledger.add_account`, `PHASE_EXTRA_DAYS`, `health._PATTERNS`, `planner.SKILL_BY_PLATFORM` ; les skills de chauffe correspondants.
- Alerte Discord au passage d'un run en `awaiting_human` (R32) ; aujourd'hui seule la ligne `AWAITING HUMAN` du terminal et la bannière du dashboard le signalent.
- La table `SocialAccount` et `GET /api/farm/accounts` (`bridge-ofmai-farm.md`) pour que la création apparaisse côté OFMAI.
- La décision SIM (Paris ou roaming, indicatif) avec Nathan, à dater dans `docs/social/decisions/`.
