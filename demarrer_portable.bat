@echo off
cd /d "%~dp0"

if not exist "portable\python\python.exe" (
    echo.
    echo Le dossier portable\python est introuvable.
    echo Verifiez que vous avez bien extrait tout le dossier telecharge depuis GitHub.
    echo.
    pause
    exit /b 1
)

echo Demarrage de l'application AVA (sans installation necessaire)...
start "" cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:5000"

"portable\python\python.exe" app.py

echo.
echo L'application s'est arretee.
pause
