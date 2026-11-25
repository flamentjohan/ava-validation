@echo off
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo Python n'est pas installe ou n'est pas dans le PATH.
    echo Installez Python depuis https://www.python.org/downloads/
    echo en cochant la case "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

echo Verification des composants (premiere fois uniquement)...
pip install -r requirements.txt >nul 2>&1

echo Demarrage de l'application AVA...
start "" cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:5000"

python app.py

echo.
echo L'application s'est arretee.
pause
