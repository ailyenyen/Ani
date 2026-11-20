param(
    [datetime]$At = '07:00',
    [string]$TaskName = 'ANI Live Prices'
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') -PathType Leaf)) {
    throw 'Set up the ANI Python environment before registering the refresh.'
}

$refresh = Join-Path $PSScriptRoot 'Refresh-LiveData.ps1'
$taskShell = (Get-Command powershell.exe -ErrorAction Stop).Source
$action = New-ScheduledTaskAction -Execute $taskShell `
    -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -File "{0}"' -f $refresh) `
    -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description 'Import published ANI crop prices and evaluate price alerts.'
