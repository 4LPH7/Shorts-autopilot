# Registers a Windows task that runs run_daily.bat at each time below, every day.
#   powershell -ExecutionPolicy Bypass -File setup_schedule.ps1
# Times must match RUN_HOURS in daily_shorts.py (the upload spacing is computed from them).
# Remove it later with:  Unregister-ScheduledTask -TaskName "MPT Daily Shorts"
param([string[]]$Times = @("09:00", "19:00"))

$bat = Join-Path $PSScriptRoot "run_daily.bat"
if (-not (Test-Path $bat)) { throw "run_daily.bat not found next to this script." }

$action   = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$bat`"" -WorkingDirectory $PSScriptRoot
$trigger  = $Times | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }
# WakeToRun: wakes a sleeping PC. StartWhenAvailable: runs later if the PC was off at that time.
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable `
            -ExecutionTimeLimit (New-TimeSpan -Hours 3) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName "MPT Daily Shorts" -Action $action -Trigger $trigger `
    -Settings $settings -Description "Render Shorts for review and upload approved ones on schedule" -Force | Out-Null

Write-Host "Scheduled 'MPT Daily Shorts' every day at $($Times -join ', '). Logs: $PSScriptRoot\logs\daily.log"
