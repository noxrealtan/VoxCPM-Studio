@echo off
rem ==========================================================================
rem  VoxCPM Studio - Lanceur Windows 10/11
rem  Double-cliquez sur ce fichier : tout s'installe automatiquement au
rem  premier lancement (Python 3.12 via uv, dependances, moteur VoxCPM).
rem ==========================================================================
setlocal EnableExtensions
chcp 65001 >nul
title VoxCPM Studio
cd /d "%~dp0"

set "BASE=%LocalAppData%\VoxCPMStudio"
set "UV_DIR=%BASE%\uv"
set "VENV_DIR=%BASE%\venv"
set "UV=%UV_DIR%\uv.exe"
set "PATH=%UV_DIR%;%PATH%"

if not exist "%UV_DIR%" mkdir "%UV_DIR%"

rem --- 1/3 : uv (gestionnaire Python autonome, aucun droit admin requis) ----
if exist "%UV%" goto :have_uv
where uv >nul 2>nul
if errorlevel 1 goto :install_uv
for /f "delims=" %%i in ('where uv') do set "UV=%%i"
echo [VoxCPM Studio] uv deja installe sur ce systeme.
goto :have_uv

:install_uv
echo [VoxCPM Studio] 1/3 - Telechargement de l'environnement Python (uv)...
curl -fsSL -o "%UV_DIR%\uv.zip" https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip
if errorlevel 1 goto :err
if not exist "%UV_DIR%\uv.zip" goto :err
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Force '%UV_DIR%\uv.zip' '%UV_DIR%'"
del "%UV_DIR%\uv.zip" >nul 2>nul
if not exist "%UV%" goto :err

:have_uv
rem --- 2/3 : environnement virtuel Python 3.12 ------------------------------
if exist "%VENV_DIR%\Scripts\python.exe" goto :have_venv
echo [VoxCPM Studio] 2/3 - Preparation de Python 3.12 (telecharge automatiquement si besoin)...
"%UV%" venv --python 3.12 "%VENV_DIR%"
if errorlevel 1 goto :err

:have_venv
rem --- 3/3 : dependances + moteur VoxCPM ------------------------------------
echo [VoxCPM Studio] 3/3 - Verification des composants (2 a 5 minutes au premier lancement, puis instantane)...
"%UV%" pip install --python "%VENV_DIR%\Scripts\python.exe" -r requirements.txt
if errorlevel 1 goto :err

echo [VoxCPM Studio] Demarrage...
rem Fenetre native (WebView2) ; bascule automatique sur le navigateur si indisponible.
"%VENV_DIR%\Scripts\python.exe" desktop.py
goto :eof

:err
echo.
echo [Erreur] L'installation a echoue. Verifiez votre connexion Internet
echo et relancez ce fichier. Les messages ci-dessus indiquent la cause.
pause
