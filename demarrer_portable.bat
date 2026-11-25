@echo off
chcp 65001 >nul 2>&1
title Application AVA
cd /d "%~dp0"

set PYTHON=portable\python\python.exe

if not exist "%PYTHON%" (
    echo.
    echo Le dossier portable\python est introuvable.
    echo Verifiez que vous avez extrait tout le dossier telecharge depuis GitHub.
    echo.
    pause
    exit /b 1
)

echo.
echo Demarrage de l'application AVA...
echo NE FERMEZ PAS cette fenetre pendant l'utilisation.
echo Le premier demarrage peut prendre 15 a 30 secondes.
echo.

"%PYTHON%" lancer.py

echo.
echo Application arretee.
if exist ava.log (
    echo Un journal a ete enregistre : ava.log
    echo Detail :
    echo ------------------------------------------------------------
    type ava.log
    echo ------------------------------------------------------------
)
echo Faites une capture de cette fenetre et envoyez-la si besoin.
pause
