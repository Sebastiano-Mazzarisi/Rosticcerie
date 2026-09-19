@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo === Rosticcerie: commit e push ===
echo Cartella: %cd%
echo.

git add -A

git diff --cached --quiet
if errorlevel 1 (
    set /p MSG="Messaggio di commit (invio per usarne uno automatico): "
    if "!MSG!"=="" set "MSG=Aggiornamento"
    git commit -m "!MSG!"
) else (
    echo Nessuna modifica da committare: procedo comunque con pull/push,
    echo nel caso ci siano commit gia' pronti ma non ancora pushati.
)

echo.
echo === git pull --rebase origin main ===
git pull --rebase origin main
if errorlevel 1 (
    echo.
    echo ATTENZIONE: il pull --rebase ha trovato un conflitto.
    echo Risolvilo a mano in questa cartella, poi rilancia questo file.
    pause
    exit /b 1
)

echo.
echo === git push ===
git push
if errorlevel 1 (
    echo Il push e' fallito ^(probabile nuovo commit automatico nel frattempo^): riprovo...
    git pull --rebase origin main
    git push
)

echo.
echo Fatto.
pause
