# Dépôt Git local et future publication

Le dépôt Git doit avoir pour racine ce projet, et non le dossier utilisateur.
Vérifier `git rev-parse --show-toplevel` avant toute sélection de fichiers.

Le périmètre préparé est le réseau communautaire : `exchange/`, `testnet/`,
`provenance/`, `v2/storage.py`, documentation, dépendances et tests. Le laboratoire
neuronal historique garde son contexte local distinct. Les preuves binaires et
résultats peuvent être conservés localement ; la sélection Git exclut les
coffres, clés, bases, dumps et environnements.

## Contrôles préparatoires

```powershell
git rev-parse --show-toplevel
git status --short
git ls-files --others --exclude-standard
python -B scripts/check.py
python -B scripts/check_public.py
```

Le workflow CI proposé reproduit les tests sur Windows et Linux avec Python 3.12,
cryptography 49.0.0 et OpenSSL. Il ne transmet pas les preuves à une TSA pendant les tests.

## Dépôt choisi et publication

Le propriétaire a choisi **https://github.com/Oykdo/Quanta**, en visibilité
publique, pour la première version **v0.1.0** du pilote. Le compte distant
doit autoriser l'écriture du dépôt et la publication du workflow GitHub Actions.

Choisir la forge, le compte, le nom et le canal privé de signalement. Examiner
la sélection publique et le diff, puis créer le premier commit seulement après
cette demande. Sur GitHub, utiliser `gh auth login`, `gh auth status` et `gh repo
create` avec le compte et le nom effectivement choisis. Une URL publique réelle
pourra alors être renseignée dans la documentation et les notices du service.

L'attribution et les droits de réutilisation sont décrits dans NOTICE.md.
L'identité d'auteur du commit peut utiliser le nom déclaré jeremy zgonec et
l'adresse noreply du compte GitHub, sans modifier la configuration Git globale.
