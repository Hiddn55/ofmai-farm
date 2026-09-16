# Écrans Reddit — relevé sur téléphone réel

> **Statut** : vérifié à la main le 2026-09-16 sur le profil GeeLark `explorer-us`
> **Répond à** : à quoi ressemble l'inscription Reddit et quelles portes elle oppose
> **Conditions** : Samsung Galaxy S20 émulé, Android 13, **720 × 1440**, Reddit **2026.35.0**, proxy IPRoyal statique résidentiel San Francisco

## 1. Le résultat qui compte

**Reddit est la seule des quatre plateformes où un compte a pu être créé et reste utilisable.** Aucun numéro, aucun captcha, aucune vérification biométrique. Compte obtenu : `jordan_reed97`, fil d'accueil accessible immédiatement.

Comparaison à la même date, mêmes appareil, proxy et rythme :

| Plateforme | Numéro exigé | Captcha | Vérification biométrique | Compte utilisable ? |
|---|---|---|---|---|
| **Reddit** | non | non | non | **oui** |
| TikTok | oui, après création (« for security purposes ») | non | non | non — bloqué faute de numéro libre |
| Instagram | oui, dans le parcours | oui, systématique | oui, selfie vidéo, présenté comme un **appel** | seulement après recours accepté |

Conséquence directe pour `build-plan.md` : **M1 peut démarrer par Reddit** sans attendre les numéros américains, alors qu'Instagram et TikTok en dépendent.

## 2. Parcours, écran par écran

| # | Écran | Élément | x, y | Note |
|---|---|---|---|---|
| 1 | The most real place on the internet | `Get Started` | 360, 1224 | |
| 2 | Get Started (feuille) | `Continue with email` | 360, 1135 | au-dessus : Google et numéro, tous deux évitables |
| 3 | Hi new friend, welcome to Reddit | champ e-mail | 360, 639 | |
| | | `Continue` | 360, 832 | |
| 4 | Verify your email | champ code | 360, 390 | 6 chiffres, champ unique (pas 6 cases) |
| | | `Continue` | 360, 917 | `Resend` disponible après 30 s |
| 5 | Create your username | champ pseudo | 360, 392 | **pré-rempli d'un pseudo aléatoire**, pas dérivé de l'e-mail — contrairement à Instagram. Vider par la croix à 655, 385 |
| | | `Continue` | 360, 832 | |
| 6 | Set a password | champ mot de passe | 360, 330 | |
| | | `Continue` | 360, 845 | |
| 7 | *(dialogue)* Can't create passkey | `OK` | 589, 1270 | **attendu sur un téléphone cloud** : ni compte Google ni verrouillage d'écran. Sans conséquence, mais le skill doit l'attendre |
| 8 | *(permission Android)* notifications | `ALLOW` | 360, 745 | à accepter : `get_notifications` lit les codes dans les notifications (`account-creation.md` §4.3) |
| 9 | About you — anniversaire | champ | 360, 372 | facultatif (`Skip` à 188, 1295) mais utile : conditionne l'accès aux subs adultes |
| | `Select date` | bascule clavier (crayon) | 596, 373 | **beaucoup plus fiable que le calendrier** : ouvre un champ `MM/DD/YYYY` |
| | | champ date | 360, 544 | saisir `06141997` sans séparateurs |
| | | `OK` | 595, 681 | |
| | | `Continue` | 531, 1295 | |
| 10 | *(feuille)* Confirm your birthday? | `Yes, Confirm` | 360, 1256 | |
| 11 | About you — genre | `Man` / `Woman` / `Non-binary` | 360, 346 / 424 / 502 | |
| 12 | Choose your interests | 12 pastilles, grille 3 × 4 | col. 120 / 360 / 600 · lignes 351, 554, 755, 958 | |
| 13 | Customize your feed | liste de sous-thèmes | lignes à partir de 412, pas de 78 px | |
| | | `Continue` | 531, 1295 | mène au fil d'accueil |

Barre de navigation du fil : `Home` 90, 1320 · `Create` 270, 1320 · `Inbox` 450, 1320 · `You` 630, 1320.

## 3. Ce qui reste à relever

Les écrans de chauffe (vote, commentaire, rejoindre un sub, profil, publication, message privé) ne sont pas encore cartographiés — c'est le prochain passage, et il est désormais possible puisque le compte est ouvert.
