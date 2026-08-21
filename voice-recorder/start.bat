@echo off
rem ============================================================
rem  Voice Recorder launcher (ASCII only to avoid CP932 issues)
rem  Double-click this file to start the app.
rem ============================================================
cd /d "%~dp0"
set "PORT=8765"

rem --- detect runtime: py -> python -> node ---
set "RUNTIME="
where py >nul 2>nul && set "RUNTIME=py -m http.server %PORT%"
if not defined RUNTIME (where python >nul 2>nul && set "RUNTIME=python -m http.server %PORT%")
if not defined RUNTIME (where node >nul 2>nul && set "RUNTIME=npx --yes http-server -p %PORT% -c-1")

if not defined RUNTIME (
  echo [ERROR] Python or Node.js was not found.
  echo Please install Python: https://www.python.org/downloads/
  echo During installation, check "Add python.exe to PATH".
  echo.
  pause
  exit /b 1
)

echo ==================================================
echo   Voice Recorder
echo   URL : http://localhost:%PORT%/
echo   A separate "server" window will open.
echo   Close THAT server window to stop the app.
echo ==================================================
echo.
echo Starting the server window...

rem --- run the server in its own window (stays open / shows errors) ---
start "Voice Recorder Server - close this window to stop" cmd /k "%RUNTIME%"

rem --- wait a moment, then open the default browser ---
timeout /t 2 /nobreak >nul
start "" http://localhost:%PORT%/

echo.
echo Browser opened at http://localhost:%PORT%/
echo If the tab shows a connection error, wait 1-2 seconds and reload.
echo You can close THIS launcher window (keep the server window open).
echo.
pause
