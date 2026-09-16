# Écrans Instagram — relevé sur téléphone réel

> **Statut** : vérifié à la main le 2026-09-16 sur le profil GeeLark `explorer-us`
> **Répond à** : à quoi ressemblent réellement les écrans d'inscription Instagram, où sont les boutons, et quelles portes humaines existent vraiment
> **Conditions du relevé** : Samsung Galaxy S20 émulé (`x1q`, `SM_G9810`), Android 13, écran **720 × 1440**, densité 261, Instagram **443.0.0.48.82**, proxy IPRoyal statique résidentiel sortant en `161.77.227.142` (San Francisco), langue de l'app anglais (US)

Les coordonnées ci-dessous sont en pixels, valables pour **720 × 1440**. Tout autre profil GeeLark avec une autre définition demande un nouveau relevé : rien ici n'est en pourcentage.

## 1. Ce que le relevé a corrigé dans le cahier des charges

| Ce qui était écrit | Ce qu'on observe |
|---|---|
| « Le numéro n'est donné que si la plateforme l'exige (bouton "Skip" d'abord) » (`account-creation.md` §5) | Instagram **exige** un numéro et un SMS **juste après la création**, sans aucun « Skip ». Le menu ⋮ de cet écran n'offre que « Download your information » et « Log out ». Le compte existe mais reste inutilisable tant que le SMS n'est pas validé. |
| Le captcha était listé comme une porte *possible* | Le captcha est arrivé **systématiquement**, immédiatement après « I agree ». Texte déformé à 6 chiffres, avec « Hear this code » et « Get a new code » en repli. |
| Le pseudo est un paramètre libre du skill | Instagram **pré-remplit le pseudo avec la partie locale de l'adresse e-mail**. Il faut donc soit nommer les adresses d'après le handle voulu (ce que `personas.md` fait déjà), soit vider le champ avant de taper. |
| — | Le sélecteur de pays du numéro s'ouvre sur **toute** la liste mondiale : un numéro non américain est accepté à cette porte. Il reste une incohérence face à une IP américaine. |

## 2. Installer l'application (API GeeLark)

`POST /open/v1/app/install` avec `{"envId": "<id du profil>", "appVersionId": "<id de version>"}`.

Le champ est **`appVersionId`**, et sa valeur se prend dans `appVersionInfoList[].id` de `POST /open/v1/app/installable/list` — **pas** dans le `id` de premier niveau, qui est l'identifiant de l'application. Passer l'identifiant d'application donne `{"code": 42006, "msg": "app not found"}` ; l'ancienne route `POST /open/v1/app/operation/batch` répond `success` avec `items: null` et **n'installe rien**.

## 3. Le piège ADB, à câbler avant tout le reste

La session ADB GeeLark expire en une dizaine de minutes. Passé ce délai, **toute** commande répond sur stdout :

```
error: you should run glogin to login first
```

`adb devices` continue d'afficher `device`, et le code de sortie reste 0. Un sondage naïf (`pm list packages | grep instagram`) renvoie donc « rien » au lieu d'une erreur : **une ferme non gardée croira que l'application n'est pas installée, ou qu'un compte ne poste pas, alors que la session est simplement tombée.**

Parade : intercepter la chaîne `run glogin` dans la sortie, reprendre le mot de passe par `POST /open/v1/adb/getData` (`{"ids": ["<id>"]}` → `data.items[0].pwd`), rejouer `adb shell glogin <pwd>`, puis rejouer la commande.

## 4. Parcours d'inscription, écran par écran

| # | Écran (titre à l'écran) | Élément | x, y | Note |
|---|---|---|---|---|
| 1 | *(connexion)* | `Create new account` | 360, 1230 | bas de l'écran d'accueil |
| 2 | What's your mobile number? | `Sign up with email` | 360, 626 | la porte e-mail, sous `Next` |
| 3 | What's your email? | champ e-mail | 360, 343 | |
| | | `Next` | 360, 448 | |
| 4 | Enter the confirmation code | 1re case du code | 75, 345 | 6 cases ; `input text` les remplit d'affilée |
| | | `I didn't get the code` | 360, 559 | renvoi d'un code |
| 5 | Create a password | champ mot de passe | 360, 343 | « Remember login info » est coché par défaut |
| | | `Next` | 360, 524 | |
| 6 | What's your birthday? | ouvre `Set date` | — | le sélecteur s'ouvre seul en arrivant |
| | `Set date` | année (éditable) | 483, 685 | **un appui rend la valeur éditable** : taper `1997` au lieu de faire défiler 29 crans |
| | | jour (éditable) | 353, 489 | coordonnées après recentrage du dialogue |
| | | mois (éditable, texte) | 222, 489 | `MOVE_END` (123) + 5 × `DEL` (67), puis taper `Jun` |
| | | `SET` | 489, 676 | |
| | | `Next` | 360, 533 | l'âge calculé s'affiche dans le champ |
| 7 | What's your name? | champ nom complet | 360, 260 | espace = `input text "%s"` |
| | | `Next` | 360, 379 | |
| 8 | Create a username | champ pseudo | 360, 356 | **pré-rempli** ; vider par `MOVE_END` + 20 × `DEL` |
| | | `Next` | 360, 475 | pastille verte = pseudo libre |
| 9 | Agree to Instagram's terms and policies | `I agree` | 360, 654 | crée le compte |
| 10 | Confirm you're human to use your account | `Continue` | 360, 597 | **porte humaine — captcha** |
| 11 | Confirm you're human | champ code | 360, 601 | image du captcha : rectangle 530 × 150 à partir de (100, 320) |
| | | `Next` | 360, 889 | |
| 12 | Enter your mobile number | champ numéro | 360, 370 | **porte humaine — SMS, sans échappatoire** |
| | | sélecteur de pays | 80, 370 | ouvre la liste mondiale |
| | | `Send code` | 360, 1281 | |

Temps observé de bout en bout, avec une capture et une lecture d'écran entre chaque action : **~35 min**. En rejeu de coordonnées, sans capture : compter 4 à 6 min, dont 1 à 2 d'attente du code e-mail.

## 4 bis. Ce qui se passe après le SMS : le compte est désactivé, pas vérifié

Suite observée le 2026-09-16 sur `jordan.reed.97`, immédiatement après la validation du numéro :

1. **Écran 13 — « Confirm you're a real person with a video selfie »**. Deux chemins seulement : `Start video selfie` (360, 1233) ou `Upload photo instead` (360, 1301). Le menu ⋮ ne propose ni « plus tard » ni « passer » : uniquement « Download your information » et « Log out ».
2. **Écran 14 — « Upload a verification selfie »** : `Upload a photo` (360, 394) → `Choose From Gallery` (360, 1216) → permission Android `ALLOW` (360, 745) → la photo → `Submit` (360, 1233).
3. **Écran 15 — « You submitted an appeal on <date> »** : *« Your account is not visible to people on Instagram, and you can't use it »*, revue annoncée en ~1 h, et *« if we find your account doesn't follow our Community Standards, it will be permanently disabled and you won't be able to appeal again »*.

Le mot important est **appeal**. Instagram n'a pas demandé à vérifier un compte actif : il a **désactivé le compte à la création**, et le selfie est le recours. Un compte neuf créé sur téléphone cloud derrière un proxy résidentiel statique naît donc désactivé, et son sort se joue sur une revue biométrique unique et sans rattrapage.

**Variable parasite introduite par ce test** : le numéro utilisé était français (+33) sur une IP San Francisco, et le code est arrivé **par WhatsApp** et non par SMS — le numéro était donc déjà connu de Meta. C'est un signal de désaccord que nous avons créé nous-mêmes ; il ne permet pas de conclure que l'escalade est systématique. Le test qui tranche est le même parcours avec un **numéro américain neuf**, tout le reste identique.

**Conséquence sur le plan si l'escalade se confirme** : la règle R7 (« créé sur le téléphone, jamais acheté ») devient le point de blocage d'Instagram, puisqu'aucun personnage synthétique ne peut franchir une vérification biométrique. Trois issues, à arbitrer : créer les comptes Instagram sur du matériel réel avec une personne réelle, retirer Instagram de M1, ou commencer M1 par une plateforme dont la porte d'entrée est moins dure [à vérifier : TikTok, X, Reddit].

## 5. Portes humaines confirmées

| Porte | `reason` (`gitd/skills/checkpoint.py`) | Quand | Automatisable ? |
|---|---|---|---|
| Code e-mail à 6 chiffres | `email` | écran 4 | **oui**, si la boîte est lisible par un connecteur |
| Captcha texte 6 chiffres | `captcha` | écran 10-11 | lisible à l'œil après agrandissement ; à traiter comme une porte humaine tant que ce n'est pas mesuré |
| Numéro + SMS | `sms` | écran 12 | **non** — demande un vrai numéro (R25) |

## 6. Ce que ça coûte, en vrai

Six personnages = **six numéros réels capables de recevoir un SMS, disponibles le jour de la création**, et non « plus tard si la plateforme le demande ». C'est un prérequis de J0, pas une option : sans numéro, le compte est créé mais reste bloqué derrière le contrôle, et ne peut ni poster, ni suivre, ni être chauffé.
