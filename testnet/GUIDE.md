# Premier testnet local : nonce, connexion et distribution primaire

## Choix de ce pilote

Ce réseau de développement relie des wallets **synthétiques** à un ledger commun
par HTTP sur **127.0.0.1 uniquement**. Il utilise les signatures Ed25519, la charte
morale, les montants entiers et les règles de crédit mutuel existantes. Il n'a
aucune conversion fiduciaire. Le coordinateur est unique ; le consensus distribué
entre plusieurs validateurs reste une étape ultérieure.

SQLite conserve le journal et les compteurs de façon transactionnelle, avec
`synchronous=FULL`, journal de rollback et écrivain unique. Les écritures utilisent
des paramètres SQL. La base est limitée à un quart du quota du dossier et de
l'espace supplémentaire est réservé avant chaque écriture pour le journal de
rollback. Par défaut le dossier dispose de **32 Mo**, dans le plafond maximal
configurable de 1 Go. Les rapports et copies temporaires sont aussi comptés.

Le programme ne réentraîne pas de modèle, ne charge pas PyTorch et réutilise
`cryptography` déjà installé dans Python Miniforge.

## Deux nonces, deux rôles

1. **Challenge de lecture** : aléatoire, valable 60 secondes et utilisable une fois.
   Le wallet signe le challenge pour demander son état. Un challenge n'est pas
   une clé d'accès : la signature prouve le contrôle de la clé privée.
2. **Compteur d'opération** : entier persistant dans le ledger pour chaque wallet.
   Une opération doit utiliser exactement le compteur courant. Un échange
   accepté incrémente les compteurs des deux participants dans la même transaction.

La signature inclut l'identité du ledger, le montant, les parties, les compteurs,
la durée de validité et l'identifiant de requête. Une requête identique déjà
validée renvoie **le même reçu** ; elle ne débite pas une deuxième fois. Une
nouvelle requête avec un compteur périmé est refusée, même si elle est signée.

## Règle de distribution primaire

Pour **N wallets** et **Q quanta** par wallet :

- N wallets reçoivent chacun exactement +Q.
- Une réserve de test reçoit le débit correspondant : **−N × Q**.
- La somme des soldes reste zéro.
- La réserve et chaque bénéficiaire signent le transfert.
- L'index d'allocation impose un seul versement primaire par bénéficiaire.
- La ressource de distribution inclut l'empreinte du plan (participants et quota).
- La réserve peut effectuer uniquement ce versement primaire exact dans ce pilote.

Avec N=1000 et Q=1000, les wallets reçoivent +1 LOCAL chacun et la réserve
porte −1000 LOCAL. Il s'agit d'une **distribution fictive de test**, pas d'une
ressource réelle créée, d'une dette d'une personne ou d'un don financé en euros.
Une distribution communautaire réelle demanderait l'acceptation collective
de l'engagement de réserve et des ressources qui permettent de le régler.

Les wallets disposent d'un plafond positif de 2Q afin de pouvoir recevoir
ensuite un échange ; les plafonner à Q les bloquerait immédiatement après leur
allocation. Leur limite de dette personnelle vaut Q. L'admission est limitée à
la liste de clés synthétiques du plan. Ce mécanisme ne prouve pas l'unicité humaine.

## Lancer 1000 wallets

Depuis la racine du projet, avec l'environnement Python activé :

```powershell
$python = 'python'
& $python -B -u -m testnet run --wallets 1000 --allocation 1000 --out testnet/results/mon_testnet --serve
```

Le dossier doit être nouveau. Le port libre est choisi automatiquement et l'URL
est affichée. Le programme inscrit les wallets, réalise la distribution et audite
les comptes. Il teste aussi la lecture signée, une requête répétée et un ancien
compteur. Avec `--serve`, l'API reste active jusqu'à **Ctrl+C**. Sans cette option,
elle s'arrête après la vérification. `--wallets` accepte 2 à 3000 wallets.

Les clés artificielles restent dans les objets clients en RAM pendant le test ;
elles ne sont ni sauvegardées ni transmises à l'API. Après arrêt, les preuves
restent auditables et une nouvelle simulation utilise de nouvelles clés. Il n'y
a aucun endpoint d'export des clés ni commande distante de système d'exploitation.

Dans une autre fenêtre, avec l'URL effectivement affichée :

```powershell
& $python -B -m testnet ping --url http://127.0.0.1:PORT
& $python -B -m testnet audit --ledger testnet/results/mon_testnet/ledger.sqlite3
```

