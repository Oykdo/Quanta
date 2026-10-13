param(
    [int]$Wallets = 100,
    [int]$Replications = 5,
    [int]$MaxRunMiB = 128,
    [switch]$Interactive,
    [switch]$RunTests
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Python = "$Root\.venv-lite\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { throw 'Run Setup-Lite.ps1 first' }
if (-not (Test-Path -LiteralPath "$Root\testnet\results")) { throw 'Test output parent missing' }
if ($RunTests) {
    $Tests = Start-Process -FilePath $Python -WorkingDirectory $Root -ArgumentList @('-B', 'scripts/check.py') -Wait -PassThru -NoNewWindow
    if ($Tests.ExitCode -ne 0) { throw 'Network tests failed' }
}
$ArgsList = @('-B', '-m', 'testnet.single', '--wallets', "$Wallets", '--replications', "$Replications", '--max-run-mib', "$MaxRunMiB")
if ($Interactive) { $ArgsList += '--interactive' }
$Run = Start-Process -FilePath $Python -WorkingDirectory $Root -ArgumentList $ArgsList -Wait -PassThru -NoNewWindow
if ($Run.ExitCode -ne 0) { throw 'Single-machine test failed' }
