# Registers one-time upload tasks. Each runs "--upload-next" (hidden, through run_hidden.pyw) once at its time:
# it posts the oldest approved video, respects the monthly quota, and never renders.
#   powershell -ExecutionPolicy Bypass -File schedule_uploads.ps1 -Times '2026-11-03 19:00','2026-11-04 09:00'
param([string[]]$Times)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "task_common.ps1")

foreach ($t in $Times) {
    $at = [datetime]::Parse($t)
    $name = "MPT Upload " + $at.ToString("yyyy-MM-dd HHmm")
    # Waits for a running render to finish (the engine waits up to an hour for the run lock).
    Register-ScheduledTask -TaskName $name -Action (New-RunAction "--upload-next") -Trigger (New-ScheduledTaskTrigger -Once -At $at) `
        -Settings (New-RunSettings 2) -Force | Out-Null
    Write-Host "Registered $name"
}
