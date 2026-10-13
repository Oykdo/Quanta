# Tester Windows et WSL en parallèle

## Architecture du test

```text
Terminal Windows A : serveur TLS + ledger SQLite
Terminal Windows B : propriétaire du wallet Windows
Terminal WSL       : propriétaire d'un autre wallet Linux
```

Le serveur conserve la base sur Windows. WSL utilise un clone Linux et sa propre
clé. Les deux clients contactent la même adresse HTTPS et vérifient le même
identifiant de ledger. Ce test valide deux environnements sur une machine,
pas une séparation physique de deux appareils.

## 0. Préparer WSL et l'espace disque

Dans PowerShell :

```powershell
wsl --list --verbose
wsl --status
```

Si aucune distribution n'est installée, il faut d'abord en installer une. Une
Ubuntu standard nécessite plusieurs Go une fois installée ; le budget des
fichiers du ledger n'est pas le budget de la machine virtuelle WSL. Avec moins
de 1 Go libre sur C:, choisir d'abord un emplacement disposant de suffisamment
d'espace ou libérer de l'espace explicitement.

Exemple d'installation, à exécuter après ce choix :

```powershell
wsl --install -d Ubuntu-24.04
```

La version Windows/WSL détermine les options d'emplacement proposées par
`wsl --help`. Terminer la création de l'utilisateur Linux et vérifier que la
distribution utilise WSL 2 avant de poursuivre.

## 1. Projet Windows et projet Linux

Dans Windows, ouvrir la racine de son projet. Exemple de variables (adapter
le chemin du clone et celui du Python existant) :

```powershell
$Repo = 'C:\chemin\Quanta'
$P = 'python'
Set-Location $Repo
$Base = 'testnet/results/windows_wsl'
```

Dans WSL/Ubuntu, conserver le clone dans le système de fichiers Linux :

```bash
sudo apt update
sudo apt install python3-venv git openssl
git clone https://github.com/Oykdo/Quanta.git "$HOME/Quanta"
cd "$HOME/Quanta"
python3 -m venv .venv-network
source .venv-network/bin/activate
python -m pip install -r requirements-network.txt
python -B scripts/check.py
```

Ne pas réutiliser un environnement virtuel Windows dans WSL.

## 2. Créer deux wallets indépendants

Windows :

```powershell
& $P -B -m testnet.lan keygen --out "$Base/windows_client"
```

WSL :

```bash
python -B -m testnet.lan keygen --out "$HOME/.local/share/quanta/wsl_client"
```

Chaque commande demande une passphrase locale. Les sorties sont distinctes.
La clé `wallet.key.pem` reste dans son environnement propriétaire.

## 3. Échanger seulement les documents publics

Sous WSL, adapter le chemin `/mnt/c/...` au clone Windows :

```bash
WIN_REPO='/mnt/c/chemin/Quanta'
CLIENT="$HOME/.local/share/quanta/wsl_client"
mkdir -p "$WIN_REPO/testnet/results/windows_wsl/linux_public"
cp "$CLIENT/wallet.public.json" "$WIN_REPO/testnet/results/windows_wsl/linux_public/"
cp "$CLIENT/wallet.csr" "$WIN_REPO/testnet/results/windows_wsl/linux_public/"
```

Copier uniquement la clé publique et le CSR, jamais la clé privée.

## 4. Initialiser le serveur et délivrer les certificats

Dans le terminal Windows administrateur du pilote, identifier l'adresse LAN
actuelle et choisir celle du serveur :

```powershell
Get-NetIPConfiguration
$HostIP = '192.168.1.48' # exemple, remplacer si nécessaire
& $P -B -m testnet.lan init --out "$Base/server" --public "$Base/windows_client/wallet.public.json" "$Base/linux_public/wallet.public.json" --server-ip $HostIP
$Db = "$Base/server/network/ledger.sqlite3"
$Pki = "$Base/server/pki"
& $P -B -m testnet.lan issue --ledger $Db --pki $Pki --csr "$Base/windows_client/wallet.csr" --out "$Base/windows_client/client.crt"
& $P -B -m testnet.lan issue --ledger $Db --pki $Pki --csr "$Base/linux_public/wallet.csr" --out "$Base/linux_public/client.crt"
Copy-Item "$Pki/ca.crt" "$Base/windows_client/ca.crt"
Copy-Item "$Pki/ca.crt" "$Base/linux_public/ca.crt"
Copy-Item "$Base/server/network.json" "$Base/linux_public/network.json"
```

