@echo off
rem ==========================================================================
rem  VoxCPM Studio - Construction du .exe Windows (a executer sur un PC)
rem  Produit : dist\VoxCPMStudio.exe (application autonome, fenetre native).
rem  Prerequis : Python 3.10+ dans le PATH. Aucun droit administrateur requis.
rem
rem  Remarque : PyInstaller ne cross-compile pas -> ce script doit tourner
rem  sous Windows. Ensuite, copiez VoxCPMStudio.exe a cote du dossier gguf\
rem  (moteur C++ optionnel) : outputs\ et refs\ sont crees a cote du .exe.
rem
rem  Le bundle embarque la fenetre native et le serveur, PAS le moteur Python
rem  (torch/voxcpm exclus) : sur une machine sans PyTorch, l'application
rem  utilise le moteur C++ GGUF s'il est installe dans gguf\, et rejette
rem  proprement les modeles natifs sinon.
rem ==========================================================================
setlocal EnableExtensions
cd /d "%~dp0.."

where python >nul 2>nul
if errorlevel 1 (
  echo [Erreur] Python introuvable dans le PATH. Installez Python 3.10+ puis relancez.
  call :pause_maybe
  exit /b 1
)

echo [1/4] Installation des dependances de build...
python -m pip install --quiet --upgrade -r requirements.txt "pyinstaller>=6.11"
if errorlevel 1 goto :err

echo [2/4] Generation de l'icone (PNG maitre, puis .ico sans dependances)...
python packaging\make_icon.py build\iconset
if errorlevel 1 goto :err
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\png_to_ico.ps1 ^
  -Source "build\iconset\icon_512x512@2x.png" -Output "build\app.ico"
if errorlevel 1 goto :err

echo [3/4] Compilation PyInstaller (2 a 5 minutes)...
rem  torch/voxcpm/numpy/etc. sont exclus : le bundle n'embarque pas le moteur
rem  Python (modeles telecharges a part, GGUF recommande sans PyTorch).
rem  clr_loader/pythonnet collectes explicitement (backend WebView2 de pywebview).
python -m PyInstaller --noconfirm --clean --onefile --console ^
  --name "VoxCPMStudio" ^
  --icon "build\app.ico" ^
  --add-data "web;web" ^
  --collect-all webview ^
  --collect-all clr_loader ^
  --collect-all pythonnet ^
  --hidden-import webview.platforms.winforms ^
  --exclude-module torch ^
  --exclude-module voxcpm ^
  --exclude-module numpy ^
  --exclude-module soundfile ^
  --exclude-module lameenc ^
  desktop.py
if errorlevel 1 goto :err

echo [4/4] Termine.
echo   Executable : dist\VoxCPMStudio.exe
echo   Pour le moteur C++ GGUF : placez voxcpm2-cli.exe et les .gguf dans
echo   gguf\bin\ et gguf\models\ a cote du .exe.
echo   (Variante silencieuse : ajoutez --noconsole a la commande PyInstaller.)
call :pause_maybe
exit /b 0

:err
echo.
echo [Erreur] La construction a echoue. Verifiez les messages ci-dessus.
call :pause_maybe
exit /b 1

:pause_maybe
rem  Pause interactive seulement hors CI (GitHub Actions definissent CI=true).
if "%CI%"=="" pause
goto :eof
