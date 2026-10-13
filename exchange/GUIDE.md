# Échanges locaux à crédit mutuel et consentement explicite

## Devise morale et finalité

> **Coopérer librement, préserver le vivant, respecter chaque personne.**

Le projet vise un réseau communautaire mondial d'entraide, fondé sur des
communautés autonomes. La [charte morale](CHARTE.md) fixe cette orientation.
La lecture de la charte est disponible sans charger le modèle sémantique :

```powershell
.\.venv\Scripts\python.exe -B -m exchange.lab charter
```

Les nouveaux registres V2 incluent la charte version 1. L'adhésion affichée par
le CLI exige son acceptation explicite ; la signature inclut son empreinte
`charter_hash`. L'audit expose la version et l'empreinte réellement inscrites.
Les registres historiques V1 restent valides et sont indiqués sans consentement
signé à la nouvelle charte. Voir `charter --ledger CHEMIN/ledger.json --json`.

## Choix économique

Ce prototype organise des échanges de biens et services dans une **coopérative
locale de crédit mutuel**, sans intérêts ni frais de protocole. Il facilite
l'utilisation de capacités disponibles lorsque la monnaie manque. Son utilité
dépend des biens, services et participants effectivement disponibles : un registre
ne crée ni ressources naturelles, ni production, ni pouvoir d'achat garanti.

Chaque crédit reçu a un débit exactement égal chez l'autre participant. Les
soldes commencent à zéro et leur somme reste zéro. La dette est une obligation
envers la communauté, réglable par des échanges ultérieurs. La coopérative fixe
des limites communes ; chaque propriétaire consent à ses limites personnelles,
qui peuvent être inférieures. Le plafond total de dette borne également
l'exposition de l'ensemble du groupe.

L'unité **LOCAL** est une unité de compte communautaire, divisible en **1000
quanta entiers**. Le projet ne prévoit aucune conversion en monnaie fiduciaire,
aucune parité avec l'euro et aucun adossement bancaire.
Les prix doivent être convenus entre les parties. Aucun taux d'intérêt, minage,
jeton spéculatif ou mécanisme de profit automatique n'est utilisé.

La configuration initiale propose 100 LOCAL de dette/crédit au maximum par compte,
1000 LOCAL de dette totale, 100 comptes et 1000 événements. Ce sont des paramètres
techniques de démonstration, pas une estimation économique des limites adaptées
à une population. Le consentement ne remplace pas une règle collective d'admission :
un identifiant cryptographique prouve une clé, **pas l'unicité d'une personne**.

## Ce qui est implémenté

- Signatures **Ed25519** standard, avec séparation de domaine et identité du registre.
- Deux signatures sur la même proposition pour chaque échange : payeur et fournisseur.
- Consentement explicite dans le CLI avant signature ; le propriétaire peut refuser.
- Charte morale versionnée, affichée et liée à la signature des nouvelles adhésions.
- Clés privées chiffrées par passphrase, conservées hors du registre.
- Limites de dette/crédit, de dette totale, de participants et de taille du journal.
- Montants entiers, sans arrondi monétaire flottant ; écritures débit/crédit atomiques.
- Compteurs par participant et expiration des autorisations (300 secondes par défaut).
- Pause/reprise signée du compte ; la pause invalide les autorisations en attente.
- Journal chaîné par empreintes, vérification des signatures et reconstruction des soldes.
- Vérification d'un reçu antérieur avec `--require-head` pour détecter son absence.
- Registre persistant avec écrivain unique, remplacement atomique et budget disque,
  y compris la copie temporaire. Par défaut **10 Mo** par dossier de registre,
  plafond configurable au maximum à **1 Go**.

Le coordinateur local vérifie et conserve le registre. Il ne reçoit aucune clé
privée et ne peut produire de nouvelle autorisation valide pour un participant.
Les propositions se transportent comme petits fichiers JSON entre propriétaires.
**Aucun port réseau, paiement bancaire ou transfert réel n'est lancé.**

Le rôle du réseau neuronal reste celui d'une interface sémantique future. Il
n'accorde aucun droit et ne possède aucune clé. Les échanges structurés se
vérifient avec des règles déterministes ; le prototype ne charge **pas PyTorch**.

## Environnement existant, sans installation

Depuis la racine du projet, utiliser Python 3.12 avec `cryptography==49.0.0`.
Un environnement Miniforge existant peut convenir :

```powershell
$python = 'python'
& $python -B -m exchange.lab --help
& $python -B -m exchange.lab demo --cycles 3
```

La démonstration fonctionne en RAM avec trois propriétaires synthétiques et des
clés éphémères. Elle ne représente pas des consentements de personnes réelles.
Chaque cycle échange une réparation, des produits et un prêt d'outil pour
1000 quanta chacun ; les trois soldes reviennent à zéro.

Pour conserver un exemple auditable dans un **nouveau** dossier :

```powershell
& $python -B -m exchange.lab demo --cycles 10 --out exchange/results/ma_demo
& $python -B -m exchange.lab audit --ledger exchange/results/ma_demo/ledger.json
```

Les clés éphémères de cette démonstration ne sont pas sauvegardées : les comptes
de démonstration ne permettent pas de nouvelles signatures après sa fin.
Le `.venv` historique reste utilisable pour les modèles sémantiques ; il ne
contient pas cette dépendance cryptographique.

## Créer un groupe de test et ses clés propriétaires

Les dossiers de sortie des clés et autorisations doivent déjà exister.
`exchange/results` est fourni. Les fichiers existants ne sont pas remplacés.