Les commandes demandent la passphrase administrative. Elles utilisent un
dossier serveur neuf. Les certificats signés sont propres aux deux wallets.

Sous WSL, recevoir les trois fichiers publics :

```bash
cp "$WIN_REPO/testnet/results/windows_wsl/linux_public/client.crt" "$CLIENT/client.crt"
cp "$WIN_REPO/testnet/results/windows_wsl/linux_public/ca.crt" "$CLIENT/ca.crt"
cp "$WIN_REPO/testnet/results/windows_wsl/linux_public/network.json" "$CLIENT/network.json"
```

Vérifier l'identité du ledger et l'empreinte de la CA entre les terminaux.
Les clés `ca.key.pem`, `server.key.pem` et `reserve.key.pem` restent sur Windows.

## 5. Démarrer le serveur dans Windows A

```powershell
& $P -B -m testnet.lan serve --ledger $Db --pki $Pki --host $HostIP --port 8443
```

Garder ce terminal ouvert. Dans le mode NAT habituel de WSL 2, `localhost` côté
Linux ne désigne pas nécessairement le serveur Windows. Utiliser la même adresse
LAN explicite des deux côtés ; elle figure dans le certificat serveur.

Si le pare-feu bloque le test, autoriser TCP 8443 uniquement pour le programme
serveur et le réseau de test concernés. Le changement de règle appartient à
l'administrateur de la machine. Aucune redirection de port Internet n'est requise.
Un changement d'adresse DHCP demande un certificat avec la nouvelle adresse.

## 6. Paramétrer les deux clients

Dans Windows B, à la racine du projet :

```powershell
$P = 'python'
$Base = 'testnet/results/windows_wsl'
$Net = Get-Content "$Base/server/network.json" -Raw | ConvertFrom-Json
$Url = "https://$($Net.server_ip):8443"
$Win = @('--url', $Url, '--ledger-id', $Net.ledger_id, '--ca', "$Base/windows_client/ca.crt", '--certificate', "$Base/windows_client/client.crt", '--key', "$Base/windows_client/wallet.key.pem")
$Reserve = @('--url', $Url, '--ledger-id', $Net.ledger_id, '--ca', "$Base/server/pki/ca.crt", '--certificate', "$Base/server/reserve.crt", '--key', "$Base/server/reserve.key.pem")
```

Dans WSL, depuis le clone Linux et son environnement activé :

```bash
CLIENT="$HOME/.local/share/quanta/wsl_client"
LEDGER_ID=$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["ledger_id"])' "$CLIENT/network.json")
HOST_IP=$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["server_ip"])' "$CLIENT/network.json")
URL="https://$HOST_IP:8443"
Wsl=(--url "$URL" --ledger-id "$LEDGER_ID" --ca "$CLIENT/ca.crt" --certificate "$CLIENT/client.crt" --key "$CLIENT/wallet.key.pem")
```

## 7. Inscrire les propriétaires, puis lire les états

Windows B :

```powershell
& $P -B -m testnet.owner @Win join --debt-limit 1000 --credit-limit 2000
& $P -B -m testnet.owner @Reserve join --debt-limit 2000 --credit-limit 0
& $P -B -m testnet.owner @Win state
```

WSL :

```bash
python -B -m testnet.owner "${Wsl[@]}" join --debt-limit 1000 --credit-limit 2000
python -B -m testnet.owner "${Wsl[@]}" state
```

Chaque adhésion doit être confirmée avec `AUTORISER`. Initialement, les soldes
sont zéro et les nonces zéro. Les lectures signées n'incrémentent pas les
compteurs d'opération. Si Windows fonctionne et WSL échoue, commencer par
vérifier l'adresse, la portée du pare-feu et les certificats du client WSL.

## 8. Distribuer les deux allocations avec deux accords

Pour chacun des deux bénéficiaires, lire son adresse et son nonce dans `state`.
La réserve prépare un transfert de 1000 quanta avec la ressource exacte
`primary_resource` de `network.json`. Exemple pour Windows :

