# Runbook — la ferme sur le Mac mini, avec de vrais iPhones

> **Nature** : procédure
> **À jour au** : 2026-10-27
> **Répond à** : installer la ferme sur le Mac mini et obtenir, le premier jour, un dump d'écran d'un iPhone piloté par la ferme. Tout ce qui vient après (Apple ID, comptes, chauffe) est dans `iphones.md` et `account-creation.md`.
> **Décision** : depuis le 19/10, les personnages tournent sur de **vrais iPhones** branchés au Mac mini (Appium + WebDriverAgent), plus sur GeeLark (attestation Google en échec, `ETAT.md`). GeeLark ne sert plus qu'aux deux comptes Instagram déjà créés, tant qu'ils vivent.

## 0. Avant de commencer : les versions

Xcode doit connaître l'iOS du téléphone. C'est le premier point qui bloque, vérifier avant tout le reste.

| iOS du téléphone (Réglages → Général → Informations) | Xcode nécessaire | macOS nécessaire sur le Mac mini |
|---|---|---|
| iOS 18.x | Xcode 16 | macOS 14.5 ou plus |
| iOS 26.x | Xcode 26 | macOS 15.5 ou plus |

`sw_vers` donne le macOS du Mac mini ; `xcodebuild -version` l'Xcode installé. Un Xcode trop vieux refuse le téléphone (« device support files »), et il n'y a pas de contournement.

## 1. Installer, une fois

```sh
# 1. Xcode (App Store, ~12 Go), puis les outils en ligne de commande
xcode-select --install
sudo xcodebuild -license accept
# 2. Node (nvm) puis Appium et son pilote iOS
npm install -g appium && appium driver install xcuitest
# 3. Le dépôt de la ferme et son environnement Python
git clone https://github.com/Hiddn55/ofmai-farm.git ~/ofmai-farm && cd ~/ofmai-farm
python3.11 -m venv .venv && .venv/bin/pip install -e ".[all]"   # ou requirements.txt selon l'état du fork
# 4. adb n'est plus nécessaire pour les iPhones ; le garder pour GeeLark : brew install android-platform-tools
# 5. Les secrets : rejouer le fichier exporté depuis le MacBook (scripts/keychain-export.sh), puis le supprimer
sh ~/Desktop/ofmai-farm-keychain-<date>.sh && rm ~/Desktop/ofmai-farm-keychain-<date>.sh
# 6. Le compte développeur Apple (99 $/an) : Xcode → Réglages → Comptes → ajouter l'Apple ID développeur
```

Variables d'environnement de la ferme, dans `~/ofmai-farm/.env` (jamais commité) :

```sh
GEELARK_APP_ID=DLOTO4D5HB4GVMQH4DYLND6YSG      # tant que les comptes GeeLark vivent
FARM_OFMAI_BASE_URL=https://ofmai.ai            # cibles radar + commentaires composés
IOS_APPIUM_URL=http://127.0.0.1:4723
IOS_APPIUM_COMMAND=appium
IOS_DEVICE_UDIDS=<udid-iphone-01>,<udid-iphone-02>
IOS_KNOWN_APPS_JSON={"Instagram":"com.burbn.instagram","TikTok":"com.zhiliaoapp.musically","Reddit":"com.reddit.Reddit","Safari":"com.apple.mobilesafari"}
```

Le secret du pont (`ofmai-farm-secret`) et la clé modèle (`ofmai-anthropic-key`) viennent du Trousseau, pas du `.env`.

## 2. Le premier iPhone : objectif du jour, un dump d'écran

1. Téléphone préparé selon `iphones.md` §3.1 (activé sans Apple ID, code dans le Trousseau, pas de profil de gestion, iOS à jour).
2. Câble Lightning sur le hub alimenté du Mac mini. Sur le téléphone : **« Se fier à cet ordinateur »**, code.
3. Réglages → Confidentialité et sécurité → **Mode développeur** → activer → redémarrage → confirmer.
4. Le Mac mini doit le voir :
   ```sh
   xcrun xctrace list devices        # l'iPhone apparaît avec son UDID → iphones.md §1
   ```
5. Signer WebDriverAgent une fois à la main (plus simple que de laisser Appium deviner) :
   ```sh
   open "$(appium driver list --installed --json | python3 -c 'import json,sys; print(list(json.load(sys.stdin).values())[0]["installPath"])')/node_modules/appium-webdriveragent/WebDriverAgent.xcodeproj"
   ```
   Dans Xcode : cible **WebDriverAgentRunner** → Signing & Capabilities → Team = le compte développeur → Product → Test sur l'iPhone. Première fois : sur le téléphone, Réglages → Général → VPN et gestion → faire confiance au développeur, puis relancer le Test. Quand l'écran de l'iPhone affiche « Automation Running », c'est gagné.
6. Appium dans un terminal qui reste ouvert : `appium --base-path /`
7. Le dump :
   ```sh
   cd ~/ofmai-farm && IOS_DEVICE_UDID=<udid> IOS_BUNDLE_ID=com.apple.mobilesafari \
     .venv/bin/python scripts/ios_safari_smoke.py --url https://ofmai.ai --screenshot-out data/ios_smoke.png
   ```
   Puis, serveur Ghost lancé (`python run.py`), `curl "http://localhost:5055/api/phone/devices?probe=deep"` doit montrer l'iPhone avec WDA, capture et arbre en vert.
8. Registre `iphones.md` : UDID, « Mode dév. : oui », « WDA : oui » + date. **Avant ce point, on n'achète pas le second iPhone.**

## 3. Ensuite, dans l'ordre

1. SIM du personnage, Wi-Fi coupé, Apple ID du personnage (`iphones.md` §3.3). Pour `iphone-01` l'Apple ID existe déjà (Léa Marchand) : y ajouter la ligne comme numéro de confiance, retirer celui de Nathan.
2. Instagram, TikTok, Reddit depuis l'App Store.
3. **Relevé des écrans iOS** : un dump par écran de chaque app, dans `screens-ios-<app>.md`, comme on l'a fait sur Android. Les skills `ofmai_*` sont écrits pour Android ; la couche iOS du fork (`gitd/bots/common/ios.py`, `elements_ios.yaml`) donne les primitives, le relevé donne les sélecteurs. Compter quelques jours par app.
4. Inscriptions par numéro, un réseau à la fois (`account-creation.md`), ledger le jour même.
5. Chauffe, avec le compositeur de commentaires branché (`FARM_OFMAI_BASE_URL`), et relecture des premiers commentaires dans l'admin OFMAI.

## 4. Ce qui ne change pas

Un téléphone qui tourne en data mobile uniquement ; les secrets dans le Trousseau du Mac mini et nulle part ailleurs ; aucun skill rejoué sur un vrai compte avant un passage complet sur un téléphone de test ; `ETAT.md` réécrit à chaque séance.