```powershell
& $python -B -m exchange.lab init --out exchange/results/mon_groupe
& $python -B -m exchange.lab keygen --out exchange/results/alice.pem
& $python -B -m exchange.lab keygen --out exchange/results/bob.pem
& $python -B -m exchange.lab join --ledger exchange/results/mon_groupe/ledger.json --key exchange/results/alice.pem
& $python -B -m exchange.lab join --ledger exchange/results/mon_groupe/ledger.json --key exchange/results/bob.pem
```

Chaque propriétaire saisit une passphrase, lit la charte et autorise lui-même
son adhésion et les limites personnelles qu'il accepte.
La passphrase n'est pas passée sur la ligne de commande. Conserver les identifiants
`account_id` retournés et le reçu d'adhésion. Vérifier l'identité du groupe et
ses conditions avec les autres participants avant d'y adhérer.

## Un échange bilatéralement autorisé

Remplacer `ID_ALICE` et `ID_BOB` par les identifiants retournés. Ici Alice reçoit
un service et doit 1,5 LOCAL à la communauté ; Bob reçoit un crédit de 1,5 LOCAL.

```powershell
& $python -B -m exchange.lab propose --ledger exchange/results/mon_groupe/ledger.json --payer ID_ALICE --payee ID_BOB --amount 1500 --resource-id repair --out exchange/results/proposition.json
& $python -B -m exchange.lab sign --ledger exchange/results/mon_groupe/ledger.json --key exchange/results/alice.pem --proposal exchange/results/proposition.json --out exchange/results/accord_alice.json
& $python -B -m exchange.lab sign --ledger exchange/results/mon_groupe/ledger.json --key exchange/results/bob.pem --proposal exchange/results/proposition.json --out exchange/results/accord_bob.json
& $python -B -m exchange.lab commit --ledger exchange/results/mon_groupe/ledger.json --authorizations exchange/results/accord_alice.json exchange/results/accord_bob.json
& $python -B -m exchange.lab audit --ledger exchange/results/mon_groupe/ledger.json
```

Les deux propriétaires voient le contenu exact et doivent saisir `AUTORISER`.
Toute autre réponse laisse la proposition non signée. Une autorisation expire
après cinq minutes par défaut ; un échange concurrent peut aussi rendre ses
compteurs obsolètes. Il faut alors produire une nouvelle proposition.

L'empreinte `hash` du reçu peut être conservée séparément et présentée lors des
opérations suivantes avec `--require-head EMPREINTE`. Le registre doit toujours
contenir ce reçu, éventuellement comme ancêtre d'échanges plus récents.

Pause ou reprise par le propriétaire :

```powershell
& $python -B -m exchange.lab control --ledger exchange/results/mon_groupe/ledger.json --key exchange/results/alice.pem --state pause
& $python -B -m exchange.lab control --ledger exchange/results/mon_groupe/ledger.json --key exchange/results/alice.pem --state resume
```

Une pause n'efface pas les dettes ni les échanges déjà enregistrés.

## Sobriété et mesures

Le CLI mesure le temps de création/signature/vérification/application **en RAM**,
le volume des autorisations et la taille du registre sauvegardé. Il ne mesure
ni joules, ni autonomie d'un appareil, ni coût carbone ou fabrication. La valeur
`energy_joules` reste donc `null`. Zéro frais de protocole ne signifie pas zéro
coût d'exploitation.

Il n'y a ni corpus supplémentaire, ni réentraînement, ni nouvelle installation.
Le registre conserve seulement des identifiants de clés, montants, ressources
opaques et preuves d'autorisation. Les clés chiffrées et fichiers d'accords ont
également un petit budget de dossier. Un journal plein ou un budget insuffisant
provoque un refus ; l'historique n'est pas supprimé pour continuer.

## Portée et garanties à développer

Ce prototype constitue un **groupe local à coordinateur de confiance**, pas un
consensus distribué mondial. Une empreinte seule ne protège pas contre le
remplacement de tout l'historique : des reçus conservés indépendamment servent
de points de comparaison. La tolérance aux coordinateurs malveillants demande
réplication, témoins et protocole de règlement supplémentaires.

Les signatures prouvent l'accord sur un message ; elles ne prouvent ni livraison
d'un bien, ni prix équitable, ni absence de défaut d'un participant. Les membres
doivent définir admission, prix, responsabilité, résolution des différends et
traitement des dettes ensemble. Aucun profilage de solvabilité n'est implémenté.
Les pseudonymes limitent les données stockées, mais ne rendent pas un historique
financier anonyme ; visibilité et durée de conservation doivent être choisies
par la communauté.

La clé déchiffrée existe en RAM pendant la signature. La protection d'un appareil
compromis, la récupération de clés, les garanties après coupure électrique et
une sécurité matérielle restent à traiter. Un répertoire `ledger.json.lock`
abandonné après un arrêt brutal doit être examiné avant intervention ; le CLI
ne le supprime pas arbitrairement.

Une future communication entre appareils pourra s'appuyer sur ACE-OAuth et
CoAP/OSCORE, avec authentification mutuelle et contrôles des deux sens. La
prochaine comparaison utile est **la même transaction autorisée**, avec/sans
interface sémantique, en mesurant aussi la radio, la veille et la persistance.
La mise en réseau publique et l'utilisation de valeur réelle nécessitent des
garanties supplémentaires ; aucun mécanisme ne promet zéro attaque possible.

## Tests

```powershell
& $python -B -m unittest discover -s exchange/tests -v
```

Les tests utilisent de vraies signatures dans des dossiers temporaires effacés
à la fin. Ils vérifient les consentements, expirations, rejeux, plafonds, pauses,
conservation des soldes, modifications du journal, écrivains concurrents,
échec de sauvegarde, chiffrement des clés et parcours CLI complet. Ils vérifient
également l'acceptation de la charte, le rejet des champs de conversion fiduciaire,
la détection d'une modification des engagements et la compatibilité historique.
