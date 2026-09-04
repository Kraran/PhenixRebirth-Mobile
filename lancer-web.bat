@echo off
setlocal
cd /d "%~dp0"
set PORT=8765
echo.
echo  Pack + patch snd OFF + repo local
echo  URL : http://localhost:%PORT%/
echo.

for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8000 :8765" ^| findstr LISTENING') do taskkill /F /PID %%P >nul 2>&1

if exist "assets\music\*.mp3" move /Y "assets\music\*.mp3" "%TEMP%\phenix-audio-pc\" >nul 2>&1
if exist "assets\sounds\*.wav" move /Y "assets\sounds\*.wav" "%TEMP%\phenix-audio-pc\" >nul 2>&1

python -m pip install "pygbag==0.9.2" >nul
if exist build rd /s /q build
python -m pygbag --build --PYBUILD 3.11 --ume_block 0 --cdn https://pygame-web.github.io/archives/0.8/ --version 0.8 --title "Phenix Rebirth Mobile" --app_name phenixrebirth --package org.kraran.phenixrebirth.mobile --width 1280 --height 720 .
if errorlevel 1 goto fail
if not exist "build\web\index.html" goto fail

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0patch-index.ps1"

if exist "archives\repo\pkg\*.whl" (
  mkdir "build\web\archives\repo\pkg" 2>nul
  xcopy /Y /I "archives\repo\*.json" "build\web\archives\repo\" >nul
  xcopy /Y /I "archives\repo\pkg\*.whl" "build\web\archives\repo\pkg\" >nul
)

echo.
echo  Ouvre http://localhost:%PORT%/   (PAS 127.0.0.1)
echo.
start "" "http://localhost:%PORT%/"
cd /d "%~dp0build\web"
python -m http.server %PORT% --bind 127.0.0.1
pause
exit /b 0
:fail
echo FAILED
pause
exit /b 1
