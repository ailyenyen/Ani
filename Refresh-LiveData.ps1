param([switch]$NoAlerts)

$ErrorActionPreference = 'Stop'
$refreshArguments = @('-X', 'utf8', (Join-Path $PSScriptRoot 'manage.py'), 'refresh_live')
if ($NoAlerts) { $refreshArguments += '--no-alerts' }
& (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') @refreshArguments
exit $LASTEXITCODE
