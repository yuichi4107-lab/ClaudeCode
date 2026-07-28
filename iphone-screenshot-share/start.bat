@echo off
REM iPhone screenshot share - receiver launcher
REM Requires Python 3.8+ on PATH. See README.md for setup (Japanese).
chcp 65001 >nul
cd /d "%~dp0"
if not exist config.json (
  echo [ERROR] config.json not found. Copy config.example.json to config.json and edit it.
  pause
  exit /b 1
)
python receiver.py
echo.
echo receiver stopped. Press any key to close.
pause >nul
