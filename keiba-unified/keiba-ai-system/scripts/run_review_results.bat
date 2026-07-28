@echo off
cd /d "G:\マイドライブ\YNFactory-cc\keiba-unified\keiba-ai-system"
set PYTHONPATH=.
set PYTHONIOENCODING=utf-8
chcp 65001 > nul 2>&1

REM 開催日チェック（非開催日はスキップ）
python scripts\check_race_day.py >> predictions\cron.log 2>&1
if errorlevel 1 exit /b 0

python scripts\review_results.py >> predictions\cron.log 2>&1
