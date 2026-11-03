$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& "$PSScriptRoot\.venv\Scripts\python.exe" -X utf8 manage.py scrape --no-alerts
$weeklyResult = $LASTEXITCODE
& "$PSScriptRoot\.venv\Scripts\python.exe" -X utf8 manage.py sync_regions
if ($weeklyResult -ne 0 -or $LASTEXITCODE -ne 0) { exit 1 }
exit 0
