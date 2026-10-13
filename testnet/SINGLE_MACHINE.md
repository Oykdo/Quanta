# One-computer test without WSL

This harness runs on Windows with one small Python virtual environment. It
tests two distinct TLS wallet identities, a synthetic wallet batch and the
economic scenarios. It is one OS and one computer; a virtual environment is
dependency configuration, not a virtual machine or a security boundary.

## Disk budget

The lightweight setup uses **Python 3.12 and cryptography 49.0.0 already
installed in the base interpreter**. It enables `system-site-packages`, creates
no pip installation and downloads no dependency. Existing libraries are shared,
not copied. This measures additional space, not the size of Python already on
the machine or the historical neural environment.

The environment has a 64 MiB check. A run defaults to 128 MiB, partitioned
between its components; the accepted maximum is 512 MiB. Thus the configured
additional environment/run budgets stay below 800 MB–1 GB. Actual usage is
reported and should be much smaller for the defaults. No WSL installation,
Docker image, new PyTorch wheel or duplicate clone is needed.

The development Windows run measured **523,364 bytes** for the lite environment
and **688,594 bytes** for a 100-wallet, five-replication test run: about **1.21 MB
additional space** in total. This is an observed example, not the size of the
pre-existing interpreter and libraries. Source updates can slightly change it.

## Windows scripts

From the project root, point the setup to the existing interpreter:

```powershell
.\scripts\Setup-Lite.ps1 -BasePython 'C:\path\to\existing\python.exe'
```

On the development machine the existing Miniforge interpreter is suitable.
The script creates `.venv-lite` and verifies the dependency versions. Repeating
it reuses only an environment carrying the Quanta marker; an unrelated existing
directory is not overwritten. No automatic package installation is attempted.

Run the complete small test:

```powershell
.\scripts\Test-SingleMachine.ps1 -Wallets 100 -Replications 5 -MaxRunMiB 128
```

Optional full source checks before the harness:

```powershell
.\scripts\Test-SingleMachine.ps1 -Wallets 100 -Replications 5 -MaxRunMiB 128 -RunTests
```

For a larger synthetic wallet test, increase `-Wallets` up to 1000. `-Replications`
accepts 1..20 for the economic comparison. Start with the defaults rather than
spawning a separate virtual environment for every wallet.

## What runs

1. A loopback server with required TLS 1.3 client certificates.
2. Two synthetic client wallets and a reserve, with distinct keys/certificates.
3. Equal grants of 1000 quanta each and a 100-quanta A→B exchange.
4. Authenticated state reads and an audit: A=900, B=1100, reserve=-2000, sum=0.
5. The seven economic scenarios over 30 participants and 30 days.
6. A wallet batch checking primary allocation, exact retry and stale nonce refusal.

The server uses a background thread and clients use actual loopback HTTPS
requests in the same Python process. Synthetic keys and automatic approvals
are not real user consent. No pre-existing ledger is modified.

## Output and automated credentials

Each run creates a fresh `testnet/results/single_UTC_TIMESTAMP` directory:

- `single_report.json`: checks, identity paths, scenario summaries and disk figures.
- `transport/`: SQLite ledger, local PKI and encrypted simulation keys.
- `economic_inputs/` and `economic_reports/`: declared synthetic inputs and reports.
- `wallet_batch/`: batch ledger and a source-provenance pack.

An automated run uses a random passphrase kept only for that run. It is not
printed or saved, and the services stop after verification. The resulting
encrypted key files are historical test data, not recoverable owner wallets.

## Interactive mode with an operator-chosen passphrase

```powershell
.\scripts\Test-SingleMachine.ps1 -Wallets 100 -Replications 5 -MaxRunMiB 128 -Interactive
```

Choose and confirm a local passphrase. The loopback TLS server remains running
after verification; Ctrl+C stops it. Read the displayed path of `single_report.json`
in a second PowerShell terminal. It contains the URL, ledger ID, public CA path
and encrypted client-key paths. The passphrase is entered locally again for
each owner command, never sent in chat or on the command line.

Example for client A from another terminal at the project root:

```powershell
$Python = '.\.venv-lite\Scripts\python.exe'
$Report = Get-Content 'testnet/results/single_TIMESTAMP/single_report.json' -Raw | ConvertFrom-Json
$A = $Report.clients.client_a
$Options = @('--url', $Report.tls_url, '--ledger-id', $Report.ledger_id, '--ca', $Report.ca_certificate, '--certificate', $A.certificate, '--key', $A.key)
& $Python -B -m testnet.owner @Options state
```

For client B, use `$Report.clients.client_b`. The signing/commit commands in
the README apply with each client's own options and explicit approval. This
is still a synthetic test harness; real participants create and retain their
own keys independently.

## Direct Python command

PowerShell wrappers only launch existing Python commands. Without them:

```powershell
.\.venv-lite\Scripts\python.exe -B -m testnet.single --wallets 100 --replications 5 --max-run-mib 128
```

Use a fresh output directory with `--out PATH` if a fixed path is desired.
Do not delete older directories or keys automatically to make room; review
the reports and choose retention explicitly. The normal output directories,
virtual environment and encrypted test material are excluded from Git.
