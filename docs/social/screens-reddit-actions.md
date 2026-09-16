# Reddit — les actions exercées sur un vrai compte

> **Statut** : vérifié à la main le 2026-09-16 sur le profil GeeLark `explorer-us`, compte `jordan_reed97`
> **Répond à** : par quoi passe chaque action sur Reddit, et comment savoir qu'elle a réussi
> **Conditions** : Android 13, 720 × 1440, Reddit 2026.35.0, proxy statique résidentiel San Francisco

## 1. La différence de fond avec Instagram

**Reddit est écrit en Jetpack Compose et n'expose presque rien à `uiautomator`.** Les boutons de vote, de commentaire et de partage d'un post n'ont **ni identifiant propre, ni `content-desc`** : ils sont noyés dans un unique nœud `post_footer`.

Conséquence sur la conception des skills : sur Instagram, un geste se vérifie dans l'arbre (`Like` → `Liked`). Sur Reddit, **la vérification doit être visuelle** — la flèche et le compteur passent à l'orange après un vote. Deux architectures différentes selon la plateforme ; le dossier ne peut pas supposer une méthode unique.

Nuance importante : les **commentaires**, eux, portent une `content-desc` riche — `Level 1 comment by <auteur>, <âge>, <n> votes`. Tout ce qui touche aux commentaires reste donc vérifiable dans l'arbre.

## 2. Tableau des actions

| Action | Par quoi ça passe | Preuve de réussite | Exercée ? |
|---|---|---|---|
| `view` | `post_unit`, `post_header` | — | oui |
| `follow` (= rejoindre) | `post_join_button` | libellé `Join` → **`Joined`** | **oui, vérifié** |
| `like` (= upvote) | décalage fixe dans `post_footer` | **flèche et compteur passent à l'orange** (contrôle visuel) | **oui, vérifié** |
| `comment` | `Join the conversation` → champ → `Send comment` | le fil affiche `Level 1 comment by <handle>, Now, 1 vote` | **oui, vérifié** |
| `post` | `post_title_field`, `post_body_field` / `richtext_edit_text_view`, `community_selector` | — | **non** : composeur entièrement relevé, publication **non effectuée** — le sélecteur n'offre pas le profil personnel comme destination et publier un test dans une vraie communauté dérange des gens pour rien |
| `search` | `main_top_app_bar_search` | — | à relever |
| `profile_visit` | `bottom_nav` → `You` | — | à relever |
| `dm_reply` (= chat) | `bottom_nav` → `Inbox` | — | à relever |
| `save` | menu `post_overflow` | — | à relever |

## 3. Coordonnées de la barre d'actions (720 × 1440)

Décalages **dans** `post_footer` — à recalculer à partir du centre du nœud, jamais en absolu :

| Contrôle | x | y (= centre de `post_footer`) |
|---|---|---|
| upvote | 61 | 728 |
| downvote | 172 | 728 |
| commentaires | 247 | 728 |
| repost | 586 | 728 |
| partage | 663 | 728 |

Barre du bas : `Home` 90,1321 · `Create` 270,1321 · `Inbox` 450,1321 · `You` 630,1321.

## 4. Écrans intercalaires vérifiés

Reddit en intercale beaucoup, et chacun avale le tap suivant si le skill ne l'attend pas :

1. **`Can't create passkey`** à l'inscription — attendu sur un téléphone cloud (ni compte Google, ni verrouillage d'écran). `OK` à 589,1270.
2. **Feuille de bienvenue** après avoir rejoint un sub — `got_it_button`, ou `Close sheet` à 360,296.
3. **« Are you enjoying Reddit? »** — se superpose au bouton précédent et le rend inopérant. Deux choix : `Not really` / `Love it!`.

L'enseignement général, commun aux deux plateformes : **avant chaque geste, confirmer l'écran courant**. Un tap envoyé sur un écran recouvert ne produit rien et ne lève aucune erreur.
