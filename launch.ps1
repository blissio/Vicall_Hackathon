$ErrorActionPreference = 'Stop'
$appRoot = $PSScriptRoot
$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (Test-Path -LiteralPath $bundledPython) {
    & $bundledPython (Join-Path $appRoot 'app.py') @args
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        Write-Host 'Python 3.10 or newer is required. Install Python, then run python app.py.'
        exit 1
    }
    & $pythonCommand.Source (Join-Path $appRoot 'app.py') @args
}
exit $LASTEXITCODE
