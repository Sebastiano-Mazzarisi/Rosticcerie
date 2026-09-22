@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Rosticcerie: pubblica foto menu

rem =====================================================================
rem  Pubblica_Menu.bat
rem
rem  A cosa serve: quando inserisci a mano una foto del menu del giorno
rem  (dentro Menu\AAAA-MM-GG-Nome.jpg oppure local_menus\slug_AAAA-MM-GG.jpg),
rem  quel file resta solo sul tuo PC finche' non viene committato e pushato
rem  su GitHub: il sito pubblico e' generato da GitHub Actions, che legge
rem  il repository, non il tuo Dropbox. Questo script fa in automatico
rem  add + commit + pull + push solo per le cartelle Menu\ e local_menus\.
rem
rem  Come si usa: doppio clic su questo file dopo aver salvato la foto.
rem  Aspetta che la finestra dica "Fatto" prima di chiuderla.
rem  Entro ~10 minuti la prossima esecuzione automatica pubblica la foto
rem  sul sito.
rem =====================================================================

echo.
echo === Rosticcerie: pubblica foto menu manuali ===
echo Cartella: %cd%
echo.

git add Menu/ 2>nul
git add local_menus/ 2>nul

git diff --cached --quiet
if errorlevel 1 (
    for /f "tokens=1-4 delims=/ " %%a in ('date /t') do set OGGI=%%a-%%b-%%c
    for /f "tokens=1-2 delims=: " %%a in ('time /t') do set ORA=%%a.%%b
    git commit -m "Foto menu manuale del !OGGI! !ORA!"
) else (
    echo Nessuna foto nuova da committare: procedo comunque con pull/push,
    echo nel caso ci sia gia' un commit pronto ma non ancora pushato.
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
echo Fatto: foto committata e pushata su GitHub.
echo Entro ~10 minuti dovrebbe comparire sul sito.
pause
