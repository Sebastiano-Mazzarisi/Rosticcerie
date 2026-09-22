@echo off
setlocal
cd /d "%~dp0"
title Rosticcerie: pulizia file inutili

echo.
echo === Rosticcerie: pulizia file inutili ===
echo Cartella: %cd%
echo.

python Pulisci_Repository.py --applica

echo.
pause
