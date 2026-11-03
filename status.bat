@echo off
setlocal
cd /d "F:\instagram_social_accounts_automation"

echo ====================================================================
echo   ETAT DU TRAITEMENT INSTAGRAM EN ARRIERE-PLAN
echo ====================================================================
echo.

powershell -NoProfile -Command "$procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*main.py*' -and $_.ProcessId -ne $PID }; if ($procs) { Write-Host 'ETAT : EN COURS D EXECUTION (ACTIF)' -ForegroundColor Green; foreach ($p in $procs) { Write-Host ('   PID : ' + $p.ProcessId) } } else { Write-Host 'ETAT : ARRETE (INACTIF)' -ForegroundColor Gray }; Write-Host ''; Write-Host '--- DERNIERES LIGNES DU JOURNAL ---' -ForegroundColor Cyan; if (Test-Path 'logs\background_service.log') { Get-Content 'logs\background_service.log' -Tail 15 } else { Write-Host '(Aucun journal pour le moment)' }"

echo.
pause
