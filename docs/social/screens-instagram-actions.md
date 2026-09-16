# Instagram — les 12 actions, exercées sur un vrai compte

> **Statut** : vérifié à la main le 2026-09-16 sur le profil GeeLark `explorer-us`, compte `jordan.reed.97`
> **Répond à** : pour chaque action de `policy.py`, par quel identifiant elle passe et **à quoi on reconnaît qu'elle a réussi**
> **Conditions** : Samsung Galaxy S20 émulé, Android 13, 720 × 1440, Instagram 443.0.0.48.82, proxy statique résidentiel San Francisco
> **Méthode** : `selectors-uiautomator.md` — dump, résolution de l'identifiant, tap, re-dump, comparaison d'état

## 1. Tableau des 12 actions

| Action (`policy.py`) | Identifiant | Preuve de réussite observée | Exercée ? |
|---|---|---|---|
| `view` | `row_feed_photo_imageview` | sa `content-desc` porte auteur, likes, commentaires, âge du post | oui |
| `like` | `row_feed_button_like` | `Like` → **`Liked`** | **oui, vérifié** |
| `save` | `row_feed_button_save` | `Add to Saved` → **`Remove from saved`** | **oui, vérifié** |
| `follow` | `profile_header_follow_button` | `Follow <nom>` → **`Following <nom>`** | **oui, vérifié** |
| `comment` | `layout_comment_thread_edittext_multiline` puis `layout_comment_thread_post_button_icon` | le fil affiche `<handle> said <texte>` et le champ redevient `Join the conversation…` | **oui, vérifié** |
| `comment_reply` | mêmes identifiants, après un tap sur `Reply` | bannière `Replying to <handle>`, champ pré-rempli `@<handle>` ; puis `<handle> said @<handle> <texte>` | **oui, vérifié** |
| `post` | `action_bar_buttons_container_left` → `next_button_textview` → `media_thumbnail_tray_button` → `caption_input_text_view` → `share_footer_button` | le fil affiche `<handle> posted a photo N seconds ago` | **oui, vérifié** |
| `story_post` | onglet `STORY` → `gallery_preview_button` → `your_story_share_shortcut_button` | bandeau `<handle>'s story, 0 of N, Unseen` | **oui, vérifié** |
| `story_view` | `row_profile_header_imageview` | `<handle>'s **unseen** story` → `<handle>'s **seen** story` | **oui, vérifié** |
| `profile_visit` | `row_search_user_username`, puis les compteurs du profil | `profile_header_familiar_{post,followers,following}_value` lisibles | **oui, vérifié** |
| `search` | `action_bar_search_edit_text` + `KEYCODE_ENTER` (66) | `serp_journey_header_query_text` porte la requête, résultats en `row_search_user_username` | **oui, vérifié** |
| `dm_reply` | `action_bar_end_action_buttons` → `direct_new_chat_to_field` / `search_edit_text` | — | **non** : suppose un message entrant, aucun sur un compte neuf |

**La recherche est gratuite en signal utile** : `row_search_user_fullname` porte déjà le nombre d'abonnés (`Gymshark • 8.6M followers`). Le choix des cibles de follow ne demande donc pas d'ouvrir chaque profil.

**Les compteurs du profil sont lisibles dans l'arbre** (`…_post_count_value`, `…_followers_value`, `…_following_value`). `metrics-attribution.md` et les canaris n'ont pas besoin d'API pour suivre la croissance d'un compte.

## 2. Pièges vérifiés, qui auraient cassé le skill en silence

1. **`caption_input_text_view` garde le libellé `Write a caption` même une fois rempli.** Un skill qui vérifierait la saisie sur ce libellé conclurait à un échec alors que la légende est là. La saisie passe par un éditeur plein écran validé par un bouton `OK` en haut à droite.
2. **`button_container` sert à la fois pour `Edit profile` et `Share profile`**, et sur un profil tiers pour `Message` et `Shop`. L'identifiant seul ne suffit jamais : il faut désambiguïser par la `content-desc`.
3. **La barre d'actions d'un post n'a pas de position fixe** : même identifiant à y=351 et y=1164 sur une seule capture. Résoudre dans le conteneur du post visé.
4. **`clickable="false"`** sur like, commentaire et partage — filtrer là-dessus jetterait les trois gestes.
5. **Les encarts promotionnels s'intercalent n'importe quand** (« Introducing the Instagram map », « Introducing instants »). Ils partagent un identifiant de rejet : **`igds_headline_secondary_action_text_button`** (« Not now »). À traiter génériquement avant chaque action, sinon le tap suivant part dans le vide.
6. **L'écran de synchronisation des contacts boucle** : `Next` ne fait rien et le retour non plus. Sortie : `am force-stop` puis relance — l'app reprend directement au fil. Effet de bord souhaitable : **les contacts ne sont jamais synchronisés**, ce qui évite un lien entre comptes.
7. **L'onglet STORY demande caméra puis micro** (`permission_allow_foreground_only_button`). À prévoir dans le skill de première publication de story.
8. **Instagram enchaîne sur un carrousel de suggestions juste après un follow** (`suggested_user_card_follow_button`). C'est le rail du follow en chaîne que la règle interdit : ne jamais enchaîner dessus.
9. **Une image générée de toutes pièces peut être refusée par le composeur** : un JPEG produit par conversion depuis un PNG synthétique n'a jamais affiché de prévisualisation, là où une vraie photo passe. À vérifier sur les rendus de la banque de contenu avant de croire à une panne de skill [à vérifier : quel attribut exact bloque].

## 3. Écran par écran, coordonnées du 720 × 1440

Barre du bas : `feed_tab` 72,1326 · `clips_tab` 216,1326 · `direct_tab` 360,1326 · `search_tab` 504,1326 · `profile_tab` 648,1326.
Barre du haut du fil : création `action_bar_buttons_container_left` 39,84 · activité `notification` 680,84.

Ces positions ne servent qu'aux barres fixes. Tout le reste passe par l'arbre.
