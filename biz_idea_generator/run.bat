@echo off
cd /d "G:\マイドライブ\YNFactory-cc\biz_idea_generator"

if not exist "logs" mkdir logs

echo ========================================>> logs\run.log
echo Starting execution at %date% %time% >> logs\run.log
"C:\Users\fcmdt\AppData\Local\Programs\Python\Python312\python.exe" main.py >> logs\run.log 2>&1
echo Finished execution at %date% %time% >> logs\run.log
