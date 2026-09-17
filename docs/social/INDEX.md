# Social — index (machine M1, armée de personnages)

> **Nature** : reference
> **Statut** : en vigueur — vagues 1 et 2 construites le 2026-09-15. Existent : côté ferme `gitd/farm/*.py`, les skills `ofmai_{instagram,tiktok,x,reddit}` et `ofmai_signup_*`, le pont et les règles collectives (390 tests) ; côté OFMAI `lib/social/*`, `app/api/farm/*`, `app/api/admin/social/*`, les six fiches persona et le schéma de la banque (350 tests). Restent à faire : la vérification des sélecteurs sur un appareil (E4, aucun `tested_on` rempli), les pages publiques, le comment-to-DM, et les trois tâches de cibles radar E3.7 / E7.5 / E7.6.
> **À jour au** : 2026-09-15
> **Répond à** : quel fichier ouvrir pour construire, puis exploiter, la ferme de personnages (téléphones virtuels, chauffe, publication, pont ferme ↔ OFMAI, santé, attribution)
> **Code concerné** : fork ofmai-farm `gitd/farm/`, `gitd/skills/ofmai_*` ; OFMAI `app/api/farm/` (à créer), `app/api/admin/social/` (à créer), `lib/social/` (à créer), `prisma/schema.prisma`, `app/api/attribution/route.ts`, `.claude/workflows/growth-*.js` (à créer)

**Le code fait foi.** Chaque fragment marque `[à vérifier]` ce qui n'a pas été lu dans le code ; les chiffres de chauffe sont ceux de `gitd/farm/policy.py`.

## Ordre de lecture

- **Pour construire** : `rules.md` → `architecture.md` → `bridge-ofmai-farm.md` → `content-pipeline.md` → `warming-policy.md` → `publishing.md` → `health-canaries.md` → `build-plan.md`.
- **Pour exploiter** : `infrastructure-geelark-proxies.md` → `account-creation.md` → `personas.md` → `metrics-attribution.md`, puis `architecture.md` §9 (qui regarde quoi, quand).

## Fragments

| Fichier | Répond à | Statut |
|---|---|---|
| `rules.md` | les 36 règles absolues (personnages synthétiques, divulgation IA 3 sur 6, SFW/NSFW par host et par plateforme, comptes, texte publié, quotas et rythme, réseau, liens, humain dans la boucle, kill-switches et santé collective, médias et code, exploration des écrans sur le seul profil explorateur), pourquoi, et ce que le code garantit ou non | en vigueur |
| `architecture.md` | composants, flux de bout en bout, processus du Mac mini, ports, secrets (noms canoniques du Trousseau), pannes et reprise, exploitation quotidienne | à vérifier |
| `infrastructure-geelark-proxies.md` | monter et maintenir un téléphone virtuel par personnage : compte, profil, l'unique adresse statique posée une fois pour toutes, ADB, les deux profils sans personnage (observateur pour les canaris, explorateur sacrificiel pour le relevé des sélecteurs), coûts, pannes | à vérifier |
| `account-creation.md` | créer, régler et enregistrer chaque compte sur son téléphone : J0 email, skills enregistrés, checkpoints humains, SIM, Trousseau, abandon | à vérifier |
| `screens-instagram.md` | relevé écran par écran de l'inscription Instagram sur téléphone réel (720 × 1440, IG 443.0.0.48.82, proxy US) : coordonnées, portes humaines confirmées (captcha **et** SMS obligatoires), pseudo pré-rempli depuis l'e-mail, champ `appVersionId` pour installer une app, expiration silencieuse de la session ADB | **vérifié sur téléphone le 2026-09-16** |
| `screens-reddit.md` | relevé de l'inscription Reddit sur téléphone réel : **seule plateforme des quatre où un compte a pu être créé et reste utilisable** — ni numéro, ni captcha, ni biométrie ; coordonnées des 13 écrans, bascule clavier du sélecteur de date, dialogue passkey attendu sur téléphone cloud | **vérifié sur téléphone le 2026-09-16** |
| `selectors-uiautomator.md` | piloter les apps par l'arbre d'interface (`uiautomator dump`) plutôt que par des coordonnées : identifiants stables du fil Instagram, pourquoi le y dépend du défilement, les deux pièges (identifiant non unique, `clickable=false` sur like/commentaire/partage), et la boucle dump → tap → dump qui rend chaque geste **vérifiable** et donne un signal de shadowban mesurable | **vérifié sur téléphone le 2026-09-16** |
| `screens-instagram-actions.md` | les 12 actions de `policy.py` exercées sur un vrai compte : identifiant de chacune et **preuve de réussite observée** (Like→Liked, Follow→Following, unseen→seen story…), 10 vérifiées de bout en bout, plus 9 pièges qui auraient cassé le skill en silence | **vérifié sur téléphone le 2026-09-16** |
| `screens-reddit-actions.md` | actions Reddit exercées sur un vrai compte : rejoindre, upvote et commentaire vérifiés ; **Reddit est en Compose et n'expose ni identifiant ni description sur les boutons de vote** — la vérification y est visuelle, pas dans l'arbre, contrairement à Instagram ; décalages de la barre d'actions et écrans intercalaires | **vérifié sur téléphone le 2026-09-16** |
| `screens-x.md` | **X refuse l'inscription depuis un téléphone cloud** (« Please use official X apps to proceed ») — adresse et provenance de l'APK écartées, attestation d'intégrité de l'appareil probable ; sans conséquence sur le plan puisque X passe déjà par l'API, mais la création du compte devra se faire ailleurs. Deux pièges : le champ e-mail de X mélange une saisie en morceaux, et le port ADB change à chaque redémarrage | **vérifié sur téléphone le 2026-09-17** |
| `warming-policy.md` | plafonds, rythmes, sessions, pools de commentaires, cibles de suivi tirées du radar par niche, santé et `api_mode` d'un compte — miroir de `policy.py` | en vigueur (§1-§7, §9) |
| `content-pipeline.md` | banque `ContentSource` / `ContentAsset` : sélection dans le radar (seule source de contenu), réplication image et vidéo avec le personnage comme sujet (une par post source, 2 tentatives au plus, `sourcePostId` consommé une seule fois par personnage), contrôle Gemini (`reviewGeneratedMedia`, system prompt versionné, sortie JSON, `keep | retry | reject`), hash perceptuel anti-repost, re-rendu par plateforme, filigrane selon `disclosed`, légendes écrites côté OFMAI, conformité, volumes, coûts | à vérifier |
| `publishing.md` | app ou API, geste par geste et par plateforme ; TikTok par MCP, X et Reddit par API et IP statique, subs Reddit, comment-to-DM, réponses | à vérifier |
| `health-canaries.md` | signaux écran, canaris de shadowban, machine d'états, règles collectives, kill-switches, escalade Discord, retirer un compte banni | à vérifier |
| `bridge-ofmai-farm.md` | contrat d'API dans les deux sens (contenu, légendes, pools, cibles du radar, événements retour), tables Prisma et `farm_*`, tick du daemon, reprise | à vérifier |
| `metrics-attribution.md` | UTM, vérité prod `User` × `Subscription`, PostHog, rapport Discord, seuils J4/J7/J14, comparaison des groupes `declared` / `undeclared` (lecture J14, décision J21) | à vérifier |
| `personas.md` | fiche persona (dont le flag `disclosed` et la date de naissance), les six personnages neufs du compte admin, page publique `/c/<slug>`, Fanvue, link-in-bio, bios par plateforme, compte de marque, ajouter un personnage | à vérifier |
| `build-plan.md` | epics → tâches, critères d'acceptation, tests, ordre, workflows de production, ce que Nathan fournit | à vérifier |

