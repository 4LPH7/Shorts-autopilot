# Registers a Windows task that runs the automation (hidden, through run_hidden.pyw) at each time below, every day.
#   powershell -ExecutionPolicy Bypass -File setup_schedule.ps1
# Times must match run_times in settings.json (the upload spacing is computed from them).
# Remove it later with:  Unregister-ScheduledTask -TaskName "MPT Daily Shorts"
param([string[]]$Times = @("09:00", "19:00"))
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "task_common.ps1")

$trigger = $Times | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }
Register-ScheduledTask -TaskName "MPT Daily Shorts" -Action (New-RunAction) -Trigger $trigger `
    -Settings (New-RunSettings 3) -Description "Render Shorts for review and upload approved ones on schedule" -Force | Out-Null

Write-Host "Scheduled 'MPT Daily Shorts' every day at $($Times -join ', '). Logs: $PSScriptRoot\logs\daily.log"