## API et SDK

| Route | Utilisation |
|---|---|
| `GET /health` | Identité du ledger, charte, hauteur et compteurs agrégés |
| `GET /challenge/IDENTIFIANT` | Challenge à signer pour lire ce wallet |
| `POST /account` | Lecture de son compte avec signature du challenge |
| `POST /commit` | Opération exacte avec les signatures des propriétaires |

Les POST n'acceptent que les champs `payload` et `signatures` en JSON, pour un
corps maximal de 8192 octets. Les connexions simultanées sont bornées à 16. La
lecture d'un solde exige une signature ; les statistiques de santé sont agrégées.

`testnet/client.py` fournit `Wallet`, `Client.join`, `Client.account_state`,
`Client.transfer` et `Client.submit`. Un client valide l'identité attendue du
ledger avant de signer. Les approbations du simulateur sont synthétiques : une
vraie interface propriétaire doit afficher les termes et recueillir le consentement.

HTTP en boucle locale est le transport de développement. Une connexion entre
appareils distants demandera transport authentifié et chiffré, enrôlement et
gestion des clés adaptés ; ce programme refuse les URL hors de 127.0.0.1.

## Résultats, contrôle et provenance

- `ledger.sqlite3` : journal binaire persistant, comptes, allocations et metadata.
- `status.json` : URL et progression de la simulation.
- `report.json` : distribution initiale, temps de commits HTTP et vérifications.
- `provenance/` : archive binaire de l'étape au nom de **jeremy zgonec**.

L'audit reconstruit les soldes à partir des signatures et vérifie l'index
d'allocation. Les temps de mesure incluent HTTP local et les commits SQLite,
contrairement au précédent benchmark en RAM. L'énergie reste non mesurée.

La distribution initiale est égale. L'échange de contrôle de 1 quantum effectué
ensuite change légitimement les soldes de deux wallets ; il ne remet pas en cause
l'égalité des versements primaires. La réserve conserve le débit total correspondant.

Pour horodater indépendamment cette nouvelle étape :

```powershell
.\.venv\Scripts\python.exe -B -m provenance stamp --proof testnet/results/mon_testnet/provenance
```

La base est inventoriée par empreinte, sans copie intégrale dans l'archive de
provenance. Si le réseau valide de nouveaux échanges, cette empreinte représente
le point de contrôle antérieur. Une nouvelle étape peut ensuite être archivée.

## Tests

```powershell
& $python -B -m unittest discover -s testnet/tests -v
```

Les tests couvrent signatures, allocation unique, compteurs après redémarrage,
répétition idempotente, challenge de lecture, écrivains concurrents, quota,
taille des messages et distribution CLI. Un lock abandonné après arrêt brutal
doit être examiné ; le programme ne supprime pas le lock d'un autre écrivain.

## Composition d'un wallet et authentification

Un wallet possède une paire **Ed25519**. La clé publique brute fait 32 octets,
soit 64 caractères hexadécimaux. L'adresse du compte est le SHA-256 de ces 32
octets publics, également représenté par 64 caractères hexadécimaux. Adresse
et clé publique sont donc deux valeurs distinctes de même longueur.

La clé privée est un secret de 32 octets à conserver côté propriétaire. Elle
sert à produire les signatures de 64 octets. Il n'existe pas d'« adresse privée »
séparée à rechercher dans le ledger. Le ledger conserve les clés publiques,
signatures, compteurs et reçus ; il ne conserve pas les clés privées.

L'authentification utilise la signature du message exact : domaine du protocole,
identité du ledger, parties, montant, compteurs, expiration et identifiant de
requête. La lecture en ligne du compte utilise un challenge aléatoire signé ;
les échanges consomment leurs compteurs persistants. Un mot de passe ou une
passphrase sert éventuellement à protéger un fichier de clé local, pas à
remplacer les signatures du protocole.

Les clés des wallets de simulation sont éphémères et restent dans les clients
simulés du processus de test. Après arrêt, leurs historiques peuvent être
vérifiés avec les clés publiques, mais les secrets ne peuvent pas être recréés
à partir des adresses. Pour des wallets durables, `exchange.lab keygen` propose
un fichier PKCS8 chiffré par passphrase ; sauvegarde et récupération doivent
être décidées par les propriétaires.

## Retrouver chaque wallet et ses reçus

L'explorateur est une vue locale d'opérateur sur le testnet synthétique. Il ouvre
SQLite en lecture seule et valide comptes, journal et allocations dans un même
snapshot. Il n'exporte aucune clé privée. Les alias `wallet-000001`, etc. sont
déterministes pour ce ledger, selon l'ordre des adresses publiques ; ils ne
sont pas des identités humaines.

