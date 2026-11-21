param([switch]$NoAlerts, [switch]$Monthly)

$ErrorActionPreference = 'Stop'
$refreshArguments = @('-X', 'utf8', (Join-Path $PSScriptRoot 'manage.py'), 'refresh_live')
if ($NoAlerts) { $refreshArguments += '--no-alerts' }
if ($Monthly) { $refreshArguments += '--monthly' }
& (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') @refreshArguments
exit $LASTEXITCODE
