@echo off
title Phenix Rebirth
cd /d "%~dp0"

echo.
echo  ========================================
echo         PHENIX REBIRTH - Launch
echo  ========================================
echo.

:: Test if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERREUR] Python n'est pas installe ou pas dans le PATH.
    echo  Telecharge Python ici : https://www.python.org/downloads/
    echo  Coche bien "Add Python to PATH" pendant l'installation.
    echo.
    pause
    exit /b 1
)

:: Try to run the game
python -c "import pygame" >nul 2>&1
if errorlevel 1 (
    echo  Pygame n'est pas installe.
    echo.
    echo  Installation automatique en cours...
    echo.
    python -m pip install --upgrade pip
    python -m pip install pygame
    echo.
    if errorlevel 1 (
        echo  [ERREUR] L'installation a echoue.
        echo  Essaie manuellement : python -m pip install pygame
        echo.
        pause
        exit /b 1
    )
    echo  Pygame installe avec succes !
    echo.
)

echo  Lancement du jeu...
echo.
python main.py
set EXITCODE=%ERRORLEVEL%

if %EXITCODE% NEQ 0 (
    echo.
    echo  [ERREUR] Le jeu a plante.
    echo  Envoie-moi le message d'erreur complet.
    echo.
    pause
    exit /b %EXITCODE%
)

:: Sortie propre (menu Quitter) : fermer sans "Appuyez sur une touche"
exit /b 0
