@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Rosticcerie: aggiornamento automatico completo

echo.
echo =========================================================
echo  Rosticcerie - aggiornamento automatico  %date% %time%
echo =========================================================
echo.

rem ── 1. Storia di Aufer (Instagram) ───────────────────────
echo [1/4] Importo la storia di Aufer Gastronomia...
python ImportaStoriaAufer.py --once --no-git
if errorlevel 1 (
    echo   ATTENZIONE: Aufer non ha pubblicato una storia oggi o c'e' stato un errore.
) else (
    echo   OK: storia Aufer importata.
)
echo.

rem ── 2. Storia di Michela (Facebook) ──────────────────────
echo [2/4] Importo la storia di Le delizie di Michela...
python ImportaStoriaMichela.py --once --no-git
if errorlevel 1 (
    echo   ATTENZIONE: Michela non ha pubblicato una storia oggi o c'e' stato un errore.
) else (
    echo   OK: storia Michela importata.
)
echo.

rem ── 3. Menus Facebook + Pane&Co (Rosticceria.py) ─────────
echo [3/4] Scraping Facebook (Fantasia, Cibaria) e Pane e Co...
python Rosticceria.py --once --no-git
if errorlevel 1 (
    echo   ATTENZIONE: Rosticceria.py ha restituito un errore.
) else (
    echo   OK: menu Facebook e Pane e Co aggiornati.
)
echo.

rem ── 4. Commit e push di tutto ────────────────────────────
echo [4/4] Pubblico su GitHub...
call commit_e_push.bat
if errorlevel 1 (
    echo   ATTENZIONE: il push su GitHub e' fallito.
)

echo.
echo =========================================================
echo  Fine aggiornamento: %time%
echo =========================================================
echo.
