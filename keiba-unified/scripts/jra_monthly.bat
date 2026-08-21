@echo off
REM JRA中央競馬 月間サマリー（毎月1日10:00）
cd /d "G:\マイドライブ\YNFactory-cc\keiba-unified\jra"
python "G:\マイドライブ\YNFactory-cc\keiba-unified\jra\scripts\check_results.py" --monthly >> "G:\マイドライブ\YNFactory-cc\keiba-unified\jra\data\reports\monthly.log" 2>&1
