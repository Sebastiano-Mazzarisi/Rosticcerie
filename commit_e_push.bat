@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Rosticcerie: commit e push

echo.
echo === Rosticcerie: commit e push ===
echo Cartella: %cd%
echo.

git add -A

git diff --cached --quiet
if errorlevel 1 (
    for /f "tokens=1-4 delims=/ " %%a in ('date /t') do set OGGI=%%a-%%b-%%c
    for /f "tokens=1-2 delims=: " %%a in ('time /t') do set ORA=%%a.%%b
    git commit -m "Aggiornamento del !OGGI! !ORA!"
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
    if errorlevel 1 (
        echo.
        echo ATTENZIONE: il push continua a fallire. Controlla manualmente.
        pause
        exit /b 1
    )
)

echo.
echo Fatto: tutto committato e pushato.
timeout /t 4 >nul
