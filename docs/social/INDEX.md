# Social — index (machine M1, armée de personnages)

> **Nature** : reference
> **Statut** : à vérifier — dossier écrit avant le build (2026-09-14) ; seuls `gitd/farm/*.py` et les skills `ofmai_instagram` / `ofmai_tiktok` du fork existent, rien côté OFMAI
> **À jour au** : 2026-09-14
> **Répond à** : quel fichier ouvrir pour construire, puis exploiter, la ferme de personnages (téléphones virtuels, chauffe, publication, pont ferme ↔ OFMAI, santé, attribution)
> **Code concerné** : fork ofmai-farm `gitd/farm/`, `gitd/skills/ofmai_*` ; OFMAI `app/api/farm/` (à créer), `app/api/admin/social/` (à créer), `lib/social/` (à créer), `prisma/schema.prisma`, `app/api/attribution/route.ts`, `.claude/workflows/growth-*.js` (à créer)

**Le code fait foi.** Chaque fragment marque `[à vérifier]` ce qui n'a pas été lu dans le code ; les chiffres de chauffe sont ceux de `gitd/farm/policy.py`.

## Ordre de lecture

- **Pour construire** : `rules.md` → `architecture.md` → `bridge-ofmai-farm.md` → `content-pipeline.md` → `warming-policy.md` → `publishing.md` → `health-canaries.md` → `build-plan.md`.
- **Pour exploiter** : `infrastructure-geelark-proxies.md` → `account-creation.md` → `personas.md` → `metrics-attribution.md`, puis `architecture.md` §9 (qui regarde quoi, quand).

## Fragments

| Fichier | Répond à | Statut |
|---|---|---|
| `rules.md` | les 35 règles absolues (personnages synthétiques, divulgation IA 3 sur 6, SFW/NSFW par host et par plateforme, comptes, texte publié, quotas et rythme, réseau, liens, humain dans la boucle, kill-switches et santé collective, médias et code), pourquoi, et ce que le code garantit ou non | en vigueur |
| `architecture.md` | composants, flux de bout en bout, processus du Mac mini, ports, secrets (noms canoniques du Trousseau), pannes et reprise, exploitation quotidienne | à vérifier |
| `infrastructure-geelark-proxies.md` | monter et maintenir un téléphone virtuel par personnage : compte, profil, proxies statique + mobile, ADB, observateur, coûts, pannes | à vérifier |
| `account-creation.md` | créer, régler et enregistrer chaque compte sur son téléphone : J0 email, skills enregistrés, checkpoints humains, SIM, Trousseau, abandon | à vérifier |
| `warming-policy.md` | plafonds, rythmes, sessions, pools, santé et `api_mode` d'un compte — miroir de `policy.py` | en vigueur (§1-§7, §9) |
| `content-pipeline.md` | banque `ContentSource` / `ContentAsset` : sélection dans le radar (seule source de contenu), réplication image et vidéo avec le personnage comme sujet (une par post source, 2 tentatives au plus, `sourcePostId` consommé une seule fois par personnage), contrôle Gemini (`reviewGeneratedMedia`, system prompt versionné, sortie JSON, `keep | retry | reject`), hash perceptuel anti-repost, re-rendu par plateforme, filigrane selon `disclosed`, légendes écrites côté OFMAI, conformité, volumes, coûts | à vérifier |
| `publishing.md` | app ou API, geste par geste et par plateforme ; TikTok par MCP, X et Reddit par API et IP statique, subs Reddit, comment-to-DM, réponses | à vérifier |
| `health-canaries.md` | signaux écran, canaris de shadowban, machine d'états, règles collectives, kill-switches, escalade Discord, retirer un compte banni | à vérifier |
| `bridge-ofmai-farm.md` | contrat d'API dans les deux sens, tables Prisma et `farm_*`, tick du daemon, reprise | à vérifier |
| `metrics-attribution.md` | UTM, vérité prod `User` × `Subscription`, PostHog, rapport Discord, seuils J4/J7/J14, comparaison des groupes `declared` / `undeclared` (lecture J14, décision J21) | à vérifier |
| `personas.md` | fiche persona (dont le flag `disclosed`), les six personnages neufs du compte admin, page publique `/c/<slug>`, Fanvue, link-in-bio, bios par plateforme, compte de marque, ajouter un personnage | à vérifier |
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
| Bascule de proxy, panne réseau, serial changé | `infrastructure-geelark-proxies.md` §4.3, §9 |

## Décisions en vigueur

Aucune pour l'instant. Le dossier `decisions/` est créé à la première décision datée (SIM, plateforme coupée, post-mortem, lecture J4/J7/J14, décision J21 du test de divulgation), au format `AAAA-MM-<sujet>.md`.
