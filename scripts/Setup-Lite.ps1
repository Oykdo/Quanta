param(
    [string]$BasePython = 'python'
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath $Root)) { throw 'Project root missing' }
& $BasePython -B "$PSScriptRoot\setup_lite.py" --out "$Root\.venv-lite"
if ($LASTEXITCODE -ne 0) { throw 'Lightweight environment setup failed' }
"Ready: $Root\.venv-lite\Scripts\python.exe"
