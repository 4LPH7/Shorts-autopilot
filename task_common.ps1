# Shared by setup_schedule.ps1 and schedule_uploads.ps1: how a scheduled run is started.

function Get-HiddenPython {
    $envFile = Join-Path $PSScriptRoot "env.bat"
    if (-not (Test-Path $envFile)) { Copy-Item (Join-Path $PSScriptRoot "env.example.bat") $envFile }
    $mpt = [regex]::Match((Get-Content $envFile -Raw), 'set\s+"MPT_DIR=([^"]*)"', 'IgnoreCase').Groups[1].Value
    $pyw = Join-Path $mpt ".venv\Scripts\pythonw.exe"
    if (-not (Test-Path $pyw)) { throw "pythonw.exe not found under '$mpt'. Run install.bat first." }
    return $pyw
}

# pythonw has no console, so there is no window to close; run_hidden.pyw starts run_daily.bat without one either.
# (A visible console window that got closed killed a run mid-upload on 2026-11-03.)
function New-RunAction([string]$RunArgs = "") {
    $launcher = Join-Path $PSScriptRoot "run_hidden.pyw"
    if (-not (Test-Path $launcher)) { throw "run_hidden.pyw not found next to this script." }
    New-ScheduledTaskAction -Execute (Get-HiddenPython) -Argument ("`"$launcher`" $RunArgs").Trim() -WorkingDirectory $PSScriptRoot
}

# WakeToRun wakes a sleeping PC. StartWhenAvailable runs late if the PC was off or asleep at the time.
# No "run only if the network is available": Microsoft doesn't say whether such a run waits or is skipped, and a skipped
# run would leave no trace in the log. Without it, an offline upload fails with a logged error and the video stays approved.
function New-RunSettings([int]$Hours) {
    New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours $Hours)
}
