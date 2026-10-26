@echo off
rem One automation run (render for review / upload approved on schedule).
rem Task Scheduler calls this; the app's buttons call it too.
rem Flags: --dry-run  --render  --doctor  (see daily_shorts.py)

set "HERE=%~dp0"
if not exist "%HERE%env.bat" copy "%HERE%env.example.bat" "%HERE%env.bat" >nul
call "%HERE%env.bat"
if not exist "%HERE%logs" mkdir "%HERE%logs"
set "LOG=%HERE%logs\daily.log"

rem Same Python lookup order as MPT's own webui.bat
set "PY="
if exist "%MPT_DIR%\.venv\Scripts\python.exe" set "PY=%MPT_DIR%\.venv\Scripts\python.exe"
if not defined PY if exist "%MPT_DIR%\lib\python\python.exe" set "PY=%MPT_DIR%\lib\python\python.exe"
if not defined PY (
    echo [%date% %time%] No MPT Python found under %MPT_DIR%. Run install.bat first.>>"%LOG%"
    exit /b 2
)

cd /d "%MPT_DIR%"
set "PYTHONPATH=%MPT_DIR%"
set "PYTHONIOENCODING=utf-8"

rem --doctor prints its report to the console (the app reads it); everything else goes to the log
if /i "%~1"=="--doctor" (
    "%PY%" "%HERE%daily_shorts.py" --doctor
    exit /b %ERRORLEVEL%
)

rem The script writes daily.log itself (shared access), so overlapping runs can't lock it.
rem Only crashes before the script starts land in crash.log.
set "AUTOPILOT_LOG=%LOG%"
"%PY%" "%HERE%daily_shorts.py" %* 2>>"%HERE%logs\crash.log"
set "RC=%ERRORLEVEL%"
exit /b %RC%
