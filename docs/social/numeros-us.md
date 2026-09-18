# Numéros américains — la chaîne est validée

> **Statut** : vérifié de bout en bout le 2026-09-18
> **Répond à** : peut-on obtenir des numéros américains utilisables depuis l'étranger, et à quel prix

## 1. Ce qui était bloquant

Instagram exige un numéro à la création, TikTok l'exige juste après. Aucune des deux ne s'ouvre sans. La recherche documentaire laissait la question ouverte : Tello interdit explicitement l'activation hors des États-Unis, Mint l'interdit dans ses CGU, Google Fi impose un jour d'usage sur place — et **Ultra Mobile et US Mobile ne documentaient rien**, ni dans un sens ni dans l'autre.

## 2. Ce qui a été vérifié, en conditions réelles

**US Mobile accepte l'activation depuis l'étranger.** Une ligne a été activée depuis la **Thaïlande**, sans aucune présence aux États-Unis, et s'est enregistrée en itinérance sur le réseau local (AIS). Numéro obtenu : indicatif **415** (San Francisco), choisi pour correspondre au proxy du profil explorateur.

**Les SMS entrants arrivent en itinérance, sans acheter de module de roaming.** Deux cas observés :

1. un message de l'opérateur depuis un numéro long (888) ;
2. **le code de vérification de TikTok, envoyé depuis un numéro court** — et c'est celui qui comptait.

La crainte documentée — les SMS de numéros courts ne franchissent souvent pas les frontières — **ne s'est pas matérialisée**. Les appels Wi-Fi étaient **désactivés** pendant tout le test : ils ne sont donc pas nécessaires chez cet opérateur, et la question de l'adresse d'urgence 911 ne se pose pas.

**La plateforme accepte le numéro.** TikTok l'a pris sans réserve, a envoyé le code, et le compte `@jordan.reed90` a été créé sur le profil explorateur.

## 3. Le coût

**10 $ par ligne et par mois**, sans engagement. Six lignes sur trois mois : **180 $**.

C'est plus cher que les 54 $ estimés pour Ultra Mobile PayGo, mais US Mobile a un avantage qu'aucune estimation ne remplace : **il fonctionne, c'est mesuré**. Ultra Mobile reste à tester si l'on veut descendre le coût ; ce n'est plus sur le chemin critique.

À comparer aux services de réception SMS : 15 à 30 $ pour six vérifications, mais 25 à 45 % d'échec sur Instagram **annoncés par les vendeurs eux-mêmes**, et des plages étiquetées `virtual` dans leurs propres API — exactement ce que teste un lookup de type de ligne. Un vrai numéro d'opérateur coûte dix fois plus et vaut la différence.

## 4. Ce qui reste à vérifier

- **Instagram** avec un numéro américain : jamais tenté. Le compte de l'explorateur est grillé pour ce test (il porte déjà un numéro français et a subi une suspension) — il faudra un profil GeeLark neuf.
- **Le partage d'un numéro entre plateformes** : un même numéro sert-il à la fois pour la boîte mail, Instagram et TikTok ? La contrainte « already taken » observée sur TikTok est interne à chaque plateforme, donc en principe oui, mais ce n'est pas mesuré.
- **Combien de profils eSIM actifs** simultanément sur un appareil : un iPhone en stocke huit mais n'en active que deux. Six lignes demandent donc trois appareils, ou des bascules manuelles — et un code expire en quelques minutes, donc le bon profil doit être actif au bon moment.

## 5. Conséquence sur le plan

Le goulot d'approvisionnement est levé. Un numéro par personnage ouvre **à la fois** la boîte mail et les plateformes : six lignes, pas douze, et on peut prendre de vraies adresses Gmail au lieu de se rabattre sur un fournisseur de second rang.
