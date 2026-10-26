@echo off
rem One-time setup on a new PC: installs MoneyPrinterTurbo (pinned version), applies the
rem Shorts Autopilot patch, writes env.bat and opens the app.
rem Needs: git and uv (https://docs.astral.sh/uv/) on PATH.
setlocal
set "HERE=%~dp0"
set "MPT_VERSION=v1.3.9"

if not exist "%HERE%env.bat" copy "%HERE%env.example.bat" "%HERE%env.bat" >nul
call "%HERE%env.bat"
echo MoneyPrinterTurbo folder: %MPT_DIR%
echo (edit env.bat first if you want it somewhere else)
echo.

where git >nul 2>&1 || (echo git is missing. Install it from https://git-scm.com & pause & exit /b 1)
where uv  >nul 2>&1 || (echo uv is missing. Install it: powershell -c "irm https://astral.sh/uv/install.ps1 | iex" & pause & exit /b 1)

if not exist "%MPT_DIR%\app\services\material.py" (
    echo Downloading MoneyPrinterTurbo %MPT_VERSION% ...
    git clone --depth 1 --branch %MPT_VERSION% https://github.com/harry0703/MoneyPrinterTurbo.git "%MPT_DIR%" || (pause & exit /b 1)
)

echo Installing Python 3.11 and MoneyPrinterTurbo's packages (a few minutes the first time) ...
pushd "%MPT_DIR%"
uv python install 3.11 || (popd & pause & exit /b 1)
uv sync --frozen || (popd & pause & exit /b 1)

echo Applying the Shorts Autopilot patch ...
findstr /c:"local edit: real footage only" app\services\material.py >nul && (
    echo Patch already applied.
) || (
    git apply "%HERE%patches\mpt-material.patch" || echo WARNING: patch did not apply. See README, section "MPT patch".
)
popd

echo.
echo Done. Opening Shorts Autopilot - finish the Setup tab (keys, Upload-Post, schedule).
call "%HERE%Shorts Autopilot.bat"
endlocal
