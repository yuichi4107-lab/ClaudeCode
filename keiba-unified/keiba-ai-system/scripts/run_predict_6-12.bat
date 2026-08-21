@echo off
cd /d "G:\マイドライブ\YNFactory-cc\keiba-unified\keiba-ai-system"
set PYTHONPATH=.
set PYTHONIOENCODING=utf-8
chcp 65001 > nul 2>&1

REM 開催日チェック＋実行タイミングチェック（非開催日・時刻不一致はスキップ）
python scripts\check_race_day.py --half second >> predictions\cron.log 2>&1
if errorlevel 1 exit /b 0

python scripts\daily_predict.py --race-from 6 --race-to 12 >> predictions\cron.log 2>&1
