# Provenance de la création — jeremy zgonec

Le nom déclaré du créateur de ce projet est **jeremy zgonec**, conformément à sa
demande. Chaque étape peut être conservée dans un dossier neuf, daté en UTC et
vérifiable. Les binaires servent à conserver un état et détecter une altération ;
ils ne rendent pas le code impossible à copier et ne constituent pas un brevet.

## Contenu d'un dossier de preuve

- `creation.zip` : archive binaire compressée des sources et modèles sélectionnés.
- `creation.bin` : conteneur binaire versionné du manifeste avec longueur et SHA-256.
- `manifest.json` : nom déclaré, date UTC de l'horloge locale, chemins, tailles et
  empreintes des fichiers, empreinte de l'archive.
- `SHA256SUMS.txt` : empreintes lisibles des trois fichiers principaux.

Les modèles `.pt` sont déjà binaires. Les données et journaux sont inventoriés
par empreinte, sans dupliquer le corpus. La sélection n'archive pas les clés
privées, environnements virtuels et caches. Le quota est de **10 Mo par dossier
parent de preuves** par défaut, partagé par les étapes qui y sont conservées.
Choisir un dossier de sortie neuf ; aucun dossier de preuve n'est remplacé.

Depuis la racine du projet, avec un environnement Python approprié :

```powershell
.\.venv\Scripts\python.exe -B -m provenance create --author "jeremy zgonec"
.\.venv\Scripts\python.exe -B -m provenance verify --proof CHEMIN_DU_DOSSIER
```

`verify --project-root .` vérifie aussi les fichiers actuels du projet. Une
différence peut indiquer une évolution depuis l'étape archivée ; elle ne rend pas
la copie historique invalide. Les données seulement inventoriées doivent rester
disponibles pour vérifier leur contenu ou les restaurer.

## Date indépendante : RFC 3161

```powershell
.\.venv\Scripts\python.exe -B -m provenance create --author "jeremy zgonec" --timestamp
.\.venv\Scripts\python.exe -B -m provenance verify --proof CHEMIN_DU_DOSSIER --require-timestamp
```

L'option `--timestamp` transmet uniquement le SHA-256 du conteneur binaire et
un nonce à `https://freetsa.org/tsr`. Les sources, poids et le nom en clair ne
sont pas transmis. La réponse et les preuves publiques sont conservées :

- `timestamp.tsq` : requête RFC 3161 binaire.
- `timestamp.tsr` : réponse signée binaire de l'autorité FreeTSA.
- `freetsa_ca.pem` : certificat public de l'autorité, dont l'empreinte est épinglée.
- `timestamp.json` : résultat de vérification et date UTC de l'autorité.

OpenSSL vérifie le nonce, la signature et sa chaîne de certificats, puis vérifie
séparément que la réponse correspond à `creation.bin`. Un échec reste un échec :
le CLI ne transforme pas une date locale en date indépendante vérifiée.
Le service et son certificat font partie des hypothèses de confiance. Le
certificat doit conserver une empreinte confirmée indépendamment ; une mise à
jour d'autorité ne doit pas être acceptée en remplaçant aveuglément le certificat.

OpenSSL déjà installé dans Miniforge est utilisé. `provenance/openssl.cnf` est
une configuration locale au processus lancé, avec le fournisseur cryptographique
standard. La commande de lecture/vérification locale n'a besoin ni de PyTorch
ni de nouvelle installation.

Pour ajouter une date indépendante à un dossier local existant :

```powershell
.\.venv\Scripts\python.exe -B -m provenance stamp --proof CHEMIN_DU_DOSSIER
```

Le nom dans le manifeste est une **attribution déclarée**, pas une vérification
d'identité civile. L'horodatage établit l'existence de l'empreinte au moment
attesté ; l'originalité, la titularité des droits et une protection juridique
particulière demandent d'autres éléments. Un dépôt approprié, par exemple e-Soleau
auprès de l'INPI, peut compléter ce dossier selon le besoin.

## Étapes d'entraînement futures

`v2.lab train` crée désormais un dossier de provenance local à la fin de chaque
entraînement, au nom de **jeremy zgonec**. Il contient les sources et les modèles
de cette session, dans le budget de sortie déjà appliqué. Exemple :

```powershell
.\.venv\Scripts\python.exe -B -m v2.lab train --out v2/results/nouvelle_etape --seeds 11 --compact --stamp-author "jeremy zgonec"
```

Le dossier est `v2/results/nouvelle_etape/provenance`. L'horodatage indépendant
se demande ensuite avec `provenance stamp`. Aucun appel réseau n'est effectué
automatiquement lors de l'entraînement. `--no-provenance` permet de désactiver
la copie locale pour une expérience technique particulière.

Conserver ensemble archive, manifeste, conteneur et réponse RFC 3161, avec une
copie indépendante choisie par le propriétaire. De nouvelles étapes peuvent
nécessiter une nouvelle attestation pour une conservation à long terme.
