@echo off
rem Lance Flux Remote sans fenetre de console.
cd /d "%~dp0"
if not exist "venv\Scripts\pythonw.exe" (
    echo Flux Remote n'est pas encore installe : double-cliquez d'abord sur installer.bat
    pause
    exit /b 1
)
rem Apres une mise a jour qui ajoute une dependance : installation automatique avant le lancement.
fc /b requirements.txt "venv\requirements.installe" >nul 2>&1 || (
    echo Mise a jour des composants de Flux Remote...
    "venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check -q && copy /y requirements.txt "venv\requirements.installe" >nul
)
start "" "venv\Scripts\pythonw.exe" "%~dp0flux_remote.py" %*