```powershell
& $python -B -m testnet wallets --ledger CHEMIN/ledger.sqlite3 --out CHEMIN/wallets.json
& $python -B -m testnet trace --ledger CHEMIN/ledger.sqlite3 --account wallet-000001
& $python -B -m testnet trace --ledger CHEMIN/ledger.sqlite3 --account reserve --offset 0 --limit 20
```

Chaque trace contient l'adhésion, l'allocation, les entrées/sorties, les
changements de contrôle, leurs dates UTC, compteurs, empreintes et signatures.
Le solde et le nonce sont reconstruits depuis les événements et comparés au
compte. On peut rechercher une adresse complète au lieu d'un alias. Les exports
doivent utiliser un nom neuf ; ils ne sont pas publiés automatiquement sur l'API.
Une lecture de comptes de personnes réelles doit respecter leurs permissions et
leurs règles de confidentialité.

## Ramification équilibrée : un plan de pairs pour le même ledger

```powershell
& $python -B -m testnet branches --ledger CHEMIN/ledger.sqlite3 --count 10 --out CHEMIN/branches.json
```

Pour 1000 wallets et 10 branches, le plan répartit **100 wallets par branche**.
Chaque wallet a deux voisins dans sa branche et un lien vers la branche
précédente, suivante et opposée : **5 pairs logiques**, soit 2500 liens non
orientés. Le graphe reste connecté si l'une des branches est retirée dans la
simulation du graphe. Pour une population non divisible, les tailles des
branches diffèrent au maximum de un et les degrés sont exposés dans le rapport.

Les branches référencent le même `ledger_id` et le même `head`. Cette opération
organise les pairs ; elle ne crée pas de ledger concurrent et ne déplace aucun
solde. L'équilibre des allocations initiales reste distinct des soldes après
des échanges volontaires.

Le fichier décrit une **topologie logique proposée** : les connexions entre
appareils, relais, répliques et consensus ne sont pas déployés par cet export.
La perte du coordinateur unique bloque encore le testnet actuel. Un passage à
des branches physiques demandera des relais autorisés, des validateurs, des
certificats de finalité et un protocole interbranches empêchant les doubles
dépenses. Les déplacements entre branches devront conserver les nonces et les
engagements plutôt que copier un solde comme une nouvelle allocation.

## Coffre persistant et reprise du pilote

Pour une nouvelle simulation durable, demander un coffre chiffré :

```powershell
python -B -m testnet run --wallets 100 --allocation 1000 --out testnet/results/pilote_durable --persist-wallets --serve
```

La passphrase est saisie localement et confirmée, jamais passée sur la ligne de
commande. Le fichier `wallets.vault` utilise AES-256-GCM avec une clé dérivée par
Scrypt (sel aléatoire, n=32768, r=8, p=1). Il contient uniquement les clés de la
simulation, chiffrées et liées à l'identité du ledger. Il est exclu de Git et des
archives de provenance. Conserver sa sauvegarde chiffrée selon le choix de l'opérateur.

Après arrêt propre du premier processus :

```powershell
python -B -m testnet resume --ledger testnet/results/pilote_durable/ledger.sqlite3 --vault testnet/results/pilote_durable/wallets.vault --serve
```

Le programme vérifie le journal, déchiffre les clés et récupère les nonces du
ledger. Les allocations déjà enregistrées ne sont pas refaites. Si une inscription
ou distribution était incomplète, seules les étapes manquantes sont effectuées.
Un compte suspendu conserve sa suspension ; une opération devenue invalide reste
refusée. Le lock empêche de reprendre simultanément un ledger déjà servi.

Ce coffre central concerne exclusivement le banc d'essai synthétique. Pour des
participants réels, chaque propriétaire doit conserver ses clés sur son appareil.
Les anciennes simulations sans coffre gardent leurs preuves publiques, mais leurs
clés éphémères ne peuvent pas être restaurées après arrêt.

## Sources et licence

Les nouvelles sessions affichent la licence AGPL-3.0-only dans `/health` et
proposent `/source`, une archive des seules sources publiques capturée au démarrage
du serveur. Elle comprend les notices, tests et scripts, sans coffre, clé, base ou
corpus. `python -B -m testnet legal` affiche l'attribution et l'emplacement du texte
de licence. La licence et la charte morale sont décrites séparément dans NOTICE.md.
