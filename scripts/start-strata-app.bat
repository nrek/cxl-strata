@echo off
setlocal EnableExtensions
REM Restart local STRATA workspace UI (cxl-strata) as a daemon.
REM Default listen port: 8765  (override: start-strata-app.bat 8766)

set "PORT=%~1"
if "%PORT%"=="" set "PORT=8765"

REM This file lives in cxl-strata\scripts\ → workspace root is ..\..
set "WORKSPACE=%~dp0..\.."
for %%I in ("%WORKSPACE%") do set "WORKSPACE=%%~fI"

echo.
echo === STRATA app restart ===
echo Workspace: %WORKSPACE%
echo Port:      %PORT%
echo.

echo [1/2] Clearing listeners on port %PORT%...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$conns = Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue;" ^
  "if (-not $conns) { Write-Host '  No LISTENING process on port %PORT%.'; exit 0 }" ^
  "$pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique;" ^
  "foreach ($procId in $pids) {" ^
  "  if ($procId -and $procId -ne 0) {" ^
  "    Write-Host ('  taskkill /F /PID ' + $procId);" ^
  "    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue" ^
  "  }" ^
  "}"
timeout /t 1 /nobreak >nul

echo [2/2] Starting strata app --daemon...
cd /d "%WORKSPACE%"
where strata >nul 2>&1
if errorlevel 1 (
  echo   strata not on PATH — using python -m cxl_strata.cli
  python -m cxl_strata.cli app --daemon --host 127.0.0.1 --port %PORT% --root "%WORKSPACE%"
) else (
  strata app --daemon --host 127.0.0.1 --port %PORT% --root "%WORKSPACE%"
)

if errorlevel 1 (
  echo.
  echo FAILED to start STRATA app.
  echo Check: python -m pip show cxl-strata
  exit /b 1
)

echo.
echo STRATA app daemon should be at http://127.0.0.1:%PORT%
echo Optional: strata app --open
echo.
endlocal
exit /b 0
