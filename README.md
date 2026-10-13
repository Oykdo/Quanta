# Quanta communautaire — pilote local

> **Coopérer librement, préserver le vivant, respecter chaque personne.**

Créateur déclaré : **jeremy zgonec**. Licence des nouvelles sources réseau :
**AGPL-3.0-only**, voir [NOTICE.md](NOTICE.md) et [LICENSE](LICENSE).

Dépôt de référence : **https://github.com/Oykdo/Quanta**.
Première version du pilote : **v0.1.0**, voir [CHANGELOG.md](CHANGELOG.md).

Ce projet expérimente un réseau d'entraide à crédit mutuel, avec autorisations
Ed25519, nonces persistants, allocation synthétique équilibrée et audit du
journal. LOCAL est une unité communautaire (1000 quanta entiers), sans mécanisme
de conversion fiduciaire, intérêt ou promesse de rendement.

## État vérifiable

- Ledger SQLite transactionnel et API limitée à `127.0.0.1`.
- Deux signatures par échange ; challenge signé pour lire un compte.
- Compteurs nonces persistants et répétitions idempotentes.
- Réserve de test et un seul versement primaire égal par clé inscrite.
- Catalogue, historique vérifié et topologie logique équilibrée de branches.
- Charte versionnée et empreinte signée lors de l'adhésion.
- Archives de provenance au nom déclaré, horodatage RFC 3161 optionnel.

Le pilote vérifié a distribué 1000 quanta à 1000 wallets synthétiques, avec
un débit de réserve correspondant et une somme des soldes égale à zéro.
Le coordinateur est encore unique ; les branches sont une topologie logique,
pas un consensus distribué déjà déployé. Une clé ne prouve pas l'unicité humaine.

## Installation reproductible

Python 3.12 et OpenSSL en ligne de commande sont utilisés pour les tests et les
horodatages. La partie réseau n'a pas besoin de PyTorch.

```powershell
python -m venv .venv-network
.\.venv-network\Scripts\python.exe -m pip install -r requirements-network.txt
.\.venv-network\Scripts\python.exe -B scripts/check.py
```

Un environnement existant, par exemple Miniforge, peut être utilisé s'il contient
déjà la dépendance nécessaire. Exécuter les commandes avec cet interpréteur ou
dans l'environnement virtuel activé.

## Premier essai

```powershell
python -B -m exchange.lab charter
python -B -m testnet run --wallets 100 --allocation 1000 --out testnet/results/pilote_100 --serve
```

Le dossier doit être neuf. Le port libre et la progression sont affichés.
Une autre fenêtre peut utiliser `testnet ping --url URL_AFFICHEE`. Ctrl+C
arrête proprement le pilote. Les signatures du simulateur sont celles de
propriétaires artificiels ; une vraie interface doit recueillir le consentement.

Guides : [testnet/GUIDE.md](testnet/GUIDE.md), [pilote LAN TLS](testnet/LAN.md), [exchange/GUIDE.md](exchange/GUIDE.md),
[provenance/GUIDE.md](provenance/GUIDE.md).

## Pérennité et équité

Un coffre chiffré peut conserver les clés synthétiques avec `--persist-wallets`.
La commande `testnet resume --ledger ... --vault ... --serve` reprend le pilote
avec les nonces du ledger et complète uniquement les allocations manquantes.
La passphrase est saisie localement. Le banc de simulation ne constitue pas un
service de garde des clés de participants réels.
La [gouvernance](GOVERNANCE.md) décrit les règles d'évolution, d'admission et de
distribution qui restent à valider collectivement. L'allocation technique par
clé est une étape de test ; elle ne suffit pas à une répartition équitable
entre personnes à l'échelle mondiale.

La progression prévue est : wallets persistants et reprise vérifiée, pilotage
par des propriétaires distincts, transport distant authentifié, puis réplication
et consensus éprouvé entre plusieurs validateurs. Les ressources réellement
offertes, la résolution des différends et la sobriété mesurée font partie du pilote.

## Contribution et publication

Voir [CONTRIBUTING.md](CONTRIBUTING.md) pour les tests et la revue des modifications,
[SECURITY.md](SECURITY.md) pour le signalement des défauts et
[PUBLICATION.md](PUBLICATION.md) pour la préparation du dépôt distant.

La sélection Git contient les sources publiques. Les données d'exécution, coffres, clés, copies
de provenance et environnements sont exclus de la sélection publique. Les
tests du réseau utilisent des données temporaires et un petit vecteur V1 public,
afin de fonctionner depuis un clone sans les résultats historiques locaux.
`python -B scripts/check_public.py` vérifie la sélection Git et exécute les tests
dans une copie temporaire des seules sources publiques. Les nouvelles sessions
de l'API fournissent une archive de ces sources à `/source`.

Le mode LAN ajoute TLS 1.3 mutuel et un client propriétaire avec consentement
local ; les commandes sont documentées dans `testnet/LAN.md`.
