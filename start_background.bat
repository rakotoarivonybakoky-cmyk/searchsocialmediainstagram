@echo off
setlocal
cd /d "F:\instagram_social_accounts_automation"

set "APP_DIR=F:\instagram_social_accounts_automation"
set "PYTHON_EXE=%APP_DIR%\venv\Scripts\python.exe"

echo ====================================================================
echo   DEMARRAGE DU TRAITEMENT INSTAGRAM EN ARRIERE-PLAN
echo ====================================================================
echo.

powershell -NoProfile -Command "Start-Process -FilePath '%PYTHON_EXE%' -ArgumentList 'main.py --provider hybrid --resume' -WorkingDirectory '%APP_DIR%' -WindowStyle Hidden -RedirectStandardOutput '%APP_DIR%\logs\background_service.log' -RedirectStandardError '%APP_DIR%\logs\background_error.log'"

echo [SUCCES] Le robot a demarre en arriere-plan.
echo Verifiez l'etat avec status.bat
echo.
pause
