@echo off
REM Schedule the task to run daily at 7:00 AM
echo Scheduling Business Idea Generator...
schtasks /create /tn "BizIdeaGenerator" /tr "c:\Users\fcmdt\.gemini\antigravity\scratch\biz_idea_generator\run.bat" /sc daily /st 06:00
if %errorlevel% neq 0 (
    echo Failed to create task. You might need to run as Administrator.
) else (
    echo Task 'BizIdeaGenerator' created successfully.
)
pause
