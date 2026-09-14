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
| `rules.md` | les 36 règles absolues (consentement, divulgation IA, SFW/NSFW, comptes, texte, quotas, réseau, liens, humain dans la boucle, kill-switches), pourquoi, et ce que le code garantit ou non | en vigueur |
| `architecture.md` | composants, flux de bout en bout, processus du Mac mini, ports, secrets (noms canoniques du Trousseau), pannes et reprise, exploitation quotidienne | à vérifier |
| `infrastructure-geelark-proxies.md` | monter et maintenir un téléphone virtuel par personnage : compte, profil, proxies statique + mobile, ADB, observateur, coûts, pannes | à vérifier |
| `account-creation.md` | créer, régler et enregistrer chaque compte sur son téléphone : J0 email, skills enregistrés, checkpoints humains, SIM, Trousseau, abandon | à vérifier |
| `warming-policy.md` | plafonds, rythmes, sessions, pools, santé et `api_mode` d'un compte — miroir de `policy.py` | en vigueur (§1-§7, §9) |
| `content-pipeline.md` | banque `ContentAsset` : génération Soul/LoRA, QA 3 pour 1, re-rendu, filigrane, légendes, conformité, volumes, coûts | à vérifier |
| `publishing.md` | app ou API, geste par geste et par plateforme ; TikTok par MCP, X et Reddit par API et IP statique, subs Reddit, comment-to-DM, réponses | à vérifier |
| `health-canaries.md` | signaux écran, canaris de shadowban, machine d'états, règles collectives, kill-switches, escalade Discord, retirer un compte banni | à vérifier |
| `bridge-ofmai-farm.md` | contrat d'API dans les deux sens, tables Prisma et `farm_*`, tick du daemon, reprise | à vérifier |
| `metrics-attribution.md` | UTM, vérité prod `User` × `Subscription`, PostHog, rapport Discord, seuils J4/J7/J14 | à vérifier |
| `personas.md` | fiche persona, les six personnages, Fanvue, link-in-bio, bios, compte de marque, ajouter un personnage | à vérifier |
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
| Passer un compte en `api_mode` | `warming-policy.md` §13 |
| Sauvegarde, restauration, reprise après redémarrage | `architecture.md` §4 et §7 |
| Bascule de proxy, panne réseau, serial changé | `infrastructure-geelark-proxies.md` §4.3, §9 |

## Décisions en vigueur

Aucune pour l'instant. Le dossier `decisions/` est créé à la première décision datée (SIM, plateforme coupée, post-mortem, lecture J4/J7/J14), au format `AAAA-MM-<sujet>.md`.
