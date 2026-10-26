@echo off
rem Opens the Shorts Autopilot app (no console window stays open).
set "HERE=%~dp0"
if not exist "%HERE%env.bat" copy "%HERE%env.example.bat" "%HERE%env.bat" >nul
call "%HERE%env.bat"
if not exist "%MPT_DIR%\.venv\Scripts\pythonw.exe" (
    echo MoneyPrinterTurbo was not found in %MPT_DIR%.
    echo Run install.bat first, or edit env.bat to point at your MPT folder.
    pause
    exit /b 2
)
start "" "%MPT_DIR%\.venv\Scripts\pythonw.exe" "%HERE%autopilot_gui.pyw"
