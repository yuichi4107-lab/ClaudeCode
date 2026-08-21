@echo off
REM JRA中央競馬 ライブモード（土日9:30）
cd /d "G:\マイドライブ\YNFactory-cc\keiba-unified\jra"
python "G:\マイドライブ\YNFactory-cc\keiba-unified\jra\scripts\run_live.py" >> "G:\マイドライブ\YNFactory-cc\keiba-unified\jra\data\reports\live.log" 2>&1
