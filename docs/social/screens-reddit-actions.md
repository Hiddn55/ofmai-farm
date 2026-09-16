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
| `save` | `post_overflow` → `action_item_title` « Save » | l'entrée du menu devient **`Unsave`** | **oui, vérifié** |
| `comment` | `Join the conversation` → champ → `Send comment` | le fil affiche `Level 1 comment by <handle>, Now, 1 vote` | **oui, vérifié** |
| `comment_reply` | `Reply` dans `fbp_comment_footer` → `Send comment` | `Level 2 comment by <handle>, Now, 1 vote` | **oui, vérifié** |
| `post` | Create → `community_selector` → `post_title_field` → `post_body_field` → `action_button_label` « Post » | `From <handle>, Posted Now, <titre>` | **oui, vérifié** — publié dans **r/test**, sub prévu pour ça |
| `profile_visit` | `bottom_nav` → `You` → `profile_name` | compteurs lisibles, dont **`profile_highlights_karma`** | **oui, vérifié** |
| `search` | `main_top_app_bar_search` → `expanded_search_field` | suggestions en `typeahead_suggestion_item`, sections en `search_section_title` | **oui, vérifié** |
| `dm_reply` (= chat) | `bottom_nav` → `Inbox` → onglet `Chats` | — | **non** : `empty_chats_content`, aucun message entrant sur un compte neuf |

**Le karma est lisible dans l'arbre** : `profile_highlights_karma` porte « 1 Karma » sur l'écran de profil. C'est exactement la donnée que `redditReadiness` (`lib/social/bridge-queue.ts`) exigeait sans qu'aucun événement ne la transporte — d'où une file Reddit qui n'aurait jamais rien publié, en silence. On sait maintenant où la lire.

**Le composeur ne propose pas le profil personnel comme destination** : la recherche par pseudo ne renvoie que des communautés. Une publication Reddit vise donc toujours un sub, ce qui rend le choix des subs (`publishing.md` §5) obligatoire et non optionnel.

## 3. Coordonnées de la barre d'actions (720 × 1440)

Décalages **dans** `post_footer` — à recalculer à partir du centre du nœud, jamais en absolu :

| Contrôle | x | y (= centre de `post_footer`) |
|---|---|---|
| upvote | 61 | 728 |
| downvote | 172 | 728 |
| commentaires | 247 | 728 |

Barre d'un **commentaire**, décalages dans `fbp_comment_footer` : menu 410 · `Reply` **512** · upvote 603 · downvote 662, au y du centre du nœud.
| repost | 586 | 728 |
| partage | 663 | 728 |

Barre du bas : `Home` 90,1321 · `Create` 270,1321 · `Inbox` 450,1321 · `You` 630,1321.

## 4. Écrans intercalaires vérifiés

Reddit en intercale beaucoup, et chacun avale le tap suivant si le skill ne l'attend pas :

1. **`Can't create passkey`** à l'inscription — attendu sur un téléphone cloud (ni compte Google, ni verrouillage d'écran). `OK` à 589,1270.
2. **Feuille de bienvenue** après avoir rejoint un sub — `got_it_button`, ou `Close sheet` à 360,296.
3. **« Are you enjoying Reddit? »** — se superpose au bouton précédent et le rend inopérant. Deux choix : `Not really` / `Love it!`.

L'enseignement général, commun aux deux plateformes : **avant chaque geste, confirmer l'écran courant**. Un tap envoyé sur un écran recouvert ne produit rien et ne lève aucune erreur.