```powershell
$WinAddress = (Get-Content "$Base/windows_client/wallet.public.json" -Raw | ConvertFrom-Json).account_id
& $P -B -m testnet.owner @Reserve propose --to $WinAddress --payee-nonce 0 --amount 1000 --resource-id $Net.primary_resource --out "$Base/grant_win.json"
& $P -B -m testnet.owner @Reserve sign --proposal "$Base/grant_win.json" --out "$Base/grant_win_reserve.json"
& $P -B -m testnet.owner @Win sign --proposal "$Base/grant_win.json" --out "$Base/grant_win_owner.json"
& $P -B -m testnet.owner @Reserve commit --authorizations "$Base/grant_win_reserve.json" "$Base/grant_win_owner.json"
```

Pour WSL, après la première allocation et si son état indique encore nonce 0 :

```powershell
$WslAddress = (Get-Content "$Base/linux_public/wallet.public.json" -Raw | ConvertFrom-Json).account_id
& $P -B -m testnet.owner @Reserve propose --to $WslAddress --payee-nonce 0 --amount 1000 --resource-id $Net.primary_resource --out "$Base/grant_wsl.json"
& $P -B -m testnet.owner @Reserve sign --proposal "$Base/grant_wsl.json" --out "$Base/grant_wsl_reserve.json"
```

Le propriétaire WSL signe dans son terminal :

```bash
SHARED="$WIN_REPO/testnet/results/windows_wsl"
python -B -m testnet.owner "${Wsl[@]}" sign --proposal "$SHARED/grant_wsl.json" --out "$SHARED/grant_wsl_owner.json"
```

Windows remet les deux accords au ledger :

```powershell
& $P -B -m testnet.owner @Reserve commit --authorizations "$Base/grant_wsl_reserve.json" "$Base/grant_wsl_owner.json"
```

La réserve passe au nonce suivant après chaque grant. Les fichiers partagés
contiennent une proposition et des signatures, pas les clés des propriétaires.

Les propositions expirent après cinq minutes. Si elles expirent ou si un nonce
change, utiliser une nouvelle proposition et deux nouveaux accords, sans modifier
un fichier déjà signé ni écraser un export existant.

## 9. Échange Windows → WSL et audit

Après les allocations : Windows = 1000, WSL = 1000, réserve = -2000 quanta.
WSL communique son adresse et son nonce. Si les états indiquent bien nonce 1
pour chacun, Windows prépare un transfert de 100 quanta :

```powershell
& $P -B -m testnet.owner @Win propose --to $WslAddress --payee-nonce 1 --amount 100 --resource-id service --out "$Base/win_to_wsl.json"
& $P -B -m testnet.owner @Win sign --proposal "$Base/win_to_wsl.json" --out "$Base/win_to_wsl_win.json"
```

WSL confirme :

```bash
python -B -m testnet.owner "${Wsl[@]}" sign --proposal "$SHARED/win_to_wsl.json" --out "$SHARED/win_to_wsl_linux.json"
```

Windows soumet :

```powershell
& $P -B -m testnet.owner @Win commit --authorizations "$Base/win_to_wsl_win.json" "$Base/win_to_wsl_linux.json"
& $P -B -m testnet.owner @Win state
```

WSL vérifie depuis son environnement :

```bash
python -B -m testnet.owner "${Wsl[@]}" state
```

Résultat attendu : **Windows 900, WSL 1100, réserve -2000 ; somme zéro**.
Les deux compteurs passent de 1 à 2 après cet échange. Chaque client relit
son état indépendamment. Windows peut effectuer l'audit opérateur :

```powershell
& $P -B -m testnet audit --ledger "$Base/server/network/ledger.sqlite3"
```

Tester aussi une répétition exacte du `commit` : reçu identique, aucun deuxième
débit. Pour tester un nonce périmé, préparer une nouvelle requête avec l'ancien
compteur et vérifier le refus. Les tests automatisés couvrent également absence
de certificat, mauvaise autorité et certificat incompatible avec le propriétaire.

## Portée de la validation

Noter versions Windows/WSL/Linux, identifiant du ledger, empreintes CA et reçus,
résultats des lectures sur les deux clients et l'audit final. L'absence de
distribution WSL empêche un essai réel dans WSL : les tests CI Windows/Linux
validés séparément ne remplacent pas cette vérification locale en parallèle.

Conserver les clés chiffrées dans leurs environnements propriétaires, la base
sur le serveur et des copies de sauvegarde choisies. Ne pas exécuter deux
écrivains sur la même base ; les dossiers Linux et Windows contiennent deux
clients, pas deux copies concurrentes du solde commun.
