@echo off
rem ===========================================================================
rem  Flux Remote - installation (double-cliquer)
rem  Python, environnement, dependances (PySide6, cryptography), raccourci sur le bureau.
rem  Fonctionne sans winget. Peut etre relance sans risque (reparation / mise a jour).
rem ===========================================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Installation de Flux Remote
set "REDEMARRER="
echo.
echo   ==========================================
echo    Installation de Flux Remote
echo   ==========================================
echo.

rem ---------------------------------------------------------------------------
rem 1. Python 3.10 a 3.13 (3.12 de preference)
rem ---------------------------------------------------------------------------
set "PY="
for %%V in (3.12 3.11 3.13 3.10) do (
    py -%%V -c "import sys" >nul 2>&1 && (
        set "PY=py -%%V"
        goto py_ok
    )
)
python -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>&1 && (
    set "PY=python"
    goto py_ok
)
echo [1/5] Python 3.12 introuvable : installation...
where winget >nul 2>&1 && (
    winget install -e --id Python.Python.3.12 --scope user --silent --accept-source-agreements --accept-package-agreements
    echo.
    echo   Python vient d'etre installe. Fermez cette fenetre et relancez installer.bat.
    pause
    exit /b 0
)
echo       Telechargement de l'installateur officiel de Python 3.12...
call :telecharger "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" "%TEMP%\python-3.12-fluxremote.exe"
if errorlevel 1 goto pas_de_python
"%TEMP%\python-3.12-fluxremote.exe" /passive InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0
del /f /q "%TEMP%\python-3.12-fluxremote.exe" >nul 2>&1
echo.
echo   Python vient d'etre installe. Fermez cette fenetre et relancez installer.bat.
pause
exit /b 0

:pas_de_python
echo   Installez Python 3.12 depuis https://www.python.org/downloads/ en cochant
echo   "Add python.exe to PATH", puis relancez installer.bat.
pause
exit /b 1

:py_ok
for /f "tokens=2" %%P in ('%PY% --version 2^>^&1') do set "PYVER=%%P"
echo [1/5] Python %PYVER% trouve.

rem ---------------------------------------------------------------------------
rem 2. Environnement virtuel (recree s'il est casse)
rem ---------------------------------------------------------------------------
if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" -c "import sys" >nul 2>&1 || (
        echo [2/5] Environnement existant casse : recreation...
        rmdir /s /q venv
    )
)
if not exist "venv\Scripts\python.exe" (
    echo [2/5] Creation de l'environnement...
    %PY% -m venv venv
    if errorlevel 1 goto erreur
) else (
    echo [2/5] Environnement existant conserve.
)
set "VPY=%~dp0venv\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip --quiet --disable-pip-version-check
if errorlevel 1 goto erreur_reseau

rem ---------------------------------------------------------------------------
rem 3. Dependances (requirements.txt)
rem ---------------------------------------------------------------------------
echo [3/5] Installation des dependances (PySide6, cryptography)...
"%VPY%" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 goto erreur_reseau
copy /y requirements.txt "venv\requirements.installe" >nul

rem ---------------------------------------------------------------------------
rem 4. Verification (Visual C++ installe seulement s'il manque)
rem ---------------------------------------------------------------------------
echo [4/5] Verification...
call :verifier
if not errorlevel 1 goto verif_ok
echo       Qt ne demarre pas : installation de Microsoft Visual C++...
echo       Une fenetre Windows va demander l'autorisation : cliquez sur "Oui".
call :telecharger "https://aka.ms/vs/17/release/vc_redist.x64.exe" "%TEMP%\vc_redist.x64.exe"
if errorlevel 1 goto erreur_reseau
"%TEMP%\vc_redist.x64.exe" /install /passive /norestart
if "%errorlevel%"=="3010" set "REDEMARRER=1"
if "%errorlevel%"=="1641" set "REDEMARRER=1"
del /f /q "%TEMP%\vc_redist.x64.exe" >nul 2>&1
call :verifier
if errorlevel 1 if not defined REDEMARRER goto erreur
:verif_ok
echo       Tout est pret.

rem ---------------------------------------------------------------------------
rem 5. Raccourci sur le bureau
rem ---------------------------------------------------------------------------
echo [5/5] Raccourci sur le bureau...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$b=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $b 'Flux Remote.lnk')); $s.TargetPath='%~dp0FluxRemote.bat'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0ressources\flux-remote.ico'; $s.WindowStyle=7; $s.Description='Flux Remote - telecommande de Flux'; $s.Save()" >nul 2>&1

echo.
echo   ==========================================
echo    Installation terminee.
echo    Lancez Flux Remote avec le raccourci du bureau
echo    ou en double-cliquant sur FluxRemote.bat
echo   ==========================================
echo.
if defined REDEMARRER (
    echo   Windows demande un redemarrage pour terminer Visual C++ : redemarrez le PC avant de lancer Flux Remote.
    echo.
    pause
    exit /b 0
)
choice /c ON /n /m "Lancer Flux Remote maintenant ? (O/N) "
if errorlevel 2 exit /b 0
start "" "%~dp0FluxRemote.bat"
exit /b 0

:erreur_reseau
echo.
echo   Un telechargement a echoue. Verifiez la connexion Internet ^(et un eventuel proxy,
echo   pare-feu ou antivirus qui bloquerait Python^), puis relancez installer.bat.
pause
exit /b 1

:erreur
echo.
echo   L'installation s'est arretee sur une erreur ^(voir les lignes ci-dessus^).
echo   Corrigez-la ou relancez installer.bat.
pause
exit /b 1

rem ===========================================================================
rem Sous-programmes
rem ===========================================================================

:verifier
"%VPY%" -c "import PySide6.QtWidgets, PySide6.QtNetwork, cryptography.x509; import fluxremote.fenetre" 
exit /b %errorlevel%

:telecharger
rem %1 = adresse, %2 = fichier de destination. curl (Windows 10/11), sinon PowerShell.
del /f /q "%~2" >nul 2>&1
where curl >nul 2>&1 && curl -fsSL --retry 3 --connect-timeout 30 -o "%~2" "%~1" >nul 2>&1
call :non_vide "%~2" && exit /b 0
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri '%~1' -OutFile '%~2'" >nul 2>&1
call :non_vide "%~2" && exit /b 0
del /f /q "%~2" >nul 2>&1
exit /b 1

:non_vide
if not exist "%~1" exit /b 1
if %~z1 GTR 0 exit /b 0
exit /b 1
