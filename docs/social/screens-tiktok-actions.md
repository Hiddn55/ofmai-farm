# TikTok — actions exercées sur un vrai compte

> **Statut** : vérifié à la main le 2026-09-18 sur le profil GeeLark `explorer-us`, compte `@jordan.reed90`
> **Conditions** : Android 13, 720 × 1440, TikTok **46.8.2**, proxy IPRoyal statique résidentiel San Francisco, numéro US Mobile en indicatif 415

## 1. Trois plateformes, trois façons de piloter

C'est l'enseignement central du relevé, et il interdit d'écrire un seul moteur de skill :

| | Sélecteurs | Vérification d'un geste |
|---|---|---|
| **Instagram** | `resource-id` stables et parlants | bascule de `content-desc` (`Like` → `Liked`) |
| **Reddit** | Compose : aucun id ni description sur les votes | **visuelle** (la flèche passe à l'orange) |
| **TikTok** | ids **obfusqués** (`a3d`, `uxt`, `g5l`…), inutilisables et changeants | **le compteur s'incrémente** |

Sur TikTok, les `content-desc` sont en revanche riches et chiffrées — `Like video. 75.7K likes`, `Read or add comments. 344 comments`, `Add or remove this video from Favorites.`, `Follow <handle>`. **C'est par la description qu'on sélectionne**, jamais par l'id.

## 2. Le piège qui casse tout : `uiautomator` ne peut pas lire une vidéo en cours

```
ERROR: could not get idle state.
```

`uiautomator dump` exige que l'interface atteigne un état stable. Une vidéo TikTok qui joue ne s'arrête jamais d'animer : **le dump échoue**, et il échoue aussi sur les **résultats de recherche**, dont les vignettes jouent en boucle. Mettre en pause ne suffit pas toujours.

Conséquence : sur ces écrans, le skill doit basculer sur **capture d'écran + coordonnées**. Le pilotage par arbre ne marche que sur les écrans statiques (feuille de commentaires, profil, composeur de publication). C'est propre à TikTok — Instagram et Reddit se laissent lire partout.

## 3. Tableau des actions

| Action | Par quoi ça passe | Preuve observée | Exercée ? |
|---|---|---|---|
| `view` | fil, `content-desc` du post | — | oui |
| `like` | description `Like` | compteur **75,7K → 75,8K** | **oui, vérifié** |
| `save` | `Add or remove this video from Favorites.` | compteur **3 855 → 3 856** | **oui, vérifié** |
| `comment` | `Add comment...` → flèche d'envoi | **344 → 345 comments**, texte retrouvé sous notre pseudo | **oui, vérifié** |
| `comment_reply` | `Reply` sous un commentaire → même composeur | **345 → 346** | **oui, vérifié** |
| `post` | Create → galerie → `Next` → titre → `Post` → `Post Now` | la publication apparaît sur la grille du profil | **oui, vérifié** |
| `search` | loupe → saisie → `KEYCODE_ENTER` | onglets Top / Users / Videos, créateurs avec nombre d'abonnés | **oui, vérifié visuellement** |
| `profile_visit` | onglet `Profile` | `Following` / `Followers` / `Likes` lisibles | **oui, vérifié** |
| `follow` | description `Follow <handle>` | — | **NON** — voir §4 |
| `dm_reply` | onglet `Inbox` | — | non exercée |

## 4. Un faux positif, et c'est la leçon la plus utile du relevé

Après un tap sur `Follow jaaw`, **le nœud `Follow jaaw` disparaît de l'arbre**. C'est tentant de lire ça comme « le follow a réussi ». C'est faux : le profil affiche ensuite **`Following 0`**.

La disparition d'un nœud n'est donc **pas** une preuve de réussite — elle peut aussi bien signaler un rendu en cours, un changement de vue, ou rien du tout. Un skill qui s'y fie compterait des follows qui n'existent pas, et le ledger dériverait en silence par rapport à la réalité.

**Séquence exacte au moment de l'échec**, parce qu'elle oriente le diagnostic : `like` → **6 s** → `save` → **8 s** → `follow`. Soit trois engagements en une quinzaine de secondes, sur un compte créé vingt minutes plus tôt, sans publication ni abonné.

Deux causes possibles, non départagées :

- **mécanique** — le bouton Suivre est à y=763, l'avatar à y=728 : **35 pixels d'écart**, un tap mal centré rate la cible ;
- **comportementale** — TikTok freine peut-être l'engagement rapide d'un compte neuf. Si c'est le cas, la politique de chauffe doit prévoir que **les premiers follows ne comptent pas**, et ne pas les inscrire comme réussis au ledger.

Le test qui tranche : espacer les gestes de plusieurs minutes, viser plus bas, et **relire le compteur du profil après chaque follow** au lieu de se fier au fil.

**Règle** : sur TikTok, un geste ne se vérifie que par un **compteur qui bouge** — celui du post pour like, favori et commentaire, celui du profil pour le suivi. Jamais par l'absence d'un élément.

## 5. Coordonnées relevées (720 × 1440)

Barre du bas : `Home` 72,1322 · `Friends` 216,1322 · `Create` 360,1322 · `Inbox` 504,1322 · `Profile` 648,1322.
Rail d'actions du fil (positions relatives au post visible, à résoudre par description) : avatar 670,728 · suivre 670,763 · like 671,827 · commentaires 668,938 · favori 668,1036 · partage 668,1134.
Feuille de commentaires : champ `Add comment...` 307,1302 · **flèche d'envoi 657,858** (clavier ouvert) · fermeture 683,471.

## 6. À l'inscription

Le compte a été créé **par numéro**, pas par e-mail. TikTok a alors **dérivé le pseudo du surnom saisi** (`Jordan Reed` → `@jordan.reed90`), sans passer par l'adresse e-mail — contrairement à Instagram, qui pré-remplit le pseudo depuis la partie locale de l'adresse. Le handle voulu doit donc être posé dans le **surnom** sur TikTok, dans l'**adresse e-mail** sur Instagram.
