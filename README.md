# Quanta Community Network

> **Cooperate freely, preserve the living world, respect every person.**

Quanta is an experimental community mutual-credit network. It combines signed
exchanges, a transactional ledger, owner consent and verifiable accounting.
Its purpose is to support useful cooperation between autonomous communities.

- **Declared creator:** jeremy zgonec
- **Repository:** https://github.com/Oykdo/Quanta
- **Pilot release:** [v0.1.0](https://github.com/Oykdo/Quanta/releases/tag/v0.1.0)
- **Network source license:** [AGPL-3.0-only](LICENSE), with attribution and scope
  described in [NOTICE.md](NOTICE.md).

## Contents

- [Capabilities and accounting](#capabilities-and-accounting)
- [Installation](#installation)
- [Start a local testnet](#start-a-local-testnet)
- [Access and inspect the ledger](#access-and-inspect-the-ledger)
- [Save wallets and resume](#save-wallets-and-resume)
- [Connect owner clients over mutual TLS](#connect-owner-clients-over-mutual-tls)
- [Wallets, authentication and nonces](#wallets-authentication-and-nonces)
- [API routes](#api-routes)
- [Tests and public source checks](#tests-and-public-source-checks)
- [Provenance and timestamps](#provenance-and-timestamps)
- [Governance and next milestones](#governance-and-next-milestones)
- [Detailed documentation](#detailed-documentation)

## Capabilities and accounting

- SQLite ledger with atomic debit/credit updates and a verifiable receipt chain.
- Ed25519 owner signatures; both parties authorize an exchange.
- Persistent operation nonces and idempotent retries.
- Equal primary allocations to the synthetic wallets listed in a test plan.
- Owner-signed account reads using single-use, expiring challenges.
- Wallet catalogue, verified histories and balanced logical branch plans.
- Versioned community charter whose fingerprint is signed when joining.
- Encrypted recovery vault for synthetic test wallets.
- TLS 1.3 mutual authentication for explicitly configured private-LAN listeners.
- Source archives and optional independently verified RFC 3161 timestamps.

**1 LOCAL = 1,000 integer quanta.** LOCAL is a community accounting unit. The
project provides no fiat-conversion mechanism, interest or promised investment
return. Each credit has a corresponding debit, so the sum of ledger balances
remains zero.

The verified 1,000-wallet test allocated 1,000 quanta per wallet, with a matching
reserve debit of 1,000,000 quanta. These were synthetic identities and test units.
The pilot currently has one coordinator. Branch plans describe logical peer
topology; distributed consensus is a separate development milestone. A public
key proves control of a key, not that its holder is a unique human.

## Installation

Use **Python 3.12**, Git and an OpenSSL command-line executable. The network
dependency is pinned in `requirements-network.txt`; PyTorch is not required
for the network pilot. Run commands from the repository root.

### Windows / PowerShell

```powershell
git clone https://github.com/Oykdo/Quanta.git
Set-Location Quanta
py -3.12 -m venv .venv-network
$Python = (Resolve-Path .\.venv-network\Scripts\python.exe).Path
& $Python -m pip install -r requirements-network.txt
& $Python -B scripts/check.py
```

### Linux / WSL / Bash

```bash
git clone https://github.com/Oykdo/Quanta.git
cd Quanta
python3.12 -m venv .venv-network
source .venv-network/bin/activate
python -m pip install -r requirements-network.txt
python -B scripts/check.py
```

On Ubuntu 24.04, install `python3-venv`, `git` and `openssl` if needed; its
default `python3` can be used instead of `python3.12`. An existing compatible
environment may also be used. In PowerShell, set `$Python` to its interpreter.
In Bash, use its activated `python` command. Never reuse a Windows virtual
environment inside WSL.

The PowerShell examples below use `$Python`. In another PowerShell window,
set that variable again from the repository root. For Bash, use `python` in
place of `& $Python` and forward-slash paths.

## Start a local testnet

Read the community charter and start 100 synthetic wallets:

```powershell
& $Python -B -m exchange.lab charter
& $Python -B -m testnet run --wallets 100 --allocation 1000 --out testnet/results/quickstart_100 --port 8765 --serve
```

Keep this terminal open. The API is available at `http://127.0.0.1:8765`.
Press **Ctrl+C** to stop it cleanly. Use a new output directory for each run.
The default port, when `--port` is omitted, is selected automatically and printed.

`--wallets` accepts 2 to 3,000 wallets. `--allocation` is an integer number of
quanta per wallet. The output quota defaults to **32,000,000 bytes** and can
be set with `--max-output-bytes`, up to 1,000,000,000 bytes. A larger experiment
may need a larger quota. Registration, distribution and verification progress
are displayed without requiring a separate Python process for each wallet.

The simulator signs with artificial client owners. Its automatic approvals
must not be interpreted as consent from real participants.

## Access and inspect the ledger

Open another terminal in the repository root:

```powershell
$Ledger = 'testnet/results/quickstart_100/ledger.sqlite3'
$Url = 'http://127.0.0.1:8765'
```

### Live service health

```powershell
& $Python -B -m testnet ping --url $Url
```

This returns the ledger identity, current head, event count, charter and aggregate
allocation statistics. `ping` is the loopback diagnostic client; authenticated
HTTPS wallet access uses `testnet.owner`, as described below.

### Verify the stored ledger

```powershell
& $Python -B -m testnet audit --ledger $Ledger
```

The audit verifies signatures and receipt ordering, reconstructs balances and
checks the primary-allocation index. It can inspect the persistent database
after the server has stopped.

### List wallets and inspect one history

```powershell
& $Python -B -m testnet wallets --ledger $Ledger --out testnet/results/quickstart_100/wallets.json
& $Python -B -m testnet trace --ledger $Ledger --account wallet-000001
& $Python -B -m testnet trace --ledger $Ledger --account reserve --offset 0 --limit 20
```

Use a wallet alias or its full public address. Aliases are deterministic within
that ledger, ordered by public address. A trace includes joining, incoming and
outgoing exchanges, control events, UTC dates, receipts, signatures, balances
and nonce progression. `--offset` and `--limit` paginate the history.

### Export a balanced logical branch plan

```powershell
& $Python -B -m testnet branches --ledger $Ledger --count 10 --out testnet/results/quickstart_100/branches.json
```

For 1,000 wallets and 10 branches, each branch contains 100 wallets. Each wallet
has five planned peers, giving 2,500 undirected links. The graph is checked for
connectivity, including removal of any single branch. This export plans peer
relationships; it does not deploy relays or create independent copies of balances.

Local `audit`, `wallets`, `trace` and `branches` commands are **operator views**
requiring filesystem access to the database. They are distinct from the
owner-authenticated account read exposed by the API. JSON exports contain no
private keys and must use new filenames.

### Output files

| File | Purpose |
|---|---|
| `ledger.sqlite3` | Accounts, signed receipts, allocation index and persistent nonces |
| `status.json` | Simulation progress, service URL and ledger identity |
| `report.json` | Initial allocation and verification results |
| `wallets.vault` | Optional encrypted synthetic-key recovery vault |
| `resume_status.json` | Result of a resumed session |
| `provenance/` | Local source snapshot and fingerprints for that milestone |

## Save wallets and resume

Stop the earlier loopback session, then start a new persistent synthetic pilot:

```powershell
& $Python -B -m testnet run --wallets 100 --allocation 1000 --out testnet/results/persistent_100 --port 8765 --persist-wallets --serve
```

The operator enters and confirms a passphrase locally. `wallets.vault` uses
AES-256-GCM with Scrypt-derived key material. It is bound to the ledger identity
and excluded from Git and provenance archives.

After stopping that session, resume it:

```powershell
& $Python -B -m testnet resume --ledger testnet/results/persistent_100/ledger.sqlite3 --vault testnet/results/persistent_100/wallets.vault --port 8765 --serve
```

Keys and addresses are restored; operation nonces come from the verified ledger.
Completed allocations are not repeated. Only missing registration or allocation
steps are completed. A paused account remains paused. The writer lock prevents
two processes from serving the same writable ledger concurrently.

This shared vault belongs to the **synthetic test harness**. Actual participants
keep their own keys on their own devices. Without a saved vault, an ephemeral
simulation remains auditable after shutdown, but its private keys cannot be
recreated from public addresses.

## Connect owner clients over mutual TLS

The LAN pilot uses an explicit private IPv4 listener, a verified server
certificate and mandatory wallet client certificates. Plain HTTP is allowed
only for the loopback simulator. The owner CLI works on Windows and Linux.

### Create a key and public certificate request on each client

```powershell
& $Python -B -m testnet.lan keygen --out testnet/results/client_a
```

On the other device, use a separate directory such as `client_b`. Send only
`wallet.public.json` and `wallet.csr` to the pilot administrator. Keep the
encrypted `wallet.key.pem` on its owner's device.

### Initialize the administrator's ledger and PKI

After receiving the two public documents, run on the server:

```powershell
& $Python -B -m testnet.lan init --out testnet/results/lan_pilot --public client_a.public.json client_b.public.json --server-ip 192.168.1.10 --allocation 1000
$LanLedger = 'testnet/results/lan_pilot/network/ledger.sqlite3'
$Pki = 'testnet/results/lan_pilot/pki'
& $Python -B -m testnet.lan issue --ledger $LanLedger --pki $Pki --csr client_a.csr --out client_a.crt
& $Python -B -m testnet.lan issue --ledger $LanLedger --pki $Pki --csr client_b.csr --out client_b.crt
& $Python -B -m testnet.lan serve --ledger $LanLedger --pki $Pki --host 192.168.1.10 --port 8443
```

Replace the example IP with the server's actual private address. The two
certificate output files must be new and their parent directory must exist.
Deliver each client its certificate, the public `ca.crt`, and the expected
ledger ID from `network.json`. Confirm the CA fingerprint and ledger identity
through the participants' agreed channel. The administrator's CA and server
private keys stay on the server.

### Read or join as a wallet owner

In PowerShell, define the common authenticated options on the client:

```powershell
$Owner = @('--url', 'https://192.168.1.10:8443', '--ledger-id', 'EXPECTED_LEDGER_ID', '--ca', 'ca.crt', '--certificate', 'client_a.crt', '--key', 'testnet/results/client_a/wallet.key.pem')
& $Python -B -m testnet.owner @Owner join --debt-limit 1000 --credit-limit 2000
& $Python -B -m testnet.owner @Owner state
```

For an equivalent Bash client, define an array instead:

```bash
Owner=(--url https://192.168.1.10:8443 --ledger-id EXPECTED_LEDGER_ID --ca ca.crt --certificate client_a.crt --key testnet/results/client_a/wallet.key.pem)
python -B -m testnet.owner "${Owner[@]}" join --debt-limit 1000 --credit-limit 2000
python -B -m testnet.owner "${Owner[@]}" state
```

Replace `EXPECTED_LEDGER_ID` and the credential paths with the received values.
Passphrases are requested locally; they are not sent to the ledger. Joining and
signing require the literal confirmation **`AUTORISER`** (authorize). Some CLI
prompts and linked guides currently remain in French.

### Prepare, cosign and submit an exchange

The recipient shares its public address and current operation nonce. The payer
prepares a proposal and signs it after reviewing its exact contents:

```powershell
& $Python -B -m testnet.owner @Owner propose --to RECIPIENT_ADDRESS --payee-nonce 1 --amount 100 --resource-id service --out proposal.json
& $Python -B -m testnet.owner @Owner sign --proposal proposal.json --out payer_approval.json
```

The recipient receives that public proposal and signs it with **its own**
connection options and key. Then either affected owner submits both approvals:

```powershell
& $Python -B -m testnet.owner @Recipient sign --proposal proposal.json --out recipient_approval.json
& $Python -B -m testnet.owner @Owner commit --authorizations payer_approval.json recipient_approval.json
```

Define `$Recipient` like `$Owner`, using the recipient's certificate and key,
or run its signing command on that recipient's separate device. In Bash, use
`"${Recipient[@]}"` with the corresponding array. Choose the current recipient
nonce, not the illustrative value `1`, if it differs.

Newly joined accounts start at zero. Primary grants use the same two-signature
workflow with the reserve as payer, the configured allocation amount, and the
exact `primary_resource` from `network.json`. For two owners receiving 1,000
quanta each, the reserve joins with debt limit 2,000 and credit limit zero.
The administrator uses `reserve.crt` and `reserve.key.pem` for that account.

If a proposal expires or a nonce changes, prepare a new proposal and obtain
new approvals. An identical committed request returns its original receipt;
a different request carrying stale nonces is rejected.

The [LAN guide](testnet/LAN.md) provides the full owner workflow. The
[Windows/WSL guide](testnet/WSL_WINDOWS.md) covers three-terminal operation and
public-file exchange between both environments. In normal WSL 2 NAT mode,
use the same explicit Windows LAN IP from both clients; Linux `localhost`
does not necessarily refer to Windows. The hostname or IP must match the
server certificate, and the server firewall must allow the selected pilot port.

## Wallets, authentication and nonces

| Component | Format | Role |
|---|---|---|
| Wallet address | 64 hexadecimal characters | SHA-256 of the raw Ed25519 public key |
| Public key | 32 bytes | Verify owner signatures |
| Private key | 32-byte secret | Sign locally; never stored in the ledger |
| Signature | 64 bytes | Authorize an exact message |
| Read challenge | Random nonce, one use, 60-second validity | Authenticate an account read |
| Operation nonce | Persistent integer per account | Reject stale exchange/control authorizations |

There is no separate "private address" to extract from the ledger. A local
passphrase protects private-key storage; the protocol authenticates signatures.
Each signed operation binds the ledger ID, participants, amount, nonces,
expiration and request ID. Mutual TLS adds peer authentication and encrypted
transport; it does not replace the two exchange signatures.

## API routes

| Route | Purpose | Access |
|---|---|---|
| `GET /health` | Ledger identity, charter, head and aggregate status | Loopback diagnostics or admitted TLS client |
| `GET /challenge/ADDRESS` | Obtain an expiring account-read challenge | Loopback simulator or admitted TLS client |
| `POST /account` | Read an account using the owner's signed challenge | Owner signature; matching client certificate in TLS mode |
| `POST /commit` | Submit an exact operation and its owner signatures | Required signatures; affected-owner TLS certificate in TLS mode |
| `GET /source` | Download the startup snapshot of public AGPL sources | Loopback simulator or admitted TLS client |

POST bodies contain exactly `payload` and `signatures`, use JSON and are limited
to 8,192 bytes. Concurrent connections are bounded. Local operator history
exports are CLI features, not unauthenticated HTTP history endpoints.

## Tests and public source checks

```powershell
& $Python -B scripts/check.py
& $Python -B scripts/check_public.py
```

The first command runs the network, charter, wallet, TLS and provenance checks.
The second verifies the Git selection and runs the checks in a temporary copy
containing only public sources. It requires a Git checkout. Tests use synthetic
keys, temporary data and a small public V1 compatibility fixture.

The v0.1.0 checks passed locally and on Windows/Linux GitHub Actions, including
missing/wrong client certificates, hostname validation, explicit consent,
nonce replay, concurrent writes, encrypted-vault recovery and unique allocation.

## Provenance and timestamps

```powershell
& $Python -B -m provenance create --author "jeremy zgonec"
& $Python -B -m provenance create --author "jeremy zgonec" --timestamp
& $Python -B -m provenance verify --proof PATH_TO_PROOF --require-timestamp
& $Python -B -m provenance stamp --proof PATH_TO_EXISTING_LOCAL_PROOF
```

Local snapshots contain a compressed source archive, a binary manifest and
SHA-256 fingerprints. Runtime datasets and ledgers are fingerprinted without
being duplicated. The optional RFC 3161 request sends only the record's hash
and a nonce to FreeTSA, then verifies the authority response. A local clock
date is reported separately from an independently verified timestamp.

The creator name is a declared attribution, not an identity certificate. The
proof establishes a fingerprint's existence at the attested time; legal
ownership and originality require their own supporting evidence.

## Governance and next milestones

The [community charter](exchange/CHARTE.md) sets the project's moral purpose.
[Governance](GOVERNANCE.md) describes collective admission, quotas, appeals,
dispute resolution and rule changes. Initial allocation equality by synthetic
key is a technical test, not proof of worldwide fairness between people.

Next milestones include owner-controlled pilots, measured availability and
energy use, independent validators, established distributed consensus and
verifiable inter-branch settlement. Credit limits and commitments must be
grounded in the resources actually offered by participants. Timing and file
size measurements do not substitute for energy or environmental-impact data.

## Detailed documentation

These companion documents currently use French; this README provides the
English entry point and ledger-access command reference.

- [Local testnet, recovery and wallet tracing](testnet/GUIDE.md)
- [Windows/Linux mutual-TLS LAN pilot](testnet/LAN.md)
- [Windows and WSL in parallel](testnet/WSL_WINDOWS.md)
- [Mutual-credit ledger and owner consent](exchange/GUIDE.md)
- [Moral charter and signed acceptance](exchange/CHARTE.md)
- [Source provenance and RFC 3161 verification](provenance/GUIDE.md)
- [Contribution guidelines](CONTRIBUTING.md)
- [Governance](GOVERNANCE.md)
- [Security reporting and current scope](SECURITY.md)
- [Git publication process](PUBLICATION.md)
- [Release history](CHANGELOG.md)

Git contains public network sources. Runtime data, vaults, keys, environments
and local proof archives are excluded. The historical neural laboratory kept
alongside the development workspace is outside this public network source tree;
see [NOTICE.md](NOTICE.md) for attribution and licensing scope.
