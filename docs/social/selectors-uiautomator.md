# Piloter les apps par l'arbre d'interface, pas par des coordonnées

> **Statut** : vérifié sur téléphone le 2026-09-16 (GeeLark `explorer-us`, Android 13, 720 × 1440, Instagram 443.0.0.48.82)
> **Répond à** : sur quoi écrire les gestes de chauffe, et comment savoir qu'un geste a vraiment eu lieu

## 1. Ce qui a été vérifié

`adb shell uiautomator dump` **fonctionne sur un téléphone cloud GeeLark**, et Instagram expose des identifiants de ressource stables. Sur le fil :

| Identifiant (`com.instagram.android:id/…`) | Ce que c'est | `content-desc` |
|---|---|---|
| `row_feed_button_like` | like | `Like` / `Liked` |
| `row_feed_button_comment` | ouvrir les commentaires | `Comment` |
| `row_feed_button_share` | envoyer en message | `Send post. <n> shares…` |
| `row_feed_button_save` | enregistrer | `Add to Saved` |
| `inline_follow_button` | suivre | `Follow <nom>` |
| `row_feed_photo_profile_name` | aller au profil | le handle |
| `row_feed_photo_imageview` | le média | résumé du post, likes, commentaires, âge |

## 2. Pourquoi ça change la conception des skills

**Le y d'une barre d'actions dépend du défilement.** Sur une même capture, `row_feed_button_like` est à y=351 pour une publication et y=1164 pour la suivante. Une coordonnée absolue est donc fausse dès le premier scroll. Les ~40 sélecteurs écrits à l'aveugle avant ce relevé doivent être réécrits sur des identifiants résolus à l'exécution.

Les coordonnées fixes ne restent légitimes que là où il n'y a pas d'identifiant utile et où l'écran est unique : les parcours d'inscription (`screens-instagram.md`, `screens-reddit.md`), les dialogues système Android, les sélecteurs de date.

## 3. Deux pièges vérifiés

1. **Un identifiant n'est pas unique à l'écran.** Il apparaît une fois par publication visible. Il faut le chercher **dans le conteneur de la publication visée** (`row_feed_profile_header` / `row_feed_view_group_buttons`), jamais globalement — sinon on like la mauvaise publication.
2. **`clickable="false"` sur like, commentaire et partage.** Seul `row_feed_button_save` est marqué `clickable="true"`. Un sélecteur qui filtrerait sur `clickable="true"` **jetterait les trois gestes principaux**. Taper le centre des `bounds` fonctionne quand même : c'est le parent qui reçoit l'événement.

## 4. La boucle qui rend chaque geste vérifiable

Vérifié de bout en bout : like posé sur la seconde publication du fil, `content-desc` passé de `Like` à `Liked`.

```
1. uiautomator dump            → état avant
2. résoudre l'identifiant dans le conteneur de la publication visée
3. input tap <centre des bounds>
4. uiautomator dump            → état après
5. comparer les content-desc
```

L'étape 5 est ce qui manquait au dossier. Un geste qui ne fait pas basculer l'état a été **avalé en silence** : c'est la définition opérationnelle d'un blocage d'action ou d'un shadowban, et elle devient mesurable au lieu d'être supposée. À brancher sur `health-canaries.md` : `n` gestes consécutifs sans bascule d'état ⇒ `shadowban_suspect`, sans attendre un signal de portée.

Coût : deux dumps par geste, ~2 s chacun sur ce téléphone. Acceptable aux volumes de la chauffe (quelques dizaines de gestes par compte et par jour), à ne pas mettre dans une boucle serrée.

## 5. Reste à relever

Les identifiants des autres surfaces (feuille de commentaires, profil, recherche, messages, publication, story) et ceux de TikTok, X et Reddit. Même méthode : ouvrir l'écran, dumper, lire.
