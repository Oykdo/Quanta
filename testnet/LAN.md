# Pilote Windows/Linux avec certificats propriétaires et TLS mutuel

Ce pilote utilise TLS 1.3 avec certificat serveur vérifié et certificat client
obligatoire. Le certificat client porte la clé publique Ed25519 du wallet :
le serveur limite les opérations à un propriétaire concerné par le message.
Les signatures des deux parties, les nonces et les règles du ledger restent
nécessaires. Les unités du pilote restent des unités de test.

Les commandes s'exécutent depuis un clone du dépôt, avec Python 3.12 et
`cryptography==49.0.0` installé. `python` peut être remplacé par le chemin de
l'interpréteur choisi. Sur Windows, les chemins et lignes restent compatibles
avec PowerShell ; sur Linux, utiliser les mêmes arguments avec `python3`.

## 1. Chaque propriétaire crée sa clé SUR son appareil

```text
python -B -m testnet.lan keygen --out testnet/results/mon_client
```

Une passphrase est demandée localement. Le dossier contient :

- `wallet.key.pem` : clé privée chiffrée, conservée par son propriétaire ;
- `wallet.public.json` : identité publique à transmettre à l'administrateur ;
- `wallet.csr` : demande de certificat signée, également publique.

Créer deux clients distincts (par exemple Windows et Linux). Transmettre seulement
les deux documents publics et les CSRs à l'administrateur, par un canal convenu.
Le protocole d'admission ne constitue pas une preuve d'unicité humaine.

## 2. L'administrateur initialise le ledger et l'autorité locale

Choisir l'adresse LAN du serveur (exemple : 192.168.1.10) :

```text
python -B -m testnet.lan init --out testnet/results/lan_pilote --public client_windows.public.json client_linux.public.json --server-ip 192.168.1.10
```

La passphrase administrative protège la clé de l'autorité, celle du serveur et
le wallet de réserve. Les clients gardent leurs propres clés. `network.json`
donne l'identité du ledger, le plan d'allocation et la ressource de distribution.

Signer chaque CSR admis :

```text
python -B -m testnet.lan issue --ledger testnet/results/lan_pilote/network/ledger.sqlite3 --pki testnet/results/lan_pilote/pki --csr client_windows.csr --out client_windows.crt
python -B -m testnet.lan issue --ledger testnet/results/lan_pilote/network/ledger.sqlite3 --pki testnet/results/lan_pilote/pki --csr client_linux.csr --out client_linux.crt
```

Remettre à chaque propriétaire son certificat, le certificat public `pki/ca.crt`
et l'identifiant du ledger. Vérifier cette identité et l'empreinte du certificat
CA par un canal convenu. Les fichiers `ca.key.pem` et `server.key.pem` restent
chez l'administrateur. Les certificats clients et serveur sont valables 30 jours
dans ce pilote ; leur renouvellement et révocation doivent être organisés.

## 3. Démarrer le serveur LAN

```text
python -B -m testnet.lan serve --ledger testnet/results/lan_pilote/network/ledger.sqlite3 --pki testnet/results/lan_pilote/pki --host 192.168.1.10 --port 8443
```

Le programme écoute l'adresse privée explicitement choisie. Il n'accepte pas
de listener LAN en HTTP non chiffré. Le pare-feu du serveur doit autoriser ce
port uniquement pour le réseau pilote choisi ; aucune redirection Internet
n'est nécessaire. Ctrl+C arrête proprement le serveur.

## 4. Inscription et état depuis chaque appareil

Utiliser les options suivantes avant chaque sous-commande propriétaire :

```text
python -B -m testnet.owner --url https://192.168.1.10:8443 --ledger-id ID_DU_LEDGER --ca ca.crt --certificate mon_client.crt --key testnet/results/mon_client/wallet.key.pem join --debt-limit 1000 --credit-limit 2000
```

Le propriétaire lit la charte et les conditions, puis saisit `AUTORISER`.
La réserve utilise ses propres fichiers (`reserve.crt`, `reserve.key.pem`) et
s'inscrit avec une limite de dette de N×1000 et une limite de crédit de zéro.

Remplacer `join ...` par `state` pour une lecture authentifiée du compte :
le challenge est signé localement. Aucun mot de passe n'est transmis au serveur.

## 5. Deux propriétaires autorisent le même échange

Le destinataire communique son adresse et son nonce actuel. Avec les mêmes
options de connexion, le payeur utilise :

```text
... propose --to ADRESSE_DESTINATAIRE --payee-nonce NONCE_DESTINATAIRE --amount 100 --resource-id service --out proposition.json
... sign --proposal proposition.json --out accord_payeur.json
```

Le destinataire reçoit la proposition et signe depuis son appareil :

```text
... sign --proposal proposition.json --out accord_destinataire.json
```

Un des deux propriétaires remet les deux accords au ledger :

```text
... commit --authorizations accord_payeur.json accord_destinataire.json
```

Le CLI affiche le montant et les parties avant signature. Une approbation
refusée ne crée pas de signature. La distribution primaire suit le même
parcours avec le wallet de réserve comme payeur, 1000 quanta par bénéficiaire
et la `primary_resource` exacte de `network.json`. Elle n'est pas exécutée
automatiquement au nom de propriétaires réels.

## Publication et périmètre

Sources prévues : https://github.com/Oykdo/Quanta, sous AGPL-3.0-only.
Les sources du serveur sont également proposées à `/source` aux clients admis.
Les clés, certificats d'exécution, bases et accords individuels restent exclus
de Git. Le transport authentifie les clés inscrites ; la gouvernance, l'admission,
les droits de recours et la réplication entre validateurs restent des responsabilités
distinctes du transport. Ce pilote conserve un coordinateur unique.
