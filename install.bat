@echo off
rem One-time setup on a new PC: installs MoneyPrinterTurbo (pinned version),
rem writes env.bat and opens the app.
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
rem The app's interface (uv sync removes extra packages, so re-add it every time)
uv pip install --python .venv\Scripts\python.exe customtkinter==5.2.2 || (popd & pause & exit /b 1)

popd

echo.
echo Setting up the narration tools (voices, speech check) in their own environment, .venv-audio ...
pushd "%HERE%"
if not exist ".venv-audio\Scripts\python.exe" (uv venv .venv-audio --python 3.11 || (popd & pause & exit /b 1))
uv pip install --python .venv-audio\Scripts\python.exe kokoro-onnx soundfile faster-whisper edge-tts numpy || (popd & pause & exit /b 1)
if not exist "models\kokoro" mkdir "models\kokoro"
if not exist "models\kokoro\kokoro-v1.0.onnx" (
    echo Downloading the Kokoro voice model, about 350 MB ...
    curl -L --fail -o "models\kokoro\kokoro-v1.0.onnx" https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx || (popd & pause & exit /b 1)
    curl -L --fail -o "models\kokoro\voices-v1.0.bin" https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin || (popd & pause & exit /b 1)
)
echo Downloading the Whisper speech model, about 460 MB ...
.venv-audio\Scripts\python.exe -c "from faster_whisper import download_model; download_model('small.en', cache_dir='models/hf')" || (popd & pause & exit /b 1)
popd

echo.
echo Setting up the long-video renderer (HyperFrames, needs Node.js 22 or newer) ...
where node >nul 2>&1 && (
    pushd "%HERE%longform"
    call npm install --ignore-scripts --no-audit --no-fund
    popd
) || echo Node.js was not found: the Long video page needs it (https://nodejs.org). Everything else works without it.

echo.
echo Done. Opening Shorts Autopilot - finish the Setup tab (keys, Upload-Post, schedule).
call "%HERE%Shorts Autopilot.bat"
endlocal
