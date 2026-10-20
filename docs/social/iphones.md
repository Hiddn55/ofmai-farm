# Les iPhones de la ferme — registre et procédure

> **Nature** : registre + procédure
> **À jour au** : 2026-10-20
> **Répond à** : quel iPhone porte quel personnage, quelle ligne, quel Apple ID ; comment on met un iPhone en service ; où sont les secrets.
> **Règle** : un iPhone = un personnage = une ligne = un Apple ID. Aucun mot de passe dans ce fichier : tout est dans le Trousseau du Mac mini.

## 1. Le registre

Une ligne par téléphone, remplie au fur et à mesure. Les colonnes vides sont des étapes pas encore faites.

| Slot | Modèle | Acheté le | N° de série / UDID | IMEI | Ligne (numéro) | Opérateur | Personnage | Apple ID (adresse iCloud) | Mode dév. | WDA | Réseaux créés |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `iphone-01` | iPhone 12 64 Go | 2026-10 | | | | B&You 90 Go | *(à décider)* | *(après la SIM)* | | | |
| `iphone-02` | iPhone 12 64 Go | 2026-10 | | | | B&You 90 Go | *(à décider)* | *(après la SIM)* | | | |

Le numéro de série et l'UDID se lisent dans Réglages → Général → Informations, ou depuis le Mac mini une fois branché : `xcrun xctrace list devices` ou `idevice_id -l`.

## 2. Les secrets, dans le Trousseau du Mac mini

Une entrée par secret, par **slug** de personnage (comme pour les réseaux, `account-creation.md` §8). Tant que le personnage n'est pas nommé, le slug est le slot (`iphone-01`), et on renomme l'entrée le jour où il l'est.

```sh
# le code de verrouillage de l'iPhone (6 chiffres, posé à la mise en service)
security add-generic-password -s ofmai-social-iphone-<slug>-passcode -a <slug> -w "<code>" -U
# le mot de passe de l'Apple ID du personnage (créé avec sa SIM)
security add-generic-password -s ofmai-social-apple-<slug> -a <adresse icloud> -w "<mot de passe>" -U
# la ligne (numéro et, s'il existe, le code PIN de la SIM)
security add-generic-password -s ofmai-social-sim-<slug> -a "+33…" -w "+33… ; PIN=…" -U
# relire
security find-generic-password -s ofmai-social-apple-<slug> -w
```

Le compte développeur Apple (99 $/an, celui qui signe WebDriverAgent) est **un seul compte, à ton nom**, sur le Mac mini : `ofmai-apple-developer` dans le Trousseau. Il ne se connecte jamais sur un iPhone.

## 3. Mise en service d'un iPhone, dans l'ordre

### 3.1 À la réception, avant toute SIM

1. Allumer. Si l'écran demande l'Apple ID **d'un ancien propriétaire** (verrouillage d'activation) : retour au vendeur, le téléphone est une brique.
2. Configuration : langue Français, région France, **pas de transfert**, Wi-Fi de la maison pour cette étape seulement.
3. Écran « Identifiant Apple » → **« Mot de passe oublié ou pas d'identifiant Apple ? » → « Configurer plus tard dans Réglages »**. On ne crée pas d'Apple ID sans la SIM du personnage.
4. Code de verrouillage : 6 chiffres, généré, **dans le Trousseau** (`-passcode`). Face ID : passer.
5. Réglages → Général → VPN et gestion : **doit être vide** (pas de profil de gestion d'entreprise).
6. Réglages → Général → Mise à jour logicielle : installer la dernière version d'iOS.
7. Réglages → Luminosité : minimum ; Verrouillage automatique : **Jamais**.
8. Noter série, UDID, IMEI dans le registre (§1).

### 3.2 Branchement au Mac mini (le test WebDriverAgent)

1. Câble Lightning sur le hub alimenté. Sur l'iPhone : « Se fier à cet ordinateur » → Se fier, code de verrouillage.
2. Réglages → Confidentialité et sécurité → **Mode développeur** → activer → redémarrage → confirmer.
3. Sur le Mac mini : Xcode installé, compte développeur ajouté dans Xcode → Réglages → Comptes.
4. Lancer la ferme en mode iOS (`docs/social/ios.md`, à écrire au premier dump) : le but du premier jour est **un dump de l'écran d'accueil**. Tant qu'il n'est pas obtenu, on n'achète rien d'autre.
5. Registre : colonnes « Mode dév. » et « WDA » à `oui` + date.

### 3.3 La ligne et l'Apple ID (quand le personnage est nommé)

1. SIM du personnage dans le téléphone. Réglages → Données cellulaires : activée ; **Wi-Fi : désactivé, réseau de la maison oublié**. À partir d'ici le téléphone ne parle qu'en data mobile.
2. Réglages → Se connecter à l'iPhone → **Créer un identifiant Apple** : nom et date de naissance **de la fiche du personnage**, « Vous n'avez pas d'adresse e-mail ? » → **obtenir une adresse iCloud** (c'est la boîte mail du personnage, elle ne se change plus), numéro = **la ligne du personnage** (le code SMS arrive sur ce téléphone), mot de passe généré → Trousseau (`ofmai-social-apple-<slug>`), moyen de paiement : **Aucun**.
3. Numéro de confiance supplémentaire : le tien, pour pouvoir récupérer le compte si la ligne saute. Apple ne le partage avec personne.
4. iCloud : tout décocher sauf Messages ; Localiser : désactivé ; « Partager les analyses » : non.
5. App Store : Instagram, TikTok, Reddit. Pas d'autre app.
6. Registre : ligne, personnage, adresse iCloud.

### 3.4 Les comptes des réseaux

`account-creation.md` : par numéro, un réseau à la fois, jamais deux codes de suite sur la même ligne, et le pseudo exact noté dans la fiche du personnage et au ledger le jour même.

## 4. Ce qu'on ne fait jamais

- Un Apple ID partagé entre deux téléphones, ou le compte développeur sur un téléphone.
- Le Wi-Fi allumé en exploitation : tout le trafic passerait par la box, plus par la ligne du personnage.
- Un secret écrit ici, dans une fiche, dans un message : Trousseau seulement.
- Un deuxième téléphone acheté avant que le premier ait donné son dump d'écran.