## Exploitation : geste → où lire

| Geste | Fichier |
|---|---|
| Rapport du matin, seuils | `metrics-attribution.md` §6-§7 ; rôles et horaires dans `architecture.md` §9 |
| Checkpoint (captcha, SMS, login) | `account-creation.md` §4.2 |
| `clear-health` après avoir regardé l'écran | `health-canaries.md` §6 |
| Kill-switch plateforme ou machine | `health-canaries.md` §4 |
| Ajouter un personnage | `personas.md` §10 |
| Retirer un compte banni | `health-canaries.md` §10 |
| Passer un compte en `api_mode` | `warming-policy.md` §10 (le passage) et §13 (la checklist de fin de chauffe) |
| Sauvegarde, restauration, reprise après redémarrage | `architecture.md` §4 et §7 |
| Où sont les identifiants proxy, panne réseau, serial changé | `infrastructure-geelark-proxies.md` §4.3, §9 |
| Revérifier des sélecteurs après une mise à jour d'application | `infrastructure-geelark-proxies.md` §6.2 (profil explorateur), `rules.md` R34 et R36, `build-plan.md` E4.1 |

## Décisions en vigueur

Aucun fichier dans `decisions/` : les décisions prises avec Nathan pendant l'écriture du dossier sont intégrées **dans les fragments**, datées sur place. Les trois du 2026-09-15 :

| Décision | Où elle est écrite |
|---|---|
| Un huitième profil de téléphone, sacrificiel, pour explorer les écrans des applications — on n'explore jamais depuis le téléphone d'un personnage | `infrastructure-geelark-proxies.md` §6.2, `rules.md` R36, `build-plan.md` §4 (E4.1) et §13, `architecture.md` §2 |
| La fiche persona porte une date de naissance complète, pas seulement un âge | `personas.md` §1 et §3.2, `account-creation.md` §2 et §6, `lib/social/personas/*.yaml` côté plateforme |
| Les comptes suivis et les profils visités pendant la chauffe sont tirés du radar, par niche | `warming-policy.md` §8.2, `bridge-ofmai-farm.md` §3.7, `personas.md` §1, `build-plan.md` E3.7 / E7.5 / E7.6 |

Le dossier `decisions/` sera créé à la première décision **postérieure au build** (SIM, plateforme coupée, post-mortem, lecture J4/J7/J14, décision J21 du test de divulgation), au format `AAAA-MM-<sujet>.md`.
