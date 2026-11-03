@echo off
setlocal
cd /d "F:\instagram_social_accounts_automation"

echo ====================================================================
echo   ARRET DU TRAITEMENT INSTAGRAM EN ARRIERE-PLAN
echo ====================================================================
echo.

powershell -NoProfile -Command "$procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*main.py*' -and $_.ProcessId -ne $PID }; if (-not $procs) { Write-Host 'Aucun processus actif trouve.' -ForegroundColor Yellow } else { foreach ($p in $procs) { Write-Host ('Arret du PID : ' + $p.ProcessId); Stop-Process -Id $p.ProcessId -Force }; Write-Host 'Traitement arrete avec succes.' -ForegroundColor Green }"

echo.
pause
