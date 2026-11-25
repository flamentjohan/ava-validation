@echo off
cd /d "%~dp0"

set PYTHON=portable\python\python.exe

if not exist "%PYTHON%" (
    echo.
    echo Le dossier portable\python est introuvable.
    echo Verifiez que vous avez bien extrait tout le dossier telecharge depuis GitHub.
    echo.
    pause
    exit /b 1
)

echo Demarrage de l'application AVA...
echo Le premier demarrage peut prendre 15 a 30 secondes (antivirus).
echo reduisez cette fenetre, le navigateur s'ouvrira tout seul.
echo.

start "AVA" /min cmd /c ""%PYTHON%" app.py > ava.log 2>&1"

set /a essais=0

:attendre
timeout /t 3 /nobreak >nul
powershell -NoProfile -Command "try{ $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5000 -TimeoutSec 3; if($r.StatusCode -eq 200){exit 0}else{exit 1} }catch{ exit 1 }" >nul 2>&1
if not errorlevel 1 goto ok

set /a essais+=1
if %essais% geq 10 goto echec
goto attendre

:ok
start "" http://127.0.0.1:5000
echo Application demarree : http://127.0.0.1:5000
echo Laissez cette fenetre ouverte pendant l'utilisation.
echo Pour arreter l'application, fermez la fenetre AVA (reduite) ou tapez Ctrl+C ici.
echo.
pause
exit /b 0

:echec
echo.
echo PROBLEME : l'application ne repond pas apres 30 secondes.
echo Le fichier ava.log contient le detail de l'erreur :
echo.
if exist ava.log type ava.log
echo.
echo Faites une capture d'ecran de cette fenetre et envoyez-la.
echo.
pause
exit /b 1
