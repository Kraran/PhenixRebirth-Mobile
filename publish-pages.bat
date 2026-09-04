@echo off
setlocal
cd /d "%~dp0"
echo === pack pygbag ===
if exist "assets\music\*.mp3" move /Y "assets\music\*.mp3" "%TEMP%\phenix-audio-pc\" >nul 2>&1
if exist "assets\sounds\*.wav" move /Y "assets\sounds\*.wav" "%TEMP%\phenix-audio-pc\" >nul 2>&1
python -m pip install "pygbag==0.9.2" >nul
if exist build rd /s /q build
python -m pygbag --build --PYBUILD 3.11 --ume_block 0 --cdn https://pygame-web.github.io/archives/0.8/ --version 0.8 --title "Phenix Rebirth Mobile" --app_name phenixrebirth --package org.kraran.phenixrebirth.mobile --width 1280 --height 720 .
if errorlevel 1 goto fail
if not exist "build\web\index.html" goto fail
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0patch-index.ps1"
echo. > "build\web\.nojekyll"
if exist "archives\repo\pkg\*.whl" (
  mkdir "build\web\archives\repo\pkg" 2>nul
  xcopy /Y /I "archives\repo\*.json" "build\web\archives\repo\" >nul
  xcopy /Y /I "archives\repo\pkg\*.whl" "build\web\archives\repo\pkg\" >nul
)

echo === push gh-pages ===
cd /d "%~dp0build\web"
if exist .git rd /s /q .git
git init -b gh-pages
git add -A
git -c user.email="pages@phenixrebirth.local" -c user.name="Phenix Pages" commit -m "gh-pages 1.1.0-mobile.1"
git remote add origin git@github.com:Kraran/PhenixRebirth-Mobile.git
git push -f origin gh-pages
if errorlevel 1 (
  echo Echec SSH. Essaie:
  echo   git remote set-url origin https://github.com/Kraran/PhenixRebirth-Mobile.git
  echo   git push -f origin gh-pages
  pause
  exit /b 1
)
cd /d "%~dp0"
echo.
echo  Pages: https://kraran.github.io/PhenixRebirth-Mobile/
echo  GitHub → Settings → Pages → branche gh-pages / root
pause
exit /b 0
:fail
echo PACK FAILED
pause
exit /b 1
