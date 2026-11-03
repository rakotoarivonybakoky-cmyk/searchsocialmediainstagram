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

echo ====================================================================
echo   DÉSINSTALLATION DE LA TÂCHE PLANIFIÉE WINDOWS
echo ====================================================================
echo.

schtasks /delete /tn "%TASK_NAME%" /f

if %errorlevel% equ 0 (
    echo.
    echo [SUCCÈS] La tâche planifiée "%TASK_NAME%" a été retirée du système.
) else (
    echo.
    echo [INFO] La tâche n'existait pas ou a déjà été retirée.
)

echo.
pause
