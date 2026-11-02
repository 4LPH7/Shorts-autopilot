# Registers one-time upload tasks. Each runs "run_daily.bat --upload-next" once at its time:
# it posts the oldest approved video, respects the monthly quota, and never renders.
#   powershell -ExecutionPolicy Bypass -File schedule_uploads.ps1 -Times '2026-11-03 09:00','2026-11-03 19:00'
param([string[]]$Times)
$ErrorActionPreference = "Stop"

$bat = Join-Path $PSScriptRoot "run_daily.bat"
if (-not (Test-Path $bat)) { throw "run_daily.bat not found next to this script." }

foreach ($t in $Times) {
    $at = [datetime]::Parse($t)
    $name = "MPT Upload " + $at.ToString("yyyy-MM-dd HHmm")
    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$bat`" --upload-next" -WorkingDirectory $PSScriptRoot
    $trigger = New-ScheduledTaskTrigger -Once -At $at
    # Waits for a running render to finish (the engine waits up to an hour for the run lock).
    $settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -AllowStartIfOnBatteries `
                -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Host "Registered $name"
}
