@echo off
REM JRA中央競馬 結果チェック（土日17:30）
cd /d "G:\マイドライブ\YNFactory-cc\keiba-unified\jra"
python "G:\マイドライブ\YNFactory-cc\keiba-unified\jra\scripts\check_results.py" >> "G:\マイドライブ\YNFactory-cc\keiba-unified\jra\data\reports\results.log" 2>&1
