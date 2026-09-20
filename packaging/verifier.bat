@echo off
rem  Verifie l empreinte SHA-256 du VoxCPMStudio.exe telecharge.
rem  Placez ce fichier (et verify_checksum.ps1, checksums.txt) dans le dossier
rem  du .exe, puis double-cliquez. Verifie tout fichier .exe du dossier.
setlocal EnableExtensions
cd /d "%~dp0"

where powershell >nul 2>nul
if errorlevel 1 (
  echo [X] PowerShell introuvable : verifiez votre installation de Windows.
  call :pause_maybe
  exit /b 1
)

set "TARGET="
for %%F in ("*.exe") do set "TARGET=%%F"
if not defined TARGET (
  echo [X] Aucun fichier .exe dans %CD%
  echo     Telechargez VoxCPMStudio.exe et checksums.txt depuis la release GitHub.
  call :pause_maybe
  exit /b 1
)

echo Fichier verifie : %TARGET%
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0verify_checksum.ps1" -Path "%TARGET%"
set "RC=%ERRORLEVEL%"
call :pause_maybe
exit /b %RC%

:pause_maybe
if "%CI%"=="" pause
goto :eof
