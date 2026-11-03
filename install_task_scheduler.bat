@echo off
chcp 65001 > nul
setlocal

:: Demander l'élévation administrateur si nécessaire
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [INFO] Cette opération nécessite les droits administrateur.
    echo Demande d'élévation en cours...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

set "TASK_NAME=InstagramAutomationService"
set "APP_DIR=F:\instagram_social_accounts_automation"
set "PYTHON_EXE=%APP_DIR%\venv\Scripts\python.exe"

echo ====================================================================
echo   INSTALLATION DANS LE PLANIFICATEUR DE TÂCHES WINDOWS
echo ====================================================================
echo.
echo Nom de la tâche : %TASK_NAME%
echo Dossier         : %APP_DIR%
echo Déclencheur     : Démarrage de la machine (au boot ou à la connexion)
echo Redémarrage     : Automatique en cas de panne
echo.

:: Supprimer la tâche existante si déjà présente
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1

:: Créer la nouvelle tâche planifiée
:: Lance python.exe avec les arguments --provider hybrid --resume
schtasks /create /tn "%TASK_NAME%" ^
  /tr "\"%PYTHON_EXE%\" main.py --provider hybrid --resume" ^
  /sc onlogon ^
  /rl highest ^
  /f

if %errorlevel% equ 0 (
    echo.
    echo [SUCCÈS] La tâche planifiée "%TASK_NAME%" a été créée avec succès !
    echo.
    echo Le robot démarrera automatiquement à chaque ouverture de session Windows.
    echo Vous pouvez également la piloter depuis l'outil "Planificateur de tâches" de Windows (taskschd.msc).
) else (
    echo.
    echo [ERREUR] Échec de la création de la tâche planifiée.
)

echo.
pause
