# X — la porte d'entrée est fermée sur téléphone cloud

> **Statut** : vérifié à la main le 2026-09-17 sur le profil GeeLark `explorer-us`
> **Répond à** : peut-on créer un compte X depuis un téléphone cloud, et sinon pourquoi
> **Conditions** : Android 13, 720 × 1440, X **12.17.0**, proxy IPRoyal statique résidentiel San Francisco

## 1. Le résultat

**X refuse l'inscription.** Après la saisie d'une adresse e-mail correctement formée, l'écran répond :

> ⊗ Please use official X apps to proceed or try again later.

Le parcours jusque-là est normal : écran d'accueil (Google · e-mail · **Continue with Phone**), l'e-mail est proposé sans exiger de numéro, l'écran « Enter your email address » accepte la saisie. Le refus tombe au moment de valider.

## 2. Ce qui a été écarté

- **Ce n'est pas l'adresse** : premier essai avec une adresse malformée, second essai avec `nathann@ofmai.ai` correctement saisie — même refus.
- **Ce n'est pas la provenance de l'APK** : les quatre applications du téléphone déclarent `installerPackageName=com.android.vending`, y compris X. GeeLark pose cette attribution ; l'application n'est pas signalée comme venant d'une source inconnue.

## 3. L'hypothèse, et son degré de certitude

Le message est celui que X renvoie quand il juge le client non authentique. Les deux applications qui se sont laissé faire (Instagram, TikTok, Reddit) ne vérifient pas l'intégrité de l'appareil à l'inscription ; X, lui, semble le faire. Un téléphone cloud GeeLark est une machine virtualisée, pas un appareil Android certifié : il échoue ce type de contrôle par construction.

**Probable, non prouvé.** Ce qui trancherait : le même parcours sur un appareil physique réel avec la même IP, pour séparer l'appareil du réseau. C'est exactement le banc d'essai à trois configurations déjà prévu (`build-plan.md`) et toujours pas fait.

## 4. Ce que ça change au plan

Peu, en réalité — et c'est la bonne nouvelle. `publishing.md` §4 prévoit déjà **X par API v2**, pas par l'application : le téléphone ne sert pas à publier sur X. Ce qui reste à résoudre, c'est uniquement la **création** du compte, qui devra se faire ailleurs que sur le téléphone cloud : navigateur sur une connexion ordinaire, puis pilotage par API depuis l'IP statique du personnage.

Conséquence sur l'ordre de construction : X sort du chemin critique du téléphone. Il ne bloque ni la chauffe, ni les trois autres plateformes.

## 5. Un piège de saisie, vérifié

Le champ e-mail de X **repositionne le curseur entre deux saisies successives**. Une adresse tapée en morceaux (`nathann` + `@ofmai` + `.ai`) est ressortie mélangée : `nath@ofmai.aiann`. Il faut envoyer l'adresse **en un seul `input text`**. Les champs d'Instagram et de Reddit ne font pas ça — c'est propre à X.

## 6. Un piège d'infrastructure, vérifié le même jour

**Le port ADB d'un téléphone GeeLark change à chaque redémarrage** : `20567` avant l'arrêt, `20780` après. Toute valeur mise en dur cesse de fonctionner silencieusement — `adb connect` expire sans rien dire d'utile. Le port et le mot de passe doivent être redemandés à `POST /open/v1/adb/getData` après chaque démarrage, jamais mémorisés.
